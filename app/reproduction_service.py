"""Orchestrate isolated reproduction runs: plan, approve, execute, collect.

A run is the only place in this project where third-party code is executed, so
the order of operations is the point of the module:

1. **plan** — read a repository that already passed static inspection and turn
   it into a plan; nothing runs here.
2. **approve** — a person picks one candidate command and writes a note. The
   approval records a digest of the plan it was granted for.
3. **execute** — a background thread re-checks that digest, then runs two
   containers: a networked one that only downloads wheels, and a
   network-isolated one that installs them and runs the approved command.
4. **collect** — exit code, full logs on disk, and an inventory of the files the
   command produced.

The digest check is the part that matters: without it, editing the plan after
approval would silently run something nobody approved.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from agents.candidate_agent import candidates_for_workspace
from agents.reproduction_agent import intake_repository
from agents.reproduction_planner import reproduce_plan, write_plan
from app.container_runner import BindMount, ContainerSpec, DockerRunner, log_tail
from database.ledger import ledger_for_workspace
from tools.files import read_json, write_json_atomic
from tools.provenance import utc_now


class ReproductionError(RuntimeError):
    """Raised when a plan or run cannot be created or queried."""


DEFAULT_IMAGE = "python:3.12-slim"

# 阶段名会写进运行记录，界面按它显示「卡在哪一步」。
PHASE_DOWNLOAD = "download_wheels"
PHASE_EXECUTE = "install_and_run"

# 产物清单最多列这么多条：一次训练可能写出成百上千个文件，全列出来读不了。
OUTPUT_LISTING_LIMIT = 60

# 遍历产物的上界：/work 里是整份仓库副本，走完全树没有意义。
OUTPUT_SCAN_LIMIT = 5000


def plan_digest(plan: dict[str, Any]) -> str:
    """计划内容的指纹。批准时记下它，执行前再算一次比对。"""
    canonical = json.dumps(plan, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _describe_outputs(output_dir: Path, work_dir: Path) -> dict[str, Any]:
    """列出命令产出的文件，并把 JSON 顶层键、CSV 表头摘出来。

    指标就是这样被动地被「看见」的：不猜哪个文件是结果，而是把命令自己写出来的
    文件摆出来，人对一眼就知道 mAP 在哪个文件里。

    `/work` 里是仓库的整份副本（几千个文件），所以先扫 `/output`，再扫 `/work`，
    并且给遍历设一个上界 —— 清单只列前若干条，不必走完全树。
    """
    listing: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    visited: int = 0
    for root in (output_dir, work_dir):
        if not root.is_dir() or len(listing) >= OUTPUT_LISTING_LIMIT:
            continue
        for path in sorted(root.rglob("*")):
            visited += 1
            if visited > OUTPUT_SCAN_LIMIT or len(listing) >= OUTPUT_LISTING_LIMIT:
                break
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            listing.append({"root": root.name, "path": relative, "bytes": path.stat().st_size})
            if len(summaries) >= 6:
                continue
            if path.suffix == ".json":
                summaries.append({"file": f"{root.name}/{relative}", "kind": "json", "keys": _json_keys(path)})
            elif path.suffix == ".csv":
                summaries.append({"file": f"{root.name}/{relative}", "kind": "csv", "columns": _csv_columns(path)})
    return {"files": listing, "summaries": summaries, "truncated": len(listing) >= OUTPUT_LISTING_LIMIT}


def _json_keys(path: Path) -> list[str]:
    """JSON 顶层键：够看出这个文件装的是什么，不用读全文。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace")[:200_000])
    except (OSError, ValueError):
        return []
    if isinstance(payload, dict):
        return [str(key) for key in list(payload.keys())[:20]]
    if isinstance(payload, list):
        return [f"list[{len(payload)}]"]
    return []


def _csv_columns(path: Path) -> list[str]:
    try:
        header = path.read_text(encoding="utf-8", errors="replace").splitlines()[:1]
    except OSError:
        return []
    if not header:
        return []
    return [item.strip() for item in header[0].split(",")[:20]]


class ReproductionService:
    """按工作区一份；运行作业在后台线程里跑。"""

    def __init__(self, project_root: Path, workspace: Path, runner: DockerRunner | None = None):
        self.project_root = project_root.resolve()
        self.workspace = workspace.resolve()
        self.runner = runner or DockerRunner()
        self.runs_dir = self.workspace / "reproductions" / "runs"
        self.approvals_dir = self.workspace / "reproductions" / "approvals"
        self.plans_dir = self.workspace / "reproductions" / "plans"
        self.ledger = ledger_for_workspace(self.project_root, self.workspace)
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- 计划

    def docker_status(self) -> dict[str, Any]:
        return self.runner.availability()

    def plans(self) -> list[dict[str, Any]]:
        if not self.plans_dir.exists():
            return []
        return sorted(
            (read_json(path) for path in self.plans_dir.glob("*.json")),
            key=lambda item: str(item.get("plan_id", "")),
        )

    def plan_detail(self, plan_id_value: str) -> dict[str, Any] | None:
        for plan in self.plans():
            if plan.get("plan_id") == plan_id_value:
                return plan
        return None

    def make_plan(self, paper_id: str, *, image: str | None = None) -> dict[str, Any]:
        """给一条候选生成复现计划。

        这一步会 clone 仓库 —— 点「生成复现计划」就是批准 clone。克隆仍然只做静态检查，
        代码要被*执行*还得再走一次 `submit` 的批准。
        """
        merged = candidates_for_workspace(self.workspace)
        record = next((item for item in merged["records"] if item.get("paper_id") == paper_id), None)
        if record is None:
            raise ReproductionError(f"Unknown research record: {paper_id}")

        clone_urls: list[str] = []
        if record.get("code_url"):
            clone_urls.append(str(record["code_url"]))
        assessment = record.get("assessment") or {}
        for candidate in assessment.get("code_candidates") or []:
            url = candidate.get("clone_url")
            if url and url not in clone_urls:
                clone_urls.append(str(url))
        if not clone_urls:
            raise ReproductionError(
                "No clonable repository on this candidate. Assess it first, or record a code URL."
            )

        repository_record = self._intake(clone_urls[0])
        plan = reproduce_plan(self.workspace, repository_record, image=image or DEFAULT_IMAGE)
        plan["paper_id"] = paper_id
        plan["title"] = record.get("title")
        stored = write_plan(self.workspace, plan)
        self.ledger.record_event(
            "reproduction_planned",
            {
                "plan_id": stored["plan_id"],
                "paper_id": paper_id,
                "repository": stored.get("repository"),
                "commands": len(stored.get("commands", [])),
                "requires_gpu": stored.get("requires_gpu"),
            },
        )
        return stored

    def _intake(self, clone_url: str) -> dict[str, Any]:
        """克隆仓库（已克隆过就直接读记录），返回 intake 记录。"""
        reproductions = self.workspace / "reproductions"
        slug = clone_url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
        existing = reproductions / f"{slug}.json"
        if existing.exists():
            record = read_json(existing)
            if record.get("status") == "static_inspection_complete":
                return record
        intake = intake_repository(self.workspace, clone_url, approved=True)
        return read_json(Path(intake["record_path"]))

    # ---------------------------------------------------------------- 运行

    def runs(self) -> list[dict[str, Any]]:
        if not self.runs_dir.exists():
            return []
        records: list[dict[str, Any]] = []
        for directory in sorted(self.runs_dir.iterdir(), reverse=True):
            path = directory / "run.json"
            if directory.is_dir() and path.exists():
                records.append(read_json(path))
        return records

    def run_detail(self, run_id: str) -> dict[str, Any] | None:
        path = self.runs_dir / run_id / "run.json"
        if not path.exists():
            return None
        return read_json(path)

    def submit(
        self,
        plan_id_value: str,
        command_id: str,
        note: str,
        *,
        command_override: str | None = None,
    ) -> dict[str, Any]:
        """批准并排队一次复现运行。

        `command_override` 是人改写后的命令。仓库 README 写的是它自己的相对路径
        （`--data data/`），而这里的数据集挂在 `/data`，所以改写是常态；改写后的命令
        会原样记进批准文件，批准的就是实际要跑的那一行。
        """
        if not note.strip():
            raise ReproductionError("A written approval note is required: say what you reviewed and why it may run.")
        status = self.runner.availability()
        if not status["available"]:
            raise ReproductionError(f"Docker is not usable: {status['reason']}")

        plan = self.plan_detail(plan_id_value)
        if plan is None:
            raise ReproductionError(f"Unknown plan: {plan_id_value}")
        command = next((item for item in plan.get("commands", []) if item.get("id") == command_id), None)
        if command is None:
            raise ReproductionError(f"Unknown command {command_id} on plan {plan_id_value}")
        effective = (command_override or "").strip() or str(command["command"]).strip()
        if "\n" in effective or "\r" in effective:
            # 多行输入会让「批准的是哪一条命令」说不清，也会往执行脚本里插行。
            raise ReproductionError("The command must be a single line.")
        source = Path(str(plan.get("local_path") or ""))
        if not source.is_dir():
            raise ReproductionError(f"The cloned repository is missing: {source}")

        with self._lock:
            run_id = self._next_run_id()
            run_dir = self.runs_dir / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            approval = {
                "run_id": run_id,
                "plan_id": plan_id_value,
                "command_id": command_id,
                "command": effective,
                "command_source": command.get("source"),
                "command_overridden": bool(command_override and command_override.strip()),
                "image": plan.get("image"),
                "resources": plan.get("resources"),
                "plan_sha256": plan_digest(plan),
                "approved_at": utc_now(),
                "note": note.strip(),
            }
            write_json_atomic(self.approvals_dir / f"{run_id}.json", approval)
            run = {
                "run_id": run_id,
                "plan_id": plan_id_value,
                "title": plan.get("title"),
                "paper_id": plan.get("paper_id"),
                "repository": plan.get("repository"),
                "commit": plan.get("commit"),
                "command_id": command_id,
                "command": effective,
                "command_origin": command.get("origin"),
                "command_documented_at": command.get("source"),
                "command_overridden": approval["command_overridden"],
                "image": plan.get("image"),
                "resources": plan.get("resources"),
                "dataset": plan.get("dataset"),
                "status": "queued",
                "phases": [],
                "exit_code": None,
                "error": None,
                "outputs": None,
                "run_dir": str(run_dir),
                "log_tail": "",
                "created_at": utc_now(),
                "started_at": None,
                "finished_at": None,
                "isolation": {
                    "network": "isolated while the command runs; networked only while downloading wheels",
                    "repository_mount": "read-only at /src; the command runs on a copy under /work",
                    "dataset_mount": "read-only at /data" if plan.get("dataset") else "no audited dataset mounted",
                },
            }
            self._save_run(run)
            self.ledger.record_event(
                "reproduction_run_submitted",
                {
                    "run_id": run_id,
                    "plan_id": plan_id_value,
                    "command": effective,
                    "overridden": approval["command_overridden"],
                    "image": plan.get("image"),
                },
            )

        thread = threading.Thread(target=self._execute, args=(run_id,), daemon=True)
        thread.start()
        return run

    def _execute(self, run_id: str) -> None:
        run = self.run_detail(run_id)
        if run is None:
            return
        run["status"] = "running"
        run["started_at"] = utc_now()
        self._save_run(run)
        self.ledger.record_event("reproduction_run_started", {"run_id": run_id, "plan_id": run["plan_id"]})
        try:
            plan = self.plan_detail(run["plan_id"])
            if plan is None:
                raise ReproductionError("The plan disappeared after approval.")
            approval = read_json(self.approvals_dir / f"{run_id}.json")
            if plan_digest(plan) != approval.get("plan_sha256"):
                raise ReproductionError("The plan changed after it was approved; refusing to run it.")

            run_dir = Path(run["run_dir"])
            source = Path(str(plan["local_path"]))
            work_dir = run_dir / "work"
            output_dir = run_dir / "output"
            work_dir.mkdir(parents=True, exist_ok=True)
            output_dir.mkdir(parents=True, exist_ok=True)

            resources = plan.get("resources") or {}
            cpus = str(resources.get("cpus") or "4")
            memory = str(resources.get("memory") or "8g")
            timeout = int(resources.get("timeout_seconds") or 3600)
            image = str(plan.get("image") or DEFAULT_IMAGE)
            manifest = plan.get("dependency_manifest")

            # 阶段一：只有这一步联网，而且只下载 wheel，不执行仓库代码。
            if manifest:
                download = ContainerSpec(
                    name=f"{run_id}-dl",
                    image=image,
                    command=f"pip download -r /src/{manifest} -d /work/wheels",
                    mounts=(BindMount(source, "/src", True), BindMount(work_dir, "/work", False)),
                    network="bridge",
                    cpus=cpus,
                    memory=memory,
                    workdir="/work",
                    timeout_seconds=min(timeout, 1800),
                )
                outcome = self.runner.run(download, log_path=run_dir / "download.log")
                run["phases"].append(
                    {
                        "phase": PHASE_DOWNLOAD,
                        "command": download.command,
                        "network": "bridge",
                        "exit_code": outcome.returncode,
                        "timed_out": outcome.timed_out,
                        "duration_seconds": outcome.duration_seconds,
                        "log_path": outcome.log_path,
                    }
                )
                self._save_run(run)
                if not outcome.succeeded:
                    raise ReproductionError("Downloading dependencies failed; see download.log")

            # 阶段二：无网。仓库以只读挂在 /src，命令在可写副本 /work/src 里跑 ——
            # 训练要往仓库目录里写权重和日志，只读挂载会让它直接失败。
            install = ""
            if manifest:
                install = f"pip install --no-index --find-links /work/wheels -r /src/{manifest} && "
            script = "\n".join(
                [
                    "set -e",
                    "mkdir -p /work/src /output",
                    "cp -a /src/. /work/src/",
                    "cd /work/src",
                    f"{install}{run['command']}",
                ]
            )
            mounts = [BindMount(source, "/src", True), BindMount(work_dir, "/work", False), BindMount(output_dir, "/output", False)]
            dataset = plan.get("dataset") or {}
            if dataset.get("host_path"):
                mounts.append(BindMount(Path(str(dataset["host_path"])), "/data", True))
            execute = ContainerSpec(
                name=f"{run_id}-run",
                image=image,
                command=script,
                mounts=tuple(mounts),
                network="none",
                cpus=cpus,
                memory=memory,
                workdir="/work/src",
                timeout_seconds=timeout,
                gpus=bool(plan.get("requires_gpu")),
                environment={"YJL_DATA": "/data", "YJL_OUTPUT": "/output", "YJL_SOURCE": "/work/src"},
            )
            outcome = self.runner.run(execute, log_path=run_dir / "run.log")
            run["phases"].append(
                {
                    "phase": PHASE_EXECUTE,
                    "command": run["command"],
                    "network": "none",
                    "exit_code": outcome.returncode,
                    "timed_out": outcome.timed_out,
                    "duration_seconds": outcome.duration_seconds,
                    "log_path": outcome.log_path,
                }
            )
            run["exit_code"] = outcome.returncode
            run["log_tail"] = log_tail(Path(outcome.log_path))
            run["outputs"] = _describe_outputs(output_dir, work_dir)
            if outcome.timed_out:
                run["status"] = "failed"
                run["error"] = f"The command did not finish within {timeout}s; the container was removed."
            elif outcome.succeeded:
                run["status"] = "succeeded"
            else:
                run["status"] = "failed"
                run["error"] = f"The command exited with code {outcome.returncode}."
        except Exception as exc:
            run["status"] = "failed"
            run["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            run["finished_at"] = utc_now()
            self._save_run(run)
            self.ledger.record_event(
                "reproduction_run_finished",
                {"run_id": run_id, "plan_id": run.get("plan_id"), "status": run["status"], "exit_code": run.get("exit_code")},
            )

    # ---------------------------------------------------------------- 内部

    def _save_run(self, run: dict[str, Any]) -> None:
        write_json_atomic(self.runs_dir / run["run_id"] / "run.json", run)

    def _next_run_id(self) -> str:
        existing = [path.name for path in self.runs_dir.glob("REPR-*") if path.is_dir()]
        numbers = [int(name.split("-", 1)[1]) for name in existing if name.split("-", 1)[1].isdigit()]
        return f"REPR-{max(numbers, default=0) + 1:04d}"


def recover_interrupted_runs(service: ReproductionService) -> None:
    """后端进程重启后，把还挂在 queued/running 的运行标成失败。

    容器是子进程，进程一死就没人管它了；留着「运行中」的状态会让人以为还在跑。
    """
    for run in service.runs():
        if run.get("status") not in ("queued", "running"):
            continue
        run["status"] = "failed"
        run["finished_at"] = utc_now()
        if not run.get("error"):
            run["error"] = "The run was interrupted by an API process restart."
        service._save_run(run)
        service.ledger.record_event("reproduction_run_interrupted", {"run_id": run.get("run_id")})
