import { http } from '@kit.NetworkKit';
import { ACCESS_TOKEN, AGENT_TIMEOUT_MS, BASE_URL, CONNECT_TIMEOUT_MS, READ_TIMEOUT_MS } from './BackendConfig';

/** 当前登录会话；密码不会保留在客户端。 */
let SESSION_TOKEN: string = '';

export function setSessionToken(token: string): void {
  SESSION_TOKEN = token;
}

export function clearSessionToken(): void {
  SESSION_TOKEN = '';
}

export function currentSessionToken(): string {
  return SESSION_TOKEN;
}

/** 用户账号与 token 积分余额。 */
export interface AccountInfo {
  user_id: string;
  username: string;
  balance_tokens: number;
  credits: number;
  welcome_credits: number;
  tokens_per_credit: number;
  credit_ledger?: CreditLedgerEntry[];
}

/** 一条追加式积分账本记录。 */
export interface CreditLedgerEntry {
  event_type: string;
  delta_tokens: number;
  balance_after: number;
  reference_id: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  created_at: string;
}

interface AuthResponse {
  token: string;
  account: AccountInfo;
}

interface LogoutResponse {
  logged_out: boolean;
}

/** 后端建议的下一步动作。 */
export interface NextAction {
  priority: string;
  action: string;
  evidence: string;
}

/** 规则确认的一处缺口。 */
export interface RuleGap {
  field: string;
  reason: string;
}

/** 规则确认就绪度。 */
export interface RuleReadiness {
  ready: boolean;
  profile: string;
  required_fields: string[];
  gaps: RuleGap[];
}

/** 当前竞赛的规范摘要。新建项目还没填规则时，后四项都是 null。 */
export interface CompetitionInfo {
  name: string | null;
  task_type: string | null;
  preferred_runner: string | null;
  metric: string | null;
  direction: string;
  requires_human_confirmation: boolean;
  rule_readiness: RuleReadiness;
}

/** 一个项目（一份可独立推进的竞赛工作区）。 */
export interface ProjectSummary {
  id: string;
  name: string;
  created_at: string;
  /** 是否是后端当前选中的项目。 */
  current: boolean;
}

/** GET /api/projects 的返回，新建与切换项目返回同一结构外加 project。 */
export interface ProjectListResponse {
  projects: ProjectSummary[];
  current: string | null;
  project: ProjectSummary | null;
}

/** 汇总指标。 */
export interface DashboardSummary {
  completed_experiments: number;
  total_experiments: number;
  data_files: number;
  data_issues: number;
  research_records: number;
  infrastructure_experiments: number;
}

/** 一个内置训练适配器。 */
export interface RunnerCapability {
  runner: string;
  kind: string;
  task_types: string[];
  template: string;
  data_contract: string;
}

/** 内置能力清单。 */
export interface Capabilities {
  runners: RunnerCapability[];
}

/** 工作流各环节的状态，取值如 approved / complete / missing / not_started。 */
export interface WorkflowComponents {
  rules: string;
  data_audit: string;
  research: string;
  baseline: string;
  approvals: string;
}

/** 工作流阶段与门禁状态。 */
export interface WorkflowSnapshot {
  stage: string;
  automatic_execution: boolean;
  blockers: string[];
  completed_experiments: number;
  components: WorkflowComponents;
}

/** 一条已记录的工作流事件。 */
export interface RecentEvent {
  event_id: number;
  event_type: string;
  created_at: string;
}

/** 仪表盘聚合快照，对应后端 GET /api/dashboard。 */
export interface DashboardSnapshot {
  competition: CompetitionInfo;
  summary: DashboardSummary;
  next_actions: NextAction[];
  capabilities: Capabilities;
  workflow: WorkflowSnapshot;
  recent_events: RecentEvent[];
}

/** GET /api/workflow：完整工作流状态，含推荐适配器与全部可用适配器。 */
export interface WorkflowDetail {
  stage: string;
  automatic_execution: boolean;
  components: WorkflowComponents;
  blockers: string[];
  completed_experiments: number;
  recommended_runner: RunnerCapability;
  available_runners: RunnerCapability[];
}

/** GET /api/next-actions。 */
export interface NextActionsResponse {
  actions: NextAction[];
}

/** GET /api/rules/report 里界面用到的部分。 */
export interface RulesReport {
  readiness: RuleReadiness;
}

/** 一次已记录的训练实验。 */
export interface ExperimentRecord {
  id: string;
  status: string;
  metric: number | null;
  best_epoch: number | null;
  hypothesis: string | null;
  change_type: string | null;
  runtime_seconds: number | null;
  decision: string | null;
  /** 是否已有人工批准记录（experiments/approvals/<id>.json）。 */
  approved: boolean;
  approved_at: string | null;
}

/** POST /api/rules/approve 的结果：规则确认这件事本身的记录。 */
export interface RuleApprovalOutcome {
  approved: boolean;
  approved_at: string;
  note: string;
  spec_path: string;
}

/** POST /api/decisions/approve 的结果：一条人工批准记录，不含执行。 */
export interface DecisionApproval {
  experiment_id: string;
  approved_at: string;
  approved_by: string;
  scope: string;
}

/** GET /api/experiments。 */
export interface ExperimentsResponse {
  experiments: ExperimentRecord[];
}

/** 一次训练任务的记录。 */
export interface TrainingJob {
  job_id: string;
  status: string;
  config_path: string;
  hypothesis: string | null;
  parent_id: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  experiment_id: string | null;
  validation_metric: number | null;
  error: string | null;
}

/** GET /api/experiments/jobs。 */
export interface TrainingJobsResponse {
  jobs: TrainingJob[];
}

/** 一条等待人工批准的实验草案。 */
export interface ExperimentDraft {
  draft_id: string;
  created_at: string;
  status: string;
  hypothesis: string;
  safety_note: string;
}

/** POST /api/experiments/drafts 的请求体。 */
interface DraftRequest {
  hypothesis: string;
}

/** GET /api/experiments/drafts。 */
export interface DraftListResponse {
  drafts: ExperimentDraft[];
}

/** 一组数值的分布（后端给的是 min/max/mean 三元组，不是单个数字）。 */
export interface MetricRange {
  min: number;
  max: number;
  mean: number;
}

/** 图像维度统计。 */
export interface ImageStats {
  count: number;
  width: MetricRange | null;
  height: MetricRange | null;
  /** 通道数 → 图片张数。后端按 `dict[int, int]` 落盘，JSON 里键是字符串。 */
  channels: Record<string, number>;
}

/** 分割掩码统计。 */
export interface MaskStats {
  count: number;
  empty_count: number;
  foreground_ratio: MetricRange | null;
}

/** GET /api/data-audit：一次数据审计的完整结果。 */
export interface DataAuditReport {
  audit_schema_version: number;
  data_dir: string;
  generated_at: string;
  file_count: number;
  issue_count: number;
  total_bytes: number;
  metadata_format: string;
  inventory_sha256: string;
  file_kinds: Record<string, number>;
  images: ImageStats;
  segmentation_masks: MaskStats;
  splits: Record<string, number>;
  exact_duplicate_groups: string[][];
  tables: string[];
}

/**
 * 相关性打分的四个分量，取值 0~1，算不出来的那一项为 null。
 *
 * 后端把分值拆开给出来，是为了让界面能解释「这个 0.68 是怎么来的」——
 * 而不是只给一个说不清的数字。
 */
export interface RelevanceParts {
  /** 查询词命中：标题权重最高，摘要次之。 */
  terms: number | null;
  /** 与竞赛规格里任务、模态、指标的吻合度。 */
  task: number | null;
  /** 记录里是否带代码仓库。 */
  code: number | null;
  /** 年份新旧。 */
  recency: number | null;
}

/** 评判里的一条证据。`key` 是枚举，界面负责翻成文案。 */
export interface CandidateSignal {
  key: string;
  /** ok / warn / danger / muted。 */
  tone: string;
  /** 证据本身（数值、许可名、仓库地址），不翻译。 */
  detail: string;
}

/** 用论文标题在 GitHub 上找到的候选实现仓库。 */
export interface CodeCandidate {
  repository: string;
  url: string | null;
  license: string | null;
  stars: number | null;
  /** 标题词在该仓库名/描述里的命中率，低于阈值就不会出现在这里。 */
  title_overlap: number;
}

/**
 * 一条候选的价值评判。
 *
 * `verdict` 是结论枚举：reproduce（值得复现）/ adapt_component（只借鉴组件）/
 * reference_only（只当参考，实现自己写）/ skip（不投入）。
 * `has_official_code` 恒为 false —— 检索源不提供作者归属，无法证明「官方实现」。
 */
export interface CandidateAssessment {
  paper_id: string;
  verdict: string;
  worth_reproducing: boolean;
  has_public_code: boolean;
  has_official_code: boolean;
  /** found / none_found / lookup_failed / skipped。查不动 ≠ 没有代码。 */
  code_lookup: string;
  code_candidates: CodeCandidate[];
  task_fit: number | null;
  relevance_score: number | null;
  assessed_at: string;
  signals: CandidateSignal[];
}

/** 一条公开文献记录。 */
export interface ResearchRecord {
  paper_id: string;
  title: string;
  authors: string[];
  year: number | null;
  venue: string | null;
  url: string | null;
  source: string;
  license: string | null;
  code_url: string | null;
  official_code: boolean | null;
  relevance_score: number | null;
  /** 复现优先度，取值 0~1（旧数据里可能是 high/medium/low 这类文本）。 */
  reproduction_priority: string | number | null;
  abstract: string | null;
  /** 检索时就写好的打分分量；老工作区的记录里没有这个字段。 */
  relevance_parts?: RelevanceParts;
  /** undecided / investigate / discard。 */
  decision: string;
  decision_note: string;
  decided_at: string | null;
  /** 没评判过时为 null。 */
  assessment: CandidateAssessment | null;
}

/** 取舍的计数，给「已调研 N / 已舍弃 M」用。 */
export interface CandidateCounts {
  records: number;
  undecided: number;
  investigate: number;
  discard: number;
  assessed: number;
}

/** GET /api/research：文献雷达的检索结果 + 取舍 + 评判。 */
export interface ResearchReport {
  query: string | null;
  searched_at: string | null;
  sources: string[];
  records: ResearchRecord[];
  provider_failures: Record<string, string>;
  report_markdown: string;
  counts: CandidateCounts;
}

/** docker 客户端与守护进程是否可用。装不上时 reason 里是具体原因。 */
export interface DockerStatus {
  available: boolean;
  version: string | null;
  reason: string;
}

/**
 * 一条候选复现命令。
 *
 * `source` 是出处（`README.md:99` 或入口文件名）：显示它是为了让人能自己去核对，
 * 而不是把系统猜的命令当仓库的用法。
 */
export interface ReproductionCommand {
  id: string;
  command: string;
  source: string;
  /** documented（文档里抄的）/ fallback（退化的探测命令）。 */
  origin: string;
  /** documented / probe / unverified。 */
  confidence: string;
}

export interface ReproductionEntrypoint {
  path: string;
  /** train / evaluate / infer / export。 */
  kind: string;
}

/** 已审计的本地数据集；没有审计过时整个字段为 null。 */
export interface ReproductionDataset {
  host_path: string;
  target: string;
  inventory_sha256: string | null;
  file_count: number | null;
}

export interface ReproductionResources {
  cpus: string;
  memory: string;
  timeout_seconds: number;
}

/** 一份复现计划：仓库、镜像、依赖、入口、候选命令、数据挂载。 */
export interface ReproductionPlan {
  plan_id: string;
  created_at: string;
  paper_id: string;
  title: string | null;
  repository: string;
  commit: string | null;
  local_path: string;
  slug: string;
  image: string;
  /** 仓库文本里出现 cuda/torch.cuda 之类关键词时的提示，用来决定要不要加 --gpus。 */
  requires_gpu: boolean;
  dependency_manifest: string | null;
  readme: string | null;
  entrypoints: ReproductionEntrypoint[];
  commands: ReproductionCommand[];
  dataset: ReproductionDataset | null;
  resources: ReproductionResources;
  execution_policy: string;
}

/** 一次运行里的一个阶段。 */
export interface ReproductionPhase {
  /** download_wheels / install_and_run。 */
  phase: string;
  command: string;
  /** none / bridge。 */
  network: string;
  exit_code: number;
  timed_out: boolean;
  duration_seconds: number;
  log_path: string;
}

export interface ReproductionOutputFile {
  /** output / work。 */
  root: string;
  path: string;
  bytes: number;
}

/** 产物摘要：JSON 的顶层键或 CSV 的表头 —— 指标就是在这里被人看见的。 */
export interface ReproductionOutputSummary {
  file: string;
  kind: string;
  keys?: string[];
  columns?: string[];
}

export interface ReproductionOutputs {
  files: ReproductionOutputFile[];
  summaries: ReproductionOutputSummary[];
  truncated: boolean;
}

/** 一次复现运行：命令、阶段、退出码、日志尾部、产物清单。 */
export interface ReproductionRun {
  run_id: string;
  plan_id: string;
  title: string | null;
  repository: string;
  commit: string | null;
  command: string;
  /** 这条命令抄自哪里；为空表示是人工改写的。 */
  command_documented_at: string | null;
  command_overridden: boolean;
  image: string;
  /** queued / running / succeeded / failed。 */
  status: string;
  phases: ReproductionPhase[];
  exit_code: number | null;
  error: string | null;
  outputs: ReproductionOutputs | null;
  log_tail: string;
  dataset: ReproductionDataset | null;
  isolation: Record<string, string>;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

/** GET /api/reproductions。 */
export interface ReproductionState {
  docker: DockerStatus;
  plans: ReproductionPlan[];
  runs: ReproductionRun[];
}

/** 论文里的一条证据声明。 */
export interface PaperClaim {
  claim: string;
  experiment_id: string;
  result_path: string;
  /** 后端核对过：它引用的结果文件当前是否还在。 */
  result_exists: boolean;
}

/** 投稿契约：官方要求的提交形态。 */
export interface SubmissionContract {
  format: string | null;
  filename_rule: string | null;
  daily_limit: number | null;
  validation_profile: string | null;
  required_files: string[];
  mask_size: number[];
}

/** GET /api/paper：论文证据包与投稿契约。 */
export interface PaperPackage {
  available: boolean;
  package_dir: string;
  tex_path: string | null;
  bib_path: string | null;
  evidence_path: string | null;
  generated_at: string | null;
  sections: string[];
  claims: PaperClaim[];
  research_records: number;
  bib_entries: number;
  submission: SubmissionContract;
}

/** 规则链里的一个必备字段：值 + 官方锚点。 */
export interface TraceRuleField {
  field: string;
  value: string | null;
  has_value: boolean;
  anchor: string | null;
  has_anchor: boolean;
}

/** 人工复核用到的官方来源。 */
export interface TraceRuleSource {
  source_type: string | null;
  source_locator: string | null;
  reviewed_at: string | null;
  confirmation_file: string | null;
}

/** 工作区里的一份证据文档。 */
export interface TraceDocument {
  name: string;
  path: string;
  size_bytes: number;
}

/** 规则链：字段值 → 官方锚点 → 来源定位 → 人工复核。 */
export interface TraceRuleChain {
  spec_path: string | null;
  profile: string;
  ready: boolean;
  gap_count: number;
  approved: boolean;
  approved_at: string | null;
  approved_note: string | null;
  source: TraceRuleSource;
  unresolved_questions: string[];
  fields: TraceRuleField[];
  required_field_count: number;
  missing_value_count: number;
  missing_anchor_count: number;
  documents: TraceDocument[];
}

/** 数据审计的指纹信息。 */
export interface TraceDataAudit {
  available: boolean;
  data_dir: string | null;
  inventory_sha256: string | null;
  file_count: number | null;
  issue_count: number | null;
  generated_at: string | null;
}

/** 一个实验的取数口径：是否落在这次审计的数据范围内。 */
export interface TraceScopeItem {
  experiment_id: string;
  in_scope: boolean;
  /** 排除原因标识，界面负责翻成人话；在范围内为 null。 */
  exclusion: string | null;
  data_version: string | null;
}

/** 数据链：审计指纹 → 每个实验的数据版本 → 是否计入当前赛题。 */
export interface TraceDataChain {
  audit: TraceDataAudit;
  experiments: TraceScopeItem[];
  in_scope_count: number;
}

/** 实验产物：界面能看出文件是真的在盘上，还是只剩一条记录。 */
export interface TraceArtifact {
  path: string;
  name: string;
  exists: boolean;
  size_bytes: number | null;
}

export interface TraceGit {
  available: boolean;
  commit: string | null;
  branch: string | null;
  dirty: boolean | null;
}

export interface TraceEnvironment {
  python: string | null;
  platform: string | null;
  torch: string | null;
  cuda_available: boolean | null;
  gpu: string | null;
}

export interface TraceApproval {
  recorded: boolean;
  verification: string | null;
  approved_at: string | null;
  approved_by: string | null;
  note: string | null;
}

/** 一条实验记录：清单 → 结果 → 产物 → 人工批准。 */
export interface TraceExperiment {
  experiment_id: string;
  in_scope: boolean;
  exclusion: string | null;
  status: string | null;
  manifest_status: string | null;
  result_status: string | null;
  status_consistent: boolean | null;
  change_type: string | null;
  hypothesis: string | null;
  config_path: string | null;
  config_sha256: string | null;
  created_at: string | null;
  seed: number | null;
  parent_id: string | null;
  git: TraceGit;
  environment: TraceEnvironment;
  metrics: Record<string, number>;
  validation_metric: number | null;
  decision: string | null;
  conclusion: string | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  runtime_seconds: number | null;
  tracker_backend: string | null;
  result_path: string | null;
  artifacts: TraceArtifact[];
  approval: TraceApproval;
}

/** 实验链。 */
export interface TraceExperimentChain {
  experiments: TraceExperiment[];
  in_scope_count: number;
  artifact_missing_count: number;
}

/** 一条文献记录。 */
export interface TraceResearchRecord {
  paper_id: string | null;
  title: string | null;
  url: string | null;
  source: string | null;
  year: number | null;
  relevance_score: number | null;
  reproduction_priority: number | null;
  code_url: string | null;
  official_code: boolean;
}

/** 文献链：检索条件 → 记录 → 引用文件，含检索失败。 */
export interface TraceResearchChain {
  query: string | null;
  searched_at: string | null;
  provider_failures: Record<string, string>;
  record_count: number;
  records: TraceResearchRecord[];
  documents: TraceDocument[];
}

/** GET /api/trace：四条溯源链 + 论文终点。 */
export interface TraceSnapshot {
  generated_at: string;
  workspace: string;
  rule: TraceRuleChain;
  data: TraceDataChain;
  experiments: TraceExperimentChain;
  research: TraceResearchChain;
  paper: PaperPackage;
}

/** 单张 GPU 的信息。 */
export interface GpuDevice {
  name: string;
  memory_total_mb: number;
  memory_free_mb: number;
  driver_version: string;
}

/** GET /api/runtime/local：本机运行时快照。 */
export interface RuntimeSnapshot {
  platform: string;
  python: string;
  conda_available: boolean;
  gpu_available: boolean;
  gpus: GpuDevice[];
}

/** 录入官方证据时，一个必备字段的当前状态。 */
export interface RuleEvidenceField {
  field: string;
  /** 规格里的现值，已折成一行文本，界面只用它展示。 */
  value: string | null;
  has_value: boolean;
  anchor: string | null;
  has_anchor: boolean;
  /** 值控件的类型：text / boolean / runtime_output / direction / list / number。 */
  kind: string;
}

/** 证据的来源信息：这份证据是从哪份官方原文复核来的。 */
export interface RuleEvidenceSource {
  source_type: string | null;
  source_locator: string | null;
  reviewed_at: string | null;
  confirmation_file: string | null;
}

/** GET /api/rules/evidence：录入官方证据的表单状态。 */
export interface RuleEvidenceForm {
  supported: boolean;
  profile: string;
  spec_path: string | null;
  source: RuleEvidenceSource;
  fields: RuleEvidenceField[];
  required_field_count: number;
  missing_value_count: number;
  missing_anchor_count: number;
}

/** 提交的一个字段：只带人实际填的东西，其余沿用规格里的值和已有锚点。 */
export interface RuleEvidenceFieldInput {
  field: string;
  anchor: string;
  /** 文本/枚举字段的新值。 */
  value_text?: string;
  /** 布尔字段的新值；显式的 false 也要发出去，不能被当成「没填」。 */
  value_flag?: boolean;
}

/** POST /api/rules/evidence 的请求体。 */
export interface RuleEvidencePayload {
  source_type: string;
  source_locator: string;
  reviewed_at: string;
  fields: RuleEvidenceFieldInput[];
}

/** 证据录入结果：它不会把规则置为已批准。 */
export interface RuleEvidenceOutcome {
  spec_path: string;
  evidence_path: string;
  applied_fields: string[];
  requires_human_confirmation: boolean;
  readiness: RuleReadiness;
  next_action: string;
}

/** 一套内置预设：点了只是把地址和名字预填进表单，之后仍然可以改。 */
export interface ModelProviderPreset {
  id: string;
  name: string;
  base_url: string;
  /** 这套预设是否必须填密钥（本地 Ollama 不需要）。 */
  key_required: boolean;
  docs_url: string;
}

/** 一套已存的模型来源。**不含密钥**，只回「有没有」。 */
export interface ModelProvider {
  id: string;
  name: string;
  /** 它属于哪条预设；自己填的地址是 custom。 */
  preset: string;
  base_url: string;
  model: string;
  /** 这套来源用过的模型名，界面用它做候选。 */
  models: string[];
  key_required: boolean;
  has_key: boolean;
  docs_url: string;
}

/** GET /api/settings/providers：预设 + 已配置的几套 + 哪套在用。 */
export interface ProviderSettings {
  /** 云端托管模型模式；此时客户端不能查看或修改服务端密钥。 */
  managed: boolean;
  presets: ModelProviderPreset[];
  providers: ModelProvider[];
  /** 当前使用的来源 id；一套都没有时是空串。 */
  active: string;
  configured: boolean;
  model: string;
  /** environment / windows_credential_manager / null，不回密钥本身。 */
  key_source: string | null;
  secure_storage_available: boolean;
  api_key_env: string;
}

/** POST /api/settings/providers/test 的结果。 */
export interface ProviderTestResult {
  ok: boolean;
  message: string;
  /** 用上了哪个模型；失败时后端不发这个字段。 */
  model?: string;
}

/** GET /health：后端存活信息。 */
export interface HealthInfo {
  status: string;
  workspace?: string;
  mode?: string;
}

/** Agent 的一次回答，只声明界面会用到的字段。 */
export interface AgentAnswer {
  model: string;
  content: string;
  turns: number;
}

/** POST /api/agent/ask 的请求体。 */
interface AgentRequest {
  prompt: string;
  stage: string;
  max_turns: number;
}

/** 科研契约里的一个动作：内部名字 + 中文名 + 三个标记。 */
export interface ResearchActionSpec {
  name: string;
  label: string;
  /** 规则覆盖不到时，模型是否可以在自由选择里挑走它。 */
  choosable: boolean;
  /** 要动算力的动作：编排器不会自动触发，只登记成待批准。 */
  pending_approval: boolean;
  /** 会让循环停下来的动作（只有"结束"是）。 */
  terminal: boolean;
}

/** 九项核查里的一项：判词（不合格时说的话）与界面的正向问法。 */
export interface ResearchCheckSpec {
  name: string;
  label: string;
  title: string;
}

/** 带中文名与色调的状态项（假设状态 / 分支状态）。 */
export interface ResearchStatusSpec {
  name: string;
  label: string;
  tone: string;
}

/** 判定值：名字 + 中文名 + 色调。 */
export interface ResearchVerdictSpec {
  name: string;
  label: string;
  tone: string;
}

/**
 * GET /api/research/contract：科研词汇的**唯一来源**。
 *
 * 动作名、九项核查、判定值、假设与分支状态的名字、中文名和色调都在后端定义一次，
 * 端侧运行时取。这里刻意没有第二份清单 —— 后端加一个动作，端侧自己就会多显示一个；
 * 而抄一份的代价不是多写几行，是**静默漂移**。
 */
export interface ResearchContract {
  contract_version: number;
  actions: ResearchActionSpec[];
  checks: ResearchCheckSpec[];
  /** 判"假设被反证"之前必须先确认的那几项核查。 */
  falsification_preconditions: string[];
  hypothesis_statuses: ResearchStatusSpec[];
  branch_statuses: ResearchStatusSpec[];
  verdicts: ResearchVerdictSpec[];
  /** 推进作业的状态（进行中 / 已完成 / 失败）。 */
  job_statuses: ResearchStatusSpec[];
  /** 作业里每一步的状态（已落实 / 等人批准 / …）。 */
  step_statuses: ResearchStatusSpec[];
  graph_node_kinds: string[];
  graph_edge_kinds: string[];
}

/** 一条可被实验判决的假设。 */
export interface ResearchHypothesis {
  hypothesis_id: string;
  statement: string;
  rationale: string[];
  predictions: string[];
  falsifiers: string[];
  uncertainty: number | null;
  status: string;
  parent_id: string | null;
  created_at: string;
  /** 有没有预测与反证条件。判据由后端给出，端侧不自己再算一遍。 */
  falsifiable: boolean;
}

/** 一次科研实验的设计（与"一次训练运行"是两件事）。 */
export interface ResearchExperiment {
  experiment_id: string;
  hypothesis_id: string;
  question: string;
  baseline: string;
  independent: string;
  controlled: string[];
  metrics: string[];
  success_condition: string;
  config_path: string;
  /** 非空表示这次设计是空的：编排器判定它跑不起来，理由就在这里。 */
  blocked: string;
  run_id: string;
  artifacts: string[];
  created_at: string;
}

/** 一项核查的取值。三态：true 合格 / false 不合格 / null 没人查过。 */
export interface ResearchCheckValue {
  name: string;
  value: boolean | null;
}

/** 一条证据核查结果。 */
export interface ResearchEvidence {
  evidence_id: string;
  experiment_id: string;
  /**
   * 九项核查的名字与取值，由后端**成对**发出。
   *
   * 端侧（ArkTS）没有反射，按名字取字段就得把那九个名字抄进这里 —— 那就等于契约有了
   * 第二份定义，后端将来加第十项时端侧会静默地少显示一项。
   */
  checks: ResearchCheckValue[];
  verdict: string;
  notes: string;
  recorded_at: string;
}

/** 一条研究分支：一个假设 + 它的实验 + 它的证据 + 它的结论。 */
export interface ResearchBranch {
  branch_id: string;
  hypothesis_id: string;
  experiments: string[];
  evidence_ids: string[];
  conclusion: string;
  status: string;
}

/** 编排器的一次决策。 */
export interface ResearchDecision {
  decision_id: string;
  action: string;
  target_id: string | null;
  reason: string;
  decided_at: string;
}

/** 编排器的下一步。它是**预测**：只读状态，取快照不会推进任何东西。 */
export interface ResearchNextAction {
  decision_id: string;
  action: string;
  target_id: string | null;
  reason: string;
}

/** 假设计数。 */
export interface ResearchHypothesisCounts {
  total: number;
  active: number;
  falsifiable: number;
}

/** 实验计数。「跑完没核查」与「设计跑不起来」是两件事，分开报。 */
export interface ResearchExperimentCounts {
  total: number;
  awaiting_evidence: string[];
  undesignable: string[];
}

/** 分支计数。 */
export interface ResearchBranchCounts {
  total: number;
  active: string[];
}

/** 研究状态摘要。 */
export interface ResearchLoopSummary {
  hypotheses: ResearchHypothesisCounts;
  experiments: ResearchExperimentCounts;
  branches: ResearchBranchCounts;
  cursor: string | null;
  updated_at: string;
}

/** 推进作业里的一步。 */
export interface ResearchLoopStep {
  decision: ResearchDecision;
  status: string;
  detail: string;
}

/** 一次推进作业。 */
export interface ResearchLoopJob {
  job_id: string;
  status: string;
  started_at: string;
  max_steps: number;
  finished_at: string | null;
  steps: ResearchLoopStep[];
  stopped_because: string;
  /** 登记下来、等人批准的动作。它们不阻塞其他路线，但必须显示出来。 */
  pending_approvals: string[];
  error: string;
}

/** GET /api/research/loop 的一屏全貌。 */
export interface ResearchLoopSnapshot {
  summary: ResearchLoopSummary;
  hypotheses: ResearchHypothesis[];
  experiments: ResearchExperiment[];
  evidence: ResearchEvidence[];
  branches: ResearchBranch[];
  decisions: ResearchDecision[];
  next_action: ResearchNextAction;
  /** 正在跑的作业号；没有作业在跑时是 null。 */
  running: string | null;
  jobs: ResearchLoopJob[];
}

/** 推进循环的请求体。 */
interface ResearchLoopStepRequest {
  max_steps: number;
}

/** 请求头。令牌始终发送，后端绑定回环地址时会忽略它。 */
interface BackendHeaders {
  'Content-Type': string;
  'X-YJL-Token': string;
  'Authorization': string;
}

/** 发送一次请求，并把网络层错误转成可读的提示。 */
async function send(url: string, method: http.RequestMethod, body: string,
  readTimeout: number): Promise<http.HttpResponse> {
  const client = http.createHttp();
  try {
    const headers: BackendHeaders = {
      'Content-Type': 'application/json',
      'X-YJL-Token': ACCESS_TOKEN,
      'Authorization': SESSION_TOKEN.length > 0 ? `Bearer ${SESSION_TOKEN}` : ''
    };
    const options: http.HttpRequestOptions = {
      method: method,
      header: headers,
      connectTimeout: CONNECT_TIMEOUT_MS,
      readTimeout: readTimeout
    };
    if (body.length > 0) {
      options.extraData = body;
    }
    return await client.request(url, options);
  } catch (err) {
    const error = err as Error;
    throw new Error(`无法连接 ${url}。请确认后端已启动、地址正确、令牌一致。原始错误：${error.message}`);
  } finally {
    client.destroy();
  }
}

/** 取回 JSON 响应体；非 2xx 直接抛错。 */
async function requestJson<T>(path: string, method: http.RequestMethod, body: string = '',
  readTimeout: number = READ_TIMEOUT_MS): Promise<T> {
  const url: string = `${BASE_URL}${path}`;
  const response: http.HttpResponse = await send(url, method, body, readTimeout);
  const raw: string = typeof response.result === 'string'
    ? response.result
    : JSON.stringify(response.result);
  if (response.responseCode < 200 || response.responseCode >= 300) {
    throw new Error(`后端返回 HTTP ${response.responseCode}：${raw}`);
  }
  return JSON.parse(raw) as T;
}

/** 新建项目与切换项目的请求体。 */
interface ProjectCreateRequest {
  name: string;
}

/** 人工确认规则、人工批准实验的请求体。 */
interface RuleApprovalRequest {
  note: string;
}

interface DecisionApprovalRequest {
  experiment_id: string;
}

/** 只认 id 的请求体：切换当前来源、删除来源、测试某一套都用它。 */
interface ProviderIdRequest {
  id: string;
}

/** 新增/更新一套模型来源的请求体；`id` 为空串表示新增。 */
interface ProviderSaveRequest {
  id: string;
  preset: string;
  name: string;
  base_url: string;
  model: string;
  api_key: string;
}

/** 检索请求：query 为空串表示按规则规格拼检索式。 */
interface ResearchSearchRequest {
  query: string;
}

/** 取舍请求：decision 取 investigate / discard / undecided。 */
interface ResearchDecisionRequest {
  paper_id: string;
  decision: string;
  note: string;
}

/** 生成复现计划的请求体。 */
interface ReproductionPlanRequest {
  paper_id: string;
}

/** 批准运行的请求体：command 留空表示用计划里选中的那条原文。 */
interface ReproductionRunRequest {
  plan_id: string;
  command_id: string;
  note: string;
  command: string;
}

interface ProjectSelectRequest {
  id: string;
}

/** 读取项目列表（当前项目带 current 标记）。 */
export function fetchProjects(): Promise<ProjectListResponse> {
  return requestJson<ProjectListResponse>('/api/projects', http.RequestMethod.GET);
}

/** 新建项目：后端建好目录骨架与规格并把它设为当前项目。 */
export function createProject(name: string): Promise<ProjectListResponse> {
  const payload: ProjectCreateRequest = { name: name };
  return requestJson<ProjectListResponse>('/api/projects', http.RequestMethod.POST,
    JSON.stringify(payload));
}

/** 切换当前项目：之后的接口都会作用在新工作区上，不需要重启后端。 */
export function selectProject(id: string): Promise<ProjectListResponse> {
  const payload: ProjectSelectRequest = { id: id };
  return requestJson<ProjectListResponse>('/api/projects/select', http.RequestMethod.POST,
    JSON.stringify(payload));
}

/**
 * 删除项目：后端从注册表移除并删掉整个工作区目录。
 *
 * 删掉的正好是当前项目时后端会把当前项目置空（不会自动挑一个顶上），
 * 所以调用方拿到结果后应留在项目选择页。
 */
export function deleteProject(id: string): Promise<ProjectListResponse> {
  return requestJson<ProjectListResponse>(`/api/projects/${id}`, http.RequestMethod.DELETE);
}

/** 读取仪表盘聚合快照。 */
export function fetchDashboard(): Promise<DashboardSnapshot> {
  return requestJson<DashboardSnapshot>('/api/dashboard', http.RequestMethod.GET);
}

/** 读取完整工作流状态。 */
export function fetchWorkflow(): Promise<WorkflowDetail> {
  return requestJson<WorkflowDetail>('/api/workflow', http.RequestMethod.GET);
}

/** 读取下一步动作队列。 */
export function fetchNextActions(): Promise<NextActionsResponse> {
  return requestJson<NextActionsResponse>('/api/next-actions', http.RequestMethod.GET);
}

/** 读取规则确认就绪度与缺口清单。 */
export function fetchRulesReport(): Promise<RulesReport> {
  return requestJson<RulesReport>('/api/rules/report', http.RequestMethod.GET);
}

/** 读取实验账本。 */
export function fetchExperiments(): Promise<ExperimentsResponse> {
  return requestJson<ExperimentsResponse>('/api/experiments', http.RequestMethod.GET);
}

/**
 * 读取官方证据录入表单：逐字段现值/锚点 + 值控件类型。
 *
 * 只读；表单里缺的锚点就是要人去官方原文里核对填上的部分。
 */
export function fetchRuleEvidence(): Promise<RuleEvidenceForm> {
  return requestJson<RuleEvidenceForm>('/api/rules/evidence', http.RequestMethod.GET);
}

/**
 * 提交官方证据：后端先落一份证据记录文件，再把值/锚点应用到规格。
 *
 * 它**不会**批准规则：批准仍要人在规则关口单独提交复核说明。
 */
export function submitRuleEvidence(payload: RuleEvidencePayload): Promise<RuleEvidenceOutcome> {
  return requestJson<RuleEvidenceOutcome>('/api/rules/evidence', http.RequestMethod.POST,
    JSON.stringify(payload));
}

/**
 * 人工确认规则规范。
 *
 * 这是工作流的第一道关口：规则字段必须齐备、且必须写一句复核说明，
 * 后端才会把确认写进 competition_spec.yaml 与账本。它不会启动任何训练。
 */
export function approveRules(note: string): Promise<RuleApprovalOutcome> {
  const payload: RuleApprovalRequest = { note: note };
  return requestJson<RuleApprovalOutcome>('/api/rules/approve', http.RequestMethod.POST,
    JSON.stringify(payload));
}

/**
 * 为某个实验记录一条人工批准。
 *
 * 只写 experiments/approvals/<id>.json 与账本，执行仍然要人另行走命令行；
 * 后端返回的 scope 里也写着这一点。
 */
export function approveExperiment(experimentId: string): Promise<DecisionApproval> {
  const payload: DecisionApprovalRequest = { experiment_id: experimentId };
  return requestJson<DecisionApproval>('/api/decisions/approve', http.RequestMethod.POST,
    JSON.stringify(payload));
}

/** 读取训练任务队列。 */
export function fetchTrainingJobs(): Promise<TrainingJobsResponse> {
  return requestJson<TrainingJobsResponse>('/api/experiments/jobs', http.RequestMethod.GET);
}

/**
 * 登记一条实验草案。
 *
 * 只写草案记录、记一次账本事件，不会启动训练；
 * 后端返回的状态是 awaiting_human_approval，执行与否仍由人决定。
 */
export function createExperimentDraft(hypothesis: string): Promise<ExperimentDraft> {
  const payload: DraftRequest = { hypothesis: hypothesis };
  return requestJson<ExperimentDraft>('/api/experiments/drafts', http.RequestMethod.POST,
    JSON.stringify(payload));
}

/** 读取已登记的实验草案，最新的在前。 */
export function fetchExperimentDrafts(): Promise<DraftListResponse> {
  return requestJson<DraftListResponse>('/api/experiments/drafts', http.RequestMethod.GET);
}

/** 读取最近一次数据审计结果。 */
export function fetchDataAudit(): Promise<DataAuditReport> {
  return requestJson<DataAuditReport>('/api/data-audit', http.RequestMethod.GET);
}

/** 读取文献检索记录 + 取舍 + 评判。 */
export function fetchResearch(): Promise<ResearchReport> {
  return requestJson<ResearchReport>('/api/research', http.RequestMethod.GET);
}

/**
 * 触发一次文献检索。
 *
 * `query` 传空串就是「按规则检索」：后端会从 competition_spec.yaml 里的任务类型与
 * 模态拼检索式。给了词就按词查，用于人工微调。
 */
export function searchResearch(query: string): Promise<ResearchReport> {
  const payload: ResearchSearchRequest = { query: query };
  return requestJson<ResearchReport>('/api/research/search', http.RequestMethod.POST,
    JSON.stringify(payload));
}

/**
 * 记下一条候选的取舍。
 *
 * 取舍单独落盘，重跑检索不会覆盖它。decision 取 investigate / discard / undecided。
 */
export function decideResearchCandidate(paperId: string, decision: string, note: string): Promise<ResearchReport> {
  const payload: ResearchDecisionRequest = { paper_id: paperId, decision: decision, note: note };
  return requestJson<ResearchReport>('/api/research/decide', http.RequestMethod.POST,
    JSON.stringify(payload));
}

/**
 * 对已标记「调研」的候选做价值评判。
 *
 * 评判会用论文标题去 GitHub 找实现仓库，所以后端默认只评判 investigate 的那些，
 * 已经决定不看的不值得再花一次查询。
 */
export function assessResearchCandidates(): Promise<ResearchReport> {
  return requestJson<ResearchReport>('/api/research/assess', http.RequestMethod.POST, JSON.stringify({}));
}

/** 读取复现计划与运行记录，外加 docker 可用性。 */
export function fetchReproductions(): Promise<ReproductionState> {
  return requestJson<ReproductionState>('/api/reproductions', http.RequestMethod.GET);
}

/**
 * 给一条候选生成复现计划。
 *
 * 这一步会 clone 仓库 —— 点这个按钮就是批准 clone。克隆仍然只做静态检查；
 * 代码要被**执行**还得再走 runReproduction 那道批准。
 */
export function planReproduction(paperId: string): Promise<ReproductionPlan> {
  const payload: ReproductionPlanRequest = { paper_id: paperId };
  return requestJson<ReproductionPlan>('/api/reproductions/plan', http.RequestMethod.POST,
    JSON.stringify(payload));
}

/**
 * 批准并运行一次复现。
 *
 * `note` 是必填的批准说明；`command` 为人改写后的命令（留空则用计划里选中的那条），
 * 后端会把它原样记进批准文件 —— 批准的就是实际要跑的那一行。
 */
export function runReproduction(planId: string, commandId: string, note: string,
  command: string): Promise<ReproductionRun> {
  const payload: ReproductionRunRequest = {
    plan_id: planId,
    command_id: commandId,
    note: note,
    command: command
  };
  return requestJson<ReproductionRun>('/api/reproductions/run', http.RequestMethod.POST,
    JSON.stringify(payload));
}

/**
 * 读取科研契约。
 *
 * 它是端侧唯一该认的词汇表：动作名、九项核查、判定与状态的中文名和色调都从这里取。
 * 端侧不抄第二份 —— 抄一份的代价是静默漂移：后端删掉一个动作，界面还显示着它的名字。
 */
export function fetchResearchContract(): Promise<ResearchContract> {
  return requestJson<ResearchContract>('/api/research/contract', http.RequestMethod.GET);
}

/** 读取研究循环的一屏全貌（含编排器对下一步的**预测**，取它不会推进任何东西）。 */
export function fetchResearchLoop(): Promise<ResearchLoopSnapshot> {
  return requestJson<ResearchLoopSnapshot>('/api/research/loop', http.RequestMethod.GET);
}

/**
 * 推进循环若干步。
 *
 * 走作业模式：一步可能跑满多轮模型调用，同步返回必然读超时。后端返回作业号，
 * 界面再轮询 `/api/research/loop` 的 running 与 jobs 看进度。
 *
 * 要动算力的动作（跑训练、复现）**不会被这一步触发**，它们只被登记成待批准。
 */
export function stepResearchLoop(maxSteps: number): Promise<ResearchLoopJob> {
  const payload: ResearchLoopStepRequest = { max_steps: maxSteps };
  return requestJson<ResearchLoopJob>('/api/research/loop/step', http.RequestMethod.POST,
    JSON.stringify(payload));
}

/**
 * 把已有实验记录重新接进研究状态。
 *
 * 幂等：训练是异步的，跑完之后没有谁通知编排层 —— 界面上的「重新回填」和轮询时的自动
 * 回填走的是同一条路。
 */
export function backfillResearchLoop(): Promise<ResearchLoopSnapshot> {
  return requestJson<ResearchLoopSnapshot>('/api/research/loop/backfill', http.RequestMethod.POST,
    JSON.stringify({}));
}

/** 读取论文证据包与投稿契约。 */
export function fetchPaper(): Promise<PaperPackage> {
  return requestJson<PaperPackage>('/api/paper', http.RequestMethod.GET);
}

/** 读取四条溯源链：每条结论到原始证据的路径。 */
export function fetchTrace(): Promise<TraceSnapshot> {
  return requestJson<TraceSnapshot>('/api/trace', http.RequestMethod.GET);
}

/** 读取本机运行时快照。 */
export async function fetchRuntime(): Promise<RuntimeSnapshot> {
  const raw: RuntimeRaw = await requestJson<RuntimeRaw>('/api/runtime/local', http.RequestMethod.GET);
  const gpus: GpuDevice[] = raw.gpu.gpus ? raw.gpu.gpus : [];
  const snapshot: RuntimeSnapshot = {
    platform: raw.platform,
    python: raw.python,
    conda_available: raw.conda.available,
    gpu_available: raw.gpu.available,
    gpus: gpus
  };
  return snapshot;
}

/** 读取模型来源：预设清单 + 已配置的几套 + 哪套在用。 */
export function fetchProviders(): Promise<ProviderSettings> {
  return requestJson<ProviderSettings>('/api/settings/providers', http.RequestMethod.GET);
}

/**
 * 新增或更新一套模型来源。
 *
 * `apiKey` 留空表示**不改动已存的密钥** —— 只改地址或模型名时不用把密钥再填一遍。
 * 后端把它存进系统凭据管理器，`settings.json` 里只有名称、地址与模型。
 */
export function saveProvider(id: string, preset: string, name: string, baseUrl: string,
  model: string, apiKey: string): Promise<ProviderSettings> {
  const payload: ProviderSaveRequest = {
    id: id,
    preset: preset,
    name: name,
    base_url: baseUrl,
    model: model,
    api_key: apiKey
  };
  return requestJson<ProviderSettings>('/api/settings/providers', http.RequestMethod.POST,
    JSON.stringify(payload));
}

/** 换一套当前使用。 */
export function setActiveProvider(id: string): Promise<ProviderSettings> {
  const payload: ProviderIdRequest = { id: id };
  return requestJson<ProviderSettings>('/api/settings/providers/active', http.RequestMethod.POST,
    JSON.stringify(payload));
}

/** 删掉一套。删的是本地这份配置，系统凭据库里那条记录不动。 */
export function deleteProvider(id: string): Promise<ProviderSettings> {
  const payload: ProviderIdRequest = { id: id };
  return requestJson<ProviderSettings>('/api/settings/providers/delete', http.RequestMethod.POST,
    JSON.stringify(payload));
}

/**
 * 发出一句最小请求，验证某一套配得通不通。
 *
 * 可以指定还没切过去的那一套先试。**配不通时后端返回 502**，而那句话正是界面要显示的东西，
 * 所以这里不能走 `requestJson`（它见到非 2xx 就抛）—— 直接在响应体上解析。
 */
export async function testProvider(id: string): Promise<ProviderTestResult> {
  const payload: ProviderIdRequest = { id: id };
  const response: http.HttpResponse = await send(`${BASE_URL}/api/settings/providers/test`,
    http.RequestMethod.POST, JSON.stringify(payload), READ_TIMEOUT_MS);
  const raw: string = typeof response.result === 'string'
    ? response.result
    : JSON.stringify(response.result);
  return JSON.parse(raw) as ProviderTestResult;
}

/** 读取后端存活信息。 */
export function fetchHealth(): Promise<HealthInfo> {
  return requestJson<HealthInfo>('/api/health', http.RequestMethod.GET);
}

/** 登录或注册；令牌只在内存中设置，密码不落盘。 */
async function authenticateAccount(path: string, username: string, password: string): Promise<AccountInfo> {
  const result: AuthResponse = await requestJson<AuthResponse>(path, http.RequestMethod.POST,
    JSON.stringify({ username: username, password: password }));
  setSessionToken(result.token);
  return result.account;
}

export function registerAccount(username: string, password: string): Promise<AccountInfo> {
  return authenticateAccount('/api/auth/register', username, password);
}

export function loginAccount(username: string, password: string): Promise<AccountInfo> {
  return authenticateAccount('/api/auth/login', username, password);
}

export function fetchAccount(): Promise<AccountInfo> {
  return requestJson<AccountInfo>('/api/account', http.RequestMethod.GET);
}

export async function logoutAccount(): Promise<void> {
  await requestJson<LogoutResponse>('/api/auth/logout', http.RequestMethod.POST, JSON.stringify({}));
  clearSessionToken();
}

/**
 * 向本地 Agent 提一个问题。
 *
 * Agent 会带着工作区记录做多轮工具调用，因此读超时放宽到 3 分钟。
 * 提问不会改动任何证据文件，改动类动作仍然要单独审批。
 * 用的是「当前使用」的那套模型来源。
 */
export function askAgent(prompt: string, stage: string): Promise<AgentAnswer> {
  const payload: AgentRequest = { prompt: prompt, stage: stage, max_turns: 6 };
  return requestJson<AgentAnswer>('/api/agent/ask', http.RequestMethod.POST,
    JSON.stringify(payload), AGENT_TIMEOUT_MS);
}

/** 运行时接口的原始嵌套结构，只在本文件内使用。 */
interface RuntimeCondaRaw {
  available: boolean;
}

interface RuntimeGpuRaw {
  available: boolean;
  gpus: GpuDevice[];
}

interface RuntimeRaw {
  platform: string;
  python: string;
  conda: RuntimeCondaRaw;
  gpu: RuntimeGpuRaw;
}
