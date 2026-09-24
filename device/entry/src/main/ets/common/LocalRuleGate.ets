/**
 * 端侧规则关口：录入官方证据、人工批准规则，并把结果写回工作区规格。
 *
 * 这是 Python 侧 `agents/rules_agent.py` 里 `rule_evidence_form_for_workspace` /
 * `build_rule_evidence_record` / `apply_official_rule_evidence` / `approve_rule_specification`
 * 的端侧对照实现，语义逐条对齐。最关键的一条：**录入证据不等于批准规则** ——
 * 录入后 `requires_human_confirmation` 仍是 true、`unresolved_questions` 清空、已有的
 * `approved_at` / `approved_note` 被移除；批准是另一道关口，要人写一句复核说明，
 * 而且缺口不归零时不允许批准。
 *
 * 与 Python 侧有意的差异：不写 `reports/official_rule_evidence_applied.json` 和
 * `reports/rule_approval.json`。那两份摘要是后端产物、给界面看的；端侧把就绪度与批准状态
 * 当场算出来显示，凭证落在规格字段、`docs/` 备份与账本事件里，不必再造中间文件。
 */

import { appendEvent, utcNow, utcStamp } from './LocalLedger';
import { LocalWorkspace } from './LocalWorkspace';
import {
  RuleReadiness,
  isKnownProfile,
  isMeaningful,
  requiredFieldsForProfile,
  ruleProfileName,
  ruleReadiness
} from './LocalRules';
import {
  YamlList,
  YamlMap,
  YamlNode,
  displayValue,
  dumpYaml,
  parseYaml,
  yamlGet,
  yamlSet
} from './YamlLite';

/** 工作区里规格文件与证据目录的名字（页面导入规格时要用同一个）。 */
export const SPEC_FILE: string = 'competition_spec.yaml';
export const EVIDENCE_DIR: string = 'docs';

/** 官方契约里运行时产物必须二选一的取值（表单也用它当选项）。 */
export const RUNTIME_OUTPUT_OPTIONS: string[] = ['loose_png', 'submit_zip'];

/** 主指标方向：同样只能二选一。 */
export const DIRECTION_OPTIONS: string[] = ['maximize', 'minimize'];

/** 必须是真布尔（不能写成字符串）的字段（与 Python 侧 BOOLEAN_EVIDENCE_FIELDS 一致）。 */
const BOOLEAN_FIELDS: string[] = [
  'constraints.offline_only',
  'constraints.external_data_allowed',
  'constraints.pretrained_models_allowed',
  'constraints.ensemble_allowed',
  'constraints.test_data_reuse_allowed',
  'submission.contract.empty_file_required'
];

/** 证据来源三项：官方规则页或官方文档的位置。 */
export interface GateSource {
  sourceType: string;
  sourceLocator: string;
  reviewedAt: string;
}

/**
 * 人在表单里对某个字段的改动。
 *
 * 没填的一律留空，表示"沿用规格现值"——界面只提交人实际填的东西，
 * 数值/布尔/列表就不用在两端往返一遍，也不会被字符串化。
 */
export interface GateFieldInput {
  field: string;
  anchor: string;
  valueText: string;
  /** 布尔字段的选择；null 表示没选，**不能**被当成 false。 */
  valueFlag: boolean | null;
  /** 二选一字段的选择（runtime_output / direction）。 */
  valueChoice: string;
}

/** 提交结果。 */
export interface GateOutcome {
  evidencePath: string;
  backupPath: string;
  evidenceSha256: string;
  appliedFieldCount: number;
  readiness: RuleReadiness;
}

/** 合并后的结果：值、锚点，以及还缺哪些字段。 */
interface MergedEvidence {
  values: YamlMap;
  anchors: YamlMap;
  missing: string[];
}

/** 账本事件的载荷，键名与 Python 侧的 `rules_evidence_applied` 一致。 */
interface EvidenceLedgerPayload {
  evidence_path: string;
  source_type: string;
  source_locator: string;
  field_count: number;
}

/** 规格里当前的批准状态。 */
export interface GateApproval {
  /** 还需要人工确认（true = 还没批准）。 */
  required: boolean;
  approvedAt: string;
  note: string;
}

/** 批准结果。 */
export interface GateApprovalOutcome {
  approvedAt: string;
  note: string;
  readiness: RuleReadiness;
}

/**
 * 账本事件的载荷。
 *
 * Python 侧把整棵 readiness 一起塞进 `rules_approved`；端侧只记审计真正要看的几项 ——
 * 一份就绪度树塞进每一行 JSONL 会让账本没法人眼扫读，而缺口数已经说明了结论。
 */
interface ApprovalLedgerPayload {
  spec_path: string;
  approved: boolean;
  approved_at: string;
  note: string;
  gap_count: number;
}

/** 当前档案的必备字段全表；还没认领档案时为空（此时不允许录证据）。 */
function requiredFields(spec: YamlMap): string[] {
  return requiredFieldsForProfile(ruleProfileName(spec));
}

/** 取节点，undefined 折成 null（规格里的空值本来也是 null）。 */
function nodeOf(map: YamlMap, key: string): YamlNode {
  const node: YamlNode | undefined = map.get(key);
  return node === undefined ? null : node;
}

/** 4 位十六进制短随机，替代 Python 的 `secrets.token_hex(2)`：文件名只要不撞，不需要密码学随机。 */
function shortToken(): string {
  const digits: string = '0123456789abcdef';
  let out: string = '';
  for (let i = 0; i < 4; i++) {
    out += digits.charAt(Math.floor(Math.random() * 16));
  }
  return out;
}

/** 规格至少要有的顶层段：一个都没有，就当用户选错了文件。 */
const SPEC_SECTIONS: string[] = ['competition', 'evaluation', 'submission', 'constraints', 'approval'];

/** 读工作区规格；不存在时抛错。 */
export function readSpec(workspace: LocalWorkspace): YamlMap {
  if (!workspace.exists(SPEC_FILE)) {
    throw new Error(`工作区里还没有 ${SPEC_FILE}，先用「导入规格文件」放一份进来`);
  }
  return parseYaml(workspace.readText(SPEC_FILE));
}

/**
 * 这段内容看起来是不是竞赛规格：能被解析，且带至少一个规格段。
 *
 * 只管"像不像"，不管"是哪个赛题"——通用赛题的规格也该能导进来，只是走不了这套证据记录。
 */
export function looksLikeSpec(text: string): boolean {
  const spec: YamlMap = parseYaml(text);
  for (const section of SPEC_SECTIONS) {
    if (spec.has(section)) {
      return true;
    }
  }
  return false;
}

/**
 * 把用户选中的规格文本放进工作区。
 *
 * 先解析、再确认它真的像一份规格，最后才落盘：导入是**覆盖**操作，读不懂或明显选错的文件
 * 绝不能把已经确认过的规格换掉。覆盖前先把原文备份到 `docs/`。
 */
export function importSpecText(workspace: LocalWorkspace, text: string): void {
  if (!looksLikeSpec(text)) {
    throw new Error('这份文件不像竞赛规格（没找到 competition / submission 等字段），已放弃导入');
  }
  if (workspace.exists(SPEC_FILE)) {
    workspace.writeText(`${EVIDENCE_DIR}/spec_backup_${utcStamp()}_import.yaml`, workspace.readText(SPEC_FILE));
  }
  workspace.writeText(SPEC_FILE, text);
}

/** 规格能否走这套证据记录：工作区得先认领一份有字段清单的档案。 */
export function gateSupported(spec: YamlMap): boolean {
  return spec.size() > 0 && isKnownProfile(ruleProfileName(spec));
}

/** 规格里已记录的来源三项，作为表单初值。 */
export function currentSource(spec: YamlMap): GateSource {
  return {
    sourceType: displayValue(yamlGet(spec, 'approval.official_evidence.source_type')),
    sourceLocator: displayValue(yamlGet(spec, 'approval.official_evidence.source_locator')),
    reviewedAt: displayValue(yamlGet(spec, 'approval.official_evidence.reviewed_at'))
  };
}

/**
 * 规格里当前的批准状态。
 *
 * 判定口径与 Python 一致：以 `requires_human_confirmation` 为准（默认 true = 未批准），
 * 批准时间与复核说明只作展示，不参与判定。
 */
export function currentApproval(spec: YamlMap): GateApproval {
  const required: YamlNode | undefined = yamlGet(spec, 'approval.requires_human_confirmation');
  return {
    required: required === false ? false : true,
    approvedAt: displayValue(yamlGet(spec, 'approval.approved_at')),
    note: displayValue(yamlGet(spec, 'approval.approved_note'))
  };
}

/** 找出某个字段的输入；没有就返回 undefined（等于没改）。 */
function inputOf(inputs: GateFieldInput[], field: string): GateFieldInput | undefined {
  for (const input of inputs) {
    if (input.field === field) {
      return input;
    }
  }
  return undefined;
}

/**
 * 把人工输入合并到规格现值与已有锚点上（对齐 Python 的 `build_rule_evidence_record`）。
 *
 * 优先级与 Python 一致：布尔选择 > 二选一选择 > 文本框；锚点为空则沿用已有锚点。
 */
function mergeEvidence(spec: YamlMap, inputs: GateFieldInput[]): MergedEvidence {
  const existing: YamlNode | undefined = yamlGet(spec, 'approval.official_evidence.fields');
  const existingAnchors: YamlMap = existing instanceof YamlMap ? existing : new YamlMap();
  const values: YamlMap = new YamlMap();
  const anchors: YamlMap = new YamlMap();
  const missing: string[] = [];

  for (const name of requiredFields(spec)) {
    let value: YamlNode | undefined = yamlGet(spec, name);
    let anchor: YamlNode | undefined = existingAnchors.get(name);
    const input: GateFieldInput | undefined = inputOf(inputs, name);
    if (input !== undefined) {
      if (input.valueFlag !== null) {
        value = input.valueFlag;
      } else if (input.valueChoice.trim().length > 0) {
        value = input.valueChoice.trim();
      } else if (input.valueText.trim().length > 0) {
        value = input.valueText.trim();
      }
      if (input.anchor.trim().length > 0) {
        anchor = input.anchor.trim();
      }
    }
    if (!isMeaningful(value) || !isMeaningful(anchor)) {
      missing.push(name);
      continue;
    }
    values.set(name, value === undefined ? null : value);
    anchors.set(name, displayValue(anchor));
  }
  return { values: values, anchors: anchors, missing: missing };
}

/** 组装要落盘的证据记录：`profile` + `source` + `fields`，与 Python 侧同一结构。 */
function buildRecord(values: YamlMap, anchors: YamlMap, source: GateSource, profile: string): YamlMap {
  const sourceMap: YamlMap = new YamlMap();
  sourceMap.set('source_type', source.sourceType);
  sourceMap.set('source_locator', source.sourceLocator);
  sourceMap.set('reviewed_at', source.reviewedAt);

  const fieldsMap: YamlMap = new YamlMap();
  for (const name of values.keys()) {
    const item: YamlMap = new YamlMap();
    item.set('value', nodeOf(values, name));
    item.set('anchor', displayValue(anchors.get(name)));
    fieldsMap.set(name, item);
  }

  const record: YamlMap = new YamlMap();
  record.set('profile', profile);
  record.set('source', sourceMap);
  record.set('fields', fieldsMap);
  return record;
}

/**
 * 提交官方证据：落证据记录文件 → 备份原规格 → 写回规格 → 记一笔账。
 *
 * 顺序与 Python 侧一致（先写文件再应用），因为规格里要记的是这份文件的路径与 sha256，
 * 证据链必须落到具体文件上。中途失败会把证据文件删掉，不留半成品。
 */
export async function applyOfficialEvidence(workspace: LocalWorkspace, source: GateSource,
  inputs: GateFieldInput[]): Promise<GateOutcome> {
  const spec: YamlMap = readSpec(workspace);
  const profile: string = ruleProfileName(spec);
  if (!gateSupported(spec)) {
    throw new Error('工作区还没认领规则档案（competition.rule_profile），没有字段清单可录');
  }

  const clean: GateSource = {
    sourceType: source.sourceType.trim(),
    sourceLocator: source.sourceLocator.trim(),
    reviewedAt: source.reviewedAt.trim()
  };
  if (clean.sourceType.length === 0 || clean.sourceLocator.length === 0 || clean.reviewedAt.length === 0) {
    throw new Error('来源类型、出处、复核日期三项都要填');
  }
  if (clean.sourceLocator.includes('...')) {
    throw new Error('出处里不能留「...」占位，要写成能定位到原文的说法');
  }

  const merged: MergedEvidence = mergeEvidence(spec, inputs);
  if (merged.missing.length > 0) {
    throw new Error(`还差 ${merged.missing.length} 个字段没齐：${merged.missing.join('、')}`);
  }
  // 类型必须在落盘前就对：规格是要被程序读的，字符串 "false" 会被当成真值。
  if (profile === 'xunfei_waterseg') {
    const outputMode: string = displayValue(merged.values.get('submission.contract.runtime_output')).toLowerCase();
    if (!RUNTIME_OUTPUT_OPTIONS.includes(outputMode)) {
      throw new Error('submission.contract.runtime_output 只能是 loose_png 或 submit_zip');
    }
  }
  const required: string[] = requiredFields(spec);
  for (const name of BOOLEAN_FIELDS) {
    if (required.indexOf(name) < 0) {
      continue;
    }
    if (typeof merged.values.get(name) !== 'boolean') {
      throw new Error(`${name} 必须是 YAML 布尔值（true / false）`);
    }
  }

  // 落证据记录文件。文件名里的时间戳与随机后缀对齐 Python 的命名习惯。
  const stamp: string = utcStamp();
  const evidenceRelative: string = `${EVIDENCE_DIR}/rule_evidence_${stamp}_${shortToken()}.yaml`;
  const backupRelative: string = `${EVIDENCE_DIR}/spec_backup_${stamp}.yaml`;
  const originalText: string = workspace.readText(SPEC_FILE);
  workspace.writeText(evidenceRelative, dumpYaml(buildRecord(merged.values, merged.anchors, clean, profile)));
  const evidenceSha256: string = await LocalWorkspace.sha256Of(workspace.join(evidenceRelative));

  try {
    // 备份原文：下面要整份重写规格，留一份原文才谈得上"可回溯"。
    workspace.writeText(backupRelative, originalText);

    // 档案名随证据一起落盘：读取方（就绪度、提交校验）据此选字段清单。
    yamlSet(spec, 'competition.rule_profile', profile);
    for (const name of merged.values.keys()) {
      yamlSet(spec, name, nodeOf(merged.values, name));
    }
    const evidence: YamlMap = new YamlMap();
    evidence.set('source_type', clean.sourceType);
    evidence.set('source_locator', clean.sourceLocator);
    evidence.set('reviewed_at', clean.reviewedAt);
    evidence.set('confirmation_file', workspace.join(evidenceRelative));
    evidence.set('confirmation_file_sha256', evidenceSha256);
    evidence.set('fields', merged.anchors);
    yamlSet(spec, 'approval.official_evidence', evidence);
    // 证据录入与"能不能开跑"是两件事，这里只录入。
    yamlSet(spec, 'approval.requires_human_confirmation', true);
    yamlSet(spec, 'approval.unresolved_questions', new YamlList());
    const approval: YamlNode | undefined = spec.get('approval');
    if (approval instanceof YamlMap) {
      approval.remove('approved_at');
      approval.remove('approved_note');
    }

    // 落盘前先自检：把**即将写入的这些字节**读回来重新算一遍，缺口必须归零。
    // 这一步挡的是"写出去的东西读回来变了意思"（转义、缩进、类型写错），
    // 规格被写歪比写失败危险得多，所以宁可不写。
    const nextText: string = dumpYaml(spec);
    const reread: RuleReadiness = ruleReadiness(parseYaml(nextText));
    if (reread.gapCount !== 0) {
      throw new Error(`写回前的自检没通过：写出去的内容读回来仍有 ${reread.gapCount} 项缺口，已放弃写入`);
    }
    workspace.writeText(SPEC_FILE, nextText);
  } catch (error) {
    workspace.remove(evidenceRelative);
    throw error as Error;
  }

  const payload: EvidenceLedgerPayload = {
    evidence_path: workspace.join(evidenceRelative),
    source_type: clean.sourceType,
    source_locator: clean.sourceLocator,
    field_count: merged.values.size()
  };
  appendEvent(workspace, 'rules_evidence_applied', JSON.stringify(payload));

  return {
    evidencePath: workspace.join(evidenceRelative),
    backupPath: workspace.join(backupRelative),
    evidenceSha256: evidenceSha256,
    appliedFieldCount: merged.values.size(),
    readiness: ruleReadiness(spec)
  };
}

/**
 * 规则关口最后一步：人工复核后批准。
 *
 * 与 Python 的 `approve_rule_specification` 逐条对齐：
 * - 缺口没归零**不允许**批准（这是关口的意义所在，不是形式）
 * - 复核说明必填，且会原文留在规格里
 * - 写回 `requires_human_confirmation: false` + `approved_at` + `approved_note`
 * - 落一笔账（`rules_approved`）
 *
 * 端侧多做的两件事：写盘前先把**即将写入的字节**读回来确认缺口仍是 0（和录入证据同一道自检），
 * 以及覆盖前把原文备份到 `docs/`。
 */
export async function approveRulesSpec(workspace: LocalWorkspace, note: string): Promise<GateApprovalOutcome> {
  const spec: YamlMap = readSpec(workspace);
  const readiness: RuleReadiness = ruleReadiness(spec);
  if (!readiness.ready) {
    throw new Error(`规则还有 ${readiness.gapCount} 项缺口没归零，不能批准`);
  }
  const clean: string = note.trim();
  if (clean.length === 0) {
    throw new Error('批准要写一句人工复核说明，这句说明会留在规格里');
  }

  const approvedAt: string = utcNow();
  const originalText: string = workspace.readText(SPEC_FILE);
  const backupRelative: string = `${EVIDENCE_DIR}/spec_backup_${utcStamp()}_approve.yaml`;
  workspace.writeText(backupRelative, originalText);

  try {
    yamlSet(spec, 'approval.requires_human_confirmation', false);
    yamlSet(spec, 'approval.approved_at', approvedAt);
    yamlSet(spec, 'approval.approved_note', clean);

    // 与录入证据同一道自检：写出去的字节读回来必须还是"已就绪"，
    // 否则宁可让这次批准失败，也不让规格停在一个读回来就不成立的状态。
    const nextText: string = dumpYaml(spec);
    if (!ruleReadiness(parseYaml(nextText)).ready) {
      throw new Error('写回前的自检没通过：写出去的规格读回来不再是"已就绪"，已放弃写入');
    }
    workspace.writeText(SPEC_FILE, nextText);
  } catch (error) {
    workspace.remove(backupRelative);
    throw error as Error;
  }

  const payload: ApprovalLedgerPayload = {
    spec_path: workspace.join(SPEC_FILE),
    approved: true,
    approved_at: approvedAt,
    note: clean,
    gap_count: readiness.gapCount
  };
  appendEvent(workspace, 'rules_approved', JSON.stringify(payload));

  return { approvedAt: approvedAt, note: clean, readiness: readiness };
}
