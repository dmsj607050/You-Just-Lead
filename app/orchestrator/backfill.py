"""Backfill the research state from experiment records that already exist.

把 `experiments/manifests/EXP-*.json` 与 `experiments/results/EXP-*.json` 读成研究状态，
让"已经在跑的实验史"接进 EGRL，而不是要求一切从头开始。

**回填刻意不补记录里没有的东西。** 现有 manifest 的 `hypothesis` 只有一句话，既没有
预测也没有反证条件 —— 那回填出来的假设就是不可证伪的，`is_falsifiable()` 直接为假；
现有记录里没有 `baseline`，那 `metric_improved` 就是 `None` 而不是 `False`。

把缺的字段编出来（"我猜它大概想验证 X"）会让入口看起来漂亮，但那是伪造科研意图，
比缺字段坏得多。缺字段本身就是要暴露的结论。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.orchestrator.state import ResearchState
from schemas.research import Evidence, Experiment, Hypothesis, ResearchBranch
from tools.files import read_json


MANIFEST_DIRECTORY = ("experiments", "manifests")
RESULT_DIRECTORY = ("experiments", "results")
JOB_DIRECTORY = ("experiments", "jobs")


def _records(workspace: Path, parts: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    """按实验号读一组记录。缺目录返回空字典，不报错。"""
    directory = Path(workspace).joinpath(*parts)
    if not directory.is_dir():
        return {}
    found: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("EXP-*.json")):
        payload = read_json(path)
        if isinstance(payload, dict) and payload.get("experiment_id"):
            found[str(payload["experiment_id"])] = payload
    return found


def _approved_run_links(workspace: Path, state: ResearchState) -> dict[str, str]:
    """训练实验号 → 研究层那次设计的假设。

    批准执行时，研究层的 `Experiment.run_id` 记下的是**作业号**；而作业文件里记着
    这个作业跑出来的**训练实验号**。这两个对上了，才能把"这次设计"和"那次运行"
    挂在同一条假设下。

    不做这一步会怎样（真实撞到过）：每次跑完训练，回填就会从 manifest 的假设文本
    再**新编一条**假设，而证据被挂到那条重复的假设上 —— 于是"据此改进"改的是那条
    重复的假设，而不是当初被批准执行的那一条，研究图越跑越糊。
    """
    jobs_dir = Path(workspace).joinpath(*JOB_DIRECTORY)
    by_run_id = {
        str(item.run_id): item.hypothesis_id
        for item in state.experiments.values()
        if item.run_id and item.hypothesis_id in state.hypotheses
    }
    if not by_run_id or not jobs_dir.is_dir():
        return {}
    links: dict[str, str] = {}
    for path in sorted(jobs_dir.glob("JOB-*.json")):
        job = read_json(path)
        if not isinstance(job, dict):
            continue
        experiment_id = str(job.get("experiment_id") or "").strip()
        hypothesis_id = by_run_id.get(str(job.get("job_id") or "").strip())
        if experiment_id and hypothesis_id:
            links[experiment_id] = hypothesis_id
    return links


def _controls_from(manifest: dict[str, Any]) -> list[str]:
    """能从记录里读出来的控制变量。

    只收记录里确有其值的字段（数据版本、随机种子）。参数量、训练步数这类
    "其余都没动"的证据，现有 manifest 里根本没有，所以不编。
    """
    controls: list[str] = []
    data_version = str(manifest.get("data_version") or "").strip()
    if data_version:
        controls.append(f"data_version={data_version}")
    seed = manifest.get("seed")
    if seed is not None:
        controls.append(f"seed={seed}")
    return controls


def backfill_state(workspace: Path, *, state: ResearchState | None = None, persist: bool = False) -> ResearchState:
    """把已有实验记录回填进研究状态。

    同一句话的假设只建一条：现有 6 条实验里有多条在试同一件事，那不是 6 个假设，
    是一个假设的 6 次尝试 —— 这个区分正是研究图要表达的。
    """
    workspace = Path(workspace)
    current = state if state is not None else ResearchState.load(workspace)
    manifests = _records(workspace, MANIFEST_DIRECTORY)
    results = _records(workspace, RESULT_DIRECTORY)
    # 由研究层批准跑出来的训练，直接挂回那次设计的假设；只有"来历不明"的训练
    # （人手跑的、或者批准记录丢了）才按 manifest 的文本另建一条。
    approved = _approved_run_links(workspace, current)

    hypothesis_ids: dict[str, str] = {}
    for experiment_id in sorted(set(manifests) | set(results)):
        if experiment_id in current.experiments:
            # 回填必须幂等：已经进来的实验不再建第二条假设、实验与证据。
            # 否则每调一次回填，状态里就多出一整套重复条目，界面计数也跟着翻倍。
            continue
        manifest = manifests.get(experiment_id, {})
        result = results.get(experiment_id, {})

        hypothesis_id = approved.get(experiment_id)
        if hypothesis_id is None:
            statement = str(manifest.get("hypothesis") or "").strip()
            if not statement:
                # 没有假设就没有科研可言：这条记录能回填的只有"跑过一次"这个事实。
                statement = f"(未记录假设的实验 {experiment_id})"

            hypothesis_id = hypothesis_ids.get(statement)
            if hypothesis_id is None:
                hypothesis_id = current.new_id("hypothesis")
                current.add_hypothesis(Hypothesis(hypothesis_id=hypothesis_id, statement=statement))
                current.add_branch(
                    ResearchBranch(branch_id=current.new_id("branch"), hypothesis_id=hypothesis_id)
                )
                hypothesis_ids[statement] = hypothesis_id

        experiment = Experiment(
            experiment_id=experiment_id,
            hypothesis_id=hypothesis_id,
            # 记录里没有"这次实验在区分什么"这个字段，留空而不是拿 expected_improvement 顶替。
            question="",
            # 记录里没有 baseline 字段 —— 这正是"结果无法归因"的根因，如实留空。
            baseline="",
            independent=str(manifest.get("change_type") or "").strip(),
            controlled=_controls_from(manifest),
            metrics=list((result.get("metrics") or {}).keys()),
            success_condition="",
            artifacts=[str(item) for item in (result.get("artifact_paths") or [])],
        )
        current.add_experiment(experiment)

        if not result:
            continue

        status = str(result.get("status") or "")
        current.record_evidence(
            Evidence(
                evidence_id=current.new_id("evidence"),
                experiment_id=experiment_id,
                # 九项核查里只有"跑没跑成"能从记录读出来，其余八项当时没人查 —— 留 None，
                # 不能被当成"查了、不合格"。这是"没查"与"不合格"必须分开的地方。
                ran_successfully=(status == "completed"),
                notes=f"backfilled from experiments/results/{experiment_id}.json (status={status})",
            )
        )

    if persist:
        current.save(workspace)
    return current


__all__ = ["MANIFEST_DIRECTORY", "RESULT_DIRECTORY", "backfill_state"]
