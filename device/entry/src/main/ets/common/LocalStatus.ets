/**
 * 端侧离线状态：后端不在时，工作区里的状态仍然看得见。
 *
 * 原则是「把**状态读取**端侧化，把**重计算**执行器化」：
 * - 读工作区文件就能得到的（数据审计摘要、实验历史、账本事件、论文证据）在端侧投影出来；
 * - 需要算力或外部资源的（检索、大模型、训练、重型数据审计）端侧不假装能做，
 *   由界面标成「需要外部执行器」。
 *
 * 字段名逐条对齐 Python 侧的真实产物，不另立一套，也不在这里做任何判断（就绪度、
 * 通过与否都由各自的模块负责）：
 * - `reports/data_statistics.json` ← `agents/data_agent.py::audit_dataset`
 * - `experiments/manifests/EXP-*.json` ← `schemas/experiment.py::ExperimentManifest`
 * - `experiments/results/EXP-*.json` ← `schemas/experiment.py::ExperimentResult`
 * - `paper/generated/evidence_map.json` ← `paper/generator.py::generate_paper_package`
 * - `ledger.jsonl` ← `common/LocalLedger.ets`（字段与 `workflow_events` 对齐）
 */

import { LedgerEvent, eventCount, readEvents } from './LocalLedger';
import { LocalWorkspace } from './LocalWorkspace';

const DATA_STATISTICS_FILE: string = 'reports/data_statistics.json';
const MANIFEST_DIR: string = 'experiments/manifests';
const RESULT_DIR: string = 'experiments/results';
const EVIDENCE_MAP_FILE: string = 'paper/generated/evidence_map.json';

/** `reports/data_statistics.json` 里用到的部分。 */
interface DatasetStatisticsFile {
  file_count: number;
  issue_count: number;
  total_bytes: number;
  generated_at: string;
  inventory_sha256: string;
  images: DatasetImages;
  segmentation_masks: DatasetMasks;
}

interface DatasetImages {
  count: number;
  width: number | null;
  height: number | null;
}

interface DatasetMasks {
  count: number;
  foreground_ratio: number | null;
}

/** `schemas/experiment.py::ExperimentManifest` 里用到的部分。 */
interface ManifestFile {
  experiment_id: string;
  hypothesis: string;
  change_type: string;
  data_version: string;
  created_at: string;
  status: string;
}

/** `schemas/experiment.py::ExperimentResult` 里用到的部分。 */
interface ResultFile {
  experiment_id: string;
  status: string;
  validation_metric: number | null;
}

/** `paper/generated/evidence_map.json` 里用到的部分。 */
interface EvidenceMapFile {
  claims: Object[];
  research_records: number;
  generated_at: string;
}

/** 数据审计摘要。文件不在时 `present` 为 false，其余字段为 0/空。 */
export interface DatasetStatus {
  present: boolean;
  fileCount: number;
  issueCount: number;
  imageCount: number;
  maskCount: number;
  totalBytes: number;
  /** 清单指纹，对应 Python 侧 `inventory_sha256`。 */
  fingerprint: string;
  generatedAt: string;
}

/** 一条实验（manifest 与 result 合成一行，便于离线时一眼看完历史）。 */
export interface ExperimentStatus {
  experimentId: string;
  status: string;
  createdAt: string;
  changeType: string;
  hypothesis: string;
  dataVersion: string;
  /** 指标原样返回，格式化交给视图层（`Format.ets::formatNumber`），这里不重复一套。 */
  validationMetric: number | null;
  /** result 文件在不在：manifest 有而 result 没有，说明这条实验没跑完。 */
  resultPresent: boolean;
}

/** 论文证据图摘要。 */
export interface EvidenceStatus {
  present: boolean;
  claimCount: number;
  researchRecords: number;
  generatedAt: string;
}

/** 端侧能读出来的全部离线状态。 */
export interface OfflineStatus {
  dataset: DatasetStatus;
  experiments: ExperimentStatus[];
  /** 最近的事件，最新在前。 */
  events: LedgerEvent[];
  /** 账本总条数：界面上要能说清"显示的是最近几条 / 一共几条"，不能看起来像全部。 */
  eventTotal: number;
  evidence: EvidenceStatus;
}

/**
 * 读一个 JSON 文件。
 *
 * 文件不存在、或内容坏掉都返回 null：离线状态页的价值是「有什么给看什么」，
 * 一个坏文件不该让整页打不开。调用方据此显示"还没有 / 读不出来"。
 */
function readJson<T>(workspace: LocalWorkspace, relative: string): T | null {
  if (!workspace.exists(relative)) {
    return null;
  }
  try {
    return JSON.parse(workspace.readText(relative)) as T;
  } catch (error) {
    return null;
  }
}

/** 数据审计摘要；`present` 为 false 就表示这个工作区还没有审计结果。 */
export function readDatasetStatus(workspace: LocalWorkspace): DatasetStatus {
  const empty: DatasetStatus = {
    present: false,
    fileCount: 0,
    issueCount: 0,
    imageCount: 0,
    maskCount: 0,
    totalBytes: 0,
    fingerprint: '',
    generatedAt: ''
  };
  const file: DatasetStatisticsFile | null = readJson<DatasetStatisticsFile>(workspace, DATA_STATISTICS_FILE);
  if (file === null) {
    return empty;
  }
  return {
    present: true,
    fileCount: file.file_count,
    issueCount: file.issue_count,
    imageCount: file.images === undefined ? 0 : file.images.count,
    maskCount: file.segmentation_masks === undefined ? 0 : file.segmentation_masks.count,
    totalBytes: file.total_bytes,
    fingerprint: file.inventory_sha256,
    generatedAt: file.generated_at
  };
}

/**
 * 实验历史，**最新在前**（按 `created_at` 倒序，与实验页的口径一致）。
 *
 * 名单以 manifest 为准：result 是跑完之后才有的，没有 manifest 的 result 不属于在册实验。
 */
export function readExperimentStatuses(workspace: LocalWorkspace): ExperimentStatus[] {
  const rows: ExperimentStatus[] = [];
  for (const name of workspace.listFiles(MANIFEST_DIR)) {
    if (!name.endsWith('.json')) {
      continue;
    }
    const manifest: ManifestFile | null = readJson<ManifestFile>(workspace, `${MANIFEST_DIR}/${name}`);
    if (manifest === null) {
      continue;
    }
    const result: ResultFile | null =
      readJson<ResultFile>(workspace, `${RESULT_DIR}/${manifest.experiment_id}.json`);
    rows.push({
      experimentId: manifest.experiment_id,
      status: result === null ? manifest.status : result.status,
      createdAt: manifest.created_at,
      changeType: manifest.change_type,
      hypothesis: manifest.hypothesis,
      dataVersion: manifest.data_version,
      validationMetric: result === null ? null : result.validation_metric,
      resultPresent: result !== null
    });
  }
  return rows.sort((left: ExperimentStatus, right: ExperimentStatus) =>
    right.createdAt.localeCompare(left.createdAt));
}

export function readEvidenceStatus(workspace: LocalWorkspace): EvidenceStatus {
  const empty: EvidenceStatus = { present: false, claimCount: 0, researchRecords: 0, generatedAt: '' };
  const file: EvidenceMapFile | null = readJson<EvidenceMapFile>(workspace, EVIDENCE_MAP_FILE);
  if (file === null) {
    return empty;
  }
  return {
    present: true,
    claimCount: file.claims === undefined ? 0 : file.claims.length,
    researchRecords: file.research_records,
    generatedAt: file.generated_at
  };
}

/** 一次读齐离线状态。`eventLimit` 控制账本显示多少条（账本可能很长）。 */
export function readOfflineStatus(workspace: LocalWorkspace, eventLimit: number): OfflineStatus {
  return {
    dataset: readDatasetStatus(workspace),
    experiments: readExperimentStatuses(workspace),
    events: readEvents(workspace, eventLimit),
    eventTotal: eventCount(workspace),
    evidence: readEvidenceStatus(workspace)
  };
}
