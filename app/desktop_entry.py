"""Entry point for the packaged Windows desktop app.

`tools/build_desktop_app.ps1` 把这里冻成一个 exe：双击之后它做三件事 ——
建好工作区、在回环地址上起一个后端、开一个无地址栏的应用窗口。

**窗口用系统自带的 Edge 开，不自带浏览器内核。** 这样安装包小两个数量级，
而且用户机器上本来就有 Edge。回退链是「Edge → 默认浏览器」，两条都通不了才会报错，
所以"双击没反应"这种说不清的故障不会出现。

工作区放在用户的「文档」目录下（`文档/YouJustLead`），与鸿蒙端一致 ——
两个端打开的是同一份工作区，而不是各写各的。

**离线**：界面是后端 serve 的，后端不在连页面都取不到。所以每次启动成功之后都会
把"页面 + 最后一次成功响应"落成一份静态离线包（`app/offline_bundle.py`）；
后端起不来时改开那份包，用户至少还看得到上一次的状态。
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from app.api_server import serve, web_root
from app.local_agent_entry import WORKSPACE_DIRECTORIES
from app.offline_bundle import build_offline_bundle, offline_page


APP_NAME = "You Just Lead"

# Edge 的常见安装位置。找不到就退回默认浏览器，不报错。
EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)

# 端口被占时往后试几个。直接失败会把"双击没反应"变成说不清的故障。
PORT_ATTEMPTS = 20

# 等后端起来的上限。它要建目录、开 SQLite，冷启动给足时间。
STARTUP_TIMEOUT_SECONDS = 30


def documents_dir() -> Path:
    """用户的「文档」目录。

    中文 Windows 上它的物理路径仍是 `Documents`，但 OneDrive 可能把它整体重定向，
    所以这里只做默认值，真正的入口是 `user_data_root()` 给的环境变量。
    """
    return Path.home() / "Documents"


def user_data_root() -> Path:
    """用户可见的数据根目录。

    默认是 `文档/YouJustLead`，与鸿蒙端一致 —— 两个端打开的是同一份工作区。
    `YJL_HOME` 直接给出这个根（多实例、测试、便携模式用），不再往里套一层目录名，
    否则 `YJL_HOME=D:\\x` 会变成 `D:\\x\\YouJustLead`，与设置它的人的预期不符。
    """
    override = os.environ.get("YJL_HOME")
    if override:
        return Path(override)
    return documents_dir() / "YouJustLead"


def cache_root() -> Path:
    """缓存放本地应用数据，不放用户的文档目录。

    浏览器 profile 有成千上万个小文件，扔进「文档」会把用户的目录弄脏 ——
    那里只该有工作区，也就是他真正在乎的东西。
    """
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return base / "YouJustLead"


def ensure_workspace() -> tuple[Path, Path]:
    """建好工作区骨架与数据库目录，返回 (项目根, 工作区)。

    骨架与端侧 `LocalWorkspace` 建立的目录一一对应，这样同一个目录两个端都能读。
    """
    data_root = user_data_root()
    workspace = data_root / "workspace" / "current_competition"
    for relative_path in WORKSPACE_DIRECTORIES:
        (workspace / relative_path).mkdir(parents=True, exist_ok=True)
    (data_root / "database").mkdir(parents=True, exist_ok=True)

    specification = workspace / "competition_spec.yaml"
    if not specification.exists():
        specification.write_text(
            "# Fill this after creating or importing a competition project.\n"
            "competition:\n"
            "  name: New competition\n"
            "  task_type: pending\n"
            "evaluation:\n"
            "  primary_metric: pending\n"
            "  direction: maximize\n"
            "approval:\n"
            "  requires_human_confirmation: true\n",
            encoding="utf-8",
        )
    return data_root, workspace


def available_port(preferred: int) -> int:
    """挑一个能绑上的端口。"""
    for candidate in range(preferred, preferred + PORT_ATTEMPTS):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", candidate))
            except OSError:
                continue
            return candidate
    raise SystemExit(f"从 {preferred} 起试了 {PORT_ATTEMPTS} 个端口都被占用，无法启动。")


def start_backend(host: str, port: int, workspace: Path, project_root: Path) -> threading.Thread:
    """在后台线程里起后端，并等到它真的能应答再返回。"""
    thread = threading.Thread(
        target=serve,
        args=(host, port, workspace),
        kwargs={"project_root": project_root},
        name="yjl-backend",
        daemon=True,
    )
    thread.start()

    deadline = time.time() + STARTUP_TIMEOUT_SECONDS
    url = f"http://{host}:{port}/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310 - loopback only
                if response.status == 200:
                    return thread
        except (urllib.error.URLError, OSError):
            time.sleep(0.3)
    raise SystemExit(f"后端在 {STARTUP_TIMEOUT_SECONDS} 秒内没有起来（{url}）。")


def open_window(target: str, profile: Path) -> None:
    """开一个无地址栏的应用窗口，并阻塞到它被关闭。

    `target` 既可以是一个 http 地址，也可以是本地文件路径（离线快照）。

    独立的 `--user-data-dir` 不只是为了干净：共用默认 profile 时系统会把新窗口交给
    已经运行的 Edge 实例，那个进程立刻退出，这里就等不到"用户关掉窗口"这个信号，
    应用会看起来一闪而过。
    """
    url = target if "://" in target else Path(target).as_uri()
    executable = next((item for item in EDGE_CANDIDATES if Path(item).exists()), None)
    if executable is None:
        # 没有 Edge 就用默认浏览器：功能一样，只是窗口带地址栏。
        webbrowser.open(url)
        # 没有窗口句柄可等，只能保持进程存活，靠用户自己关掉控制台结束。
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return

    profile.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            executable,
            f"--app={url}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1440,960",
        ],
        check=False,
    )


def refresh_offline_bundle(base_url: str) -> dict | None:
    """把界面与最后一次成功响应落一份静态离线包。

    失败**不能**挡住启动：离线包是可用性兜底，不是主路径。但要说清楚失败了 ——
    静默失败会让人以为"离线能用"，直到真的断了才发现没有。
    """
    try:
        record = build_offline_bundle(web_root(), cache_root(), base_url)
    except Exception as error:  # noqa: BLE001 - 兜底功能不该拖垮启动
        print(f"离线快照没有生成（{type(error).__name__}: {error}），后端不可达时界面打不开。")
        return None
    if record["missing"]:
        print(f"离线快照里缺这些端点（它们在那次请求里没成功）：{'、'.join(record['missing'])}")
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} desktop app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="不启动后端，直接打开上一次生成的离线快照（只读）",
    )
    args = parser.parse_args()

    if args.offline:
        page = offline_page(cache_root())
        if page is None:
            raise SystemExit("还没有生成过离线快照。先正常启动一次，之后才有的可看。")
        print(f"{APP_NAME}（离线）：{page}")
        open_window(str(page), cache_root() / "browser")
        return

    project_root, workspace = ensure_workspace()
    port = available_port(args.port)

    try:
        start_backend(args.host, port, workspace, project_root)
    except SystemExit as error:
        # 后端起不来时不要只丢一句报错就退出：鸿蒙端能离线看状态，Windows 端也该能。
        page = offline_page(cache_root())
        if page is None:
            raise
        print(str(error))
        print(f"改为打开上一次的离线快照：{page}")
        open_window(str(page), cache_root() / "browser")
        return

    base_url = f"http://{args.host}:{port}/"
    refresh_offline_bundle(base_url)

    print(f"{APP_NAME} 已启动：{base_url}")
    print(f"工作区：{workspace}")
    print("关闭应用窗口即可退出。")

    open_window(base_url, cache_root() / "browser")


if __name__ == "__main__":
    main()
