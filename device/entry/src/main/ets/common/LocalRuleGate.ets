/**
 * 端侧规则关口：录入官方证据并写回工作区规格。
 *
 * 这是 Python 侧 `agents/rules_agent.py` 里 `rule_evidence_form_for_workspace` /
 * `build_rule_evidence_record` / `apply_official_rule_evidence` 的端侧对照实现，语义逐条对齐。
 * 最关键的一条：**录入证据不等于批准规则** —— 写回后 `requires_human_confirmation` 仍是 true、
 * `unresolved_questions` 清空、已有的 `approved_at` / `approved_note` 被移除，批准仍要走另一道关口。
 *
 * 与 Python 侧有意的差异：不写 `reports/official_rule_evidence_applied.json`。
 * 那份摘要是后端产物、给界面看的；端侧把就绪度当场算出来显示，不必再造一份中间文件。
 */

import { appendEvent, utcStamp } from './LocalLedger';
import { LocalWorkspace } from './LocalWorkspace';
import {
  BASE_CONFIRMATION_FIELDS,
  RuleReadiness,
  XUNFEI_CONFIRMATION_FIELDS,
  isMeaningful,
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

/** 必须是真布尔（不能写成字符串）的字段。 */
const BOOLEAN_FIELDS: string[] = [
  'constraints.external_data_allowed',
  'constraints.pretrained_models_allowed',
  'constraints.ensemble_allowed'
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

/** 讯飞档案的必备字段全表（通用 10 项 + 追加 9 项）。 */
function requiredFields(): string[] {
  return BASE_CONFIRMATION_FIELDS.concat(XUNFEI_CONFIRMATION_FIELDS);
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

/** 规格能否走这套证据记录（目前只有讯飞水体分割档案）。 */
export function gateSupported(spec: YamlMap): boolean {
  return spec.size() > 0 && ruleReadiness(spec).profile === 'xunfei_waterseg';
}

/** 规格里已记录的来源三项，作为表单初值。 */
export function currentSource(spec: YamlMap): GateSource {
  return {
    sourceType: displayValue(yamlGet(spec, 'approval.official_evidence.source_type')),
    sourceLocator: displayValue(yamlGet(spec, 'approval.official_evidence.source_locator')),
    reviewedAt: displayValue(yamlGet(spec, 'approval.official_evidence.reviewed_at'))
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

  for (const name of requiredFields()) {
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

/** 组装要落盘的证据记录：`source` + `fields`，与 Python 侧同一结构。 */
function buildRecord(values: YamlMap, anchors: YamlMap, source: GateSource): YamlMap {
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
  if (!gateSupported(spec)) {
    throw new Error('当前规格不是讯飞水体分割档案，这套证据记录不适用');
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
  const outputMode: string = displayValue(merged.values.get('submission.contract.runtime_output')).toLowerCase();
  if (!RUNTIME_OUTPUT_OPTIONS.includes(outputMode)) {
    throw new Error('submission.contract.runtime_output 只能是 loose_png 或 submit_zip');
  }
  for (const name of BOOLEAN_FIELDS) {
    if (typeof merged.values.get(name) !== 'boolean') {
      throw new Error(`${name} 必须是 YAML 布尔值（true / false）`);
    }
  }

  // 落证据记录文件。文件名里的时间戳与随机后缀对齐 Python 的命名习惯。
  const stamp: string = utcStamp();
  const evidenceRelative: string = `${EVIDENCE_DIR}/rule_evidence_${stamp}_${shortToken()}.yaml`;
  const backupRelative: string = `${EVIDENCE_DIR}/spec_backup_${stamp}.yaml`;
  const originalText: string = workspace.readText(SPEC_FILE);
  workspace.writeText(evidenceRelative, dumpYaml(buildRecord(merged.values, merged.anchors, clean)));
  const evidenceSha256: string = await LocalWorkspace.sha256Of(workspace.join(evidenceRelative));

  try {
    // 备份原文：下面要整份重写规格，留一份原文才谈得上"可回溯"。
    workspace.writeText(backupRelative, originalText);

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
