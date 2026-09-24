"""发布清单与版本纪律。

目标对 Release Engineering 的要求是「最终提交出去的不再是一个『文件包』，而是一个**可审计的
软件版本**」，并点名 `release_manifest.json` 要记录 version / git commit / schema version /
build time / HAP 或 APP 的 SHA256 / backend version / workspace schema / migration version。

这个文件把那些字段**逐条钉住**，并测三件容易退化的事：

1. 版本号必须符合 dev → alpha → beta → rc → release 的流转格式（写歪了直接拒）；
2. 「可以发布」是有条件的：不是 rc/release 阶段、缺产物、或有未提交改动，都不算可以发布；
3. 发布说明里点名的产物必须留下摘要 —— `docs/RELEASE_0.1.5.md` 记了 SHA-256，
   而 0.1.6~0.1.9 都没记，纪律就是这么退化的。
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from app.release_service import (
    MANIFEST_VERSION,
    STAGES,
    VERSION_FILE,
    ArtifactSpec,
    build_release_manifest,
    manifest_path,
    parse_version,
    read_project_version,
    write_release_manifest,
)

#: 目标里点名要记录的字段。少一个就失败。
OBJECTIVE_FIELDS = (
    "version",
    "stage",
    "build_time",
    "git",
    "schema",
    "workspace_schema",
    "components",
    "artifacts",
)

#: 早期发布说明的统一标记：说明那份文档是历史记录、对应的安装包不在仓库里。
HISTORICAL_MARKER = "历史发布记录"

_SHA256 = re.compile(r"\b[0-9a-fA-F]{64}\b")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _has_git() -> bool:
    return shutil.which("git") is not None


def _init_repo(root: Path) -> None:
    """建一个只有一个提交的临时仓库，用来测"未提交改动会挡住发布"。"""
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    (root / VERSION_FILE).write_text("1.0.0\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        [
            "git", "-C", str(root),
            "-c", "user.email=release-test@example.invalid",
            "-c", "user.name=Release Test",
            "commit", "-q", "-m", "init",
        ],
        check=True,
        capture_output=True,
    )


class VersionTests(unittest.TestCase):
    def test_accepts_the_documented_flow(self) -> None:
        for text, stage, serial in (
            ("1.0.0", "release", None),
            ("1.0.0-dev.0", "dev", 0),
            ("2.3.4-alpha.7", "alpha", 7),
            ("2.3.4-beta.1", "beta", 1),
            ("2.3.4-rc.2", "rc", 2),
        ):
            with self.subTest(version=text):
                parsed = parse_version(text)
                self.assertEqual(parsed.stage, stage)
                self.assertEqual(parsed.serial, serial)
                self.assertEqual(parsed.core, text.split("-")[0])

    def test_rejects_anything_else(self) -> None:
        for text in ("1.0", "1.0.0.0", "v1.0.0", "1.0.0-dev", "1.0.0-final.1", "1.0.0-dev.x", "", "  "):
            with self.subTest(version=text):
                with self.assertRaises(ValueError):
                    parse_version(text)

    def test_only_rc_and_release_count_as_release_stages(self) -> None:
        for text in ("1.0.0-dev.0", "1.0.0-alpha.1", "1.0.0-beta.9"):
            with self.subTest(version=text):
                self.assertFalse(parse_version(text).is_release_stage)
        for text in ("1.0.0-rc.1", "1.0.0"):
            with self.subTest(version=text):
                self.assertTrue(parse_version(text).is_release_stage)

    def test_all_documented_stages_exist(self) -> None:
        self.assertEqual(STAGES, ("dev", "alpha", "beta", "rc", "release"))

    def test_project_version_file_is_valid(self) -> None:
        parsed = read_project_version(_repo_root())
        self.assertEqual(parsed.text, parsed.text.strip())
        self.assertIn(parsed.stage, STAGES)


class ManifestShapeTests(unittest.TestCase):
    """在临时目录里造产物与仓库，逐条核对清单的字段。"""

    def test_records_every_field_the_objective_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "dist").mkdir(parents=True, exist_ok=True)
            (root / "dist" / "probe.bin").write_bytes(b"probe-payload")

            manifest = build_release_manifest(
                root,
                version_text="1.0.0-rc.1",
                artifacts=[ArtifactSpec("probe-artifact", "test", root, "dist/probe.bin", True)],
                build_time="2026-01-01T00:00:00+00:00",
            )

        for field in OBJECTIVE_FIELDS:
            with self.subTest(field=field):
                self.assertIn(field, manifest)

        self.assertEqual(manifest["manifest_version"], MANIFEST_VERSION)
        self.assertEqual(manifest["version"], "1.0.0-rc.1")
        self.assertEqual(manifest["stage"], "rc")
        self.assertEqual(manifest["build_time"], "2026-01-01T00:00:00+00:00")

    def test_records_git_state_for_both_repositories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = build_release_manifest(
                Path(temporary), version_text="1.0.0-rc.1", artifacts=[]
            )
        self.assertIn("backend", manifest["git"])
        self.assertIn("device", manifest["git"])
        # 临时目录不是仓库：如实记 available=false，不假装有 commit。
        self.assertFalse(manifest["git"]["backend"]["available"])
        self.assertIsNone(manifest["git"]["backend"]["commit"])

    def test_records_every_schema_number_that_actually_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = build_release_manifest(
                Path(temporary), version_text="1.0.0-rc.1", artifacts=[]
            )
        schema = manifest["schema"]
        self.assertIn("db_migration", schema)
        self.assertIn("data_contracts", schema)
        self.assertIn("experiment_registry", schema)
        self.assertIn("training_scaffold", schema)
        for name, value in schema.items():
            with self.subTest(schema=name):
                self.assertIsInstance(value, int)
        # 迁移版本就是账本的 schema 版本，不是另编一个数。
        from database.ledger import SCHEMA_VERSION as LEDGER_SCHEMA_VERSION

        self.assertEqual(schema["db_migration"], LEDGER_SCHEMA_VERSION)

    def test_workspace_schema_lists_directories_and_a_digest(self) -> None:
        from app.experiment_service import WORKSPACE_DIRECTORIES

        with tempfile.TemporaryDirectory() as temporary:
            manifest = build_release_manifest(
                Path(temporary), version_text="1.0.0-rc.1", artifacts=[]
            )
        workspace_schema = manifest["workspace_schema"]
        self.assertEqual(workspace_schema["directories"], list(WORKSPACE_DIRECTORIES))
        expected = hashlib.sha256("\n".join(WORKSPACE_DIRECTORIES).encode("utf-8")).hexdigest()
        self.assertEqual(workspace_schema["digest"], expected)

    def test_artifact_digests_match_the_files_on_disk(self) -> None:
        payload = b"probe-payload-for-digest"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "dist").mkdir(parents=True, exist_ok=True)
            (root / "dist" / "probe.bin").write_bytes(payload)

            manifest = build_release_manifest(
                root,
                version_text="1.0.0-rc.1",
                artifacts=[
                    ArtifactSpec("probe-artifact", "test", root, "dist/probe.bin", True)
                ],
            )

        entry = manifest["artifacts"][0]
        self.assertTrue(entry["present"])
        self.assertEqual(entry["bytes"], len(payload))
        self.assertEqual(entry["sha256"], hashlib.sha256(payload).hexdigest())

    def test_missing_artifact_is_recorded_as_absent_not_invented(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = build_release_manifest(
                root,
                version_text="1.0.0-dev.0",
                artifacts=[
                    ArtifactSpec("probe-artifact", "test", root, "dist/probe.bin", False)
                ],
            )

        entry = manifest["artifacts"][0]
        self.assertFalse(entry["present"])
        self.assertIsNone(entry["sha256"])
        self.assertIsNone(entry["bytes"])
        self.assertFalse(entry["required_for_release"])
        # 非发布必需的产物缺失不该阻塞：dev 阶段本来就没有正式产物。
        self.assertEqual(manifest["release_blockers"], ["version stage is 'dev', not rc/release"])


class ReleaseGateTests(unittest.TestCase):
    """「可以发布」是有条件的，而且这个条件可判定。"""

    def test_release_stage_without_a_required_artifact_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = build_release_manifest(
                root,
                version_text="1.0.0-rc.1",
                artifacts=[
                    ArtifactSpec("device-hap", "harmony-hap", root, "entry/build/*.hap", True)
                ],
            )

        self.assertFalse(manifest["release_ready"])
        self.assertTrue(
            any("required artifacts are missing" in item for item in manifest["release_blockers"]),
            manifest["release_blockers"],
        )

    def test_release_stage_with_every_artifact_present_can_be_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "entry" / "build").mkdir(parents=True, exist_ok=True)
            (root / "entry" / "build" / "app.hap").write_bytes(b"hap")

            manifest = build_release_manifest(
                root,
                version_text="1.0.0-rc.1",
                artifacts=[
                    ArtifactSpec("device-hap", "harmony-hap", root, "entry/build/*.hap", True)
                ],
            )

        self.assertTrue(manifest["release_ready"], manifest["release_blockers"])
        self.assertEqual(manifest["release_blockers"], [])

    def test_dev_stage_is_never_release_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = build_release_manifest(
                Path(temporary), version_text="1.0.0-dev.0", artifacts=[]
            )
        self.assertFalse(manifest["release_ready"])

    @unittest.skipUnless(_has_git(), "git 不在 PATH 上")
    def test_uncommitted_changes_block_a_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _init_repo(root)

            clean = build_release_manifest(root, artifacts=[])
            self.assertTrue(clean["git"]["backend"]["available"])
            self.assertFalse(clean["git"]["backend"]["dirty"])
            self.assertTrue(clean["release_ready"], clean["release_blockers"])

            (root / "scratch.txt").write_text("uncommitted\n", encoding="utf-8")
            dirty = build_release_manifest(root, artifacts=[])

        self.assertTrue(dirty["git"]["backend"]["dirty"])
        self.assertFalse(dirty["release_ready"])
        self.assertEqual(dirty["release_blockers"], ["uncommitted changes in: backend"])


class DeviceAppVersionTests(unittest.TestCase):
    def test_device_app_version_must_match_the_project_version_core(self) -> None:
        """端侧 `AppScope/app.json5` 的 versionName 与应用内声明的版本核心必须一致。

        不一致就是「文档里的版本 ≠ 实际构建的版本」那类问题的根，所以判为阻塞项。
        """
        with tempfile.TemporaryDirectory() as temporary:
            device = Path(temporary)
            (device / "AppScope").mkdir(parents=True, exist_ok=True)
            (device / "AppScope" / "app.json5").write_text(
                '{"app": {"bundleName": "com.example.app", "versionName": "9.9.9", "versionCode": 1}}',
                encoding="utf-8",
            )

            manifest = build_release_manifest(
                Path(temporary) / "backend",
                device_root=device,
                version_text="1.0.0-rc.1",
                artifacts=[],
            )

        self.assertEqual(manifest["components"]["device"]["version_name"], "9.9.9")
        self.assertFalse(manifest["release_ready"])
        self.assertTrue(
            any("versionName" in item for item in manifest["release_blockers"]),
            manifest["release_blockers"],
        )

    def test_real_device_repository_matches_the_project_version(self) -> None:
        """本机上端侧是真的存在且版本对得上的 —— 对不上说明有一侧的版本号该改。"""
        from tools.device_repo import device_repo_root

        device = device_repo_root(_repo_root())
        if device is None:
            self.skipTest("端侧仓库不在这台机器上")
        manifest = build_release_manifest(
            _repo_root(), device_root=device, version_text="1.0.0-rc.1", artifacts=[]
        )
        info = manifest["components"]["device"]
        self.assertEqual(info["version_name"], "1.0.0")

    def test_missing_device_repository_is_recorded_as_null(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = build_release_manifest(
                Path(temporary), device_root=None, version_text="1.0.0-rc.1", artifacts=[]
            )
        self.assertIsNone(manifest["git"]["device"])
        self.assertIsNone(manifest["components"]["device"])


class ManifestWritingTests(unittest.TestCase):
    def test_writes_next_to_the_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = build_release_manifest(root, version_text="1.0.0-dev.0", artifacts=[])

            written = write_release_manifest(root, manifest)

            self.assertEqual(written, manifest_path(root))
            self.assertTrue(written.is_file())
            self.assertEqual(written.parent.name, "release")

    def test_is_deterministic_apart_from_the_build_time(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = build_release_manifest(root, version_text="1.0.0-rc.1", artifacts=[],
                                           build_time="2026-01-01T00:00:00+00:00")
            second = build_release_manifest(root, version_text="1.0.0-rc.1", artifacts=[],
                                            build_time="2026-01-01T00:00:00+00:00")
        self.assertEqual(first, second)


class ReleaseOutputIsIgnoredTests(unittest.TestCase):
    """发布产物目录必须被 git 忽略。

    `.gitignore` 里原先**漏了** `/release/`，于是它是"未跟踪"而不是"被忽略"的状态 ——
    十几 MB 的安装包与清单随时会被一次 `git add -A` 带进版本库。靠"记得别 add"不算保障，
    所以钉成测试。
    """

    @unittest.skipUnless(_has_git(), "git 不在 PATH 上")
    def test_release_output_directory_is_ignored_by_git(self) -> None:
        result = subprocess.run(
            ["git", "-C", str(_repo_root()), "check-ignore", "-q", "release/release_manifest.json"],
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, "release/ 没有被 .gitignore 忽略，发布产物可能被误提交")


class ReleaseNoteDisciplineTests(unittest.TestCase):
    """发布说明不能"点了名却什么都不留"。

    `docs/RELEASE_0.1.5.md` 记了安装包的 SHA-256，0.1.6~0.1.9 都没记 —— 纪律是这么退化的。
    这份检查要求：每份发布说明要么明确标成历史记录（早期那些，产物已不在），
    要么留下产物的 SHA-256。**它只能证明"摘要写了"，不能证明"摘要对得上那个文件"** ——
    产物本身不进版本库（`release/` 是 gitignore 的输出目录）。
    """

    def test_every_release_note_is_either_historical_or_carries_digests(self) -> None:
        notes = sorted((_repo_root() / "docs").glob("RELEASE_*.md"))
        self.assertTrue(notes, "没有找到任何发布说明")
        for note in notes:
            text = note.read_text(encoding="utf-8")
            with self.subTest(note=note.name):
                if HISTORICAL_MARKER in text:
                    continue
                self.assertRegex(
                    text,
                    _SHA256,
                    f"{note.name} 既没标成历史记录、也没有留下产物摘要",
                )

    def test_the_violation_this_guards_against_is_real(self) -> None:
        """证明这条检查抓得住东西：去掉历史标记的说明必须被判不通过。"""
        note = (_repo_root() / "docs" / "RELEASE_0.1.9.md").read_text(encoding="utf-8")
        without_marker = note.replace(HISTORICAL_MARKER, "")
        self.assertNotIn(HISTORICAL_MARKER, without_marker)
        self.assertIsNone(_SHA256.search(without_marker))


if __name__ == "__main__":
    unittest.main()
