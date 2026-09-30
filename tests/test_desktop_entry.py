from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from app.desktop_entry import open_window


class DesktopEntryTests(unittest.TestCase):
    def test_edge_app_keeps_its_launcher_until_the_window_closes(self) -> None:
        profile = Path("B:/isolated-browser-profile")
        with (
            patch("app.desktop_entry.Path.exists", return_value=True),
            patch("app.desktop_entry.Path.mkdir"),
            patch("app.desktop_entry.subprocess.run") as run,
        ):
            open_window("http://127.0.0.1:8765/", profile)

        arguments = run.call_args.args[0]
        self.assertIn("--edge-skip-compat-layer-relaunch", arguments)
        self.assertIn("--disable-background-mode", arguments)
        self.assertEqual(run.call_args.kwargs, {"check": False})


if __name__ == "__main__":
    unittest.main()
