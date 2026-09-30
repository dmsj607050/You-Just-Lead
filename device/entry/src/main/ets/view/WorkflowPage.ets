import {
  AgentAnswer,
  approveRules,
  askAgent,
  fetchNextActions,
  fetchRuleEvidence,
  fetchRulesReport,
  fetchWorkflow,
  NextAction,
  RuleGap,
  RuleEvidenceFieldInput,
  RuleEvidenceForm,
  RuleEvidenceOutcome,
  RuleEvidencePayload,
  RulesReport,
  RuleApprovalOutcome,
  submitRuleEvidence,
  WorkflowDetail
} from '../common/BackendClient';
import AppTheme from '../common/AppTheme';
import {
  componentLabel,
  componentTone,
  formatTimestamp,
  plainText,
  priorityLabel,
  priorityTone,
  ruleGapActionLabel,
  stageLabel,
  todayLocal
} from '../common/Format';
import { tFor, tfFor } from '../common/I18n';
import { DIRECTION_OPTIONS, RUNTIME_OUTPUT_OPTIONS } from '../common/LocalRuleGate';
import { CardPanel, EmptyHint, PageHeader, ProgressBar, RailItemSpec, SectionRail, StatusBadge } from './Widgets';

/** 一个环节的展示行。labelKey 存文案键，渲染时再取 this.tr()，语言切换才会跟着变。 */
interface ComponentRow {
  labelKey: string;
  state: string;
}

/** 一组规则缺口：同一类「要做什么」下的多个字段。 */
interface RuleGapGroup {
  reason: string;
  fields: string[];
}

/**
 * 证据录入表单里的一行。
 *
 * `anchor` / `valueDraft` 是人的输入（逐键写回这个对象，不需要重绘）；
 * `flag` / `choice` 是布尔与枚举字段的选择，选完要触发一次刷新才能看到选中态。
 * 值缺失时不允许替人猜：`flag` 未选就是 null，提交前会被本地校验拦下。
 */
interface EvidenceRow {
  field: string;
  kind: string;
  valueText: string | null;
  hasValue: boolean;
  anchor: string;
  hasAnchor: boolean;
  flag: boolean | null;
  choice: string;
  valueDraft: string;
}

/**
 * 按「要做什么」把缺口归组，组内按字段去重。
 *
 * 后端对同一个字段可能给出不同类的要求（例如 `submission.contract.runtime_output`
 * 既有「值未确认」又有「要按官方运行时契约二选一」），所以同一个字段允许出现在
 * 两个组里；组内则只列一次，计数与标签数一致。
 * 按字段前缀分组会让「官方证据出处」这类大组只显示第一条原因，把组内另一类工作藏掉，
 * 因此这里改用 reason 作分组轴。
 */
function groupRuleGaps(gaps: RuleGap[]): RuleGapGroup[] {
  const groups: RuleGapGroup[] = [];
  for (const gap of gaps) {
    let target: RuleGapGroup | null = null;
    for (const group of groups) {
      if (group.reason === gap.reason) {
        target = group;
        break;
      }
    }
    if (target === null) {
      groups.push({ reason: gap.reason, fields: [gap.field] });
    } else if (!target.fields.includes(gap.field)) {
      target.fields.push(gap.field);
    }
  }
  return groups;
}

/**
 * 工作流页：看阶段、看每个环节的状态、看卡在哪里、看下一步做什么。
 *
 * 数据全部来自后端 /api/workflow 与 /api/next-actions。
 */
@Component
export struct WorkflowPage {
  /** 父页面可指定首次进入的分段，例如空项目从规则证据开始。 */
  @Prop initialSection: string = 'status';
  /** 当前账户余额；模型调用后由父页面刷新。 */
  @Prop creditBalance: number = 0;
  /** 一次模型请求完成后通知父页面刷新账户余额。 */
  onCreditsChanged: () => void = () => {
  };
  @State loading: boolean = false;
  @State errorText: string = '';
  /**
   * 当前分段：status / rules / blockers / actions / ask。
   *
   * 原先这一页把组件状态、规则缺口、证据录入、批准、阻塞项、待办动作、问一问全堆在一列，
   * 一次要滑很多屏；现在一次只渲染一段，「现在到哪一步、卡在哪」写在标题下面一行里。
   */
  @State section: string = 'status';
  @State stage: string = '';
  @State automatic: boolean = false;
  @State completedExperiments: number = 0;
  @State blockers: string[] = [];
  @State rows: ComponentRow[] = [];
  /**
   * 展开的环节（存 labelKey）。
   *
   * 三种取值：空串＝跟随当前阶段（默认只展开它）；`none`＝全部收起；其余＝那一个环节。
   * 存 key 而不是下标：`ForEach` 的 key 生成器只拿得到元素、拿不到下标，
   * 而展开态**必须进 key** 才能触发重建（ArkUI 不会因为 @Builder 里读到的状态变了就重建子树）。
   */
  @State expandedStepKey: string = '';
  /** 窄窗口下右栏挪到时间线下面。 */
  @State compactFlow: boolean = true;
  @State actions: NextAction[] = [];
  @State ruleReady: boolean = false;
  @State ruleProfile: string = '';
  @State requiredFieldCount: number = 0;
  @State ruleGroups: RuleGapGroup[] = [];
  /** 规则是否已人工确认（来自环节状态，而不是"字段齐不齐"）。 */
  @State rulesApproved: boolean = false;
  /** 规则确认关口的输入与状态。 */
  @State approvalNote: string = '';
  @State approving: boolean = false;
  @State approvalError: string = '';
  @State approvalRecordedAt: string = '';
  /** 官方证据录入：表单是否展开、档案是否支持、逐字段的输入行。 */
  @State evidenceOpen: boolean = false;
  @State evidenceSupported: boolean = false;
  @State evidenceSourceType: string = '';
  @State evidenceSourceLocator: string = '';
  @State evidenceReviewedAt: string = '';
  @State evidenceRows: EvidenceRow[] = [];
  @State evidenceRequiredCount: number = 0;
  @State evidenceMissingValue: number = 0;
  @State evidenceMissingAnchor: number = 0;
  @State evidenceError: string = '';
  @State evidenceDone: string = '';
  @State evidenceSubmitting: boolean = false;
  @State question: string = '';
  @State answer: string = '';
  /** 回答的模型名与轮数：分开存，渲染时再拼文案，切语言才不会留在旧语言。 */
  @State answerModel: string = '';
  @State answerTurns: number = 0;
  @State asking: boolean = false;
  @State askError: string = '';
  /**
   * 当前语言。ArkUI 只重建读到状态变量的节点，所以本组件所有文案都走 this.tr()，
   * 由它读一次 this.lang，等于把用到的节点登记到语言变化上。
   */
  @StorageLink('lang') lang: string = 'zh';
  /** 外部唤起时带进来的问题（键名与 EntryAbility 里的 PENDING_QUESTION_KEY 一致）。 */
  @StorageLink('pendingQuestion') pendingQuestion: string = '';

  aboutToAppear(): void {
    this.section = this.initialSection;
    if (this.pendingQuestion.length > 0) {
      this.question = this.pendingQuestion;
    }
    this.load();
  }

  /** 取文案：读一次 lang，让调用它的节点订阅语言变化。 */
  private tr(key: string): string {
    return tFor(this.lang, key);
  }

  /** 已知的后端建议提供中文呈现；未知文案保留原文，避免误译来源信息。 */
  private actionText(value: string, evidence: boolean = false): string {
    const keys: Record<string, string> = evidence ? {
      'Specification is not approved.': 'workflow.actionEvidence.rules',
      'No data_statistics.json exists.': 'workflow.actionEvidence.audit',
      'No persisted research radar exists.': 'workflow.actionEvidence.research',
      'No completed experiments recorded.': 'workflow.actionEvidence.baseline'
    } : {
      'Resolve official-rule questions and explicitly approve the specification.': 'workflow.action.rules',
      'Run the deterministic data audit before creating a real baseline.': 'workflow.action.audit',
      'Search research sources using the task and metric from the approved specification.': 'workflow.action.research',
      'After rules and audit are approved, run one reproducible baseline with a frozen configuration.': 'workflow.action.baseline'
    };
    const key = keys[value];
    return key ? this.tr(key) : value;
  }

  /** 带占位符取文案。 */
  private trf(key: string, args: string[]): string {
    return tfFor(this.lang, key, args);
  }

  /**
   * 人工确认规则：写一句复核说明提交。
   *
   * 说明是这道关口的留痕，空说明直接拦在本地；规则字段没齐时按钮是禁用的，
   * 因为后端也会拒绝（"Cannot approve an incomplete rule specification"）。
   */
  async submitRuleApproval(): Promise<void> {
    const note: string = this.approvalNote.trim();
    this.approvalError = '';
    if (note.length === 0) {
      this.approvalError = this.tr('workflow.gateNoteRequired');
      return;
    }
    this.approving = true;
    try {
      const outcome: RuleApprovalOutcome = await approveRules(note);
      this.approvalNote = '';
      this.approvalRecordedAt = formatTimestamp(outcome.approved_at);
      // 关口过了，阶段与各环节状态都会变，整体重新取一次。
      await this.load();
    } catch (err) {
      const error = err as Error;
      this.approvalError = error.message;
    } finally {
      this.approving = false;
    }
  }

  /**
   * 读取证据录入表单。
   *
   * 表单展开时不覆盖人正在填的内容，只更新顶部的缺口计数（后端仍会拒不合规的提交）。
   */
  async loadEvidence(): Promise<void> {
    try {
      const form: RuleEvidenceForm = await fetchRuleEvidence();
      this.evidenceSupported = form.supported;
      this.evidenceRequiredCount = form.required_field_count;
      this.evidenceMissingValue = form.missing_value_count;
      this.evidenceMissingAnchor = form.missing_anchor_count;
      if (this.evidenceOpen) {
        return;
      }
      this.evidenceSourceType = form.source.source_type !== null ? form.source.source_type : '';
      this.evidenceSourceLocator = form.source.source_locator !== null ? form.source.source_locator : '';
      this.evidenceReviewedAt = form.source.reviewed_at !== null ? form.source.reviewed_at : todayLocal();
      const rows: EvidenceRow[] = [];
      for (const item of form.fields) {
        rows.push({
          field: item.field,
          kind: item.kind,
          valueText: item.value,
          hasValue: item.has_value,
          anchor: item.anchor !== null ? item.anchor : '',
          hasAnchor: item.has_anchor,
          // 值缺失时不替人猜：布尔与枚举都留空，等人在官方原文里读到再选。
          flag: item.value === 'true' ? true : (item.value === 'false' ? false : null),
          choice: item.kind === 'direction' && item.value !== null ? item.value
            : (item.kind === 'runtime_output' && item.value !== null && item.value !== 'unresolved' ? item.value : ''),
          valueDraft: ''
        });
      }
      this.evidenceRows = rows;
    } catch (err) {
      const error = err as Error;
      this.evidenceError = error.message;
    }
  }

  /**
   * 替换表单里的一行。
   *
   * 必须整体换掉数组、并且换成一个**新对象**：ArkUI 只在数组本身或元素引用变化时才重绘，
   * 就地改字段再赋回同一个引用，选中态不会显示出来（提交时值却是新的，最容易看漏）。
   */
  private updateEvidenceRow(index: number, row: EvidenceRow): void {
    const next: EvidenceRow[] = this.evidenceRows.slice();
    next[index] = {
      field: row.field,
      kind: row.kind,
      valueText: row.valueText,
      hasValue: row.hasValue,
      anchor: row.anchor,
      hasAnchor: row.hasAnchor,
      flag: row.flag,
      choice: row.choice,
      valueDraft: row.valueDraft
    };
    this.evidenceRows = next;
  }

  /** 数一遍还差什么：值缺几项、锚点缺几项。 */
  private evidenceIncomplete(): number[] {
    let missingValue: number = 0;
    let missingAnchor: number = 0;
    for (const row of this.evidenceRows) {
      if (row.anchor.trim().length === 0) {
        missingAnchor++;
      }
      if (row.hasValue) {
        continue;
      }
      if (row.kind === 'boolean') {
        if (row.flag === null) {
          missingValue++;
        }
      } else if (row.kind === 'runtime_output' || row.kind === 'direction') {
        if (row.choice.length === 0) {
          missingValue++;
        }
      } else if (row.kind === 'text') {
        if (row.valueDraft.trim().length === 0) {
          missingValue++;
        }
      } else {
        // 列表与数值不允许在界面里改：缺值只能先回规格里确认。
        missingValue++;
      }
    }
    return [missingValue, missingAnchor];
  }

  /** 只提交人实际填的东西，其余字段由后端沿用规格里的值。 */
  private evidenceInputs(): RuleEvidenceFieldInput[] {
    const inputs: RuleEvidenceFieldInput[] = [];
    for (const row of this.evidenceRows) {
      const input: RuleEvidenceFieldInput = { field: row.field, anchor: row.anchor.trim() };
      if (!row.hasValue) {
        const flag: boolean | null = row.flag;
        const draft: string = row.valueDraft.trim();
        if (row.kind === 'boolean' && flag !== null) {
          input.value_flag = flag;
        } else if ((row.kind === 'runtime_output' || row.kind === 'direction') && row.choice.length > 0) {
          input.value_text = row.choice;
        } else if (row.kind === 'text' && draft.length > 0) {
          input.value_text = draft;
        }
      }
      inputs.push(input);
    }
    return inputs;
  }

  /**
   * 提交官方证据。
   *
   * 本地先数缺项（比后端的报错更快、更清楚），再交给后端落文件并应用。
   * 提交成功也不等于批准规则：关口仍要人另写复核说明。
   */
  async sendRuleEvidence(): Promise<void> {
    this.evidenceError = '';
    if (this.evidenceSourceType.trim().length === 0
      || this.evidenceSourceLocator.trim().length === 0
      || this.evidenceReviewedAt.trim().length === 0) {
      this.evidenceError = this.tr('workflow.evidenceNeedSource');
      return;
    }
    const counts: number[] = this.evidenceIncomplete();
    if (counts[0] > 0 || counts[1] > 0) {
      this.evidenceError = this.trf('workflow.evidenceIncomplete', [
        `${counts[0] + counts[1]}`, `${counts[0]}`, `${counts[1]}`
      ]);
      return;
    }
    this.evidenceSubmitting = true;
    try {
      const payload: RuleEvidencePayload = {
        source_type: this.evidenceSourceType.trim(),
        source_locator: this.evidenceSourceLocator.trim(),
        reviewed_at: this.evidenceReviewedAt.trim(),
        fields: this.evidenceInputs()
      };
      const outcome: RuleEvidenceOutcome = await submitRuleEvidence(payload);
      this.evidenceDone = this.trf('workflow.evidenceDone', [`${outcome.applied_fields.length}`]);
      this.evidenceOpen = false;
      // 缺口与环节状态都会变；表单也重新读一次，锚点徽章才会变绿。
      await this.load();
      await this.loadEvidence();
    } catch (err) {
      const error = err as Error;
      this.evidenceError = error.message;
    } finally {
      this.evidenceSubmitting = false;
    }
  }

  /** 把问题连同当前阶段交给后端 Agent，它自己决定查哪些记录。 */
  async ask(): Promise<void> {
    const prompt: string = this.question.trim();
    if (prompt.length === 0 || this.asking) {
      return;
    }
    this.asking = true;
    this.askError = '';
    this.answer = '';
    this.pendingQuestion = '';
    try {
      const reply: AgentAnswer = await askAgent(prompt, stageLabel(this.lang, this.stage));
      this.answer = plainText(reply.content);
      this.answerModel = reply.model;
      this.answerTurns = reply.turns;
    } catch (err) {
      const error = err as Error;
      this.askError = error.message;
    } finally {
      this.asking = false;
      // 失败响应也可能已经产生服务端用量；让父页从账本账户接口读回实际余额。
      this.onCreditsChanged();
    }
  }

  async load(): Promise<void> {
    this.loading = true;
    this.errorText = '';
    try {
      const detail: WorkflowDetail = await fetchWorkflow();
      const queue = await fetchNextActions();
      const rules: RulesReport = await fetchRulesReport();
      this.stage = detail.stage;
      this.automatic = detail.automatic_execution;
      this.completedExperiments = detail.completed_experiments;
      this.blockers = detail.blockers;
      this.ruleReady = rules.readiness.ready;
      this.ruleProfile = rules.readiness.profile;
      this.requiredFieldCount = rules.readiness.required_fields.length;
      this.ruleGroups = groupRuleGaps(rules.readiness.gaps);
      this.rows = [
        { labelKey: 'workflow.rulesConfirm', state: detail.components.rules },
        { labelKey: 'workflow.dataAudit', state: detail.components.data_audit },
        { labelKey: 'workflow.researchSearch', state: detail.components.research },
        { labelKey: 'workflow.baselineRepro', state: detail.components.baseline },
        { labelKey: 'workflow.approvalReview', state: detail.components.approvals }
      ];
      this.rulesApproved = detail.components.rules === 'approved';
      this.actions = queue.actions;
      // 证据录入的档案支持情况与缺口计数也要跟着刷新。
      await this.loadEvidence();
    } catch (err) {
      const error = err as Error;
      this.errorText = error.message;
    } finally {
      this.loading = false;
    }
  }

  /** 待办条数：同一字段若有两类要求会被计两次，与界面上列出的标签总数一致。 */
  private gapCount(): number {
    let total: number = 0;
    for (const group of this.ruleGroups) {
      total += group.fields.length;
    }
    return total;
  }

  /** 涉及的不同字段数：跨组去重，因此不会大于 gapCount()。 */
  private uniqueFieldCount(): number {
    const seen: string[] = [];
    for (const group of this.ruleGroups) {
      for (const field of group.fields) {
        if (!seen.includes(field)) {
          seen.push(field);
        }
      }
    }
    return seen.length;
  }

  /** 「Rule evidence missing:」这类行已由「规则缺口」面板结构化展示，这里不再重复。 */
  private openQuestions(): string[] {
    const questions: string[] = [];
    for (const item of this.blockers) {
      if (!item.startsWith('Rule evidence missing:')) {
        questions.push(item);
      }
    }
    return questions;
  }

  /** 缺口该做什么：用后端 reason 映射出的动作名，映射不到返回空串。 */
  private gapTitle(group: RuleGapGroup): string {
    return ruleGapActionLabel(this.lang, group.reason);
  }

  /**
   * 官方证据录入：逐字段填「值 + 官方锚点」，让缺口从「要做什么」变成「官方原文在哪」。
   *
   * 录入不等于批准规则（后端也只写证据、不置批准位），所以它放在规则关口之前。
   */
  @Builder
  EvidenceGate() {
    Column() {
      Divider()
        .color(AppTheme.BORDER_SOFT)
        .margin({ top: 16 * AppTheme.UI_SCALE, bottom: 16 * AppTheme.UI_SCALE })

      Row() {
        Column() {
          Text(this.tr('workflow.evidenceTitle'))
            .fontSize(15 * AppTheme.UI_SCALE)
            .fontWeight(FontWeight.Medium)
            .fontColor(AppTheme.TEXT_PRIMARY)
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)

        if (this.evidenceSupported) {
          Text(this.evidenceOpen ? this.tr('workflow.evidenceClose') : this.tr('workflow.evidenceOpen'))
            .fontSize(13 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.PRIMARY)
            .padding({ left: 12 * AppTheme.UI_SCALE, right: 12 * AppTheme.UI_SCALE, top: 6 * AppTheme.UI_SCALE, bottom: 6 * AppTheme.UI_SCALE })
            .onClick(() => {
              this.evidenceOpen = !this.evidenceOpen;
              this.evidenceError = '';
              if (this.evidenceOpen) {
                this.loadEvidence();
              }
            })
        }
      }
      .width('100%')
      .alignItems(VerticalAlign.Top)

      if (!this.evidenceSupported) {
        Text(this.tr('workflow.evidenceUnsupported'))
          .fontSize(12 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.WARN_TEXT)
          .width('100%')
          .margin({ top: 10 * AppTheme.UI_SCALE })
      } else if (!this.evidenceOpen) {
        // 填写进度用两条比例条说：原先是一行灰字「必填 24 项：缺值 0 项、缺锚点 0 项」，
        // 要逐字读完才知道还差多少；条一眼就看出来。
        ProgressBar({
          label: this.tr('workflow.valuesFilled'),
          current: this.evidenceRequiredCount - this.evidenceMissingValue,
          total: this.evidenceRequiredCount
        })
          .margin({ top: 14 * AppTheme.UI_SCALE, bottom: 10 * AppTheme.UI_SCALE })
        ProgressBar({
          label: this.tr('workflow.anchorsFilled'),
          current: this.evidenceRequiredCount - this.evidenceMissingAnchor,
          total: this.evidenceRequiredCount
        })
      }

      if (this.evidenceDone.length > 0) {
        Text(this.evidenceDone)
          .fontSize(12 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.PRIMARY_DARK)
          .width('100%')
          .margin({ top: 10 * AppTheme.UI_SCALE })
      }

      if (this.evidenceOpen && this.evidenceSupported) {
        this.EvidenceForm()
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
  }

  /** 证据来源：类型 + 定位 + 复核时间，三项都要人填。 */
  @Builder
  EvidenceForm() {
    Column({ space: 8 * AppTheme.UI_SCALE }) {
      Text(this.tr('workflow.evidenceGateHint'))
        .fontSize(12 * AppTheme.UI_SCALE)
        .fontColor(AppTheme.TEXT_TERTIARY)
        .width('100%')

      Text(this.tr('workflow.evidenceSourceType'))
        .fontSize(12 * AppTheme.UI_SCALE)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .width('100%')
      TextInput({ text: this.evidenceSourceType, placeholder: this.tr('workflow.evidenceSourceTypeHint') })
        .fontSize(13 * AppTheme.UI_SCALE)
        .width('100%')
        .height(38 * AppTheme.UI_SCALE)
        .onChange((value: string) => {
          this.evidenceSourceType = value;
        })

      Text(this.tr('workflow.evidenceSourceLocator'))
        .fontSize(12 * AppTheme.UI_SCALE)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .width('100%')
      TextInput({ text: this.evidenceSourceLocator, placeholder: this.tr('workflow.evidenceSourceLocatorHint') })
        .fontSize(13 * AppTheme.UI_SCALE)
        .width('100%')
        .height(38 * AppTheme.UI_SCALE)
        .onChange((value: string) => {
          this.evidenceSourceLocator = value;
        })

      Text(this.tr('workflow.evidenceReviewedAt'))
        .fontSize(12 * AppTheme.UI_SCALE)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .width('100%')
      TextInput({ text: this.evidenceReviewedAt, placeholder: this.tr('workflow.evidenceReviewedAtHint') })
        .fontSize(13 * AppTheme.UI_SCALE)
        .width('100%')
        .height(38 * AppTheme.UI_SCALE)
        .onChange((value: string) => {
          this.evidenceReviewedAt = value;
        })

      Row() {
        Text(this.tr('workflow.evidenceFieldColumn'))
          .fontSize(13 * AppTheme.UI_SCALE)
          .fontWeight(FontWeight.Medium)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .layoutWeight(1)
        Text(this.trf('workflow.evidenceSummary', [
          `${this.evidenceRequiredCount}`, `${this.evidenceMissingValue}`, `${this.evidenceMissingAnchor}`
        ]))
          .fontSize(12 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.TEXT_TERTIARY)
      }
      .width('100%')
      .margin({ top: 8 * AppTheme.UI_SCALE })

      ForEach(this.evidenceRows, (row: EvidenceRow, index: number) => {
        this.EvidenceRowLine(row, index)
      }, (row: EvidenceRow) => `${row.field}-${row.flag}-${row.choice}-${row.hasAnchor}`)

      if (this.evidenceError.length > 0) {
        Text(this.evidenceError)
          .fontSize(12 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.DANGER)
          .width('100%')
          .margin({ top: 6 * AppTheme.UI_SCALE })
      }

      Row({ space: 12 * AppTheme.UI_SCALE }) {
        Text(this.evidenceSubmitting ? this.tr('workflow.evidenceSubmitting') : this.tr('workflow.evidenceSubmit'))
          .fontSize(13 * AppTheme.UI_SCALE)
          .fontColor(Color.White)
          .backgroundColor(AppTheme.PRIMARY)
          .borderRadius(AppTheme.RADIUS_SM)
          .padding({ left: 16 * AppTheme.UI_SCALE, right: 16 * AppTheme.UI_SCALE, top: 8 * AppTheme.UI_SCALE, bottom: 8 * AppTheme.UI_SCALE })
          .enabled(!this.evidenceSubmitting)
          .opacity(this.evidenceSubmitting ? 0.6 : 1)
          .onClick(() => {
            this.sendRuleEvidence();
          })
        Text(this.tr('workflow.evidenceCancel'))
          .fontSize(13 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .padding({ left: 8 * AppTheme.UI_SCALE, right: 8 * AppTheme.UI_SCALE, top: 8 * AppTheme.UI_SCALE, bottom: 8 * AppTheme.UI_SCALE })
          .onClick(() => {
            this.evidenceOpen = false;
            this.evidenceError = '';
          })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .margin({ top: 10 * AppTheme.UI_SCALE })
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .margin({ top: 14 * AppTheme.UI_SCALE })
  }

  /** 允许 / 不允许：布尔字段只能人选，未选就是没确认。 */
  @Builder
  BooleanChips(row: EvidenceRow, index: number) {
    Row({ space: 8 * AppTheme.UI_SCALE }) {
      Text(this.tr('workflow.evidenceYes'))
        .fontSize(12 * AppTheme.UI_SCALE)
        .fontColor(row.flag === true ? AppTheme.PRIMARY_DARK : AppTheme.TEXT_SECONDARY)
        .backgroundColor(row.flag === true ? AppTheme.PRIMARY_SOFT : AppTheme.PAGE_BG)
        .borderRadius(6 * AppTheme.UI_SCALE)
        .padding({ left: 10 * AppTheme.UI_SCALE, right: 10 * AppTheme.UI_SCALE, top: 4 * AppTheme.UI_SCALE, bottom: 4 * AppTheme.UI_SCALE })
        .onClick(() => {
          row.flag = true;
          this.updateEvidenceRow(index, row);
        })
      Text(this.tr('workflow.evidenceNo'))
        .fontSize(12 * AppTheme.UI_SCALE)
        .fontColor(row.flag === false ? AppTheme.PRIMARY_DARK : AppTheme.TEXT_SECONDARY)
        .backgroundColor(row.flag === false ? AppTheme.PRIMARY_SOFT : AppTheme.PAGE_BG)
        .borderRadius(6 * AppTheme.UI_SCALE)
        .padding({ left: 10 * AppTheme.UI_SCALE, right: 10 * AppTheme.UI_SCALE, top: 4 * AppTheme.UI_SCALE, bottom: 4 * AppTheme.UI_SCALE })
        .onClick(() => {
          row.flag = false;
          this.updateEvidenceRow(index, row);
        })
    }
    .layoutWeight(1)
  }

  /** 取值必须二选一的字段（loose_png / submit_zip、maximize / minimize）。 */
  @Builder
  ChoiceChips(row: EvidenceRow, index: number, options: string[]) {
    Row({ space: 8 * AppTheme.UI_SCALE }) {
      ForEach(options, (option: string) => {
        Text(option)
          .fontSize(12 * AppTheme.UI_SCALE)
          .fontColor(row.choice === option ? AppTheme.PRIMARY_DARK : AppTheme.TEXT_SECONDARY)
          .backgroundColor(row.choice === option ? AppTheme.PRIMARY_SOFT : AppTheme.PAGE_BG)
          .borderRadius(6 * AppTheme.UI_SCALE)
          .padding({ left: 10 * AppTheme.UI_SCALE, right: 10 * AppTheme.UI_SCALE, top: 4 * AppTheme.UI_SCALE, bottom: 4 * AppTheme.UI_SCALE })
          .onClick(() => {
            row.choice = option;
            this.updateEvidenceRow(index, row);
          })
      }, (option: string) => `${row.field}-${option}-${row.choice}`)
    }
    .layoutWeight(1)
  }

  /** 一行字段：值控件按类型分派，锚点永远是人填的输入框。 */
  @Builder
  EvidenceRowLine(row: EvidenceRow, index: number) {
    Column() {
      Row() {
        Text(row.field)
          .fontSize(13 * AppTheme.UI_SCALE)
          .fontWeight(FontWeight.Medium)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .layoutWeight(1)
        StatusBadge({
          text: row.hasAnchor ? this.tr('workflow.evidenceAnchored') : this.tr('workflow.evidenceNeedAnchor'),
          tone: row.hasAnchor ? 'ok' : 'danger'
        })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Row() {
        Text(this.tr('workflow.evidenceValueColumn'))
          .fontSize(12 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .width(84 * AppTheme.UI_SCALE)
        if (row.hasValue) {
          Text(row.valueText !== null ? row.valueText : '—')
            .fontSize(12 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .layoutWeight(1)
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        } else if (row.kind === 'boolean') {
          this.BooleanChips(row, index)
        } else if (row.kind === 'runtime_output') {
          this.ChoiceChips(row, index, RUNTIME_OUTPUT_OPTIONS)
        } else if (row.kind === 'direction') {
          this.ChoiceChips(row, index, DIRECTION_OPTIONS)
        } else if (row.kind === 'text') {
          TextInput({ text: row.valueDraft, placeholder: this.tr('workflow.evidenceValueHint') })
            .fontSize(12 * AppTheme.UI_SCALE)
            .layoutWeight(1)
            .height(36 * AppTheme.UI_SCALE)
            .onChange((value: string) => {
              row.valueDraft = value;
            })
        } else {
          Text(this.tr('workflow.evidenceLockedValue'))
            .fontSize(12 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.WARN_TEXT)
            .layoutWeight(1)
        }
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .margin({ top: 8 * AppTheme.UI_SCALE })

      Row() {
        Text(this.tr('workflow.evidenceAnchorColumn'))
          .fontSize(12 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .width(84 * AppTheme.UI_SCALE)
        TextInput({ text: row.anchor, placeholder: this.tr('workflow.evidenceAnchorHint') })
          .fontSize(12 * AppTheme.UI_SCALE)
          .layoutWeight(1)
          .height(36 * AppTheme.UI_SCALE)
          .onChange((value: string) => {
            row.anchor = value;
          })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .margin({ top: 6 * AppTheme.UI_SCALE })
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ top: 12 * AppTheme.UI_SCALE, bottom: 12 * AppTheme.UI_SCALE })
    .border({ width: { bottom: 1 }, color: AppTheme.BORDER_SOFT })
  }

  /**
   * 规则确认关口：人写复核说明、点确认，工作流才会放行到下一步。
   *
   * 未确认时按钮禁用有两个前提：必填字段齐了、说明不为空——两者缺一，后端也会拒绝。
   */
  @Builder
  RuleGate() {
    Column() {
      Divider()
        .color(AppTheme.BORDER_SOFT)
        .margin({ top: 16 * AppTheme.UI_SCALE, bottom: 16 * AppTheme.UI_SCALE })

      Text(this.tr('workflow.gateTitle'))
        .fontSize(15 * AppTheme.UI_SCALE)
        .fontWeight(FontWeight.Medium)
        .fontColor(AppTheme.TEXT_PRIMARY)

      if (this.rulesApproved) {
        Text(this.tr('workflow.gateDone'))
          .fontSize(13 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.PRIMARY_DARK)
          .backgroundColor(AppTheme.PRIMARY_SOFT)
          .borderRadius(6 * AppTheme.UI_SCALE)
          .padding({ left: 10 * AppTheme.UI_SCALE, right: 10 * AppTheme.UI_SCALE, top: 5 * AppTheme.UI_SCALE, bottom: 5 * AppTheme.UI_SCALE })
          .margin({ top: 12 * AppTheme.UI_SCALE })
      } else {
        if (!this.ruleReady) {
          Text(this.trf('workflow.gateBlocked', [`${this.gapCount()}`]))
            .fontSize(12 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.WARN_TEXT)
            .margin({ top: 12 * AppTheme.UI_SCALE })
        }

        Row() {
          TextInput({ text: this.approvalNote, placeholder: this.tr('workflow.gateNotePlaceholder') })
            .layoutWeight(1)
            .height(38 * AppTheme.UI_SCALE)
            .fontSize(13 * AppTheme.UI_SCALE)
            .backgroundColor(AppTheme.PAGE_BG)
            .borderRadius(AppTheme.RADIUS_SM)
            .enabled(this.ruleReady && !this.approving)
            .onChange((value: string) => {
              this.approvalNote = value;
              this.approvalError = '';
            })
          Button(this.approving ? this.tr('workflow.gateApproving') : this.tr('workflow.gateSubmit'))
            .height(38 * AppTheme.UI_SCALE)
            .fontSize(13 * AppTheme.UI_SCALE)
            .fontColor(Color.White)
            .backgroundColor(AppTheme.PRIMARY)
            .margin({ left: 10 * AppTheme.UI_SCALE })
            .enabled(this.ruleReady && !this.approving && this.approvalNote.trim().length > 0)
            .onClick(() => {
              this.submitRuleApproval();
            })
        }
        .width('100%')
        .margin({ top: 12 * AppTheme.UI_SCALE })
        .alignItems(VerticalAlign.Center)
      }

      if (this.approvalError.length > 0) {
        Text(this.approvalError)
          .fontSize(12 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.DANGER)
          .margin({ top: 8 * AppTheme.UI_SCALE })
      }

      if (this.approvalRecordedAt.length > 0) {
        Text(this.trf('workflow.gateRecorded', [this.approvalRecordedAt]))
          .fontSize(12 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.PRIMARY_DARK)
          .margin({ top: 8 * AppTheme.UI_SCALE })
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
  }

  /** 一组规则缺口：动作名 + 后端给出的英文原因 + 字段清单。 */
  @Builder
  RuleGapBlock(group: RuleGapGroup) {
    Column() {
      Row() {
        Text(this.gapTitle(group).length > 0 ? this.gapTitle(group) : group.reason)
          .fontSize(14 * AppTheme.UI_SCALE)
          .fontWeight(FontWeight.Medium)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .layoutWeight(1)
        Text(this.trf('workflow.fieldCount', [`${group.fields.length}`]))
          .fontSize(12 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.TEXT_TERTIARY)
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      if (this.gapTitle(group).length > 0) {
        Text(group.reason)
          .fontSize(12 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .margin({ top: 6 * AppTheme.UI_SCALE })
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }

      Flex({ wrap: FlexWrap.Wrap }) {
        ForEach(group.fields, (field: string) => {
          Text(field)
            .fontSize(12 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .backgroundColor(AppTheme.PAGE_BG)
            .borderRadius(6 * AppTheme.UI_SCALE)
            .padding({ left: 8 * AppTheme.UI_SCALE, right: 8 * AppTheme.UI_SCALE, top: 4 * AppTheme.UI_SCALE, bottom: 4 * AppTheme.UI_SCALE })
            .margin({ top: 8 * AppTheme.UI_SCALE, right: 8 * AppTheme.UI_SCALE })
        }, (field: string) => field)
      }
      .width('100%')
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ top: 12 * AppTheme.UI_SCALE, bottom: 12 * AppTheme.UI_SCALE })
    .border({ width: { bottom: 1 }, color: AppTheme.BORDER_SOFT })
  }

  /**
   * 一行现状：阶段 · 执行方式 · 已完成实验 · 阻塞项。
   *
   * 原先这四个数是四块等大的统计块，谁也不比谁重要。压成一句之后，页面顶部只剩
   * 「现在到哪一步了」这一个结论，其余数字留在各自的分段里。
   */
  private statusText(): string {
    if (this.stage.length === 0 && this.blockers.length === 0) {
      return '';
    }
    return this.trf('workflow.status', [
      stageLabel(this.lang, this.stage),
      this.automatic ? this.tr('workflow.autoOn') : this.tr('workflow.autoOff'),
      `${this.completedExperiments}`,
      `${this.blockers.length}`
    ]);
  }

  /** 分段导航的项。色点说的是这一段通不通，不是它有多少条。 */
  private railItems(): RailItemSpec[] {
    return [
      {
        key: 'status',
        label: this.tr('workflow.section.status'),
        tone: this.blockers.length === 0 ? 'ok' : 'warn'
      },
      { key: 'rules', label: this.tr('workflow.section.rules'), tone: this.ruleReady ? 'ok' : 'warn' },
      {
        key: 'blockers',
        label: this.tr('workflow.section.blockers'),
        tone: this.openQuestions().length === 0 ? 'ok' : 'warn'
      },
      {
        key: 'actions',
        label: this.tr('workflow.section.actions'),
        tone: this.actions.length === 0 ? 'ok' : 'warn'
      },
      { key: 'ask', label: this.tr('workflow.section.ask'), tone: 'muted' }
    ];
  }

  @Builder
  ErrorBanner() {
    Column() {
      Text(this.tr('common.connectionFailed'))
        .fontSize(15 * AppTheme.UI_SCALE)
        .fontWeight(FontWeight.Medium)
        .fontColor(AppTheme.DANGER)
      Text(this.errorText)
        .fontSize(13 * AppTheme.UI_SCALE)
        .fontColor(AppTheme.DANGER)
        .margin({ top: 8 * AppTheme.UI_SCALE })
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding(20 * AppTheme.UI_SCALE)
    .backgroundColor(AppTheme.DANGER_SOFT)
    .borderRadius(AppTheme.RADIUS)
    .margin({ bottom: 20 * AppTheme.UI_SCALE })
  }

  // ---- 流程时间线 ----

  /** 这个环节做完了吗。 */
  private stepDone(state: string): boolean {
    return state === 'approved' || state === 'complete';
  }

  /** 这个环节被卡住了吗（后端把「缺东西」标成 missing）。 */
  private stepBlocked(state: string): boolean {
    return state === 'missing';
  }

  /** 当前环节的下标：第一个没做完的；全做完返回 -1。 */
  private currentStepIndex(): number {
    for (let index: number = 0; index < this.rows.length; index++) {
      if (!this.stepDone(this.rows[index].state)) {
        return index;
      }
    }
    return -1;
  }

  /** 每个环节对应的那句后端阻塞原文（与 actionText 的映射表同一批，不另造话术）。 */
  private stepBlockerSentence(index: number): string {
    if (index === 1) {
      return 'No data_statistics.json exists.';
    }
    if (index === 2) {
      return 'No persisted research radar exists.';
    }
    if (index === 3) {
      return 'No completed experiments recorded.';
    }
    return '';
  }

  /**
   * 这一步为什么停着。
   *
   * 只在**后端真的报了这条阻塞**时才显示：拿那句原文去阻塞项里对，对上才翻译出来。
   * 对不上就留空 —— 猜出来的原因是编的。
   */
  private stepReason(index: number): string {
    if (index === 0 && !this.rulesApproved) {
      return this.gapCount() > 0
        ? this.trf('workflow.gateBlocked', [`${this.gapCount()}`])
        : this.tr('workflow.stepWaitingConfirm');
    }
    const sentence: string = this.stepBlockerSentence(index);
    if (sentence.length === 0 || !this.blockers.includes(sentence)) {
      return '';
    }
    return this.actionText(sentence, true);
  }

  /** 节点符号：完成打勾、卡住感叹号、当前实心点、未开始空心圈。 */
  private stepGlyph(index: number): string {
    if (this.stepDone(this.rows[index].state)) {
      return '✓';
    }
    if (this.stepBlocked(this.rows[index].state)) {
      return '!';
    }
    return index === this.currentStepIndex() ? '●' : '○';
  }

  /** 节点与文字的色调：ok 完成 / warn 卡住 / current 当前 / muted 未开始。 */
  private stepTone(index: number): string {
    if (this.stepDone(this.rows[index].state)) {
      return 'ok';
    }
    if (this.stepBlocked(this.rows[index].state)) {
      return 'warn';
    }
    return index === this.currentStepIndex() ? 'current' : 'muted';
  }

  private stepNodeColor(index: number): ResourceColor {
    const tone: string = this.stepTone(index);
    if (tone === 'ok' || tone === 'current') {
      return AppTheme.PRIMARY_DARK;
    }
    return tone === 'warn' ? AppTheme.WARN_TEXT : AppTheme.TEXT_TERTIARY;
  }

  private stepNodeBackground(index: number): ResourceColor {
    const tone: string = this.stepTone(index);
    if (tone === 'ok' || tone === 'current') {
      return AppTheme.PRIMARY_SOFT;
    }
    return tone === 'warn' ? AppTheme.WARN_SOFT : AppTheme.PAGE_BG;
  }

  /** 这一步要不要人动手；要的话给什么入口文案，不要就返回空串。 */
  private stepActionLabel(index: number): string {
    if (this.stepBlocked(this.rows[index].state)) {
      return this.tr('workflow.stepViewBlockers');
    }
    if (index === this.currentStepIndex() && index === 0 && !this.rulesApproved) {
      return this.tr('workflow.stepNeedConfirm');
    }
    return '';
  }

  /** 状态摘要条：四个数，一眼看完「走到哪、卡几个、要不要我动手」。 */
  @Builder
  SummaryStrip() {
    Row() {
      this.SummaryCell('workflow.summary.stage', stageLabel(this.lang, this.stage), AppTheme.PRIMARY_DARK)
      this.SummaryCell('workflow.summary.experiments', `${this.completedExperiments}`, AppTheme.TEXT_PRIMARY)
      this.SummaryCell('workflow.summary.blockers', `${this.blockers.length}`,
        this.blockers.length > 0 ? AppTheme.WARN_TEXT : AppTheme.TEXT_PRIMARY)
      this.SummaryCell('workflow.summary.confirm', this.rulesApproved ? '0' : '1',
        this.rulesApproved ? AppTheme.TEXT_PRIMARY : AppTheme.PRIMARY_DARK)
    }
    .width('100%')
    .padding({ top: 14 * AppTheme.UI_SCALE, bottom: 14 * AppTheme.UI_SCALE })
    .alignItems(VerticalAlign.Top)
    .backgroundColor(AppTheme.SURFACE)
    .borderRadius(AppTheme.RADIUS)
    .border({ width: 1, color: AppTheme.BORDER })
  }

  @Builder
  SummaryCell(labelKey: string, value: string, color: ResourceColor) {
    Column() {
      Text(this.tr(labelKey))
        .fontSize(12 * AppTheme.UI_SCALE)
        .fontColor(AppTheme.TEXT_TERTIARY)
      Text(value)
        .fontSize(16 * AppTheme.UI_SCALE)
        .fontWeight(FontWeight.Medium)
        .fontColor(color)
        .margin({ top: 4 * AppTheme.UI_SCALE })
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
    }
    .alignItems(HorizontalAlign.Start)
    .layoutWeight(1)
    .padding({ left: 16 * AppTheme.UI_SCALE, right: 8 * AppTheme.UI_SCALE })
  }

  /**
   * 这个环节现在展开着吗。
   *
   * 空串＝跟随当前阶段（默认只展开它）；`none`＝全部收起；其余＝那一个环节。
   */
  private isStepExpanded(row: ComponentRow, index: number): boolean {
    if (this.expandedStepKey === 'none') {
      return false;
    }
    if (this.expandedStepKey.length === 0) {
      return index === this.currentStepIndex();
    }
    return this.expandedStepKey === row.labelKey;
  }

  /** ForEach 的 key 后缀：展开态必须进 key，否则展开块不会重建。 */
  private stepKeySuffix(row: ComponentRow): string {
    if (this.expandedStepKey === 'none') {
      return 'collapsed';
    }
    if (this.expandedStepKey.length === 0) {
      return 'auto';
    }
    return this.expandedStepKey === row.labelKey ? 'open' : 'closed';
  }

  /** 详情里的一行：标签 + 值。 */
  @Builder
  DetailLine(labelKey: string, value: string, color: ResourceColor) {
    Row() {
      Text(this.tr(labelKey))
        .fontSize(11 * AppTheme.UI_SCALE)
        .fontColor(AppTheme.TEXT_TERTIARY)
        .width(64 * AppTheme.UI_SCALE)
      Text(value)
        .fontSize(12 * AppTheme.UI_SCALE)
        .fontColor(color)
        .layoutWeight(1)
        .maxLines(3)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
    }
    .width('100%')
    .alignItems(VerticalAlign.Top)
    .margin({ top: 6 * AppTheme.UI_SCALE })
  }

  /**
   * 流程时间线。
   *
   * 一条**有方向的流程**：左边节点与连接线，完成打勾、卡住感叹号、当前实心点；
   * 右边是环节名与后端给的状态词，卡住或需要人确认时再补一行原因和入口。
   * 状态词与色调直接取后端枚举的映射（`componentLabel` / `componentTone`），不另立一套。
   *
   * 环节名下面原先还有一行「确认实验规则、目标与约束」那样的说明，已删除：
   * 它只是把环节名换个说法再说一遍，占位置不增信息量。
   */
  @Builder
  Timeline() {
    Column() {
      ForEach(this.rows, (row: ComponentRow, index: number) => {
        Row() {
          // 左列：节点 + 一小段连接线。线不做整条贯穿 —— Row 内撑满高度在不同窗口下不可靠。
          Column() {
            Text(this.stepGlyph(index))
              .fontSize(13 * AppTheme.UI_SCALE)
              .fontColor(this.stepNodeColor(index))
              .backgroundColor(this.stepNodeBackground(index))
              .borderRadius(11 * AppTheme.UI_SCALE)
              .width(22 * AppTheme.UI_SCALE)
              .height(22 * AppTheme.UI_SCALE)
              .textAlign(TextAlign.Center)
            if (index < this.rows.length - 1) {
              Column()
                .width(1 * AppTheme.UI_SCALE)
                .height(26 * AppTheme.UI_SCALE)
                .backgroundColor(AppTheme.BORDER)
            }
          }
          .width(30 * AppTheme.UI_SCALE)
          .alignItems(HorizontalAlign.Center)

          Column() {
            Row() {
              Text(this.tr(row.labelKey))
                .fontSize(14 * AppTheme.UI_SCALE)
                .fontWeight(index === this.currentStepIndex() ? FontWeight.Medium : FontWeight.Normal)
                .fontColor(AppTheme.TEXT_PRIMARY)
                .layoutWeight(1)
              StatusBadge({ text: componentLabel(this.lang, row.state), tone: componentTone(row.state) })
            }
            .width('100%')
            .alignItems(VerticalAlign.Center)
            .onClick(() => {
              // 点环节展开/收起详情；展开态进了 ForEach 的 key，才会真的重建。
              this.expandedStepKey = this.isStepExpanded(row, index) ? 'none' : row.labelKey;
            })

            if (this.stepReason(index).length > 0) {
              Text(this.stepReason(index))
                .fontSize(12 * AppTheme.UI_SCALE)
                .fontColor(AppTheme.WARN_TEXT)
                .width('100%')
                .margin({ top: 6 * AppTheme.UI_SCALE })
            }

            if (this.stepActionLabel(index).length > 0) {
              Text(this.stepActionLabel(index))
                .fontSize(12 * AppTheme.UI_SCALE)
                .fontColor(AppTheme.PRIMARY_DARK)
                .backgroundColor(AppTheme.PRIMARY_SOFT)
                .borderRadius(6 * AppTheme.UI_SCALE)
                .padding({ left: 12 * AppTheme.UI_SCALE, right: 12 * AppTheme.UI_SCALE, top: 6 * AppTheme.UI_SCALE, bottom: 6 * AppTheme.UI_SCALE })
                .margin({ top: 10 * AppTheme.UI_SCALE })
                .onClick(() => {
                  this.section = index === 0 ? 'rules' : 'blockers';
                })
            }

            // 展开的详情。只放后端真有的字段：状态、当前阻塞、下一步。
            // 「输入」与「Agent 已完成的操作」接口里还没有，不编。
            if (this.isStepExpanded(row, index)) {
              Column() {
                this.DetailLine('workflow.detailState', componentLabel(this.lang, row.state), AppTheme.TEXT_PRIMARY)
                // 阻塞那行只在有**具体原因**时出现：通用的「等待人工确认」与上面那行状态重复，不再抄一遍。
                if (this.stepReason(index).length > 0
                  && this.stepReason(index) !== this.tr('workflow.stepWaitingConfirm')) {
                  this.DetailLine('workflow.detailBlocker', this.stepReason(index), AppTheme.WARN_TEXT)
                }
                // 卡住的环节，下一步是「补齐」而不是流程里的下一个环节，那件事由上面的入口按钮负责，这里不写。
                if (this.stepNextName(index).length > 0 && !this.stepBlocked(row.state)) {
                  this.DetailLine('workflow.detailNext', this.stepNextName(index), AppTheme.TEXT_SECONDARY)
                }
              }
              .width('100%')
              .alignItems(HorizontalAlign.Start)
              .margin({ top: 10 * AppTheme.UI_SCALE })
              .padding({ left: 12 * AppTheme.UI_SCALE })
              .border({ width: { left: 2 }, color: AppTheme.BORDER })
            }
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1)
          .margin({ left: 12 * AppTheme.UI_SCALE })
          .padding({ bottom: index < this.rows.length - 1 ? 10 * AppTheme.UI_SCALE : 0 * AppTheme.UI_SCALE })
        }
        .width('100%')
        .alignItems(VerticalAlign.Top)
      }, (row: ComponentRow) => `${row.labelKey}-${row.state}-${this.stepKeySuffix(row)}`)
    }
    .width('100%')
  }

  // ---- 右栏：卡在哪 / 下一步 / Agent 在做什么 ----

  /** 这一步之后是哪一个环节；没有下一步返回空串。 */
  private stepNextName(index: number): string {
    return index < this.rows.length - 1 ? this.tr(this.rows[index + 1].labelKey) : '';
  }

  /** 补齐之前哪一步进不去。用环节顺序推，不编影响面。 */
  private blockedImpact(): string {
    const index: number = this.currentStepIndex();
    if (index < 0 || index >= this.rows.length - 1) {
      return '';
    }
    return this.trf('workflow.blockedImpact', [this.stepNextName(index)]);
  }

  /** 下一步的说明：当前环节要人确认时是「完成后自动开始」，否则是「Agent 会自动执行」。 */
  private nextStepHint(): string {
    const index: number = this.currentStepIndex();
    if (index < 0) {
      return this.tr('workflow.agentAuto');
    }
    const current: string = this.tr(this.rows[index].labelKey);
    const next: string = this.stepNextName(index);
    if (index === 0 && !this.rulesApproved) {
      return next.length > 0
        ? this.trf('workflow.nextAfterCurrent', [current, next])
        : this.tr('workflow.stepWaitingConfirm');
    }
    return next.length > 0 ? this.trf('workflow.nextAuto', [next]) : this.tr('workflow.agentAuto');
  }

  /** 下一步该点哪里：要人确认就去规则关口，否则去后端的待办建议。 */
  private nextStepSection(): string {
    return this.currentStepIndex() === 0 && !this.rulesApproved ? 'rules' : 'actions';
  }

  /**
   * 右栏一：现在卡在哪。
   *
   * 用浅橙底而不是红色错误框 —— 这是「要先补东西」，不是「出错了」。
   * 「缺失内容」列的是**工作区里真的缺的字段**（来自规则缺口），不是编出来的清单。
   */
  @Builder
  BlockedCard() {
    Column() {
      Text(this.tr('workflow.blockedTitle'))
        .fontSize(15 * AppTheme.UI_SCALE)
        .fontWeight(FontWeight.Medium)
        .fontColor(AppTheme.TEXT_PRIMARY)

      if (this.blockers.length === 0) {
        Text(this.tr('workflow.blockedNone'))
          .fontSize(13 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.PRIMARY_DARK)
          .width('100%')
          .margin({ top: 10 * AppTheme.UI_SCALE })
      } else {
        Text(this.actionText(this.blockers[0], true))
          .fontSize(13 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.WARN_TEXT)
          .width('100%')
          .margin({ top: 10 * AppTheme.UI_SCALE })
          .maxLines(3)
          .textOverflow({ overflow: TextOverflow.Ellipsis })

        if (this.ruleGroups.length > 0) {
          Text(this.tr('workflow.blockedMissing'))
            .fontSize(11 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .width('100%')
            .margin({ top: 12 * AppTheme.UI_SCALE })
          Flex({ wrap: FlexWrap.Wrap }) {
            ForEach(this.ruleGroups, (group: RuleGapGroup) => {
              ForEach(group.fields, (field: string) => {
                Text(field)
                  .fontSize(11 * AppTheme.UI_SCALE)
                  .fontColor(AppTheme.TEXT_SECONDARY)
                  .backgroundColor(AppTheme.SURFACE)
                  .borderRadius(6 * AppTheme.UI_SCALE)
                  .padding({ left: 8 * AppTheme.UI_SCALE, right: 8 * AppTheme.UI_SCALE, top: 4 * AppTheme.UI_SCALE, bottom: 4 * AppTheme.UI_SCALE })
                  .margin({ top: 6 * AppTheme.UI_SCALE, right: 6 * AppTheme.UI_SCALE })
              }, (field: string) => `${group.reason}-${field}`)
            }, (group: RuleGapGroup) => group.reason)
          }
          .width('100%')
        }

        if (this.blockedImpact().length > 0) {
          Text(this.blockedImpact())
            .fontSize(12 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .width('100%')
            .margin({ top: 12 * AppTheme.UI_SCALE })
        }

        Row({ space: 10 * AppTheme.UI_SCALE }) {
          Text(this.tr('workflow.blockedFill'))
            .fontSize(12 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.PRIMARY_DARK)
            .backgroundColor(AppTheme.SURFACE)
            .borderRadius(6 * AppTheme.UI_SCALE)
            .padding({ left: 12 * AppTheme.UI_SCALE, right: 12 * AppTheme.UI_SCALE, top: 6 * AppTheme.UI_SCALE, bottom: 6 * AppTheme.UI_SCALE })
            .onClick(() => {
              this.section = 'rules';
            })
          Text(this.tr('workflow.blockedCheckAgent'))
            .fontSize(12 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .backgroundColor(AppTheme.SURFACE)
            .borderRadius(6 * AppTheme.UI_SCALE)
            .padding({ left: 12 * AppTheme.UI_SCALE, right: 12 * AppTheme.UI_SCALE, top: 6 * AppTheme.UI_SCALE, bottom: 6 * AppTheme.UI_SCALE })
            .onClick(() => {
              // 只把问题填好并跳到问答段，不替人发出去 —— 发一次是要花积分的。
              this.question = this.tr('workflow.agentCheckPrompt');
              this.section = 'ask';
            })
        }
        .width('100%')
        .margin({ top: 14 * AppTheme.UI_SCALE })
      }
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
    .padding(20 * AppTheme.UI_SCALE)
    .backgroundColor(this.blockers.length > 0 ? AppTheme.WARN_SOFT : AppTheme.SURFACE)
    .borderRadius(AppTheme.RADIUS)
    .border({ width: 1, color: AppTheme.BORDER })
  }

  /** 右栏二：下一步会发生什么，以及现在该点哪里。 */
  @Builder
  NextStepCard() {
    CardPanel({ title: this.tr('workflow.nextTitle') }) {
      Column() {
        Text(this.nextStepHint())
          .fontSize(13 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .width('100%')
        Text(this.automatic ? this.tr('workflow.autoOn') : this.tr('workflow.autoOff'))
          .fontSize(11 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .width('100%')
          .margin({ top: 6 * AppTheme.UI_SCALE })
        Row() {
          Text(this.currentStepIndex() === 0 && !this.rulesApproved
            ? this.tr('workflow.stepNeedConfirm')
            : this.tr('workflow.nextViewActions'))
            .fontSize(12 * AppTheme.UI_SCALE)
            .fontColor(Color.White)
            .backgroundColor(AppTheme.PRIMARY)
            .borderRadius(6 * AppTheme.UI_SCALE)
            .padding({ left: 14 * AppTheme.UI_SCALE, right: 14 * AppTheme.UI_SCALE, top: 8 * AppTheme.UI_SCALE, bottom: 8 * AppTheme.UI_SCALE })
            .onClick(() => {
              this.section = this.nextStepSection();
            })
        }
        .width('100%')
        .margin({ top: 14 * AppTheme.UI_SCALE })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
  }

  /** 右栏三：Agent 现在在做什么 —— 用户是在看它推进，不是在手动跑每一步。 */
  @Builder
  AgentStateCard() {
    CardPanel({ title: this.tr('workflow.agentState') }) {
      Column() {
        Text(this.rulesApproved ? this.tr('workflow.agentAuto') : this.tr('workflow.agentWaitingRules'))
          .fontSize(13 * AppTheme.UI_SCALE)
          .fontColor(this.rulesApproved ? AppTheme.PRIMARY_DARK : AppTheme.WARN_TEXT)
          .width('100%')
        Row() {
          Text(this.tr('workflow.autoExecution'))
            .fontSize(11 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .layoutWeight(1)
          Text(this.automatic ? this.tr('workflow.autoOn') : this.tr('workflow.autoOff'))
            .fontSize(11 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.TEXT_PRIMARY)
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)
        .margin({ top: 10 * AppTheme.UI_SCALE })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
  }

  @Builder
  BlockerList() {
    Column() {
      ForEach(this.openQuestions(), (item: string, index: number) => {
        Row() {
          Text(`${index + 1}`)
            .fontSize(12 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.DANGER)
            .backgroundColor(AppTheme.DANGER_SOFT)
            .borderRadius(11 * AppTheme.UI_SCALE)
            .width(22 * AppTheme.UI_SCALE)
            .height(22 * AppTheme.UI_SCALE)
            .textAlign(TextAlign.Center)
          Text(item)
            .fontSize(13 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .layoutWeight(1)
            .margin({ left: 12 * AppTheme.UI_SCALE })
        }
        .width('100%')
        .alignItems(VerticalAlign.Top)
        .padding({ top: 10 * AppTheme.UI_SCALE, bottom: 10 * AppTheme.UI_SCALE })
      }, (item: string, index: number) => `${index}-${item}`)
    }
    .width('100%')
  }

  @Builder
  ActionList() {
    Column() {
      ForEach(this.actions, (item: NextAction) => {
        Row() {
          StatusBadge({ text: priorityLabel(this.lang, item.priority), tone: priorityTone(item.priority) })
          Column() {
            Text(this.actionText(item.action))
              .fontSize(14 * AppTheme.UI_SCALE)
              .fontColor(AppTheme.TEXT_PRIMARY)
            Text(this.actionText(item.evidence, true))
              .fontSize(12 * AppTheme.UI_SCALE)
              .fontColor(AppTheme.TEXT_TERTIARY)
              .margin({ top: 6 * AppTheme.UI_SCALE })
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1)
          .margin({ left: 12 * AppTheme.UI_SCALE })
        }
        .width('100%')
        .alignItems(VerticalAlign.Top)
        .padding({ top: 12 * AppTheme.UI_SCALE, bottom: 12 * AppTheme.UI_SCALE })
      }, (item: NextAction) => `${item.priority}-${item.action}`)
    }
    .width('100%')
  }

  /** 提问区：输入框 + 回答 / 错误 / 进行中三种状态。 */
  @Builder
  AskPanel() {
    Column() {
      Row() {
        Text(this.tr('auth.balance'))
          .fontSize(12 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .layoutWeight(1)
        Text(this.creditBalance.toFixed(2))
          .fontSize(13 * AppTheme.UI_SCALE)
          .fontWeight(FontWeight.Medium)
          .fontColor(AppTheme.PRIMARY_DARK)
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .margin({ bottom: 10 * AppTheme.UI_SCALE })

      Row() {
        TextInput({ text: this.question, placeholder: this.tr('workflow.askPlaceholder') })
          .layoutWeight(1)
          .height(40 * AppTheme.UI_SCALE)
          .fontSize(14 * AppTheme.UI_SCALE)
          .backgroundColor(AppTheme.PAGE_BG)
          .onChange((value: string) => {
            this.question = value;
          })
        Button(this.tr('workflow.ask'))
          .height(40 * AppTheme.UI_SCALE)
          .margin({ left: 12 * AppTheme.UI_SCALE })
          .fontSize(14 * AppTheme.UI_SCALE)
          .fontColor(Color.White)
          .backgroundColor(AppTheme.PRIMARY)
          .enabled(!this.asking)
          .onClick(() => {
            this.ask();
          })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      if (this.askError.length > 0) {
        Text(this.askError)
          .fontSize(12 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.DANGER)
          .width('100%')
          .margin({ top: 12 * AppTheme.UI_SCALE })
      }

      if (this.asking) {
        Text(this.tr('workflow.asking'))
          .fontSize(13 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .width('100%')
          .margin({ top: 14 * AppTheme.UI_SCALE })
      } else if (this.answer.length > 0) {
        Column() {
          Text(this.answer)
            .fontSize(13 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.TEXT_PRIMARY)
            .width('100%')
          Text(this.trf('workflow.answerMeta', [this.answerModel, `${this.answerTurns}`]))
            .fontSize(11 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .margin({ top: 10 * AppTheme.UI_SCALE })
        }
        .alignItems(HorizontalAlign.Start)
        .width('100%')
        .padding(16 * AppTheme.UI_SCALE)
        .backgroundColor(AppTheme.PAGE_BG)
        .borderRadius(AppTheme.RADIUS_SM)
        .margin({ top: 14 * AppTheme.UI_SCALE })
      }
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
  }

  build() {
    Column({ space: 20 * AppTheme.UI_SCALE }) {
      PageHeader({
        // 标题不再放页面顶部：左侧面板里高亮的那一项已经写着「工作流」。
        status: this.statusText(),
        onRefresh: () => {
          this.load();
        }
      })

      // 进页面直接给状态：一条摘要条四个数。原先标题下面还有一句「Agent 正在推进…」，
      // 它没有一个数字、只是把这一页介绍了一遍，已删除 —— 状态本身说明问题。
      this.SummaryStrip()

      if (this.errorText.length > 0) {
        this.ErrorBanner()
      }

      SectionRail({
        items: this.railItems(),
        active: this.section,
        onSelect: (key: string) => {
          this.section = key;
        }
      })

      if (this.section === 'rules') {
        CardPanel({
          title: this.tr('workflow.ruleGapsTitle')
        }) {
          // 必填字段的完成度用条表示：文字「24 个必填字段、0 项待办」要读两遍才明白。
          ProgressBar({
            label: this.tr('workflow.requiredFields'),
            current: this.requiredFieldCount - this.uniqueFieldCount(),
            total: this.requiredFieldCount
          })

          if (this.ruleGroups.length === 0) {
            EmptyHint({ text: this.tr('workflow.noRuleGaps') })
          } else {
            Column() {
              ForEach(this.ruleGroups, (group: RuleGapGroup) => {
                this.RuleGapBlock(group)
              }, (group: RuleGapGroup) => `${group.reason}-${group.fields.join(',')}`)
            }
            .width('100%')
          }

          this.EvidenceGate()
          this.RuleGate()
        }
      } else if (this.section === 'blockers') {
        CardPanel({
          title: this.tr('workflow.blockers')
        }) {
          if (this.openQuestions().length === 0) {
            EmptyHint({ text: this.tr('workflow.noOpenQuestions') })
          } else {
            Text(this.trf('workflow.blockersSubtitle', [`${this.openQuestions().length}`]))
              .fontSize(13 * AppTheme.UI_SCALE)
              .fontColor(AppTheme.TEXT_SECONDARY)
              .width('100%')
              .margin({ bottom: 6 * AppTheme.UI_SCALE })
            this.BlockerList()
          }
        }
      } else if (this.section === 'actions') {
        CardPanel({
          title: this.tr('workflow.actions')
        }) {
          Text(this.tr('workflow.actionHint'))
            .fontSize(12 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .width('100%')
            .margin({ bottom: 8 * AppTheme.UI_SCALE })
          if (this.actions.length === 0) {
            EmptyHint({ text: this.tr('workflow.noActions') })
          } else {
            this.ActionList()
          }
        }
      } else if (this.section === 'ask') {
        CardPanel({
          title: this.tr('workflow.askTitle')
        }) {
          this.AskPanel()
        }
      } else if (this.compactFlow) {
        // 窄窗口：右栏挪到时间线下面，一列到底。
        Column({ space: 16 * AppTheme.UI_SCALE }) {
          CardPanel({
            title: this.tr('workflow.timeline')
          }) {
            this.Timeline()
          }
          this.BlockedCard()
          this.NextStepCard()
          this.AgentStateCard()
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
      } else {
        // 宽窗口：左 65% 时间线、右 35% 「卡在哪 / 下一步 / Agent 在做什么」。
        Row({ space: 16 * AppTheme.UI_SCALE }) {
          Column() {
            CardPanel({
              title: this.tr('workflow.timeline')
            }) {
              this.Timeline()
            }
          }
          .layoutWeight(2)
          .alignItems(HorizontalAlign.Start)

          Column({ space: 16 * AppTheme.UI_SCALE }) {
            this.BlockedCard()
            this.NextStepCard()
            this.AgentStateCard()
          }
          .layoutWeight(1)
          .alignItems(HorizontalAlign.Start)
        }
        .width('100%')
        .alignItems(VerticalAlign.Top)
      }

      if (this.loading) {
        Text(this.tr('common.loading'))
          .fontSize(12 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .margin({ top: 12 * AppTheme.UI_SCALE })
      }
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
    .onAreaChange((_old: Area, newArea: Area) => {
      // 断点取 900：右栏 1/3 要有 300vp 才装得下那几张卡，再窄就挤成读不下去的窄条，
      // 不如改上下排。（侧栏加宽后内容区少了一百多 vp，原来那个 1000 在常见窗口里
      // 会把两栏直接关掉，所以往下调到 900。）
      const compact: boolean = Number(newArea.width) < 900;
      if (this.compactFlow !== compact) {
        this.compactFlow = compact;
      }
    })
  }
}
