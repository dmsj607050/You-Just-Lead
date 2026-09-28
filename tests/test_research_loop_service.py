"""研究循环服务层的测试：状态持有、后台推进、冲突拒绝。

这些测试全离线：注入一个假执行器，把**模型调用**换掉，但推进流程本身照跑 ——
流程才是这个类要保证的东西。
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from app.research_loop_service import MAX_STEPS_PER_JOB, ResearchLoopError, ResearchLoopService
from schemas.research import Experiment, Hypothesis


def _workspace(root: Path) -> Path:
    workspace = root / "workspace"
    (workspace / "experiments" / "manifests").mkdir(parents=True)
    (workspace / "experiments" / "results").mkdir(parents=True)
    return workspace


def _experiment_record(workspace: Path, experiment_id: str, hypothesis: str, status: str = "completed") -> None:
    (workspace / "experiments" / "manifests" / f"{experiment_id}.json").write_text(
        json.dumps(
            {"experiment_id": experiment_id, "hypothesis": hypothesis, "change_type": "baseline", "seed": 0},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (workspace / "experiments" / "results" / f"{experiment_id}.json").write_text(
        json.dumps({"experiment_id": experiment_id, "status": status, "metrics": {"mAP": 0.5}}),
        encoding="utf-8",
    )


def _fake_executor(action: str, decision: object, state: object, workspace: Path) -> dict:
    """假执行器：不改状态，只回报自己被执行了。"""
    return {"detail": f"fake handled {action}"}


def _wait_for_job(service: ResearchLoopService, job_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = service.job(job_id)
        if job and job["status"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError(f"作业 {job_id} 没有在 {timeout} 秒内结束")


def _settle(service: ResearchLoopService, timeout: float = 10.0) -> None:
    """等所有作业结束再离开临时目录。

    推进跑在后台线程里；不等它写完就删目录，Windows 会以 WinError 145
    （目录不是空的）失败 —— 那是测试的时序问题，不是产品缺陷。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if all(job["status"] != "running" for job in service.jobs()):
            return
        time.sleep(0.05)


class SnapshotTests(unittest.TestCase):
    def test_snapshot_carries_the_four_things_the_ui_needs(self) -> None:
        """界面只该显示四件事，快照必须一次把它们都给全。"""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace(Path(temporary))
            _experiment_record(workspace, "EXP-0001", "加宽 P2 层")
            service = ResearchLoopService(Path(temporary), workspace)

            snapshot = service.snapshot()

            self.assertIn("summary", snapshot)
            self.assertIn("next_action", snapshot)
            self.assertIn("hypotheses", snapshot)
            self.assertIn("evidence", snapshot)
            self.assertEqual(len(snapshot["experiments"]), 1)

    def test_next_action_is_a_prediction_and_changes_nothing(self) -> None:
        """预测不能有副作用：界面每次刷新都会问一次下一步，问了就改状态就没法用了。"""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace(Path(temporary))
            _experiment_record(workspace, "EXP-0001", "加宽 P2 层")
            service = ResearchLoopService(Path(temporary), workspace)

            first = service.snapshot()
            second = service.snapshot()

            self.assertEqual(first["next_action"], second["next_action"])
            self.assertEqual(len(service.state().decisions), 0)
            self.assertIn("action", first["next_action"])

    def test_backfilling_twice_does_not_duplicate_experiments(self) -> None:
        """回填必须幂等：界面上有个「重新回填」按钮，重复点不该让计数翻倍。"""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace(Path(temporary))
            _experiment_record(workspace, "EXP-0001", "加宽 P2 层")
            service = ResearchLoopService(Path(temporary), workspace)

            service.snapshot()
            service.backfill()
            service.backfill()

            self.assertEqual(len(service.state().experiments), 1)
            self.assertEqual(len(service.state().hypotheses), 1)


class StepJobTests(unittest.TestCase):
    def test_a_submitted_step_runs_in_the_background_and_lands_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace(Path(temporary))
            _experiment_record(workspace, "EXP-0001", "加宽 P2 层")
            service = ResearchLoopService(Path(temporary), workspace, executor_factory=lambda: _fake_executor)

            job = service.submit_step(max_steps=1)
            finished = _wait_for_job(service, job.job_id)

            self.assertEqual(finished["status"], "completed")
            self.assertTrue(finished["steps"])
            # 状态必须落盘：进程重启后循环要能接着走，而不是回到起点。
            self.assertTrue((workspace / "research" / "loop" / "state.json").exists())

    def test_max_steps_is_capped(self) -> None:
        """一步要真调模型，跑飞了要有人能按住 —— 请求给得再大也要封顶。"""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace(Path(temporary))
            service = ResearchLoopService(Path(temporary), workspace, executor_factory=lambda: _fake_executor)

            job = service.submit_step(max_steps=999)

            self.assertEqual(job.max_steps, MAX_STEPS_PER_JOB)
            _settle(service)

    def test_a_result_that_landed_after_the_state_was_loaded_is_still_seen(self) -> None:
        """推进前必须把磁盘上的新实验记录接进来。

        训练是异步的：跑完之后没有谁通知编排层"有新结果了"。如果推进时只用手上那份旧状态，
        刚跑完的实验就**看不见** —— 编排器会拿着旧状态再设计一次，而那个结果永远等不到核查，
        闭环就断在"真执行 → 证据核查"这一步。真实撞到过。
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = _workspace(root)
            service = ResearchLoopService(root, workspace, executor_factory=lambda: _fake_executor)
            # 先取一次快照：状态被加载进内存，此刻磁盘上还没有任何实验。
            self.assertEqual(service.snapshot()["experiments"], [])

            # 状态加载之后，训练才跑完并落盘。
            _experiment_record(workspace, "EXP-0009", "加宽 P2 层")

            job = service.submit_step(max_steps=1)
            finished = _wait_for_job(service, job.job_id)

            self.assertEqual(finished["status"], "completed")
            # 直接读内存里那份状态：`snapshot()` 会顺手回填，用它来断言就绕过了这条修复。
            self.assertIn(
                "EXP-0009",
                service.state().experiments,
                "推进时看不到刚落盘的实验 —— 编排器按旧状态做了决定",
            )

    def test_a_second_step_is_refused_while_one_is_running(self) -> None:
        """同一工作区不能有两个循环同时改状态，否则会互相覆盖。"""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace(Path(temporary))
            _experiment_record(workspace, "EXP-0001", "加宽 P2 层")

            released = {"go": False}

            def blocking_executor(action: str, decision: object, state: object, workspace: Path) -> dict:
                deadline = time.time() + 5
                while not released["go"] and time.time() < deadline:
                    time.sleep(0.02)
                return {"detail": "慢执行器"}

            service = ResearchLoopService(Path(temporary), workspace, executor_factory=lambda: blocking_executor)
            first = service.submit_step(max_steps=1)

            with self.assertRaises(ResearchLoopError):
                service.submit_step(max_steps=1)

            with self.assertRaises(ResearchLoopError):
                service.backfill()

            released["go"] = True
            _wait_for_job(service, first.job_id)
            # 跑完之后又能提交了。
            second = service.submit_step(max_steps=1)
            self.assertIsNotNone(second)
            _settle(service)

    def test_a_failing_executor_lands_in_the_job_not_in_a_traceback(self) -> None:
        """执行器抛错要记进作业本身：界面得能说出"这一步为什么没成"。"""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace(Path(temporary))
            _experiment_record(workspace, "EXP-0001", "加宽 P2 层")

            def exploding_executor(action: str, decision: object, state: object, workspace: Path) -> dict:
                raise RuntimeError("模型没返回可解析的 JSON")

            service = ResearchLoopService(Path(temporary), workspace, executor_factory=lambda: exploding_executor)
            job = service.submit_step(max_steps=1)
            finished = _wait_for_job(service, job.job_id)

            # step() 会把动作级失败记成 failed 步骤，而不是让整个作业崩掉；
            # 两种情况都要能读出原因，所以这里接受其中之一，但必须写明。
            self.assertIn(finished["status"], ("completed", "failed"))
            detail = json.dumps(finished, ensure_ascii=False)
            self.assertIn("模型没返回可解析的 JSON", detail)

    def test_job_history_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace(Path(temporary))
            service = ResearchLoopService(Path(temporary), workspace, executor_factory=lambda: _fake_executor)

            for _ in range(3):
                finished = _wait_for_job(service, service.submit_step(max_steps=1).job_id)
                self.assertEqual(finished["status"], "completed")
                # 上一轮刚判完成，下一轮就必须能提交：中间不许存在"已完成但仍被拒"的窗口。
                self.assertIsNone(service.snapshot()["running"])

            self.assertEqual(len(service.jobs()), 3)
            self.assertEqual(service.jobs()[0]["status"], "completed")

    def test_job_ids_stay_unique_within_the_same_second(self) -> None:
        """只用秒级时间戳会碰撞。

        后果不是"id 不好看"：按 id 查作业返回的是先建的那个，调用方于是看到一个假的
        "已完成"，紧接着提交被拒 —— 界面上像是卡住了，而真实原因是两条作业重名。
        """
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace(Path(temporary))
            service = ResearchLoopService(Path(temporary), workspace)

            identities = {service._next_job_id() for _ in range(50)}

            self.assertEqual(len(identities), 50)


class HumanHypothesisTests(unittest.TestCase):
    """人可以提假设，但"是人写的"不是免检章。"""

    def test_a_human_hypothesis_lands_in_the_pool_with_a_branch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace(Path(temporary))
            service = ResearchLoopService(Path(temporary), workspace)

            added = service.add_hypothesis(
                statement="把 external.stage 从 rgb 换成 fusion 能提升 mAP@50-95",
                predictions=["mAP@50-95 高于 RGB 单模态的 0.00234"],
                falsifiers=["mAP@50-95 不高于 0.00234"],
                rationale=["规则九（一）要求算法读取三模态"],
            )

            self.assertEqual(added["hypothesis_id"], "H0001")
            self.assertEqual(service.state().branches["B0001"].hypothesis_id, "H0001")
            self.assertTrue(service.state().hypotheses["H0001"].is_falsifiable())

    def test_a_too_short_statement_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace(Path(temporary))
            service = ResearchLoopService(Path(temporary), workspace)

            with self.assertRaises(ValueError):
                service.add_hypothesis(statement="试试", predictions=["x"], falsifiers=["y"])

    def test_a_human_hypothesis_without_falsifiers_faces_the_same_gate(self) -> None:
        """人不写反证条件，编排器一样把它打回补全 —— 否则人就成了一条绕过门控的捷径。"""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace(Path(temporary))
            service = ResearchLoopService(Path(temporary), workspace)
            added = service.add_hypothesis(statement="三模态融合应该比单模态更好一些", predictions=[], falsifiers=[])

            self.assertFalse(service.state().hypotheses[added["hypothesis_id"]].is_falsifiable())
            self.assertEqual(service.state().falsifiable_hypotheses(), [])


class ExecutionHandoffTests(unittest.TestCase):
    """从「设计」到「执行」的交接：没有真配置就不排作业，批准要绑内容。"""

    def _state_with(self, workspace: Path, **experiment_fields) -> ResearchLoopService:
        service = ResearchLoopService(workspace.parent, workspace)
        state = service.state()
        state.add_hypothesis(Hypothesis(hypothesis_id="H0001", statement="门控残差能提升 ball 召回"))
        state.add_experiment(Experiment(experiment_id="E0001", hypothesis_id="H0001", question="球类召回是否改善", **experiment_fields))
        return service

    def test_a_design_without_a_config_cannot_be_executed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace(Path(temporary))
            service = self._state_with(workspace)

            runnable, reason = service.executable("E0001")

            self.assertFalse(runnable)
            self.assertIn("没有给出配置", reason)

    def test_a_config_path_that_does_not_exist_is_refused(self) -> None:
        """写进 JSON 的路径与真的存在那个文件是两件事，只有后者能跑。

        不先问清楚就会排一个注定失败的作业，然后被人读成"实验跑了、只是没出结果"。
        """
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace(Path(temporary))
            service = self._state_with(workspace, config_path="configs/loop/nope.yaml")

            runnable, reason = service.executable("E0001")

            self.assertFalse(runnable)
            self.assertIn("配置不存在", reason)

    def test_a_design_with_a_real_config_is_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace(Path(temporary))
            (workspace / "configs" / "loop").mkdir(parents=True)
            (workspace / "configs" / "loop" / "e1.yaml").write_text("a: 1\n", encoding="utf-8")
            service = self._state_with(workspace, config_path="configs/loop/e1.yaml")

            runnable, reason = service.executable("E0001")

            self.assertTrue(runnable, reason)

    def test_approval_records_the_config_digest(self) -> None:
        """批准绑定内容：配置批完之后再被改动，一比对就知道。"""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace(Path(temporary))
            (workspace / "configs" / "loop").mkdir(parents=True)
            config = workspace / "configs" / "loop" / "e1.yaml"
            config.write_text("a: 1\n", encoding="utf-8")
            service = self._state_with(workspace, config_path="configs/loop/e1.yaml")

            approval = service.mark_running("E0001", run_id="JOB-1", note="核对过配置与数据版本")

            self.assertEqual(approval["run_id"], "JOB-1")
            self.assertEqual(len(approval["config_sha256"]), 64)
            self.assertTrue((workspace / "research" / "loop" / "approvals" / "E0001.json").is_file())
            # 作业号回写到实验上，这样"这次设计"和"那次运行"才对得上。
            self.assertEqual(service.state().experiments["E0001"].run_id, "JOB-1")

    def test_approving_an_unknown_experiment_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace(Path(temporary))
            service = ResearchLoopService(Path(temporary), workspace)

            with self.assertRaises(ResearchLoopError):
                service.mark_running("E9999", run_id="JOB-1", note="x")


class KillHintTests(unittest.TestCase):
    def test_a_killed_hypothesis_is_not_offered_for_experiments(self) -> None:
        """终止过的假设不该再被送上实验台 —— 否则"终止"就只是个显示状态。"""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace(Path(temporary))
            service = ResearchLoopService(Path(temporary), workspace)
            state = service.state()
            state.add_hypothesis(
                Hypothesis(
                    hypothesis_id="H0001",
                    statement="门控残差能提升 ball 召回",
                    predictions=["ball AP50 提升"],
                    falsifiers=["ball AP50 不变"],
                )
            )
            state.hypotheses["H0001"].status = "killed"

            self.assertEqual([item.hypothesis_id for item in state.falsifiable_hypotheses()], [])


if __name__ == "__main__":
    unittest.main()
