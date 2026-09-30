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
        self.assertIn("@State compactWorkspace: boolean = true;", index)
        self.assertIn(".minContentWidth(this.compactWorkspace ? 260 : 420)", index)
        self.assertIn("const compact = Number(newArea.width) < 680;", index)


class GroupedNavigationTests(unittest.TestCase):
    """端侧侧栏按科研流程分组，并保证中英文都有分组标题。"""

    def test_side_navigation_renders_all_shared_groups_and_items(self) -> None:
        root = _device_root()
        types = (root / "entry/src/main/ets/common/ViewTypes.ets").read_text(encoding="utf-8")
        side_nav = (root / "entry/src/main/ets/view/SideNav.ets").read_text(encoding="utf-8")
        i18n = (root / "entry/src/main/ets/common/I18n.ets").read_text(encoding="utf-8")

        for group in ("workspace", "research", "outputs"):
            with self.subTest(group=group):
                self.assertIn(f"group: '{group}'", types)
                self.assertIn(f"key: 'nav.group.{group}'", i18n)
                self.assertRegex(i18n, rf"key: 'nav\.group\.{group}'.*zh: '.+'.*en: '.+'")

        self.assertIn("return ['workspace', 'research', 'outputs'];", side_nav)
        self.assertIn("this.tr(`nav.group.${groupKey}`)", side_nav)
        self.assertIn("ForEach(this.itemsForGroup(groupKey)", side_nav)
        self.assertIn("this.onSelect(item.key);", side_nav)
        self.assertIn("item.key === 'workflow' && this.blockerCount > 0", side_nav)
        self.assertIn(".scrollBar(BarState.Auto)", side_nav)
        self.assertIn("this.onSelect('settings');", side_nav)
        self.assertNotIn("nav.quote", side_nav)
        self.assertNotIn("Blank()", side_nav)


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
