"""Regression tests for the atomic JSON helpers in `tools.files`.

They cover a Windows-specific failure mode that used to surface as a flaky scheduler test:
`os.replace` refuses to overwrite a file that another handle has open. When the API server
polled a job record while the worker wrote the next revision, the worker's write blew up with
"access denied" and the job stayed stuck in `running`.

On POSIX the replace succeeds even over an open file, so the "reader still holds it" case
cannot fail there. The assertions still pin the behaviour we require -- they just cannot
detect the regression on Linux/macOS.
"""

from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from tools.files import read_json, write_json_atomic


class AtomicJsonTests(unittest.TestCase):
    def test_write_waits_while_a_reader_still_holds_the_file(self) -> None:
        with TemporaryDirectory() as temporary:
            target = Path(temporary) / "record.json"
            write_json_atomic(target, {"revision": 1})

            holder = target.open("r", encoding="utf-8")
            outcome: dict[str, object] = {}

            def write_next_revision() -> None:
                try:
                    write_json_atomic(target, {"revision": 2})
                    outcome["written"] = True
                except Exception as exc:  # pragma: no cover - only on the broken behaviour
                    outcome["error"] = repr(exc)

            writer = threading.Thread(target=write_next_revision)
            writer.start()
            # Let the writer run into the open handle, then let go of it.
            time.sleep(0.2)
            holder.close()
            writer.join(timeout=5)

            self.assertFalse(writer.is_alive(), "写入线程没有在重试预算内结束")
            self.assertNotIn("error", outcome, outcome.get("error"))
            self.assertTrue(outcome.get("written"))
            self.assertEqual(read_json(target)["revision"], 2)

    def test_failed_replace_reports_the_error_and_leaves_no_scratch_file(self) -> None:
        with TemporaryDirectory() as temporary:
            target = Path(temporary) / "record.json"
            write_json_atomic(target, {"revision": 1})

            with mock.patch("tools.files.os.replace", side_effect=PermissionError(13, "denied")):
                with self.assertRaises(PermissionError):
                    write_json_atomic(target, {"revision": 2})

            # 原来的失败会留下一个 .tmp 残渣，重试也只是重试，不能改判错误。
            self.assertEqual(list(Path(temporary).glob("*.tmp")), [])
            self.assertEqual(read_json(target)["revision"], 1, "失败的写入不该动到已有内容")

    def test_reader_and_writer_stay_consistent_under_concurrency(self) -> None:
        """冒烟：写者不停换版，读者不停读，双方都不该报错、也不该留下残渣。

        这是并发窗口的抽样，不是确定性复现（确定性那条在上面）；它顺带守着"不留 .tmp"。
        """
        with TemporaryDirectory() as temporary:
            target = Path(temporary) / "record.json"
            write_json_atomic(target, {"revision": 0})
            stop = threading.Event()
            errors: list[str] = []

            def reader() -> None:
                while not stop.is_set():
                    try:
                        read_json(target)
                    except Exception as exc:  # pragma: no cover - only on the broken behaviour
                        errors.append(f"read: {exc!r}")
                        return

            def writer() -> None:
                for revision in range(200):
                    try:
                        write_json_atomic(target, {"revision": revision})
                    except Exception as exc:  # pragma: no cover - only on the broken behaviour
                        errors.append(f"write: {exc!r}")
                        return

            reading = threading.Thread(target=reader, daemon=True)
            reading.start()
            writing = threading.Thread(target=writer)
            writing.start()
            writing.join(timeout=30)
            stop.set()
            reading.join(timeout=5)

            self.assertFalse(writing.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(list(Path(temporary).glob("*.tmp")), [])
            self.assertEqual(read_json(target)["revision"], 199)


if __name__ == "__main__":
    unittest.main()
