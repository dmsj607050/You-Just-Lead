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
import { CardPanel, EmptyHint, PageHeader, StatTileGrid, StatusBadge } from './Widgets';

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
  @State loading: boolean = false;
  @State errorText: string = '';
  @State stage: string = '';
  @State automatic: boolean = false;
  @State completedExperiments: number = 0;
  @State blockers: string[] = [];
  @State rows: ComponentRow[] = [];
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
    if (this.pendingQuestion.length > 0) {
      this.question = this.pendingQuestion;
    }
    this.load();
  }

  /** 取文案：读一次 lang，让调用它的节点订阅语言变化。 */
  private tr(key: string): string {
    return tFor(this.lang, key);
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
        .margin({ top: 16, bottom: 16 })

      Row() {
        Column() {
          Text(this.tr('workflow.evidenceTitle'))
            .fontSize(15)
            .fontWeight(FontWeight.Medium)
            .fontColor(AppTheme.TEXT_PRIMARY)
          Text(this.tr('workflow.evidenceSubtitle'))
            .fontSize(12)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .margin({ top: 6 })
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)

        if (this.evidenceSupported) {
          Text(this.evidenceOpen ? this.tr('workflow.evidenceClose') : this.tr('workflow.evidenceOpen'))
            .fontSize(13)
            .fontColor(AppTheme.PRIMARY)
            .padding({ left: 12, right: 12, top: 6, bottom: 6 })
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
          .fontSize(12)
          .fontColor(AppTheme.WARN_TEXT)
          .width('100%')
          .margin({ top: 10 })
      } else if (!this.evidenceOpen) {
        Text(this.trf('workflow.evidenceSummary', [
          `${this.evidenceRequiredCount}`, `${this.evidenceMissingValue}`, `${this.evidenceMissingAnchor}`
        ]))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .width('100%')
          .margin({ top: 10 })
      }

      if (this.evidenceDone.length > 0) {
        Text(this.evidenceDone)
          .fontSize(12)
          .fontColor(AppTheme.PRIMARY_DARK)
          .width('100%')
          .margin({ top: 10 })
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
    Column({ space: 8 }) {
      Text(this.tr('workflow.evidenceGateHint'))
        .fontSize(12)
        .fontColor(AppTheme.TEXT_TERTIARY)
        .width('100%')

      Text(this.tr('workflow.evidenceSourceType'))
        .fontSize(12)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .width('100%')
      TextInput({ text: this.evidenceSourceType, placeholder: this.tr('workflow.evidenceSourceTypeHint') })
        .fontSize(13)
        .width('100%')
        .height(38)
        .onChange((value: string) => {
          this.evidenceSourceType = value;
        })

      Text(this.tr('workflow.evidenceSourceLocator'))
        .fontSize(12)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .width('100%')
      TextInput({ text: this.evidenceSourceLocator, placeholder: this.tr('workflow.evidenceSourceLocatorHint') })
        .fontSize(13)
        .width('100%')
        .height(38)
        .onChange((value: string) => {
          this.evidenceSourceLocator = value;
        })

      Text(this.tr('workflow.evidenceReviewedAt'))
        .fontSize(12)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .width('100%')
      TextInput({ text: this.evidenceReviewedAt, placeholder: this.tr('workflow.evidenceReviewedAtHint') })
        .fontSize(13)
        .width('100%')
        .height(38)
        .onChange((value: string) => {
          this.evidenceReviewedAt = value;
        })

      Row() {
        Text(this.tr('workflow.evidenceFieldColumn'))
          .fontSize(13)
          .fontWeight(FontWeight.Medium)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .layoutWeight(1)
        Text(this.trf('workflow.evidenceSummary', [
          `${this.evidenceRequiredCount}`, `${this.evidenceMissingValue}`, `${this.evidenceMissingAnchor}`
        ]))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
      }
      .width('100%')
      .margin({ top: 8 })

      ForEach(this.evidenceRows, (row: EvidenceRow, index: number) => {
        this.EvidenceRowLine(row, index)
      }, (row: EvidenceRow) => `${row.field}-${row.flag}-${row.choice}-${row.hasAnchor}`)

      if (this.evidenceError.length > 0) {
        Text(this.evidenceError)
          .fontSize(12)
          .fontColor(AppTheme.DANGER)
          .width('100%')
          .margin({ top: 6 })
      }

      Row({ space: 12 }) {
        Text(this.evidenceSubmitting ? this.tr('workflow.evidenceSubmitting') : this.tr('workflow.evidenceSubmit'))
          .fontSize(13)
          .fontColor(Color.White)
          .backgroundColor(AppTheme.PRIMARY)
          .borderRadius(AppTheme.RADIUS_SM)
          .padding({ left: 16, right: 16, top: 8, bottom: 8 })
          .enabled(!this.evidenceSubmitting)
          .opacity(this.evidenceSubmitting ? 0.6 : 1)
          .onClick(() => {
            this.sendRuleEvidence();
          })
        Text(this.tr('workflow.evidenceCancel'))
          .fontSize(13)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .padding({ left: 8, right: 8, top: 8, bottom: 8 })
          .onClick(() => {
            this.evidenceOpen = false;
            this.evidenceError = '';
          })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .margin({ top: 10 })
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .margin({ top: 14 })
  }

  /** 允许 / 不允许：布尔字段只能人选，未选就是没确认。 */
  @Builder
  BooleanChips(row: EvidenceRow, index: number) {
    Row({ space: 8 }) {
      Text(this.tr('workflow.evidenceYes'))
        .fontSize(12)
        .fontColor(row.flag === true ? AppTheme.PRIMARY_DARK : AppTheme.TEXT_SECONDARY)
        .backgroundColor(row.flag === true ? AppTheme.PRIMARY_SOFT : AppTheme.PAGE_BG)
        .borderRadius(6)
        .padding({ left: 10, right: 10, top: 4, bottom: 4 })
        .onClick(() => {
          row.flag = true;
          this.updateEvidenceRow(index, row);
        })
      Text(this.tr('workflow.evidenceNo'))
        .fontSize(12)
        .fontColor(row.flag === false ? AppTheme.PRIMARY_DARK : AppTheme.TEXT_SECONDARY)
        .backgroundColor(row.flag === false ? AppTheme.PRIMARY_SOFT : AppTheme.PAGE_BG)
        .borderRadius(6)
        .padding({ left: 10, right: 10, top: 4, bottom: 4 })
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
    Row({ space: 8 }) {
      ForEach(options, (option: string) => {
        Text(option)
          .fontSize(12)
          .fontColor(row.choice === option ? AppTheme.PRIMARY_DARK : AppTheme.TEXT_SECONDARY)
          .backgroundColor(row.choice === option ? AppTheme.PRIMARY_SOFT : AppTheme.PAGE_BG)
          .borderRadius(6)
          .padding({ left: 10, right: 10, top: 4, bottom: 4 })
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
          .fontSize(13)
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
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .width(84)
        if (row.hasValue) {
          Text(row.valueText !== null ? row.valueText : '—')
            .fontSize(12)
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
            .fontSize(12)
            .layoutWeight(1)
            .height(36)
            .onChange((value: string) => {
              row.valueDraft = value;
            })
        } else {
          Text(this.tr('workflow.evidenceLockedValue'))
            .fontSize(12)
            .fontColor(AppTheme.WARN_TEXT)
            .layoutWeight(1)
        }
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .margin({ top: 8 })

      Row() {
        Text(this.tr('workflow.evidenceAnchorColumn'))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .width(84)
        TextInput({ text: row.anchor, placeholder: this.tr('workflow.evidenceAnchorHint') })
          .fontSize(12)
          .layoutWeight(1)
          .height(36)
          .onChange((value: string) => {
            row.anchor = value;
          })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .margin({ top: 6 })
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ top: 12, bottom: 12 })
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
        .margin({ top: 16, bottom: 16 })

      Text(this.tr('workflow.gateTitle'))
        .fontSize(15)
        .fontWeight(FontWeight.Medium)
        .fontColor(AppTheme.TEXT_PRIMARY)
      Text(this.tr('workflow.gateScope'))
        .fontSize(12)
        .fontColor(AppTheme.TEXT_TERTIARY)
        .margin({ top: 6 })

      if (this.rulesApproved) {
        Text(this.tr('workflow.gateDone'))
          .fontSize(13)
          .fontColor(AppTheme.PRIMARY_DARK)
          .backgroundColor(AppTheme.PRIMARY_SOFT)
          .borderRadius(6)
          .padding({ left: 10, right: 10, top: 5, bottom: 5 })
          .margin({ top: 12 })
      } else {
        if (!this.ruleReady) {
          Text(this.trf('workflow.gateBlocked', [`${this.gapCount()}`]))
            .fontSize(12)
            .fontColor(AppTheme.WARN_TEXT)
            .margin({ top: 12 })
        }

        Row() {
          TextInput({ text: this.approvalNote, placeholder: this.tr('workflow.gateNotePlaceholder') })
            .layoutWeight(1)
            .height(38)
            .fontSize(13)
            .backgroundColor(AppTheme.PAGE_BG)
            .borderRadius(AppTheme.RADIUS_SM)
            .enabled(this.ruleReady && !this.approving)
            .onChange((value: string) => {
              this.approvalNote = value;
              this.approvalError = '';
            })
          Button(this.approving ? this.tr('workflow.gateApproving') : this.tr('workflow.gateSubmit'))
            .height(38)
            .fontSize(13)
            .fontColor(Color.White)
            .backgroundColor(AppTheme.PRIMARY)
            .margin({ left: 10 })
            .enabled(this.ruleReady && !this.approving && this.approvalNote.trim().length > 0)
            .onClick(() => {
              this.submitRuleApproval();
            })
        }
        .width('100%')
        .margin({ top: 12 })
        .alignItems(VerticalAlign.Center)
      }

      if (this.approvalError.length > 0) {
        Text(this.approvalError)
          .fontSize(12)
          .fontColor(AppTheme.DANGER)
          .margin({ top: 8 })
      }

      if (this.approvalRecordedAt.length > 0) {
        Text(this.trf('workflow.gateRecorded', [this.approvalRecordedAt]))
          .fontSize(12)
          .fontColor(AppTheme.PRIMARY_DARK)
          .margin({ top: 8 })
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
          .fontSize(14)
          .fontWeight(FontWeight.Medium)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .layoutWeight(1)
        Text(this.trf('workflow.fieldCount', [`${group.fields.length}`]))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      if (this.gapTitle(group).length > 0) {
        Text(group.reason)
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .margin({ top: 6 })
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }

      Flex({ wrap: FlexWrap.Wrap }) {
        ForEach(group.fields, (field: string) => {
          Text(field)
            .fontSize(12)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .backgroundColor(AppTheme.PAGE_BG)
            .borderRadius(6)
            .padding({ left: 8, right: 8, top: 4, bottom: 4 })
            .margin({ top: 8, right: 8 })
        }, (field: string) => field)
      }
      .width('100%')
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ top: 12, bottom: 12 })
    .border({ width: { bottom: 1 }, color: AppTheme.BORDER_SOFT })
  }

  @Builder
  ErrorBanner() {
    Column() {
      Text(this.tr('common.connectionFailed'))
        .fontSize(15)
        .fontWeight(FontWeight.Medium)
        .fontColor(AppTheme.DANGER)
      Text(this.errorText)
        .fontSize(13)
        .fontColor(AppTheme.DANGER)
        .margin({ top: 8 })
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding(20)
    .backgroundColor(AppTheme.DANGER_SOFT)
    .borderRadius(AppTheme.RADIUS)
    .margin({ bottom: 20 })
  }

  @Builder
  ComponentList() {
    Column() {
      ForEach(this.rows, (row: ComponentRow) => {
        Row() {
          Text(this.tr(row.labelKey))
            .fontSize(14)
            .fontColor(AppTheme.TEXT_PRIMARY)
            .layoutWeight(1)
          StatusBadge({ text: componentLabel(this.lang, row.state), tone: componentTone(row.state) })
        }
        .width('100%')
        .padding({ top: 12, bottom: 12 })
        .border({ width: { bottom: 1 }, color: AppTheme.BORDER_SOFT })
      }, (row: ComponentRow) => `${row.labelKey}-${row.state}`)
    }
    .width('100%')
  }

  @Builder
  BlockerList() {
    Column() {
      ForEach(this.openQuestions(), (item: string, index: number) => {
        Row() {
          Text(`${index + 1}`)
            .fontSize(12)
            .fontColor(AppTheme.DANGER)
            .backgroundColor(AppTheme.DANGER_SOFT)
            .borderRadius(11)
            .width(22)
            .height(22)
            .textAlign(TextAlign.Center)
          Text(item)
            .fontSize(13)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .layoutWeight(1)
            .margin({ left: 12 })
        }
        .width('100%')
        .alignItems(VerticalAlign.Top)
        .padding({ top: 10, bottom: 10 })
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
            Text(item.action)
              .fontSize(14)
              .fontColor(AppTheme.TEXT_PRIMARY)
            Text(item.evidence)
              .fontSize(12)
              .fontColor(AppTheme.TEXT_TERTIARY)
              .margin({ top: 6 })
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1)
          .margin({ left: 12 })
        }
        .width('100%')
        .alignItems(VerticalAlign.Top)
        .padding({ top: 12, bottom: 12 })
      }, (item: NextAction) => `${item.priority}-${item.action}`)
    }
    .width('100%')
  }

  /** 提问区：输入框 + 回答 / 错误 / 进行中三种状态。 */
  @Builder
  AskPanel() {
    Column() {
      Row() {
        TextInput({ text: this.question, placeholder: this.tr('workflow.askPlaceholder') })
          .layoutWeight(1)
          .height(40)
          .fontSize(14)
          .backgroundColor(AppTheme.PAGE_BG)
          .onChange((value: string) => {
            this.question = value;
          })
        Button(this.tr('workflow.ask'))
          .height(40)
          .margin({ left: 12 })
          .fontSize(14)
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
          .fontSize(12)
          .fontColor(AppTheme.DANGER)
          .width('100%')
          .margin({ top: 12 })
      }

      if (this.asking) {
        Text(this.tr('workflow.asking'))
          .fontSize(13)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .width('100%')
          .margin({ top: 14 })
      } else if (this.answer.length > 0) {
        Column() {
          Text(this.answer)
            .fontSize(13)
            .fontColor(AppTheme.TEXT_PRIMARY)
            .width('100%')
          Text(this.trf('workflow.answerMeta', [this.answerModel, `${this.answerTurns}`]))
            .fontSize(11)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .margin({ top: 10 })
        }
        .alignItems(HorizontalAlign.Start)
        .width('100%')
        .padding(16)
        .backgroundColor(AppTheme.PAGE_BG)
        .borderRadius(AppTheme.RADIUS_SM)
        .margin({ top: 14 })
      }
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
  }

  build() {
    Column({ space: 20 }) {
      PageHeader({
        title: this.tr('workflow.title'),
        subtitle: this.tr('workflow.subtitle'),
        onRefresh: () => {
          this.load();
        }
      })

      if (this.errorText.length > 0) {
        this.ErrorBanner()
      }

      StatTileGrid({
        items: [
          {
            label: this.tr('workflow.currentStage'),
            value: stageLabel(this.lang, this.stage),
            hint: this.tr('workflow.currentStageHint')
          },
          {
            label: this.tr('workflow.autoRun'),
            value: this.automatic ? this.tr('workflow.autoOn') : this.tr('workflow.autoOff'),
            hint: this.tr('workflow.autoHint')
          },
          {
            label: this.tr('workflow.completedExperiments'),
            value: `${this.completedExperiments}`,
            hint: this.tr('workflow.completedExperimentsHint')
          },
          {
            label: this.tr('workflow.blockers'),
            value: `${this.blockers.length}`,
            hint: this.tr('workflow.blockersHint')
          }
        ]
      })

      CardPanel({
        title: this.tr('workflow.componentStatus'),
        subtitle: this.tr('workflow.componentStatusHint')
      }) {
        this.ComponentList()
      }

      CardPanel({
        title: this.tr('workflow.ruleGapsTitle'),
        subtitle: this.trf('workflow.rulesSummary', [
          this.ruleReady ? this.tr('workflow.ruleReady') : this.tr('workflow.ruleNotReady'),
          `${this.requiredFieldCount}`, `${this.gapCount()}`, `${this.uniqueFieldCount()}`, this.ruleProfile
        ])
      }) {
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

      CardPanel({
        title: this.tr('workflow.blockers'),
        subtitle: this.trf('workflow.blockersSubtitle', [`${this.openQuestions().length}`])
      }) {
        if (this.openQuestions().length === 0) {
          EmptyHint({ text: this.tr('workflow.noOpenQuestions') })
        } else {
          this.BlockerList()
        }
      }

      CardPanel({
        title: this.tr('workflow.actions'),
        subtitle: this.tr('workflow.actionsHint')
      }) {
        if (this.actions.length === 0) {
          EmptyHint({ text: this.tr('workflow.noActions') })
        } else {
          this.ActionList()
        }
      }

      CardPanel({
        title: this.tr('workflow.askTitle'),
        subtitle: this.tr('workflow.askSubtitle')
      }) {
        this.AskPanel()
      }

      if (this.loading) {
        Text(this.tr('common.loading'))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .margin({ top: 12 })
      }
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
  }
}
