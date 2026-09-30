import { common } from '@kit.AbilityKit';
import { i18n } from '@kit.LocalizationKit';
import { preferences } from '@kit.ArkData';

/**
 * 应用内多语言。
 *
 * 没有走鸿蒙的资源限定词方案（`$r('app.string.x')` + `resources/en_US`），原因有两个：
 * 一是切换语言要求即时生效，资源限定词只能跟随系统语言、改语言通常要重启；
 * 二是本项目大量文案是在 TS 里拼出来的（Format.ets 的标签映射、步骤名数组、
 * 带数字的句子），那些地方需要的是 string 而不是 Resource。
 *
 * 做法是「一张文案表 + AppStorage 广播」：
 * 选中的语言存在模块变量里，同时写进 AppStorage 的 LANG_KEY；
 * 需要跟着语言重绘的组件加 `@StorageLink(LANG_KEY) lang: string = LANG_ZH;` 订阅即可。
 */

/** AppStorage 里的语言键。装饰器只接受字面量，组件里要写同样的字符串。 */
export const LANG_KEY: string = 'lang';

export const LANG_ZH: string = 'zh';
export const LANG_EN: string = 'en';

/** 偏好存储的文件名与键名。 */
const PREF_STORE: string = 'youjustlead_settings';
const PREF_LANG: string = 'lang';

/** 一条文案：中英对照。 */
interface Entry {
  key: string;
  zh: string;
  en: string;
}

/**
 * 全部文案。
 *
 * 键名按模块前缀分组（`nav.` / `menu.` / `workflow.` …），新增文案直接往对应段里加。
 * 键不存在时 `t()` 会原样返回键名，界面上会直接暴露出来，不会被静默忽略。
 */
const ENTRIES: Entry[] = [
  // ---- 通用 ----
  { key: 'common.refresh', zh: '刷新', en: 'Refresh' },
  { key: 'common.retry', zh: '重试', en: 'Retry' },
  { key: 'common.cancel', zh: '取消', en: 'Cancel' },
  { key: 'common.connectionFailed', zh: '连接失败', en: 'Connection failed' },
  { key: 'common.loading', zh: '正在读取后端数据…', en: 'Reading backend data…' },
  { key: 'common.none', zh: '无', en: 'None' },

  // ---- 云账号 ----
  { key: 'auth.subtitle', zh: '登录后进入独立的科研工作区', en: 'Sign in to open your private research workspace' },
  { key: 'auth.loading', zh: '正在检查登录状态…', en: 'Checking your session…' },
  { key: 'auth.username', zh: '用户名', en: 'Username' },
  { key: 'auth.usernameHint', zh: '3–32 位字母、数字或 . _ -', en: '3–32 letters, numbers, or . _ -' },
  { key: 'auth.password', zh: '密码', en: 'Password' },
  { key: 'auth.passwordHint', zh: '至少 8 个字符', en: 'At least 8 characters' },
  { key: 'auth.login', zh: '登录', en: 'Sign in' },
  { key: 'auth.register', zh: '注册并领取 100 积分', en: 'Create account and get 100 credits' },
  { key: 'auth.working', zh: '正在连接…', en: 'Connecting…' },
  { key: 'auth.creditGrant', zh: '新账号一次性赠送 100 积分；1 积分 = 1,000 输入与输出 token。', en: 'New accounts receive 100 credits once; 1 credit = 1,000 input and output tokens.' },
  { key: 'auth.noKey', zh: '模型由平台连接 DeepSeek，无需填写 API Key。', en: 'The platform connects to DeepSeek; no API key is needed.' },
  { key: 'auth.haveAccount', zh: '已有账号？', en: 'Already have an account?' },
  { key: 'auth.needAccount', zh: '还没有账号？', en: 'New here?' },
  { key: 'auth.goLogin', zh: '去登录', en: 'Sign in' },
  { key: 'auth.goRegister', zh: '去注册', en: 'Create one' },
  { key: 'auth.sessionExpired', zh: '登录状态已失效，请重新登录。', en: 'Your session expired. Please sign in again.' },
  { key: 'auth.signOut', zh: '退出登录', en: 'Sign out' },
  { key: 'auth.balance', zh: '剩余积分', en: 'Credits remaining' },
  { key: 'auth.registered', zh: '账号已创建，已赠送 100 积分。', en: 'Account created with 100 credits.' },

  // ---- 顶栏 ----
  { key: 'topbar.tagline', zh: '让研究更自由地发生', en: 'Let research happen freely' },
  { key: 'topbar.notifications', zh: '通知', en: 'Notifications' },
  { key: 'topbar.avatarHint', zh: '账户菜单', en: 'Account menu' },
  { key: 'topbar.projectHint', zh: '当前项目，点击切换', en: 'Current project; click to switch' },
  { key: 'topbar.noProject', zh: '尚未配置竞赛', en: 'No competition configured' },

  // ---- 侧栏 ----
  { key: 'nav.group.workspace', zh: '工作区', en: 'Workspace' },
  { key: 'nav.group.research', zh: '研究', en: 'Research' },
  { key: 'nav.group.outputs', zh: '产出', en: 'Outputs' },
  { key: 'nav.overview', zh: '概览', en: 'Overview' },
  { key: 'nav.workflow', zh: '工作流', en: 'Workflow' },
  { key: 'nav.experiment', zh: '实验', en: 'Experiments' },
  { key: 'nav.literature', zh: '文献', en: 'Literature' },
  { key: 'nav.data', zh: '数据', en: 'Data' },
  { key: 'nav.writing', zh: '写作', en: 'Writing' },
  { key: 'nav.trace', zh: '溯源', en: 'Trace' },
  { key: 'nav.reproduction', zh: '复现', en: 'Reproduce' },
  { key: 'nav.loop', zh: '研究循环', en: 'Research loop' },
  { key: 'nav.settings', zh: '设置', en: 'Settings' },
  // ---- 账户菜单 ----
  { key: 'menu.workspace', zh: '本地工作区', en: 'Local workspace' },
  { key: 'menu.badge', zh: '云端', en: 'Cloud' },
  { key: 'menu.refresh', zh: '刷新数据', en: 'Refresh data' },
  { key: 'menu.blockedTitle', zh: '待处理阻塞项', en: 'Open blockers' },
  { key: 'menu.blockedHint', zh: '阻塞项来自后端账本，处理完自动消失', en: 'Blockers come from the backend ledger and clear once resolved' },
  { key: 'menu.blockedUnit', zh: '{0} 条', en: '{0} open' },
  { key: 'menu.blockedNone', zh: '全部已处理', en: 'All clear' },
  { key: 'menu.language', zh: '语言', en: 'Language' },
  { key: 'menu.switchProject', zh: '切换项目', en: 'Switch project' },
  { key: 'menu.backend', zh: '后端连接', en: 'Backend' },
  { key: 'menu.backendOk', zh: '正常', en: 'Online' },
  { key: 'menu.backendDown', zh: '离线', en: 'Offline' },
  { key: 'menu.messages', zh: '消息', en: 'Messages' },
  { key: 'menu.settings', zh: '设置', en: 'Settings' },
  { key: 'menu.quit', zh: '退出应用', en: 'Quit app' },
  { key: 'menu.langZh', zh: '简体中文', en: '简体中文' },
  { key: 'menu.langEn', zh: 'English', en: 'English' },

  // ---- 概览 ----
  { key: 'overview.status', zh: '{0} · 数据 {1} 个文件（{2} 处问题）· 研究记录 {3} · 已完成实验 {4}', en: '{0} · {1} data files ({2} issues) · {3} research records · {4} completed experiments' },
  { key: 'overview.emptyStatus', zh: '先核对竞赛规则，再导入数据', en: 'Review the competition rules, then add data' },
  { key: 'overview.section.project', zh: '项目', en: 'Project' },
  { key: 'overview.section.workflow', zh: '工作流', en: 'Workflow' },
  { key: 'overview.section.capabilities', zh: '内置能力', en: 'Capabilities' },
  { key: 'overview.section.recent', zh: '最近动态', en: 'Recent' },
  { key: 'overview.field.competition', zh: '竞赛', en: 'Competition' },
  { key: 'overview.field.taskType', zh: '任务类型', en: 'Task type' },
  { key: 'overview.field.metric', zh: '主指标', en: 'Primary metric' },
  { key: 'overview.field.adapter', zh: '适配器', en: 'Adapter' },
  { key: 'overview.field.lastUpdated', zh: '最后更新', en: 'Last updated' },
  { key: 'overview.field.ruleFields', zh: '规则字段', en: 'Rule fields' },
  { key: 'overview.field.blockers', zh: '阻塞项', en: 'Blockers' },
  { key: 'overview.nextStep', zh: '下一步', en: 'Next step' },
  { key: 'overview.noPendingActions', zh: '当前没有待办动作', en: 'No pending actions' },
  { key: 'overview.recentUpdates', zh: '最近更新', en: 'Recent updates' },
  { key: 'overview.noRecords', zh: '暂无记录', en: 'No records yet' },
  { key: 'overview.emptyProjectTitle', zh: '先从竞赛规则开始', en: 'Start with the competition rules' },
  { key: 'overview.emptyProjectBody', zh: '导入官方规则来源，逐项核对证据并由你确认后，再继续数据审计与实验。', en: 'Add the official rule source, review each piece of evidence, and confirm it before data auditing and experiments.' },
  { key: 'overview.configureRules', zh: '开始核对规则', en: 'Review rules' },

  // ---- 项目选择页 ----
  { key: 'gate.title', zh: '选择项目', en: 'Choose a project' },
  { key: 'gate.current', zh: '当前', en: 'Current' },
  { key: 'gate.enter', zh: '进入', en: 'Open' },
  { key: 'gate.delete', zh: '删除', en: 'Delete' },
  { key: 'gate.deleteConfirm', zh: '确认删除', en: 'Confirm delete' },
  { key: 'gate.createdAt', zh: '创建于 {0}', en: 'Created {0}' },
  { key: 'gate.newTitle', zh: '新建项目', en: 'New project' },
  { key: 'gate.namePlaceholder', zh: '项目名称，例如：遥感水体分割 v2', en: 'Project name, e.g. Water segmentation v2' },
  { key: 'gate.create', zh: '创建并进入', en: 'Create and open' },
  { key: 'gate.creating', zh: '正在创建…', en: 'Creating…' },
  { key: 'gate.nameRequired', zh: '项目名不能为空，最多 60 个字符。', en: 'Project name must not be empty and at most 60 characters.' },
  { key: 'gate.empty', zh: '还没有项目，先建一个。', en: 'No projects yet — create one to get started.' },
  { key: 'gate.hint', zh: '项目数据保存在本账号的云端工作区；原始数据只读，规则与结论由你核对。', en: 'Project data stays in this account’s cloud workspace. Source data is read-only; you review the rules and conclusions.' },
  { key: 'gate.localToolsTitle', zh: '本地与离线工具', en: 'Local and offline tools' },
  { key: 'gate.localToolsHint', zh: '仅在需要本机工作区或离线核对时展开。', en: 'Expand only when you need an on-device workspace or offline review.' },
  { key: 'gate.localToolsExpand', zh: '展开', en: 'Show' },
  { key: 'gate.localToolsCollapse', zh: '收起', en: 'Hide' },

  // ---- 阶段 / 事件 / 优先级 / 环节状态 / 实验状态 / 规则缺口 / 时间（Format.ets 用）----
  { key: 'stage.rulesCapture', zh: '规则收集', en: 'Rules capture' },
  { key: 'stage.rulesReview', zh: '规则待人工确认', en: 'Rules awaiting confirmation' },
  { key: 'stage.dataAudit', zh: '数据审计', en: 'Data audit' },
  { key: 'stage.baselineDesign', zh: '基线设计', en: 'Baseline design' },
  { key: 'stage.evidenceLedIteration', zh: '证据驱动迭代', en: 'Evidence-led iteration' },

  { key: 'evt.rulesAnalyzed', zh: '解析了官方规则文档', en: 'Parsed the official rule document' },
  { key: 'evt.rulesImported', zh: '导入了规则文档', en: 'Imported the rule document' },
  { key: 'evt.rulesApproved', zh: '人工确认了规则规范', en: 'Rules spec confirmed by a human' },
  { key: 'evt.ruleEvidenceRecorded', zh: '记录了官方规则证据', en: 'Recorded official rule evidence' },
  { key: 'evt.ruleEvidenceApplied', zh: '已录入官方规则证据', en: 'Applied official rule evidence' },
  { key: 'evt.workspaceInitialized', zh: '已初始化本工作区', en: 'Workspace initialized' },
  { key: 'evt.projectCreated', zh: '已新建项目', en: 'Project created' },
  { key: 'evt.dataAudited', zh: '完成了数据审计', en: 'Finished the data audit' },
  { key: 'evt.researchSearched', zh: '完成了公开文献检索', en: 'Finished the public literature search' },
  { key: 'evt.repositoryIntake', zh: '创建了第三方仓库接入记录', en: 'Created a third-party repository intake record' },
  { key: 'evt.decisionPlanGenerated', zh: '生成了下一步动作队列', en: 'Generated the next-action queue' },
  { key: 'evt.paperPackageGenerated', zh: '生成了论文证据包', en: 'Generated the paper evidence package' },
  { key: 'evt.trainingScaffoldCreated', zh: '生成了训练配置骨架', en: 'Generated the training config scaffold' },
  { key: 'evt.runtimeProbed', zh: '完成了本地运行时探测', en: 'Finished the local runtime probe' },
  { key: 'evt.trainingConfigApproved', zh: '批准了一次 GPU 训练配置', en: 'Approved a GPU training config' },
  { key: 'evt.experimentDraftCreated', zh: '创建了一个实验草案', en: 'Created an experiment draft' },
  { key: 'evt.experimentApprovalRecorded', zh: '记录了一次实验批准', en: 'Recorded an experiment approval' },
  { key: 'evt.submissionValidated', zh: '校验了本地提交候选', en: 'Validated the local submission candidate' },
  { key: 'evt.trainingJob', zh: '训练任务状态变更', en: 'Training job status changed' },
  { key: 'evt.dataAuditJob', zh: '数据审计任务状态变更', en: 'Data audit job status changed' },
  { key: 'evt.materialIntake', zh: '资料采集任务状态变更', en: 'Material intake job status changed' },
  { key: 'evt.deepseek', zh: '模型设置或会话变更', en: 'Model settings or session changed' },

  { key: 'prio.blocker', zh: '阻塞', en: 'Blocker' },
  { key: 'prio.high', zh: '高', en: 'High' },
  { key: 'prio.medium', zh: '中', en: 'Medium' },
  { key: 'prio.low', zh: '低', en: 'Low' },

  { key: 'state.done', zh: '已完成', en: 'Done' },
  { key: 'state.awaitingHuman', zh: '待人工确认', en: 'Awaiting confirmation' },
  { key: 'state.missing', zh: '证据缺失', en: 'Evidence missing' },
  { key: 'state.notStarted', zh: '未开始', en: 'Not started' },

  { key: 'status.completed', zh: '已完成', en: 'Completed' },
  { key: 'status.failed', zh: '失败', en: 'Failed' },
  { key: 'status.running', zh: '运行中', en: 'Running' },
  { key: 'status.queued', zh: '排队中', en: 'Queued' },
  { key: 'status.planned', zh: '已计划', en: 'Planned' },
  { key: 'status.awaitingHumanApproval', zh: '等待人工批准', en: 'Awaiting approval' },

  { key: 'gap.valueMissing', zh: '字段值还没确认', en: 'Value not confirmed' },
  { key: 'gap.outputModeChoice', zh: '输出模式必须二选一', en: 'Pick one output mode' },
  { key: 'gap.reviewAnchorMissing', zh: '缺复核出处记录', en: 'Missing review reference' },
  { key: 'gap.quoteMissing', zh: '缺官方原文锚点', en: 'Missing official quote' },
  { key: 'gap.questionPending', zh: '问题待澄清', en: 'Question needs clarification' },

  { key: 'time.justNow', zh: '刚刚', en: 'Just now' },
  { key: 'time.minutesAgo', zh: '{0} 分钟前', en: '{0} min ago' },
  { key: 'time.hoursAgo', zh: '{0} 小时前', en: '{0} h ago' },
  { key: 'time.daysAgo', zh: '{0} 天前', en: '{0} d ago' },
  { key: 'time.seconds', zh: '{0} 秒', en: '{0} s' },
  { key: 'time.minutesSeconds', zh: '{0} 分 {1} 秒', en: '{0} min {1} s' },
  { key: 'time.hoursMinutes', zh: '{0} 小时 {1} 分', en: '{0} h {1} min' },

  // ---- 工作流页 ----
  { key: 'workflow.status', zh: '阶段 {0} · {1} · 已完成实验 {2} · 阻塞项 {3}', en: 'Stage {0} · {1} · {2} completed · {3} blockers' },
  { key: 'workflow.requiredFields', zh: '必填字段', en: 'Required fields' },
  { key: 'workflow.valuesFilled', zh: '已填值', en: 'Values filled' },
  { key: 'workflow.anchorsFilled', zh: '已带锚点', en: 'With anchor' },
  { key: 'workflow.section.status', zh: '现状', en: 'Status' },
  { key: 'workflow.section.rules', zh: '规则缺口', en: 'Rule gaps' },
  { key: 'workflow.section.blockers', zh: '阻塞', en: 'Blockers' },
  { key: 'workflow.section.actions', zh: '下一步', en: 'Next steps' },
  { key: 'workflow.section.ask', zh: '问一问', en: 'Ask' },
  { key: 'workflow.autoOn', zh: '已开启', en: 'On' },
  { key: 'workflow.autoOff', zh: '已关闭', en: 'Off' },
  { key: 'workflow.blockers', zh: '阻塞项', en: 'Blockers' },
  { key: 'workflow.componentStatus', zh: '环节状态', en: 'Step status' },
  { key: 'workflow.ruleGapsTitle', zh: '规则缺口', en: 'Rule gaps' },
  { key: 'workflow.ruleReady', zh: '必填规则已就绪', en: 'Required rules ready' },
  { key: 'workflow.ruleNotReady', zh: '规则尚未就绪', en: 'Rules not ready yet' },
  { key: 'workflow.rulesSummary', zh: '{0}：{1} 个必填字段，{2} 项待办、涉及 {3} 个字段（profile：{4}）', en: '{0}: {1} required fields, {2} open items across {3} fields (profile: {4})' },
  { key: 'workflow.noRuleGaps', zh: '必填规则字段都已确认。', en: 'All required rule fields are confirmed.' },
  { key: 'workflow.blockersSubtitle', zh: '共 {0} 条待确认问题（结构性缺口见上方「规则缺口」）', en: '{0} open questions (see Rule gaps above for structural gaps)' },
  { key: 'workflow.noOpenQuestions', zh: '当前没有待确认问题。', en: 'No open questions right now.' },
  { key: 'workflow.actions', zh: '建议动作', en: 'Suggested actions' },
  { key: 'workflow.noActions', zh: '当前没有待办动作。', en: 'No pending actions right now.' },
  { key: 'workflow.actionHint', zh: '以下只是流程建议，不会自动执行；当前云端版本暂不支持在应用内上传数据或启动审计。', en: 'These are workflow suggestions and will not run automatically. This cloud version cannot upload data or start an audit in the app yet.' },
  { key: 'workflow.action.rules', zh: '对照官方规则补齐待办，并由你逐项复核后确认。', en: 'Resolve official-rule questions and explicitly approve the specification.' },
  { key: 'workflow.action.audit', zh: '先对只读原始数据运行审计，再制定真实基线。', en: 'Run the deterministic data audit before creating a real baseline.' },
  { key: 'workflow.action.research', zh: '规则确认后，按任务类型和主指标检索相关研究。', en: 'Search research sources using the task and metric from the approved specification.' },
  { key: 'workflow.action.baseline', zh: '规则和数据审计通过后，使用冻结配置运行可复现基线。', en: 'After rules and audit are approved, run one reproducible baseline with a frozen configuration.' },
  { key: 'workflow.actionEvidence.rules', zh: '规则尚未经过确认。', en: 'Specification is not approved.' },
  { key: 'workflow.actionEvidence.audit', zh: '尚未生成 data_statistics.json。', en: 'No data_statistics.json exists.' },
  { key: 'workflow.actionEvidence.research', zh: '尚未保存研究检索结果。', en: 'No persisted research radar exists.' },
  { key: 'workflow.actionEvidence.baseline', zh: '尚无已完成的实验记录。', en: 'No completed experiments recorded.' },
  { key: 'workflow.askTitle', zh: '问一问 AI', en: 'Ask the AI' },
  { key: 'workflow.askPlaceholder', zh: '例如：这 9 条阻塞项里，哪些必须去官方页面确认？', en: 'e.g. Of these 9 blockers, which ones must be confirmed on the official page?' },
  { key: 'workflow.ask', zh: '提问', en: 'Ask' },
  { key: 'workflow.asking', zh: 'Agent 正在读取工作区记录并思考，这一步可能要等一会儿…', en: 'The agent is reading workspace records and thinking — this may take a moment…' },
  { key: 'workflow.answerMeta', zh: '{0} · {1} 轮', en: '{0} · {1} turns' },
  { key: 'workflow.fieldCount', zh: '{0} 项', en: '{0} items' },
  { key: 'workflow.rulesConfirm', zh: '规则确认', en: 'Rules confirmation' },
  { key: 'workflow.dataAudit', zh: '数据审计', en: 'Data audit' },
  { key: 'workflow.researchSearch', zh: '研究检索', en: 'Research search' },
  { key: 'workflow.baselineRepro', zh: '基线复现', en: 'Baseline reproduction' },
  { key: 'workflow.approvalReview', zh: '候选审批', en: 'Candidate review' },

  // ---- 工作流页：状态摘要条 + 流程时间线（2026-09-30 改版）----
  // 这里不放「这一页是什么」的说明文字：副标题、环节名下面那句解释、展开提示都已删除。
  { key: 'workflow.summary.stage', zh: '当前阶段', en: 'Current stage' },
  { key: 'workflow.summary.experiments', zh: '已完成实验', en: 'Completed experiments' },
  { key: 'workflow.summary.blockers', zh: '阻塞项', en: 'Blockers' },
  { key: 'workflow.summary.confirm', zh: '需要人工确认', en: 'Awaiting confirmation' },
  { key: 'workflow.timeline', zh: '流程时间线', en: 'Workflow timeline' },
  { key: 'workflow.stepWaitingConfirm', zh: '等待人工确认', en: 'Awaiting human confirmation' },
  { key: 'workflow.stepNeedConfirm', zh: '查看并确认', en: 'Review and confirm' },
  { key: 'workflow.stepViewBlockers', zh: '查看缺失项', en: 'View what is missing' },
  { key: 'workflow.agentState', zh: 'Agent 状态', en: 'Agent status' },
  { key: 'workflow.agentAuto', zh: 'Agent 将自动执行下一步。', en: 'The Agent will run the next step automatically.' },
  { key: 'workflow.agentWaitingRules', zh: '等待规则确认，通过后将自动进入下一阶段。', en: 'Waiting for the rules to be confirmed; the next stage starts on its own after that.' },
  { key: 'workflow.blockedTitle', zh: '当前阻塞', en: 'Current blocker' },
  { key: 'workflow.blockedNone', zh: '现在没有阻塞，Agent 会按流程继续推进。', en: 'No blockers right now; the Agent keeps the flow moving.' },
  { key: 'workflow.blockedMissing', zh: '缺失内容', en: 'What is missing' },
  { key: 'workflow.blockedImpact', zh: '在补齐之前，「{0}」无法开始。', en: 'Until these are filled in, "{0}" cannot start.' },
  { key: 'workflow.blockedFill', zh: '补充材料', en: 'Add the material' },
  { key: 'workflow.blockedCheckAgent', zh: '让 Agent 检查工作区', en: 'Have the Agent inspect the workspace' },
  { key: 'workflow.agentCheckPrompt', zh: '请检查当前工作区还缺哪些材料，并说明补齐的顺序。', en: 'Check what material the workspace is still missing, and tell me the order to supply it in.' },
  { key: 'workflow.nextTitle', zh: '下一步', en: 'Next step' },
  { key: 'workflow.nextAfterCurrent', zh: '完成「{0}」后，Agent 将自动开始「{1}」。', en: 'Once "{0}" is done, the Agent starts "{1}" on its own.' },
  { key: 'workflow.nextAuto', zh: 'Agent 将自动执行「{0}」。', en: 'The Agent will run "{0}" automatically.' },
  { key: 'workflow.nextViewActions', zh: '查看下一步建议', en: 'See the suggested next actions' },
  { key: 'workflow.detailState', zh: '状态', en: 'State' },
  { key: 'workflow.detailBlocker', zh: '当前阻塞', en: 'Blocker' },
  { key: 'workflow.detailNext', zh: '下一步', en: 'Next' },
  { key: 'workflow.autoExecution', zh: '自动执行', en: 'Automatic execution' },
  { key: 'workflow.gateTitle', zh: '人工确认规则', en: 'Confirm the rules' },
  { key: 'workflow.gateDone', zh: '规则已人工确认', en: 'Rules confirmed by a human' },
  { key: 'workflow.gateBlocked', zh: '还有 {0} 项待办，处理完才允许确认。', en: '{0} items must be resolved before confirming.' },
  { key: 'workflow.gateNotePlaceholder', zh: '复核说明（必填）：依据哪份官方文档、确认了什么', en: 'Review note (required): which official document, and what was confirmed' },
  { key: 'workflow.gateSubmit', zh: '确认规则', en: 'Confirm rules' },
  { key: 'workflow.gateApproving', zh: '正在记录…', en: 'Recording…' },
  { key: 'workflow.gateNoteRequired', zh: '复核说明不能为空。', en: 'A review note is required.' },
  { key: 'workflow.gateRecorded', zh: '已记录：{0}', en: 'Recorded {0}' },

  // ---- 官方证据录入 ----
  { key: 'workflow.evidenceTitle', zh: '录入官方证据', en: 'Record official evidence' },
  { key: 'workflow.evidenceOpen', zh: '录入证据', en: 'Record evidence' },
  { key: 'workflow.evidenceClose', zh: '收起', en: 'Hide' },
  { key: 'workflow.evidenceUnsupported', zh: '当前项目的规则档案不支持这个录入流程（目前仅对讯飞水体分割档案开放）。', en: 'This recording flow is currently limited to the Xunfei water-segmentation profile.' },
  { key: 'workflow.evidenceGateHint', zh: '录入只记录官方出处，不会批准规则、也不会启动训练。', en: 'Recording only stores where each fact came from; it neither approves the rules nor starts training.' },
  { key: 'workflow.evidenceSourceType', zh: '来源类型', en: 'Source type' },
  { key: 'workflow.evidenceSourceLocator', zh: '来源定位', en: 'Source locator' },
  { key: 'workflow.evidenceReviewedAt', zh: '复核时间', en: 'Reviewed at' },
  { key: 'workflow.evidenceSourceTypeHint', zh: '例如 authenticated_rule_page', en: 'e.g. authenticated_rule_page' },
  { key: 'workflow.evidenceSourceLocatorHint', zh: '官方规则页 URL 或官方文档路径', en: 'Official rule page URL or official document path' },
  { key: 'workflow.evidenceReviewedAtHint', zh: '例如 2026-09-20', en: 'e.g. 2026-09-20' },
  { key: 'workflow.evidenceAnchorHint', zh: '引文 / 章节号 / 页码 / 截图文件名', en: 'Quote, section, page, or screenshot file' },
  { key: 'workflow.evidenceValueHint', zh: '官方原文里的取值', en: 'The value stated by the official source' },
  { key: 'workflow.evidenceFieldColumn', zh: '字段', en: 'Field' },
  { key: 'workflow.evidenceValueColumn', zh: '值', en: 'Value' },
  { key: 'workflow.evidenceAnchorColumn', zh: '官方锚点', en: 'Official anchor' },
  { key: 'workflow.evidenceAnchored', zh: '已带锚点', en: 'Anchored' },
  { key: 'workflow.evidenceNeedAnchor', zh: '缺锚点', en: 'No anchor' },
  { key: 'workflow.evidenceLockedValue', zh: '这个字段的值不能在界面里改，要先在规格里确认。', en: 'This value cannot be edited here; confirm it in the specification first.' },
  { key: 'workflow.evidenceYes', zh: '允许', en: 'Allowed' },
  { key: 'workflow.evidenceNo', zh: '不允许', en: 'Not allowed' },
  { key: 'workflow.evidenceSummary', zh: '必填 {0} 项：缺值 {1} 项、缺锚点 {2} 项', en: '{0} required fields: {1} without a value, {2} without an anchor' },
  { key: 'workflow.evidenceIncomplete', zh: '还差 {0} 项：缺值 {1} 项、缺锚点 {2} 项。填完才能提交。', en: '{0} items still incomplete: {1} without a value, {2} without an anchor.' },
  { key: 'workflow.evidenceNeedSource', zh: '来源类型、来源定位、复核时间都要填。', en: 'Source type, source locator, and reviewed-at are all required.' },
  { key: 'workflow.evidenceSubmit', zh: '提交证据', en: 'Submit evidence' },
  { key: 'workflow.evidenceSubmitting', zh: '正在提交…', en: 'Submitting…' },
  { key: 'workflow.evidenceCancel', zh: '取消', en: 'Cancel' },
  { key: 'workflow.evidenceDone', zh: '已录入 {0} 个字段的官方锚点；下一步是「确认规则」。', en: 'Recorded anchors for {0} fields; the next step is to confirm the rules.' },

  // ---- 工作流步骤条 ----
  { key: 'step.rules', zh: '规则确认', en: 'Rules' },
  { key: 'step.audit', zh: '数据审计', en: 'Data audit' },
  { key: 'step.research', zh: '研究检索', en: 'Research' },
  { key: 'step.baseline', zh: '基线复现', en: 'Baseline' },
  { key: 'step.iteration', zh: '实验迭代', en: 'Iteration' },
  { key: 'step.diagnosis', zh: '结果诊断', en: 'Diagnosis' },
  { key: 'step.approvals', zh: '候选审批', en: 'Approvals' },
  { key: 'step.paper', zh: '论文证据', en: 'Evidence' },
  { key: 'step.inProgress', zh: '进行中', en: 'In progress' },
  { key: 'step.completed', zh: '已完成', en: 'Done' },
  { key: 'step.notStarted', zh: '等待开始', en: 'Not started' },

  // ---- 数据页 ----
  { key: 'data.kindFile', zh: '普通文件', en: 'Regular file' },
  { key: 'data.kindImage', zh: '图像', en: 'Image' },
  { key: 'data.kindMask', zh: '掩码', en: 'Mask' },
  { key: 'data.kindTable', zh: '表格', en: 'Table' },
  { key: 'data.splitTrain', zh: '训练集', en: 'Train' },
  { key: 'data.splitValidation', zh: '验证集', en: 'Validation' },
  { key: 'data.splitTest', zh: '测试集', en: 'Test' },
  { key: 'data.splitUnassigned', zh: '未分配', en: 'Unassigned' },
  { key: 'data.status', zh: '{0} 个文件 · {1} · {2} 个问题 · {3} 组重复', en: '{0} files · {1} · {2} issues · {3} duplicate groups' },
  { key: 'data.channelDistribution', zh: '通道分布', en: 'Channel distribution' },
  { key: 'data.channelLabel', zh: '{0} 通道', en: '{0} channels' },
  { key: 'data.section.source', zh: '审计来源', en: 'Audit source' },
  { key: 'data.section.images', zh: '图像与掩码', en: 'Images and masks' },
  { key: 'data.section.kinds', zh: '类型与划分', en: 'Kinds and splits' },
  { key: 'data.section.issues', zh: '重复与表格', en: 'Duplicates and tables' },
  { key: 'data.auditSource', zh: '审计来源', en: 'Audit source' },
  { key: 'data.dataDir', zh: '数据目录', en: 'Data directory' },
  { key: 'data.auditTime', zh: '审计时间', en: 'Audited at' },
  { key: 'data.metadataFormat', zh: '元数据格式', en: 'Metadata format' },
  { key: 'data.inventoryHash', zh: '清单哈希', en: 'Inventory hash' },
  { key: 'data.schemaVersion', zh: '审计结构版本', en: 'Audit schema version' },
  { key: 'data.imagesAndMasks', zh: '图像与掩码', en: 'Images and masks' },
  { key: 'data.imageCount', zh: '图像数量', en: 'Images' },
  { key: 'data.imageSize', zh: '图像尺寸', en: 'Image size' },
  { key: 'data.maskCount', zh: '掩码数量', en: 'Masks' },
  { key: 'data.emptyMasks', zh: '空掩码', en: 'Empty masks' },
  { key: 'data.foregroundRatio', zh: '前景占比', en: 'Foreground ratio' },
  { key: 'data.fileKinds', zh: '文件类型', en: 'File types' },
  { key: 'data.noFileKinds', zh: '没有统计到文件类型。', en: 'No file types recorded.' },
  { key: 'data.noAuditReport', zh: '当前项目尚未生成数据审计报告。完成数据审计后，结果会显示在这里。', en: 'This project has no data audit report yet. Results will appear here after an audit is completed.' },
  { key: 'data.cloudAuditUnavailable', zh: '当前云端版本没有数据上传或页面内审计入口；完成数据接入并生成报告后，结果会显示在这里。', en: 'This cloud version has no data upload or in-app audit entry point yet. Results will appear here after data is connected and an audit report is generated.' },
  { key: 'data.viewNextSteps', zh: '查看下一步建议', en: 'View next steps' },
  { key: 'data.splits', zh: '数据划分', en: 'Data splits' },
  { key: 'data.noSplits', zh: '没有划分记录。', en: 'No split records.' },
  { key: 'data.duplicatesAndTables', zh: '重复项与表格', en: 'Duplicates and tables' },
  { key: 'data.noDuplicates', zh: '没有发现内容完全重复的文件。', en: 'No byte-identical files found.' },
  { key: 'data.duplicateGroup', zh: '重复组 {0}', en: 'Duplicate group {0}' },
  { key: 'data.tableFiles', zh: '表格文件 {0} 个', en: '{0} table files' },

  // ---- 文献页 ----
  { key: 'lit.status', zh: '{0} 条候选 · 已调研 {1} · 已舍弃 {2} · 已评判 {3}', en: '{0} candidates · {1} investigating · {2} discarded · {3} assessed' },
  { key: 'lit.section.query', zh: '检索条件', en: 'Query' },
  { key: 'lit.section.records', zh: '候选', en: 'Candidates' },
  { key: 'lit.records', zh: '候选文献', en: 'Candidates' },
  { key: 'lit.runSearch', zh: '按规则检索', en: 'Search from the rules' },
  { key: 'lit.rerunSearch', zh: '重新检索', en: 'Search again' },
  { key: 'lit.searching', zh: '正在检索…', en: 'Searching…' },
  { key: 'lit.fromSpecHint', zh: '不填检索词就按竞赛规则自动拼：任务类型 + 模态', en: 'Leave the query empty to build it from the spec: task type + modalities' },
  { key: 'lit.queryLabel', zh: '检索词', en: 'Query' },
  { key: 'lit.queryPlaceholder', zh: '例如 rgb infrared depth fusion', en: 'e.g. rgb infrared depth fusion' },
  { key: 'lit.queryLabelOverride', zh: '检索式（人工覆盖）', en: 'Query (manual override)' },
  { key: 'lit.failedSourcesHint', zh: '本轮不可用的数据源', en: 'Data sources unavailable this round' },
  { key: 'lit.queryInfo', zh: '检索信息', en: 'Search details' },
  { key: 'lit.query', zh: '检索式：{0}', en: 'Query: {0}' },
  { key: 'lit.searchedAt', zh: '检索时间：{0}', en: 'Searched at: {0}' },
  { key: 'lit.dataSources', zh: '数据源', en: 'Sources' },
  { key: 'lit.venueUnknown', zh: '未标注来源', en: 'Venue not listed' },
  { key: 'lit.yearUnknown', zh: '年份未知', en: 'Year unknown' },
  { key: 'lit.authorsUnknown', zh: '作者未知', en: 'Authors unknown' },
  { key: 'lit.relevance', zh: '相关系数 {0}', en: 'Relevance {0}' },
  { key: 'lit.partTerms', zh: '词 {0}', en: 'terms {0}' },
  { key: 'lit.partTask', zh: '任务 {0}', en: 'task {0}' },
  { key: 'lit.partCode', zh: '代码 {0}', en: 'code {0}' },
  { key: 'lit.partRecency', zh: '年份 {0}', en: 'year {0}' },
  { key: 'lit.officialCode', zh: '官方代码', en: 'Official code' },
  { key: 'lit.codeLink', zh: '有代码链接', en: 'Code link' },
  { key: 'lit.recordsNote', zh: '收录不等于复现或背书，复现前需人工确认代码与许可', en: 'Being listed is not reproduction or endorsement; verify code and license by hand before reproducing' },
  { key: 'lit.noRecords', zh: '还没有候选。先按规则检索一次。', en: 'No candidates yet. Run a rule-driven search first.' },
  { key: 'lit.providerFailure', zh: '{0}：{1}', en: '{0}: {1}' },
  { key: 'lit.authorSeparator', zh: '、', en: ', ' },

  // ---- 文献取舍与价值评判 ----
  { key: 'lit.decisionLabel', zh: '取舍', en: 'Decision' },
  { key: 'lit.decideInvestigate', zh: '调研', en: 'Investigate' },
  { key: 'lit.decideDiscard', zh: '舍弃', en: 'Discard' },
  { key: 'lit.decideReset', zh: '未决', en: 'Undecided' },
  { key: 'lit.decidedInvestigate', zh: '已选调研', en: 'Investigating' },
  { key: 'lit.decidedDiscard', zh: '已舍弃', en: 'Discarded' },
  { key: 'lit.decidedReset', zh: '未决', en: 'Undecided' },
  { key: 'lit.assessRun', zh: '评判已调研的候选', en: 'Assess the investigated ones' },
  { key: 'lit.assessing', zh: '正在评判…', en: 'Assessing…' },
  { key: 'lit.assessNone', zh: '还没有标记「调研」的候选，先在上面的候选里选几条。', en: 'No candidate is marked for investigation yet.' },
  { key: 'lit.assessSummary', zh: '已调研 {0} · 已舍弃 {1} · 已评判 {2}', en: '{0} investigating · {1} discarded · {2} assessed' },
  { key: 'lit.assessedAt', zh: '评判于 {0}', en: 'Assessed {0}' },
  { key: 'lit.verdict', zh: '结论', en: 'Verdict' },
  { key: 'lit.verdictReproduce', zh: '值得复现', en: 'Worth reproducing' },
  { key: 'lit.verdictAdaptComponent', zh: '只借鉴组件', en: 'Borrow components' },
  { key: 'lit.verdictReferenceOnly', zh: '只作参考', en: 'Read only' },
  { key: 'lit.verdictSkip', zh: '不投入', en: 'Skip' },
  { key: 'lit.adviceReproduce', zh: '有代码、任务也吻合：可以按它的方法跑一遍。', en: 'Code exists and the task matches: reproduce it.' },
  { key: 'lit.adviceAdaptComponent', zh: '有代码，但不是同一件事：只借鉴其中可复用的部分。', en: 'Code exists but it is a different task: borrow the reusable parts only.' },
  { key: 'lit.adviceReferenceOnly', zh: '没找到代码，但任务高度吻合：值得精读，实现要自己写。', en: 'No code found, but the task matches closely: read it, implement it yourself.' },
  { key: 'lit.adviceSkip', zh: '既没找到代码、任务也不吻合：不建议投入。', en: 'Neither code nor task fit: do not invest here.' },
  { key: 'lit.worthReproducing', zh: '是否值得复现', en: 'Worth reproducing' },
  { key: 'lit.worthYes', zh: '值得', en: 'Worth it' },
  { key: 'lit.worthNo', zh: '不值得', en: 'Not worth it' },
  { key: 'lit.openSource', zh: '开源代码', en: 'Public code' },
  { key: 'lit.openSourceRecord', zh: '记录自带仓库', en: 'Repo in the record' },
  { key: 'lit.openSourceFound', zh: '找到实现仓库', en: 'Implementation found' },
  { key: 'lit.openSourceNone', zh: '没找到', en: 'None found' },
  { key: 'lit.openSourceUnknown', zh: '没查成（不代表没有）', en: 'Lookup failed (not proof of absence)' },
  { key: 'lit.officialCodeNone', zh: '无法证明（检索源不给作者归属）', en: 'Cannot be proven (providers omit authorship)' },
  { key: 'lit.signalLicense', zh: '许可', en: 'Licence' },
  { key: 'lit.signalLicenseUnknown', zh: '未标注许可', en: 'No licence declared' },
  { key: 'lit.signalTaskFit', zh: '任务匹配', en: 'Task fit' },
  { key: 'lit.signalYear', zh: '年份', en: 'Year' },
  { key: 'lit.signalVenue', zh: '发表来源', en: 'Venue' },
  { key: 'lit.signalUnknown', zh: '未知', en: 'Unknown' },
  { key: 'lit.codeCandidates', zh: '候选实现仓库', en: 'Candidate repositories' },
  { key: 'lit.codeOverlap', zh: '标题重合 {0}', en: 'title overlap {0}' },
  { key: 'lit.codeStars', zh: '{0} 星', en: '{0} stars' },
  { key: 'lit.actionFailed', zh: '操作失败：{0}', en: 'Action failed: {0}' },
  { key: 'lit.buildPlan', zh: '生成复现计划', en: 'Build a reproduction plan' },
  { key: 'lit.buildingPlan', zh: '正在克隆并生成计划…', en: 'Cloning and planning…' },
  { key: 'lit.planError', zh: '生成计划失败：{0}', en: 'Could not build the plan: {0}' },

  // ---- 复现（隔离容器跑 baseline） ----
  { key: 'repro.status', zh: '容器引擎 {0} · {1} 个计划 · {2} 次运行', en: 'Container engine {0} · {1} plans · {2} runs' },
  { key: 'repro.engineOk', zh: '{0}', en: '{0}' },
  { key: 'repro.engineMissing', zh: '不可用', en: 'unavailable' },
  { key: 'repro.engineMissingDetail', zh: '复现运行环境当前不可用，请联系平台管理员检查服务端容器配置。诊断信息：{0}', en: 'The reproduction runtime is unavailable. Ask the platform administrator to check the server container setup. Diagnostic: {0}' },
  { key: 'repro.section.plans', zh: '计划', en: 'Plans' },
  { key: 'repro.section.runs', zh: '运行', en: 'Runs' },
  { key: 'repro.noPlans', zh: '还没有复现计划。去文献页，对已评判的候选取一条点「生成复现计划」。', en: 'No plans yet. On the literature page, assess a candidate and press “Build a reproduction plan”.' },
  { key: 'repro.noRuns', zh: '还没有运行记录。批准一条命令后，这里会出现它的阶段与产物。', en: 'No runs yet. Approve a command and its phases and outputs will show up here.' },
  { key: 'repro.repository', zh: '仓库', en: 'Repository' },
  { key: 'repro.commit', zh: '固定提交', en: 'Pinned commit' },
  { key: 'repro.image', zh: '镜像', en: 'Image' },
  { key: 'repro.manifest', zh: '依赖清单', en: 'Dependency manifest' },
  { key: 'repro.manifestNone', zh: '仓库里没找到依赖清单，容器里不会预装依赖', en: 'No dependency manifest found; nothing is installed in the container' },
  { key: 'repro.entrypoints', zh: '入口', en: 'Entrypoints' },
  { key: 'repro.dataset', zh: '数据挂载', en: 'Dataset mount' },
  { key: 'repro.datasetNone', zh: '没有已审计的数据集，容器里不会挂 /data', en: 'No audited dataset; /data is not mounted' },
  { key: 'repro.resources', zh: '资源', en: 'Resources' },
  { key: 'repro.resourceValue', zh: '{0} CPU · {1} 内存 · 超时 {2}s', en: '{0} CPU · {1} memory · {2}s timeout' },
  { key: 'repro.gpuOn', zh: '需要 GPU', en: 'Needs a GPU' },
  { key: 'repro.gpuOff', zh: '只用 CPU', en: 'CPU only' },
  { key: 'repro.commands', zh: '候选命令', en: 'Candidate commands' },
  { key: 'repro.commandDocumented', zh: '文档原文', en: 'from the docs' },
  { key: 'repro.commandFallback', zh: '退化命令', en: 'fallback' },
  { key: 'repro.commandSource', zh: '出处 {0}', en: 'from {0}' },
  { key: 'repro.commandHint', zh: '选中一条后可以改写再批准 —— README 里的路径是仓库自己的，这里的数据集挂在 /data。', en: 'Pick one, then edit it before approving: the README uses the repository own paths, while the dataset is mounted at /data.' },
  { key: 'repro.noteLabel', zh: '批准说明', en: 'Approval note' },
  { key: 'repro.notePlaceholder', zh: '你核对了什么、为什么可以跑（必填）', en: 'What you reviewed and why it may run (required)' },
  { key: 'repro.approveAndRun', zh: '批准并运行', en: 'Approve and run' },
  { key: 'repro.submitting', zh: '正在提交…', en: 'Submitting…' },
  { key: 'repro.phaseDownload', zh: '依赖下载（有网）', en: 'Download wheels (networked)' },
  { key: 'repro.phaseRun', zh: '安装并运行（无网）', en: 'Install and run (isolated)' },
  { key: 'repro.exitCode', zh: '退出码 {0}', en: 'exit {0}' },
  { key: 'repro.duration', zh: '耗时 {0}s', en: '{0}s' },
  { key: 'repro.logTail', zh: '日志尾部', en: 'Log tail' },
  { key: 'repro.outputs', zh: '产物', en: 'Outputs' },
  { key: 'repro.outputsEmpty', zh: '没有列出产物文件。', en: 'No output files were listed.' },
  { key: 'repro.outputKeys', zh: '顶层键：{0}', en: 'keys: {0}' },
  { key: 'repro.outputColumns', zh: '表头：{0}', en: 'columns: {0}' },
  { key: 'repro.statusQueued', zh: '排队中', en: 'Queued' },
  { key: 'repro.statusRunning', zh: '运行中', en: 'Running' },
  { key: 'repro.statusSucceeded', zh: '成功', en: 'Succeeded' },
  { key: 'repro.statusFailed', zh: '失败', en: 'Failed' },
  { key: 'repro.rewritten', zh: '已改写', en: 'edited' },
  { key: 'repro.policy', zh: '隔离方式：仓库只读挂在 /src，命令在 /work 的副本里跑；依赖只在有网阶段下载，运行阶段容器无网。', en: 'Isolation: the repository is read-only at /src and the command runs on a copy under /work; wheels are downloaded in the networked phase only, and the run phase has no network.' },
  { key: 'repro.actionFailed', zh: '操作失败：{0}', en: 'Action failed: {0}' },

  // ---- 设置页 ----
  { key: 'settings.status', zh: '后端 {0} · 模型 {1} · GPU {2} · Conda {3}', en: 'Backend {0} · model {1} · GPU {2} · Conda {3}' },
  { key: 'settings.section.workspace', zh: '本地工作区', en: 'Local workspace' },
  { key: 'settings.section.backend', zh: '后端', en: 'Backend' },
  { key: 'settings.section.model', zh: '模型', en: 'Model' },
  { key: 'settings.section.runtime', zh: '运行环境', en: 'Runtime environment' },
  { key: 'settings.notConnected', zh: '未连接', en: 'Not connected' },
  { key: 'settings.gpuMemory', zh: '可用 {0} / 共 {1} · 驱动 {2}', en: 'Free {0} / Total {1} · Driver {2}' },
  { key: 'settings.gpuCount', zh: '可用 {0} 张', en: '{0} available' },
  { key: 'settings.available', zh: '可用', en: 'Available' },
  { key: 'settings.unavailable', zh: '不可用', en: 'Unavailable' },
  { key: 'settings.serviceAddress', zh: '服务地址', en: 'Service URL' },
  { key: 'settings.sharedToken', zh: '共享令牌', en: 'Shared token' },
  { key: 'settings.accountAuth', zh: '账号认证', en: 'Account authentication' },
  { key: 'settings.accountAuthActive', zh: '登录会话有效', en: 'Signed in' },
  { key: 'settings.managedModel', zh: '平台托管模型', en: 'Platform-managed model' },
  { key: 'settings.deepseekManaged', zh: 'DeepSeek（平台托管）', en: 'DeepSeek (platform managed)' },
  { key: 'settings.managedModelHint', zh: '模型密钥由平台保管，不会下发到本机。每次调用按实际输入与输出 token 从账号积分扣除。', en: 'The platform keeps the model key; it is never sent to this device. Actual input and output tokens are deducted from your account credits.' },
  { key: 'settings.configured', zh: '已配置', en: 'Configured' },
  { key: 'settings.tokenNotConfigured', zh: '未配置（回环地址不校验）', en: 'Not set (loopback needs no auth)' },
  { key: 'settings.health', zh: '健康状态', en: 'Health' },
  { key: 'settings.workspace', zh: '工作区', en: 'Workspace' },
  { key: 'settings.keySource', zh: '密钥来源', en: 'Key source' },
  { key: 'settings.keySourceEnv', zh: '环境变量', en: 'Environment variable' },
  { key: 'settings.keySourceStore', zh: '系统凭据管理器', en: 'System credential store' },
  { key: 'settings.keySourceNone', zh: '未设置', en: 'Not set' },
  { key: 'settings.apiKeyEnv', zh: '密钥环境变量', en: 'Key environment variable' },
  { key: 'settings.secureStorage', zh: '安全存储', en: 'Secure storage' },
  { key: 'settings.currentSource', zh: '当前使用', en: 'Active source' },
  { key: 'settings.currentName', zh: '名称', en: 'Name' },
  { key: 'settings.currentModel', zh: '模型', en: 'Model' },
  { key: 'settings.sourceList', zh: '模型来源', en: 'Model sources' },
  { key: 'settings.noSource', zh: '还没有配置模型来源。点下面「新增来源」加一套。', en: 'No model source yet. Click New source below to add one.' },
  { key: 'settings.activeTag', zh: '当前', en: 'Active' },
  { key: 'settings.needKey', zh: '缺密钥', en: 'No key' },
  { key: 'settings.activate', zh: '设为当前', en: 'Use this' },
  { key: 'settings.test', zh: '测试', en: 'Test' },
  { key: 'settings.testing', zh: '测试中…', en: 'Testing…' },
  { key: 'settings.testOk', zh: '连接正常（{0}）。', en: 'Connection OK ({0}).' },
  { key: 'settings.testFailed', zh: '连接失败：{0}', en: 'Connection failed: {0}' },
  { key: 'settings.edit', zh: '编辑', en: 'Edit' },
  { key: 'settings.delete', zh: '删除', en: 'Delete' },
  { key: 'settings.deleteConfirm', zh: '确认删除', en: 'Confirm delete' },
  { key: 'settings.newSource', zh: '新增来源', en: 'New source' },
  { key: 'settings.editSource', zh: '编辑来源', en: 'Edit source' },
  { key: 'settings.preset', zh: '预设（点一下预填地址和名称，之后仍可改）', en: 'Preset (click to prefill the URL and name; both stay editable)' },
  { key: 'settings.fieldName', zh: '名称', en: 'Name' },
  { key: 'settings.fieldNameHint', zh: '例如：我的 DeepSeek', en: 'e.g. My DeepSeek' },
  { key: 'settings.fieldBaseUrl', zh: '接口地址', en: 'Base URL' },
  { key: 'settings.fieldBaseUrlHint', zh: 'https://api.deepseek.com', en: 'https://api.deepseek.com' },
  { key: 'settings.fieldModel', zh: '模型名', en: 'Model name' },
  { key: 'settings.fieldModelHint', zh: '例如：deepseek-chat', en: 'e.g. deepseek-chat' },
  { key: 'settings.fieldApiKey', zh: '密钥', en: 'API key' },
  { key: 'settings.fieldApiKeyHintNew', zh: '粘贴密钥（存进系统凭据管理器，不写进配置文件）', en: 'Paste the key (kept in the system credential store, never in the config file)' },
  { key: 'settings.fieldApiKeyHintKeep', zh: '留空＝不改已存的密钥', en: 'Leave empty to keep the stored key' },
  { key: 'settings.save', zh: '保存', en: 'Save' },
  { key: 'settings.saving', zh: '保存中…', en: 'Saving…' },
  { key: 'settings.saved', zh: '已保存。', en: 'Saved.' },
  { key: 'settings.activated', zh: '已切换到「{0}」。', en: 'Switched to {0}.' },
  { key: 'settings.deleted', zh: '已删除「{0}」。', en: 'Deleted {0}.' },

  // ---- 本地工作区（端侧自足）----
  { key: 'settings.localWorkspace', zh: '本地工作区', en: 'Local workspace' },
  { key: 'settings.workspacePath', zh: '工作区目录', en: 'Workspace folder' },
  { key: 'settings.workspaceNone', zh: '还没准备好（点「初始化工作区」开始）', en: 'Not set up yet (click Initialise workspace)' },
  { key: 'settings.workspaceReady', zh: '目录可读写。', en: 'The folder is readable and writable.' },
  { key: 'settings.workspaceNotReadable', zh: '现在读不到这个目录（可能被移动或删掉了），请重新准备。', en: 'This folder cannot be read right now (it may have been moved or deleted); set it up again.' },
  { key: 'settings.workspacePermissionDenied', zh: '没拿到「文档」目录的读写权限。请在系统弹窗里允许，或到「设置 → 应用 → You Just Lead → 权限」里手动打开。', en: 'The Documents folder permission was not granted. Allow it in the system dialog, or enable it under Settings → Apps → You Just Lead → Permissions.' },
  { key: 'settings.workspaceUnsupported', zh: '这台设备不支持「用户文档目录」这个系统能力，端侧工作区在这台机器上用不了。', en: 'This device does not provide the user Documents folder capability, so the on-device workspace cannot be used here.' },
  { key: 'settings.workspaceHint', zh: '工作区会建在「文档/YouJustLead」下（首次点按钮时系统会问一次权限）。它是你自己磁盘上的普通文件夹，随时能在文件管理器里打开核对。', en: 'The workspace is created under Documents/YouJustLead (the system asks for permission the first time). It is an ordinary folder on your disk that you can open and check any time.' },
  { key: 'settings.chooseFolder', zh: '初始化工作区', en: 'Initialise workspace' },
  { key: 'settings.initSkeleton', zh: '初始化项目目录', en: 'Set up project folders' },
  { key: 'settings.recheck', zh: '检查工作区', en: 'Check workspace' },
  { key: 'settings.working', zh: '处理中…', en: 'Working…' },
  { key: 'settings.specFile', zh: '规格文件', en: 'Specification' },
  { key: 'settings.present', zh: '存在', en: 'Present' },
  { key: 'settings.missing', zh: '缺失', en: 'Missing' },
  { key: 'settings.ruleProfile', zh: '规则档案', en: 'Rule profile' },
  { key: 'settings.ruleFields', zh: '必备字段', en: 'Required fields' },
  { key: 'settings.ruleGaps', zh: '规则缺口', en: 'Rule gaps' },
  { key: 'settings.ruleGapsValue', zh: '{0} 项（缺值 {1}、缺锚点 {2}）', en: '{0} gaps ({1} without a value, {2} without an anchor)' },
  { key: 'settings.specFingerprint', zh: '规格指纹', en: 'Spec digest' },
  { key: 'settings.ledgerEvents', zh: '账本事件', en: 'Ledger events' },
  { key: 'settings.ruleGate', zh: '核对运行规则', en: 'Review run rules' },
  { key: 'settings.ruleApproval', zh: '规则批准', en: 'Rule approval' },

  // ---- 设置页：就绪状态与配置卡片（2026-09-30 重做版式）----
  { key: 'settings.pageSubtitle', zh: 'Settings', en: 'Settings' },
  { key: 'settings.pageDesc', zh: '查看服务与运行环境状态，并管理当前模式支持的模型配置。', en: 'Check service and runtime status, and manage model settings supported by this mode.' },
  { key: 'settings.readiness.title', zh: '系统就绪状态', en: 'System readiness' },
  { key: 'settings.checking', zh: '正在检测', en: 'Checking' },
  { key: 'settings.checkingNote', zh: '正在读取服务、模型与运行环境状态。', en: 'Reading the service, model and runtime status.' },
  { key: 'settings.verdictReady', zh: '服务与运行环境已就绪', en: 'Service and runtime ready' },
  { key: 'settings.verdictLimited', zh: '服务可用，部分运行能力受限', en: 'Service available; some runtime features are limited' },
  { key: 'settings.verdictBlocked', zh: '服务或模型尚未就绪', en: 'Service or model is not ready' },
  { key: 'settings.verdictReadyNote', zh: '后端、模型与运行环境都已就绪，可以开始研究与分析。', en: 'Backend, model and runtime are all in place; research and analysis can start.' },
  { key: 'settings.verdictLimitedNote', zh: '当前环境可以支持基础的研究与分析任务，但存在未配置项；补齐后能力才完整。', en: 'Basic research and analysis work now; finish the unconfigured items to unlock everything.' },
  { key: 'settings.verdictBlockedNote', zh: '连不上后端。端侧仍能查看工作区与离线记录，但实验、检索与问答都用不了。', en: 'The backend is unreachable. The workspace and offline records still work, but experiments, search and Q&A do not.' },
  { key: 'settings.readiness.ready', zh: '服务与模型已连通，当前执行环境检测到 GPU 和 Conda。此状态只代表环境检测通过，不代表真实训练闭环已完成。', en: 'The service and model respond, and a GPU and Conda were detected. This is an environment check only; it does not mean a full training loop has been completed.' },
  { key: 'settings.readiness.limited', zh: '服务与模型可用，但当前执行环境缺少 GPU 或 Conda。依赖它们的训练加速、环境创建或依赖管理会受影响。', en: 'The service and model are available, but the current runtime lacks a GPU or Conda. Training acceleration, environment creation or dependency management may be affected.' },
  { key: 'settings.readiness.backendUnavailable', zh: '当前无法连接后端服务。请检查网络与服务状态；云端功能暂不可用。', en: 'The backend cannot be reached. Check the network and service status; cloud features are unavailable for now.' },
  { key: 'settings.readiness.modelUnavailable', zh: '后端已连接，但没有可用模型。请进入模型设置检查来源与连接。', en: 'The backend is connected, but no model is available. Check the provider and connection in model settings.' },
  { key: 'settings.localModelHint', zh: '本地模式可在模型设置中管理提供商与 API Key；密钥不会在来源列表中回显。', en: 'In local mode, manage providers and API keys in model settings; saved keys are never shown in the provider list.' },
  { key: 'settings.viewModelInfo', zh: '查看模型信息', en: 'View model details' },
  { key: 'settings.runtimeManagementHint', zh: '此处显示当前后端执行环境的检测结果。安装或修改 Python、Conda、GPU 驱动需要在运行后端的设备上完成。', en: 'These results describe the backend runtime. Install or change Python, Conda or GPU drivers on the device running the backend.' },
  { key: 'settings.advancedHint', zh: '这里只显示服务诊断信息。规则审批与科研事件请到工作流或溯源页面查看。', en: 'This area shows service diagnostics. Review rule approvals and research events in Workflow or Traceability.' },
  { key: 'settings.statusReadFailed', zh: '部分状态读取失败', en: 'Some status checks failed' },
  { key: 'settings.agentPermissionsHint', zh: '当前版本没有开放自动安装依赖、修改代码或自动训练的权限开关。涉及外部数据、运行陌生代码、高成本训练、删除记录或竞赛提交等关键操作，仍须按项目约定由人确认。', en: 'This version has no permission toggles for automatic dependency installation, code changes or training. External data, unfamiliar code, costly training, deleting records and contest submissions still require human confirmation under the project rules.' },
  { key: 'settings.recheckAll', zh: '重新检测', en: 'Re-check' },
  { key: 'settings.offlineRecords', zh: '离线记录', en: 'Offline records' },
  { key: 'settings.tile.backend', zh: '后端服务', en: 'Backend Service' },
  { key: 'settings.tile.model', zh: '当前模型', en: 'AI Model' },
  { key: 'settings.tile.noteBackendOk', zh: '服务运行正常。具体功能以当前接入能力为准。', en: 'The service is responding. Available features depend on what is integrated.' },
  { key: 'settings.tile.noteBackendDown', zh: '连不上后端：请确认服务地址与网络，或先看离线记录。', en: 'Cannot reach the backend; check the address and the network, or open the offline records.' },
  { key: 'settings.tile.noteModelOk', zh: '模型已就绪，可进行推理与分析。', en: 'The model is ready for inference and analysis.' },
  { key: 'settings.tile.noteModelMissing', zh: '还没有可用的模型来源，推理与问答不可用。', en: 'No usable model source, so inference and Q&A are unavailable.' },
  { key: 'settings.tile.noteGpuOk', zh: '可用于训练与科学计算加速。', en: 'Available for training and accelerated scientific computing.' },
  { key: 'settings.tile.noteGpuMissing', zh: '未检测到可用的 GPU。将影响模型训练、科学计算加速等任务。', en: 'No GPU detected; training and accelerated scientific computing are affected.' },
  { key: 'settings.tile.noteCondaOk', zh: '可用于创建科研环境与管理依赖。', en: 'Available for creating environments and managing dependencies.' },
  { key: 'settings.tile.noteCondaMissing', zh: '未找到 Conda 环境。将影响科研环境创建与依赖管理。', en: 'No Conda environment found; environment creation and dependency management are affected.' },
  { key: 'settings.pillNormal', zh: '正常', en: 'OK' },
  { key: 'settings.pillUnconfigured', zh: '未配置', en: 'Not configured' },
  { key: 'settings.pillNotDetected', zh: '未检测到', en: 'Not detected' },
  { key: 'settings.limitedTitle', zh: '当前有 {0} 项能力受限', en: '{0} capabilities are limited' },
  { key: 'settings.limitedBody', zh: '{0} 未就绪。需要它们的功能会受影响，其余照常。', en: '{0} not ready. Features that need them are affected; the rest still work.' },
  { key: 'settings.card.workspace', zh: '工作区设置', en: 'Workspace' },
  { key: 'settings.card.workspaceSub', zh: '管理研究项目的本地工作目录与相关文件', en: 'The local working folder and the files inside it' },
  { key: 'settings.workspacePurpose', zh: '用于存储项目文件、实验数据、生成结果等。', en: 'Holds project files, experiment data and generated results.' },
  { key: 'settings.card.modelRuntime', zh: '模型与运行时配置', en: 'Model & Runtime' },
  { key: 'settings.card.modelRuntimeSub', zh: '当前用哪个模型，以及 Python、Conda 与 GPU 的可用情况', en: 'Which model is active, plus Python, Conda and GPU availability' },
  { key: 'settings.modelProvider', zh: '模型提供商', en: 'Model provider' },
  { key: 'settings.modelName', zh: '模型名称', en: 'Model name' },
  { key: 'settings.pythonInterpreter', zh: 'Python 解释器', en: 'Python interpreter' },
  { key: 'settings.condaEnv', zh: 'Conda 环境', en: 'Conda environment' },
  { key: 'settings.gpuCuda', zh: 'GPU / CUDA', en: 'GPU / CUDA' },
  { key: 'settings.testConnection', zh: '测试连接', en: 'Test connection' },
  { key: 'settings.managedByPlatform', zh: '云端由平台统一配置，端侧只读。', en: 'Configured by the platform in cloud mode; read-only here.' },
  { key: 'settings.card.permissions', zh: 'Agent 权限与行为', en: 'Agent Permissions' },
  { key: 'settings.card.permissionsSub', zh: '控制 Agent 在本地环境中的操作权限', en: 'What the Agent may do in the local environment' },
  { key: 'settings.permDeps', zh: '自动安装依赖', en: 'Install dependencies' },
  { key: 'settings.permDepsNote', zh: '允许 Agent 自动安装缺失的 Python 依赖包', en: 'Let the Agent install missing Python packages' },
  { key: 'settings.permCode', zh: '允许修改代码', en: 'Edit code' },
  { key: 'settings.permCodeNote', zh: '允许 Agent 修改项目中的代码文件', en: 'Let the Agent change code files in the project' },
  { key: 'settings.permExperiment', zh: '允许执行实验', en: 'Run experiments' },
  { key: 'settings.permExperimentNote', zh: '允许 Agent 运行实验、训练模型和分析数据', en: 'Let the Agent run experiments, train models and analyse data' },
  { key: 'settings.permConfirm', zh: '关键步骤人工确认', en: 'Confirm key steps' },
  { key: 'settings.permConfirmNote', zh: '在删除文件、改动外部网络等操作前需要人工确认', en: 'Ask a human before deleting files or touching the network' },
  { key: 'settings.permFootnote', zh: '这四项目前保存在本机，是你与 Agent 的约定；执行器接入后由后端按同一份设置拦截。', en: 'These four live on this device for now; once the executor is connected the backend enforces the same settings.' },
  { key: 'settings.card.advanced', zh: '高级信息', en: 'Advanced' },
  { key: 'settings.section.overview', zh: '系统状态', en: 'System status' },
  { key: 'settings.section.advanced', zh: '高级诊断', en: 'Advanced diagnostics' },
  { key: 'settings.card.advancedSub', zh: '以下为系统内部信息，供高级用户参考', en: 'Internal system information for advanced users' },
  { key: 'settings.ruleStatus', zh: '规则状态', en: 'Rule status' },
  { key: 'settings.backendWorkspace', zh: '后端工作区', en: 'Backend workspace' },
  { key: 'settings.notProbed', zh: '还没探测', en: 'Not probed yet' },

  // ---- 端侧规则关口（整页，不经过后端）----
  { key: 'localRule.title', zh: '运行规则检查', en: 'Run rules check' },
  { key: 'localRule.back', zh: '返回', en: 'Back' },
  { key: 'localRule.importSpec', zh: '导入规格文件', en: 'Import spec file' },
  { key: 'localRule.profile', zh: '规则档案', en: 'Rule profile' },
  { key: 'localRule.specFingerprint', zh: '规格指纹', en: 'Spec digest' },
  { key: 'localRule.sourceTitle', zh: '证据来源', en: 'Evidence source' },
  { key: 'localRule.noWorkspace', zh: '还没有准备用户目录', en: 'The user folder is not set up yet' },
  { key: 'localRule.noWorkspaceHint', zh: '先返回到上一屏，在「工作区设置」卡片上点「初始化工作区」。', en: 'Go back and click "Initialise workspace" on the workspace card first.' },
  { key: 'localRule.noSpecHint', zh: '点右上角「导入规格文件」从文件选择器里挑一份 YAML；也可以用系统文件管理器把文件直接拷进工作区目录。', en: 'Use "Import spec file" at the top right to pick a YAML file, or copy one into the workspace folder with the system file manager.' },
  { key: 'localRule.done', zh: '已录入 {0} 个字段的官方证据，规则缺口已归零。', en: 'Recorded official evidence for {0} fields; the rule gap count is now zero.' },
  { key: 'localRule.notApproval', zh: '录入证据不等于批准规则：批准是另一道关口，需要人写一句复核说明。', en: 'Recording evidence is not the same as approving the rules: approval is a separate gate that needs a human review note.' },
  { key: 'localRule.approvalTitle', zh: '批准规则', en: 'Approve the rules' },
  { key: 'localRule.approvalNoteLabel', zh: '人工复核说明', en: 'Human review note' },
  { key: 'localRule.approvalNoteHint', zh: '你对着官方原文复核了什么（这句会原文留在规格里）', en: 'What you checked against the official source (stored verbatim in the spec)' },
  { key: 'localRule.approve', zh: '批准规则', en: 'Approve rules' },
  { key: 'localRule.approving', zh: '正在批准…', en: 'Approving…' },
  { key: 'localRule.approved', zh: '已批准', en: 'Approved' },
  { key: 'localRule.notApproved', zh: '未批准', en: 'Not approved' },
  { key: 'localRule.approvalBlocked', zh: '还有 {0} 项规则缺口没归零，不能批准。', en: '{0} rule gaps are still open, so approval is not allowed.' },
  { key: 'localRule.approvalNeedNote', zh: '批准要写一句人工复核说明。', en: 'Approval requires a human review note.' },
  { key: 'localRule.approvalDone', zh: '已批准（{0}），缺口保持为 0。', en: 'Approved at {0}; the gap count stays at zero.' },
  { key: 'localRule.approvalRevokeHint', zh: '再录一次证据会撤回这次批准：证据变了，原来的复核结论就不再成立。', en: 'Recording evidence again revokes this approval: once the evidence changes, the earlier review no longer holds.' },

  // ---- 端侧离线状态（整页，后端不在时也能看）----
  { key: 'localStatus.title', zh: '离线记录', en: 'Offline records' },
  { key: 'localStatus.back', zh: '返回', en: 'Back' },
  { key: 'localStatus.noWorkspace', zh: '还没有准备用户目录', en: 'The user folder is not set up yet' },
  { key: 'localStatus.noWorkspaceHint', zh: '先返回到上一屏，在「工作区设置」卡片上点「初始化工作区」。', en: 'Go back and click "Initialise workspace" on the workspace card first.' },
  { key: 'localStatus.readable', zh: '这几项不经过后端', en: 'These do not go through the backend' },
  { key: 'localStatus.executorTitle', zh: '需要外部执行器', en: 'External executor required' },
  { key: 'localStatus.capSearch', zh: '文献检索', en: 'Literature search' },
  { key: 'localStatus.capLlm', zh: '大模型问答', en: 'LLM question answering' },
  { key: 'localStatus.capTraining', zh: '真实训练', en: 'Real training' },
  { key: 'localStatus.capAudit', zh: '重型数据审计', en: 'Heavy data audit' },
  { key: 'localStatus.executorBadge', zh: '需外部执行器', en: 'Needs executor' },
  { key: 'localStatus.dataset', zh: '数据审计', en: 'Dataset audit' },
  { key: 'localStatus.datasetMissing', zh: '还没有审计结果', en: 'No audit result yet' },
  { key: 'localStatus.datasetFiles', zh: '文件数', en: 'Files' },
  { key: 'localStatus.datasetIssues', zh: '问题数', en: 'Issues' },
  { key: 'localStatus.datasetBytes', zh: '总大小', en: 'Total size' },
  { key: 'localStatus.datasetImages', zh: '图像', en: 'Images' },
  { key: 'localStatus.datasetMasks', zh: '掩膜', en: 'Masks' },
  { key: 'localStatus.datasetFingerprint', zh: '清单指纹', en: 'Inventory digest' },
  { key: 'localStatus.generatedAt', zh: '生成时间', en: 'Generated at' },
  { key: 'localStatus.experiments', zh: '实验历史', en: 'Experiment history' },
  { key: 'localStatus.experimentsNone', zh: '工作区里还没有实验记录。', en: 'No experiment is recorded in this workspace yet.' },
  { key: 'localStatus.experimentMetric', zh: '验证指标', en: 'Validation metric' },
  { key: 'localStatus.experimentData', zh: '数据版本', en: 'Data version' },
  { key: 'localStatus.experimentChange', zh: '变更类型', en: 'Change type' },
  { key: 'localStatus.experimentNoResult', zh: '没有结果文件（这条实验没跑完）', en: 'No result file: this experiment never finished' },
  { key: 'localStatus.ledger', zh: '账本', en: 'Ledger' },
  { key: 'localStatus.ledgerLatest', zh: '显示最近 {0} / 共 {1} 条', en: 'Showing the latest {0} of {1}' },
  { key: 'localStatus.ledgerNone', zh: '账本里还没有事件。', en: 'The ledger has no events yet.' },
  { key: 'localStatus.evidence', zh: '论文证据', en: 'Paper evidence' },
  { key: 'localStatus.evidenceNone', zh: '还没有生成论文证据图。', en: 'The paper evidence map has not been generated yet.' },
  { key: 'localStatus.evidenceClaims', zh: '证据声明', en: 'Claims' },
  { key: 'localStatus.evidenceRecords', zh: '文献记录', en: 'Research records' },
  { key: 'localStatus.trace', zh: '证据链', en: 'Evidence chains' },
  { key: 'localStatus.traceBroken', zh: '链断在：{0}', en: 'The chain is broken at: {0}' },
  { key: 'localStatus.traceAllLinked', zh: '四条链与论文终点都接上了。', en: 'All four chains and the paper endpoint are linked.' },
  { key: 'localStatus.chainLinked', zh: '已接上', en: 'Linked' },
  { key: 'localStatus.chainBroken', zh: '断了', en: 'Broken' },
  { key: 'localStatus.chain.rule', zh: '规则链', en: 'Rules' },
  { key: 'localStatus.chain.data', zh: '数据链路', en: 'Data' },
  { key: 'localStatus.chain.experiment', zh: '实验档案链', en: 'Experiments' },
  { key: 'localStatus.chain.research', zh: '文献链', en: 'Research' },
  { key: 'localStatus.chain.paper', zh: '论文终点', en: 'Paper' },
  { key: 'localStatus.chain.ruleValue', zh: '{0} / {1} 个锚点', en: '{0} / {1} anchors' },
  { key: 'localStatus.chain.dataValue', zh: '{0} 个文件 · {1} 个问题', en: '{0} files · {1} issues' },
  { key: 'localStatus.chain.experimentValue', zh: '{0} / {1} 条完成', en: '{0} / {1} completed' },
  { key: 'localStatus.chain.researchValue', zh: '{0} 条记录 · {1} 个来源失败', en: '{0} records · {1} provider failures' },
  { key: 'localStatus.chain.paperValue', zh: '{0} 条声明', en: '{0} claims' },
  { key: 'localStatus.research', zh: '文献检索', en: 'Literature search' },
  { key: 'localStatus.researchNone', zh: '还没有做过检索。', en: 'No search has been run yet.' },
  { key: 'localStatus.researchQuery', zh: '检索式', en: 'Query' },
  { key: 'localStatus.researchSearchedAt', zh: '检索时间', en: 'Searched at' },
  { key: 'localStatus.researchFailures', zh: '来源失败', en: 'Provider failures' },
  { key: 'settings.offlineStatus', zh: '查看离线能力', en: 'View offline capabilities' },
  { key: 'settings.runtime', zh: '运行环境', en: 'Runtime environment' },
  { key: 'settings.platform', zh: '平台', en: 'Platform' },
  { key: 'settings.noGpu', zh: '没有探测到可用 GPU。', en: 'No available GPU detected.' },

  // ---- 写作页 ----
  { key: 'writing.status', zh: '{0} 条声明 · {1} 个章节 · {2} 篇参考 · {3} 条文献记录', en: '{0} claims · {1} sections · {2} references · {3} research records' },
  { key: 'writing.section.package', zh: '证据包', en: 'Package' },
  { key: 'writing.section.structure', zh: '结构与声明', en: 'Structure and claims' },
  { key: 'writing.section.contract', zh: '提交契约', en: 'Submission contract' },
  { key: 'writing.paperPackage', zh: '论文包', en: 'Paper package' },
  { key: 'writing.noPackage', zh: '还没有论文包。当前客户端只能展示后端已生成的证据包，尚不能在页面中触发生成。请先完成规则、数据审计和实验。', en: 'No paper package yet. This client can display a backend-generated package but cannot trigger generation. Complete rules, data audit, and experiments first.' },
  { key: 'writing.viewNextSteps', zh: '查看下一步建议', en: 'View next-step suggestions' },
  { key: 'writing.generatedAt', zh: '生成时间', en: 'Generated at' },
  { key: 'writing.packageDir', zh: '包目录', en: 'Package directory' },
  { key: 'writing.texFile', zh: 'TeX 文件', en: 'TeX file' },
  { key: 'writing.bibFile', zh: 'BibTeX 文件', en: 'BibTeX file' },
  { key: 'writing.evidenceFile', zh: '证据文件', en: 'Evidence file' },
  { key: 'writing.sectionStructure', zh: '章节结构', en: 'Section structure' },
  { key: 'writing.noSections', zh: '没有读到章节。', en: 'No sections found.' },
  { key: 'writing.evidenceChain', zh: '证据链', en: 'Evidence chain' },
  { key: 'writing.noClaims', zh: '还没有实验结论写入证据包。完成实验后再生成一次论文包。', en: 'No experiment conclusions have been written into the evidence package yet. Regenerate the paper package once the experiments are done.' },
  { key: 'writing.submissionContract', zh: '投稿契约', en: 'Submission contract' },
  { key: 'writing.submissionFormat', zh: '提交格式', en: 'Submission format' },
  { key: 'writing.filenameRule', zh: '文件名规则', en: 'File name rule' },
  { key: 'writing.maskSize', zh: '掩码尺寸', en: 'Mask size' },
  { key: 'writing.dailyLimit', zh: '每日提交上限', en: 'Daily submission limit' },
  { key: 'writing.dailyLimitValue', zh: '{0} 次', en: '{0} submissions' },
  { key: 'writing.validationProfile', zh: '校验配置', en: 'Validation profile' },
  { key: 'writing.requiredFiles', zh: '必需文件', en: 'Required files' },
  { key: 'writing.noRequiredFiles', zh: '没有记录必需文件。', en: 'No required files recorded.' },

  // ---- 实验页 ----
  { key: 'exp.status', zh: '{0} 个实验 · {1} 个已完成 · 最佳 {2} · 训练任务 {3}', en: '{0} experiments · {1} completed · best {2} · {3} jobs' },
  { key: 'exp.section.ledger', zh: '实验台账', en: 'Ledger' },
  { key: 'exp.section.jobs', zh: '训练任务', en: 'Jobs' },
  { key: 'exp.section.drafts', zh: '草稿', en: 'Drafts' },
  { key: 'exp.section.register', zh: '登记', en: 'Register' },
  { key: 'exp.trainingJobs', zh: '训练任务', en: 'Training jobs' },
  { key: 'exp.ledgerTitle', zh: '实验账本', en: 'Experiment ledger' },
  { key: 'exp.ledgerEmpty', zh: '当前还没有实验记录。生成实验结果后，这里会显示运行配置、指标和结论。', en: 'No experiment records yet. Once a run produces results, its configuration, metrics, and conclusions will appear here.' },
  { key: 'exp.cloudExecutionUnavailable', zh: '当前云端 HAP 没有数据上传入口和训练执行器，暂时不能在应用内运行实验；此页只展示已生成的记录。', en: 'This cloud HAP has no data upload entry or training executor, so experiments cannot run in the app yet. This page only shows existing records.' },
  { key: 'exp.viewNextSteps', zh: '查看下一步建议', en: 'View next-step suggestions' },
  { key: 'exp.jobsEmpty', zh: '调度队列是空的。', en: 'The scheduler queue is empty.' },
  { key: 'exp.draftsTitle', zh: '等待人工批准的草案', en: 'Drafts awaiting human approval' },
  { key: 'exp.draftsEmpty', zh: '还没有待批准的草案。', en: 'No drafts awaiting approval yet.' },
  { key: 'exp.registerTitle', zh: '登记实验草案', en: 'Register an experiment draft' },
  { key: 'exp.draftHint', zh: '草案只登记假设，不会启动训练；执行前需要你单独批准。', en: 'A draft only records the hypothesis; it never starts training, and every run needs your approval.' },
  { key: 'exp.registerDraft', zh: '登记草案', en: 'Register draft' },
  { key: 'exp.hypothesisPlaceholder', zh: '例如：用边界损失替换交叉熵，观察 global_water_iou 是否提升', en: 'e.g. swap cross-entropy for boundary loss and see whether global_water_iou improves' },
  { key: 'exp.hypothesisTooShort', zh: '假设至少写 {0} 个字符，写清「改什么、看什么指标」。', en: 'Write at least {0} characters and spell out what changes and which metric to watch.' },
  { key: 'exp.draftSubmitted', zh: '草案 {0} 已登记，状态：等待人工批准（不会自动训练）。', en: 'Draft {0} registered, status: awaiting human approval (training will not start automatically).' },
  { key: 'exp.changeType', zh: '变更类型 {0}', en: 'Change type {0}' },
  { key: 'exp.metric', zh: '指标 {0}', en: 'Metric {0}' },
  { key: 'exp.runtime', zh: '耗时 {0}', en: 'Runtime {0}' },
  { key: 'exp.submittedAt', zh: '提交于 {0}', en: 'Submitted {0}' },
  { key: 'exp.registeredAt', zh: '登记于 {0}', en: 'Registered {0}' },
  { key: 'exp.approveAction', zh: '记录批准', en: 'Record approval' },
  { key: 'exp.approveConfirm', zh: '确认批准', en: 'Confirm approval' },
  { key: 'exp.approved', zh: '已批准', en: 'Approved' },
  { key: 'exp.approvedAt', zh: '批准于 {0}', en: 'Approved {0}' },
  { key: 'exp.approveHint', zh: '只写入一条人工批准记录，不会启动训练；执行仍要人走命令行。', en: 'Writes a human approval record only; execution stays a manual command-line step.' },

  // ---- 溯源 ----
  { key: 'trace.status', zh: '锚点 {0}/{1} · 在册实验 {2} · 文献记录 {3} · 证据声明 {4}', en: 'Anchors {0}/{1} · {2} in-scope experiments · {3} research records · {4} claims' },
  { key: 'trace.statAnchors', zh: '已带锚点', en: 'With anchor' },
  { key: 'trace.statRecords', zh: '文献记录', en: 'Research records' },

  // 分段导航：四条证据链 + 论文终点，一次只看一段，短到不用长滚动。
  { key: 'trace.section.rule', zh: '规则', en: 'Rules' },
  { key: 'trace.section.data', zh: '数据', en: 'Data' },
  { key: 'trace.section.experiment', zh: '实验', en: 'Experiments' },
  { key: 'trace.section.research', zh: '文献', en: 'Research' },
  { key: 'trace.section.paper', zh: '论文', en: 'Paper' },

  { key: 'trace.ruleTitle', zh: '规则证据链', en: 'Rule evidence chain' },
  { key: 'trace.ruleGateApproved', zh: '已人工确认', en: 'Human-confirmed' },
  { key: 'trace.ruleGatePending', zh: '待人工确认', en: 'Awaiting human confirmation' },
  { key: 'trace.ruleGateStale', zh: '已确认，但出现新缺口', en: 'Confirmed, but new gaps appeared' },
  { key: 'trace.gapTotal', zh: '缺口 {0} 项：值未确认 {1} 项、缺官方锚点 {2} 项', en: '{0} open gaps: {1} unresolved values, {2} missing anchors' },
  { key: 'trace.specFile', zh: '规格文件', en: 'Specification' },
  { key: 'trace.sourceType', zh: '来源类型', en: 'Source type' },
  { key: 'trace.sourceLocator', zh: '来源定位', en: 'Source locator' },
  { key: 'trace.reviewedAt', zh: '复核时间', en: 'Reviewed at' },
  { key: 'trace.approvedAt', zh: '人工确认时间', en: 'Confirmed at' },
  { key: 'trace.approvedNote', zh: '复核说明', en: 'Review note' },
  { key: 'trace.fieldColumn', zh: '字段', en: 'Field' },
  { key: 'trace.valueLabel', zh: '值', en: 'Value' },
  { key: 'trace.anchorLabel', zh: '官方锚点', en: 'Official anchor' },
  { key: 'trace.anchorOk', zh: '已带锚点', en: 'Anchored' },
  { key: 'trace.anchorMissing', zh: '缺锚点', en: 'No anchor' },
  { key: 'trace.valueUnresolved', zh: '值未确认', en: 'Unresolved' },
  { key: 'trace.evidenceDocs', zh: '人工证据文档', en: 'Human evidence documents' },
  { key: 'trace.docCount', zh: '{0} 份', en: '{0} files' },
  { key: 'trace.noFields', zh: '这个规格没有需要确认的必备字段。', en: 'This specification has no required fields to confirm.' },
  { key: 'trace.noDocs', zh: '工作区里还没有证据文档。', en: 'No evidence documents in the workspace yet.' },

  { key: 'trace.dataTitle', zh: '数据指纹链', en: 'Data fingerprint chain' },
  { key: 'trace.auditDir', zh: '数据目录', en: 'Data directory' },
  { key: 'trace.auditFingerprint', zh: '内容指纹', en: 'Content fingerprint' },
  { key: 'trace.auditFiles', zh: '审计文件数', en: 'Audited files' },
  { key: 'trace.auditIssues', zh: '审计问题数', en: 'Audit issues' },
  { key: 'trace.auditGeneratedAt', zh: '审计时间', en: 'Audited at' },
  { key: 'trace.auditMissing', zh: '还没有数据审计，因此没有任何实验能计入当前赛题。', en: 'No data audit yet, so no experiment can count for this competition.' },
  { key: 'trace.inScope', zh: '计入当前赛题', en: 'In current scope' },
  { key: 'trace.excluded', zh: '不计入当前赛题', en: 'Out of scope' },
  { key: 'trace.exclusion.synthetic', zh: '跑在合成数据上的基础设施实验', en: 'Infrastructure run on synthetic data' },
  { key: 'trace.exclusion.outside', zh: '数据不在这次审计范围内', en: 'Data outside the audited scope' },
  { key: 'trace.exclusion.noAudit', zh: '没有数据审计', en: 'No data audit' },
  { key: 'trace.dataVersion', zh: '数据版本 {0}', en: 'Data version {0}' },
  { key: 'trace.noExperiments', zh: '还没有实验清单。', en: 'No experiment manifests yet.' },

  { key: 'trace.expTitle', zh: '实验档案链', en: 'Experiment record chain' },
  { key: 'trace.expCount', zh: '{0}/{1} 计入当前赛题', en: '{0}/{1} in current scope' },
  { key: 'trace.artifactMissing', zh: '产物缺失 {0} 个', en: '{0} artifacts missing' },
  { key: 'trace.detailsOpen', zh: '收起详情', en: 'Hide details' },
  { key: 'trace.detailsClose', zh: '查看详情', en: 'Show details' },
  { key: 'trace.hypothesis', zh: '假设', en: 'Hypothesis' },
  { key: 'trace.changeTypeRow', zh: '变更类型', en: 'Change type' },
  { key: 'trace.configPath', zh: '配置路径', en: 'Config path' },
  { key: 'trace.configHash', zh: '配置指纹', en: 'Config digest' },
  { key: 'trace.gitRow', zh: 'Git 绑定', en: 'Git binding' },
  { key: 'trace.gitUnbound', zh: '未绑定仓库', en: 'No repository bound' },
  { key: 'trace.gitDirty', zh: '有未提交改动', en: 'Uncommitted changes' },
  { key: 'trace.gitClean', zh: '工作区干净', en: 'Clean' },
  { key: 'trace.envRow', zh: '运行环境', en: 'Runtime environment' },
  { key: 'trace.metricRow', zh: '指标', en: 'Metric' },
  { key: 'trace.decisionRow', zh: '决策', en: 'Decision' },
  { key: 'trace.conclusionRow', zh: '结论', en: 'Conclusion' },
  { key: 'trace.runtimeRow', zh: '耗时', en: 'Runtime' },
  { key: 'trace.trackerRow', zh: '记录后端', en: 'Tracker backend' },
  { key: 'trace.artifactsRow', zh: '产物', en: 'Artifacts' },
  { key: 'trace.artifactPresent', zh: '存在', en: 'Present' },
  { key: 'trace.artifactAbsent', zh: '缺失', en: 'Missing' },
  { key: 'trace.approvalRow', zh: '人工批准', en: 'Human approval' },
  { key: 'trace.approvalNone', zh: '未记录', en: 'Not recorded' },
  { key: 'trace.approvalVerified', zh: '记录已核验', en: 'Approval verified' },
  { key: 'trace.approvalNote', zh: '批准备注：{0}', en: 'Approval note: {0}' },
  { key: 'trace.approvalUnverified', zh: '未核验：{0}', en: 'Not verified: {0}' },
  { key: 'trace.approvalMissingDigest', zh: '缺少配置指纹', en: 'Configuration fingerprint missing' },
  { key: 'trace.approvalInvalidDigest', zh: '配置指纹格式无效', en: 'Configuration fingerprint invalid' },
  { key: 'trace.approvalMissing', zh: '未找到记录', en: 'Record not found' },
  { key: 'trace.approvalUnreadable', zh: '记录无法读取', en: 'Record unreadable' },
  { key: 'trace.approvalWrongType', zh: '记录类型不匹配', en: 'Record type mismatch' },
  { key: 'trace.approvalDigestMismatch', zh: '配置指纹不匹配', en: 'Configuration fingerprint mismatch' },
  { key: 'trace.approvalIncomplete', zh: '记录信息不完整', en: 'Record incomplete' },
  { key: 'trace.approvalUnknown', zh: '原因未知', en: 'Unknown reason' },
  { key: 'trace.approvalBy', zh: '批准人 {0}', en: 'Approved by {0}' },
  { key: 'trace.statusCheckRow', zh: '清单与结果核对', en: 'Manifest and result check' },
  { key: 'trace.statusConsistent', zh: '两处状态一致', en: 'Statuses match' },
  { key: 'trace.statusDiverged', zh: '结果：{0}；清单：{1}', en: 'Result: {0}; manifest: {1}' },
  { key: 'trace.statusCheckUnavailable', zh: '缺少清单或结果状态', en: 'Manifest or result status missing' },
  { key: 'trace.resultFile', zh: '结果文件', en: 'Result file' },
  { key: 'trace.expEmpty', zh: '还没有实验记录。先在工作流里确认规则，再跑一次可复现的基线。', en: 'No experiments yet. Confirm the rules in the workflow, then run a reproducible baseline.' },

  { key: 'trace.researchTitle', zh: '文献链', en: 'Research chain' },
  { key: 'trace.query', zh: '检索条件', en: 'Query' },
  { key: 'trace.searchedAt', zh: '检索时间', en: 'Searched at' },
  { key: 'trace.providerFailure', zh: '检索源失败', en: 'Provider failures' },
  { key: 'trace.relevance', zh: '相关度 {0}', en: 'Relevance {0}' },
  { key: 'trace.refFiles', zh: '引用文件', en: 'Reference files' },
  { key: 'trace.recordsShown', zh: '显示前 {0} 条，共 {1} 条；完整列表在文献页。', en: 'Showing the first {0} of {1}; the full list is on the Literature page.' },
  { key: 'trace.researchEmpty', zh: '还没有文献检索记录。', en: 'No research records yet.' },

  { key: 'trace.paperTitle', zh: '论文终点', en: 'Paper destination' },
  { key: 'trace.packageDir', zh: '证据包目录', en: 'Package directory' },
  { key: 'trace.generatedAt', zh: '生成时间', en: 'Generated at' },
  { key: 'trace.sectionsLabel', zh: '章节数', en: 'Sections' },
  { key: 'trace.bibLabel', zh: '参考文献', en: 'Bibliography entries' },
  { key: 'trace.claimsTitle', zh: '证据声明', en: 'Evidence claims' },
  { key: 'trace.claimsEmpty', zh: '证据包里还没有声明：论文只写有证据支撑的内容。', en: 'No claims in the package yet: the paper only states what evidence supports.' },
  { key: 'trace.claimResolved', zh: '引用的结果文件存在', en: 'Cited result exists' },
  { key: 'trace.claimUnresolved', zh: '引用的结果文件缺失', en: 'Cited result missing' },
  { key: 'trace.paperMissing', zh: '还没有论文证据包。', en: 'No paper evidence package yet.' },

  // ---- 研究循环 ----
  // 动作名、九项核查、判定与状态的中文名**不在这里**：它们属于科研契约，由后端
  // `GET /api/research/contract` 发出，端侧运行时取。这里只有这一页自己的话。
  { key: 'loop.status', zh: '假设 {0}（可证伪 {1}） · 实验 {2} · 分支 {3}/{4} 活跃 · 证据 {5}', en: 'Hypotheses {0} ({1} falsifiable) · experiments {2} · branches {3}/{4} active · evidence {5}' },
  { key: 'loop.statusUndesignable', zh: ' · 其中 {0} 个设计跑不起来', en: ' · {0} designs cannot run' },
  { key: 'loop.section.now', zh: '当前', en: 'Now' },
  { key: 'loop.section.hypotheses', zh: '假设', en: 'Hypotheses' },
  { key: 'loop.section.evidence', zh: '证据', en: 'Evidence' },
  { key: 'loop.section.history', zh: '决策轨迹', en: 'Decisions' },
  { key: 'loop.metric.hypotheses', zh: '假设总数', en: 'Hypotheses' },
  { key: 'loop.metric.falsifiable', zh: '可被实验判决', en: 'Falsifiable' },
  { key: 'loop.metric.experiments', zh: '实验总数', en: 'Experiments' },
  { key: 'loop.metric.awaiting', zh: '跑完没核查', en: 'Unchecked runs' },
  { key: 'loop.metric.undesignable', zh: '设计跑不起来', en: 'Dead designs' },
  { key: 'loop.stepOne', zh: '推进一步', en: 'Step once' },
  { key: 'loop.stepThree', zh: '连推三步', en: 'Step three times' },
  { key: 'loop.backfill', zh: '重新回填实验记录', en: 'Re-sync experiment records' },
  { key: 'loop.stepping', zh: '推进中（{0}）', en: 'Running ({0})' },
  { key: 'loop.busy', zh: '正在提交…', en: 'Submitting…' },
  { key: 'loop.hint', zh: '每一步都会真调模型：先由编排器决定做什么，再交给执行器带工具去做。要动算力的动作（跑训练、复现）不会被自动触发，它们会停在这里等人批准。', en: 'Each step really calls the model: the orchestrator decides what to do, then the executor carries it out with tools. Actions that spend compute (training, replication) are never triggered automatically — they stop here and wait for a human.' },
  { key: 'loop.unknownAction', zh: '未知动作', en: 'Unknown action' },
  { key: 'loop.recent', zh: '最近的推进', en: 'Recent runs' },
  { key: 'loop.noJobs', zh: '还没有推进过。点「推进一步」让循环开始。', en: 'Nothing has been advanced yet. Press “Step once” to start the loop.' },
  { key: 'loop.jobMax', zh: '最多 {0} 步', en: 'up to {0} steps' },
  { key: 'loop.jobStopped', zh: '停止于「{0}」', en: 'stopped: “{0}”' },
  { key: 'loop.pending', zh: '等待人工批准：{0} —— 它们没被执行，但也没挡住其他路线。', en: 'Waiting for approval: {0} — not executed, but they did not block other lines.' },
  { key: 'loop.noHypotheses', zh: '还没有假设。循环会先检索文献，再据此提出假设。', en: 'No hypotheses yet. The loop searches the literature first, then proposes hypotheses.' },
  { key: 'loop.predictions', zh: '预测', en: 'Predictions' },
  { key: 'loop.falsifiers', zh: '什么结果会否定它', en: 'What would refute it' },
  { key: 'loop.rationale', zh: '依据', en: 'Basis' },
  { key: 'loop.unfalsifiable', zh: '不可证伪', en: 'Unfalsifiable' },
  { key: 'loop.unfalsifiableHint', zh: '既没有预测也没有反证条件 —— 编排器会先要求把它补成可判决的，补不动就终止这条路线。', en: 'No predictions and no falsifiers — the orchestrator will first ask for a judgeable version, and kill the line if it cannot produce one.' },
  { key: 'loop.blocked', zh: '这次设计跑不起来：{0}', en: 'This design cannot run: {0}' },
  { key: 'loop.blockedUnknown', zh: '没有对照也没有配置（生成它时还没有记下原因）', en: 'no baseline and no config (the reason was not recorded when it was made)' },
  { key: 'loop.noEvidence', zh: '还没有核查过任何实验。', en: 'No experiment has been checked yet.' },
  { key: 'loop.checkYes', zh: '是', en: 'Yes' },
  { key: 'loop.checkNo', zh: '否', en: 'No' },
  { key: 'loop.checkUnknown', zh: '未核查', en: 'Not checked' },
  { key: 'loop.noDecisions', zh: '这个工作区还没有推进过循环。', en: 'The loop has never been advanced in this workspace.' },
  { key: 'loop.actionFailed', zh: '操作失败：{0}', en: 'Action failed: {0}' },

  // ---- 能力网格 / 工作流步骤 ----
  { key: 'cap.title', zh: '内置能力', en: 'Capabilities' },
  { key: 'cap.searchPlaceholder', zh: '搜索适配器', en: 'Search adapters' },
  { key: 'cap.empty', zh: '后端未连接，暂时读不到内置能力清单。', en: "Backend offline; the capability list can't be loaded right now." },
  { key: 'cap.noMatch', zh: '没有匹配的适配器，换个词试试。', en: 'No adapter matches; try another word.' },
  { key: 'cap.clear', zh: '清空', en: 'Clear' },
  { key: 'cap.matchCount', zh: '匹配 {0} 个 / 共 {1} 个适配器', en: '{0} of {1} adapters match' },

  // 适配器的展示文案。后端的 training/catalog.py 是一张固定的英文表（标识、类型、契约说明
  // 全是英文），所以这一层翻译必须**按标识**对上；对不上的标识原样显示英文原文。
  // 后端改表时，这几行要跟着改：键名是适配器/类型的标识，不是那句英文。
  { key: 'cap.runner.syntheticBinaryClassification', zh: '合成二分类（冒烟测试）', en: 'Synthetic binary classification' },
  { key: 'cap.runner.tabularClassification', zh: '表格分类', en: 'Tabular classification' },
  { key: 'cap.runner.tabularRegression', zh: '表格回归', en: 'Tabular regression' },
  { key: 'cap.runner.imageClassification', zh: '图像分类', en: 'Image classification' },
  { key: 'cap.runner.imageSegmentation', zh: '图像分割', en: 'Image segmentation' },
  { key: 'cap.runner.watersegExternal', zh: '水域分割（外部工程）', en: 'Water segmentation (external project)' },
  { key: 'cap.runner.externalDetection', zh: '目标检测（外部工程）', en: 'Object detection (external project)' },

  { key: 'cap.kind.infrastructureSmokeTest', zh: '链路冒烟测试', en: 'Pipeline smoke test' },
  { key: 'cap.kind.classification', zh: '分类', en: 'Classification' },
  { key: 'cap.kind.regression', zh: '回归', en: 'Regression' },
  { key: 'cap.kind.imageClassification', zh: '图像分类', en: 'Image classification' },
  { key: 'cap.kind.binarySegmentation', zh: '二值分割', en: 'Binary segmentation' },
  { key: 'cap.kind.approvedExternalTrainingProject', zh: '已批准的外部训练工程', en: 'Approved external training project' },

  { key: 'cap.contract.syntheticBinaryClassification', zh: '数据在内存里生成，只用来验证训练链路通不通，不能当作竞赛成绩。', en: 'Data is generated in memory; it only proves the pipeline runs and is never a competition score.' },
  { key: 'cap.contract.tabularClassification', zh: '训练、测试各一份 CSV，含目标列，可选 ID 列。', en: 'A train CSV and a test CSV, with a target column and an optional ID column.' },
  { key: 'cap.contract.tabularRegression', zh: '训练、测试各一份 CSV，目标列是数值，可选 ID 列。', en: 'A train CSV and a test CSV, with a numeric target column and an optional ID column.' },
  { key: 'cap.contract.imageClassification', zh: '每类一个子目录放训练图，可另给一个扁平的测试图目录。', en: 'Training images in one subdirectory per class, plus an optional flat test-image folder.' },
  { key: 'cap.contract.imageSegmentation', zh: '训练图与二值掩码分两个目录，文件名主干要一一对应；可另给测试图目录。', en: 'Train image and binary-mask folders with matching filename stems, plus an optional test-image folder.' },
  { key: 'cap.contract.watersegExternal', zh: '已审计的图像与掩码目录，外加一份冻结的、你自有的 waterseg 源码树，以及明确批准的 CUDA 配置。', en: 'Audited image and mask folders plus a frozen, user-owned waterseg source tree and an explicitly approved CUDA configuration.' },
  { key: 'cap.contract.externalDetection', zh: '已审计的目标检测图像树，外加一份冻结的、你自有的检测工程源码；指标直接读该工程自己产出的 Ultralytics results.csv。', en: "An audited object-detection image tree plus a frozen, user-owned detection source tree; the metric is read from that project's own Ultralytics results.csv." },

  { key: 'card.workflow', zh: '研究工作流', en: 'Research workflow' }
];

/** 键到文案的索引。 */
const TABLE: Map<string, Entry> = new Map<string, Entry>();
for (const entry of ENTRIES) {
  TABLE.set(entry.key, entry);
}

/** 当前语言。用模块变量而不是每次读 AppStorage，`t()` 会被高频调用。 */
let current: string = LANG_ZH;

/** 偏好存储需要的上下文，由 initLang 注入。 */
let prefContext: common.Context | null = null;

/** 规范化语言值：只认 zh / en，其他一律回落到中文。 */
export function normalizeLang(value: string): string {
  return value === LANG_EN ? LANG_EN : LANG_ZH;
}

export function currentLang(): string {
  return current;
}

/**
 * 切换语言。
 *
 * 写 AppStorage 是为了让订阅了 LANG_KEY 的组件重绘；持久化失败不影响本次切换。
 */
export function setLang(lang: string): void {
  current = normalizeLang(lang);
  AppStorage.setOrCreate<string>(LANG_KEY, current);
  persistLang(current).catch(() => {
    // 存不下来只影响下次启动的默认值，不打断当前这次切换。
  });
}

/**
 * 启动时确定初始语言：优先用上次的选择，没有就跟系统语言。
 *
 * 在 EntryAbility.onCreate 里调用，先于界面加载，避免先显示中文再跳成英文。
 */
export async function initLang(context: common.Context): Promise<void> {
  prefContext = context;
  let lang: string = systemLang();
  try {
    const store: preferences.Preferences = await preferences.getPreferences(context, PREF_STORE);
    const saved: preferences.ValueType = await store.get(PREF_LANG, '');
    if (typeof saved === 'string' && saved.length > 0) {
      lang = normalizeLang(saved);
    }
  } catch (err) {
    // 读不到偏好就用系统语言，不阻塞启动。
  }
  current = lang;
  AppStorage.setOrCreate<string>(LANG_KEY, lang);
}

/** 系统语言是中文就默认中文，否则默认英文。 */
function systemLang(): string {
  try {
    return i18n.System.getSystemLanguage().toLowerCase().startsWith('zh') ? LANG_ZH : LANG_EN;
  } catch (err) {
    return LANG_ZH;
  }
}

async function persistLang(lang: string): Promise<void> {
  if (prefContext === null) {
    return;
  }
  try {
    const store: preferences.Preferences = await preferences.getPreferences(prefContext, PREF_STORE);
    await store.put(PREF_LANG, lang);
    await store.flush();
  } catch (err) {
    // 偏好写入失败只影响下次启动的默认语言，不向外抛。
  }
}

/** 取文案；键不存在时返回键名本身，方便一眼看出漏了哪个键。 */
export function t(key: string): string {
  return tFor(current, key);
}

/**
 * 指定语言取文案，界面组件一律走这个而不是 `t()`。
 *
 * ArkUI 的局部刷新是按「读到状态变量的那个节点」算的：组件的 build 里如果没有
 * 读过 `@StorageLink('lang')`，切换语言时它一个节点都不会重建。所以组件里统一
 * 调 `this.tr(key)`（内部把 `this.lang` 传进来），读一次 lang 就等于把当前节点
 * 登记到语言变化上。`t()` 只留给 I18n 自己的内部调用和 Format 的纯函数用。
 */
export function tFor(lang: string, key: string): string {
  const entry: Entry | undefined = TABLE.get(key);
  if (entry === undefined) {
    return key;
  }
  return normalizeLang(lang) === LANG_EN ? entry.en : entry.zh;
}

/**
 * 带占位符取文案，`{0}`、`{1}` 依次被替换。
 *
 * 中英文语序不同，所以带数字的句子要用占位符而不是字符串拼接。
 */
export function tf(key: string, args: string[]): string {
  return tfFor(current, key, args);
}

/** tf 的指定语言版本，给组件用。 */
export function tfFor(lang: string, key: string, args: string[]): string {
  let text: string = tFor(lang, key);
  for (let index = 0; index < args.length; index++) {
    text = text.replace(`{${index}}`, args[index]);
  }
  return text;
}

/** 语言名：用该语言自己的写法，英文界面下也显示「简体中文」。 */
export function langName(lang: string): string {
  return normalizeLang(lang) === LANG_EN ? t('menu.langEn') : t('menu.langZh');
}
