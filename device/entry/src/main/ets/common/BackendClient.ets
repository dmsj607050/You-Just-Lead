import { http } from '@kit.NetworkKit';
import { ACCESS_TOKEN, AGENT_TIMEOUT_MS, BASE_URL, CONNECT_TIMEOUT_MS, READ_TIMEOUT_MS } from './BackendConfig';

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
  reproduction_priority: string | null;
  abstract: string | null;
}

/** GET /api/research：文献雷达的检索结果。 */
export interface ResearchReport {
  query: string | null;
  searched_at: string | null;
  sources: string[];
  records: ResearchRecord[];
  provider_failures: Record<string, string>;
  report_markdown: string;
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
  approved_at: string | null;
  approved_by: string | null;
}

/** 一条实验记录：清单 → 结果 → 产物 → 人工批准。 */
export interface TraceExperiment {
  experiment_id: string;
  in_scope: boolean;
  exclusion: string | null;
  status: string | null;
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

/** GET /api/settings/deepseek：模型设置状态。 */
export interface DeepSeekSettings {
  configured: boolean;
  key_source: string;
  model: string;
  supported_models: string[];
  secure_storage_available: boolean;
}

/** GET /health：后端存活信息。 */
export interface HealthInfo {
  status: string;
  workspace: string;
}

/** Agent 的一次回答，只声明界面会用到的字段。 */
export interface AgentAnswer {
  model: string;
  content: string;
  turns: number;
}

/** POST /api/agent/deepseek 的请求体。 */
interface AgentRequest {
  prompt: string;
  stage: string;
  max_turns: number;
}

/** 请求头。令牌始终发送，后端绑定回环地址时会忽略它。 */
interface BackendHeaders {
  'Content-Type': string;
  'X-YJL-Token': string;
}

/** 发送一次请求，并把网络层错误转成可读的提示。 */
async function send(url: string, method: http.RequestMethod, body: string,
  readTimeout: number): Promise<http.HttpResponse> {
  const client = http.createHttp();
  try {
    const headers: BackendHeaders = {
      'Content-Type': 'application/json',
      'X-YJL-Token': ACCESS_TOKEN
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

/** 读取文献检索记录。 */
export function fetchResearch(): Promise<ResearchReport> {
  return requestJson<ResearchReport>('/api/research', http.RequestMethod.GET);
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

/** 读取模型设置状态。 */
export function fetchDeepSeekSettings(): Promise<DeepSeekSettings> {
  return requestJson<DeepSeekSettings>('/api/settings/deepseek', http.RequestMethod.GET);
}

/** 读取后端存活信息。 */
export function fetchHealth(): Promise<HealthInfo> {
  return requestJson<HealthInfo>('/health', http.RequestMethod.GET);
}

/**
 * 向本地 Agent 提一个问题。
 *
 * Agent 会带着工作区记录做多轮工具调用，因此读超时放宽到 3 分钟。
 * 提问不会改动任何证据文件，改动类动作仍然要单独审批。
 */
export function askAgent(prompt: string, stage: string): Promise<AgentAnswer> {
  const payload: AgentRequest = { prompt: prompt, stage: stage, max_turns: 6 };
  return requestJson<AgentAnswer>('/api/agent/deepseek', http.RequestMethod.POST,
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
