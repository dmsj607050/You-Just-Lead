"""端侧 ArkTS 工程的位置。

端侧工程与后端在**同一个仓库**里，就在 `device/` 子目录下 —— 2026-09-28 之前它是并列的
第二个仓库（`YouJustLead-Harmony`），合并的理由是分仓时**两边谁也检查不了对方**：

- 拿不到另一个 checkout 时，端侧那九条源码检查会静默跳过，`Ran 403 tests` 照样是绿的；
- 发布清单在找不到端侧仓库时，会**干脆不把 HAP 列进产物清单**，于是 `release_ready` 报 true，
  而端侧那半根本没被看过一眼。

合并之后位置只有一处，所以这里不再有"猜"：`device/` 就是它，找不到意味着检出坏了，
由调用方直接失败，而不是安静地少做一半检查。
"""

from __future__ import annotations

from pathlib import Path

#: 端侧工程在仓库里的位置。
DEVICE_SUBDIR = "device"

#: 认这个目录来判断端侧工程的源码在不在。
SOURCE_MARKER = Path("entry") / "src" / "main" / "ets"


def device_project_root(project_root: Path) -> Path:
    """端侧工程的位置：`<仓库根>/device`。

    刻意**不返回 None**：位置是确定的，"在不在"是另一回事，由调用方按自己的口径判断
    （产物清单看 `present`，源码检查直接断言目录存在）。
    """
    return Path(project_root) / DEVICE_SUBDIR


def device_source_present(project_root: Path) -> bool:
    """端侧源码在不在。正常的检出里恒为 True；为 False 说明检出缺了 `device/`。"""
    return (device_project_root(project_root) / SOURCE_MARKER).is_dir()
