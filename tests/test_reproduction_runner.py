"""Tests for reproduction planning and isolated container execution."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from agents.reproduction_planner import (
    audited_dataset,
    commands_from_readme,
    dependency_manifest,
    find_entrypoints,
    looks_like_gpu,
    reproduce_plan,
    write_plan,
)
from app.api_server import CompetitionApiHandler
from app.container_runner import (
    DOCKER_FALLBACK_PATHS,
    BindMount,
    ContainerSpec,
    DockerRunner,
    RunOutcome,
    build_arguments,
)
from app.reproduction_service import ReproductionError, ReproductionService, _describe_outputs, plan_digest
from tools.files import read_json, write_json_atomic


README_WITH_COMMANDS = """# Baseline

## Training

```bash
python train.py --data /data/aic2026 --epochs 10 --output /output
```

## Inference

```bash
python infer.py --weights weights.pt
```
"""


def _fake_repository(root: Path, *, content: dict[str, str] | None = None) -> Path:
    """造一个仓库目录：入口脚本、依赖清单、README。"""
    source = root / "reproductions" / "sources" / "baseline"
    source.mkdir(parents=True)
    files = {
        "train.py": "print('train')\n",
        "infer.py": "print('infer')\n",
        "_private.py": "print('helper')\n",
        "requirements.txt": "torch==2.4.0\nnumpy\n",
        "README.md": README_WITH_COMMANDS,
    }
    files.update(content or {})
    for name, text in files.items():
        (source / name).write_text(text, encoding="utf-8")
    return source


def _workspace_with_candidate(root: Path, source: Path, *, dataset: bool = True, clone_url: str = "https://github.com/example/baseline.git") -> Path:
    """把「候选 + 已通过静态检查的仓库 + 已审计数据」铺进一个工作区。"""
    workspace = root / "workspace" / "current"
    workspace.mkdir(parents=True, exist_ok=True)
    write_json_atomic(
        workspace / "reproductions" / "baseline.json",
        {
            "repository": clone_url,
            "commit": "abc1234",
            "status": "static_inspection_complete",
            "local_path": str(source),
            "static_signals": {"license_file": "LICENSE"},
        },
    )
    write_json_atomic(
        workspace / "research" / "papers.json",
        {
            "query": "object detection",
            "sources": ["arxiv"],
            "provider_failures": {},
            "records": [
                {
                    "paper_id": "arxiv:1",
                    "title": "Tri-modal fusion detector",
                    "source": "arxiv",
                    "code_url": None,
                    "relevance_score": 0.7,
                    "relevance_parts": {"task": 0.7, "code": 0.0},
                }
            ],
        },
    )
    write_json_atomic(
        workspace / "research" / "candidate_assessments.json",
        {
            "assessments": {
                "arxiv:1": {
                    "paper_id": "arxiv:1",
                    "code_candidates": [{"repository": "example/baseline", "clone_url": clone_url, "license": "MIT"}],
                    "code_lookup": "found",
                    "verdict": "reproduce",
                }
            }
        },
    )
    if dataset:
        data_dir = root / "data" / "aic2026"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "train.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        write_json_atomic(
            workspace / "reports" / "data_statistics.json",
            {"data_dir": str(data_dir), "inventory_sha256": "a" * 64, "file_count": 1},
        )
    return workspace


class PlanningTests(unittest.TestCase):
    def test_entrypoints_rank_training_first_and_skip_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = _fake_repository(Path(temporary))
            entries = find_entrypoints(source)
            self.assertEqual([item["kind"] for item in entries], ["train", "infer"])
            self.assertNotIn("_private.py", [item["path"] for item in entries])

    def test_dependency_manifest_prefers_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = _fake_repository(Path(temporary))
            self.assertEqual(dependency_manifest(source), "requirements.txt")

    def test_missing_manifest_is_reported_as_none(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = _fake_repository(Path(temporary), content={"requirements.txt": ""})
            (source / "requirements.txt").unlink()
            self.assertIsNone(dependency_manifest(source))

    def test_readme_commands_keep_their_line_reference(self) -> None:
        """候选命令必须带出处：人看到的是仓库自己写的用法，不是系统编的。"""
        with tempfile.TemporaryDirectory() as temporary:
            source = _fake_repository(Path(temporary))
            commands = commands_from_readme(source, "README.md", ["train.py", "infer.py"])

            self.assertEqual(len(commands), 2)
            self.assertEqual(commands[0]["command"], "python train.py --data /data/aic2026 --epochs 10 --output /output")
            self.assertEqual(commands[0]["source"], "README.md:6")
            # origin 只用两个词：documented / fallback。界面按它区分「文档原文」与「退化命令」，
            # 两边用同一套取值，否则抄来的命令会被显示成猜的。
            self.assertEqual(commands[0]["origin"], "documented")
            self.assertEqual(commands[1]["source"], "README.md:12")

    def test_commands_not_mentioning_repository_scripts_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = _fake_repository(Path(temporary), content={"README.md": "```bash\npython -m pip install -r something.txt\n```\n"})
            self.assertEqual(commands_from_readme(source, "README.md", ["train.py"]), [])

    def test_plan_offers_probe_commands_when_readme_has_none(self) -> None:
        """README 没有命令时只给带 fallback 标记的探测命令，不假装那是推荐用法。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _fake_repository(root, content={"README.md": "# No commands here\n"})
            workspace = _workspace_with_candidate(root, source)

            plan = reproduce_plan(workspace, read_json(workspace / "reproductions" / "baseline.json"))

            self.assertTrue(plan["commands"])
            self.assertTrue(all(item["origin"] == "fallback" for item in plan["commands"]))
            self.assertEqual(plan["commands"][0]["command"], "python train.py --help")
            self.assertEqual(plan["commands"][0]["confidence"], "probe")

    def test_plan_refuses_a_repository_that_was_not_inspected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _fake_repository(root)
            record = read_json(_workspace_with_candidate(root, source) / "reproductions" / "baseline.json")
            record["status"] = "awaiting_human_approval"
            with self.assertRaises(ValueError):
                reproduce_plan(root, record)

    def test_plan_mounts_the_audited_dataset_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _fake_repository(root)
            workspace = _workspace_with_candidate(root, source)

            plan = reproduce_plan(workspace, read_json(workspace / "reproductions" / "baseline.json"))

            self.assertTrue(plan["dataset"]["host_path"].endswith("aic2026"))
            self.assertEqual(plan["dataset"]["inventory_sha256"], "a" * 64)
            self.assertTrue(plan["mounts"]["dataset"]["read_only"])
            self.assertTrue(plan["mounts"]["source"]["read_only"])

    def test_dataset_is_absent_without_an_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _fake_repository(root)
            workspace = _workspace_with_candidate(root, source, dataset=False)

            self.assertIsNone(audited_dataset(workspace))
            plan = reproduce_plan(workspace, read_json(workspace / "reproductions" / "baseline.json"))
            self.assertIsNone(plan["dataset"])
            self.assertFalse(plan["mounts"]["dataset"]["present"])

    def test_gpu_hint_comes_from_the_repository_text(self) -> None:
        self.assertTrue(looks_like_gpu("install torch and use torch.cuda"))
        self.assertFalse(looks_like_gpu("a pure numpy baseline"))

    def test_write_plan_names_the_plan_after_the_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _fake_repository(root)
            workspace = _workspace_with_candidate(root, source)
            stored = write_plan(workspace, reproduce_plan(workspace, read_json(workspace / "reproductions" / "baseline.json")))

            self.assertEqual(stored["plan_id"], "REPRO-baseline")
            self.assertTrue((workspace / "reproductions" / "plans" / "baseline.json").exists())


class ArgumentTests(unittest.TestCase):
    def test_mounts_use_explicit_type_bind_syntax(self) -> None:
        """Windows 宿主路径里带盘符冒号，`--mount` 比 `-v` 好读也好查。"""
        spec = ContainerSpec(
            name="t",
            image="python:3.12-slim",
            command="echo hi",
            mounts=(BindMount(Path("B:/data/x"), "/data", True), BindMount(Path("B:/work"), "/work", False)),
        )
        arguments = build_arguments(spec)

        self.assertIn("type=bind,source=B:\\data\\x,target=/data,readonly", arguments)
        self.assertIn("type=bind,source=B:\\work,target=/work", arguments)
        self.assertEqual(arguments[-4:], ["python:3.12-slim", "sh", "-lc", "echo hi"])

    def test_network_and_resources_are_always_explicit(self) -> None:
        spec = ContainerSpec(name="t", image="img", command="c", mounts=(), network="none", cpus="2", memory="4g")
        arguments = build_arguments(spec)
        self.assertEqual(arguments[arguments.index("--network") + 1], "none")
        self.assertEqual(arguments[arguments.index("--cpus") + 1], "2")
        self.assertEqual(arguments[arguments.index("--memory") + 1], "4g")
        self.assertNotIn("--gpus", arguments)

    def test_gpu_is_opt_in(self) -> None:
        spec = ContainerSpec(name="t", image="img", command="c", mounts=(), gpus=True)
        arguments = build_arguments(spec)
        self.assertEqual(arguments[arguments.index("--gpus") + 1], "all")

    def test_timed_out_run_removes_the_container(self) -> None:
        """docker run 客户端被超时杀掉，容器还在跑，必须显式删掉。"""
        removed: list[str] = []

        class RecordingRunner(DockerRunner):
            def remove(self, name: str) -> None:
                removed.append(name)

        runner = RecordingRunner(executable="docker")
        spec = ContainerSpec(name="yjl-1", image="img", command="sleep", mounts=(), timeout_seconds=1)
        with tempfile.TemporaryDirectory() as temporary:
            log_path = Path(temporary) / "run.log"
            with patch("app.container_runner.subprocess.run", side_effect=subprocess.TimeoutExpired("docker", 1)):
                outcome = runner.run(spec, log_path=log_path)

            self.assertTrue(outcome.timed_out)
            self.assertEqual(removed, ["yjl-1"])
            self.assertIn("[timeout]", log_path.read_text(encoding="utf-8"))

    def test_missing_docker_is_reported_as_unavailable(self) -> None:
        with patch("app.container_runner.subprocess.run", side_effect=FileNotFoundError("docker")):
            status = DockerRunner(executable="docker").availability()
        self.assertFalse(status["available"])
        self.assertIn("not found", status["reason"])


class DockerLocationTests(unittest.TestCase):
    """docker 与它的凭据助手必须都能被子进程找到，否则连公开镜像都拉不下来。"""

    def test_path_wins_when_docker_is_already_there(self) -> None:
        with patch("app.container_runner.shutil.which", return_value="/usr/local/bin/docker"):
            self.assertEqual(DockerRunner.locate(), "/usr/local/bin/docker")

    def test_falls_back_to_the_default_install_location(self) -> None:
        """刚装完 Docker Desktop 时 docker 还不在 PATH 里（要开新终端才有）。"""
        with patch("app.container_runner.shutil.which", return_value=None):
            with patch("app.container_runner.Path.is_file", return_value=True):
                self.assertEqual(DockerRunner.locate(), DOCKER_FALLBACK_PATHS[0])

    def test_environment_puts_the_docker_directory_first_on_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "docker.exe"
            executable.write_text("", encoding="utf-8")
            runner = DockerRunner(executable=str(executable))
            with patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True):
                env = runner.environment()

            self.assertEqual(env["PATH"].split(os.pathsep)[0], str(executable.parent))
            self.assertIn("/usr/bin", env["PATH"])

    def test_the_resolved_executable_is_what_gets_run(self) -> None:
        spec = ContainerSpec(name="t", image="img", command="c", mounts=())
        self.assertEqual(build_arguments(spec, "C:/docker/docker.exe")[0], "C:/docker/docker.exe")
        self.assertEqual(build_arguments(spec)[0], "docker")


class FakeRunner(DockerRunner):
    """把容器调用换成可断言的假实现，其余编排逻辑照跑。"""

    def __init__(self, codes: list[int] | None = None, available: bool = True):
        # 显式指定可执行文件：不要让测试结果取决于这台机器上装没装 docker。
        super().__init__(executable="docker")
        self.codes = list(codes or [])
        self.specs: list[ContainerSpec] = []
        self.removed: list[str] = []
        self._available = available

    def availability(self) -> dict:
        if not self._available:
            return {"available": False, "version": None, "reason": "docker executable not found on PATH"}
        return {"available": True, "version": "test", "reason": ""}

    def run(self, spec: ContainerSpec, *, log_path: Path) -> RunOutcome:
        self.specs.append(spec)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("$ fake\nepoch 1\ndone\n", encoding="utf-8")
        # 下载阶段真的会往挂载点里写出 wheel；不模拟这一点，缓存就永远命中不了。
        for mount in spec.mounts:
            if mount.target != "/work/wheels":
                continue
            mount.host.mkdir(parents=True, exist_ok=True)
            (mount.host / "torch-2.4.0-py3-none-any.whl").write_bytes(b"wheel")
        code = self.codes.pop(0) if self.codes else 0
        return RunOutcome(returncode=code, timed_out=False, duration_seconds=0.01, log_path=str(log_path), command_line=[])

    def remove(self, name: str) -> None:
        self.removed.append(name)


class ServiceTests(unittest.TestCase):
    def _service(self, root: Path, runner: FakeRunner, *, dataset: bool = True) -> tuple[ReproductionService, Path]:
        source = _fake_repository(root)
        workspace = _workspace_with_candidate(root, source, dataset=dataset)
        return ReproductionService(root, workspace, runner=runner), workspace

    def _wait(self, service: ReproductionService, run_id: str, timeout: float = 15.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            run = service.run_detail(run_id)
            if run and run.get("status") not in ("queued", "running"):
                return run
            time.sleep(0.05)
        raise AssertionError(f"run {run_id} did not finish within {timeout}s")

    def test_plan_is_built_from_the_assessed_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service, _ = self._service(Path(temporary), FakeRunner())
            plan = service.make_plan("arxiv:1")

            self.assertEqual(plan["plan_id"], "REPRO-baseline")
            self.assertEqual(plan["paper_id"], "arxiv:1")
            self.assertEqual(plan["dependency_manifest"], "requirements.txt")
            self.assertEqual(service.plan_detail("REPRO-baseline")["title"], "Tri-modal fusion detector")

    def test_plan_requires_a_clonable_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service, workspace = self._service(root, FakeRunner())
            write_json_atomic(
                workspace / "research" / "candidate_assessments.json",
                {"assessments": {"arxiv:1": {"paper_id": "arxiv:1", "code_candidates": [], "code_lookup": "lookup_failed"}}},
            )
            with self.assertRaises(ReproductionError):
                service.make_plan("arxiv:1")

    def test_run_requires_a_written_approval_note(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service, _ = self._service(Path(temporary), FakeRunner())
            service.make_plan("arxiv:1")
            with self.assertRaises(ReproductionError) as raised:
                service.submit("REPRO-baseline", "cmd-1", "   ")
            self.assertIn("approval note", str(raised.exception))

    def test_run_is_refused_when_docker_is_unavailable(self) -> None:
        """装不上 Docker 时报错，而不是排一个永远跑不动的作业。"""
        with tempfile.TemporaryDirectory() as temporary:
            service, _ = self._service(Path(temporary), FakeRunner(available=False))
            service.make_plan("arxiv:1")
            with self.assertRaises(ReproductionError) as raised:
                service.submit("REPRO-baseline", "cmd-1", "reviewed the README")
            self.assertIn("Docker is not usable", str(raised.exception))

    def test_run_is_refused_for_an_unknown_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service, _ = self._service(Path(temporary), FakeRunner())
            service.make_plan("arxiv:1")
            with self.assertRaises(ReproductionError):
                service.submit("REPRO-baseline", "cmd-999", "note")

    def test_two_phases_download_then_run_without_network(self) -> None:
        """第一阶段联网只下载 wheel，第二阶段无网安装并跑命令。"""
        with tempfile.TemporaryDirectory() as temporary:
            runner = FakeRunner()
            service, _ = self._service(Path(temporary), runner)
            service.make_plan("arxiv:1")
            submitted = service.submit("REPRO-baseline", "cmd-1", "reviewed the README and the licence")
            run = self._wait(service, submitted["run_id"])

            self.assertEqual(run["status"], "succeeded")
            self.assertEqual([spec.network for spec in runner.specs], ["bridge", "none"])
            self.assertEqual(runner.specs[0].command, "pip download -r /src/requirements.txt -d /work/wheels")
            self.assertIn("pip install --no-index --find-links /wheels", runner.specs[1].command)
            # 缓存以只读挂进去：命令装得上依赖，但改不了那份 wheel。
            wheels_mount = next(mount for mount in runner.specs[1].mounts if mount.target == "/wheels")
            self.assertTrue(wheels_mount.read_only)
            self.assertIn("python train.py --data /data/aic2026", runner.specs[1].command)
            self.assertEqual([phase["phase"] for phase in run["phases"]], ["download_wheels", "install_and_run"])

    def test_repository_is_read_only_and_the_command_runs_on_a_copy(self) -> None:
        """仓库始终只读；训练要写权重，所以在 /work/src 的副本里跑。"""
        with tempfile.TemporaryDirectory() as temporary:
            runner = FakeRunner()
            service, _ = self._service(Path(temporary), runner)
            service.make_plan("arxiv:1")
            self._wait(service, service.submit("REPRO-baseline", "cmd-1", "note")["run_id"])

            execute = runner.specs[1]
            source_mount = next(mount for mount in execute.mounts if mount.target == "/src")
            self.assertTrue(source_mount.read_only)
            self.assertIn("cp -a /src/. /work/src/", execute.command)
            self.assertEqual(execute.workdir, "/work/src")

    def test_dataset_is_mounted_read_only_when_audited(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runner = FakeRunner()
            service, _ = self._service(Path(temporary), runner)
            service.make_plan("arxiv:1")
            self._wait(service, service.submit("REPRO-baseline", "cmd-1", "note")["run_id"])

            data_mount = next(mount for mount in runner.specs[1].mounts if mount.target == "/data")
            self.assertTrue(data_mount.read_only)
            self.assertEqual(runner.specs[1].environment["YJL_DATA"], "/data")

    def test_no_dataset_mount_without_an_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runner = FakeRunner()
            service, _ = self._service(Path(temporary), runner, dataset=False)
            service.make_plan("arxiv:1")
            run = self._wait(service, service.submit("REPRO-baseline", "cmd-1", "note")["run_id"])

            self.assertNotIn("/data", [mount.target for mount in runner.specs[1].mounts])
            self.assertEqual(run["isolation"]["dataset_mount"], "no audited dataset mounted")

    def test_failing_download_stops_before_running_the_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runner = FakeRunner(codes=[1])
            service, _ = self._service(Path(temporary), runner)
            service.make_plan("arxiv:1")
            run = self._wait(service, service.submit("REPRO-baseline", "cmd-1", "note")["run_id"])

            self.assertEqual(run["status"], "failed")
            self.assertIn("Downloading dependencies failed", run["error"])
            self.assertEqual(len(runner.specs), 1)

    def test_command_failure_is_recorded_with_its_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runner = FakeRunner(codes=[0, 3])
            service, _ = self._service(Path(temporary), runner)
            service.make_plan("arxiv:1")
            run = self._wait(service, service.submit("REPRO-baseline", "cmd-1", "note")["run_id"])

            self.assertEqual(run["status"], "failed")
            self.assertEqual(run["exit_code"], 3)
            self.assertIn("exited with code 3", run["error"])

    def test_editing_the_plan_after_approval_blocks_the_run(self) -> None:
        """批准的是「这份计划」：批准之后改计划，就不能再拿旧批准去跑。"""
        with tempfile.TemporaryDirectory() as temporary:
            runner = FakeRunner()
            service, workspace = self._service(Path(temporary), runner)
            plan = service.make_plan("arxiv:1")
            submitted = service.submit("REPRO-baseline", "cmd-1", "note")

            plan["commands"][0]["command"] = "python something-else.py"
            plan["commands"][0]["id"] = "cmd-1"
            write_json_atomic(workspace / "reproductions" / "plans" / "baseline.json", plan)
            self.assertNotEqual(plan_digest(plan), read_json(workspace / "reproductions" / "approvals" / f"{submitted['run_id']}.json")["plan_sha256"])

            run = self._wait(service, submitted["run_id"])
            self.assertEqual(run["status"], "failed")
            self.assertIn("changed after it was approved", run["error"])
            self.assertEqual(runner.specs, [])

    def test_outputs_are_listed_with_json_keys_and_csv_columns(self) -> None:
        """结果是被「看见」的：把命令写出来的文件摆出来，人去里面认指标。"""
        with tempfile.TemporaryDirectory() as temporary:
            runner = FakeRunner()
            service, _ = self._service(Path(temporary), runner)
            service.make_plan("arxiv:1")
            submitted = service.submit("REPRO-baseline", "cmd-1", "note")
            run_dir = Path(submitted["run_dir"])
            (run_dir / "output").mkdir(parents=True, exist_ok=True)
            (run_dir / "output" / "metrics.json").write_text('{"mAP50_95": 0.31}', encoding="utf-8")
            (run_dir / "output" / "results.csv").write_text("epoch,loss,mAP\n1,2.1,0.2\n", encoding="utf-8")
            run = self._wait(service, submitted["run_id"])

            summaries = {item["file"]: item for item in run["outputs"]["summaries"]}
            self.assertEqual(summaries["output/metrics.json"]["keys"], ["mAP50_95"])
            self.assertEqual(summaries["output/results.csv"]["columns"], ["epoch", "loss", "mAP"])

    def test_boilerplate_directories_do_not_crowd_out_the_real_outputs(self) -> None:
        """`.git` 与依赖缓存不是产物，却按字母序排在前面，会把 60 条的清单占满。

        这一条来自一次真实运行：命令在 `/work/src` 的副本里跑，`cp -a` 把 `.git`
        一起带了过去，于是清单前 60 条全是 hooks 样例，命令真正写出来的文件一个都
        没露出来。
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "output"
            work = root / "work"
            output.mkdir()
            (work / ".git" / "hooks").mkdir(parents=True)
            (work / "wheels").mkdir(parents=True)
            for index in range(70):
                (work / ".git" / "hooks" / f"sample-{index:02d}.sample").write_text("x", encoding="utf-8")
            (work / "wheels" / "torch-2.14.0.whl").write_bytes(b"0")
            (work / "run.log").write_text("epoch 1\n", encoding="utf-8")
            (output / "metrics.json").write_text('{"mAP50_95": 0.31}', encoding="utf-8")

            described = _describe_outputs(output, work)

            paths = [item["path"] for item in described["files"]]
            self.assertIn("metrics.json", paths)
            self.assertIn("run.log", paths)
            self.assertFalse([item for item in paths if item.startswith(".git")])
            self.assertFalse([item for item in paths if item.startswith("wheels")])
            self.assertFalse(described["truncated"])

    def test_second_run_reuses_the_cached_wheels(self) -> None:
        """同一份依赖清单只下一次：torch 一套是几 GB、十几分钟，不该每次都重来。"""
        with tempfile.TemporaryDirectory() as temporary:
            runner = FakeRunner()
            service, workspace = self._service(Path(temporary), runner)
            service.make_plan("arxiv:1")

            first = self._wait(service, service.submit("REPRO-baseline", "cmd-1", "note")["run_id"])
            self.assertFalse(first["wheel_cache"]["hit"])
            self.assertEqual([item["phase"] for item in first["phases"]], ["download_wheels", "install_and_run"])
            self.assertTrue(list((workspace / "reproductions" / "wheel_cache").glob("*/*.whl")))

            second = self._wait(service, service.submit("REPRO-baseline", "cmd-1", "note")["run_id"])
            self.assertTrue(second["wheel_cache"]["hit"])
            # 只剩执行那一段 —— 没有下载阶段。
            self.assertEqual([item["phase"] for item in second["phases"]], ["install_and_run"])
            self.assertEqual(len(runner.specs), 3)
            self.assertIn("/wheels", [mount.target for mount in runner.specs[-1].mounts])

    def test_editing_the_manifest_invalidates_the_cache(self) -> None:
        """清单内容一变，键就跟着变 —— 绝不悄悄复用旧 wheel。"""
        with tempfile.TemporaryDirectory() as temporary:
            runner = FakeRunner()
            service, _ = self._service(Path(temporary), runner)
            plan = service.make_plan("arxiv:1")

            first = self._wait(service, service.submit("REPRO-baseline", "cmd-1", "note")["run_id"])
            (Path(plan["local_path"]) / "requirements.txt").write_text("torch==2.5.0\nnumpy\n", encoding="utf-8")
            second = self._wait(service, service.submit("REPRO-baseline", "cmd-1", "note")["run_id"])

            self.assertNotEqual(second["wheel_cache"]["key"], first["wheel_cache"]["key"])
            self.assertFalse(second["wheel_cache"]["hit"])

    def test_approved_command_can_be_rewritten_before_running(self) -> None:
        """README 写的是仓库自己的相对路径，这里数据集挂在 /data，改写是常态。"""
        with tempfile.TemporaryDirectory() as temporary:
            runner = FakeRunner()
            service, workspace = self._service(Path(temporary), runner)
            service.make_plan("arxiv:1")
            rewritten = "python scripts/train.py --data /data --epochs 1 --batch-size 2 --output /output"
            submitted = service.submit("REPRO-baseline", "cmd-1", "pointed the data flag at the audited mount", command_override=rewritten)
            run = self._wait(service, submitted["run_id"])

            self.assertEqual(run["command"], rewritten)
            self.assertTrue(run["command_overridden"])
            self.assertEqual(run["command_documented_at"], "README.md:6")
            self.assertIn(rewritten, runner.specs[1].command)
            approval = read_json(workspace / "reproductions" / "approvals" / f"{submitted['run_id']}.json")
            self.assertEqual(approval["command"], rewritten)
            self.assertEqual(approval["command_source"], "README.md:6")

    def test_multiline_command_is_rejected(self) -> None:
        """多行输入会让「批准的是哪一条命令」说不清。"""
        with tempfile.TemporaryDirectory() as temporary:
            service, _ = self._service(Path(temporary), FakeRunner())
            service.make_plan("arxiv:1")
            with self.assertRaises(ReproductionError) as raised:
                service.submit("REPRO-baseline", "cmd-1", "note", command_override="python a.py\nrm -rf /work")
            self.assertIn("single line", str(raised.exception))

    def test_approval_and_run_records_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runner = FakeRunner()
            service, workspace = self._service(Path(temporary), runner)
            service.make_plan("arxiv:1")
            submitted = service.submit("REPRO-baseline", "cmd-1", "reviewed the code at commit abc1234")

            approval = read_json(workspace / "reproductions" / "approvals" / f"{submitted['run_id']}.json")
            self.assertEqual(approval["command"], "python train.py --data /data/aic2026 --epochs 10 --output /output")
            self.assertIn("reviewed the code", approval["note"])
            self._wait(service, submitted["run_id"])
            self.assertEqual(len(service.runs()), 1)
            self.assertTrue((workspace / "reproductions" / "runs" / submitted["run_id"] / "run.json").exists())


class ReproductionApiTests(unittest.TestCase):
    """两个新接口走真实 HTTP 路径：只验证它们接得上，不真开容器。"""

    def _serve(self, root: Path, workspace: Path):
        handler = type(
            "TestReproductionApiHandler",
            (CompetitionApiHandler,),
            {"project_root": root, "workspace": workspace},
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def _get(self, base: str, path: str) -> dict:
        with urlopen(base + path, timeout=5) as response:  # nosec B310: local test server
            return json.loads(response.read())

    def _post_error(self, base: str, path: str, payload: dict) -> tuple[int, str]:
        request = Request(
            base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=5) as response:  # nosec B310: local test server
                return response.status, response.read().decode("utf-8")
        except HTTPError as error:
            return int(error.code), error.read().decode("utf-8")

    def test_status_endpoint_reports_docker_plans_and_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _fake_repository(root)
            workspace = _workspace_with_candidate(root, source)
            server, thread = self._serve(root, workspace)
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                status = self._get(base, "/api/reproductions")
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

            # Docker 在开发机上可能装着也可能没装，所以这里只断言「如实报告了」。
            self.assertIn("available", status["docker"])
            self.assertEqual(status["plans"], [])
            self.assertEqual(status["runs"], [])

    def test_run_without_an_approval_note_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _fake_repository(root)
            workspace = _workspace_with_candidate(root, source)
            server, thread = self._serve(root, workspace)
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                status, body = self._post_error(
                    base, "/api/reproductions/run", {"plan_id": "REPRO-baseline", "command_id": "cmd-1"}
                )
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

            self.assertEqual(status, 400)
            self.assertIn("approval note", body)

    def test_plan_for_an_unknown_candidate_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _fake_repository(root)
            workspace = _workspace_with_candidate(root, source)
            server, thread = self._serve(root, workspace)
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                status, body = self._post_error(base, "/api/reproductions/plan", {"paper_id": "arxiv:nope"})
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

            self.assertEqual(status, 400)
            self.assertIn("Unknown research record", body)


if __name__ == "__main__":
    unittest.main()
