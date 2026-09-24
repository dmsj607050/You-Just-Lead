/**
 * 端侧规则就绪度（只读投影）。
 *
 * 这里是 Python 侧 `agents/rules_agent.py::rule_confirmation_readiness` 的端侧对照实现：
 * 必备字段清单、`is_meaningful` 的判定、缺口的计数口径都必须**逐条对齐**，否则同一个工作区
 * 在 App 里和命令行里会得出不同结论——那比没有结论更糟。
 *
 * P0 只做只读评估（给工作区自检用）；写回规格、证据记录与批准在 P1 搬。
 */

import { YamlList, YamlMap, YamlNode, displayValue, yamlGet } from './YamlLite';

/** 通用必备字段（与 Python 侧 BASE_CONFIRMATION_FIELDS 一致）。 */
export const BASE_CONFIRMATION_FIELDS: string[] = [
  'competition.name',
  'competition.platform',
  'competition.task_type',
  'competition.deadline',
  'evaluation.primary_metric',
  'evaluation.direction',
  'submission.format',
  'submission.filename_rule',
  'submission.daily_limit',
  'constraints.model_size_limit_mb'
];

/** 讯飞水体分割档案的追加字段（与 Python 侧 XUNFEI_CONFIRMATION_FIELDS 一致）。 */
export const XUNFEI_CONFIRMATION_FIELDS: string[] = [
  'submission.contract.package_layout',
  'submission.contract.required_files',
  'submission.contract.mask_size',
  'submission.contract.mask_filename_suffix',
  'submission.contract.runtime_output',
  'constraints.external_data_allowed',
  'constraints.pretrained_models_allowed',
  'constraints.ensemble_allowed',
  'constraints.inference_limit_evidence'
];

const PLACEHOLDERS: string[] = ['unresolved', 'unknown', 'tbd', 'todo', '待填', '待确认'];

/**
 * 值控件的类型，与 Python 侧 `EVIDENCE_FIELD_KINDS` **逐条对齐**。
 *
 * 只有类型敏感的字段需要特判，其余按文本处理；`list` 与 `number` 在界面上**不允许改写**——
 * 让人在输入框里敲 1024,1024 会把列表写成字符串，而规格是要被程序读的。
 */
export function evidenceFieldKind(field: string): string {
  if (field === 'submission.contract.runtime_output') {
    return 'runtime_output';
  }
  if (field === 'constraints.external_data_allowed'
    || field === 'constraints.pretrained_models_allowed'
    || field === 'constraints.ensemble_allowed') {
    return 'boolean';
  }
  if (field === 'submission.contract.required_files' || field === 'submission.contract.mask_size') {
    return 'list';
  }
  if (field === 'submission.daily_limit' || field === 'constraints.model_size_limit_mb') {
    return 'number';
  }
  if (field === 'evaluation.direction') {
    return 'direction';
  }
  return 'text';
}

/** 一个值是否"真的填好了"：空值、占位词、空列表都算没填。 */
export function isMeaningful(value: YamlNode | undefined): boolean {
  if (value === undefined || value === null) {
    return false;
  }
  if (typeof value === 'boolean' || typeof value === 'number') {
    return true;
  }
  if (value instanceof YamlList) {
    return value.items.length > 0;
  }
  if (value instanceof YamlMap) {
    return value.size() > 0;
  }
  const text: string = `${value}`.trim().toLowerCase();
  if (text.length === 0) {
    return false;
  }
  for (const placeholder of PLACEHOLDERS) {
    if (text.includes(placeholder)) {
      return false;
    }
  }
  return true;
}

/** 是否是讯飞水体分割档案：决定要不要走那 9 个追加字段。 */
export function isXunfeiWatersegSpec(spec: YamlMap): boolean {
  const profile: YamlNode | undefined = yamlGet(spec, 'submission.validation_profile');
  if (profile === 'xunfei_waterseg_inference_package' || profile === 'xunfei_waterseg_runtime_output') {
    return true;
  }
  return displayValue(yamlGet(spec, 'competition.preferred_runner')) === 'waterseg_external';
}

/** 一个必备字段的当前状态。 */
export interface RuleFieldState {
  field: string;
  value: string;
  hasValue: boolean;
  anchor: string;
  hasAnchor: boolean;
  /** 值控件类型，见 `evidenceFieldKind`。 */
  kind: string;
}

/** 规则就绪度：与 Python 侧同名结构保持同样的语义。 */
export interface RuleReadiness {
  profile: string;
  ready: boolean;
  requiredFieldCount: number;
  missingValueCount: number;
  missingAnchorCount: number;
  /** 缺口条数：口径与 Python 侧 gaps 数组的长度一致。 */
  gapCount: number;
  /** 未澄清的规则问题条数。 */
  openQuestionCount: number;
  fields: RuleFieldState[];
}

/**
 * 评估规则就绪度。
 *
 * 缺口的计数顺序与 Python 侧一致：先"值没确认"，再"输出模式二选一"，再来源三件套，
 * 再逐个字段的锚点，最后未澄清问题。数字对不上就说明一端写歪了，不要凑。
 */
export function ruleReadiness(spec: YamlMap): RuleReadiness {
  const strict: boolean = isXunfeiWatersegSpec(spec);
  const required: string[] = strict
    ? BASE_CONFIRMATION_FIELDS.concat(XUNFEI_CONFIRMATION_FIELDS)
    : [];
  const anchors: YamlNode | undefined = yamlGet(spec, 'approval.official_evidence.fields');
  const anchorMap: YamlMap = anchors instanceof YamlMap ? anchors : new YamlMap();

  const fields: RuleFieldState[] = [];
  let gaps: number = 0;
  let missingValue: number = 0;
  let missingAnchor: number = 0;

  for (const name of required) {
    const value: YamlNode | undefined = yamlGet(spec, name);
    const hasValue: boolean = isMeaningful(value);
    if (!hasValue) {
      gaps++;
      missingValue++;
    }
    const anchor: YamlNode | undefined = anchorMap.get(name);
    const hasAnchor: boolean = isMeaningful(anchor);
    if (!hasAnchor) {
      missingAnchor++;
    }
    fields.push({
      field: name,
      value: displayValue(value),
      hasValue: hasValue,
      anchor: displayValue(anchor),
      hasAnchor: hasAnchor,
      kind: evidenceFieldKind(name)
    });
  }

  if (strict) {
    const outputMode: string = displayValue(yamlGet(spec, 'submission.contract.runtime_output')).toLowerCase();
    if (outputMode !== 'loose_png' && outputMode !== 'submit_zip') {
      gaps++;
    }
    for (const name of ['source_type', 'source_locator', 'reviewed_at']) {
      if (!isMeaningful(yamlGet(spec, `approval.official_evidence.${name}`))) {
        gaps++;
      }
    }
    gaps += missingAnchor;
  }

  const questions: YamlNode | undefined = yamlGet(spec, 'approval.unresolved_questions');
  let openQuestions: number = 0;
  if (questions === undefined || questions === null) {
    openQuestions = 0;
  } else if (questions instanceof YamlList) {
    openQuestions = questions.items.length;
    if (openQuestions > 0) {
      gaps++;
    }
  } else {
    gaps++;
    openQuestions = 1;
  }

  return {
    profile: strict ? 'xunfei_waterseg' : 'generic',
    ready: gaps === 0,
    requiredFieldCount: required.length,
    missingValueCount: missingValue,
    missingAnchorCount: missingAnchor,
    gapCount: gaps,
    openQuestionCount: openQuestions,
    fields: fields
  };
}
