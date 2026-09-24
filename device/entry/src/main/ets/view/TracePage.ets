import {
  fetchTrace,
  PaperClaim,
  TraceArtifact,
  TraceDocument,
  TraceExperiment,
  TraceResearchRecord,
  TraceRuleField,
  TraceScopeItem,
  TraceSnapshot
} from '../common/BackendClient';
import AppTheme from '../common/AppTheme';
import {
  experimentStatusLabel,
  experimentStatusTone,
  formatBytes,
  formatDuration,
  formatNumber,
  formatTimestamp
} from '../common/Format';
import { tFor, tfFor } from '../common/I18n';
import { CardPanel, EmptyHint, KeyValueRow, PageHeader, RailItemSpec, SectionRail, StatusBadge } from './Widgets';

/**
 * 溯源页：把「这条结论凭什么成立」摊开成四条链。
 *
 * 规则：字段值 → 官方锚点 → 来源定位 → 人工复核
 * 数据：审计指纹 → 每个实验的数据版本 → 是否计入当前赛题
 * 实验：假设与配置指纹 → 结果与产物 → 人工批准
 * 文献：检索条件 → 记录与引用文件，检索失败也如实上报
 *
 * 四条链加论文终点**不堆在一列**：顶部分段导航一次只显示一段，色点表示这条链通不通。
 * 规则链在 AIC 这样的赛题下有二十几个字段，堆在一起会有十几屏，读者会丢失方位。
 *
 * 页面本身只读：缺什么就显示缺什么，不会替后端补结论。
 */

/** 文献链在溯源页里最多列几条：完整清单在文献页。 */
const TRACE_RESEARCH_LIMIT: number = 8;

/** 指标字典摊平成一行行。 */
interface NameValue {
  name: string;
  value: string;
}

/** 检索源失败字典摊平成一行行。 */
interface NameText {
  name: string;
  text: string;
}

function metricRows(map: Record<string, number>): NameValue[] {
  const rows: NameValue[] = [];
  for (const key of Object.keys(map)) {
    rows.push({ name: key, value: formatNumber(map[key], 6) });
  }
  return rows;
}

function failureRows(map: Record<string, string>): NameText[] {
  const rows: NameText[] = [];
  for (const key of Object.keys(map)) {
    rows.push({ name: key, text: map[key] });
  }
  return rows;
}

@Component
export struct TracePage {
  /**
   * 当前语言。ArkUI 只重建读到状态变量的节点，所以本组件所有文案都走 this.tr()，
   * 由它读一次 this.lang，等于把用到的节点登记到语言变化上。
   */
  @StorageLink('lang') lang: string = 'zh';
  @State loading: boolean = false;
  @State errorText: string = '';
  @State snapshot: TraceSnapshot | null = null;
  /** 展开的实验 id；同时只展开一条，长页面才不至于来回跳。 */
  @State openExperiment: string = '';
  /**
   * 当前分段：rule / data / experiment / research / paper。
   *
   * 原来这四张链卡加论文卡堆在一列里，规则链光字段就有二十几行，整页十几屏，
   * 读的人不知道自己读到哪一段了。现在一次只渲染一段，段与段之间用色点导航切。
   */
  @State section: string = 'rule';

  /** 取文案：读一次 lang，让调用它的节点订阅语言变化。 */
  private tr(key: string): string {
    return tFor(this.lang, key);
  }

  /** 带占位符取文案。 */
  private trf(key: string, args: string[]): string {
    return tfFor(this.lang, key, args);
  }

  aboutToAppear(): void {
    this.load();
  }

  async load(): Promise<void> {
    this.loading = true;
    this.errorText = '';
    try {
      this.snapshot = await fetchTrace();
    } catch (err) {
      const error = err as Error;
      this.errorText = error.message;
    } finally {
      this.loading = false;
    }
  }

  /** 指纹只显示前 12 位：完整值一屏放不下，也没必要。 */
  private shortHash(value: string | null): string {
    if (value === null || value.length === 0) {
      return '';
    }
    return value.length > 12 ? value.slice(0, 12) : value;
  }

  /** 空值统一显示成短横线。 */
  private textOrDash(value: string | null): string {
    return value === null || value.length === 0 ? '—' : value;
  }

  private countText(value: number | null): string {
    return value === null ? '—' : `${value}`;
  }

  /** 相关度是小数，带上标签才读得懂。 */
  private relevanceText(value: number | null): string {
    return value === null ? '—' : this.trf('trace.relevance', [`${value}`]);
  }

  /** 排除原因标识翻成人话；不认识的标识原样显示，不假装理解。 */
  private exclusionLabel(code: string | null): string {
    if (code === 'synthetic_runner') {
      return this.tr('trace.exclusion.synthetic');
    }
    if (code === 'outside_audit_scope') {
      return this.tr('trace.exclusion.outside');
    }
    if (code === 'no_audit') {
      return this.tr('trace.exclusion.noAudit');
    }
    return code === null ? '' : code;
  }

  /** 规则关口的三种状态：已确认且无缺口 / 已确认但又有缺口 / 还没确认。 */
  private ruleGateText(): string {
    if (this.snapshot === null) {
      return '';
    }
    if (!this.snapshot.rule.approved) {
      return this.tr('trace.ruleGatePending');
    }
    return this.snapshot.rule.ready ? this.tr('trace.ruleGateApproved') : this.tr('trace.ruleGateStale');
  }

  private ruleGateTone(): string {
    if (this.snapshot === null) {
      return 'muted';
    }
    if (!this.snapshot.rule.approved) {
      return 'warn';
    }
    return this.snapshot.rule.ready ? 'ok' : 'warn';
  }

  private ruleFields(): TraceRuleField[] {
    return this.snapshot === null ? [] : this.snapshot.rule.fields;
  }

  private ruleDocs(): TraceDocument[] {
    return this.snapshot === null ? [] : this.snapshot.rule.documents;
  }

  private ruleUnresolved(): string[] {
    return this.snapshot === null ? [] : this.snapshot.rule.unresolved_questions;
  }

  private scopeItems(): TraceScopeItem[] {
    return this.snapshot === null ? [] : this.snapshot.data.experiments;
  }

  private experiments(): TraceExperiment[] {
    return this.snapshot === null ? [] : this.snapshot.experiments.experiments;
  }

  private researchRecords(): TraceResearchRecord[] {
    return this.snapshot === null ? [] : this.snapshot.research.records;
  }

  /**
   * 文献链只列前几条：完整清单在文献页，这里铺开会让证据链的终点被推到十几屏之外。
   */
  private researchRecordsShown(): TraceResearchRecord[] {
    return this.researchRecords().slice(0, TRACE_RESEARCH_LIMIT);
  }

  private researchDocs(): TraceDocument[] {
    return this.snapshot === null ? [] : this.snapshot.research.documents;
  }

  private claims(): PaperClaim[] {
    return this.snapshot === null ? [] : this.snapshot.paper.claims;
  }

  private inScopeCount(): number {
    return this.snapshot === null ? 0 : this.snapshot.experiments.in_scope_count;
  }

  private artifactMissingCount(): number {
    return this.snapshot === null ? 0 : this.snapshot.experiments.artifact_missing_count;
  }

  private paperAvailable(): boolean {
    return this.snapshot !== null && this.snapshot.paper.available;
  }

  private paperPackageDir(): string {
    return this.snapshot === null ? '' : this.snapshot.paper.package_dir;
  }

  private paperGeneratedAt(): string | null {
    return this.snapshot === null ? null : this.snapshot.paper.generated_at;
  }

  private paperSectionCount(): number {
    return this.snapshot === null ? 0 : this.snapshot.paper.sections.length;
  }

  private paperBibEntries(): number {
    return this.snapshot === null ? 0 : this.snapshot.paper.bib_entries;
  }

  /**
   * 已带锚点的字段比例。
   *
   * 原先这是一个大统计块。它只在规则段里有意义，收进来之后页面顶部就不必再压一排数字。
   */
  private anchorRatioText(): string {
    if (this.snapshot === null || this.snapshot.rule.required_field_count === 0) {
      return '';
    }
    const total: number = this.snapshot.rule.required_field_count;
    const withAnchor: number = total - this.snapshot.rule.missing_anchor_count;
    return `${this.tr('trace.statAnchors')} ${withAnchor}/${total}`;
  }

  /** 规则链通不通：没批准是待办，批准了又冒出缺口是告警。 */
  private ruleTone(): string {
    if (this.snapshot === null) {
      return 'muted';
    }
    if (!this.snapshot.rule.approved) {
      return 'warn';
    }
    return this.snapshot.rule.ready ? 'ok' : 'warn';
  }

  /** 数据链通不通：审计在册且有指纹才算通。 */
  private dataTone(): string {
    if (this.snapshot === null) {
      return 'muted';
    }
    return this.snapshot.data.audit.available ? 'ok' : 'warn';
  }

  /** 实验链通不通：有在册实验、且产物没丢才算通。 */
  private experimentTone(): string {
    if (this.snapshot === null) {
      return 'muted';
    }
    if (this.inScopeCount() === 0) {
      return 'warn';
    }
    return this.artifactMissingCount() > 0 ? 'danger' : 'ok';
  }

  /** 文献链通不通：有检索记录才算通，没有是中性（还没轮到这里），不是错。 */
  private researchTone(): string {
    if (this.snapshot === null) {
      return 'muted';
    }
    return this.snapshot.research.record_count > 0 ? 'ok' : 'muted';
  }

  /** 论文终点通不通：有声明但结果文件丢了是红的，不是黄的。 */
  private paperTone(): string {
    if (this.snapshot === null || !this.paperAvailable()) {
      return 'muted';
    }
    if (this.claims().length === 0) {
      return 'warn';
    }
    for (const claim of this.claims()) {
      if (!claim.result_exists) {
        return 'danger';
      }
    }
    return 'ok';
  }

  /** 分段导航的项。标签走 this.tr()，语言切换时会跟着重建。 */
  private railItems(): RailItemSpec[] {
    return [
      { key: 'rule', label: this.tr('trace.section.rule'), tone: this.ruleTone() },
      { key: 'data', label: this.tr('trace.section.data'), tone: this.dataTone() },
      { key: 'experiment', label: this.tr('trace.section.experiment'), tone: this.experimentTone() },
      { key: 'research', label: this.tr('trace.section.research'), tone: this.researchTone() },
      { key: 'paper', label: this.tr('trace.section.paper'), tone: this.paperTone() }
    ];
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

  /** 一组用来展示文件名的标签。 */
  @Builder
  DocumentChips(documents: TraceDocument[]) {
    Flex({ wrap: FlexWrap.Wrap }) {
      ForEach(documents, (item: TraceDocument) => {
        Text(`${item.path}（${formatBytes(item.size_bytes)}）`)
          .fontSize(12)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .backgroundColor(AppTheme.PAGE_BG)
          .borderRadius(6)
          .padding({ left: 10, right: 10, top: 5, bottom: 5 })
          .margin({ top: 8, right: 8 })
      }, (item: TraceDocument) => item.path)
    }
    .width('100%')
  }

  /** 规则链里的一行：字段 + 值 + 官方锚点。 */
  @Builder
  RuleFieldRow(item: TraceRuleField) {
    Column() {
      Row() {
        Text(item.field)
          .fontSize(13)
          .fontWeight(FontWeight.Medium)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .layoutWeight(1)
        StatusBadge({
          text: item.has_anchor ? this.tr('trace.anchorOk') : this.tr('trace.anchorMissing'),
          tone: item.has_anchor ? 'ok' : 'danger'
        })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Row() {
        Text(this.tr('trace.valueLabel'))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .width(104)
        Text(item.value !== null ? item.value : this.tr('trace.valueUnresolved'))
          .fontSize(12)
          .fontColor(item.has_value ? AppTheme.TEXT_SECONDARY : AppTheme.DANGER)
          .layoutWeight(1)
          .maxLines(3)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }
      .width('100%')
      .alignItems(VerticalAlign.Top)
      .margin({ top: 6 })

      Row() {
        Text(this.tr('trace.anchorLabel'))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .width(104)
        Text(item.anchor !== null ? item.anchor : this.tr('trace.anchorMissing'))
          .fontSize(12)
          .fontColor(item.has_anchor ? AppTheme.TEXT_SECONDARY : AppTheme.DANGER)
          .layoutWeight(1)
          .maxLines(3)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }
      .width('100%')
      .alignItems(VerticalAlign.Top)
      .margin({ top: 4 })
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ top: 12, bottom: 12 })
    .border({ width: { bottom: 1 }, color: AppTheme.BORDER_SOFT })
  }

  /** 规则链。 */
  @Builder
  RuleCard() {
    CardPanel({
      title: this.tr('trace.ruleTitle'),
      subtitle: this.tr('trace.ruleSubtitle')
    }) {
      Column({ space: 6 }) {
        Row() {
          StatusBadge({ text: this.ruleGateText(), tone: this.ruleGateTone() })
          Text(this.anchorRatioText())
            .fontSize(12)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .margin({ left: 12 })
          Text(this.snapshot === null
            ? ''
            : this.trf('trace.gapTotal', [`${this.snapshot.rule.gap_count}`,
              `${this.snapshot.rule.missing_value_count}`, `${this.snapshot.rule.missing_anchor_count}`]))
            .fontSize(12)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .layoutWeight(1)
            .margin({ left: 12 })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        KeyValueRow({
          label: this.tr('trace.specFile'),
          value: this.snapshot === null ? '—' : this.textOrDash(this.snapshot.rule.spec_path),
          mono: true
        })
        KeyValueRow({
          label: this.tr('trace.sourceType'),
          value: this.snapshot === null ? '—' : this.textOrDash(this.snapshot.rule.source.source_type)
        })
        KeyValueRow({
          label: this.tr('trace.sourceLocator'),
          value: this.snapshot === null ? '—' : this.textOrDash(this.snapshot.rule.source.source_locator),
          mono: true
        })
        KeyValueRow({
          label: this.tr('trace.reviewedAt'),
          value: this.snapshot === null ? '—' : formatTimestamp(this.snapshot.rule.source.reviewed_at)
        })
        KeyValueRow({
          label: this.tr('trace.approvedAt'),
          value: this.snapshot === null ? '—' : formatTimestamp(this.snapshot.rule.approved_at)
        })
        KeyValueRow({
          label: this.tr('trace.approvedNote'),
          value: this.snapshot === null ? '—' : this.textOrDash(this.snapshot.rule.approved_note)
        })

        Text(this.tr('trace.fieldColumn'))
          .fontSize(13)
          .fontWeight(FontWeight.Medium)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .margin({ top: 14 })

        if (this.ruleFields().length === 0) {
          EmptyHint({ text: this.tr('trace.noFields') })
        } else {
          ForEach(this.ruleFields(), (item: TraceRuleField) => {
            this.RuleFieldRow(item)
          }, (item: TraceRuleField) => `${item.field}-${item.has_value}-${item.has_anchor}`)
        }

        if (this.ruleUnresolved().length > 0) {
          Text(this.tr('workflow.blockers'))
            .fontSize(13)
            .fontWeight(FontWeight.Medium)
            .fontColor(AppTheme.TEXT_PRIMARY)
            .margin({ top: 16 })
          ForEach(this.ruleUnresolved(), (item: string, index: number) => {
            Text(`${index + 1}. ${item}`)
              .fontSize(12)
              .fontColor(AppTheme.TEXT_SECONDARY)
              .width('100%')
              .margin({ top: 6 })
          }, (item: string) => item)
        }

        Text(`${this.tr('trace.evidenceDocs')} · ${this.trf('trace.docCount', [`${this.ruleDocs().length}`])}`)
          .fontSize(13)
          .fontWeight(FontWeight.Medium)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .margin({ top: 18 })

        if (this.ruleDocs().length === 0) {
          EmptyHint({ text: this.tr('trace.noDocs') })
        } else {
          this.DocumentChips(this.ruleDocs())
        }
      }
      .alignItems(HorizontalAlign.Start)
      .width('100%')
    }
  }

  /** 数据链里的一行：实验 + 数据版本 + 是否计入当前赛题。 */
  @Builder
  ScopeRow(item: TraceScopeItem) {
    Column() {
      Row() {
        Text(item.experiment_id)
          .fontSize(13)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .width(140)
        Text(item.data_version !== null ? this.trf('trace.dataVersion', [item.data_version]) : '—')
          .fontSize(12)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .layoutWeight(1)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        StatusBadge({
          text: item.in_scope ? this.tr('trace.inScope') : this.tr('trace.excluded'),
          tone: item.in_scope ? 'ok' : 'muted'
        })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      if (!item.in_scope && this.exclusionLabel(item.exclusion).length > 0) {
        Text(this.exclusionLabel(item.exclusion))
          .fontSize(12)
          .fontColor(AppTheme.WARN_TEXT)
          .margin({ top: 6 })
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ top: 12, bottom: 12 })
    .border({ width: { bottom: 1 }, color: AppTheme.BORDER_SOFT })
  }

  /** 数据指纹链。 */
  @Builder
  DataCard() {
    CardPanel({
      title: this.tr('trace.dataTitle'),
      subtitle: this.tr('trace.dataSubtitle')
    }) {
      Column({ space: 6 }) {
        KeyValueRow({
          label: this.tr('trace.auditDir'),
          value: this.snapshot === null ? '—' : this.textOrDash(this.snapshot.data.audit.data_dir),
          mono: true
        })
        KeyValueRow({
          label: this.tr('trace.auditFingerprint'),
          value: this.snapshot === null ? '—' : this.textOrDash(this.shortHash(this.snapshot.data.audit.inventory_sha256)),
          mono: true
        })
        KeyValueRow({
          label: this.tr('trace.auditFiles'),
          value: this.snapshot === null ? '—' : this.countText(this.snapshot.data.audit.file_count)
        })
        KeyValueRow({
          label: this.tr('trace.auditIssues'),
          value: this.snapshot === null ? '—' : this.countText(this.snapshot.data.audit.issue_count)
        })
        KeyValueRow({
          label: this.tr('trace.auditGeneratedAt'),
          value: this.snapshot === null ? '—' : formatTimestamp(this.snapshot.data.audit.generated_at)
        })

        if (this.snapshot !== null && !this.snapshot.data.audit.available) {
          Text(this.tr('trace.auditMissing'))
            .fontSize(12)
            .fontColor(AppTheme.WARN_TEXT)
            .width('100%')
            .margin({ top: 6 })
        }

        Text(this.snapshot === null
          ? ''
          : this.trf('trace.expCount', [`${this.snapshot.data.in_scope_count}`, `${this.scopeItems().length}`]))
          .fontSize(13)
          .fontWeight(FontWeight.Medium)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .margin({ top: 16 })

        if (this.scopeItems().length === 0) {
          EmptyHint({ text: this.tr('trace.noExperiments') })
        } else {
          ForEach(this.scopeItems(), (item: TraceScopeItem) => {
            this.ScopeRow(item)
          }, (item: TraceScopeItem) => `${item.experiment_id}-${item.in_scope}-${item.exclusion}`)
        }
      }
      .alignItems(HorizontalAlign.Start)
      .width('100%')
    }
  }

  /** 实验详情：清单、环境、指标、产物、人工批准。 */
  @Builder
  ExperimentDetail(item: TraceExperiment) {
    Column({ space: 4 }) {
      KeyValueRow({ label: this.tr('trace.hypothesis'), value: this.textOrDash(item.hypothesis) })
      KeyValueRow({ label: this.tr('trace.changeTypeRow'), value: this.textOrDash(item.change_type) })
      KeyValueRow({ label: this.tr('trace.configPath'), value: this.textOrDash(item.config_path), mono: true })
      KeyValueRow({
        label: this.tr('trace.configHash'),
        value: this.textOrDash(this.shortHash(item.config_sha256)),
        mono: true
      })
      KeyValueRow({
        label: this.tr('trace.gitRow'),
        value: item.git.available
          ? `${this.textOrDash(this.shortHash(item.git.commit))} · ${item.git.dirty ? this.tr('trace.gitDirty') : this.tr('trace.gitClean')}`
          : this.tr('trace.gitUnbound')
      })
      KeyValueRow({
        label: this.tr('trace.envRow'),
        value: `Python ${this.textOrDash(item.environment.python)} · torch ${this.textOrDash(item.environment.torch)} · ${this.textOrDash(item.environment.gpu)}`
      })
      KeyValueRow({
        label: this.tr('trace.metricRow'),
        value: formatNumber(item.validation_metric, 6)
      })
      KeyValueRow({ label: this.tr('trace.decisionRow'), value: this.textOrDash(item.decision) })
      KeyValueRow({ label: this.tr('trace.conclusionRow'), value: this.textOrDash(item.conclusion) })
      KeyValueRow({
        label: this.tr('trace.runtimeRow'),
        value: item.runtime_seconds === null ? '—' : formatDuration(this.lang, item.runtime_seconds)
      })
      KeyValueRow({ label: this.tr('trace.trackerRow'), value: this.textOrDash(item.tracker_backend) })
      KeyValueRow({ label: this.tr('trace.resultFile'), value: this.textOrDash(item.result_path), mono: true })
      KeyValueRow({
        label: this.tr('trace.approvalRow'),
        value: item.approval.recorded
          ? `${formatTimestamp(item.approval.approved_at)} · ${this.trf('trace.approvalBy', [this.textOrDash(item.approval.approved_by)])}`
          : this.tr('trace.approvalNone')
      })

      ForEach(metricRows(item.metrics), (metric: NameValue) => {
        KeyValueRow({ label: metric.name, value: metric.value })
      }, (metric: NameValue) => `metric-${metric.name}-${metric.value}`)

      Text(this.tr('trace.artifactsRow'))
        .fontSize(13)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .margin({ top: 10, bottom: 4 })

      if (item.artifacts.length === 0) {
        EmptyHint({ text: this.tr('common.none') })
      } else {
        ForEach(item.artifacts, (artifact: TraceArtifact) => {
          Row() {
            Text(artifact.name)
              .fontSize(12)
              .fontColor(AppTheme.TEXT_SECONDARY)
              .width(150)
            Text(artifact.path)
              .fontSize(11)
              .fontColor(AppTheme.TEXT_TERTIARY)
              .layoutWeight(1)
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
            if (artifact.exists && artifact.size_bytes !== null) {
              Text(formatBytes(artifact.size_bytes))
                .fontSize(11)
                .fontColor(AppTheme.TEXT_TERTIARY)
                .margin({ right: 10 })
            }
            StatusBadge({
              text: artifact.exists ? this.tr('trace.artifactPresent') : this.tr('trace.artifactAbsent'),
              tone: artifact.exists ? 'ok' : 'danger'
            })
          }
          .width('100%')
          .alignItems(VerticalAlign.Center)
          .padding({ top: 6, bottom: 6 })
        }, (artifact: TraceArtifact) => `${artifact.path}-${artifact.exists}`)
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ left: 16, top: 10, bottom: 14 })
    .backgroundColor(AppTheme.PAGE_BG)
    .borderRadius(AppTheme.RADIUS)
    .margin({ top: 10 })
  }

  /** 实验链里的一行：摘要 + 可展开的详情。 */
  @Builder
  ExperimentRow(item: TraceExperiment) {
    Column() {
      Row() {
        Text(item.experiment_id)
          .fontSize(13)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .width(140)
        Text(item.hypothesis !== null ? item.hypothesis : '—')
          .fontSize(12)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .layoutWeight(1)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        StatusBadge({ text: experimentStatusLabel(this.lang, item.status === null ? '' : item.status), tone: experimentStatusTone(item.status === null ? '' : item.status) })
        StatusBadge({
          text: item.in_scope ? this.tr('trace.inScope') : this.tr('trace.excluded'),
          tone: item.in_scope ? 'ok' : 'muted'
        })
          .margin({ left: 8 })
        Text(this.openExperiment === item.experiment_id ? this.tr('trace.detailsOpen') : this.tr('trace.detailsClose'))
          .fontSize(12)
          .fontColor(AppTheme.PRIMARY)
          .margin({ left: 12 })
          .onClick(() => {
            this.openExperiment = this.openExperiment === item.experiment_id ? '' : item.experiment_id;
          })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      if (!item.in_scope && this.exclusionLabel(item.exclusion).length > 0) {
        Text(this.exclusionLabel(item.exclusion))
          .fontSize(12)
          .fontColor(AppTheme.WARN_TEXT)
          .margin({ top: 6 })
      }

      if (this.openExperiment === item.experiment_id) {
        this.ExperimentDetail(item)
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ top: 12, bottom: 12 })
    .border({ width: { bottom: 1 }, color: AppTheme.BORDER_SOFT })
  }

  /** 实验档案链。 */
  @Builder
  ExperimentCard() {
    CardPanel({
      title: this.tr('trace.expTitle'),
      subtitle: this.tr('trace.expSubtitle')
    }) {
      Column({ space: 6 }) {
        Row() {
          Text(this.trf('trace.expCount', [`${this.inScopeCount()}`, `${this.experiments().length}`]))
            .fontSize(12)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .layoutWeight(1)
          if (this.artifactMissingCount() > 0) {
            StatusBadge({
              text: this.trf('trace.artifactMissing', [`${this.artifactMissingCount()}`]),
              tone: 'danger'
            })
          }
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)
        .margin({ bottom: 6 })

        if (this.experiments().length === 0) {
          EmptyHint({ text: this.tr('trace.expEmpty') })
        } else {
          ForEach(this.experiments(), (item: TraceExperiment) => {
            this.ExperimentRow(item)
          }, (item: TraceExperiment) => `${item.experiment_id}-${this.openExperiment === item.experiment_id}`)
        }
      }
      .alignItems(HorizontalAlign.Start)
      .width('100%')
    }
  }

  /** 一条文献记录。 */
  @Builder
  ResearchRow(item: TraceResearchRecord) {
    Column() {
      Text(item.title !== null ? item.title : '—')
        .fontSize(13)
        .fontColor(AppTheme.TEXT_PRIMARY)
        .width('100%')
        .maxLines(2)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
      Text(`${this.textOrDash(item.paper_id)} · ${this.textOrDash(item.source)} · ${this.countText(item.year)} · ${this.relevanceText(item.relevance_score)}`)
        .fontSize(12)
        .fontColor(AppTheme.TEXT_TERTIARY)
        .margin({ top: 6 })
      if (item.url !== null) {
        Text(item.url)
          .fontSize(11)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .width('100%')
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 4 })
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ top: 12, bottom: 12 })
    .border({ width: { bottom: 1 }, color: AppTheme.BORDER_SOFT })
  }

  /** 文献链。 */
  @Builder
  ResearchCard() {
    CardPanel({
      title: this.tr('trace.researchTitle'),
      subtitle: this.tr('trace.researchSubtitle')
    }) {
      Column({ space: 6 }) {
        KeyValueRow({
          label: this.tr('trace.query'),
          value: this.snapshot === null ? '—' : this.textOrDash(this.snapshot.research.query)
        })
        KeyValueRow({
          label: this.tr('trace.searchedAt'),
          value: this.snapshot === null ? '—' : formatTimestamp(this.snapshot.research.searched_at)
        })
        KeyValueRow({
          label: this.tr('trace.statRecords'),
          value: this.snapshot === null ? '—' : `${this.snapshot.research.record_count}`
        })

        if (this.snapshot !== null && failureRows(this.snapshot.research.provider_failures).length > 0) {
          Text(this.tr('trace.providerFailure'))
            .fontSize(13)
            .fontColor(AppTheme.WARN_TEXT)
            .margin({ top: 10 })
          ForEach(failureRows(this.snapshot.research.provider_failures), (item: NameText) => {
            Text(`${item.name}: ${item.text}`)
              .fontSize(12)
              .fontColor(AppTheme.WARN_TEXT)
              .width('100%')
              .maxLines(2)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
              .margin({ top: 4 })
          }, (item: NameText) => `failure-${item.name}-${item.text}`)
        }

        if (this.researchRecords().length === 0) {
          EmptyHint({ text: this.tr('trace.researchEmpty') })
        } else {
          if (this.researchRecords().length > TRACE_RESEARCH_LIMIT) {
            Text(this.trf('trace.recordsShown', [`${TRACE_RESEARCH_LIMIT}`, `${this.researchRecords().length}`]))
              .fontSize(12)
              .fontColor(AppTheme.TEXT_TERTIARY)
              .width('100%')
              .margin({ top: 8, bottom: 4 })
          }
          ForEach(this.researchRecordsShown(), (item: TraceResearchRecord) => {
            this.ResearchRow(item)
          }, (item: TraceResearchRecord) => `${item.paper_id}-${item.title}`)
        }

        Text(this.tr('trace.refFiles'))
          .fontSize(13)
          .fontWeight(FontWeight.Medium)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .margin({ top: 16 })

        if (this.researchDocs().length === 0) {
          EmptyHint({ text: this.tr('trace.noDocs') })
        } else {
          this.DocumentChips(this.researchDocs())
        }
      }
      .alignItems(HorizontalAlign.Start)
      .width('100%')
    }
  }

  /** 论文终点：证据包 + 每条声明引用的结果文件是否还在。 */
  @Builder
  PaperCard() {
    CardPanel({
      title: this.tr('trace.paperTitle'),
      subtitle: this.tr('trace.paperSubtitle')
    }) {
      Column({ space: 6 }) {
        if (!this.paperAvailable()) {
          EmptyHint({ text: this.tr('trace.paperMissing') })
        } else {
          KeyValueRow({
            label: this.tr('trace.packageDir'),
            value: this.paperPackageDir(),
            mono: true
          })
          KeyValueRow({
            label: this.tr('trace.generatedAt'),
            value: formatTimestamp(this.paperGeneratedAt())
          })
          KeyValueRow({
            label: this.tr('trace.sectionsLabel'),
            value: `${this.paperSectionCount()}`
          })
          KeyValueRow({
            label: this.tr('trace.bibLabel'),
            value: `${this.paperBibEntries()}`
          })

          Text(this.tr('trace.claimsTitle'))
            .fontSize(13)
            .fontWeight(FontWeight.Medium)
            .fontColor(AppTheme.TEXT_PRIMARY)
            .margin({ top: 14 })

          if (this.claims().length === 0) {
            EmptyHint({ text: this.tr('trace.claimsEmpty') })
          } else {
            ForEach(this.claims(), (claim: PaperClaim) => {
              Column() {
                Row() {
                  Text(claim.claim)
                    .fontSize(13)
                    .fontColor(AppTheme.TEXT_PRIMARY)
                    .layoutWeight(1)
                    .maxLines(2)
                    .textOverflow({ overflow: TextOverflow.Ellipsis })
                  StatusBadge({
                    text: claim.result_exists ? this.tr('trace.claimResolved') : this.tr('trace.claimUnresolved'),
                    tone: claim.result_exists ? 'ok' : 'danger'
                  })
                    .margin({ left: 12 })
                }
                .width('100%')
                .alignItems(VerticalAlign.Top)

                Text(`${claim.experiment_id} · ${claim.result_path}`)
                  .fontSize(12)
                  .fontColor(AppTheme.TEXT_TERTIARY)
                  .width('100%')
                  .maxLines(1)
                  .textOverflow({ overflow: TextOverflow.Ellipsis })
                  .margin({ top: 6 })
              }
              .alignItems(HorizontalAlign.Start)
              .width('100%')
              .padding({ top: 12, bottom: 12 })
              .border({ width: { bottom: 1 }, color: AppTheme.BORDER_SOFT })
            }, (claim: PaperClaim) => `${claim.experiment_id}-${claim.result_path}-${claim.result_exists}`)
          }
        }
      }
      .alignItems(HorizontalAlign.Start)
      .width('100%')
    }
  }

  build() {
    Column({ space: 20 }) {
      PageHeader({
        title: this.tr('nav.trace'),
        subtitle: this.tr('trace.subtitle'),
        onRefresh: () => {
          this.load();
        }
      })

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

      if (this.section === 'data') {
        this.DataCard()
      } else if (this.section === 'experiment') {
        this.ExperimentCard()
      } else if (this.section === 'research') {
        this.ResearchCard()
      } else if (this.section === 'paper') {
        this.PaperCard()
      } else {
        this.RuleCard()
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
