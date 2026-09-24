"""定位鸿蒙端仓库。

端侧与后端是**并列的两个仓库**（各自有 `.git`），不在同一个工作树里，所以路径不能从后端仓库
推出来 —— 只能按约定位置找，或者由调用方显式指定。

规则只有这一处：

1. 环境变量 `YJL_ARKTS_ROOT` 优先；
2. 否则试两个约定位置：与后端仓库**同级**（本机就是这样：后端 `B:\\You Just Lead\\competition-agent`、
   端侧 `B:\\YouJustLead`），以及后端的上一级。

找不到返回 `None` —— 调用方据此**跳过**端侧相关检查，而不是假装端侧不存在或直接失败。
"""

from __future__ import annotations

import os
from pathlib import Path

#: 显式指定端侧仓库根的环境变量名。
DEVICE_REPO_ENV = "YJL_ARKTS_ROOT"

#: 认这个目录来判断"是不是端侧仓库"。
_DEVICE_MARKER = Path("entry") / "src" / "main" / "ets"


def device_repo_root(project_root: Path) -> Path | None:
    """端侧仓库的根；找不到返回 None。"""
    configured = os.environ.get(DEVICE_REPO_ENV)
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    candidates.append(Path(project_root).parent / "YouJustLead")
    candidates.append(Path(project_root).parent.parent / "YouJustLead")
    for candidate in candidates:
        if (candidate / _DEVICE_MARKER).is_dir():
            return candidate
    return None
