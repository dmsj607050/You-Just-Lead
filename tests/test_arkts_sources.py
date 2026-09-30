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

import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import settings_service
from app.research_loop_service import ResearchLoopService
from schemas.research import research_contract
from tools.device_project import device_project_root, device_source_present


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _device_root() -> Path:
    """端侧工程的位置。

    它现在就在本仓库的 `device/` 里，所以**不再跳过**：缺了说明检出坏了，
    要让测试红，而不是安静地少检查一遍（这正是当初分仓留下的病）。
    """
    if not device_source_present(_repo_root()):
        raise AssertionError(f"端侧工程不在 {device_project_root(_repo_root())}；它随本仓库走，不该缺")
    return device_project_root(_repo_root())


def _camel(name: str) -> str:
    """`tabular_classification` → `tabularClassification`。

    端侧 i18n 的键用驼峰，后端那张表用下划线；两边靠这个换算对齐，谁也不用抄一份名字。
    """
    head, *rest = name.split("_")
    return head + "".join(part.capitalize() for part in rest)


#: 要检查的文件（相对端侧工程根）。
CHECKED_FILES = (
    "entry/src/main/ets/view/ResearchLoopPage.ets",
    "entry/src/main/ets/view/DataPage.ets",
    "entry/src/main/ets/view/SettingsPage.ets",
    "entry/src/main/ets/view/ProjectGate.ets",
    "entry/src/main/ets/view/TopBar.ets",
    "entry/src/main/ets/common/BackendClient.ets",
    "entry/src/main/ets/common/I18n.ets",
    "entry/src/main/ets/common/ViewTypes.ets",
    "entry/src/main/ets/common/IconPaths.ets",
    "entry/src/main/ets/pages/Index.ets",
)

_IMPORT = re.compile(r"import\s*\{([^}]*)\}\s*from\s*'([^']+)'")
_INTERFACE = re.compile(r"export\s+interface\s+(\w+)\s*\{([^}]*)\}", re.S)
_INTERFACE_FIELD = re.compile(r"^\s{2}(\w+)\s*[?:]", re.M)
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
    """去掉注释与字符串字面量：括号配平要在"只剩代码"的文本上做。

    单趟扫描，而不是连着跑三个正则 —— 正则之间会互相咬，两种顺序都有假的失败：
    先删行注释，`'https://api.deepseek.com'` 里的 `//` 会把这一行连收尾的 `}` 一起吃掉
    （真的发生过：加了一条带地址的文案，配平就红了）；先删字符串，注释里一个
    `don't` 的单引号又会把后半行当字符串。
    """
    out: list[str] = []
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        if char == '/' and source.startswith('//', index):
            newline = source.find('\n', index)
            if newline == -1:
                break
            index = newline
            continue
        if char == '/' and source.startswith('/*', index):
            end = source.find('*/', index + 2)
            index = length if end == -1 else end + 2
            out.append(' ')
            continue
        if char == "'" or char == '"' or char == '`':
            index += 1
            while index < length and source[index] != char:
                index += 2 if source[index] == '\\' else 1
            index += 1
            out.append('""')
            continue
        out.append(char)
        index += 1
    return ''.join(out)


class DeviceCheckoutTests(unittest.TestCase):
    def test_the_device_project_ships_with_this_repository(self) -> None:
        """端侧工程在本仓库里，随本仓库克隆而克隆。

        这条钉的是一段真实病史：端侧原先在第二个仓库，那九条检查在拿不到它的机器上会
        **静默跳过**，`Ran 403 tests` 照样是绿的。现在缺了它，这里直接红。
        """
        self.assertTrue(device_source_present(_repo_root()))


class ThemeResourceTests(unittest.TestCase):
    """浅色与深色主题提供完全相同的语义颜色令牌。"""

    def test_base_and_dark_themes_declare_every_app_theme_token(self) -> None:
        root = _device_root() / "entry/src/main/resources"
        theme = (root.parent / "ets/common/AppTheme.ets").read_text(encoding="utf-8")
        names = set(re.findall(r"\$r\('app\.color\.([a-z_]+)'\)", theme))
        self.assertTrue(names, "AppTheme 没有引用系统颜色资源")

        resources: dict[str, set[str]] = {}
        for mode in ("base", "dark"):
            payload = json.loads((root / mode / "element/color.json").read_text(encoding="utf-8"))
            resources[mode] = {item["name"] for item in payload["color"]}

        self.assertEqual(names, resources["base"] - {"start_window_background"})
        self.assertEqual(names, resources["dark"] - {"start_window_background"})


class BalanceTests(unittest.TestCase):
    def test_every_checked_file_has_balanced_brackets(self) -> None:
        root = _device_root()

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

        # 字符串里带 `//` 的（地址文案就有）不能被当成行注释，否则整行的收尾 `}` 会被吃掉。
        with_url = _strip_noise("const u = { doc: 'https://a.b/v1' };")
        self.assertEqual(with_url.count("{"), with_url.count("}"))
        self.assertIn("doc", with_url)


class ImportTests(unittest.TestCase):
    def test_everything_the_loop_page_imports_is_exported(self) -> None:
        """手写 import 最容易出的事是"这个名字其实没导出"。"""
        root = _device_root()

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


class EmptyProjectOnboardingTests(unittest.TestCase):
    """零规则项目必须有下一步入口，并在状态切换时强制重建 ArkUI 子树。"""

    def test_empty_project_action_opens_rule_evidence_section(self) -> None:
        root = _device_root()
        index = (root / "entry/src/main/ets/pages/Index.ets").read_text(encoding="utf-8")
        workflow = (root / "entry/src/main/ets/view/WorkflowPage.ets").read_text(encoding="utf-8")
        i18n = (root / "entry/src/main/ets/common/I18n.ets").read_text(encoding="utf-8")

        self.assertRegex(index, r"projectSectionKeys\(\): string\[\][\s\S]*?this\.ruleTotal === 0")
        self.assertIn("ForEach(this.projectSectionKeys()", index)
        self.assertIn("ForEach(this.activePageKeys()", index)
        self.assertIn("this.tr('overview.configureRules')", index)
        self.assertIn("this.openRuleSetup();", index)
        self.assertRegex(index, r"openRuleSetup\(\): void[\s\S]*?workflowInitialSection = 'rules'[\s\S]*?activeNav = 'workflow'")
        self.assertIn("initialSection: this.workflowInitialSection,", index)
        self.assertIn("@Prop initialSection: string = 'status';", workflow)
        self.assertIn("this.section = this.initialSection;", workflow)
        self.assertIn("overview.emptyProjectTitle", i18n)
        self.assertIn("overview.emptyProjectBody", i18n)
        self.assertIn("overview.configureRules", i18n)

    def test_cloud_project_gate_keeps_local_tools_secondary_and_available(self) -> None:
        root = _device_root()
        gate = (root / "entry/src/main/ets/view/ProjectGate.ets").read_text(encoding="utf-8")
        settings = (root / "entry/src/main/ets/view/SettingsPage.ets").read_text(encoding="utf-8")
        i18n = (root / "entry/src/main/ets/common/I18n.ets").read_text(encoding="utf-8")

        self.assertIn("@State localToolsExpanded: boolean = false;", gate)
        self.assertIn("ForEach(this.localToolsKeys()", gate)
        self.assertIn("LocalWorkspaceCard()", gate)
        self.assertIn("LocalWorkspaceCard()", settings)
        self.assertIn("gate.localToolsTitle", i18n)
        self.assertIn("gate.localToolsExpand", i18n)
        self.assertIn("gate.localToolsCollapse", i18n)
        self.assertIn("项目数据保存在本账号的云端工作区", i18n)
        self.assertIn("原始数据只读，规则与结论由你核对", i18n)
        self.assertIn("Project data stays in this account’s cloud workspace", i18n)
        self.assertNotIn("the app only reads and records", i18n)


class ResponsiveHeaderTests(unittest.TestCase):
    """窄宽度时保住项目切换、账户和语言入口，通知也必须真正可用。"""

    def test_project_gate_hides_the_long_tagline_before_language_control_is_clipped(self) -> None:
        root = _device_root()
        gate = (root / "entry/src/main/ets/view/ProjectGate.ets").read_text(encoding="utf-8")

        self.assertIn("@State compactHeader: boolean = false;", gate)
        self.assertIn("const compact = width < 640;", gate)
        self.assertIn("if (!this.compactHeader)", gate)
        self.assertIn("const tight = width < 400;", gate)
        self.assertIn("Number(newArea.width)", gate)

    def test_workspace_header_adapts_and_notification_opens_workflow(self) -> None:
        root = _device_root()
        top_bar = (root / "entry/src/main/ets/view/TopBar.ets").read_text(encoding="utf-8")
        index = (root / "entry/src/main/ets/pages/Index.ets").read_text(encoding="utf-8")

        self.assertIn("const compact = width < 680;", top_bar)
        self.assertIn("const tight = width < 440;", top_bar)
        self.assertIn("this.blockerCount > 0", top_bar)
        self.assertIn("this.onNotificationsClick();", top_bar)
        self.assertRegex(index, r"TopBar\(\{[\s\S]*?onNotificationsClick: \(\) => \{[\s\S]*?activeNav = 'workflow';")
        # 2026-09-30 侧栏改成一列两层后，这里不再有「窄窗口收起面板」那套：
        # 侧栏只剩一列，没有可以退守的图标栏，收了就等于把导航整条藏掉。
        self.assertNotIn("this.panelOpen", index)
        self.assertNotIn("this.compactWorkspace", index)


class GroupedNavigationTests(unittest.TestCase):
    """侧栏是**一列两层**：一级是「工作区 / 研究 / 产出」，二级缩进排在展开的那一行下面。

    这里改过三次，都是跟着版式走，**钉住的东西一直没变**：三个功能域都在共享导航表里、
    都有中英双语文案、当前所在的域与当前页各有激活态、设置始终可达、导航表不重复抄。
    第一次：一列文字里的手风琴；第二次：图标栏 + 面板两列；
    第三次（2026-09-30，按用户要求）：回到单列手风琴，但一级是完整导航行（图标 + 名称 +
    展开箭头），并且**导航项里不许出现说明文字**。
    """

    def test_side_navigation_renders_all_shared_groups_and_items(self) -> None:
        root = _device_root()
        types = (root / "entry/src/main/ets/common/ViewTypes.ets").read_text(encoding="utf-8")
        nav = (root / "entry/src/main/ets/view/SideNav.ets").read_text(encoding="utf-8")
        index = (root / "entry/src/main/ets/pages/Index.ets").read_text(encoding="utf-8")
        i18n = (root / "entry/src/main/ets/common/I18n.ets").read_text(encoding="utf-8")

        for group in ("workspace", "research", "outputs"):
            with self.subTest(group=group):
                # 二级页面的归属
                self.assertIn(f"group: '{group}'", types)
                # 一级功能域：在共享表里，并且带图标（`key: 'x', icon:` 只有 NAV_GROUPS 是这写法）
                self.assertRegex(types, rf"key: '{group}', icon: IconPaths\.\w+")
                self.assertIn(f"key: 'nav.group.{group}'", i18n)
                self.assertRegex(i18n, rf"key: 'nav\.group\.{group}'.*zh: '.+'.*en: '.+'")

        # 两级各读共享表，谁也不自己抄一份
        self.assertIn("export function groupOfNavItem(navKey: string): string", types)
        self.assertIn("export function navItemsOf(groupKey: string): NavItem[]", types)
        self.assertIn("ForEach(NAV_GROUPS, (group: NavGroupSpec) =>", nav)
        self.assertIn("ForEach(navItemsOf(group.key), (item: NavItem) =>", nav)
        self.assertNotIn("return ['workspace'", nav)

        # 一级行：图标 + 名称 + 右侧展开箭头；展开态与当前域各有底色/配色
        self.assertIn("expanded: this.openGroup === group.key,", nav)
        self.assertIn("current: groupOfNavItem(this.activeKey) === group.key,", nav)
        self.assertIn("this.openGroup === group.key", nav)
        self.assertIn(".rotate({ angle: this.expanded ? 90 : 0 })", nav)
        self.assertIn("AppTheme.PRIMARY_SOFT_ALT", nav)

        # 二级行：当前页浅底 + 品牌色；工作流带阻塞角标；设置固定在底部
        self.assertIn("active: this.activeKey === item.key,", nav)
        self.assertIn("badge: item.key === 'workflow' ? this.blockerCount : 0,", nav)
        self.assertIn("this.onSelect(item.key);", nav)
        self.assertIn("label: this.tr('nav.settings'),", nav)
        self.assertIn("icon: IconPaths.SLIDERS,", nav)
        self.assertIn("this.onSelect('settings');", nav)

        # 悬停是**自己画的**一层浅灰绿，不是系统高亮
        self.assertIn("AppTheme.NAV_HOVER", nav)
        self.assertIn(".onHover((isHover: boolean) => {", nav)

        # 外壳：侧栏 + 内容区一行排开；展开哪个域由外壳一个状态说了算
        self.assertIn("SideNav({", index)
        self.assertIn("openGroup: this.openGroup,", index)
        self.assertIn("@State openGroup: string = 'workspace';", index)
        self.assertIn("private toggleGroup(groupKey: string): void", index)
        self.assertIn("private selectPage(key: string): void", index)
        self.assertNotIn("IconRail", index)

    def test_navigation_items_carry_no_explanatory_copy(self) -> None:
        """导航项只有图标 + 名称：不放副标题、不放「用于…」「你可以在这里…」这类说明。

        说明文字属于页面内部、空状态或首次引导。导航条本身只回答「去哪里」。
        """
        root = _device_root() / "entry/src/main/ets"
        source = (root / "view/SideNav.ets").read_text(encoding="utf-8")

        # 侧栏只会去取 `nav.*` 这几个键：名称与域名。取别的键就说明有人塞了说明文案进来。
        # （匹配时要带上引号，否则组件注释里那句 `this.tr()` 也会被算进来。）
        all_calls = re.findall(r"this\.tr\([`'\"]", source)
        nav_calls = re.findall(r"this\.tr\([`']nav\.", source)
        self.assertEqual(len(all_calls), len(nav_calls))

        # 两级行组件都不自己取文案，只渲染父级给的名称；出现 this.tr( 就是自己加了一句
        body = source.split("struct NavRow {")[1].split("\n}")[0]
        self.assertNotIn("this.tr(", body)

        # 一级 / 二级的缩进是两个具名常量，不散落在两处字面量里
        self.assertIn("const CHILD_INDENT: number = 40;", source)
        self.assertIn("const ROOT_INDENT: number = 12;", source)
        self.assertIn("indent: CHILD_INDENT,", source)
        # 一级有两处用它：功能域那一行，和底部的设置
        self.assertEqual(2, source.count("indent: ROOT_INDENT,"))

        # 上一版的图标栏整个删掉了，不是留着不用
        self.assertFalse((root / "view/IconRail.ets").exists())


class WorkflowTimelineLayoutTests(unittest.TestCase):
    """工作流页：宽窗口左时间线 + 右栏（卡在哪 / 下一步 / Agent 在做什么），窄窗口改上下排。

    钉住三件事，都是会静默坏掉的机制：
    一、断点：窄了必须换成单列，否则右栏被挤成读不下去的窄条；
    二、展开态：ArkUI 不会因为 @Builder 里读到的状态变了就重建子树，展开态**必须进 ForEach 的 key**；
    三、右栏说的要是后端真有的东西：缺失项取规则缺口的真实字段，
       「让 Agent 检查工作区」只把问题填好、不替人发出去（发一次是要花积分的）。
    """

    def test_wide_screen_shows_side_column_and_narrow_screen_stacks_it(self) -> None:
        workflow = (_device_root() / "entry/src/main/ets/view/WorkflowPage.ets").read_text(encoding="utf-8")

        self.assertIn("@State compactFlow: boolean = true;", workflow)
        self.assertIn("const compact: boolean = Number(newArea.width) < 900;", workflow)
        self.assertIn("this.compactFlow = compact;", workflow)
        # 宽：一行两列；窄：同一个 else 分支里改成一列
        self.assertIn("} else if (this.compactFlow) {", workflow)
        self.assertIn(".layoutWeight(2)", workflow)
        self.assertIn(".layoutWeight(1)", workflow)
        for builder in ("BlockedCard()", "NextStepCard()", "AgentStateCard()"):
            with self.subTest(builder=builder):
                # 宽窄两条分支都要挂，漏一条这一块就在那种窗口里消失
                self.assertEqual(2, workflow.count(f"this.{builder}"))

    def test_expanded_step_state_is_part_of_the_foreach_key(self) -> None:
        workflow = (_device_root() / "entry/src/main/ets/view/WorkflowPage.ets").read_text(encoding="utf-8")

        self.assertIn("@State expandedStepKey: string = '';", workflow)
        self.assertIn("private isStepExpanded(row: ComponentRow, index: number): boolean", workflow)
        self.assertIn("private stepKeySuffix(row: ComponentRow): string", workflow)
        self.assertIn("${row.labelKey}-${row.state}-${this.stepKeySuffix(row)}", workflow)
        self.assertIn("this.expandedStepKey = this.isStepExpanded(row, index) ? 'none' : row.labelKey;", workflow)

    def test_blocked_card_uses_real_gaps_and_never_sends_a_paid_question(self) -> None:
        workflow = (_device_root() / "entry/src/main/ets/view/WorkflowPage.ets").read_text(encoding="utf-8")

        # 缺失内容列的是规则缺口里的真实字段，不是编出来的清单
        self.assertIn("ForEach(group.fields, (field: string) => {", workflow)
        # 「让 Agent 检查工作区」只预填问题并跳到问答段
        self.assertIn("this.question = this.tr('workflow.agentCheckPrompt');", workflow)
        self.assertIn("this.section = 'ask';", workflow)
        # 详情只写后端真有的三项；抢在「猜测原因」上的话一律不许出现在详情块里
        for key in ("workflow.detailState", "workflow.detailBlocker", "workflow.detailNext"):
            with self.subTest(key=key):
                self.assertIn(key, workflow)


class UiScaleTests(unittest.TestCase):
    """界面整体放大：所有长度都乘 `AppTheme.UI_SCALE`，改一个数就能整体变大变小。

    2026-09-30 按用户要求把字号与组件统一放大。以下两个检查是防止它悄悄退化的：
    一是那个数还在（且只有一个来源），二是**没有漏网的裸字面量** ——
    漏一个就会有两种大小的字并排出现，比整体偏小更难发现。
    """

    def test_theme_exposes_a_single_scale_knob(self) -> None:
        theme = (_device_root() / "entry/src/main/ets/common/AppTheme.ets").read_text(encoding="utf-8")

        self.assertRegex(theme, r"const UI_SCALE: number = \d+(?:\.\d+)?;")
        self.assertIn("static readonly UI_SCALE: number = UI_SCALE;", theme)
        self.assertIn("static readonly TOPBAR_HEIGHT: number = 56 * UI_SCALE;", theme)
        self.assertIn("static readonly SIDEBAR_WIDTH: number = 240 * UI_SCALE;", theme)

    def test_no_view_keeps_an_unscaled_length_literal(self) -> None:
        root = _device_root() / "entry/src/main/ets"
        # 匹配的是「参数就是一个裸数字」的写法；写成 `14 * AppTheme.UI_SCALE` 就不算命中。
        number = r"\d+(?:\.\d+)?"
        scalar = re.compile(
            rf"\.(?:fontSize|lineHeight|strokeWidth|width|height|borderRadius)\({number}\)"
            rf"|\.(?:padding|margin)\({number}\)"
            rf"|\.(?:padding|margin)\(\{{[^}}]*:\s*{number}\s*[,}}]"
        )
        spacing = re.compile(rf"(?:Row|Column|Flex)\(\{{ space: {number}\s*[,}}]")

        for path in sorted(root.rglob("*.ets")):
            if path.name == "AppTheme.ets":
                continue
            for number_, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                with self.subTest(file=path.name, line=number_):
                    self.assertIsNone(scalar.search(line), f"{path.name}:{number_} {line.strip()}")
                    self.assertIsNone(spacing.search(line), f"{path.name}:{number_} {line.strip()}")


class CapabilityCopyTests(unittest.TestCase):
    """内置能力卡片不许把后端那张英文表直接铺出来。

    后端 `training/catalog.py` 是一张固定的英文表（适配器标识、类型、数据契约说明全是英文），
    2026-09-30 用户报的就是这个：界面切成中文，卡片还是 `tabular_classification`。
    现在三层文案各走一个翻译函数，认不出的标识退回原文。

    这里**直接读后端那张表**做对照：后端加了适配器而端侧没加译文，这个测试就红 ——
    这正是这套映射最容易烂掉的地方。
    """

    def _assert_has_both_languages(self, i18n: str, key: str) -> None:
        # 中英两栏都必须有值。英文那栏可能用双引号（句子里带撇号），所以两种引号都收。
        lines = [line for line in i18n.splitlines() if f"key: '{key}'" in line]
        self.assertEqual(1, len(lines), f"{key} 应该有且只有一条")
        self.assertRegex(lines[0], r"zh: ['\"].+['\"]")
        self.assertRegex(lines[0], r"en: ['\"].+['\"]")

    def test_backend_catalog_has_device_translations(self) -> None:
        from training.catalog import RUNNER_CAPABILITIES

        root = _device_root() / "entry/src/main/ets"
        i18n = (root / "common/I18n.ets").read_text(encoding="utf-8")
        format_source = (root / "common/Format.ets").read_text(encoding="utf-8")

        for item in RUNNER_CAPABILITIES:
            runner = str(item["runner"])
            kind = str(item["kind"])
            with self.subTest(runner=runner):
                # 展示名与契约说明都按适配器标识索引
                for prefix in ("cap.runner.", "cap.contract."):
                    self._assert_has_both_languages(i18n, f"{prefix}{_camel(runner)}")
                # 翻译函数里必须有这个标识的分支，否则就是"键加了但没接上"
                self.assertIn(f"runner === '{runner}'", format_source)

            with self.subTest(kind=kind):
                self._assert_has_both_languages(i18n, f"cap.kind.{_camel(kind)}")
                self.assertIn(f"kind === '{kind}'", format_source)

    def test_cards_render_translations_not_raw_backend_fields(self) -> None:
        grid = (_device_root() / "entry/src/main/ets/view/CapabilityGrid.ets").read_text(encoding="utf-8")

        self.assertIn("Text(runnerLabel(this.lang, item.runner))", grid)
        self.assertIn("Text(runnerKindLabel(this.lang, item.kind))", grid)
        self.assertIn("runnerContractLabel(this.lang, item.runner, item.data_contract)", grid)
        # 原样铺后端字段的写法必须一个都不剩
        for banned in ("Text(item.runner)", "Text(item.kind)", "Text(item.data_contract)"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, grid)
        # 中文界面下搜「分类」也要能搜到，所以译文也要进搜索
        self.assertIn("runnerLabel(this.lang, item.runner).toLowerCase().includes(key)", grid)
        # 切语言要真的重建卡片：语言进 ForEach 的 key
        self.assertIn("(item: RunnerCapability) => `${item.runner}-${this.gridView}-${this.lang}`", grid)


class PageHeadingTests(unittest.TestCase):
    """页面顶部不再重复页面名：左侧面板里高亮的那一项已经写着它。

    2026-09-30 按用户要求删掉（起因是「文献」页顶部又写了一遍「文献」）。
    例外是**不在导航里的页面** —— 设置（侧栏底部的一级入口，侧栏上不再有它的名字）
    与两个本地离线工具页，它们没有别的地方显示名字，各自的大标题保留。
    """

    def test_page_header_no_longer_renders_a_title(self) -> None:
        widgets = (_device_root() / "entry/src/main/ets/view/Widgets.ets").read_text(encoding="utf-8")
        header = widgets.split("export struct PageHeader {")[1].split("\n}")[0]

        self.assertNotIn("@Prop title", header)
        self.assertNotIn("FontWeight.Bold", header)
        # 现状那行还在，刷新入口也还在：删的只是标题
        self.assertIn("@Prop status: string = '';", header)
        self.assertIn("this.onRefresh();", header)

    def test_every_nav_page_drops_the_duplicate_title(self) -> None:
        ets = _device_root() / "entry/src/main/ets"
        names = ("pages/Index.ets", "view/WorkflowPage.ets", "view/LiteraturePage.ets",
                 "view/ExperimentPage.ets", "view/DataPage.ets", "view/WritingPage.ets",
                 "view/TracePage.ets", "view/ReproductionPage.ets", "view/ResearchLoopPage.ets")
        for name in names:
            with self.subTest(page=name):
                source = (ets / name).read_text(encoding="utf-8")
                blocks = re.findall(r"PageHeader\(\{[\s\S]*?\n      \}\)", source)
                # 页面里必须还剩着这条状态条，只是不再传标题
                self.assertTrue(blocks)
                for block in blocks:
                    self.assertNotIn("title:", block)

    def test_pages_without_a_panel_entry_keep_their_own_heading(self) -> None:
        view = _device_root() / "entry/src/main/ets/view"
        for name in ("SettingsPage.ets", "LocalStatusPage.ets", "LocalRulePage.ets"):
            with self.subTest(page=name):
                self.assertIn("FontWeight.Bold", (view / name).read_text(encoding="utf-8"))


class ReproductionRuntimeCopyTests(unittest.TestCase):
    """云端 HAP 的容器故障提示不能要求评委安装 Windows 本地工具。"""

    def test_missing_runtime_copy_points_to_the_server_administrator(self) -> None:
        i18n = (_device_root() / "entry/src/main/ets/common/I18n.ets").read_text(encoding="utf-8")
        record = next(line for line in i18n.splitlines() if "key: 'repro.engineMissingDetail'" in line)

        self.assertIn("联系平台管理员", record)
        self.assertIn("服务端容器配置", record)
        self.assertIn("诊断信息：{0}", record)
        self.assertNotIn("Docker Desktop", record)
        self.assertNotIn("WSL2", record)


class CreditBalanceRefreshTests(unittest.TestCase):
    """模型问答结束后，项目页余额应从账户接口更新。"""

    def test_workflow_notifies_parent_and_parent_refreshes_account(self) -> None:
        root = _device_root()
        index = (root / "entry/src/main/ets/pages/Index.ets").read_text(encoding="utf-8")
        workflow = (root / "entry/src/main/ets/view/WorkflowPage.ets").read_text(encoding="utf-8")

        self.assertIn("onCreditsChanged: () => void", workflow)
        self.assertIn("@Prop creditBalance: number = 0;", workflow)
        self.assertIn("Text(this.creditBalance.toFixed(2))", workflow)
        self.assertRegex(workflow, r"async ask\(\): Promise<void>[\s\S]*?finally \{[\s\S]*?this\.onCreditsChanged\(\);")
        self.assertRegex(index, r"WorkflowPage\(\{[\s\S]*?creditBalance: this\.creditBalance,[\s\S]*?onCreditsChanged: \(\) => \{[\s\S]*?this\.refreshAccount\(\);")
        self.assertRegex(index, r"refreshAccount\(\): Promise<void>[\s\S]*?this\.applyAccount\(await fetchAccount\(\)\)")


class EmptyDataAuditPageTests(unittest.TestCase):
    def test_data_page_handles_a_project_without_an_audit_report(self) -> None:
        root = _device_root()
        page = (root / "entry/src/main/ets/view/DataPage.ets").read_text(encoding="utf-8")
        i18n = (root / "entry/src/main/ets/common/I18n.ets").read_text(encoding="utf-8")

        self.assertIn("Object.keys(report).length === 0", page)
        self.assertIn("this.audit = null;", page)
        self.assertIn("data.noAuditReport", page)
        self.assertIn("this.tr('data.cloudAuditUnavailable')", page)
        self.assertIn("this.tr('data.noAuditReport')", page)
        self.assertIn("尚未生成数据审计报告", i18n)
        self.assertIn("this.tr('data.viewNextSteps')", page)
        self.assertIn("this.onOpenNextSteps()", page)

        index = (root / "entry/src/main/ets/pages/Index.ets").read_text(encoding="utf-8")
        self.assertIn("this.workflowInitialSection = 'actions';", index)
        self.assertIn("this.openWorkflowNextSteps();", index)

    def test_empty_paper_package_explains_generation_boundary_and_links_to_workflow(self) -> None:
        root = _device_root()
        page = (root / "entry/src/main/ets/view/WritingPage.ets").read_text(encoding="utf-8")
        index = (root / "entry/src/main/ets/pages/Index.ets").read_text(encoding="utf-8")
        i18n = (root / "entry/src/main/ets/common/I18n.ets").read_text(encoding="utf-8")

        self.assertIn("this.tr('writing.viewNextSteps')", page)
        self.assertIn("this.onOpenNextSteps();", page)
        self.assertIn("onOpenNextSteps: () => {", index)
        self.assertIn("尚不能在页面中触发生成", i18n)

    def test_empty_experiment_ledger_links_to_workflow_without_running_training(self) -> None:
        root = _device_root()
        page = (root / "entry/src/main/ets/view/ExperimentPage.ets").read_text(encoding="utf-8")
        index = (root / "entry/src/main/ets/pages/Index.ets").read_text(encoding="utf-8")
        i18n = (root / "entry/src/main/ets/common/I18n.ets").read_text(encoding="utf-8")

        self.assertIn("this.tr('exp.viewNextSteps')", page)
        self.assertIn("this.onOpenNextSteps();", page)
        self.assertIn("onOpenNextSteps: () => {", index)
        self.assertIn("this.openWorkflowNextSteps();", index)
        self.assertIn("查看下一步建议", i18n)
        self.assertIn("@Prop cloudAccount: boolean = false;", page)
        self.assertIn("cloudAccount: this.authenticated", index)
        self.assertIn("this.CloudExecutionNote()", page)
        self.assertIn("当前云端 HAP 没有数据上传入口和训练执行器", i18n)

    def test_known_workflow_actions_and_evidence_have_translations(self) -> None:
        root = _device_root()
        workflow = (root / "entry/src/main/ets/view/WorkflowPage.ets").read_text(encoding="utf-8")
        i18n = (root / "entry/src/main/ets/common/I18n.ets").read_text(encoding="utf-8")

        self.assertIn("Text(this.actionText(item.action))", workflow)
        self.assertIn("Text(this.actionText(item.evidence, true))", workflow)
        self.assertIn("this.tr('workflow.actionHint')", workflow)
        self.assertIn("No data_statistics.json exists.", workflow)
        self.assertIn("尚未生成 data_statistics.json。", i18n)

    def test_harmony_hides_cloud_filesystem_roots_in_path_labels(self) -> None:
        root = _device_root()
        formatter = (root / "entry/src/main/ets/common/Format.ets").read_text(encoding="utf-8")

        self.assertIn("export function workspacePathLabel", formatter)
        self.assertIn("normalizedValue.startsWith('/') || hasDrivePrefix", formatter)
        for name in ("DataPage.ets", "ExperimentPage.ets", "WritingPage.ets", "TracePage.ets"):
            with self.subTest(page=name):
                page = (root / f"entry/src/main/ets/view/{name}").read_text(encoding="utf-8")
                self.assertIn("workspacePathLabel", page)


class ContractShapeTests(unittest.TestCase):
    """端侧接口声明的东西，必须与后端**实际在发**的一致 —— 这条不依赖编译器。

    它盯的是一个真实发生过的错：后端给契约加了 `job_statuses` / `step_statuses` 之后，
    端侧的 `ResearchContract` 没跟上，于是那两个循环解析成 `any`、属性不存在，编译报 8 个错。
    在有构建链的机器上编译器会拦；这里让没有构建链的机器也拦得住。
    """

    #: 快照里端侧暂时不渲染的顶层键。例外必须显式写出来 —— 漏字段是编译期才会炸的错，
    #: 而"多声明一个没人看的字段"是另一回事。
    IGNORED_SNAPSHOT_KEYS = ("edges",)

    def _client_source(self) -> str:
        root = _device_root()
        return (root / "entry/src/main/ets/common/BackendClient.ets").read_text(encoding="utf-8")

    def _declared(self, interface: str) -> set[str]:
        source = self._client_source()
        for match in _INTERFACE.finditer(source):
            if match.group(1) == interface:
                return set(_INTERFACE_FIELD.findall(match.group(2)))
        return set()

    def test_the_contract_interface_declares_exactly_what_the_backend_sends(self) -> None:
        declared = self._declared("ResearchContract")
        self.assertTrue(declared, "没有解析出 ResearchContract 的字段，正则可能失效了")

        served = set(research_contract())
        self.assertEqual(sorted(served - declared), [], "后端在发、端侧接口没声明 —— 这种漏项要到编译时才炸")
        self.assertEqual(sorted(declared - served), [], "端侧声明了后端不发的字段")

    def test_the_snapshot_interface_declares_exactly_what_the_backend_sends(self) -> None:
        declared = self._declared("ResearchLoopSnapshot")
        self.assertTrue(declared, "没有解析出 ResearchLoopSnapshot 的字段，正则可能失效了")

        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            served = set(ResearchLoopService(workspace, workspace).snapshot())

        missing = served - declared - set(self.IGNORED_SNAPSHOT_KEYS)
        self.assertEqual(sorted(missing), [], "后端在发、端侧接口没声明 —— 这种漏项要到编译时才炸")
        self.assertEqual(sorted(declared - served), [], "端侧声明了后端不发的字段")

    def test_the_provider_interface_declares_exactly_what_the_backend_sends(self) -> None:
        """模型来源接口与后端 `providers_status()` 逐字段对齐。

        端侧「设置 → 模型」这一段是可以改配置的，字段对不齐的表现是设置页整段读不出来。
        这一条同时钉住密钥那一侧：后端只回 `has_key` / `key_source` 这种「有没有」，
        端侧接口里**不该出现任何能拿到密钥本身的字段**。

        不碰这台机器真实的东西：`APPDATA` 指向临时目录，凭据库换成「不可用」。
        """
        declared = self._declared("ProviderSettings")
        self.assertTrue(declared, "没有解析出 ProviderSettings 的字段，正则可能失效了")

        with tempfile.TemporaryDirectory() as temporary, \
                patch.dict(os.environ, {"APPDATA": temporary}, clear=False), \
                patch.object(settings_service, "_keyring", return_value=None):
            served = set(settings_service.providers_status())

        self.assertEqual(sorted(served - declared), [], "后端在发、端侧接口没声明 —— 这种漏项要到编译时才炸")
        self.assertEqual(sorted(declared - served), [], "端侧声明了后端不发的字段")


if __name__ == "__main__":
    unittest.main()
