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

  // ---- 顶栏 ----
  { key: 'topbar.tagline', zh: '让研究更自由地发生', en: 'Let research happen freely' },
  { key: 'topbar.notifications', zh: '通知', en: 'Notifications' },
  { key: 'topbar.avatarHint', zh: '账户菜单', en: 'Account menu' },
  { key: 'topbar.projectHint', zh: '当前项目，点击切换', en: 'Current project; click to switch' },

  // ---- 侧栏 ----
  { key: 'nav.overview', zh: '概览', en: 'Overview' },
  { key: 'nav.workflow', zh: '工作流', en: 'Workflow' },
  { key: 'nav.experiment', zh: '实验', en: 'Experiments' },
  { key: 'nav.literature', zh: '文献', en: 'Literature' },
  { key: 'nav.data', zh: '数据', en: 'Data' },
  { key: 'nav.writing', zh: '写作', en: 'Writing' },
  { key: 'nav.trace', zh: '溯源', en: 'Trace' },
  { key: 'nav.settings', zh: '设置', en: 'Settings' },
  { key: 'nav.quote1', zh: '更好的问题', en: 'Better questions' },
  { key: 'nav.quote2', zh: '会带来更好的世界。', en: 'make a better world.' },

  // ---- 账户菜单 ----
  { key: 'menu.workspace', zh: '本地工作区', en: 'Local workspace' },
  { key: 'menu.badge', zh: '本地', en: 'Local' },
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

  // ---- 项目总览 ----
  { key: 'overview.title', zh: '项目总览', en: 'Project overview' },
  { key: 'overview.subtitle', zh: '从问题到论文，与你一起推进每一个重要的研究时刻。', en: 'From question to paper, moving every important research moment forward with you.' },
  { key: 'overview.summary', zh: '当前阶段：{0} · 数据文件 {1}（{2} 处质量问题）· 研究记录 {3} · 已完成实验 {4}', en: 'Stage: {0} · {1} data files ({2} issues) · {3} research records · {4} completed experiments' },

  // ---- 快速开始 ----
  { key: 'quick.title', zh: '快速开始', en: 'Quick start' },
  { key: 'quick.newProject', zh: '新建项目', en: 'New project' },
  { key: 'quick.newProjectDetail', zh: '开始一个新的研究课题', en: 'Start a new research topic' },
  { key: 'quick.newWorkflow', zh: '创建工作流', en: 'Create a workflow' },
  { key: 'quick.newWorkflowDetail', zh: '定制你的研究流程', en: 'Tailor your research process' },
  { key: 'quick.runExperiment', zh: '运行实验', en: 'Run an experiment' },
  { key: 'quick.runExperimentDetail', zh: '让 AI 帮你执行实验', en: 'Let the AI execute it for you' },
  { key: 'quick.searchLiterature', zh: '检索文献', en: 'Search literature' },
  { key: 'quick.searchLiteratureDetail', zh: '快速找到相关研究', en: 'Find related work fast' },
  { key: 'quick.analyzeData', zh: '分析数据', en: 'Analyze data' },
  { key: 'quick.analyzeDataDetail', zh: '从数据中发现洞察', en: 'Find insight in your data' },
  { key: 'quick.startWriting', zh: '开始写作', en: 'Start writing' },
  { key: 'quick.startWritingDetail', zh: '与 AI 协作完成论文', en: 'Draft the paper with the AI' },

  // ---- 项目选择页 ----
  { key: 'gate.title', zh: '选择项目', en: 'Choose a project' },
  { key: 'gate.subtitle', zh: '每个项目是一份独立的竞赛工作区：规则、数据、实验与投稿材料互不干扰。', en: 'Each project is its own competition workspace: rules, data, experiments, and submission material stay separate.' },
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
  { key: 'gate.hint', zh: '项目存放在后端工作区里，界面只读取与登记，不改动证据文件。', en: 'Projects live in the backend workspace; the app only reads and records, never edits evidence files.' },

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
  { key: 'workflow.title', zh: '工作流', en: 'Workflow' },
  { key: 'workflow.subtitle', zh: '阶段推进由后端状态机驱动，需要人工确认的环节会停下来等你。', en: 'Stage progression is driven by the backend state machine; steps that need human confirmation wait for you.' },
  { key: 'workflow.status', zh: '阶段 {0} · {1} · 已完成实验 {2} · 阻塞项 {3}', en: 'Stage {0} · {1} · {2} completed · {3} blockers' },
  { key: 'workflow.section.status', zh: '现状', en: 'Status' },
  { key: 'workflow.section.rules', zh: '规则缺口', en: 'Rule gaps' },
  { key: 'workflow.section.blockers', zh: '阻塞', en: 'Blockers' },
  { key: 'workflow.section.actions', zh: '下一步', en: 'Next steps' },
  { key: 'workflow.section.ask', zh: '问一问', en: 'Ask' },
  { key: 'workflow.autoOn', zh: '已开启', en: 'On' },
  { key: 'workflow.autoOff', zh: '已关闭', en: 'Off' },
  { key: 'workflow.blockers', zh: '阻塞项', en: 'Blockers' },
  { key: 'workflow.componentStatus', zh: '环节状态', en: 'Step status' },
  { key: 'workflow.componentStatusHint', zh: '每个环节是否放行，取决于账本里的真实记录', en: 'Whether a step is cleared depends on the real records in the ledger' },
  { key: 'workflow.ruleGapsTitle', zh: '规则缺口', en: 'Rule gaps' },
  { key: 'workflow.ruleReady', zh: '必填规则已就绪', en: 'Required rules ready' },
  { key: 'workflow.ruleNotReady', zh: '规则尚未就绪', en: 'Rules not ready yet' },
  { key: 'workflow.rulesSummary', zh: '{0}：{1} 个必填字段，{2} 项待办、涉及 {3} 个字段（profile：{4}）', en: '{0}: {1} required fields, {2} open items across {3} fields (profile: {4})' },
  { key: 'workflow.noRuleGaps', zh: '必填规则字段都已确认。', en: 'All required rule fields are confirmed.' },
  { key: 'workflow.blockersSubtitle', zh: '共 {0} 条待确认问题（结构性缺口见上方「规则缺口」）', en: '{0} open questions (see Rule gaps above for structural gaps)' },
  { key: 'workflow.noOpenQuestions', zh: '当前没有待确认问题。', en: 'No open questions right now.' },
  { key: 'workflow.actions', zh: '建议动作', en: 'Suggested actions' },
  { key: 'workflow.actionsHint', zh: '后端决策队列按优先级给出，执行前由你确认', en: 'Ranked by priority from the backend decision queue; you confirm before anything runs' },
  { key: 'workflow.noActions', zh: '当前没有待办动作。', en: 'No pending actions right now.' },
  { key: 'workflow.askTitle', zh: '问一问 AI', en: 'Ask the AI' },
  { key: 'workflow.askSubtitle', zh: '问题会带上当前阶段交给后端 Agent，它自己决定查哪些记录', en: 'Your question goes to the backend agent with the current stage; it decides which records to read' },
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
  { key: 'workflow.gateTitle', zh: '人工确认规则', en: 'Confirm the rules' },
  { key: 'workflow.gateScope', zh: '这是工作流的第一道关口：确认后会写进竞赛规范与账本，但不会启动任何训练。', en: 'The first gate of the workflow: confirming writes the spec and the ledger, but starts nothing.' },
  { key: 'workflow.gateDone', zh: '规则已人工确认', en: 'Rules confirmed by a human' },
  { key: 'workflow.gateBlocked', zh: '还有 {0} 项待办，处理完才允许确认。', en: '{0} items must be resolved before confirming.' },
  { key: 'workflow.gateNotePlaceholder', zh: '复核说明（必填）：依据哪份官方文档、确认了什么', en: 'Review note (required): which official document, and what was confirmed' },
  { key: 'workflow.gateSubmit', zh: '确认规则', en: 'Confirm rules' },
  { key: 'workflow.gateApproving', zh: '正在记录…', en: 'Recording…' },
  { key: 'workflow.gateNoteRequired', zh: '复核说明不能为空。', en: 'A review note is required.' },
  { key: 'workflow.gateRecorded', zh: '已记录：{0}', en: 'Recorded {0}' },

  // ---- 官方证据录入 ----
  { key: 'workflow.evidenceTitle', zh: '录入官方证据', en: 'Record official evidence' },
  { key: 'workflow.evidenceSubtitle', zh: '逐字段填「值 + 官方锚点」：锚点就是这条结论在官方原文里的出处', en: 'Fill in the value and its official anchor for each field; the anchor is where that fact appears in the official source' },
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

  // ---- 项目总览补充 ----
  { key: 'overview.nextStep', zh: '下一步', en: 'Next step' },
  { key: 'overview.noPendingActions', zh: '当前没有待办动作', en: 'No pending actions' },
  { key: 'overview.recentUpdates', zh: '最近更新', en: 'Recent updates' },
  { key: 'overview.viewAll', zh: '查看全部 →', en: 'View all →' },
  { key: 'overview.noRecords', zh: '暂无记录', en: 'No records yet' },

  // ---- 数据页 ----
  { key: 'data.kindFile', zh: '普通文件', en: 'Regular file' },
  { key: 'data.kindImage', zh: '图像', en: 'Image' },
  { key: 'data.kindMask', zh: '掩码', en: 'Mask' },
  { key: 'data.kindTable', zh: '表格', en: 'Table' },
  { key: 'data.splitTrain', zh: '训练集', en: 'Train' },
  { key: 'data.splitValidation', zh: '验证集', en: 'Validation' },
  { key: 'data.splitTest', zh: '测试集', en: 'Test' },
  { key: 'data.splitUnassigned', zh: '未分配', en: 'Unassigned' },
  { key: 'data.subtitle', zh: '数据先过审计再进训练：文件清单、图像维度、掩码与重复项都记录在案。', en: 'Data is audited before it enters training: file inventory, image dimensions, masks, and duplicates are all on record.' },
  { key: 'data.status', zh: '{0} 个文件 · {1} · {2} 个问题 · {3} 组重复', en: '{0} files · {1} · {2} issues · {3} duplicate groups' },
  { key: 'data.section.source', zh: '审计来源', en: 'Audit source' },
  { key: 'data.section.images', zh: '图像与掩码', en: 'Images and masks' },
  { key: 'data.section.kinds', zh: '类型与划分', en: 'Kinds and splits' },
  { key: 'data.section.issues', zh: '重复与表格', en: 'Duplicates and tables' },
  { key: 'data.auditSource', zh: '审计来源', en: 'Audit source' },
  { key: 'data.auditSourceHint', zh: '每一次审计都固定记录目录、时间与清单哈希，便于复核', en: 'Every audit records the directory, time, and inventory hash for review' },
  { key: 'data.dataDir', zh: '数据目录', en: 'Data directory' },
  { key: 'data.auditTime', zh: '审计时间', en: 'Audited at' },
  { key: 'data.metadataFormat', zh: '元数据格式', en: 'Metadata format' },
  { key: 'data.inventoryHash', zh: '清单哈希', en: 'Inventory hash' },
  { key: 'data.schemaVersion', zh: '审计结构版本', en: 'Audit schema version' },
  { key: 'data.imagesAndMasks', zh: '图像与掩码', en: 'Images and masks' },
  { key: 'data.imagesAndMasksHint', zh: '尺寸与通道一致时才允许进入训练', en: 'Training starts only when dimensions and channels match' },
  { key: 'data.imageCount', zh: '图像数量', en: 'Images' },
  { key: 'data.imageSize', zh: '图像尺寸', en: 'Image size' },
  { key: 'data.maskCount', zh: '掩码数量', en: 'Masks' },
  { key: 'data.emptyMasks', zh: '空掩码', en: 'Empty masks' },
  { key: 'data.foregroundRatio', zh: '前景占比', en: 'Foreground ratio' },
  { key: 'data.fileKinds', zh: '文件类型', en: 'File types' },
  { key: 'data.fileKindsHint', zh: '按类型统计的数量', en: 'Count by file type' },
  { key: 'data.noFileKinds', zh: '没有统计到文件类型。', en: 'No file types recorded.' },
  { key: 'data.splits', zh: '数据划分', en: 'Data splits' },
  { key: 'data.splitsHint', zh: '当前数据集的分组情况', en: 'How the current dataset is grouped' },
  { key: 'data.noSplits', zh: '没有划分记录。', en: 'No split records.' },
  { key: 'data.duplicatesAndTables', zh: '重复项与表格', en: 'Duplicates and tables' },
  { key: 'data.duplicatesAndTablesHint', zh: '内容完全相同的文件会分组列出，避免训练集泄漏', en: 'Byte-identical files are grouped to prevent train-set leakage' },
  { key: 'data.noDuplicates', zh: '没有发现内容完全重复的文件。', en: 'No byte-identical files found.' },
  { key: 'data.duplicateGroup', zh: '重复组 {0}', en: 'Duplicate group {0}' },
  { key: 'data.tableFiles', zh: '表格文件 {0} 个', en: '{0} table files' },

  // ---- 文献页 ----
  { key: 'lit.unrated', zh: '未评级', en: 'Unrated' },
  { key: 'lit.priorityHigh', zh: '高优先', en: 'High' },
  { key: 'lit.priorityMedium', zh: '中优先', en: 'Medium' },
  { key: 'lit.priorityLow', zh: '低优先', en: 'Low' },
  { key: 'lit.subtitle', zh: '公开文献雷达：先如实记录检索到的内容，再决定复现哪一篇。', en: 'Public literature radar: record what the search actually found, then decide what to reproduce.' },
  { key: 'lit.status', zh: '{0} 条记录 · {1} 个来源 · {2} 条带代码 · {3} 个失败源', en: '{0} records · {1} sources · {2} with code · {3} failed sources' },
  { key: 'lit.section.query', zh: '检索条件', en: 'Query' },
  { key: 'lit.section.records', zh: '记录', en: 'Records' },
  { key: 'lit.records', zh: '文献记录', en: 'Literature records' },
  { key: 'lit.failedSourcesHint', zh: '本轮不可用的数据源', en: 'Data sources unavailable this round' },
  { key: 'lit.queryInfo', zh: '检索信息', en: 'Search details' },
  { key: 'lit.queryInfoHint', zh: '检索式与时间一并留档，便于复核结果来源', en: 'The query and time are kept on record so results can be traced' },
  { key: 'lit.query', zh: '检索式：{0}', en: 'Query: {0}' },
  { key: 'lit.searchedAt', zh: '检索时间：{0}', en: 'Searched at: {0}' },
  { key: 'lit.dataSources', zh: '数据源', en: 'Sources' },
  { key: 'lit.venueUnknown', zh: '未标注来源', en: 'Venue not listed' },
  { key: 'lit.yearUnknown', zh: '年份未知', en: 'Year unknown' },
  { key: 'lit.authorsUnknown', zh: '作者未知', en: 'Authors unknown' },
  { key: 'lit.relevance', zh: '相关度 {0}', en: 'Relevance {0}' },
  { key: 'lit.officialCode', zh: '官方代码', en: 'Official code' },
  { key: 'lit.codeLink', zh: '有代码链接', en: 'Code link' },
  { key: 'lit.recordsNote', zh: '收录不等于复现或背书，复现前需人工确认代码与许可', en: 'Being listed is not reproduction or endorsement; verify code and license by hand before reproducing' },
  { key: 'lit.noRecords', zh: '还没有检索记录。', en: 'No search records yet.' },
  { key: 'lit.providerFailure', zh: '{0}：{1}', en: '{0}: {1}' },
  { key: 'lit.authorSeparator', zh: '、', en: ', ' },

  // ---- 设置页 ----
  { key: 'settings.subtitle', zh: '连接、模型与本机运行环境；地址与令牌在构建期配置里修改。', en: 'Connection, model, and local runtime; the address and token are set in build-time config.' },
  { key: 'settings.status', zh: '后端 {0} · 模型 {1} · GPU {2} · Conda {3}', en: 'Backend {0} · model {1} · GPU {2} · Conda {3}' },
  { key: 'settings.section.workspace', zh: '本地工作区', en: 'Local workspace' },
  { key: 'settings.section.backend', zh: '后端', en: 'Backend' },
  { key: 'settings.section.model', zh: '模型', en: 'Model' },
  { key: 'settings.section.runtime', zh: '运行时', en: 'Runtime' },
  { key: 'settings.notConnected', zh: '未连接', en: 'Not connected' },
  { key: 'settings.gpuMemory', zh: '可用 {0} / 共 {1} · 驱动 {2}', en: 'Free {0} / Total {1} · Driver {2}' },
  { key: 'settings.gpuCount', zh: '可用 {0} 张', en: '{0} available' },
  { key: 'settings.available', zh: '可用', en: 'Available' },
  { key: 'settings.unavailable', zh: '不可用', en: 'Unavailable' },
  { key: 'settings.backendSubtitle', zh: '应用只作为客户端，所有结论都来自后端', en: 'The app is a client only; every result comes from the backend' },
  { key: 'settings.serviceAddress', zh: '服务地址', en: 'Service URL' },
  { key: 'settings.sharedToken', zh: '共享令牌', en: 'Shared token' },
  { key: 'settings.configured', zh: '已配置', en: 'Configured' },
  { key: 'settings.tokenNotConfigured', zh: '未配置（回环地址不校验）', en: 'Not set (loopback needs no auth)' },
  { key: 'settings.health', zh: '健康状态', en: 'Health' },
  { key: 'settings.workspace', zh: '工作区', en: 'Workspace' },
  { key: 'settings.modelSettings', zh: '模型设置', en: 'Model settings' },
  { key: 'settings.modelSubtitle', zh: '推理模型的密钥只从环境变量或安全存储读取', en: 'The inference key is read only from environment variables or secure storage' },
  { key: 'settings.isConfigured', zh: '是否已配置', en: 'Configured' },
  { key: 'settings.notConfigured', zh: '未配置', en: 'Not configured' },
  { key: 'settings.keySource', zh: '密钥来源', en: 'Key source' },
  { key: 'settings.secureStorage', zh: '安全存储', en: 'Secure storage' },
  { key: 'settings.supportedModels', zh: '支持的模型', en: 'Supported models' },

  // ---- 本地工作区（端侧自足）----
  { key: 'settings.localWorkspace', zh: '本地工作区', en: 'Local workspace' },
  { key: 'settings.localWorkspaceSubtitle', zh: '端侧自足：数据放在你「文档」目录里，读规则与算结论都不经过后端', en: 'Self-sufficient on device: your data lives in your Documents folder; reading rules and drawing conclusions never goes through the backend' },
  { key: 'settings.workspacePath', zh: '工作区目录', en: 'Workspace folder' },
  { key: 'settings.workspaceNone', zh: '还没准备（点「准备用户目录」开始）', en: 'Not set up yet (click Set up user folder)' },
  { key: 'settings.workspaceReady', zh: '目录可读写。', en: 'The folder is readable and writable.' },
  { key: 'settings.workspaceNotReadable', zh: '现在读不到这个目录（可能被移动或删掉了），请重新准备。', en: 'This folder cannot be read right now (it may have been moved or deleted); set it up again.' },
  { key: 'settings.workspacePermissionDenied', zh: '没拿到「文档」目录的读写权限。请在系统弹窗里允许，或到「设置 → 应用 → You Just Lead → 权限」里手动打开。', en: 'The Documents folder permission was not granted. Allow it in the system dialog, or enable it under Settings → Apps → You Just Lead → Permissions.' },
  { key: 'settings.workspaceUnsupported', zh: '这台设备不支持「用户文档目录」这个系统能力，端侧工作区在这台机器上用不了。', en: 'This device does not provide the user Documents folder capability, so the on-device workspace cannot be used here.' },
  { key: 'settings.workspaceHint', zh: '工作区会建在「文档/YouJustLead」下（首次点按钮时系统会问一次权限）。它是你自己磁盘上的普通文件夹，随时能在文件管理器里打开核对。', en: 'The workspace is created under Documents/YouJustLead (the system asks for permission the first time). It is an ordinary folder on your disk that you can open and check any time.' },
  { key: 'settings.chooseFolder', zh: '准备用户目录', en: 'Set up user folder' },
  { key: 'settings.initSkeleton', zh: '建骨架', en: 'Create layout' },
  { key: 'settings.recheck', zh: '重新自检', en: 'Re-check' },
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
  { key: 'settings.ruleGate', zh: '规则关口', en: 'Rule gate' },
  { key: 'settings.ruleApproval', zh: '规则批准', en: 'Rule approval' },

  // ---- 端侧规则关口（整页，不经过后端）----
  { key: 'localRule.title', zh: '端侧规则关口', en: 'On-device rule gate' },
  { key: 'localRule.subtitle', zh: '在工作区里录入官方规则证据：读写规格、算缺口、记账本全在端侧完成，不经过后端。', en: 'Record official rule evidence inside the workspace: spec read/write, gap counting and the ledger all happen on device, without the backend.' },
  { key: 'localRule.back', zh: '返回', en: 'Back' },
  { key: 'localRule.importSpec', zh: '导入规格文件', en: 'Import spec file' },
  { key: 'localRule.profile', zh: '规则档案', en: 'Rule profile' },
  { key: 'localRule.specFingerprint', zh: '规格指纹', en: 'Spec digest' },
  { key: 'localRule.sourceTitle', zh: '证据来源', en: 'Evidence source' },
  { key: 'localRule.noWorkspace', zh: '还没有准备用户目录', en: 'The user folder is not set up yet' },
  { key: 'localRule.noWorkspaceHint', zh: '先返回到上一屏，在「本地工作区」卡片上点「准备用户目录」。', en: 'Go back and click "Set up user folder" on the local workspace card first.' },
  { key: 'localRule.noSpec', zh: '工作区里还没有规格文件', en: 'The workspace has no specification yet' },
  { key: 'localRule.noSpecHint', zh: '点右上角「导入规格文件」从文件选择器里挑一份 YAML；也可以用系统文件管理器把文件直接拷进工作区目录。', en: 'Use "Import spec file" at the top right to pick a YAML file, or copy one into the workspace folder with the system file manager.' },
  { key: 'localRule.done', zh: '已录入 {0} 个字段的官方证据，规则缺口已归零。', en: 'Recorded official evidence for {0} fields; the rule gap count is now zero.' },
  { key: 'localRule.notApproval', zh: '录入证据不等于批准规则：批准是另一道关口，需要人写一句复核说明。', en: 'Recording evidence is not the same as approving the rules: approval is a separate gate that needs a human review note.' },
  { key: 'localRule.approvalTitle', zh: '批准规则', en: 'Approve the rules' },
  { key: 'localRule.approvalSubtitle', zh: '录入证据只是记下出处；批准是另一道人工关口，要写一句复核说明。缺口没归零就不许批准。', en: 'Recording evidence only stores where each fact came from; approval is a separate human gate that needs a review note. Approval stays blocked while any gap is open.' },
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
  { key: 'localStatus.title', zh: '离线状态', en: 'Offline status' },
  { key: 'localStatus.subtitle', zh: '后端不在时也能读：工作区里的数据审计、实验历史、账本与论文证据都在端侧直接读出来。', en: 'Readable without the backend: dataset audit, experiment history, ledger and paper evidence are read straight from the workspace on device.' },
  { key: 'localStatus.back', zh: '返回', en: 'Back' },
  { key: 'localStatus.noWorkspace', zh: '还没有准备用户目录', en: 'The user folder is not set up yet' },
  { key: 'localStatus.noWorkspaceHint', zh: '先返回到上一屏，在「本地工作区」卡片上点「准备用户目录」。', en: 'Go back and click "Set up user folder" on the local workspace card first.' },
  { key: 'localStatus.readable', zh: '这几项不经过后端', en: 'These do not go through the backend' },
  { key: 'localStatus.executorTitle', zh: '需要外部执行器', en: 'External executor required' },
  { key: 'localStatus.executorHint', zh: '下面这些要算力或外部服务，端侧不做，也不会假装做了。', en: 'The following need compute or external services; the device does not do them, and will not pretend to.' },
  { key: 'localStatus.capSearch', zh: '文献检索', en: 'Literature search' },
  { key: 'localStatus.capLlm', zh: '大模型问答', en: 'LLM question answering' },
  { key: 'localStatus.capTraining', zh: '真实训练', en: 'Real training' },
  { key: 'localStatus.capAudit', zh: '重型数据审计', en: 'Heavy data audit' },
  { key: 'localStatus.executorBadge', zh: '需外部执行器', en: 'Needs executor' },
  { key: 'localStatus.dataset', zh: '数据审计', en: 'Dataset audit' },
  { key: 'localStatus.datasetHint', zh: '读 reports/data_statistics.json', en: 'Reads reports/data_statistics.json' },
  { key: 'localStatus.datasetMissing', zh: '还没有审计结果', en: 'No audit result yet' },
  { key: 'localStatus.datasetFiles', zh: '文件数', en: 'Files' },
  { key: 'localStatus.datasetIssues', zh: '问题数', en: 'Issues' },
  { key: 'localStatus.datasetBytes', zh: '总大小', en: 'Total size' },
  { key: 'localStatus.datasetImages', zh: '图像', en: 'Images' },
  { key: 'localStatus.datasetMasks', zh: '掩膜', en: 'Masks' },
  { key: 'localStatus.datasetFingerprint', zh: '清单指纹', en: 'Inventory digest' },
  { key: 'localStatus.generatedAt', zh: '生成时间', en: 'Generated at' },
  { key: 'localStatus.experiments', zh: '实验历史', en: 'Experiment history' },
  { key: 'localStatus.experimentsHint', zh: '读 experiments/manifests 与 results', en: 'Reads experiments/manifests and results' },
  { key: 'localStatus.experimentsNone', zh: '工作区里还没有实验记录。', en: 'No experiment is recorded in this workspace yet.' },
  { key: 'localStatus.experimentMetric', zh: '验证指标', en: 'Validation metric' },
  { key: 'localStatus.experimentData', zh: '数据版本', en: 'Data version' },
  { key: 'localStatus.experimentChange', zh: '变更类型', en: 'Change type' },
  { key: 'localStatus.experimentNoResult', zh: '没有结果文件（这条实验没跑完）', en: 'No result file: this experiment never finished' },
  { key: 'localStatus.ledger', zh: '账本', en: 'Ledger' },
  { key: 'localStatus.ledgerHint', zh: '读 ledger.jsonl，最新在前', en: 'Reads ledger.jsonl, newest first' },
  { key: 'localStatus.ledgerLatest', zh: '显示最近 {0} / 共 {1} 条', en: 'Showing the latest {0} of {1}' },
  { key: 'localStatus.ledgerNone', zh: '账本里还没有事件。', en: 'The ledger has no events yet.' },
  { key: 'localStatus.evidence', zh: '论文证据', en: 'Paper evidence' },
  { key: 'localStatus.evidenceHint', zh: '读 paper/generated/evidence_map.json', en: 'Reads paper/generated/evidence_map.json' },
  { key: 'localStatus.evidenceNone', zh: '还没有生成论文证据图。', en: 'The paper evidence map has not been generated yet.' },
  { key: 'localStatus.evidenceClaims', zh: '证据声明', en: 'Claims' },
  { key: 'localStatus.evidenceRecords', zh: '文献记录', en: 'Research records' },
  { key: 'localStatus.trace', zh: '证据链', en: 'Evidence chains' },
  { key: 'localStatus.traceHint', zh: '与后端「溯源」页同样的顺序，只读工作区里已落盘的东西', en: 'The same order as the backend trace page; reads only what is already in the workspace' },
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
  { key: 'localStatus.researchHint', zh: '读 research/papers.json', en: 'Reads research/papers.json' },
  { key: 'localStatus.researchNone', zh: '还没有做过检索。', en: 'No search has been run yet.' },
  { key: 'localStatus.researchQuery', zh: '检索式', en: 'Query' },
  { key: 'localStatus.researchSearchedAt', zh: '检索时间', en: 'Searched at' },
  { key: 'localStatus.researchFailures', zh: '来源失败', en: 'Provider failures' },
  { key: 'settings.offlineStatus', zh: '离线状态', en: 'Offline status' },
  { key: 'settings.runtime', zh: '本机运行时', en: 'Local runtime' },
  { key: 'settings.runtimeSubtitle', zh: '训练前的环境探测结果，决定能不能跑 GPU 任务', en: 'Environment probe before training; decides whether GPU jobs can run' },
  { key: 'settings.platform', zh: '平台', en: 'Platform' },
  { key: 'settings.noGpu', zh: '没有探测到可用 GPU。', en: 'No available GPU detected.' },

  // ---- 写作页 ----
  { key: 'writing.subtitle', zh: '论文只写有证据支撑的部分：证据链、章节结构与投稿契约一一对应。', en: 'The paper only states what the evidence supports: evidence chain, section structure, and submission contract map one to one.' },
  { key: 'writing.status', zh: '{0} 条声明 · {1} 个章节 · {2} 篇参考 · {3} 条文献记录', en: '{0} claims · {1} sections · {2} references · {3} research records' },
  { key: 'writing.section.package', zh: '证据包', en: 'Package' },
  { key: 'writing.section.structure', zh: '结构与声明', en: 'Structure and claims' },
  { key: 'writing.section.contract', zh: '提交契约', en: 'Submission contract' },
  { key: 'writing.paperPackage', zh: '论文包', en: 'Paper package' },
  { key: 'writing.packageSubtitle', zh: '由命令行生成，界面只读取不修改', en: 'Generated from the command line; the UI is read-only' },
  { key: 'writing.noPackage', zh: '还没有生成论文包。在后端运行 python main.py paper 之后，这里会显示章节与证据链。', en: 'No paper package yet. After running python main.py paper on the backend, sections and the evidence chain will appear here.' },
  { key: 'writing.generatedAt', zh: '生成时间', en: 'Generated at' },
  { key: 'writing.packageDir', zh: '包目录', en: 'Package directory' },
  { key: 'writing.texFile', zh: 'TeX 文件', en: 'TeX file' },
  { key: 'writing.bibFile', zh: 'BibTeX 文件', en: 'BibTeX file' },
  { key: 'writing.evidenceFile', zh: '证据文件', en: 'Evidence file' },
  { key: 'writing.sectionStructure', zh: '章节结构', en: 'Section structure' },
  { key: 'writing.sectionStructureSubtitle', zh: '当前 TeX 里的章节顺序', en: 'Order of sections in the current TeX' },
  { key: 'writing.noSections', zh: '没有读到章节。', en: 'No sections found.' },
  { key: 'writing.evidenceChain', zh: '证据链', en: 'Evidence chain' },
  { key: 'writing.evidenceChainSubtitle', zh: '每条结论都指向具体实验与结果文件', en: 'Every claim points to a specific experiment and result file' },
  { key: 'writing.noClaims', zh: '还没有实验结论写入证据包。完成实验后再生成一次论文包。', en: 'No experiment conclusions have been written into the evidence package yet. Regenerate the paper package once the experiments are done.' },
  { key: 'writing.submissionContract', zh: '投稿契约', en: 'Submission contract' },
  { key: 'writing.contractSubtitle', zh: '来自已确认的竞赛规范，提交前逐项核对', en: 'From the confirmed competition rules; verify each item before submitting' },
  { key: 'writing.submissionFormat', zh: '提交格式', en: 'Submission format' },
  { key: 'writing.filenameRule', zh: '文件名规则', en: 'File name rule' },
  { key: 'writing.maskSize', zh: '掩码尺寸', en: 'Mask size' },
  { key: 'writing.dailyLimit', zh: '每日提交上限', en: 'Daily submission limit' },
  { key: 'writing.dailyLimitValue', zh: '{0} 次', en: '{0} submissions' },
  { key: 'writing.validationProfile', zh: '校验配置', en: 'Validation profile' },
  { key: 'writing.requiredFiles', zh: '必需文件', en: 'Required files' },
  { key: 'writing.noRequiredFiles', zh: '没有记录必需文件。', en: 'No required files recorded.' },

  // ---- 实验页 ----
  { key: 'exp.subtitle', zh: '每一次训练都留痕：配置、假设、指标与结论都可以追溯到账本记录。', en: 'Every run leaves a trace: configs, hypotheses, metrics and conclusions all trace back to the ledger.' },
  { key: 'exp.status', zh: '{0} 个实验 · {1} 个已完成 · 最佳 {2} · 训练任务 {3}', en: '{0} experiments · {1} completed · best {2} · {3} jobs' },
  { key: 'exp.section.ledger', zh: '实验台账', en: 'Ledger' },
  { key: 'exp.section.jobs', zh: '训练任务', en: 'Jobs' },
  { key: 'exp.section.drafts', zh: '草稿', en: 'Drafts' },
  { key: 'exp.section.register', zh: '登记', en: 'Register' },
  { key: 'exp.trainingJobs', zh: '训练任务', en: 'Training jobs' },
  { key: 'exp.ledgerTitle', zh: '实验账本', en: 'Experiment ledger' },
  { key: 'exp.ledgerSubtitle', zh: '只有落盘并有验证指标的实验才计入完成', en: 'Only experiments written to disk with a validation metric count as complete' },
  { key: 'exp.ledgerEmpty', zh: '账本里还没有实验记录。先在工作流里确认规则，再跑一次可复现的基线。', en: 'No experiments in the ledger yet. Confirm the rules in the workflow, then run a reproducible baseline.' },
  { key: 'exp.jobsSubtitle', zh: '由调度器排队执行，同一时刻只允许一个任务在跑', en: 'Queued by the scheduler; only one job runs at a time' },
  { key: 'exp.jobsEmpty', zh: '调度队列是空的。', en: 'The scheduler queue is empty.' },
  { key: 'exp.draftsTitle', zh: '等待人工批准的草案', en: 'Drafts awaiting human approval' },
  { key: 'exp.draftsSubtitle', zh: '草案不会自己变成训练任务：先在 configs 写好配置，再人工批准（approve-run）后执行（run）', en: 'A draft never becomes a training job on its own: write the config under configs, approve-run it, then run it' },
  { key: 'exp.draftsEmpty', zh: '还没有待批准的草案。', en: 'No drafts awaiting approval yet.' },
  { key: 'exp.registerTitle', zh: '登记实验草案', en: 'Register an experiment draft' },
  { key: 'exp.registerSubtitle', zh: '把想验证的假设交给后端记下来，执行与否由你决定', en: 'Hand the hypothesis you want to test to the backend; you decide whether it ever runs' },
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
  { key: 'trace.subtitle', zh: '每条结论都要能回到原始证据：规则锚点、数据指纹、实验产物、文献来源', en: 'Every conclusion must trace back to its source: rule anchors, data fingerprint, artifacts, references' },
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
  { key: 'trace.ruleSubtitle', zh: '字段值 → 官方锚点 → 来源定位 → 人工复核', en: 'Field value → official anchor → source locator → human review' },
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
  { key: 'trace.dataSubtitle', zh: '审计指纹 → 每个实验的数据版本 → 是否计入当前赛题', en: 'Audit fingerprint → each experiment data version → whether it counts for this competition' },
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
  { key: 'trace.expSubtitle', zh: '假设与配置指纹 → 结果与产物 → 人工批准', en: 'Hypothesis and config digest → results and artifacts → human approval' },
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
  { key: 'trace.approvalBy', zh: '批准人 {0}', en: 'Approved by {0}' },
  { key: 'trace.resultFile', zh: '结果文件', en: 'Result file' },
  { key: 'trace.expEmpty', zh: '还没有实验记录。先在工作流里确认规则，再跑一次可复现的基线。', en: 'No experiments yet. Confirm the rules in the workflow, then run a reproducible baseline.' },

  { key: 'trace.researchTitle', zh: '文献链', en: 'Research chain' },
  { key: 'trace.researchSubtitle', zh: '检索条件 → 记录与引用文件，检索失败也如实上报', en: 'Search criteria → records and reference files; provider failures are reported too' },
  { key: 'trace.query', zh: '检索条件', en: 'Query' },
  { key: 'trace.searchedAt', zh: '检索时间', en: 'Searched at' },
  { key: 'trace.providerFailure', zh: '检索源失败', en: 'Provider failures' },
  { key: 'trace.relevance', zh: '相关度 {0}', en: 'Relevance {0}' },
  { key: 'trace.refFiles', zh: '引用文件', en: 'Reference files' },
  { key: 'trace.recordsShown', zh: '显示前 {0} 条，共 {1} 条；完整列表在文献页。', en: 'Showing the first {0} of {1}; the full list is on the Literature page.' },
  { key: 'trace.researchEmpty', zh: '还没有文献检索记录。', en: 'No research records yet.' },

  { key: 'trace.paperTitle', zh: '论文终点', en: 'Paper destination' },
  { key: 'trace.paperSubtitle', zh: '证据包与它引用的结果文件', en: 'The evidence package and the result files it cites' },
  { key: 'trace.packageDir', zh: '证据包目录', en: 'Package directory' },
  { key: 'trace.generatedAt', zh: '生成时间', en: 'Generated at' },
  { key: 'trace.sectionsLabel', zh: '章节数', en: 'Sections' },
  { key: 'trace.bibLabel', zh: '参考文献', en: 'Bibliography entries' },
  { key: 'trace.claimsTitle', zh: '证据声明', en: 'Evidence claims' },
  { key: 'trace.claimsEmpty', zh: '证据包里还没有声明：论文只写有证据支撑的内容。', en: 'No claims in the package yet: the paper only states what evidence supports.' },
  { key: 'trace.claimResolved', zh: '引用的结果文件存在', en: 'Cited result exists' },
  { key: 'trace.claimUnresolved', zh: '引用的结果文件缺失', en: 'Cited result missing' },
  { key: 'trace.paperMissing', zh: '还没有论文证据包。', en: 'No paper evidence package yet.' },

  // ---- 横幅 / 能力网格 / 项目卡 ----
  { key: 'hero.welcome', zh: '欢迎回来，{0}', en: 'Welcome back, {0}' },
  { key: 'hero.welcomeFallback', zh: '继续推进你的科研工作流', en: "let's keep your research moving" },
  { key: 'hero.subtitle', zh: 'AI 负责执行，关键决策由你主导。', en: 'AI does the legwork; you make the calls.' },
  { key: 'hero.flow', zh: '更高效的研究流程', en: 'A faster research workflow' },
  { key: 'hero.insight', zh: '更深入的洞察发现', en: 'Deeper insight' },
  { key: 'hero.impact', zh: '更有影响力的成果', en: 'More impactful results' },

  { key: 'cap.title', zh: '内置能力', en: 'Capabilities' },
  { key: 'cap.subtitle', zh: '已接通的训练适配器与它们的数据契约', en: 'Connected training adapters and their data contracts' },
  { key: 'cap.searchPlaceholder', zh: '搜索适配器', en: 'Search adapters' },
  { key: 'cap.empty', zh: '后端未连接，暂时读不到内置能力清单。', en: "Backend offline; the capability list can't be loaded right now." },

  { key: 'card.noCompetition', zh: '尚未配置竞赛', en: 'No competition configured' },
  { key: 'card.mainMetric', zh: '主指标 {0}', en: 'Primary metric {0}' },
  { key: 'card.adapter', zh: '适配器 {0}', en: 'Adapter {0}' },
  { key: 'card.inProgress', zh: '进行中', en: 'In progress' },
  { key: 'card.lastUpdated', zh: '最后更新 {0}', en: 'Last updated {0}' },
  { key: 'card.ruleFields', zh: '规则字段 {0}/{1}', en: 'Rule fields {0}/{1}' },
  { key: 'card.blockers', zh: '阻塞项 {0} 条', en: '{0} blockers' },
  { key: 'card.metric', zh: '指标 {0}', en: 'Metric {0}' },
  { key: 'card.workflow', zh: '研究工作流', en: 'Research workflow' },
  { key: 'card.viewDetails', zh: '查看详情 →', en: 'View details →' }
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
