"""ArkTS 源码的结构检查：在**没有 DevEco 构建链**的机器上能自动验的那一部分。

端侧工程只能在本机的 DevEco 里编译，CI 里没有这套构建链。所以这里的检查刻意只做
**能确定对错**的事，不假装自己是编译器：

1. 括号配平（跳过字符串与注释）—— 少一个 `}` 是这类手写代码最常见的致命错；
2. 我用到的每个符号，都真的在它 import 的那个文件里 export 过；
3. 页面里出现的每一个 `this.xxx(` 调用，都是这个 struct 上真的有的方法/字段。

**能力边界（别把结论放大）**：它证明不了类型对、也证明不了 ArkTS 的语法限制都守住了
（例如 `@Builder` 的参数规则、`@State` 的可观察性）。那部分要装机验收，见
`docs/architecture.md` D9。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tools.device_repo import DEVICE_REPO_ENV, device_repo_root


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _device_root() -> Path | None:
    return device_repo_root(_repo_root())


#: 要检查的文件（相对端侧仓库根）。
CHECKED_FILES = (
    "entry/src/main/ets/view/ResearchLoopPage.ets",
    "entry/src/main/ets/common/BackendClient.ets",
    "entry/src/main/ets/common/I18n.ets",
    "entry/src/main/ets/common/ViewTypes.ets",
    "entry/src/main/ets/common/IconPaths.ets",
    "entry/src/main/ets/pages/Index.ets",
)

_STRING = re.compile(r"'[^'\n]*'|\"[^\"\n]*\"|`[^`]*`")
_LINE_COMMENT = re.compile(r"//[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_IMPORT = re.compile(r"import\s*\{([^}]*)\}\s*from\s*'([^']+)'")
_MEMBER_CALL = re.compile(r"this\.([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_MEMBER_FIELD = re.compile(r"this\.([A-Za-z_][A-Za-z0-9_]*)")

#: struct 上的成员声明。刻意写得窄：宁可漏掉一种写法而让检查变弱，
#: 也不要放宽到把 `Column(` 这种容器调用当成"声明"，那样这条检查就白做了。
#:
#: 最后一条靠**缩进**认方法：struct 的成员都在 2 个空格上，而 builder / build 里面的
#: 容器调用至少 4 个空格。`@Builder` 那种没写 `private` 的也在这一条里。
_DECLARATIONS = (
    re.compile(r"@State\s+(\w+)"),
    re.compile(r"@Prop\s+(\w+)"),
    re.compile(r"@StorageLink\([^)]*\)\s*(\w+)"),
    re.compile(r"@Builder\s*\n\s*(\w+)\s*\("),
    re.compile(r"\n\s{2}(?:(?:private|public|async)\s+)*(\w+)\s*\("),
)


def _strip_noise(source: str) -> str:
    """去掉注释与字符串字面量：括号配平要在"只剩代码"的文本上做。"""
    without_blocks = _BLOCK_COMMENT.sub(" ", source)
    without_lines = _LINE_COMMENT.sub(" ", without_blocks)
    return _STRING.sub('""', without_lines)


class BalanceTests(unittest.TestCase):
    def test_every_checked_file_has_balanced_brackets(self) -> None:
        root = _device_root()
        if root is None:
            self.skipTest(f"端侧仓库不在这台机器上；设 {DEVICE_REPO_ENV} 指向它即可一并检查")

        for relative in CHECKED_FILES:
            code = _strip_noise((root / relative).read_text(encoding="utf-8"))
            with self.subTest(file=relative):
                self.assertEqual(code.count("{"), code.count("}"), f"{relative} 的花括号不配平")
                self.assertEqual(code.count("("), code.count(")"), f"{relative} 的圆括号不配平")

    def test_the_stripper_actually_removes_strings_and_comments(self) -> None:
        """自检：抽取失败时上面的配平检查会**空着通过**，那等于没有保护。"""
        stripped = _strip_noise("const a = '}{'; // }}\n/* { */ const b = 1;")

        self.assertEqual(stripped.count("{"), stripped.count("}"))
        self.assertNotIn("}{", stripped)


class ImportTests(unittest.TestCase):
    def test_everything_the_loop_page_imports_is_exported(self) -> None:
        """手写 import 最容易出的事是"这个名字其实没导出"。"""
        root = _device_root()
        if root is None:
            self.skipTest(f"端侧仓库不在这台机器上；设 {DEVICE_REPO_ENV} 指向它即可一并检查")

        page = root / "entry/src/main/ets/view/ResearchLoopPage.ets"
        source = page.read_text(encoding="utf-8")
        for names, module in _IMPORT.findall(source):
            target = (page.parent / f"{module}.ets").resolve()
            with self.subTest(module=module):
                self.assertTrue(target.is_file(), f"{module} 不存在：{target}")
                exported = target.read_text(encoding="utf-8")
                for name in (item.strip() for item in names.split(",")):
                    if not name:
                        continue
                    with self.subTest(name=name):
                        self.assertRegex(
                            exported,
                            rf"export\s+(interface|function|struct|const|class)\s+{re.escape(name)}\b",
                            f"{module} 没有导出 {name}",
                        )


class MemberTests(unittest.TestCase):
    def _declared(self, code: str) -> set[str]:
        found: set[str] = set()
        for pattern in _DECLARATIONS:
            for match in pattern.findall(code):
                if match:
                    found.add(match)
        return found

    def test_the_declaration_extraction_finds_the_members(self) -> None:
        """自检：一条都抽不到的话，下面那条会**空着通过**。"""
        root = _device_root()
        if root is None:
            self.skipTest(f"端侧仓库不在这台机器上；设 {DEVICE_REPO_ENV} 指向它即可一并检查")

        code = _strip_noise((root / "entry/src/main/ets/view/ResearchLoopPage.ets").read_text(encoding="utf-8"))
        declared = self._declared(code)

        self.assertGreaterEqual(len(declared), 25, f"只抽到 {len(declared)} 个成员，正则可能失效了")
        for expected in ("aboutToAppear", "build", "load", "step", "backfill", "hypotheses", "nextActionName"):
            with self.subTest(member=expected):
                self.assertIn(expected, declared)

    def test_every_this_call_on_the_loop_page_exists_in_that_struct(self) -> None:
        """`this.xxx(` 里的 xxx 必须是这个 struct 上真的有的东西。

        漏改名字、或者把方法写成另一个页面的名字，在这台机器上编译不出来也看不出来。
        """
        root = _device_root()
        if root is None:
            self.skipTest(f"端侧仓库不在这台机器上；设 {DEVICE_REPO_ENV} 指向它即可一并检查")

        page = root / "entry/src/main/ets/view/ResearchLoopPage.ets"
        code = _strip_noise(page.read_text(encoding="utf-8"))
        declared = self._declared(code)

        used = set(_MEMBER_CALL.findall(code)) | set(_MEMBER_FIELD.findall(code))
        unknown = sorted(used - declared)
        self.assertEqual(unknown, [], f"这些 this.xxx 在 struct 上没有定义：{unknown}")

    def test_the_unknown_member_check_actually_catches_a_typo(self) -> None:
        """证明这条检查抓得住东西：换一个不存在的成员名就该被判不通过。"""
        code = _strip_noise("struct X {\n  private real(): void {\n  }\n\n  build() {\n    this.reel();\n  }\n}")
        declared = self._declared(code)

        self.assertIn("real", declared)
        self.assertEqual(sorted(set(_MEMBER_CALL.findall(code)) - declared), ["reel"])


if __name__ == "__main__":
    unittest.main()
