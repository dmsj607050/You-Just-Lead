"""Tests for explicit, read-only runtime discovery."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.runtime_probe_service import RuntimeProbeError, latest_runtime_probe, probe_runtime


class RuntimeProbeServiceTests(unittest.TestCase):
    def test_local_probe_persists_real_capacity_assessment(self) -> None:
        runtime = {
            "platform": "Windows test",
            "python": "3.11.0",
            "conda": {"available": True, "executable": "conda.exe", "environments": ["C:/conda/envs/AIC"]},
            "gpu": {
                "available": True,
                "gpus": [{"name": "RTX Test", "memory_total_mb": 49152, "memory_free_mb": 40960, "driver_version": "999"}],
            },
        }
        with tempfile.TemporaryDirectory() as temporary, patch("app.runtime_probe_service.local_runtime_snapshot", return_value=runtime):
            workspace = Path(temporary) / "workspace"
            outcome = probe_runtime(
                workspace,
                target="local",
                required_vram_gb=24,
                conda_strategy="existing",
                conda_environment="AIC",
            )

            self.assertEqual(outcome["probe_id"], "PROBE-0001")
            self.assertEqual(outcome["assessment"]["status"], "local_ready")
            self.assertEqual(outcome["environment"]["status"], "available")
            self.assertEqual(latest_runtime_probe(workspace)["probe_id"], "PROBE-0001")

    def test_local_probe_recommends_server_when_free_memory_is_insufficient(self) -> None:
        runtime = {
            "platform": "Windows test",
            "python": "3.11.0",
            "conda": {"available": False, "executable": None, "environments": []},
            "gpu": {"available": True, "gpus": [{"name": "Small GPU", "memory_total_mb": 8192, "memory_free_mb": 6144, "driver_version": "999"}]},
        }
        with tempfile.TemporaryDirectory() as temporary, patch("app.runtime_probe_service.local_runtime_snapshot", return_value=runtime):
            outcome = probe_runtime(Path(temporary), target="local", required_vram_gb=12, conda_strategy="new")

        self.assertEqual(outcome["assessment"]["status"], "server_needed")
        self.assertIn("本机实际可用显存", outcome["assessment"]["reason"])

    def test_remote_probe_rejects_password_authentication_without_sending_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(RuntimeProbeError) as captured:
                probe_runtime(
                    Path(temporary),
                    target="server",
                    required_vram_gb=8,
                    conda_strategy="existing",
                    server={"host": "gpu.example.test", "user": "ubuntu", "port": 22, "auth": "password", "credential": "not-sent"},
                )

        self.assertIn("SSH-key authentication only", str(captured.exception))


if __name__ == "__main__":
    unittest.main()
