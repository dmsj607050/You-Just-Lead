from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.trace_service import _experiment_chain
from tools.files import write_json_atomic


class ExperimentTraceTests(unittest.TestCase):
    def _workspace(self, root: Path, digest: str) -> Path:
        workspace = root / "workspace"
        manifests = workspace / "experiments" / "manifests"
        results = workspace / "experiments" / "results"
        approvals = workspace / "experiments" / "approvals"
        manifests.mkdir(parents=True)
        results.mkdir(parents=True)
        approvals.mkdir(parents=True)
        write_json_atomic(
            manifests / "EXP-0001.json",
            {
                "experiment_id": "EXP-0001",
                "status": "planned",
                "config_sha256": digest,
                "config": {"training": {"runner": "synthetic_binary_classification"}},
            },
        )
        write_json_atomic(results / "EXP-0001.json", {"experiment_id": "EXP-0001", "status": "completed"})
        return workspace

    def test_trace_verifies_config_hash_approval_and_surfaces_status_divergence(self) -> None:
        digest = "a" * 64
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self._workspace(Path(temporary), digest)
            write_json_atomic(
                workspace / "experiments" / "approvals" / f"config-{digest[:16]}.json",
                {
                    "type": "training_config_approval",
                    "config_sha256": digest,
                    "approved_at": "2026-09-28T01:46:56+00:00",
                    "note": "reviewed budget",
                },
            )

            experiment = _experiment_chain(workspace)["experiments"][0]

        self.assertTrue(experiment["approval"]["recorded"])
        self.assertEqual(experiment["approval"]["verification"], "verified")
        self.assertEqual(experiment["approval"]["note"], "reviewed budget")
        self.assertEqual(experiment["manifest_status"], "planned")
        self.assertEqual(experiment["result_status"], "completed")
        self.assertFalse(experiment["status_consistent"])
        self.assertEqual(experiment["status"], "completed")

    def test_trace_rejects_a_prefix_collision_in_approval_record(self) -> None:
        digest = "a" * 64
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self._workspace(Path(temporary), digest)
            write_json_atomic(
                workspace / "experiments" / "approvals" / f"config-{digest[:16]}.json",
                {
                    "type": "training_config_approval",
                    "config_sha256": "a" * 16 + "b" * 48,
                    "approved_at": "2026-09-28T01:46:56+00:00",
                    "note": "different config",
                },
            )

            approval = _experiment_chain(workspace)["experiments"][0]["approval"]

        self.assertFalse(approval["recorded"])
        self.assertEqual(approval["verification"], "digest_mismatch")

    def test_trace_reports_missing_config_digest_without_claiming_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self._workspace(Path(temporary), "")

            approval = _experiment_chain(workspace)["experiments"][0]["approval"]

        self.assertFalse(approval["recorded"])
        self.assertEqual(approval["verification"], "missing_config_digest")

    def test_trace_rejects_invalid_digest_and_incomplete_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self._workspace(Path(temporary), "not-a-sha256")
            invalid_digest = _experiment_chain(workspace)["experiments"][0]["approval"]

        self.assertFalse(invalid_digest["recorded"])
        self.assertEqual(invalid_digest["verification"], "invalid_config_digest")

        digest = "c" * 64
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self._workspace(Path(temporary), digest)
            write_json_atomic(
                workspace / "experiments" / "approvals" / f"config-{digest[:16]}.json",
                {
                    "type": "training_config_approval",
                    "config_sha256": digest,
                    "approved_at": None,
                    "note": " ",
                },
            )
            incomplete = _experiment_chain(workspace)["experiments"][0]["approval"]

        self.assertFalse(incomplete["recorded"])
        self.assertEqual(incomplete["verification"], "incomplete")


if __name__ == "__main__":
    unittest.main()
