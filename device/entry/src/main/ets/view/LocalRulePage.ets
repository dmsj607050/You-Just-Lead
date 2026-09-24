import { common } from '@kit.AbilityKit';
import { picker } from '@kit.CoreFileKit';
import AppTheme from '../common/AppTheme';
import { describeError, shortHash, todayLocal } from '../common/Format';
import { tFor, tfFor } from '../common/I18n';
import {
  DIRECTION_OPTIONS,
  GateApproval,
  GateApprovalOutcome,
  GateFieldInput,
  GateOutcome,
  GateSource,
  RUNTIME_OUTPUT_OPTIONS,
  SPEC_FILE,
  applyOfficialEvidence,
  approveRulesSpec,
  currentApproval,
  currentSource,
  gateSupported,
  importSpecText,
  readSpec
} from '../common/LocalRuleGate';
import { RuleReadiness, ruleReadiness } from '../common/LocalRules';
import { LocalWorkspace, readPickedText } from '../common/LocalWorkspace';
import { YamlMap } from '../common/YamlLite';
import { CardPanel, EmptyHint, KeyValueRow, ProgressBar, StatusBadge } from './Widgets';

/**
 * 端侧规则关口（整页）。
 *
 * 与「工作流」页里的在线版是同一件事的两条路径：这一页完全不经过后端，
 * 直接读写工作区里的 `competition_spec.yaml`，所以后端没起来时规则关口也走得通。
 * 交互刻意与在线版保持一致（同一种控件、同一套文案、同样"只提交人实际填的东西"），
 * 免得同一件事在两端学两遍。
 */

/** 表单里的一行。`anchor` / `valueDraft` 是人正在敲的内容，不需要触发重绘。 */
interface GateRow {
  field: string;
  kind: string;
  /** 规格里的现值，只读展示。 */
  valueText: string;
  hasValue: boolean;
  anchor: string;
  hasAnchor: boolean;
  /** 布尔字段的选择；null 表示没选。 */
  flag: boolean | null;
  /** 二选一字段的选择。 */
  choice: string;
  valueDraft: string;
}

@Component
export struct LocalRulePage {
  /**
   * 当前语言。ArkUI 只重建读到状态变量的节点，所以本组件所有文案都走 this.tr()，
   * 由它读一次 this.lang，等于把用到的节点登记到语言变化上。
   */
  @StorageLink('lang') lang: string = 'zh';
  /** 返回上一屏。 */
  onBack: () => void = () => {
  };

  @State workspaceRoot: string = '';
  @State ready: boolean = false;
  @State specPresent: boolean = false;
  @State supported: boolean = false;
  @State profile: string = '';
  @State specHash: string = '';
  @State sourceType: string = '';
  @State sourceLocator: string = '';
  @State reviewedAt: string = '';
  @State rows: GateRow[] = [];
  @State requiredCount: number = 0;
  @State missingValue: number = 0;
  @State missingAnchor: number = 0;
  /** 缺口总数与"是否已就绪"，用来决定批准关口能不能按。 */
  @State gapCount: number = 0;
  /** 规格里的批准状态：还需要人工确认时为 true。 */
  @State approvalRequired: boolean = true;
  @State approvedAt: string = '';
  @State approvedNote: string = '';
  /** 本次要提交的复核说明。 */
  @State noteDraft: string = '';
  @State approving: boolean = false;
  @State approvalDone: string = '';
  /** 页级错误（读规格、导入规格）——在页面顶部。 */
  @State errorText: string = '';
  /**
   * 表单级错误：必须显示在**按钮旁边**。
   *
   * 这一页很长（19 行字段），按钮在底部而页级提示在顶部，实测点了按钮看不到任何提示，
   * 只看到内容整体挪了一下。和在线版一样把错误贴在各自的表单里才说得通。
   */
  @State evidenceError: string = '';
  @State approvalError: string = '';
  @State doneText: string = '';
  @State busy: boolean = false;

  aboutToAppear(): void {
    this.reload();
  }

  /** 取文案：读一次 lang，让调用它的节点订阅语言变化。 */
  private tr(key: string): string {
    return tFor(this.lang, key);
  }

  /** 带占位符取文案。 */
  private trf(key: string, args: string[]): string {
    return tfFor(this.lang, key, args);
  }

  private abilityContext(): common.UIAbilityContext {
    return this.getUIContext().getHostContext() as common.UIAbilityContext;
  }

  /**
   * 重新读一遍工作区与规格。
   *
   * 人已经在表单里填过东西时，只刷新顶部的缺口计数与规格指纹，不覆盖正在填的行。
   */
  async reload(): Promise<void> {
    this.errorText = '';
    this.evidenceError = '';
    this.approvalError = '';
    try {
      const workspace: LocalWorkspace = await LocalWorkspace.restore(this.abilityContext());
      this.workspaceRoot = workspace.root;
      this.ready = workspace.hasRoot() && workspace.readable;
      if (!this.ready) {
        this.reset();
        return;
      }
      this.specPresent = workspace.exists(SPEC_FILE);
      if (!this.specPresent) {
        this.reset();
        return;
      }
      const spec: YamlMap = readSpec(workspace);
      this.specHash = shortHash(await LocalWorkspace.sha256Of(workspace.join(SPEC_FILE)));
      this.supported = gateSupported(spec);
      const readiness: RuleReadiness = ruleReadiness(spec);
      this.profile = readiness.profile;
      this.requiredCount = readiness.requiredFieldCount;
      this.missingValue = readiness.missingValueCount;
      this.missingAnchor = readiness.missingAnchorCount;
      this.gapCount = readiness.gapCount;
      const approval: GateApproval = currentApproval(spec);
      this.approvalRequired = approval.required;
      this.approvedAt = approval.approvedAt;
      this.approvedNote = approval.note;
      if (!this.supported) {
        this.rows = [];
        return;
      }
      if (this.rows.length === this.requiredCount) {
        return;
      }
      const source: GateSource = currentSource(spec);
      this.sourceType = source.sourceType.length > 0 ? source.sourceType : this.sourceType;
      this.sourceLocator = source.sourceLocator.length > 0 ? source.sourceLocator : this.sourceLocator;
      this.reviewedAt = source.reviewedAt.length > 0 ? source.reviewedAt
        : (this.reviewedAt.length > 0 ? this.reviewedAt : todayLocal());
      const rows: GateRow[] = [];
      for (const item of readiness.fields) {
        rows.push({
          field: item.field,
          kind: item.kind,
          valueText: item.value,
          hasValue: item.hasValue,
          anchor: item.anchor,
          hasAnchor: item.hasAnchor,
          // 值缺失时不替人猜：布尔与枚举都留空，等人在官方原文里读到再选。
          flag: item.value === 'true' ? true : (item.value === 'false' ? false : null),
          choice: item.kind === 'direction' && item.value.length > 0 ? item.value
            : (item.kind === 'runtime_output' && item.value.length > 0 && item.value !== 'unresolved'
              ? item.value : ''),
          valueDraft: ''
        });
      }
      this.rows = rows;
    } catch (err) {
      this.errorText = describeError(err as Object);
    }
  }

  /** 工作区或规格不可用时清空表单状态，避免显示上一次的残留。 */
  private reset(): void {
    this.specPresent = false;
    this.supported = false;
    this.profile = '';
    this.specHash = '';
    this.rows = [];
    this.requiredCount = 0;
    this.missingValue = 0;
    this.missingAnchor = 0;
    this.gapCount = 0;
    this.approvalRequired = true;
    this.approvedAt = '';
    this.approvedNote = '';
  }

  /**
   * 替换表单里的一行。
   *
   * 必须整体换掉数组、并且换成一个**新对象**：ArkUI 只在数组本身或元素引用变化时才重绘，
   * 就地改字段再赋回同一个引用，选中态不会显示出来（提交时值却是新的，最容易看漏）。
   */
  private updateRow(index: number, row: GateRow): void {
    const next: GateRow[] = this.rows.slice();
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
    this.rows = next;
  }

  /** 数一遍还差什么：值缺几项、锚点缺几项。口径与在线版一致。 */
  private incomplete(): number[] {
    let missingValue: number = 0;
    let missingAnchor: number = 0;
    for (const row of this.rows) {
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
        // 列表与数值在界面上不可改：缺值只能先回规格里确认。
        missingValue++;
      }
    }
    return [missingValue, missingAnchor];
  }

  /** 只提交人实际填的东西，其余字段由端侧沿用规格现值。 */
  private inputs(): GateFieldInput[] {
    const list: GateFieldInput[] = [];
    for (const row of this.rows) {
      const input: GateFieldInput = {
        field: row.field,
        anchor: row.anchor.trim(),
        valueText: '',
        valueFlag: null,
        valueChoice: ''
      };
      if (!row.hasValue) {
        if (row.kind === 'boolean' && row.flag !== null) {
          input.valueFlag = row.flag;
        } else if ((row.kind === 'runtime_output' || row.kind === 'direction') && row.choice.length > 0) {
          input.valueChoice = row.choice;
        } else if (row.kind === 'text' && row.valueDraft.trim().length > 0) {
          input.valueText = row.valueDraft.trim();
        }
      }
      list.push(input);
    }
    return list;
  }

  /** 提交证据：本地先数缺项（比落盘后的报错更快更清楚），再交给端侧关口写回。 */
  async submit(): Promise<void> {
    this.evidenceError = '';
    this.doneText = '';
    if (this.sourceType.trim().length === 0
      || this.sourceLocator.trim().length === 0
      || this.reviewedAt.trim().length === 0) {
      this.evidenceError = this.tr('workflow.evidenceNeedSource');
      return;
    }
    const counts: number[] = this.incomplete();
    if (counts[0] > 0 || counts[1] > 0) {
      this.evidenceError = this.trf('workflow.evidenceIncomplete',
        [`${counts[0] + counts[1]}`, `${counts[0]}`, `${counts[1]}`]);
      return;
    }
    this.busy = true;
    try {
      const workspace: LocalWorkspace = new LocalWorkspace(this.workspaceRoot);
      const source: GateSource = {
        sourceType: this.sourceType,
        sourceLocator: this.sourceLocator,
        reviewedAt: this.reviewedAt
      };
      const outcome: GateOutcome = await applyOfficialEvidence(workspace, source, this.inputs());
      this.doneText = this.trf('localRule.done', [`${outcome.appliedFieldCount}`]);
      // 规格已经变了，表单要按新规格重建（锚点徽章才会变绿）；人刚才填的内容已进规格，不必留。
      this.rows = [];
      await this.reload();
    } catch (err) {
      this.evidenceError = describeError(err as Object);
    } finally {
      this.busy = false;
    }
  }

  /**
   * 批准规则：关口最后一步。
   *
   * 缺口没归零时按钮是禁用的，本地也再拦一次 —— 这是"人主导"里真正的那道决定，
   * 不能让它在缺口没齐的时候被按下去。批准和录入证据是两回事，这里只批准。
   */
  async approve(): Promise<void> {
    this.approvalError = '';
    this.approvalDone = '';
    if (this.gapCount > 0) {
      this.approvalError = this.trf('localRule.approvalBlocked', [`${this.gapCount}`]);
      return;
    }
    if (this.noteDraft.trim().length === 0) {
      this.approvalError = this.tr('localRule.approvalNeedNote');
      return;
    }
    this.approving = true;
    try {
      const workspace: LocalWorkspace = new LocalWorkspace(this.workspaceRoot);
      const outcome: GateApprovalOutcome = await approveRulesSpec(workspace, this.noteDraft);
      this.approvalDone = this.trf('localRule.approvalDone', [outcome.approvedAt]);
      this.noteDraft = '';
      await this.reload();
    } catch (err) {
      this.approvalError = describeError(err as Object);
    } finally {
      this.approving = false;
    }
  }

  /**
   * 导入规格文件。
   *
   * 端侧工作区在用户的「文档」目录里，本来也能用系统文件管理器拷进去；这里给一条
   * 应用内的路径，省得在两处之间来回切。先解析一遍再落盘：读不懂的 YAML 不往工作区写，
   * 免得把已经确认过的规格换成一份读不了的东西；覆盖前先把原文备份到 `docs/`。
   */
  async importSpec(): Promise<void> {
    this.busy = true;
    this.errorText = '';
    this.doneText = '';
    try {
      if (!this.ready) {
        throw new Error(this.tr('localRule.noWorkspace'));
      }
      const options: picker.DocumentSelectOptions = new picker.DocumentSelectOptions();
      options.maxSelectNumber = 1;
      const view: picker.DocumentViewPicker = new picker.DocumentViewPicker(this.abilityContext());
      const picked: string[] = await view.select(options);
      if (picked.length === 0) {
        return;
      }
      const text: string = readPickedText(picked[0]);
      importSpecText(new LocalWorkspace(this.workspaceRoot), text);
      this.rows = [];
      await this.reload();
    } catch (err) {
      this.errorText = describeError(err as Object);
    } finally {
      this.busy = false;
    }
  }

  /** 允许 / 不允许：布尔字段只能人选，未选就是没确认。 */
  @Builder
  BooleanChips(row: GateRow, index: number) {
    Row({ space: 8 }) {
      Text(this.tr('workflow.evidenceYes'))
        .fontSize(12)
        .fontColor(row.flag === true ? AppTheme.PRIMARY_DARK : AppTheme.TEXT_SECONDARY)
        .backgroundColor(row.flag === true ? AppTheme.PRIMARY_SOFT : AppTheme.PAGE_BG)
        .borderRadius(6)
        .padding({ left: 10, right: 10, top: 4, bottom: 4 })
        .onClick(() => {
          row.flag = true;
          this.updateRow(index, row);
        })
      Text(this.tr('workflow.evidenceNo'))
        .fontSize(12)
        .fontColor(row.flag === false ? AppTheme.PRIMARY_DARK : AppTheme.TEXT_SECONDARY)
        .backgroundColor(row.flag === false ? AppTheme.PRIMARY_SOFT : AppTheme.PAGE_BG)
        .borderRadius(6)
        .padding({ left: 10, right: 10, top: 4, bottom: 4 })
        .onClick(() => {
          row.flag = false;
          this.updateRow(index, row);
        })
    }
    .layoutWeight(1)
  }

  /** 取值必须二选一的字段（loose_png / submit_zip、maximize / minimize）。 */
  @Builder
  ChoiceChips(row: GateRow, index: number, options: string[]) {
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
            this.updateRow(index, row);
          })
      }, (option: string) => `${row.field}-${option}-${row.choice}`)
    }
    .layoutWeight(1)
  }

  /** 一行字段：值控件按类型分派，锚点永远是人填的输入框。 */
  @Builder
  FieldLine(row: GateRow, index: number) {
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
          .width(72)
        if (row.hasValue) {
          Text(row.valueText.length > 0 ? row.valueText : '—')
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
          .width(72)
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
    .padding({ top: 10, bottom: 10 })
    .border({ width: { top: 1 }, color: AppTheme.BORDER })
  }

  /** 顶部：返回 + 导入规格 + 工作区信息。 */
  @Builder
  Header() {
    Column() {
      Row() {
        Text(`← ${this.tr('localRule.back')}`)
          .fontSize(13)
          .fontColor(AppTheme.PRIMARY)
          .padding({ right: 12, top: 4, bottom: 4 })
          .onClick(() => {
            this.onBack();
          })
        Blank()
        Text(this.tr('localRule.importSpec'))
          .fontSize(13)
          .fontColor(this.busy ? AppTheme.TEXT_TERTIARY : AppTheme.PRIMARY)
          .padding({ left: 12, right: 12, top: 6, bottom: 6 })
          .enabled(!this.busy)
          .onClick(() => {
            this.importSpec();
          })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Text(this.tr('localRule.title'))
        .fontSize(24)
        .fontWeight(FontWeight.Bold)
        .fontColor(AppTheme.TEXT_PRIMARY)
        .margin({ top: 10 })

      if (this.workspaceRoot.length > 0) {
        Text(this.workspaceRoot)
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .margin({ top: 6 })
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
  }

  build() {
    // 卡片用父容器的间距排版：CardPanel 带尾随闭包时不能再链 `.margin()`。
    Column({ space: 18 }) {
      this.Header()

      if (this.errorText.length > 0) {
        Text(this.errorText)
          .fontSize(12)
          .fontColor(AppTheme.DANGER)
          .width('100%')
      }
      if (this.doneText.length > 0) {
        Column() {
          Text(this.doneText)
            .fontSize(13)
            .fontColor(AppTheme.PRIMARY_DARK)
            .width('100%')
          Text(this.tr('localRule.notApproval'))
            .fontSize(12)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .width('100%')
            .margin({ top: 6 })
        }
        .alignItems(HorizontalAlign.Start)
        .width('100%')
        .padding(14)
        .backgroundColor(AppTheme.PRIMARY_SOFT)
        .borderRadius(AppTheme.RADIUS)
      }

      if (this.workspaceRoot.length === 0) {
        CardPanel({ title: this.tr('localRule.title') }) {
          Text(this.tr('localRule.noWorkspaceHint'))
            .fontSize(13)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .width('100%')
        }
      } else if (!this.specPresent) {
        CardPanel({ title: this.tr('localRule.title') }) {
          Text(this.tr('localRule.noSpecHint'))
            .fontSize(13)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .width('100%')
        }
      } else if (!this.supported) {
        CardPanel({ title: this.tr('localRule.title') }) {
          Text(this.tr('workflow.evidenceUnsupported'))
            .fontSize(13)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .width('100%')
            .margin({ bottom: 10 })
          KeyValueRow({ label: this.tr('localRule.profile'), value: this.profile })
          KeyValueRow({ label: this.tr('localRule.specFingerprint'), value: this.specHash, mono: true })
        }
      } else {
        CardPanel({ title: this.tr('localRule.sourceTitle') }) {
          Text(this.tr('workflow.evidenceGateHint'))
            .fontSize(12)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .width('100%')
            .margin({ bottom: 10 })
          Text(this.tr('workflow.evidenceSourceType'))
            .fontSize(12)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .width('100%')
          TextInput({ text: this.sourceType, placeholder: this.tr('workflow.evidenceSourceTypeHint') })
            .fontSize(13)
            .width('100%')
            .height(38)
            .onChange((value: string) => {
              this.sourceType = value;
            })

          Text(this.tr('workflow.evidenceSourceLocator'))
            .fontSize(12)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .width('100%')
            .margin({ top: 8 })
          TextInput({ text: this.sourceLocator, placeholder: this.tr('workflow.evidenceSourceLocatorHint') })
            .fontSize(13)
            .width('100%')
            .height(38)
            .onChange((value: string) => {
              this.sourceLocator = value;
            })

          Text(this.tr('workflow.evidenceReviewedAt'))
            .fontSize(12)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .width('100%')
            .margin({ top: 8 })
          TextInput({ text: this.reviewedAt, placeholder: this.tr('workflow.evidenceReviewedAtHint') })
            .fontSize(13)
            .width('100%')
            .height(38)
            .onChange((value: string) => {
              this.reviewedAt = value;
            })

          KeyValueRow({ label: this.tr('localRule.profile'), value: this.profile })
          KeyValueRow({ label: this.tr('localRule.specFingerprint'), value: this.specHash, mono: true })
        }

        CardPanel({
          title: this.tr('workflow.evidenceFieldColumn')
        }) {
          // 填写进度用两条比例条表示：原先这是标题下一行灰字「必填 24 项；缺值 0 项、缺锚点 0 项」，
          // 读两遍才明白；条一眼就知道还差多少。
          ProgressBar({
            label: this.tr('workflow.valuesFilled'),
            current: this.requiredCount - this.missingValue,
            total: this.requiredCount
          })
            .margin({ bottom: 10 })
          ProgressBar({
            label: this.tr('workflow.anchorsFilled'),
            current: this.requiredCount - this.missingAnchor,
            total: this.requiredCount
          })
            .margin({ bottom: 16 })

          ForEach(this.rows, (row: GateRow, index: number) => {
            this.FieldLine(row, index)
          }, (row: GateRow) => `${row.field}-${row.flag}-${row.choice}-${row.hasAnchor}`)

          if (this.evidenceError.length > 0) {
            Text(this.evidenceError)
              .fontSize(12)
              .fontColor(AppTheme.DANGER)
              .width('100%')
              .margin({ top: 12 })
          }

          Row({ space: 12 }) {
            Text(this.busy ? this.tr('workflow.evidenceSubmitting') : this.tr('workflow.evidenceSubmit'))
              .fontSize(13)
              .fontColor(Color.White)
              .backgroundColor(AppTheme.PRIMARY)
              .borderRadius(AppTheme.RADIUS_SM)
              .padding({ left: 16, right: 16, top: 8, bottom: 8 })
              .enabled(!this.busy)
              .opacity(this.busy ? 0.6 : 1)
              .onClick(() => {
                this.submit();
              })
          }
          .width('100%')
          .margin({ top: 16 })
        }

        CardPanel({
          title: this.tr('localRule.approvalTitle')
        }) {
          if (this.approvalRequired) {
            if (this.gapCount > 0) {
              Text(this.trf('localRule.approvalBlocked', [`${this.gapCount}`]))
                .fontSize(12)
                .fontColor(AppTheme.WARN_TEXT)
                .width('100%')
            }
            if (this.approvalError.length > 0) {
              Text(this.approvalError)
                .fontSize(12)
                .fontColor(AppTheme.DANGER)
                .width('100%')
                .margin({ top: 8 })
            }
            Text(this.tr('localRule.approvalNoteLabel'))
              .fontSize(12)
              .fontColor(AppTheme.TEXT_SECONDARY)
              .width('100%')
              .margin({ top: 8 })
            TextInput({ text: this.noteDraft, placeholder: this.tr('localRule.approvalNoteHint') })
              .fontSize(13)
              .width('100%')
              .height(38)
              .onChange((value: string) => {
                this.noteDraft = value;
              })
            Row({ space: 12 }) {
              Text(this.approving ? this.tr('localRule.approving') : this.tr('localRule.approve'))
                .fontSize(13)
                .fontColor(Color.White)
                .backgroundColor(this.gapCount === 0 ? AppTheme.PRIMARY : AppTheme.TEXT_TERTIARY)
                .borderRadius(AppTheme.RADIUS_SM)
                .padding({ left: 16, right: 16, top: 8, bottom: 8 })
                .enabled(this.gapCount === 0 && !this.approving)
                .opacity(this.approving ? 0.6 : 1)
                .onClick(() => {
                  this.approve();
                })
              if (this.approvalDone.length > 0) {
                Text(this.approvalDone)
                  .fontSize(12)
                  .fontColor(AppTheme.PRIMARY_DARK)
                  .layoutWeight(1)
              }
            }
            .width('100%')
            .alignItems(VerticalAlign.Center)
            .margin({ top: 14 })
          } else {
            Row() {
              StatusBadge({ text: this.tr('localRule.approved'), tone: 'ok' })
              Text(this.approvedAt)
                .fontSize(12)
                .fontColor(AppTheme.TEXT_TERTIARY)
                .margin({ left: 10 })
            }
            .width('100%')
            .alignItems(VerticalAlign.Center)
            if (this.approvedNote.length > 0) {
              Text(this.approvedNote)
                .fontSize(12)
                .fontColor(AppTheme.TEXT_SECONDARY)
                .width('100%')
                .margin({ top: 8 })
            }
            // 证据一变，原来的复核结论就不成立了 —— 录入证据会把批准撤回（与后端同一套语义）。
            Text(this.tr('localRule.approvalRevokeHint'))
              .fontSize(12)
              .fontColor(AppTheme.TEXT_TERTIARY)
              .width('100%')
              .margin({ top: 10 })
          }
        }
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
  }
}
