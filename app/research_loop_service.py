"""研究循环的服务层：把 EGRL 编排层接到 HTTP 上。

编排层本身是纯函数加数据类（`policy` 只读状态、`validator` 只判证据），没有进程概念。
这里补三件它做不了的事：

1. **持有状态**：按工作区缓存一份 `ResearchState`。每次请求都从实验记录重新回填的话，
   刚由模型推出来的假设与证据会被磁盘上的旧记录覆盖掉；
2. **后台推进**：一步可能跑满多轮模型调用（每轮几十秒），同步返回必然读超时，
   所以走作业模式 —— 与 `data-audit/run`、训练作业的 202 + 轮询一致；
3. **注入执行器**：给了执行器循环才会真的干活；没给就停在 `deferred`，那是设计边界不是故障。

同一个工作区不允许两个循环同时改状态（会互相覆盖），提交时发现有作业在跑就直接拒绝。
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.account_service import UsageMeter
from app.orchestrator.backfill import backfill_state
from app.orchestrator.executor import ResearchExecutor
from app.orchestrator.loop import run as run_loop
from app.orchestrator.policy import decide_next_action
from app.orchestrator.state import ResearchState
from schemas.research import CHECK_FIELDS, Evidence, Hypothesis, ResearchBranch
from tools.files import write_json_atomic
from tools.provenance import utc_now


# 内存里保留的最近作业数。作业是"这一次推进"的过程记录，历史价值由账本与状态文件承担。
JOB_HISTORY_LIMIT = 20

# 一次提交最多推进几步。给上限是因为每一步都要真调模型，跑飞了要有人能按住。
MAX_STEPS_PER_JOB = 6


def hypothesis_payload(item: Hypothesis) -> dict[str, Any]:
    """一条假设 + 它的可证伪判定。

    "可证伪"的判据（既写了预测、又写了反证条件）只在 `Hypothesis.is_falsifiable()` 里
    写一次。让两个前端各自再实现一遍这条判断，就多出两个实现漂移的机会 —— 而界面上
    "不可证伪"标错属于最难查的那类问题：两边看起来都"有道理"。
    """
    payload = item.to_dict()
    payload['falsifiable'] = item.is_falsifiable()
    return payload


def evidence_payload(item: Evidence) -> dict[str, Any]:
    """一条证据 + 它九项核查的**逐项取值**，成对发出。

    为什么要把取值配成 `[{"name": ..., "value": ...}]` 而不是只发字段：端侧（ArkTS）
    没有反射，想按名字取字段就得把九个名字抄进端侧源码 —— 那就等于契约有了第二份定义，
    后端将来加第十项时端侧会静默地少显示一项。名字与顺序仍然只来自契约
    （`GET /api/research/contract` 的 checks），这里只负责把"查到了什么"配上对。
    """
    payload = item.to_dict()
    payload['checks'] = [{'name': name, 'value': getattr(item, name)} for name in CHECK_FIELDS]
    return payload


class ResearchLoopError(RuntimeError):
    """循环层面的冲突：已有作业在跑，或正在推进时被要求回填。

    单独一个类型是为了让接口层能把它映射成 409（冲突），而不是混进 500 里 ——
    "现在不能做"和"坏了"是两件事。
    """


@dataclass
class LoopJob:
    """一次推进作业。"""

    job_id: str
    status: str  # running / completed / failed
    started_at: str
    max_steps: int
    finished_at: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    stopped_because: str = ""
    # 登记下来、等人批准的动作。它们不阻塞其他路线，但必须显示出来 ——
    # 否则"循环停了"看起来像"没事可做"，而实际是"有事等你拍板"。
    pending_approvals: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResearchLoopService:
    """一个工作区一份：持有研究状态，并按需在后台推进循环。"""

    def __init__(
        self,
        project_root: Path,
        workspace: Path,
        *,
        executor_factory: Callable[[], Any] | None = None,
        usage_meter: UsageMeter | None = None,
    ):
        """`executor_factory` 只给测试用：默认的执行器会真调模型。

        这一步不做成"给个假的就跳过推进"，因为推进本身才是这个类要保证的东西 ——
        要用假的换掉的是**模型调用**，不是流程。
        """
        self.project_root = Path(project_root).resolve()
        self.workspace = Path(workspace).resolve()
        self._state: ResearchState | None = None
        self._jobs: list[LoopJob] = []
        self._running_job: str | None = None
        self._lock = threading.Lock()
        self._job_counter = 0
        self._usage_meter = usage_meter
        self._executor_factory = executor_factory or (
            lambda: ResearchExecutor(project_root=self.project_root, usage_meter=self._usage_meter)
        )

    def bind_usage_meter(self, usage_meter: UsageMeter) -> None:
        """把按用户计量绑定到已缓存的工作区服务（通常它先被只读快照创建）。"""
        with self._lock:
            self._usage_meter = usage_meter

    def _next_job_id(self) -> str:
        """作业号。

        只用秒级时间戳会碰撞：同一秒内提交两次会得到同一个 id，而按 id 查作业返回的是
        先建的那个 —— 调用方于是看到"新作业已经跑完了"。加自增序号把这件事变成不可能。
        """
        self._job_counter += 1
        stamp = utc_now()[:19].replace("-", "").replace(":", "")
        return f"LOOP-{stamp}-{self._job_counter:03d}"

    # ------------------------------------------------------------------ 状态

    def _loaded_state(self) -> ResearchState:
        """已加载的研究状态。**调用方必须已持有 `self._lock`。**

        单独拆出来是因为 `threading.Lock` 不可重入：持锁的方法里再调 `state()`
        会直接死锁，而这类死锁只在真正并发时才现形，测试里根本撞不到。
        """
        if self._state is None:
            self._state = backfill_state(self.workspace)
        return self._state

    def state(self) -> ResearchState:
        """当前研究状态。第一次访问时从实验记录回填，之后以内存这份为准。"""
        with self._lock:
            return self._loaded_state()

    def backfill(self, *, rebuild: bool = False) -> dict[str, Any]:
        """把已有实验记录接进研究状态。

        `rebuild=True` 时丢掉内存里这份重新来（磁盘上的 `state.json` 仍是起点，
        所以模型此前推出的假设不会因此消失）；否则沿用已加载的状态，只是把新出现的
        实验补进去 —— 回填是幂等的。
        """
        with self._lock:
            if self._running_job is not None:
                raise ResearchLoopError("循环正在推进，此时不要回填")
            self._state = backfill_state(self.workspace, state=None if rebuild else self._state)
            self._state.save(self.workspace)
            return self.snapshot_locked()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self.snapshot_locked()

    def snapshot_locked(self) -> dict[str, Any]:
        """给界面看的全貌。

        `next_action` 是**预测**不是执行：`decide_next_action` 只读状态，所以界面可以
        显示"编排器下一步打算做什么、为什么"，而不会真的推进任何东西。
        """
        state = self._loaded_state()
        # 顺手把新出现的实验记录接进来。训练是异步的：跑完之后没有谁去通知编排层
        # "有新结果了"，而界面轮询的这一刻正好是最该知道的时候。回填是幂等的，
        # 所以重复调用只是重读几个小 JSON。
        state = backfill_state(self.workspace, state=state)
        prediction: dict[str, Any] | None = None
        try:
            prediction = decide_next_action(state).to_dict()
        except Exception as error:  # noqa: BLE001 - 预测失败不该让整个快照失败
            prediction = {"action": "unavailable", "reason": f"无法预测下一步：{error}"}

        return {
            "summary": state.summary(),
            "hypotheses": [hypothesis_payload(item) for item in state.hypotheses.values()],
            "experiments": [asdict(item) for item in state.experiments.values()],
            "evidence": [evidence_payload(item) for item in state.latest_evidence()],
            "branches": [asdict(item) for item in state.branches.values()],
            "decisions": [item.to_dict() for item in state.decisions[-30:]],
            "edges": [asdict(item) for item in state.edges[-200:]],
            "next_action": prediction,
            "running": self._running_job,
            "jobs": [item.to_dict() for item in self._jobs[-5:]][::-1],
        }

    # ------------------------------------------------------------------ 执行

    def add_hypothesis(
        self,
        *,
        statement: str,
        predictions: list[str],
        falsifiers: list[str],
        rationale: list[str] | None = None,
    ) -> dict[str, Any]:
        """人直接提出一条假设。

        EGRL 里假设可以来自文献、模型，也可以来自人 —— 而这个项目的定位正是"人主导"。
        关键是：**人写进来的假设与模型提的走同一套判据**。没有预测和反证条件，编排器
        一样会把它打回补全，不会因为"是人写的"就放行 —— 否则人就成了一条绕过门控的捷径。
        """
        text = str(statement or "").strip()
        if len(text) < 8:
            # 输入不合法是 400（ValueError），不是 409 那种"现在不能做"的冲突。
            raise ValueError("假设至少要写清一句话（8 个字符以上）")
        with self._lock:
            state = self._loaded_state()
            hypothesis = Hypothesis(
                hypothesis_id=state.new_id("hypothesis"),
                statement=text,
                rationale=[str(item).strip() for item in (rationale or []) if str(item).strip()],
                predictions=[str(item).strip() for item in predictions if str(item).strip()],
                falsifiers=[str(item).strip() for item in falsifiers if str(item).strip()],
            )
            state.add_hypothesis(hypothesis)
            state.add_branch(
                ResearchBranch(branch_id=state.new_id("branch"), hypothesis_id=hypothesis.hypothesis_id)
            )
            state.save(self.workspace)
            return hypothesis.to_dict()

    def executable(self, experiment_id: str) -> tuple[bool, str]:
        """这次设计能不能真的跑起来。

        "写进 JSON 的路径"和"真的存在那个文件"是两件事，只有后者能跑。先问清楚，
        而不是把作业排上去再让它失败 —— 一个注定失败的任务会污染作业历史，
        而且会让人以为"实验跑了、只是没出结果"。
        """
        experiment = self.state().experiments.get(experiment_id)
        if experiment is None:
            return False, f"找不到实验 {experiment_id}"
        if not experiment.config_path:
            return False, "这次设计没有给出配置，无法执行"
        if not (self.workspace / experiment.config_path).is_file():
            return False, f"配置不存在：{experiment.config_path}"
        return True, ""

    def mark_running(self, experiment_id: str, *, run_id: str, note: str) -> dict[str, Any]:
        """记下"人批准了这次执行"。

        批准绑定的是**内容**：连同配置当时的 sha256 一起存档。配置在批准之后被改动过，
        一比对就知道 —— 与复现那边是同一套做法，不让人批的和机器跑的不是同一个东西。
        """
        with self._lock:
            state = self._loaded_state()
            experiment = state.experiments.get(experiment_id)
            if experiment is None:
                raise ResearchLoopError(f"找不到实验 {experiment_id}")
            experiment.run_id = run_id
            config = self.workspace / experiment.config_path
            record = {
                "experiment_id": experiment_id,
                "hypothesis_id": experiment.hypothesis_id,
                "run_id": run_id,
                "config_path": experiment.config_path,
                "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest() if config.is_file() else "",
                "note": note,
                "approved_at": utc_now(),
            }
            directory = self.workspace / "research" / "loop" / "approvals"
            directory.mkdir(parents=True, exist_ok=True)
            write_json_atomic(directory / f"{experiment_id}.json", record)
            state.save(self.workspace)
            return record

    # ------------------------------------------------------------------ 推进

    def submit_step(self, *, max_steps: int = 1) -> LoopJob:
        """在后台推进一步（或几步）。同一工作区同一时刻只允许一个作业。"""
        try:
            steps = max(1, min(int(max_steps), MAX_STEPS_PER_JOB))
        except (TypeError, ValueError):
            steps = 1

        with self._lock:
            if self._running_job is not None:
                raise ResearchLoopError(f"已有作业在推进：{self._running_job}")
            if self._state is None:
                self._state = backfill_state(self.workspace)
            job = LoopJob(
                job_id=self._next_job_id(),
                status="running",
                started_at=utc_now(),
                max_steps=steps,
            )
            self._jobs.append(job)
            del self._jobs[:-JOB_HISTORY_LIMIT]
            self._running_job = job.job_id

        thread = threading.Thread(target=self._advance, args=(job,), name=f"research-loop-{job.job_id}", daemon=True)
        thread.start()
        return job

    def _advance(self, job: LoopJob) -> None:
        """后台推进。状态只在锁里改，模型调用在锁外 —— 否则一次长调用会卡住所有只读请求。"""
        failure = ""
        try:
            executor = self._executor_factory()
            with self._lock:
                # 推进之前先把磁盘上的新实验记录接进来。训练是异步的：跑完之后没有谁
                # 通知编排层"有新结果了"，此前只有界面轮询时顺手回填。少了这一步，
                # 刚跑完的实验在推进时**看不见** —— 编排器会拿着旧状态再设计一次，
                # 而那个结果永远等不到核查，闭环就断在这里。真实撞到过。
                # 回填是幂等的，重复调用只是重读几个小 JSON。
                self._state = backfill_state(self.workspace, state=self._state)
                state = self._state

            outcome = run_loop(state, self.workspace, executor=executor, max_steps=job.max_steps)
            job.steps = [item.to_dict() for item in outcome.steps]
            job.stopped_because = outcome.stopped_because
            job.pending_approvals = list(outcome.pending_approvals)
        except Exception as error:  # noqa: BLE001 - 作业失败要记进作业本身，不能只留一行日志
            failure = f"{type(error).__name__}: {error}"
        finally:
            with self._lock:
                self._state.save(self.workspace)
                # 作业的终态与"没有作业在跑"必须在同一把锁里同时生效。
                # 分两步写的话，调用方会看到"已完成"却仍被拒绝提交 —— 那个窗口里
                # 界面上像是卡住了，实际只是时序。
                job.finished_at = utc_now()
                if failure:
                    job.status = "failed"
                    job.error = failure
                else:
                    job.status = "completed"
                self._running_job = None

    def job(self, job_id: str) -> dict[str, Any] | None:
        for item in self._jobs:
            if item.job_id == job_id:
                return item.to_dict()
        return None

    def jobs(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self._jobs][::-1]


__all__ = ["JOB_HISTORY_LIMIT", "MAX_STEPS_PER_JOB", "LoopJob", "ResearchLoopError", "ResearchLoopService"]
