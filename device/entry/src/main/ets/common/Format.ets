import { BusinessError } from '@kit.BasicServicesKit';
import { tFor, tfFor } from './I18n';

/**
 * 展示层格式化函数：把后端的枚举值和时间戳转成界面文案。
 *
 * 纯函数，不依赖任何状态，便于单独理解和调整。
 *
 * 每个会产出文案的函数都把语言作为**第一个参数**：ArkUI 只重绘读到了状态变量的
 * 那些节点，调用处写 `stageLabel(this.lang, stage)` 就等于把该节点登记到语言变化上，
 * 切换语言时它才会跟着重建。
 */

/** 把后端阶段标识翻成可读名称。 */
export function stageLabel(lang: string, stage: string): string {
  if (stage === 'rules_capture') {
    return tFor(lang, 'stage.rulesCapture');
  }
  if (stage === 'rules_review') {
    return tFor(lang, 'stage.rulesReview');
  }
  if (stage === 'data_audit') {
    return tFor(lang, 'stage.dataAudit');
  }
  if (stage === 'baseline_design') {
    return tFor(lang, 'stage.baselineDesign');
  }
  if (stage === 'evidence_led_iteration') {
    return tFor(lang, 'stage.evidenceLedIteration');
  }
  return stage;
}

/** 把事件类型翻成可读短句。 */
export function eventTitle(lang: string, eventType: string): string {
  if (eventType === 'rules_analyzed') {
    return tFor(lang, 'evt.rulesAnalyzed');
  }
  if (eventType === 'rules_imported') {
    return tFor(lang, 'evt.rulesImported');
  }
  if (eventType === 'rules_approved') {
    return tFor(lang, 'evt.rulesApproved');
  }
  if (eventType === 'official_rule_evidence_recorded') {
    return tFor(lang, 'evt.ruleEvidenceRecorded');
  }
  // 下面三个是端侧自己记的事件（JSONL 账本）与新建项目事件，命名与后端同一套：
  // 不映射的话界面上会直接显示成 `local_workspace_initialized` 这种原始事件名。
  if (eventType === 'rules_evidence_applied') {
    return tFor(lang, 'evt.ruleEvidenceApplied');
  }
  if (eventType === 'local_workspace_initialized') {
    return tFor(lang, 'evt.workspaceInitialized');
  }
  if (eventType === 'project_created') {
    return tFor(lang, 'evt.projectCreated');
  }
  if (eventType === 'data_audited') {
    return tFor(lang, 'evt.dataAudited');
  }
  if (eventType === 'research_searched') {
    return tFor(lang, 'evt.researchSearched');
  }
  if (eventType === 'repository_intake') {
    return tFor(lang, 'evt.repositoryIntake');
  }
  if (eventType === 'decision_plan_generated') {
    return tFor(lang, 'evt.decisionPlanGenerated');
  }
  if (eventType === 'paper_package_generated') {
    return tFor(lang, 'evt.paperPackageGenerated');
  }
  if (eventType === 'training_scaffold_created') {
    return tFor(lang, 'evt.trainingScaffoldCreated');
  }
  if (eventType === 'runtime_probed') {
    return tFor(lang, 'evt.runtimeProbed');
  }
  if (eventType === 'training_config_approved') {
    return tFor(lang, 'evt.trainingConfigApproved');
  }
  if (eventType === 'experiment_draft_created') {
    return tFor(lang, 'evt.experimentDraftCreated');
  }
  if (eventType === 'experiment_approval_recorded') {
    return tFor(lang, 'evt.experimentApprovalRecorded');
  }
  if (eventType === 'submission_validated') {
    return tFor(lang, 'evt.submissionValidated');
  }
  if (eventType.startsWith('training_job')) {
    return tFor(lang, 'evt.trainingJob');
  }
  if (eventType.startsWith('data_audit_job')) {
    return tFor(lang, 'evt.dataAuditJob');
  }
  if (eventType.startsWith('material_intake')) {
    return tFor(lang, 'evt.materialIntake');
  }
  if (eventType.startsWith('deepseek')) {
    return tFor(lang, 'evt.deepseek');
  }
  return eventType;
}

/** 把 ISO 时间转成相对时间描述。 */
export function relativeTime(lang: string, iso: string): string {
  const then: number = new Date(iso).getTime();
  if (isNaN(then)) {
    return iso;
  }
  const diffMinutes: number = Math.floor((Date.now() - then) / 60000);
  if (diffMinutes < 1) {
    return tFor(lang, 'time.justNow');
  }
  if (diffMinutes < 60) {
    return tfFor(lang, 'time.minutesAgo', [`${diffMinutes}`]);
  }
  const hours: number = Math.floor(diffMinutes / 60);
  if (hours < 24) {
    return tfFor(lang, 'time.hoursAgo', [`${hours}`]);
  }
  return tfFor(lang, 'time.daysAgo', [`${Math.floor(hours / 24)}`]);
}

/** 把建议动作的优先级翻成短标签。 */
export function priorityLabel(lang: string, priority: string): string {
  if (priority === 'blocker') {
    return tFor(lang, 'prio.blocker');
  }
  if (priority === 'high') {
    return tFor(lang, 'prio.high');
  }
  if (priority === 'medium') {
    return tFor(lang, 'prio.medium');
  }
  return tFor(lang, 'prio.low');
}

/** 优先级对应的徽章色调。 */
export function priorityTone(priority: string): string {
  if (priority === 'blocker') {
    return 'danger';
  }
  if (priority === 'high') {
    return 'warn';
  }
  return 'muted';
}

/** 工作流环节状态翻成短标签。 */
export function componentLabel(lang: string, state: string): string {
  if (state === 'approved' || state === 'complete' || state === 'recorded') {
    return tFor(lang, 'state.done');
  }
  if (state === 'awaiting_human_confirmation') {
    return tFor(lang, 'state.awaitingHuman');
  }
  if (state === 'missing') {
    return tFor(lang, 'state.missing');
  }
  if (state === 'none' || state === 'not_started') {
    return tFor(lang, 'state.notStarted');
  }
  return state;
}

/** 工作流环节状态对应的徽章色调。 */
export function componentTone(state: string): string {
  if (state === 'approved' || state === 'complete' || state === 'recorded') {
    return 'ok';
  }
  if (state === 'awaiting_human_confirmation' || state === 'missing') {
    return 'warn';
  }
  return 'muted';
}

/**
 * 规则缺口该「做什么」的说法，按后端 reason 原文的开头匹配。
 *
 * 后端 `agents/rules_agent.py` 目前只会产出五种 reason，这里的匹配是前端的一层
 * 翻译，不是权威判断：匹配不上就返回空串，界面只显示英文原文，不猜。
 */
export function ruleGapActionLabel(lang: string, reason: string): string {
  if (reason.startsWith('The confirmed value is missing')) {
    return tFor(lang, 'gap.valueMissing');
  }
  if (reason.startsWith('Use exactly loose_png')) {
    return tFor(lang, 'gap.outputModeChoice');
  }
  if (reason.startsWith('Record the official rule-page')) {
    return tFor(lang, 'gap.reviewAnchorMissing');
  }
  if (reason.startsWith('Add an exact quote')) {
    return tFor(lang, 'gap.quoteMissing');
  }
  if (reason.startsWith('Resolve all') || reason.startsWith('This must be a list')) {
    return tFor(lang, 'gap.questionPending');
  }
  return '';
}

/** 实验状态翻成短标签。 */
export function experimentStatusLabel(lang: string, status: string): string {
  if (status === 'completed') {
    return tFor(lang, 'status.completed');
  }
  if (status === 'failed') {
    return tFor(lang, 'status.failed');
  }
  if (status === 'running') {
    return tFor(lang, 'status.running');
  }
  if (status === 'queued') {
    return tFor(lang, 'status.queued');
  }
  if (status === 'planned') {
    return tFor(lang, 'status.planned');
  }
  if (status === 'awaiting_human_approval') {
    return tFor(lang, 'status.awaitingHumanApproval');
  }
  return status;
}

/** 实验状态对应的徽章色调。 */
export function experimentStatusTone(status: string): string {
  if (status === 'completed') {
    return 'ok';
  }
  if (status === 'failed') {
    return 'danger';
  }
  if (status === 'running' || status === 'awaiting_human_approval') {
    return 'warn';
  }
  return 'muted';
}

/** 字节数转成易读单位。 */
export function formatBytes(bytes: number): string {
  if (bytes <= 0) {
    return '0 B';
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  const kb: number = bytes / 1024;
  if (kb < 1024) {
    return `${kb.toFixed(1)} KB`;
  }
  const mb: number = kb / 1024;
  if (mb < 1024) {
    return `${mb.toFixed(1)} MB`;
  }
  return `${(mb / 1024).toFixed(2)} GB`;
}

/** 秒数转成「1 分 20 秒」这类描述。 */
export function formatDuration(lang: string, seconds: number): string {
  if (seconds <= 0) {
    return '—';
  }
  if (seconds < 60) {
    return tfFor(lang, 'time.seconds', [`${seconds.toFixed(0)}`]);
  }
  const minutes: number = Math.floor(seconds / 60);
  if (minutes < 60) {
    return tfFor(lang, 'time.minutesSeconds', [`${minutes}`, `${Math.floor(seconds % 60)}`]);
  }
  return tfFor(lang, 'time.hoursMinutes', [`${Math.floor(minutes / 60)}`, `${minutes % 60}`]);
}

/** 数值缺省时统一显示成占位符。 */
export function formatNumber(value: number | null, digits: number): string {
  if (value === null || value === undefined || isNaN(value)) {
    return '—';
  }
  return value.toFixed(digits);
}

/**
 * 指纹只显示前若干位：完整 64 位十六进制在界面上读不出来，截断后只用于"人对一眼"。
 */
export function shortHash(value: string): string {
  if (value.length === 0) {
    return '';
  }
  return value.length > 12 ? value.substring(0, 12) : value;
}

/**
 * 把异常变成一句能定位问题的提示。
 *
 * 系统 API 的 message 常常只有一句 "Permission denied"，光看这句分不清是授权没拿到
 * 还是这个目录根本不可写；带上 code（如 201 / 13900001）才能查。
 */
export function describeError(error: Object): string {
  const failure: BusinessError = error as BusinessError;
  const message: string = failure.message !== undefined ? failure.message : `${error}`;
  if (failure.code === undefined || failure.code === 0) {
    return message;
  }
  return `${message}（code ${failure.code}）`;
}

/**
 * 今天的本地日期（YYYY-MM-DD）。
 *
 * 给「复核时间」这类输入一个可编辑的起点：默认值只是省一次手输，
 * 复核这件事还是得人对着官方原文做。
 */
export function todayLocal(): string {
  const now: Date = new Date();
  const pad = (value: number): string => value < 10 ? `0${value}` : `${value}`;
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** 把 ISO 时间截成「年-月-日 时:分」。 */
export function formatTimestamp(iso: string | null): string {
  if (iso === null || iso.length === 0) {
    return '—';
  }
  const parsed: Date = new Date(iso);
  if (isNaN(parsed.getTime())) {
    return iso;
  }
  const pad = (value: number): string => value < 10 ? `0${value}` : `${value}`;
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} `
    + `${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
}

/**
 * 去掉 Agent 回答里的 Markdown 标记。
 *
 * 只清理标题号与加粗符号，正文一个字都不动。
 */
export function plainText(markdown: string): string {
  const lines: string[] = markdown.split('\n');
  const cleaned: string[] = [];
  for (const line of lines) {
    let text: string = line.trim();
    while (text.startsWith('#')) {
      text = text.substring(1).trim();
    }
    cleaned.push(text.split('**').join(''));
  }
  return cleaned.join('\n').trim();
}
