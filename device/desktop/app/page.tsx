"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, DragEvent } from "react";
import { DesktopModelSettings } from "./desktop-model-settings";

type Run = {
  id: string;
  name: string;
  metric: string;
  change: string;
  state: "accepted" | "running" | "planned";
  detail: string;
};

type DashboardExperiment = {
  id: string;
  status: string;
  metric: number | null;
  best_epoch: number | null;
  hypothesis: string | null;
  change_type: string | null;
  runtime_seconds: number | null;
  decision: string | null;
};

type RunnerCapability = {
  runner: string;
  kind: string;
  task_types: string[];
  template: string;
  data_contract: string;
};

type ExperimentProposal = {
  proposal_id: string;
  rank: number;
  change_type: string;
  hypothesis: string;
  priority_score: number;
  expected_gain: string;
  evidence: Array<{ source: string; detail: string }>;
};

type DashboardSnapshot = {
  competition: {
    name: string | null;
    metric: string | null;
    requires_human_confirmation: boolean;
    rule_readiness?: { ready: boolean; gaps: Array<{ field: string; reason: string }> };
  };
  summary: {
    completed_experiments: number;
    total_experiments: number;
    best: { experiment_id: string; metric: number; history: Array<Record<string, number>> } | null;
    data_files: number;
    data_issues: number;
    research_records: number;
  };
  experiments: DashboardExperiment[];
  workflow?: { stage: string; blockers: string[]; completed_experiments: number };
  capabilities?: { runners: RunnerCapability[] };
  proposals?: ExperimentProposal[];
};

const navigation = ["总览", "实验台账", "数据审计", "研究雷达", "论文证据"];

const offlineRun: Run = {
  id: "OFFLINE",
  name: "Local API unavailable",
  metric: "—",
  change: "No live data",
  state: "planned",
  detail: "This screen deliberately does not substitute demo experiments for real competition records.",
};

type WorkspaceStage = "project" | "rules" | "data" | "research" | "materials" | "build" | "environment";
type WorkspaceView = WorkspaceStage | "overview";
type UploadedRule = { name: string; type: string; size: number; file: File };
type RuleSection = Record<string, unknown>;
type RuleSpec = {
  competition?: RuleSection;
  data?: RuleSection;
  evaluation?: RuleSection;
  submission?: RuleSection;
  constraints?: RuleSection;
  approval?: RuleSection;
  rule_source?: RuleSection;
};
type RuleReadiness = {
  ready: boolean;
  gaps: Array<{ field: string; reason: string }>;
};
type RuleImportReport = {
  source?: { kind: string; filename: string; path: string; sha256: string; url?: string | null };
  analysis: { evidence_count?: number; unresolved_questions?: string[] };
  spec: RuleSpec;
  readiness: RuleReadiness;
  report_markdown: string;
};
type MaterialState = "queued" | "downloading" | "reading" | "ready" | "failed";
type MaterialItem = {
  paper_id: string;
  title?: string;
  paper: { status: string; error?: string; excerpt?: string };
  code: { status: string; error?: string };
};
type MaterialJob = {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  paper_ids: string[];
  items?: MaterialItem[];
  error?: string | null;
  safety_note?: string;
};
type DataAuditJob = {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  data_dir: string;
  summary?: {
    file_count: number;
    issue_count: number;
    inventory_sha256: string;
    file_kinds: Record<string, number>;
    splits: Record<string, number>;
  } | null;
  error?: string | null;
  safety_note?: string;
};
type ResearchRecord = {
  paper_id: string;
  source: string;
  title: string;
  year?: number | null;
  venue?: string | null;
  abstract?: string | null;
  url?: string | null;
  code_url?: string | null;
  official_code?: boolean;
};
type ResearchCard = {
  id: string;
  title: string;
  source: string;
  date: string;
  code: string;
  takeaway: string;
  tag: string;
  url?: string | null;
  codeUrl?: string | null;
};
type ResearchReport = {
  query: string | null;
  searched_at?: string | null;
  sources?: string[];
  records: ResearchRecord[];
  provider_failures: Record<string, string>;
  report_markdown?: string;
};
type TrainingTarget = "local" | "server";
type CondaStrategy = "existing" | "new";
type EnvironmentAssessment = {
  status: "local-ready" | "server-needed" | "server-ready" | "server-insufficient";
  title: string;
  reason: string;
  recommendation: string;
};

type RuntimeProbeReport = {
  probe_id: string;
  target: TrainingTarget;
  runtime: {
    platform: string;
    python: string;
    conda: { available: boolean; environments: string[]; error?: string };
    gpu: { available: boolean; gpus: Array<{ name: string; memory_total_mb: number; memory_free_mb: number; driver_version: string }> };
  };
  environment: { strategy: CondaStrategy; requested?: string | null; status: string; note: string };
  assessment: {
    status: "local_ready" | "server_needed" | "server_ready" | "server_insufficient";
    title: string;
    reason: string;
    recommendation: string;
    available_vram_gb: number;
    total_vram_gb: number;
    recommended_vram_gb: number;
    recommended_batch_size: number;
    gpu_name?: string | null;
  };
};
type TrainingScaffoldReport = {
  build_id: string;
  status: "ready_for_environment_review" | "needs_data_mapping";
  config_path: string;
  report_path: string;
  markdown_path: string;
  runner: string;
  blockers: string[];
  advisories: string[];
  data_audit: { inventory_sha256: string; file_count?: number | null; issue_count?: number | null };
  execution: { started: false; queued: false; automatic_execution: false; next_gate: string };
};

const workspaceStages: Array<{ id: WorkspaceStage; index: number; title: string; hint: string }> = [
  { id: "project", index: 1, title: "项目", hint: "新建竞赛项目" },
  { id: "rules", index: 2, title: "规则", hint: "提交并确认规则" },
  { id: "data", index: 3, title: "数据", hint: "审计原始数据集" },
  { id: "research", index: 4, title: "检索", hint: "筛选研究资料" },
  { id: "materials", index: 5, title: "分析", hint: "阅读论文与源码" },
  { id: "build", index: 6, title: "构建", hint: "实现训练框架" },
  { id: "environment", index: 7, title: "部署", hint: "确认训练位置" },
];

const researchPreview: ResearchCard[] = [
  {
    id: "rein",
    title: "Rein: A Comprehensive Benchmark and Model for Remote Sensing Image Segmentation",
    source: "CVPR 2024 · GitHub",
    date: "2024-06",
    code: "提供源码",
    takeaway: "可借鉴可复用的遥感分割骨干、适配策略与训练配置。",
    tag: "模型结构",
  },
  {
    id: "fourier",
    title: "Fourier Domain Generalization for Semantic Segmentation",
    source: "CVPR 2021 · arXiv",
    date: "2021-06",
    code: "代码待核验",
    takeaway: "可作为跨区域、跨成像条件下的数据增强与泛化思路。",
    tag: "训练策略",
  },
  {
    id: "dbfnet",
    title: "DBF-Net: Boundary-aware Water Body Extraction from Remote Sensing Images",
    source: "Journal of Geo-information Science",
    date: "2026",
    code: "论文方法",
    takeaway: "可借鉴边界约束、细长水体错误分析与后处理设计。",
    tag: "优化思路",
  },
];

function formatFileSize(size: number) {
  return size < 1024 * 1024 ? `${Math.max(1, Math.round(size / 1024))} KB` : `${(size / 1024 / 1024).toFixed(1)} MB`;
}
function researchCardFromRecord(record: ResearchRecord): ResearchCard {
  const abstract = (record.abstract ?? "").replace(/\s+/g, " ").trim();
  const venue = record.venue ? ` · ${record.venue}` : "";
  return {
    id: record.paper_id,
    title: record.title,
    source: `${record.source}${venue}`,
    date: record.year ? String(record.year) : "日期未提供",
    code: record.code_url ? "提供源码入口" : "未提供源码入口",
    takeaway: record.code_url
      ? "已发现公开源码入口；确认采用后可创建可审计的静态复现任务。"
      : abstract ? `摘要摘录：${abstract.slice(0, 180)}${abstract.length > 180 ? "…" : ""}` : "已保存公开索引记录；需阅读原文后再判断可借鉴点。",
    tag: record.source.toUpperCase(),
    url: record.url,
    codeUrl: record.code_url,
  };
}


const LOCAL_AGENT_URL = "http://127.0.0.1:8765";

function ruleValue(spec: RuleSpec, section: keyof RuleSpec, field: string) {
  const value = (spec[section] as RuleSection | undefined)?.[field];
  if (value === undefined || value === null || value === "") return "未从当前材料中提取";
  if (Array.isArray(value)) return value.join("、") || "未从当前材料中提取";
  if (value === true) return "允许";
  if (value === false) return "不允许";
  return String(value);
}

function fileToBase64(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error(`无法读取文件：${file.name}`));
    reader.onload = () => {
      if (typeof reader.result !== "string") {
        reject(new Error(`无法读取文件：${file.name}`));
        return;
      }
      resolve(reader.result.split(",", 2)[1] ?? "");
    };
    reader.readAsDataURL(file);
  });
}

async function localApiRequest<T>(path: string, init?: RequestInit) {
  const response = await fetch(`${LOCAL_AGENT_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const raw = await response.text();
  let payload: unknown = {};
  try {
    payload = raw ? JSON.parse(raw) : {};
  } catch {
    throw new Error("本地 Agent 返回了无法解析的响应。");
  }
  if (!response.ok) {
    const message = typeof payload === "object" && payload && "error" in payload ? String(payload.error) : `请求失败（${response.status}）`;
    throw new Error(message);
  }
  return payload as T;
}




function CompetitionWorkspace() {
  const [stage, setStage] = useState<WorkspaceView>("project");
  const [furthestStage, setFurthestStage] = useState(1);
  const [projectName, setProjectName] = useState("");
  const [projectCreated, setProjectCreated] = useState(false);
  const [ruleFiles, setRuleFiles] = useState<UploadedRule[]>([]);
  const [ruleUrl, setRuleUrl] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const [ruleParsing, setRuleParsing] = useState(false);
  const [ruleReportReady, setRuleReportReady] = useState(false);
  const [ruleReport, setRuleReport] = useState<RuleImportReport | null>(null);
  const [ruleReviewNote, setRuleReviewNote] = useState("");
  const [rulesConfirmed, setRulesConfirmed] = useState(false);
  const [dataDirectory, setDataDirectory] = useState("");
  const [dataAuditJob, setDataAuditJob] = useState<DataAuditJob | null>(null);
  const [dataAuditRunning, setDataAuditRunning] = useState(false);
  const dataAuditPollTimer = useRef<number | null>(null);  const [researchStarted, setResearchStarted] = useState(false);
  const [researchQuery, setResearchQuery] = useState("");
  const [researchCards, setResearchCards] = useState<ResearchCard[] | null>(null);
  const [researchSearching, setResearchSearching] = useState(false);
  const [researchFailures, setResearchFailures] = useState<Record<string, string>>({});
  const [selectedReferences, setSelectedReferences] = useState<string[]>(researchPreview.map((item) => item.id));
  const [referencesConfirmed, setReferencesConfirmed] = useState(false);
  const [materialStates, setMaterialStates] = useState<Record<string, MaterialState>>({});
  const [materialsRunning, setMaterialsRunning] = useState(false);
  const [materialDetails, setMaterialDetails] = useState<Record<string, string>>({});
  const [materialJobId, setMaterialJobId] = useState<string | null>(null);
  const materialPollTimer = useRef<number | null>(null);
  useEffect(() => () => {
    if (materialPollTimer.current !== null) window.clearTimeout(materialPollTimer.current);
    if (dataAuditPollTimer.current !== null) window.clearTimeout(dataAuditPollTimer.current);
  }, []);
  const [trainingStarted, setTrainingStarted] = useState(false);
  const [trainingProgress, setTrainingProgress] = useState(0);
  const [trainingTarget, setTrainingTarget] = useState<TrainingTarget>("local");
  const [condaStrategy, setCondaStrategy] = useState<CondaStrategy>("existing");
  const [condaEnvironment, setCondaEnvironment] = useState("");
  const [serverHost, setServerHost] = useState("");
  const [serverPort, setServerPort] = useState("22");
  const [serverUser, setServerUser] = useState("");
  const [serverAuth, setServerAuth] = useState<"key" | "password">("key");
  const [trainingBuilding, setTrainingBuilding] = useState(false);
  const [trainingScaffold, setTrainingScaffold] = useState<TrainingScaffoldReport | null>(null);
  const [serverCredential, setServerCredential] = useState("");
  const [availableVram, setAvailableVram] = useState("");
  const [requiredVram, setRequiredVram] = useState("24");
  const [probeState, setProbeState] = useState<"idle" | "checking" | "ready">("idle");
  const [environmentAssessment, setEnvironmentAssessment] = useState<EnvironmentAssessment | null>(null);
  const [runtimeProbe, setRuntimeProbe] = useState<RuntimeProbeReport | null>(null);
  const [deploymentConfirmed, setDeploymentConfirmed] = useState(false);
  const [activity, setActivity] = useState("准备创建第一个竞赛项目");
  const [notice, setNotice] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const current = stage === "overview"
    ? workspaceStages[Math.max(0, Math.min(furthestStage - 1, workspaceStages.length - 1))]
    : workspaceStages.find((item) => item.id === stage) ?? workspaceStages[0];

  function moveTo(next: WorkspaceStage) {
    const target = workspaceStages.find((item) => item.id === next)!;
    if (target.index > furthestStage) {
      setNotice("请先完成当前步骤，系统会保留每一步的确认记录。");
      return;
    }
    setStage(next);
  }

  function openProjectMap() {
    if (!projectCreated) {
      setStage("project");
      return;
    }
    setStage("overview");
  }

  function addFiles(files: FileList | File[]) {
    const incoming = Array.from(files).map((file) => ({ name: file.name, type: file.type || "未知格式", size: file.size, file }));
    if (!incoming.length) return;
    setRuleFiles((existing) => [...existing, ...incoming.filter((file) => !existing.some((item) => item.name === file.name))]);
    setNotice(`已加入 ${incoming.length} 个规则文件。`);
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    if (event.target.files) addFiles(event.target.files);
    event.target.value = "";
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragging(false);
    addFiles(event.dataTransfer.files);
  }

  function createProject() {
    const cleanName = projectName.trim();
    if (!cleanName) {
      setNotice("请先为项目命名。");
      return;
    }
    setProjectName(cleanName);
    setProjectCreated(true);
    setFurthestStage(2);
    setStage("rules");
    setActivity(`项目「${cleanName}」已创建，等待提交比赛规则`);
  }

  async function parseRules() {
    if (!ruleFiles.length && !ruleUrl.trim()) {
      setNotice("请上传规则文件，或粘贴一个规则网页链接。");
      return;
    }
    setRuleParsing(true);
    setRulesConfirmed(false);
    setActivity("正在调用本地 Agent 解析比赛规则、保存原始材料并提取结构化字段");
    try {
      let latestReport: RuleImportReport | null = null;
      for (const file of ruleFiles) {
        latestReport = await localApiRequest<RuleImportReport>("/api/rules/import", {
          method: "POST",
          body: JSON.stringify({ filename: file.name, content_base64: await fileToBase64(file.file) }),
        });
      }
      if (ruleUrl.trim()) {
        latestReport = await localApiRequest<RuleImportReport>("/api/rules/import", {
          method: "POST",
          body: JSON.stringify({ source_url: ruleUrl.trim() }),
        });
      }
      if (!latestReport) throw new Error("没有可供解析的规则材料。");
      setRuleReport(latestReport);
      setRuleReportReady(true);
      const gapCount = latestReport.readiness.gaps.length;
      setActivity("规则报告已由本地 Agent 生成，等待人工核对");
      setNotice(`已保存并解析规则材料，提取到 ${latestReport.analysis.evidence_count ?? 0} 条证据${gapCount ? `；还有 ${gapCount} 项待核对` : "；可以填写核对说明后确认"}。`);
    } catch (error) {
      setRuleReportReady(false);
      setRuleReport(null);
      setNotice(error instanceof Error ? `规则解析失败：${error.message}` : "规则解析失败，请检查本地 Agent 是否已启动。");
    } finally {
      setRuleParsing(false);
    }
  }

  async function confirmRules() {
    if (!ruleReport) {
      setNotice("请先生成真实的规则报告。");
      return;
    }
    if (!ruleReviewNote.trim()) {
      setNotice("请填写你已核对官方规则的说明，再确认报告。");
      return;
    }
    setRuleParsing(true);
    try {
      await localApiRequest<{ approved: boolean }>("/api/rules/approve", {
        method: "POST",
        body: JSON.stringify({ note: ruleReviewNote.trim() }),
      });
      const refreshed = await localApiRequest<RuleImportReport>("/api/rules/report");
      setRuleReport(refreshed);
      setRuleReportReady(true);
      setRulesConfirmed(true);
      setFurthestStage(3);
      setStage("data");
      setActivity("规则已确认，请先对原始数据集执行真实审计");
      setNotice("规则确认已写入本地项目记录。下一步请指定本机数据集目录。");
    } catch (error) {
      setNotice(error instanceof Error ? `无法确认规则：${error.message}` : "无法确认规则，请稍后重试。");
    } finally {
      setRuleParsing(false);
    }
  }

  async function pollDataAuditJob(jobId: string) {
    try {
      const job = await localApiRequest<DataAuditJob>("/api/data-audit/jobs/" + encodeURIComponent(jobId));
      setDataAuditJob(job);
      if (job.status === "queued" || job.status === "running") {
        setActivity(job.status === "queued" ? "数据审计任务已入队，等待后台开始" : "正在真实读取文件、计算数据指纹与质量统计");
        dataAuditPollTimer.current = window.setTimeout(() => { void pollDataAuditJob(jobId); }, 700);
        return;
      }
      setDataAuditRunning(false);
      if (job.status === "completed") {
        setFurthestStage(4);
        const summary = job.summary;
        setActivity("数据审计完成，已生成可追溯的数据质量报告");
        setNotice("数据审计 " + job.job_id + " 已完成：共 " + String(summary?.file_count ?? 0) + " 个文件，发现 " + String(summary?.issue_count ?? 0) + " 项质量问题。");
      } else {
        setActivity("数据审计失败");
        setNotice("数据审计 " + job.job_id + " 失败：" + (job.error ?? "未返回错误详情"));
      }
    } catch (error) {
      setDataAuditRunning(false);
      const reason = error instanceof Error ? error.message : "无法读取数据审计任务状态。";
      setActivity("无法读取数据审计状态");
      setNotice("数据审计状态读取失败：" + reason);
    }
  }

  async function startDataAudit() {
    const directory = dataDirectory.trim();
    if (!directory) {
      setNotice("请输入本机比赛数据集目录，例如 B:\\2026xunfei\\train。");
      return;
    }
    if (dataAuditPollTimer.current !== null) window.clearTimeout(dataAuditPollTimer.current);
    setDataAuditRunning(true);
    setDataAuditJob(null);
    setActivity("正在提交只读数据审计任务");
    setNotice("审计会读取原始数据、计算文件指纹并在项目内写入报告；不会移动、修改或上传数据。");
    try {
      const job = await localApiRequest<DataAuditJob>("/api/data-audit/run", {
        method: "POST",
        body: JSON.stringify({ data_dir: directory }),
      });
      setDataAuditJob(job);
      await pollDataAuditJob(job.job_id);
    } catch (error) {
      setDataAuditRunning(false);
      const reason = error instanceof Error ? error.message : "无法提交数据审计任务。";
      setActivity("数据审计未能提交");
      setNotice("无法启动数据审计：" + reason);
    }
  }
  async function startResearch() {
    const query = researchQuery.trim();
    if (!query) {
      setNotice("请输入用于检索的英文关键词或中英文混合技术主题。");
      return;
    }
    setResearchSearching(true);
    setActivity("正在从 arXiv、OpenAlex、Semantic Scholar 与 GitHub 检索公开资料");
    try {
      const report = await localApiRequest<ResearchReport>("/api/research/search", {
        method: "POST",
        body: JSON.stringify({ query, limit: 6 }),
      });
      const cards = report.records.map(researchCardFromRecord);
      setResearchCards(cards);
      setResearchFailures(report.provider_failures ?? {});
      setSelectedReferences(cards.map((item) => item.id));
      setReferencesConfirmed(false);
      setResearchStarted(true);
      setActivity("真实检索结果已保存到本地项目，等待你筛选参考资料");
      const failed = Object.keys(report.provider_failures ?? {}).length;
      setNotice(`已从公开来源保存 ${cards.length} 条结果${failed ? `；${failed} 个来源暂时不可用，详情已显示` : ""}。`);
    } catch (error) {
      setResearchStarted(false);
      setResearchCards(null);
      setNotice(error instanceof Error ? `研究检索失败：${error.message}` : "研究检索失败，请检查本地 Agent 和网络连接。");
    } finally {
      setResearchSearching(false);
    }
  }

  function toggleReference(id: string) {
    setSelectedReferences((items) => items.includes(id) ? items.filter((item) => item !== id) : [...items, id]);
  }

  function confirmReferences() {
    if (!selectedReferences.length) {
      setNotice("至少保留一项参考资料，才能进入资料分析。");
      return;
    }
    setReferencesConfirmed(true);
    setFurthestStage(5);
    setStage("materials");
    setActivity(`已确认 ${selectedReferences.length} 项资料，等待下载与分析`);
  }

  async function pollMaterialJob(jobId: string, chosen: ResearchCard[]) {
    // material intake polling is implemented below.
    try {
      const job = await localApiRequest<MaterialJob>(`/api/materials/jobs/${encodeURIComponent(jobId)}`);
      if (job.status === "queued" || job.status === "running") {
        const interimState: MaterialState = job.status === "queued" ? "queued" : "downloading";
        setMaterialStates(Object.fromEntries(chosen.map((item) => [item.id, interimState])));
        setActivity(job.status === "queued" ? "资料任务已入队，等待后台开始" : "后台正在下载公开论文并静态检查选中的源码");
        materialPollTimer.current = window.setTimeout(() => { void pollMaterialJob(jobId, chosen); }, 900);
        return;
      }

      if (job.status === "completed") {
        const items = new Map((job.items ?? []).map((item) => [item.paper_id, item]));
        const nextStates: Record<string, MaterialState> = {};
        const nextDetails: Record<string, string> = {};
        for (const paper of chosen) {
          const item = items.get(paper.id);
          if (!item) {
            nextStates[paper.id] = "failed";
            nextDetails[paper.id] = "后台任务未返回该资料的记录。";
            continue;
          }
          const paperStatus = item.paper?.status ?? "unknown";
          const codeStatus = item.code?.status ?? "unknown";
          const error = item.paper?.error ?? item.code?.error;
          nextStates[paper.id] = error ? "failed" : "ready";
          nextDetails[paper.id] = error
            ? `论文：${paperStatus}；源码：${codeStatus}；${error}`
            : `论文：${paperStatus}；源码：${codeStatus}`;
        }
        const failed = Object.values(nextStates).filter((state) => state === "failed").length;
        setMaterialStates(nextStates);
        setMaterialDetails(nextDetails);
        setMaterialsRunning(false);
        setFurthestStage(6);
        setActivity(failed ? "资料任务已结束，部分条目需要人工处理" : "选中资料已保存并完成静态分析记录");
        setNotice(failed
          ? `资料任务 ${job.job_id} 已结束；${failed} 项下载或静态复现失败，原因已逐项列出。可修正后重新发起任务。`
          : `资料任务 ${job.job_id} 已完成。论文摘录、源码静态检查结果与分析报告已写入项目工作区。`);
        return;
      }

      setMaterialsRunning(false);
      setMaterialStates(Object.fromEntries(chosen.map((item) => [item.id, "failed" as MaterialState])));
      setMaterialDetails(Object.fromEntries(chosen.map((item) => [item.id, job.error ?? "后台资料任务失败。"])));
      setActivity("资料任务失败");
      setNotice(`资料任务 ${job.job_id} 失败：${job.error ?? "未返回错误详情"}`);
    } catch (error) {
      setMaterialsRunning(false);
      setMaterialStates(Object.fromEntries(chosen.map((item) => [item.id, "failed" as MaterialState])));
      const reason = error instanceof Error ? error.message : "无法读取资料任务状态。";
      setMaterialDetails(Object.fromEntries(chosen.map((item) => [item.id, reason])));
      setActivity("无法读取资料任务状态");
      setNotice(`资料任务状态读取失败：${reason}`);
    }
  }

  async function startMaterialAnalysis() {
    const chosen = activeResearchItems.filter((item) => selectedReferences.includes(item.id));
    if (!chosen.length) {
      setNotice("请至少选择一项真实检索结果，再启动资料下载。");
      return;
    }
    if (materialPollTimer.current !== null) window.clearTimeout(materialPollTimer.current);
    setMaterialsRunning(true);
    setMaterialStates(Object.fromEntries(chosen.map((item) => [item.id, "queued" as MaterialState])));
    setMaterialDetails(Object.fromEntries(chosen.map((item) => [item.id, "等待本地后台任务。"])));
    setActivity("正在提交选中资料的下载与静态分析任务");
    setNotice("仅下载你确认的公开论文，并只对公开源码做静态检查；此流程不会执行第三方代码。");
    try {
      const job = await localApiRequest<MaterialJob>("/api/materials/intake", {
        method: "POST",
        body: JSON.stringify({ paper_ids: chosen.map((item) => item.id) }),
      });
      setMaterialJobId(job.job_id);
      await pollMaterialJob(job.job_id, chosen);
    } catch (error) {
      setMaterialsRunning(false);
      const reason = error instanceof Error ? error.message : "无法提交资料任务。";
      setMaterialStates(Object.fromEntries(chosen.map((item) => [item.id, "failed" as MaterialState])));
      setMaterialDetails(Object.fromEntries(chosen.map((item) => [item.id, reason])));
      setActivity("资料任务未能提交");
      setNotice(`无法启动资料下载与分析：${reason}`);
    }
  }
  async function startBuild() {
    if (trainingBuilding) return;
    setTrainingBuilding(true);
    setTrainingProgress(18);
    setTrainingScaffold(null);
    setActivity("正在根据已确认规则、数据审计和训练适配器生成真实训练配置");
    setNotice("本操作只会写入训练配置和审计报告，不会安装依赖、连接服务器或启动训练。");
    try {
      const report = await localApiRequest<TrainingScaffoldReport>("/api/build/scaffold", {
        method: "POST",
        body: JSON.stringify({}),
      });
      setTrainingScaffold(report);
      setTrainingStarted(true);
      setTrainingProgress(100);
      setActivity(report.status === "ready_for_environment_review"
        ? `训练骨架 ${report.build_id} 已生成，等待环境与 GPU 审核`
        : `训练骨架 ${report.build_id} 已生成，但还需补全数据映射`);
      if (report.status === "ready_for_environment_review") {
        setFurthestStage(7);
        setNotice(`已生成 ${report.config_path}、${report.report_path} 和 ${report.markdown_path}；请继续确认运行环境。`);
      } else {
        setNotice(`已生成 ${report.config_path}，但尚不能训练：${report.blockers.join("；")}`);
      }
    } catch (error) {
      setTrainingStarted(false);
      setTrainingProgress(0);
      const reason = error instanceof Error ? error.message : "本地训练骨架服务未返回可用结果。";
      setActivity("训练骨架未生成");
      setNotice(`无法生成真实训练骨架：${reason}`);
    } finally {

      setTrainingBuilding(false);
    }
  }
  async function probeEnvironment() {
    // The asynchronous read-only implementation is inserted below.

    const minimum = Number(requiredVram);
    if (!Number.isFinite(minimum) || minimum <= 0) {
      setNotice("请先填写训练方案预估的最低显存（GB），再执行真实探测。");
      return;
    }
    if (trainingTarget === "server") {
      if (!serverHost.trim() || !serverUser.trim() || !serverCredential.trim()) {
        setNotice("服务器探测需要地址、登录用户和本机 SSH 私钥路径。私钥内容不会被上传或保存。");
        return;
      }
      if (serverAuth !== "key") {
        setNotice("当前安全探测只支持 SSH 私钥认证；不会向本地 Agent 发送或保存服务器密码。");
        return;
      }
    }
    setProbeState("checking");
    setEnvironmentAssessment(null);
    setRuntimeProbe(null);
    setDeploymentConfirmed(false);
    setActivity(trainingTarget === "local" ? "正在真实读取本机 Conda、Python 与 NVIDIA GPU" : "正在通过 SSH 执行只读的服务器 Conda、Python 与 NVIDIA GPU 探测");
    try {
      const report = await localApiRequest<RuntimeProbeReport>("/api/runtime/probe", {
        method: "POST",
        body: JSON.stringify({
          target: trainingTarget,
          required_vram_gb: minimum,
          conda_strategy: condaStrategy,
          conda_environment: condaEnvironment.trim(),
          server: trainingTarget === "server" ? {
            host: serverHost.trim(),
            port: Number(serverPort) || 22,
            user: serverUser.trim(),
            auth: serverAuth,
            credential: serverCredential.trim(),
          } : undefined,
        }),
      });
      const statusMap: Record<RuntimeProbeReport["assessment"]["status"], EnvironmentAssessment["status"]> = {
        local_ready: "local-ready",
        server_needed: "server-needed",
        server_ready: "server-ready",
        server_insufficient: "server-insufficient",
      };
      setRuntimeProbe(report);
      setAvailableVram(report.assessment.available_vram_gb ? String(report.assessment.available_vram_gb) : "");
      setEnvironmentAssessment({
        status: statusMap[report.assessment.status],
        title: report.assessment.title,
        reason: report.assessment.reason,
        recommendation: report.assessment.recommendation,
      });
      setProbeState("ready");
      setActivity(report.assessment.title);
      const gpu = report.assessment.gpu_name
        ? `${report.assessment.gpu_name} · 空闲 ${report.assessment.available_vram_gb} GB / 总计 ${report.assessment.total_vram_gb} GB`
        : "未返回可用 NVIDIA GPU";
      setNotice(`真实探测 ${report.probe_id} 已保存：${gpu}；Conda 环境状态为 ${report.environment.status}。未创建环境、安装依赖或启动训练。`);
    } catch (error) {
      setProbeState("idle");
      const reason = error instanceof Error ? error.message : "无法完成真实运行环境探测。";
      setActivity("运行环境探测失败");
      setNotice(`运行环境探测失败：${reason}`);
    }
  }

  function evaluateEnvironment() {
    const available = Number(availableVram);
    const minimum = Number(requiredVram);
    if (!Number.isFinite(available) || available <= 0 || !Number.isFinite(minimum) || minimum <= 0) {
      setNotice("请填写可用 GPU 显存和预估最低显存（单位：GB），再生成建议。");
      return;
    }
    if (trainingTarget === "server" && (!serverHost.trim() || !serverUser.trim())) {
      setNotice("选择服务器训练时，请先填写服务器地址与登录用户。密码或私钥不会被保存到项目记录中。");
      return;
    }

    const recommended = Math.ceil(minimum * 1.2);
    const batchSize = available >= 48 ? 8 : available >= 24 ? 4 : 2;
    const hasCapacity = available >= recommended;
    const targetName = trainingTarget === "local" ? "本机" : "该服务器";
    let next: EnvironmentAssessment;
    if (trainingTarget === "local" && !hasCapacity) {
      next = {
        status: "server-needed",
        title: "建议改用服务器训练",
        reason: `本机可用显存为 ${available} GB，而当前方案建议至少预留 ${recommended} GB（模型估算 ${minimum} GB + 运行余量）。继续本机训练容易在前向、验证或保存检查点时发生显存不足。`,
        recommendation: `选择配备 ≥ ${recommended} GB 可用显存的服务器，并优先启用混合精度、梯度累积和可恢复检查点。`,
      };
    } else if (trainingTarget === "server" && !hasCapacity) {
      next = {
        status: "server-insufficient",
        title: "当前服务器规格仍不足",
        reason: `${targetName}填写的可用显存为 ${available} GB，低于建议容量 ${recommended} GB；仅连接服务器并不能解决训练显存不足的问题。`,
        recommendation: `请改选显存 ≥ ${recommended} GB 的 GPU，或回到模型配置阶段降低输入尺寸、模型规模与 batch size。`,
      };
    } else if (trainingTarget === "server") {
      next = {
        status: "server-ready",
        title: "服务器资源可以承载当前方案",
        reason: `${targetName}可用显存 ${available} GB，满足建议容量 ${recommended} GB。服务器地址与运行环境方案已收集，等待真实连通性与 GPU 探测确认。`,
        recommendation: `建议先用 batch size ${batchSize}、混合精度与梯度累积启动一次小规模验证，再放开完整训练。`,
      };
    } else {
      next = {
        status: "local-ready",
        title: "本机可以启动训练",
        reason: `本机可用显存 ${available} GB，满足建议容量 ${recommended} GB。该判断保留了模型估算 ${minimum} GB 的运行余量。`,
        recommendation: `建议以 batch size ${batchSize}、混合精度与梯度累积进行首轮训练；Agent 会在真实运行后依据峰值显存继续调整配置。`,
      };
    }
    setEnvironmentAssessment(next);
    setActivity(next.title);
  }

  function confirmDeploymentPlan() {
    if (!environmentAssessment) {
      setNotice("请先完成资源评估，再确认训练部署方案。");
      return;
    }
    if (environmentAssessment.status === "server-needed" || environmentAssessment.status === "server-insufficient") {
      setNotice("当前资源评估不建议直接启动训练。请切换到满足显存建议的服务器后重新评估。");
      return;
    }
    setDeploymentConfirmed(true);
    setActivity(trainingTarget === "local" ? "本机训练方案已确认，等待启动首轮验证" : "服务器训练方案已确认，等待安全连接与首轮验证");
  }

  const activeResearchItems = researchCards ?? researchPreview;
  const selectedMaterialCount = Object.values(materialStates).filter((item) => item === "ready").length;
  const materialResolvedCount = Object.values(materialStates).filter((item) => item === "ready" || item === "failed").length;
  const chosenReferences = activeResearchItems.filter((item) => selectedReferences.includes(item.id));

  function stageResult(item: WorkspaceStage) {
    if (item.id === "project") return projectCreated ? "项目已建立，工作区已创建" : "等待创建项目";
    if (item.id === "rules") return rulesConfirmed ? "规则报告已确认" : ruleReportReady ? "报告已生成，等待确认" : "等待提交规则";
    if (item.id === "research") return referencesConfirmed ? `已确认 ${selectedReferences.length} 项资料` : researchStarted ? "检索结果等待筛选" : "等待开始检索";
    if (item.id === "materials") return selectedMaterialCount ? `已分析 ${selectedMaterialCount} 项资料` : "等待下载与阅读";
    if (item.id === "build") return trainingProgress === 100 ? "训练框架已构建" : trainingStarted ? "正在构建训练框架" : "等待生成训练工程";
    return deploymentConfirmed ? "训练部署方案已确认" : environmentAssessment ? environmentAssessment.title : "等待资源评估";
  }

  return (
    <main className="workspace-app">
      <aside className="workspace-sidebar">
        <div className="workspace-brand"><span className="brand-orb">YL</span><span><b>You Just Lead</b><small>COMPETITION LAB</small></span></div>
        <button className="project-switcher" type="button" onClick={openProjectMap}><span className="project-badge">{projectName ? projectName.slice(0, 2).toUpperCase() : "＋"}</span><span><small>当前项目</small><b>{projectName || "新建一个项目"}</b></span><i>⌄</i></button>
        <div className="sidebar-menu" aria-label="项目导航"><p>项目</p><button className={stage === "overview" ? "active" : ""} disabled={!projectCreated} onClick={openProjectMap} type="button"><span>◎</span><div><b>项目脉络</b><small>查看流程与阶段结果</small></div></button><button className={stage === "project" ? "active" : ""} onClick={() => setStage("project")} type="button"><span>＋</span><div><b>新建项目</b><small>创建独立竞赛工作区</small></div></button></div>
        <div className="sidebar-model"><p>本地 Agent</p><DesktopModelSettings /></div>
        <div className="sidebar-foot"><span className="signal"><i /> 项目化记录</span><p>流程节点在项目主视图中展开；侧栏只用于进入项目。</p></div>
      </aside>

      <section className="workspace-main">
        <header className="workspace-topbar"><div><span className="eyebrow">COMPETITION TRAINING AGENT</span><h1>{projectName || "创建你的竞赛项目"}</h1></div><div className="topbar-actions">{projectCreated && stage !== "overview" ? <button className="map-return" onClick={openProjectMap} type="button">项目脉络</button> : null}<div className="top-step"><span>{stage === "overview" ? "项目流程" : `步骤 ${String(current.index).padStart(2, "0")} / ${String(workspaceStages.length).padStart(2, "0")}`}</span><b>{stage === "overview" ? "点击节点查看阶段结果" : current.hint}</b></div></div></header>
        <div className="activity-strip"><span className="pulse-dot" /><span>Agent 状态</span><b>{activity}</b></div>
        {notice ? <button className="workspace-notice" onClick={() => setNotice("")} type="button"><span>提示</span>{notice}<i>×</i></button> : null}

        <div className="workspace-content">
          {stage === "overview" && <section className="project-map-page step-page">
            <div className="map-heading"><div><span className="step-number">PROJECT MAP</span><h2>项目正在向前推进。</h2><p>每个节点保存该阶段的输入、确认记录和工作结果。点击任一已开放节点，即可回到对应页面查看或继续工作。</p></div><div className="map-current"><span>当前工作到</span><b>{current.title} · {current.hint}</b></div></div>
            <div className="workflow-map card-surface"><div className="map-legend"><span><i className="legend-done" />已完成</span><span><i className="legend-active" />当前阶段</span><span><i className="legend-locked" />待开始</span></div><div className="graph-scroll"><div className="graph-track" aria-label="竞赛项目流程图">{workspaceStages.map((item, index) => { const nodeState = item.index < furthestStage ? "done" : item.index === furthestStage ? "active" : "locked"; const available = item.index <= furthestStage; return <div className="graph-unit" key={item.id}><button aria-label={`查看${item.title}阶段：${stageResult(item.id)}`} className={`graph-node ${nodeState}`} disabled={!available} onClick={() => moveTo(item.id)} type="button"><span className="graph-number">{String(item.index).padStart(2, "0")}</span><span className="graph-core"><i>{nodeState === "done" ? "✓" : item.index}</i></span><b>{item.title}</b><small>{stageResult(item.id)}</small></button>{index < workspaceStages.length - 1 ? <span className={`graph-flow ${item.index < furthestStage ? "active" : ""}`} aria-hidden="true"><i /></span> : null}</div>; })}</div></div></div>
            <div className="map-detail card-surface"><span className="eyebrow">CURRENT HANDOFF</span><div><h3>{current.title}阶段正在等待处理</h3><p>{stageResult(current.id)}。进入该节点后，可以查看已生成的内容，并继续完成当前所需确认。</p></div><button className="button primary-button" onClick={() => moveTo(current.id)} type="button">进入当前节点 <span>→</span></button></div>
          </section>}

          {stage === "project" && <section className="step-page intro-page">
            <div className="step-copy"><span className="step-number">01 · PROJECT</span><h2>从一场比赛开始，<em>建立你的研究工作区。</em></h2><p>每个项目都会独立保存规则、参考资料、训练配置、实验记录和最终论文证据。</p></div>
            <div className="project-form card-surface"><label>项目名称<input autoFocus onChange={(event) => setProjectName(event.target.value)} onKeyDown={(event) => event.key === "Enter" && createProject()} placeholder="例如：2026 遥感水体分割挑战赛" value={projectName} /></label><div className="form-grid"><label>项目类型<select defaultValue="竞赛打榜"><option>竞赛打榜</option><option>模型训练</option><option>复现研究</option></select></label><label>研究目标<input defaultValue="建立可复现的高分方案" /></label></div><button className="button primary-button" onClick={createProject} type="button">创建项目并提交规则 <span>→</span></button></div>
            <div className="promise-row"><span>项目隔离</span><span>可审计记录</span><span>人工确认闸门</span></div>
          </section>}

          {stage === "rules" && (
            <section className="step-page">
              <div className="step-header">
                <div>
                  <span className="step-number">02 · RULES INTAKE</span>
                  <h2>提交比赛规则</h2>
                  <p>上传后由本地 Agent 保存原始材料、提取结构化字段并生成可审计的 Markdown 报告。支持 PDF、Markdown、文本、HTML 和公共规则网页。</p>
                </div>
                <span className="step-state">{rulesConfirmed ? "已确认" : ruleReport ? "待人工核对" : "等待材料"}</span>
              </div>
              <div className="rules-layout">
                <div className="card-surface upload-card">
                  <div
                    className={`drop-zone ${isDragging ? "dragging" : ""}`}
                    onDragEnter={() => setIsDragging(true)}
                    onDragLeave={() => setIsDragging(false)}
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={handleDrop}
                  >
                    <input accept=".pdf,.md,.markdown,.txt,.html,.htm" aria-label="上传比赛规则" hidden multiple onChange={handleFileChange} ref={fileInput} type="file" />
                    <span className="upload-icon">↑</span>
                    <h3>拖入规则文件</h3>
                    <p>PDF、Markdown、文本或 HTML</p>
                    <button className="button secondary-button" onClick={() => fileInput.current?.click()} type="button">选择文件</button>
                  </div>
                  <p className="upload-help">扫描图片暂未启用 OCR，不会伪造解析结果；请上传文字版 PDF 或 OCR 后的文本。</p>
                  <div className="or-divider"><span>或</span></div>
                  <label className="url-field">规则网页链接<input onChange={(event) => setRuleUrl(event.target.value)} placeholder="https://..." type="url" value={ruleUrl} /></label>
                  {ruleFiles.length ? (
                    <div className="file-list">
                      {ruleFiles.map((file) => (
                        <div className="file-row" key={file.name}>
                          <span>文档</span><b>{file.name}</b><small>{formatFileSize(file.size)}</small>
                          <button aria-label={`移除 ${file.name}`} onClick={() => setRuleFiles((items) => items.filter((item) => item.name !== file.name))} type="button">×</button>
                        </div>
                      ))}
                    </div>
                  ) : null}
                  <button className="button primary-button wide-button" disabled={ruleParsing} onClick={parseRules} type="button">{ruleParsing ? "正在调用本地 Agent 解析…" : "生成真实规则报告"}</button>
                </div>

                <div className="rule-report card-surface">
                  <div className="report-title">
                    <div><span className="eyebrow">STRUCTURED REPORT</span><h3>规则结构化报告</h3></div>
                    <span className={ruleReport ? "status-chip pending" : "status-chip"}>{rulesConfirmed ? "已确认" : ruleReport ? "待核对" : "提交材料后生成"}</span>
                  </div>
                  {ruleReport ? (
                    <>
                      <p className="rule-source"><b>实际解析来源</b><span>{ruleReport.source?.filename ?? ruleValue(ruleReport.spec, "rule_source", "path")}</span></p>
                      <p className="report-evidence">已记录 {ruleReport.analysis.evidence_count ?? 0} 条字段证据。每次重新导入规则都会重新进入人工确认。</p>
                      <dl>
                        <div><dt>比赛任务</dt><dd>{ruleValue(ruleReport.spec, "competition", "task_type")}</dd></div>
                        <div><dt>数据要求</dt><dd>{ruleValue(ruleReport.spec, "data", "requirements")}</dd></div>
                        <div><dt>评价指标</dt><dd>{ruleValue(ruleReport.spec, "evaluation", "primary_metric")} · {ruleValue(ruleReport.spec, "evaluation", "direction")}</dd></div>
                        <div><dt>提交方式</dt><dd>{ruleValue(ruleReport.spec, "submission", "format")}；{ruleValue(ruleReport.spec, "submission", "filename_rule")}</dd></div>
                        <div><dt>时间节点</dt><dd>{ruleValue(ruleReport.spec, "competition", "deadline")}</dd></div>
                        <div><dt>其他限制</dt><dd>外部数据：{ruleValue(ruleReport.spec, "constraints", "external_data_allowed")}；预训练：{ruleValue(ruleReport.spec, "constraints", "pretrained_models_allowed")}；集成：{ruleValue(ruleReport.spec, "constraints", "ensemble_allowed")}</dd></div>
                      </dl>
                      <details className="rule-markdown">
                        <summary>查看本地生成的完整 Markdown 报告</summary>
                        <pre>{ruleReport.report_markdown}</pre>
                      </details>
                      {ruleReport.readiness.gaps.length ? (
                        <div className="rule-gaps">
                          <b>还不能确认：请补充或重新上传包含以下信息的官方材料</b>
                          <ul>{ruleReport.readiness.gaps.map((gap) => <li key={gap.field}><code>{gap.field}</code>：{gap.reason}</li>)}</ul>
                        </div>
                      ) : (
                        <label className="rule-review-note">
                          <span>人工核对说明</span>
                          <textarea onChange={(event) => setRuleReviewNote(event.target.value)} placeholder="例如：已对照官方规则第 2、4、6 节，确认任务、指标、提交格式与限制无误。" value={ruleReviewNote} />
                        </label>
                      )}
                      <div className="confirm-bar">
                        <span>{ruleReport.readiness.gaps.length ? "当前信息不完整，Agent 不会放行到下一阶段。" : "核对说明会与确认时间一起写入本地项目记录。"}</span>
                        <button className="button primary-button" disabled={ruleParsing || !ruleReviewNote.trim() || ruleReport.readiness.gaps.length > 0} onClick={confirmRules} type="button">确认规则报告</button>
                      </div>
                    </>
                  ) : (
                    <div className="empty-state"><span>02</span><p>提交规则后，这里会显示本地 Agent 的真实解析结果和证据数量。</p></div>
                  )}
                </div>
              </div>
            </section>
          )}

          {false && stage === "rules" && <section className="step-page">
            <div className="step-header"><div><span className="step-number">02 · RULES INTAKE</span><h2>提交比赛规则</h2><p>支持图片、PDF、网页链接和 Markdown。Agent 会整理任务、数据、指标、提交方式、时间节点与限制。</p></div><span className="step-state">{rulesConfirmed ? "已确认" : ruleReportReady ? "待确认" : "等待材料"}</span></div>
            <div className="rules-layout"><div className="card-surface upload-card"><div className={`drop-zone ${isDragging ? "dragging" : ""}`} onDragEnter={() => setIsDragging(true)} onDragLeave={() => setIsDragging(false)} onDragOver={(event) => event.preventDefault()} onDrop={handleDrop}><input accept=".pdf,.md,.markdown,image/*,.txt" aria-label="上传比赛规则" hidden multiple onChange={handleFileChange} ref={fileInput} type="file" /><span className="upload-icon">↑</span><h3>拖入规则文件</h3><p>PDF、图片、Markdown 或文本文件</p><button className="button secondary-button" onClick={() => fileInput.current?.click()} type="button">选择文件</button></div><div className="or-divider"><span>或</span></div><label className="url-field">规则网页链接<input onChange={(event) => setRuleUrl(event.target.value)} placeholder="https://..." type="url" value={ruleUrl} /></label>{ruleFiles.length ? <div className="file-list">{ruleFiles.map((file) => <div className="file-row" key={file.name}><span>文档</span><b>{file.name}</b><small>{formatFileSize(file.size)}</small><button aria-label={`移除 ${file.name}`} onClick={() => setRuleFiles((items) => items.filter((item) => item.name !== file.name))} type="button">×</button></div>)}</div> : null}<button className="button primary-button wide-button" disabled={ruleParsing} onClick={parseRules} type="button">{ruleParsing ? "正在解析规则…" : "让 Agent 生成规则报告"}</button></div>
              <div className="rule-report card-surface"><div className="report-title"><div><span className="eyebrow">STRUCTURED REPORT</span><h3>规则结构化报告</h3></div><span className={ruleReportReady ? "status-chip pending" : "status-chip"}>{ruleReportReady ? "等待确认" : "提交材料后生成"}</span></div>{ruleReportReady ? <><p className="preview-note">前端交互预览：真实接入后，此区域将由上传规则自动生成并标注证据位置。</p><dl><div><dt>比赛任务</dt><dd>待解析 · 将识别任务类型与目标</dd></div><div><dt>数据要求</dt><dd>待解析 · 将识别文件、标注与数据限制</dd></div><div><dt>评价指标</dt><dd>待解析 · 将识别主指标及方向</dd></div><div><dt>提交方式</dt><dd>待解析 · 将识别格式、命名与配额</dd></div><div><dt>时间节点</dt><dd>待解析 · 将识别报名、截止与提交时间</dd></div><div><dt>其他限制</dt><dd>待解析 · 外部数据、预训练、资源与模型限制</dd></div></dl><div className="confirm-bar"><span>确认后将启动多源资料检索</span><button className="button primary-button" onClick={confirmRules} type="button">确认规则报告</button></div></> : <div className="empty-state"><span>02</span><p>提交规则后，报告会在这里逐项呈现。</p></div>}</div></div>
          </section>}

          {stage === "data" && (
            <section className="step-page">
              <div className="step-header">
                <div>
                  <span className="step-number">03 · DATA AUDIT</span>
                  <h2>先审计数据，<em>再设计训练方案。</em></h2>
                  <p>选择本机原始数据目录后，Agent 会在后台计算文件指纹、结构、图像尺寸、标签/掩码概况、重复与质量风险；原始文件不会被修改。</p>
                </div>
                <span className="step-state">{dataAuditJob?.status === "completed" ? "审计完成" : dataAuditRunning ? "正在审计" : "等待数据目录"}</span>
              </div>
              <div className="data-audit-layout">
                <div className="card-surface data-audit-card">
                  <span className="eyebrow">LOCAL DATA SOURCE</span>
                  <h3>原始数据集在哪里？</h3>
                  <label>
                    本机数据目录
                    <input onChange={(event) => setDataDirectory(event.target.value)} placeholder={"例如：B:\\2026xunfei\\train"} value={dataDirectory} />
                  </label>
                  <p>仅支持本机目录。不会读取网络共享，不会上传数据，也不会改动原始文件。</p>
                  <button className="button primary-button" disabled={dataAuditRunning} onClick={() => void startDataAudit()} type="button">
                    {dataAuditRunning ? "正在执行真实审计…" : dataAuditJob ? "重新审计此目录" : "开始真实数据审计"}
                  </button>
                </div>
                <div className="card-surface data-audit-result">
                  <div className="report-title">
                    <div><span className="eyebrow">AUDIT EVIDENCE</span><h3>数据质量与指纹</h3></div>
                    <span className={dataAuditJob?.status === "completed" ? "status-chip ready" : "status-chip"}>{dataAuditJob?.status === "completed" ? "已保存" : dataAuditRunning ? "后台执行中" : "等待开始"}</span>
                  </div>
                  {dataAuditJob?.status === "completed" && dataAuditJob.summary ? (
                    <>
                      <div className="audit-stat-grid">
                        <div><small>文件数</small><b>{dataAuditJob.summary.file_count}</b></div>
                        <div><small>质量问题</small><b>{dataAuditJob.summary.issue_count}</b></div>
                        <div><small>文件类型</small><b>{Object.entries(dataAuditJob.summary.file_kinds).map(([kind, count]) => kind + " " + count).join(" · ") || "无"}</b></div>
                        <div><small>切分提示</small><b>{Object.entries(dataAuditJob.summary.splits).map(([split, count]) => split + " " + count).join(" · ") || "未识别"}</b></div>
                      </div>
                      <p className="audit-fingerprint">数据指纹 · {dataAuditJob.summary.inventory_sha256}</p>
                      <p>已写入：<code>reports/data_statistics.json</code>、<code>reports/data_profile.md</code>、<code>reports/data_quality_issues.csv</code> 和 <code>data/metadata.jsonl</code>。</p>
                    </>
                  ) : dataAuditJob?.status === "failed" ? (
                    <div className="rule-gaps"><b>审计没有被伪装为成功</b><p>{dataAuditJob.error ?? "未返回错误详情。"}</p></div>
                  ) : (
                    <div className="empty-state"><span>03</span><p>输入数据目录并开始审计后，这里会展示真实文件统计、风险和可复现的数据指纹。</p></div>
                  )}
                </div>
              </div>
              {dataAuditJob?.status === "completed" ? (
                <div className="bottom-action ready-action">
                  <span>数据审计已完成，训练框架会绑定这份数据指纹，确保数据改变后不会继续沿用旧结论。</span>
                  <button className="button primary-button" onClick={() => setStage("research")} type="button">进入文献检索 <span>→</span></button>
                </div>
              ) : null}
            </section>
          )}

          {stage === "research" && (
            <section className="step-page">
              <div className="step-header">
                <div>
                  <span className="step-number">04 · RESEARCH RADAR</span>
                  <h2>检索与筛选参考资料</h2>
                  <p>检索会实时调用本地 Agent，从公开论文与代码来源获取记录；每项结果均保留来源、年份、链接和源码入口。</p>
                </div>
                <span className="step-state">{researchStarted ? `已选择 ${selectedReferences.length} 项` : "等待检索"}</span>
              </div>
              <div className="research-toolbar card-surface">
                <label>
                  检索主题
                  <input onChange={(event) => setResearchQuery(event.target.value)} onKeyDown={(event) => event.key === "Enter" && void startResearch()} placeholder="例如：remote sensing water segmentation boundary loss" value={researchQuery} />
                </label>
                <button className="button primary-button" disabled={researchSearching} onClick={() => void startResearch()} type="button">{researchSearching ? "正在检索公开来源…" : "开始真实多源检索"}</button>
              </div>
              {researchStarted ? (
                <>
                  {Object.keys(researchFailures).length ? (
                    <div className="research-failures card-surface">
                      <b>部分来源本次未返回结果</b>
                      <ul>{Object.entries(researchFailures).map(([source, reason]) => <li key={source}><code>{source}</code>：{reason}</li>)}</ul>
                    </div>
                  ) : null}
                  {researchCards?.length ? (
                    <>
                      <div className="research-real-note">以下为本次真实检索并已保存到项目 `research/papers.json` 的公开记录。带“提供源码入口”的条目可在你确认后进入可审计的复现审查。</div>
                      <div className="research-list">
                        {researchCards.map((paper) => {
                          const selected = selectedReferences.includes(paper.id);
                          return (
                            <article className={`research-card ${selected ? "selected" : ""}`} key={paper.id}>
                              <button aria-label={selected ? `取消采用 ${paper.title}` : `采用 ${paper.title}`} className="reference-toggle" onClick={() => toggleReference(paper.id)} type="button">{selected ? "✓" : ""}</button>
                              <div className="paper-main">
                                <div className="paper-meta"><span>{paper.tag}</span><small>{paper.date}</small></div>
                                <h3>{paper.title}</h3>
                                <p>{paper.takeaway}</p>
                                <div className="paper-foot">
                                  <span>{paper.source}</span>
                                  <b>{paper.code}</b>
                                  <span className="paper-links">{paper.url ? <a href={paper.url} rel="noreferrer" target="_blank">原文</a> : null}{paper.codeUrl ? <a href={paper.codeUrl} rel="noreferrer" target="_blank">源码</a> : null}</span>
                                </div>
                              </div>
                            </article>
                          );
                        })}
                      </div>
                      <div className="bottom-action">
                        <span>确认后会固化本次采用范围；真正的下载、克隆和执行仍需在下一阶段单独确认。</span>
                        <button className="button primary-button" disabled={!selectedReferences.length} onClick={confirmReferences} type="button">确认 {selectedReferences.length} 项参考资料 <span>→</span></button>
                      </div>
                    </>
                  ) : (
                    <div className="research-empty card-surface"><span>本次无可用结果</span><h3>没有伪造候选资料。</h3><p>请尝试更具体的英文关键词，或稍后重新检索；上方会列出发生故障的公开来源。</p></div>
                  )}
                </>
              ) : (
                <div className="research-empty card-surface"><span>多源检索</span><h3>从真实公开来源开始。</h3><p>输入研究主题后，Agent 会将检索结果和来源故障情况保存到本地工作区。</p></div>
              )}
            </section>
          )}

          {false && stage === "research" && <section className="step-page">
            <div className="step-header"><div><span className="step-number">04 · RESEARCH RADAR</span><h2>检索与筛选参考资料</h2><p>默认纳入所有候选资料；你可以取消不希望采用的论文或开源项目，再确认研究范围。</p></div><span className="step-state">已选择 {selectedReferences.length} 项</span></div>
            <div className="research-toolbar card-surface"><label>检索主题<input defaultValue={`${projectName || "当前比赛"} · 模型、训练策略、分割方法`} /></label><button className="button primary-button" onClick={startResearch} type="button">开始多源检索</button></div>
            {researchStarted ? <><div className="preview-banner">当前为前端检索交互预览；接入真实服务后将显示实际检索来源、发表时间、代码地址与 Agent 评价。</div><div className="research-list">{researchPreview.map((paper) => { const selected = selectedReferences.includes(paper.id); return <article className={`research-card ${selected ? "selected" : ""}`} key={paper.id}><button aria-label={selected ? `取消采用 ${paper.title}` : `采用 ${paper.title}`} className="reference-toggle" onClick={() => toggleReference(paper.id)} type="button">{selected ? "✓" : ""}</button><div className="paper-main"><div className="paper-meta"><span>{paper.tag}</span><small>{paper.date}</small></div><h3>{paper.title}</h3><p>{paper.takeaway}</p><div className="paper-foot"><span>{paper.source}</span><b>{paper.code}</b></div></div></article>; })}</div><div className="bottom-action"><span>确认后，Agent 会按顺序下载论文与源码并记录可借鉴方法。</span><button className="button primary-button" onClick={confirmReferences} type="button">确认 {selectedReferences.length} 项参考资料 <span>→</span></button></div></> : <div className="research-empty card-surface"><span>多源检索</span><h3>从论文、技术报告与开源社区开始。</h3><p>点击“开始多源检索”后，结果会按可借鉴之处、来源、时间和源码可用性展示。</p></div>}
          </section>}

          {stage === "materials" && <section className="step-page">

            <div className="step-header">
              <div>
                <span className="step-number">05 · MATERIAL ANALYSIS</span>
                <h2>下载、阅读并提炼可用方法</h2>
                <p>只处理你确认的公开资料。论文会保存为证据；公开源码仅做静态检查，不会被自动执行。</p>
              </div>
              <span className="step-state">已处理 {materialResolvedCount} / {chosenReferences.length}</span>
            </div>
            <div className="analysis-board card-surface">
              <div className="analysis-top">
                <div>
                  <span className="eyebrow">ANALYSIS QUEUE</span>
                  <h3>资料分析队列</h3>
                  {materialJobId ? <small className="material-job">后台任务 · {materialJobId}</small> : null}
                </div>
                <button className="button primary-button" disabled={materialsRunning} onClick={startMaterialAnalysis} type="button">
                  {materialsRunning ? "后台正在处理…" : materialJobId ? "重新下载与分析" : "开始下载与分析"}
                </button>
              </div>
              <p className="material-safety">只下载公开 PDF；若条目提供仓库链接，将克隆到本地供静态审查。不会安装依赖、运行脚本或启动训练。</p>
              {chosenReferences.map((paper) => {
                const state = materialStates[paper.id] ?? "queued";
                const statusText = state === "queued"
                  ? "等待开始"
                  : state === "downloading"
                    ? "后台正在下载或静态检查"
                    : state === "reading"
                      ? "正在提炼方法"
                      : state === "failed"
                        ? "处理失败，需人工查看原因"
                        : "结果已记录";
                const detail = materialDetails[paper.id];
                return (
                  <div className="analysis-row" key={paper.id}>
                    <span className={`analysis-status ${state}`} />
                    <div>
                      <b>{paper.title}</b>
                      <small>{statusText}{detail ? ` · ${detail}` : ""}</small>
                    </div>
                    <p>{state === "failed" ? "此条目没有被伪装成已完成；请根据失败原因重试或取消采用。" : state === "ready" ? "论文/源码处理状态已写入项目记录。" : paper.tag}</p>
                  </div>
                );
              })}
            </div>
            {materialResolvedCount === chosenReferences.length && chosenReferences.length && !materialsRunning ? (
              <div className="bottom-action ready-action">
                <span>{selectedMaterialCount === chosenReferences.length ? "所有选中资料均已写入分析记录。" : "资料任务已结束；可继续构建，也可以先处理失败条目。"}</span>
                <button className="button primary-button" onClick={() => setStage("build")} type="button">进入模型构建 <span>→</span></button>
              </div>
            ) : null}
          </section>}
          {stage === "build" && <section className="step-page">
            <div className="step-header"><div><span className="step-number">06 · TRAINING FOUNDATION</span><h2>构建模型与完整训练框架</h2><p>模型实现、训练配置、数据版本、实验账本、日志和结果诊断会在同一项目内保持可追溯。</p></div><span className="step-state">{trainingProgress === 100 ? "框架已就绪" : "等待启动"}</span></div>
            <div className="build-layout">
              <div className="build-card card-surface">
                <span className="eyebrow">EVIDENCE-BACKED BUILD</span>
                <h3>{trainingBuilding ? activity : trainingScaffold ? `训练骨架 ${trainingScaffold.build_id} 已落盘` : "准备生成训练工程"}</h3>
                <div className="progress-track"><i style={{ width: `${trainingProgress}%` }} /></div>
                <div className="progress-copy">
                  <b>{trainingProgress}%</b>
                  <span>{trainingScaffold ? "已写入配置与审计报告；不会自动启动训练" : "只生成可审查的训练工程，不会自动启动耗时训练"}</span>
                </div>
                <button className="button primary-button" disabled={trainingBuilding} onClick={startBuild} type="button">
                  {trainingBuilding ? "正在生成真实训练骨架…" : trainingStarted ? "重新生成训练骨架" : "生成模型与训练框架"}
                </button>
              </div>
              <div className="build-plan">
                <article><span>01</span><div><b>模型与损失</b><p>由已实现的任务适配器生成可审查的初始模型配置。</p></div></article>
                <article><span>02</span><div><b>训练与验证</b><p>绑定数据审计指纹、随机种子、验证指标与基础优化器。</p></div></article>
                <article><span>03</span><div><b>实验账本</b><p>生成构建记录；真实训练仍须通过规则、数据和资源门禁。</p></div></article>
                <article><span>04</span><div><b>论文证据</b><p>后续只从真实实验记录生成图表、表格与 TeX 草稿。</p></div></article>
              </div>
            </div>
            {trainingScaffold ? (
              <div className="bottom-action ready-action scaffold-result">
                <div>
                  <span>真实构建记录 · {trainingScaffold.build_id} · {trainingScaffold.runner}</span>
                  <strong>{trainingScaffold.status === "ready_for_environment_review" ? "训练骨架已就绪，等待环境审核" : "训练骨架已生成，等待补全数据映射"}</strong>
                  <small>配置：{trainingScaffold.config_path}；报告：{trainingScaffold.report_path}；数据指纹：{trainingScaffold.data_audit.inventory_sha256.slice(0, 12)}…</small>
                  {trainingScaffold.blockers.length ? <ul className="scaffold-blockers">{trainingScaffold.blockers.map((item) => <li key={item}>{item}</li>)}</ul> : null}
                </div>
                {trainingScaffold.status === "ready_for_environment_review" ? (
                  <button className="button primary-button" onClick={() => setStage("environment")} type="button">确认训练部署方案 <span>→</span></button>
                ) : null}
              </div>
            ) : null}
          </section>}

          {stage === "environment" && <section className="step-page">
            <div className="step-header"><div><span className="step-number">07 · TRAINING DEPLOYMENT</span><h2>确认训练位置，<em>再启动真实训练。</em></h2><p>先选择本机或服务器，再确定 Conda 环境和 GPU 容量。Agent 会保留资源判断依据，并在本机不满足要求时明确建议切换服务器。</p></div><span className="step-state">{deploymentConfirmed ? "方案已确认" : "等待资源评估"}</span></div>
            <div className="deployment-layout">
              <div className="deployment-card card-surface">
                <div className="deployment-section-head"><div><span className="eyebrow">TRAINING TARGET</span><h3>训练跑在哪里？</h3></div><span>不会自动启动训练</span></div>
                <div className="target-toggle" role="radiogroup" aria-label="训练位置"><button aria-checked={trainingTarget === "local"} className={trainingTarget === "local" ? "selected" : ""} onClick={() => { setTrainingTarget("local"); setEnvironmentAssessment(null); }} role="radio" type="button"><b>本机训练</b><small>直接使用当前设备的 GPU 与 Conda</small></button><button aria-checked={trainingTarget === "server"} className={trainingTarget === "server" ? "selected" : ""} onClick={() => { setTrainingTarget("server"); setEnvironmentAssessment(null); }} role="radio" type="button"><b>服务器训练</b><small>通过 SSH 连接远程 Linux / GPU 服务器</small></button></div>
                {trainingTarget === "server" ? <div className="server-fields"><label>服务器地址<input onChange={(event) => setServerHost(event.target.value)} placeholder="gpu.example.com 或 10.0.0.8" value={serverHost} /></label><div className="form-grid"><label>SSH 端口<input inputMode="numeric" onChange={(event) => setServerPort(event.target.value)} value={serverPort} /></label><label>登录用户<input onChange={(event) => setServerUser(event.target.value)} placeholder="ubuntu" value={serverUser} /></label></div><div className="auth-choice"><button className={serverAuth === "key" ? "active" : ""} onClick={() => setServerAuth("key")} type="button">SSH 密钥</button><button className={serverAuth === "password" ? "active" : ""} onClick={() => setServerAuth("password")} type="button">密码</button></div><label>{serverAuth === "key" ? "私钥路径或凭据标识" : "服务器密码"}<input autoComplete="off" onChange={(event) => setServerCredential(event.target.value)} placeholder={serverAuth === "key" ? "例如：~/.ssh/competition_gpu" : "仅用于本次安全连接"} type={serverAuth === "key" ? "text" : "password"} value={serverCredential} /></label><p className="secret-note">连接信息仅用于发起真实 SSH 探测；密码和私钥不会写入实验账本或项目文档。</p></div> : <div className="local-note"><b>本机优先</b><p>真实接入后，Agent 会读取当前 Conda、CUDA、GPU 型号、总显存与可用显存，不会依据猜测启动训练。</p></div>}
              </div>
              <div className="deployment-card card-surface">
                <div className="deployment-section-head"><div><span className="eyebrow">PYTHON RUNTIME</span><h3>Conda 环境怎么准备？</h3></div></div>
                <div className="conda-choice"><button className={condaStrategy === "existing" ? "active" : ""} onClick={() => setCondaStrategy("existing")} type="button"><b>使用已有环境</b><small>复用已验证的 Conda 依赖</small></button><button className={condaStrategy === "new" ? "active" : ""} onClick={() => setCondaStrategy("new")} type="button"><b>新建环境</b><small>为当前项目隔离依赖与版本</small></button></div><label>{condaStrategy === "existing" ? "现有 Conda 环境名称" : "新 Conda 环境名称"}<input onChange={(event) => setCondaEnvironment(event.target.value)} placeholder={condaStrategy === "existing" ? "例如：AIC" : "例如：competition-2026"} value={condaEnvironment} /></label>{condaStrategy === "new" ? <div className="runtime-tags"><span>Python 3.11</span><span>PyTorch + CUDA</span><span>项目锁定依赖</span></div> : <p className="runtime-copy">Agent 会在真实探测中核对 Python、PyTorch、CUDA、驱动与核心依赖是否兼容当前训练框架。</p>}</div>
              <div className="resource-card card-surface runtime-resource-card">
                <div className="deployment-section-head">
                  <div><span className="eyebrow">GPU CAPACITY</span><h3>用真实显存决定是否值得本机跑</h3></div>
                  <button className="button secondary-button" disabled={probeState === "checking"} onClick={probeEnvironment} type="button">
                    {probeState === "checking" ? "正在真实探测…" : trainingTarget === "local" ? "检测本机资源" : "连接并检测服务器"}
                  </button>
                </div>
                <p className="resource-copy">点击检测会调用本地 Agent：本机读取 Conda 与 nvidia-smi；服务器仅通过 SSH 私钥运行只读命令。不会创建环境、安装依赖或启动训练。</p>
                {trainingTarget === "server" ? <p className="secret-note">真实服务器探测仅支持本机 SSH 私钥，并要求该服务器主机指纹已在 OpenSSH 中验证；密码不会上传或保存。</p> : null}
                <div className="resource-inputs">
                  <label>实际可用 GPU 显存（GB）<input inputMode="decimal" min="1" onChange={(event) => setAvailableVram(event.target.value)} placeholder="检测后自动填入" type="number" value={availableVram} /></label>
                  <label>预估最低显存（GB）<input inputMode="decimal" min="1" onChange={(event) => setRequiredVram(event.target.value)} type="number" value={requiredVram} /></label>
                </div>
                <div className="resource-action">
                  <span>{runtimeProbe ? `已保存真实探测 ${runtimeProbe.probe_id}；下方判断使用该次检测结果。 ` : "也可手动录入显存，仅生成预估建议。"} </span>
                  <button className="button primary-button" onClick={evaluateEnvironment} type="button">按录入值预估</button>
                </div>
                {runtimeProbe ? (
                  <div className="runtime-proof">
                    <span>真实探测 · {runtimeProbe.probe_id}</span>
                    <b>{runtimeProbe.assessment.gpu_name ?? "未发现 NVIDIA GPU"}</b>
                    <small>{runtimeProbe.runtime.platform} · Python {runtimeProbe.runtime.python}</small>
                    <small>可用 {runtimeProbe.assessment.available_vram_gb} GB / 总计 {runtimeProbe.assessment.total_vram_gb} GB · 建议至少 {runtimeProbe.assessment.recommended_vram_gb} GB · 推荐 batch size {runtimeProbe.assessment.recommended_batch_size}</small>
                    <small>Conda：{runtimeProbe.environment.status}。{runtimeProbe.environment.note}</small>
                  </div>
                ) : null}
              </div>
              <div className="resource-card card-surface"><div className="deployment-section-head"><div><span className="eyebrow">GPU CAPACITY</span><h3>用显存决定是否值得本机跑</h3></div><button className="button secondary-button" disabled={probeState === "checking"} onClick={probeEnvironment} type="button">{probeState === "checking" ? "正在检测…" : trainingTarget === "local" ? "检测本机资源" : "连接并检测服务器"}</button></div><p className="resource-copy">正式接入后会自动读取 GPU 总显存与空闲显存；当前原型不虚构硬件数据，可先手动录入实际可用显存演示决策。</p><div className="resource-inputs"><label>可用 GPU 显存（GB）<input inputMode="decimal" min="1" onChange={(event) => setAvailableVram(event.target.value)} placeholder="例如：16" type="number" value={availableVram} /></label><label>预估最低显存（GB）<input inputMode="decimal" min="1" onChange={(event) => setRequiredVram(event.target.value)} type="number" value={requiredVram} /></label></div><div className="resource-action"><span>{probeState === "ready" ? "检测动作已准备好，可录入结果并评估。" : "填写后会为训练预留 20% 的运行余量。"}</span><button className="button primary-button" onClick={evaluateEnvironment} type="button">生成训练建议</button></div></div>
            </div>
            {environmentAssessment ? <div className={`assessment-card ${environmentAssessment.status}`}><div><span className="assessment-mark">{environmentAssessment.status === "local-ready" || environmentAssessment.status === "server-ready" ? "✓" : "!"}</span><div><span className="eyebrow">RESOURCE DECISION</span><h3>{environmentAssessment.title}</h3></div></div><p>{environmentAssessment.reason}</p><strong>{environmentAssessment.recommendation}</strong>{environmentAssessment.status === "server-needed" ? <button className="button primary-button" onClick={() => { setTrainingTarget("server"); setEnvironmentAssessment(null); }} type="button">切换到服务器训练</button> : <button className="button primary-button" onClick={confirmDeploymentPlan} type="button">{deploymentConfirmed ? "训练方案已确认" : "确认训练方案"}</button>}</div> : null}
          </section>}
        </div>
      </section>
    </main>
  );
}

export default function Home() {
  return <CompetitionWorkspace />;
}

function LegacyDashboard() {
  const [activeNav, setActiveNav] = useState("总览");
  const [selectedId, setSelectedId] = useState("OFFLINE");
  const [approved, setApproved] = useState(false);
  const [draftOpen, setDraftOpen] = useState(false);
  const [draftHypothesis, setDraftHypothesis] = useState("增加边界辅助监督能够改善细长水体的分割质量。");
  const [notice, setNotice] = useState("");
  const [dashboard, setDashboard] = useState<DashboardSnapshot | null>(null);
  const [connection, setConnection] = useState<"connecting" | "live" | "offline">("connecting");

  const apiBase = (process.env.NEXT_PUBLIC_COMPETITION_API_URL ?? "").replace(/\/$/, "");

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${apiBase}/api/dashboard`, { signal: controller.signal })
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error("Dashboard API unavailable"))))
      .then((payload: DashboardSnapshot) => {
        setDashboard(payload);
        setConnection("live");
      })
      .catch(() => setConnection("offline"));
    return () => controller.abort();
  }, [apiBase]);

  const runs = useMemo<Run[]>(() => {
    if (!dashboard) return [offlineRun];
    if (!dashboard.experiments.length) {
      return [{ ...offlineRun, id: "NO-RESULTS", name: "No recorded competition experiment", change: "Awaiting first approved run", detail: "No real results are available in this competition workspace." }];
    }
    return dashboard.experiments.map((item) => ({
      id: item.id,
      name: item.change_type ?? item.hypothesis ?? "Recorded experiment",
      metric: item.metric === null ? "—" : item.metric.toFixed(4),
      change: item.decision ?? item.status,
      state: item.status === "completed" ? "accepted" : item.status === "running" ? "running" : "planned",
      detail: item.best_epoch ? `best epoch ${item.best_epoch} · ${item.runtime_seconds ?? 0}s` : item.hypothesis ?? "Awaiting recorded configuration",
    }));
  }, [dashboard]);

  const bestMetric = dashboard?.summary.best?.metric.toFixed(4) ?? "—";
  const bestId = dashboard?.summary.best?.experiment_id ?? "No recorded result";
  const completedRuns = dashboard ? String(dashboard.summary.completed_experiments).padStart(2, "0") : "—";
  const rulesLabel = dashboard?.competition.requires_human_confirmation ? "规则待确认" : "规则已确认";
  const workflowStage = dashboard?.workflow?.stage ?? "local API required";
  const workflowBlockers = dashboard?.workflow?.blockers ?? ["Connect the local API to inspect live workflow gates."];
  const adapters = dashboard?.capabilities?.runners ?? [];
  const topProposal = dashboard?.proposals?.[0] ?? null;
  const ruleGaps = dashboard?.competition.rule_readiness?.gaps ?? [];
  const curve = useMemo(
    () => (dashboard?.summary.best?.history ?? [])
      .map((item) => item.val_global_iou ?? item.val_iou ?? item.validation_metric ?? item.metric)
      .filter((value): value is number => typeof value === "number" && Number.isFinite(value)),
    [dashboard?.summary.best?.history],
  );
  const curveCeiling = Math.max(...curve, 1);

  const selectedRun = useMemo(
    () => runs.find((run) => run.id === selectedId) ?? runs[0],
    [selectedId, runs],
  );

  function selectNav(item: string) {
    setActiveNav(item);
    setNotice(item + " 视图已就绪，真实工作区数据接入后会在此展开。");
  }

  function approve() {
    if (!topProposal) {
      setNotice("尚无基于真实结果的候选方案可批准。");
      return;
    }
    setApproved(true);
    if (connection === "live") {
      void fetch(`${apiBase}/api/decisions/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ experiment_id: topProposal.proposal_id, approved_by: "research-lead" }),
      });
      setNotice("批准已写入本地审计台账；训练仍需人工手动启动。");
    } else {
      setNotice("本地工作区尚未连接；不会创建演示批准记录。");
    }
  }

  async function createDraft() {
    setDraftOpen(false);
    if (connection !== "live") {
      setNotice("本地工作区尚未连接；草案没有被保存。启动 API 后可保存为可审计草稿。");
      return;
    }
    try {
      const response = await fetch(`${apiBase}/api/experiments/drafts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hypothesis: draftHypothesis, parent_experiment_id: bestId, estimated_gpu_hours: 5 }),
      });
      const payload = await response.json();
      setNotice(response.ok ? `${payload.draft_id} 已保存，等待人工批准。` : payload.error ?? "草案保存失败。");
    } catch {
      setNotice("无法连接本地 API，草案未保存。");
    }
  }

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">YJ</span>
          <span>
            <b>You Just Lead</b>
            <small>COMPETITION OS</small>
          </span>
        </div>

        <div className="workspace-picker">
          <span className="label">当前工作区</span>
          <button type="button">
            <i>WS</i>
            <span><b>Water Segmentation</b><small>Research workspace</small></span>
            <strong>⌄</strong>
          </button>
        </div>

        <nav aria-label="主导航">
          {navigation.map((item, index) => (
            <button
              className={activeNav === item ? "nav-item active" : "nav-item"}
              key={item}
              onClick={() => selectNav(item)}
              type="button"
            >
              <i>{String(index + 1).padStart(2, "0")}</i>
              {item}
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <span className="healthy"><i /> {connection === "live" ? "Local API connected" : "Local API offline"}</span>
          <p>每个动作都保留证据、版本与审批轨迹。</p>
          <button className="user" type="button">
            <i>CL</i>
            <span><b>Research lead</b><small>Owner access</small></span>
          </button>
        </div>
      </aside>

      <section className="main-column">
        <header className="topbar">
          <div className="breadcrumbs"><span>竞赛指挥中心</span><i>／</i><b>{activeNav}</b></div>
          <div className="top-actions">
            <span className="sync"><i /> {connection === "live" ? "已连接本地工作区" : connection === "connecting" ? "正在连接工作区" : "未连接本地工作区"}</span>
            <button className="quiet" type="button">{rulesLabel}</button>
            <button className="primary" onClick={() => setDraftOpen(true)} type="button">
              <b>＋</b> 新建实验
            </button>
          </div>
        </header>

        <div className="content">
          {notice && (
            <button className="notice" onClick={() => setNotice("")} type="button">
              <span>已更新</span>{notice}<b>×</b>
            </button>
          )}

          {connection === "offline" && (
            <div className="offline-banner" role="status">
              离线视图不会展示模拟分数或虚构实验。设置 <code>NEXT_PUBLIC_COMPETITION_API_URL</code> 指向本地 API，即可查看真实记录。
            </div>
          )}

          <section className="hero">
            <div>
              <span className="label warm">EVIDENCE-LED COMPETITION WORKFLOW</span>
              <h1>把每一轮实验，<em>变成下一步的依据。</em></h1>
              <p>从规则、数据到训练曲线与最终论文，让研究决策始终建立在可复现的证据之上；系统不会把演示数据当作真实成绩。</p>
            </div>
            <div aria-hidden="true" className="orbit">
              <i className="ring first" /><i className="ring second" />
              <i className="node one" /><i className="node two" /><i className="node three" />
              <b>{bestMetric}</b><small>BEST RECORDED SCORE</small>
            </div>
          </section>

          <section className="metrics" aria-label="关键指标">
            <article><span>当前最佳分数</span><strong>{bestMetric}</strong><small className={dashboard?.summary.best ? "positive" : "warm-text"}>{dashboard?.summary.best ? `${bestId} · 已记录证据` : "尚无真实训练结果"}</small></article>
            <article><span>已完成真实实验</span><strong>{completedRuns}</strong><small>{dashboard ? "来自当前赛题工作区" : "等待本地 API"}</small></article>
            <article><span>数据审计文件</span><strong>{dashboard ? dashboard.summary.data_files.toLocaleString() : "—"}</strong><small className={dashboard?.summary.data_issues ? "warm-text" : "positive"}>{dashboard ? `${dashboard.summary.data_issues} 个审计问题` : "未读取"}</small></article>
            <article><span>规则复核缺口</span><strong>{dashboard ? String(ruleGaps.length).padStart(2, "0") : "—"}</strong><small className={dashboard?.competition.requires_human_confirmation ? "warm-text" : "positive"}>{dashboard?.competition.requires_human_confirmation ? "仍阻止真实训练" : "训练门槛已解除"}</small></article>
          </section>

          <section className="grid primary-grid">
            <article className="panel chart-panel">
              <div className="panel-head">
                <div><span className="label">MODEL SIGNAL</span><h2>真实验证性能轨迹</h2></div>
                <div className="legend"><span><i /> {dashboard?.competition.metric ?? "Validation metric"}</span></div>
              </div>
              <div className="chart">
                {curve.length ? <>
                  <div className="axis"><span>{curveCeiling.toFixed(2)}</span><span>0</span></div>
                  <div className="bars">
                    {curve.map((value, index) => <span className={index === curve.length - 1 ? "bar latest" : "bar"} key={`${index}-${value}`} style={{ height: `${Math.max(6, value / curveCeiling * 100)}%` }}><i /></span>)}
                    <div className="chart-callout"><span>BEST</span><b>{bestMetric}</b><small>{bestId} · tracked run</small></div>
                  </div>
                </> : <div className="empty-plot">尚无已完成的真实训练曲线。规则批准与 GPU 运行批准后，首个 fold 的曲线会自动进入这里。</div>}
              </div>
              {curve.length ? <div className="axis-bottom"><span>first epoch</span><span>latest epoch</span></div> : null}
            </article>

            <article className="panel decision">
              <div className="panel-head">
                <div><span className="label">NEXT SAFE MOVE</span><h2>{dashboard?.competition.requires_human_confirmation ? "规则复核清单" : "下一步实验建议"}</h2></div>
                <span className="confidence">evidence gated</span>
              </div>
              <p className="quote"><i>“</i>{dashboard?.competition.requires_human_confirmation ? "真实训练保持锁定，直到每个关键规则都有官方证据。" : topProposal?.hypothesis ?? "尚未形成可依据实验结果的下一步建议。"}</p>
              <div className="evidence">
                {dashboard?.competition.requires_human_confirmation ? ruleGaps.slice(0, 3).map((gap, index) => (
                  <p key={gap.field}><i>{String(index + 1).padStart(2, "0")}</i><span><b>{gap.field}</b> {gap.reason}</span></p>
                )) : topProposal ? topProposal.evidence.slice(0, 3).map((item, index) => (
                  <p key={item.source}><i>{String(index + 1).padStart(2, "0")}</i><span><b>{item.source}</b> {item.detail}</span></p>
                )) : <p><i>01</i><span><b>状态</b> 等待首个真实结果。</span></p>}
              </div>
              <div className="decision-meta">
                <span><b>{dashboard?.competition.requires_human_confirmation ? "完整缺口" : topProposal ? "优先级得分" : "状态"}</b>{dashboard?.competition.requires_human_confirmation ? `${ruleGaps.length} 项` : topProposal ? topProposal.priority_score.toFixed(4) : "等待首个真实结果"}</span>
                <span><b>{dashboard?.competition.requires_human_confirmation ? "检查命令" : topProposal ? "变更类型" : "训练"}</b>{dashboard?.competition.requires_human_confirmation ? "rules-readiness" : topProposal ? topProposal.change_type.replaceAll("_", " ") : "尚未批准"}</span>
              </div>
              {topProposal && !dashboard?.competition.requires_human_confirmation ? <button className={approved ? "approved" : "approve"} onClick={approve} type="button">{approved ? "✓ 已批准 · 等待调度" : `批准 ${topProposal.proposal_id}`}</button> : null}
            </article>
          </section>

          <section className="grid lower-grid">
            <article className="panel ledger">
              <div className="panel-head">
                <div><span className="label">EXPERIMENT LEDGER</span><h2>当前赛题实验账本</h2></div>
                <button className="text-button" onClick={() => selectNav("实验台账")} type="button">查看全部 →</button>
              </div>
              <div className="run-list">
                {runs.map((run) => (
                  <button className={selectedId === run.id ? "run active" : "run"} key={run.id} onClick={() => setSelectedId(run.id)} type="button">
                    <i className={run.state} />
                    <span className="run-name"><b>{run.id}</b><small>{run.name}</small></span>
                    <span className="run-detail">{run.detail}</span>
                    <span className="run-score"><b>{run.metric}</b><small>{run.change}</small></span>
                    <em>→</em>
                  </button>
                ))}
              </div>
              <div className="selected-run"><span>已选择</span><b>{selectedRun.id}</b><p>{selectedRun.detail}</p><button onClick={() => setNotice(selectedRun.id === "OFFLINE" || selectedRun.id === "NO-RESULTS" ? "没有可打开的真实实验卡片。" : selectedRun.id + " 的完整证据卡片已准备好。")} type="button">打开证据卡</button></div>
            </article>

            <article className="panel protocol">
              <div className="panel-head">
                <div><span className="label">RESEARCH PROTOCOL</span><h2>现在的节奏</h2></div>
                <span className="live"><i /> {connection === "live" ? "live" : "offline"}</span>
              </div>
              <ol>
                <li className={dashboard && !dashboard.competition.requires_human_confirmation ? "done" : "current"}><i>{dashboard && !dashboard.competition.requires_human_confirmation ? "✓" : "01"}</i><span><b>确认官方规则</b><small>{dashboard && !dashboard.competition.requires_human_confirmation ? "已记录可审计规则证据" : "完成规则字段与官方锚点复核"}</small></span></li>
                <li className={dashboard?.summary.data_files ? "done" : ""}><i>{dashboard?.summary.data_files ? "✓" : "02"}</i><span><b>数据审计</b><small>{dashboard?.summary.data_files ? "数据指纹和质量报告已生成" : "等待读取真实工作区"}</small></span></li>
                <li className={dashboard?.summary.completed_experiments ? "done" : dashboard && !dashboard.competition.requires_human_confirmation ? "current" : ""}><i>{dashboard?.summary.completed_experiments ? "✓" : "03"}</i><span><b>运行可复现基线</b><small>{dashboard?.summary.completed_experiments ? "曲线和结果已进入账本" : "需规则与精确 GPU 批准"}</small></span></li>
                <li><i>04</i><span><b>生成候选提交与论文</b><small>仅由真实实验记录生成</small></span></li>
              </ol>
              <div className="lead-note"><i>⌁</i><p><b>Lead, don’t micromanage.</b><br />系统记录证据，你专注研究方向。</p></div>
            </article>
          </section>

          <section className="capability-grid" aria-label="Workflow status and task adapters">
            <article className="panel workflow-card">
              <div className="panel-head">
                <div><span className="label">WORKFLOW STATE</span><h2>Live operating gate</h2></div>
                <span className={connection === "live" ? "state-chip live-state" : "state-chip"}>{connection === "live" ? "live" : "offline"}</span>
              </div>
              <div className="workflow-body">
                <span>Current stage</span>
                <strong>{workflowStage.replaceAll("_", " ")}</strong>
                <p>{connection === "live" ? "The next move is derived from recorded rules, data and experiment evidence." : "Start the local API to read the current workspace; no preview results are shown offline."}</p>
                <ul>
                  {workflowBlockers.slice(0, 2).map((blocker) => <li key={blocker}>{blocker}</li>)}
                </ul>
              </div>
            </article>

            <article className="panel adapter-card">
              <div className="panel-head">
                <div><span className="label">TRAINING CAPABILITIES</span><h2>Task-ready baselines</h2></div>
                <span className="adapter-count">{adapters.filter((adapter) => adapter.runner !== "synthetic_binary_classification").length} adapters</span>
              </div>
              <div className="adapter-list">
                {adapters.filter((adapter) => adapter.runner !== "synthetic_binary_classification").map((adapter) => (
                  <div className="adapter-row" key={adapter.runner}>
                    <span>{adapter.kind.replaceAll("_", " ")}</span>
                    <b>{adapter.runner.replaceAll("_", " ")}</b>
                    <small>{adapter.data_contract}</small>
                  </div>
                ))}
              </div>
            </article>
          </section>
        </div>
      </section>

      {draftOpen && (
        <div className="modal-layer" role="presentation">
          <section aria-modal="true" className="modal" role="dialog">
            <button aria-label="关闭" className="close" onClick={() => setDraftOpen(false)} type="button">×</button>
            <span className="label warm">NEW EXPERIMENT</span>
            <h2>从一个清晰假设开始。</h2>
            <p>系统会在执行前冻结配置、数据版本、Git 状态与预算估计。</p>
            <label>实验假设<textarea value={draftHypothesis} onChange={(event) => setDraftHypothesis(event.target.value)} /></label>
            <div className="modal-meta"><span>父实验 <b>EXP-0002</b></span><span>预估 <b>5 GPU h</b></span></div>
            <button className="primary wide" onClick={createDraft} type="button">创建实验草案</button>
          </section>
        </div>
      )}
    </main>
  );
}
