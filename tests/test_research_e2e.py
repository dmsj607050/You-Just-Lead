"""研究循环在**真实工作区**上的端到端：一整圈走完，每一步的产物都被下一步真实消费。

与 `test_real_data_e2e.py` 的分工：那个文件测的是**流水线**（规则 → 数据 → 训练 → 论文），
它不碰编排层；这个文件测的是**循环**：

    人工批准规则 → 真实数据审计（真指纹） → 人提一条可证伪的假设
      → 编排器设计实验（模型把配置**真的写到盘上**）
      → 人工批准执行（研究层批准 + GPU 预算批准，两次都落在文件上）
      → 训练调度器真的跑起来（CPU，tabular_classification）
      → 回填把这次运行接进研究状态，并挂回**当初被批准的那条假设**
      → 核查九项、算出判定，编排器据判定决定下一步（先去跨种子复现）
      → 走到没有可设计的假设时综合证据，并**开出新假设**（这一环闭合）

模型那一层是注入的（本测试不联网），但**被它驱动的链路全是真的**：它说"把这份配置写出来"，
配置就真的落到盘上并被 `executable()` 检查存在性；它的判断真的进入九项核查、真的由
`validate_evidence` 算判定；训练真的跑、结果真的回填、下一步真的由策略算出来。

**范围说明（别把结论放大）**：数据是本测试自己写的 CSV（比赛数据不在本机），训练用的是
内置的 CPU runner。这证明的是"循环在真实文件上闭得上"，不是比赛成绩。
"""

from __future__ import annotations

import csv
import json
import random
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Callable

from agents.data_agent import audit_dataset
from agents.rules_agent import approve_rule_specification
from app.approval_service import approve_training_config
from app.orchestrator.executor import ResearchExecutor
from app.orchestrator.loop import run as run_loop
from app.orchestrator.state import ResearchState
from app.project_registry import create_project, workspace_path
from app.research_loop_service import ResearchLoopService
from app.training_scheduler import TrainingScheduler
from tools.configuration import write_yaml
from tools.files import read_json

ROWS = 240
FEATURE_NAMES = ("feature_1", "feature_2")

#: 这次设计的配置写在哪儿。与研究层其他落盘物（`research/loop/`）同一个习惯：
#: 模型自己写出来的东西集中放，别和工作区原有的配置混在一起。
CONFIG_RELATIVE = "configs/loop/e2e_design.yaml"

#: 真训练的上限等待时间。CPU 上这个数据集十几秒就完；给足余量但不无限等。
JOB_TIMEOUT_SECONDS = 300


def _write_dataset(raw_dir: Path, *, rows: int = ROWS, seed: int = 7) -> None:
    """写一份**真实落盘**的数值 CSV：特征 + 目标列，线性可分（指标稳定、不靠运气）。"""
    raw_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    header = ["id", *FEATURE_NAMES, "target"]
    for name in ("train.csv", "test.csv"):
        with (raw_dir / name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            for index in range(rows):
                first = rng.uniform(-1.0, 1.0)
                second = rng.uniform(-1.0, 1.0)
                writer.writerow(
                    [f"row-{index}", f"{first:.6f}", f"{second:.6f}", 1 if first + second > 0 else 0]
                )


def _generic_spec(workspace: Path) -> None:
    """一份**通用**档案的规格。先留成待人工确认，再走真实的批准函数把它翻过来。"""
    write_yaml(
        workspace / "competition_spec.yaml",
        {
            "competition": {"name": "Loop Cup", "task_type": "tabular_classification"},
            "evaluation": {"primary_metric": "accuracy", "direction": "maximize"},
            "approval": {"requires_human_confirmation": True, "unresolved_questions": []},
        },
    )


def _training_config(raw_dir: Path, fingerprint: str) -> dict[str, Any]:
    """模型这次要写出来的训练配置。

    数据路径必须是**绝对**且落在审计目录内 —— `AuditedInputScopePolicy` 按提交上来的
    参数原样检查，相对路径会被解析到当前工作目录而不是工作区，因此会被拒。
    """
    return {
        "experiment": {
            "hypothesis": "A shallow MLP reproduces a held-out tabular baseline on audited local data.",
            "change_type": "baseline",
            "estimated_gpu_hours": 0,
            "rollback_plan": "Keep this frozen baseline if later changes underperform.",
        },
        "data": {
            "version": fingerprint,
            "train_csv": str(raw_dir / "train.csv"),
            "test_csv": str(raw_dir / "test.csv"),
            "target_column": "target",
            "id_column": "id",
            "prediction_column": "target",
            "validation_fraction": 0.2,
            "feature_columns": list(FEATURE_NAMES),
        },
        "model": {"hidden_dim": 32, "dropout": 0.0},
        "training": {
            "runner": "tabular_classification",
            "seed": 42,
            "epochs": 12,
            "batch_size": 32,
            "device": "cpu",
        },
        "optimizer": {"name": "adamw", "learning_rate": 0.01, "weight_decay": 0.0},
        "validation": {"metric": "accuracy", "direction": "maximize"},
    }


def _offline_model(workspace: Path, raw_dir: Path, fingerprint: str) -> Callable[[str, str], dict]:
    """一个离线的"模型"：按提示词认出这是哪个动作，给出该动作要的 JSON。

    它扮演的正是模型那一层，所以它**真的写文件** —— 设计实验这一步要的配置由它落到盘上。
    收到没准备的提示词就直接报错：编排层新增了动作却没在这里补上，测试要立刻知道。
    """
    next_questions = ["同一配置换一个随机种子再跑一次，结论还成立吗"]

    def chat(_system: str, user: str) -> dict:
        if "设计**一次**实验" in user:
            path = workspace / CONFIG_RELATIVE
            path.parent.mkdir(parents=True, exist_ok=True)
            write_yaml(path, _training_config(raw_dir, fingerprint))
            return {
                "content": json.dumps(
                    {
                        "question": "这份冻结配置在真实数据上跑出来的 holdout accuracy 是多少",
                        "baseline": "本次运行自身即基线：同一份配置、同一份审计数据、同一种子",
                        "independent": "无（基线复跑，刻意不改任何变量）",
                        "controlled": [
                            f"data_version={fingerprint}",
                            "seed=42",
                            "epochs=12",
                            "batch_size=32",
                            "device=cpu",
                        ],
                        "metrics": ["accuracy"],
                        "success_condition": "跑完并落盘 accuracy；与基线一致（±0.01）即算复现成功",
                        "config_path": CONFIG_RELATIVE,
                        "blocker": "",
                    },
                    ensure_ascii=False,
                )
            }
        if "核查下面这次实验的结果" in user:
            # 九项里能判断的判断。`prediction_met=True` 是关键：跨种子复现还没做，
            # 所以判定应当是"查不动、先去复现"，而不是"假设被反证"。
            return {
                "content": json.dumps(
                    {
                        "ran_successfully": True,
                        "baseline_comparable": True,
                        "metric_improved": False,
                        "prediction_met": True,
                        "replicated_across_seeds": False,
                        "leakage_free": True,
                        "matches_hypothesis": True,
                        "single_variable": True,
                        "logs_consistent": True,
                        "notes": "记录与产物一致；本次只跑了一个种子。",
                    },
                    ensure_ascii=False,
                )
            }
        if "综合目前的证据" in user:
            return {
                "content": json.dumps(
                    {
                        "conclusion": "只跑了一个种子，参考点尚不足以支撑任何结论。",
                        "supported": [],
                        "refuted": [],
                        "next_questions": next_questions,
                    },
                    ensure_ascii=False,
                )
            }
        if "不可证伪" in user:
            return {
                "content": json.dumps(
                    {
                        "predictions": ["同一配置换种子重跑，accuracy 与基线一致（±0.01）"],
                        "falsifiers": ["换种子重跑后 accuracy 与基线差值超过 0.01"],
                        "uncertainty": 0.1,
                        "note": "",
                    },
                    ensure_ascii=False,
                )
            }
        if "编排器当前的动作是" in user:
            return {"content": json.dumps({"advice": "按记录继续。", "verdict": "continue"}, ensure_ascii=False)}
        if "提出 2 到 3 条" in user:
            return {"content": json.dumps({"hypotheses": []}, ensure_ascii=False)}
        raise AssertionError(f"离线模型收到了没准备的提示词：{user[:240]}")

    return chat


class ResearchLoopEndToEndTests(unittest.TestCase):
    """一整圈。断言落在每一环的**产物**上，而不是"跑完就算数"。"""

    def _prepared_workspace(self, root: Path) -> tuple[Path, Path, str]:
        """走到"循环可以开始设计实验"之前的全部前置步骤。"""
        project = create_project(root, "Loop Cup")
        workspace = workspace_path(root, str(project["id"]))
        _generic_spec(workspace)
        raw_dir = workspace / "data" / "raw"
        _write_dataset(raw_dir)
        # 规则不人工确认，真实训练起不来 —— 这一步必须走真实的批准函数。
        approve_rule_specification(workspace, "复核了通用表格任务的口径。")
        audit_dataset(workspace, raw_dir)
        fingerprint = str(read_json(workspace / "reports" / "data_statistics.json")["inventory_sha256"])
        return workspace, raw_dir, fingerprint

    def _wait_for_job(self, scheduler: TrainingScheduler, job_id: str) -> dict[str, Any]:
        deadline = time.time() + JOB_TIMEOUT_SECONDS
        while time.time() < deadline:
            job = scheduler.job_status(job_id) or {}
            if job.get("status") in ("completed", "failed"):
                return job
            time.sleep(0.5)
        self.fail(f"训练作业 {job_id} 在 {JOB_TIMEOUT_SECONDS}s 内没有结束")

    def test_one_full_circle_on_a_real_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace, raw_dir, fingerprint = self._prepared_workspace(root)
            executor = ResearchExecutor(chat=_offline_model(workspace, raw_dir, fingerprint))
            service = ResearchLoopService(root, workspace, executor_factory=lambda: executor)

            # 一、人提一条可证伪的假设。它进去之后与模型提的走同一套判据。
            hypothesis = service.add_hypothesis(
                statement="同一份冻结配置在审计过的真实数据上重跑，holdout accuracy 与基线一致（±0.01）。",
                predictions=["重跑得到的 accuracy 与基线差值不超过 0.01"],
                falsifiers=["重跑得到的 accuracy 与基线差值超过 0.01，或重跑没有落盘指标"],
                rationale=["这是判断后续改动可不可比的参考点"],
            )
            hypothesis_id = hypothesis["hypothesis_id"]

            # 二、编排器决定设计实验，执行器把它做成 —— 配置真的写到盘上。
            state = service.state()
            outcome = run_loop(state, workspace, executor=executor, max_steps=1)
            self.assertEqual([item.decision.action for item in outcome.steps], ["DESIGN_EXPERIMENT"])
            designed = [item for item in state.experiments.values() if item.hypothesis_id == hypothesis_id]
            self.assertEqual(len(designed), 1, "这次设计没有被挂在人提的那条假设下")
            experiment = designed[0]
            self.assertTrue(experiment.is_controlled(), "缺对照或控制变量的设计不算一次公平比较")
            self.assertEqual(experiment.config_path, CONFIG_RELATIVE)
            self.assertTrue((workspace / CONFIG_RELATIVE).is_file(), "模型说写了配置，盘上却没有")

            # 三、人批准执行：研究层"这次设计该跑" + 预算"这次运行可以花这些算力"。
            runnable, reason = service.executable(experiment.experiment_id)
            self.assertTrue(runnable, reason)
            config_path = workspace / experiment.config_path
            budget = approve_training_config(workspace, config_path, "这份设计有对照、只复跑同配置，批准。")
            self.assertEqual(budget["requested_device"], "cpu")
            scheduler = TrainingScheduler(root, workspace)
            job = scheduler.submit(config_path, hypothesis=experiment.question)
            approval = service.mark_running(
                experiment.experiment_id, run_id=str(job["job_id"]), note="批准复跑同配置"
            )
            self.assertEqual(len(approval["config_sha256"]), 64, "批准必须绑住配置内容，不只是路径")

            # 四、真训练。调度器内部走的就是 ExperimentService.run 那一套闸门。
            finished = self._wait_for_job(scheduler, str(job["job_id"]))
            self.assertEqual(finished["status"], "completed", finished.get("error"))
            self.assertIsNotNone(finished["validation_metric"])
            self.assertGreater(float(finished["validation_metric"]), 0.5)
            training_experiment_id = str(finished["experiment_id"])
            self.assertTrue(
                (workspace / "experiments" / "results" / f"{training_experiment_id}.json").is_file(),
                "跑完必须留下结果记录",
            )

            # 五、回填：把这次运行接进研究状态，并挂回**当初被批准的那条假设**。
            snapshot = service.snapshot()
            self.assertEqual(
                len(snapshot["hypotheses"]),
                1,
                "回填不该为这次运行另编一条重复假设（那会让证据挂到别的假设上）",
            )
            backfilled = next(
                item for item in snapshot["experiments"] if item["experiment_id"] == training_experiment_id
            )
            self.assertEqual(backfilled["hypothesis_id"], hypothesis_id)
            backfilled_evidence = [
                item for item in snapshot["evidence"] if item["experiment_id"] == training_experiment_id
            ]
            self.assertEqual(len(backfilled_evidence), 1, "跑完的实验必须先有一条'跑没跑成'的证据")
            self.assertIs(backfilled_evidence[0]["ran_successfully"], True)
            # 其余八项当时没人查 —— 必须是 None，不能被当成"查了不合格"。
            self.assertIsNone(backfilled_evidence[0]["prediction_met"])

            # 六、核查这次结果，并据判定决定下一步。判定由验证器算，不由模型说了算。
            outcome = run_loop(state, workspace, executor=executor, max_steps=2)
            actions = [item.decision.action for item in outcome.steps]
            self.assertEqual(actions, ["ANALYZE_RESULT", "REPLICATE_EXPERIMENT"], outcome.stopped_because)
            self.assertEqual(outcome.steps[0].status, "applied")
            # 预测被满足、但只跑了一个种子 —— 该去复现，而不是判假设被反证。
            self.assertEqual(outcome.steps[1].status, "awaiting_approval")
            self.assertEqual(outcome.pending_approvals, ["REPLICATE_EXPERIMENT"])

            latest = next(
                item for item in state.latest_evidence() if item.experiment_id == training_experiment_id
            )
            self.assertIs(latest.prediction_met, True, "模型判的'预测被满足'没有进到证据里")
            self.assertNotEqual(
                latest.verdict, "hypothesis_falsified", "预测被满足却判了假设被反证"
            )

            # 七、据此改进 → 新假设：没有可设计的假设时综合证据，并开出下一轮的问题。
            outcome = run_loop(state, workspace, executor=executor, max_steps=1)
            self.assertEqual([item.decision.action for item in outcome.steps], ["SYNTHESIZE"])
            opened = [item for item in state.hypotheses.values() if item.hypothesis_id != hypothesis_id]
            self.assertTrue(opened, "综合结论没有开出新假设，循环就断在这里了")
            # 新假设还没有预测与反证条件 —— 下一轮编排器会先去补全它，这正是循环的下一步。
            self.assertTrue(all(not item.is_falsifiable() for item in opened))
            notes = sorted((workspace / "research" / "loop" / "notes").glob("synthesis-*.md"))
            self.assertTrue(notes, "综合结论必须落成可审计的笔记")

            # 八、状态真的落盘了：换一个进程读回来，这一圈的对象一个不少。
            reloaded = ResearchState.load(workspace)
            self.assertIn(hypothesis_id, reloaded.hypotheses)
            self.assertIn(training_experiment_id, reloaded.experiments)
            self.assertEqual(reloaded.experiments[training_experiment_id].hypothesis_id, hypothesis_id)
            self.assertTrue(
                any(
                    edge.kind == "tests" and edge.source_id == training_experiment_id
                    for edge in reloaded.edges
                ),
                "研究图上必须有'这次实验检验那条假设'的边",
            )
            self.assertIn("REPLICATE_EXPERIMENT", [item.action for item in reloaded.decisions])


if __name__ == "__main__":
    unittest.main()
