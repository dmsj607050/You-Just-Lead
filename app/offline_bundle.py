"""把界面与「最后一次成功响应」打成一份静态离线包。

鸿蒙端的界面装在设备上，后端不在也打得开：端侧直接读工作区文件（`LocalStatus.ets`）。
Windows 端不一样 —— 界面是后端 serve 出来的，后端不在连页面都取不到。所以
「后端不在时核心状态仍可读」在 Windows 端要换个做法：把**页面本身**和
**最后一次成功响应**落成一份静态包，桌面外壳在后端不可达时直接用浏览器打开它。

两条设计上的取舍：

* **端点清单不在这里另抄一份**。它从 `web/app.js` 里把 `API.get('/...')` 抠出来 ——
  界面会问什么，就预先取什么。手抄一份迟早会和界面对不上，而那种漂移是静默的。
* **取不到的不放进快照**。快照里只留真实拿到过的东西，缺的那页由界面如实说
  「没有本地数据」。编一个空对象出来会让人以为后端还活着。
"""

from __future__ import annotations

import json
import re
import shutil
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from tools.files import write_json_atomic
from tools.provenance import utc_now


#: 离线包需要跟着走的界面文件。与 `api_server.STATIC_ASSETS` 是同一批：
#: 少一个，离线页就会静默地少一半（缺的脚本让界面直接白屏）。
ASSET_NAMES: tuple[str, ...] = ("index.html", "styles.css", "ui.js", "views.js", "app.js")

#: 快照脚本的文件名。它必须在 `app.js` 之前加载 —— 否则界面已经先去过网络了。
SNAPSHOT_NAME = "snapshot.js"

#: 离线包在缓存目录下的位置。
BUNDLE_DIRECTORY = "offline"

#: 界面取数用的调用形式：`API.get('/api/dashboard')`。
_ENDPOINT_PATTERN = re.compile(r"API\.get\('(/[^']+)'")

#: 单个端点的取数超时。本机回环，给太多没有意义。
FETCH_TIMEOUT_SECONDS = 20.0


def frontend_read_endpoints(app_js: str) -> list[str]:
    """界面会去取的读接口，按出现顺序去重。"""
    found: list[str] = []
    for path in _ENDPOINT_PATTERN.findall(app_js):
        if path not in found:
            found.append(path)
    return found


def fetch_responses(
    base_url: str,
    endpoints: list[str],
    *,
    opener: Callable[[str], Any] | None = None,
    timeout: float = FETCH_TIMEOUT_SECONDS,
) -> tuple[dict[str, Any], list[str]]:
    """逐条取一次，返回 (响应表, 没取到的端点)。

    `opener` 可注入，测试因此不必真的起一个服务。
    """
    open_url = opener or (lambda url: urllib.request.urlopen(url, timeout=timeout))  # noqa: S310 - loopback only
    responses: dict[str, Any] = {}
    missing: list[str] = []
    for path in endpoints:
        try:
            with open_url(base_url.rstrip("/") + path) as response:
                responses[path] = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError):
            missing.append(path)
    return responses, missing


def render_offline_page(html: str) -> str:
    """把线上那份 `index.html` 改成能在文件系统里直接打开的形态。

    两处必须改：资源引用要从 `/xxx` 变成相对路径（`file://` 下 `/` 指的是盘根），
    以及插入快照脚本 —— 而且必须在 `app.js` 之前。
    """
    rendered = html
    for name in ASSET_NAMES:
        rendered = rendered.replace(f'"/{name}"', f'"{name}"')
    marker = '<script src="app.js"></script>'
    if marker not in rendered:
        raise ValueError("index.html 里找不到 app.js 的 script 标签，离线页没有插入点")
    return rendered.replace(marker, f'<script src="{SNAPSHOT_NAME}"></script>\n    {marker}')


def _snapshot_script(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    # `</` 在 JS 文件里是安全的，但转义掉可以避免这份文件被内联进 HTML 时提前收尾。
    escaped = body.replace("</", "<\\/")
    return f"window.__OFFLINE_SNAPSHOT__ = {escaped};\n"


def build_offline_bundle(
    web_root: Path,
    cache_dir: Path,
    base_url: str,
    *,
    opener: Callable[[str], Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """生成离线包，返回一份描述它自己的记录（落一份 `bundle.json` 供审计）。

    页面资源是**原样复制**的：离线页跑的就是线上那份脚本，不是另写一个简化版。
    另写一份的后果是离线页与真实界面慢慢变成两个东西，而没人会发现。
    """
    web_root = Path(web_root)
    directory = Path(cache_dir) / BUNDLE_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)

    for name in ASSET_NAMES:
        source = web_root / name
        if not source.is_file():
            raise FileNotFoundError(f"离线包需要 {name}，但它在 {source} 不存在")
        if name == "index.html":
            (directory / name).write_text(
                render_offline_page(source.read_text(encoding="utf-8")), encoding="utf-8"
            )
        else:
            shutil.copyfile(source, directory / name)

    endpoints = frontend_read_endpoints((web_root / "app.js").read_text(encoding="utf-8"))
    if not endpoints:
        raise ValueError("没能从 app.js 里解析出任何读接口，快照会是空的")
    responses, missing = fetch_responses(base_url, endpoints, opener=opener)

    record = {
        "generated_at": generated_at or utc_now(),
        "base_url": base_url.rstrip("/"),
        "endpoints": endpoints,
        "captured": sorted(responses),
        "missing": missing,
    }
    (directory / SNAPSHOT_NAME).write_text(
        _snapshot_script({"contract": responses.get("/api/research/contract"), **record, "responses": responses}),
        encoding="utf-8",
    )
    write_json_atomic(directory / "bundle.json", record)
    return record


def offline_page(cache_dir: Path) -> Path | None:
    """上一次生成的离线页；没生成过返回 None。

    判"能不能离线打开"看的是**页面在不在**，不看 `bundle.json` ——
    前者才是用户真正需要的东西。
    """
    page = Path(cache_dir) / BUNDLE_DIRECTORY / "index.html"
    return page if page.is_file() else None


__all__ = [
    "ASSET_NAMES",
    "BUNDLE_DIRECTORY",
    "SNAPSHOT_NAME",
    "build_offline_bundle",
    "fetch_responses",
    "frontend_read_endpoints",
    "offline_page",
    "render_offline_page",
]
