import {
  CandidateAssessment,
  CandidateCounts,
  CandidateSignal,
  CodeCandidate,
  RelevanceParts,
  ResearchRecord,
  ResearchReport,
  assessResearchCandidates,
  decideResearchCandidate,
  fetchResearch,
  searchResearch
} from '../common/BackendClient';
import AppTheme from '../common/AppTheme';
import { formatNumber, formatTimestamp } from '../common/Format';
import { tFor, tfFor } from '../common/I18n';
import {
  CardPanel,
  ChoiceChips,
  ChoiceSpec,
  EmptyHint,
  PageHeader,
  RailItemSpec,
  SectionRail,
  StatusBadge
} from './Widgets';

/** 某个数据源的失败记录：provider 与后端错误原文分开存，展示时才拼，避免文案被定死。 */
interface SourceFailure {
  provider: string;
  message: string;
}

/** 空计数：后端还没给过 counts 时用它，界面不用到处判空。 */
function emptyCounts(): CandidateCounts {
  return { records: 0, undecided: 0, investigate: 0, discard: 0, assessed: 0 };
}

/** 分量的可读值：算不出来时给一个破折号，不要显示 null。 */
function partValue(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '—';
  }
  return formatNumber(value, 2);
}

/** 取舍的可读名称。 */
function decisionText(lang: string, decision: string): string {
  if (decision === 'investigate') {
    return tFor(lang, 'lit.decidedInvestigate');
  }
  if (decision === 'discard') {
    return tFor(lang, 'lit.decidedDiscard');
  }
  return tFor(lang, 'lit.decidedReset');
}

/** 取舍的徽章色调。 */
function decisionTone(decision: string): string {
  if (decision === 'investigate') {
    return 'ok';
  }
  if (decision === 'discard') {
    return 'warn';
  }
  return 'muted';
}

/** 结论的可读名称。 */
function verdictText(lang: string, verdict: string): string {
  if (verdict === 'reproduce') {
    return tFor(lang, 'lit.verdictReproduce');
  }
  if (verdict === 'adapt_component') {
    return tFor(lang, 'lit.verdictAdaptComponent');
  }
  if (verdict === 'reference_only') {
    return tFor(lang, 'lit.verdictReferenceOnly');
  }
  return tFor(lang, 'lit.verdictSkip');
}

/** 结论的徽章色调：值得复现是绿的，只作参考是灰的，不投入是警戒色。 */
function verdictTone(verdict: string): string {
  if (verdict === 'reproduce') {
    return 'ok';
  }
  if (verdict === 'adapt_component') {
    return 'warn';
  }
  if (verdict === 'reference_only') {
    return 'muted';
  }
  return 'danger';
}

/** 结论对应的建议。文案表里四档各一句，不在这里拼句子。 */
function adviceText(lang: string, verdict: string): string {
  if (verdict === 'reproduce') {
    return tFor(lang, 'lit.adviceReproduce');
  }
  if (verdict === 'adapt_component') {
    return tFor(lang, 'lit.adviceAdaptComponent');
  }
  if (verdict === 'reference_only') {
    return tFor(lang, 'lit.adviceReferenceOnly');
  }
  return tFor(lang, 'lit.adviceSkip');
}

/**
 * 开源代码这一项的结论。
 *
 * `lookup_failed` 必须和 `none_found` 分开显示：网络不通不代表这篇工作没开源，
 * 把两者说成一样会让人误判。
 */
function openSourceText(lang: string, assessment: CandidateAssessment): string {
  if (assessment.code_lookup === 'found') {
    return assessment.has_public_code
      ? (assessment.code_candidates.length > 0 ? tFor(lang, 'lit.openSourceFound') : tFor(lang, 'lit.openSourceRecord'))
      : tFor(lang, 'lit.openSourceNone');
  }
  if (assessment.code_lookup === 'lookup_failed') {
    return tFor(lang, 'lit.openSourceUnknown');
  }
  if (assessment.code_lookup === 'skipped') {
    return tFor(lang, 'lit.openSourceRecord');
  }
  return tFor(lang, 'lit.openSourceNone');
}

/** 开源代码徽章的色调。 */
function openSourceTone(assessment: CandidateAssessment): string {
  if (assessment.has_public_code) {
    return 'ok';
  }
  if (assessment.code_lookup === 'lookup_failed') {
    return 'muted';
  }
  return 'warn';
}

/** 证据行的标题：许可、任务匹配、年份、发表来源各一行。代码与官方归属另有徽章。 */
function signalLabel(lang: string, key: string): string {
  if (key === 'license_declared' || key === 'license_unknown') {
    return tFor(lang, 'lit.signalLicense');
  }
  if (key === 'task_fit' || key === 'task_fit_unknown') {
    return tFor(lang, 'lit.signalTaskFit');
  }
  if (key === 'year_known' || key === 'year_unknown') {
    return tFor(lang, 'lit.signalYear');
  }
  if (key === 'venue_known' || key === 'venue_unknown') {
    return tFor(lang, 'lit.signalVenue');
  }
  return key;
}

/** 证据行的取值：拿不到时统一说「未知」，不要漏出后端英文解释。 */
function signalDetail(lang: string, signal: CandidateSignal): string {
  const unknown: string[] = ['license_unknown', 'task_fit_unknown', 'year_unknown', 'venue_unknown'];
  if (unknown.includes(signal.key)) {
    return signal.key === 'license_unknown' ? tFor(lang, 'lit.signalLicenseUnknown') : tFor(lang, 'lit.signalUnknown');
  }
  return signal.detail;
}

/** 要在评判卡里列出来的证据（代码与官方归属已经各自有徽章，不重复）。 */
function reviewSignals(assessment: CandidateAssessment): CandidateSignal[] {
  const keep: string[] = ['license_declared', 'license_unknown', 'task_fit', 'task_fit_unknown',
    'year_known', 'year_unknown', 'venue_known', 'venue_unknown'];
  return assessment.signals.filter((signal: CandidateSignal) => keep.includes(signal.key));
}

/**
 * 文献页：按规则检索候选 → 逐条取舍 → 对调研过的做价值评判。
 *
 * 三段之间是一条链：检索式决定候选从哪来，取舍决定评判对谁做，评判给出复现建议。
 * 取舍与评判都在后端落盘，重跑检索不会覆盖人的决定。
 */
@Component
export struct LiteraturePage {
  /**
   * 当前语言。ArkUI 只重建读到状态变量的节点，所以本组件所有文案都走 this.tr()，
   * 由它读一次 this.lang，等于把用到的节点登记到语言变化上。
   */
  @StorageLink('lang') lang: string = 'zh';
  @State loading: boolean = false;
  @State errorText: string = '';
  @State query: string = '';
  @State searchedAt: string = '';
  @State sources: string[] = [];
  @State records: ResearchRecord[] = [];
  @State failures: SourceFailure[] = [];
  @State counts: CandidateCounts = emptyCounts();
  /**
   * 当前分段：query / records。
   *
   * 记录一多，检索条件就会被顶到看不见。分成两段之后，条件与候选清单各占一屏。
   */
  @State section: string = 'query';
  /** 正在跑检索或评判：按钮禁用，避免连点。 */
  @State busy: boolean = false;
  /** 正在提交取舍的那条记录 id；空串表示没有。 */
  @State pendingId: string = '';
  /** 取舍/评判失败的提示，贴在操作旁边而不是页面顶部。 */
  @State actionError: string = '';
  /** 人工检索词；留空表示按规则自动拼。 */
  @State queryDraft: string = '';

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

  /** 把一份报告摊到界面状态上；取数、检索、取舍、评判四条路径共用。 */
  private applyReport(report: ResearchReport): void {
    this.query = report.query === null ? '' : report.query;
    this.searchedAt = formatTimestamp(report.searched_at);
    this.sources = report.sources;
    this.records = report.records;
    this.counts = report.counts === undefined ? emptyCounts() : report.counts;

    const failures: SourceFailure[] = [];
    for (const provider of Object.keys(report.provider_failures)) {
      failures.push({ provider: provider, message: report.provider_failures[provider] });
    }
    this.failures = failures;
  }

  async load(): Promise<void> {
    this.loading = true;
    this.errorText = '';
    try {
      this.applyReport(await fetchResearch());
    } catch (err) {
      this.errorText = (err as Error).message;
    } finally {
      this.loading = false;
    }
  }

  /**
   * 跑一次检索。
   *
   * 检索词留空就是不传 query，后端按竞赛规则里的任务类型与模态拼一条 —— 这条路径
   * 不需要人自己编检索词；填了词就按词查，用于人工微调。
   */
  async runSearch(): Promise<void> {
    if (this.busy) {
      return;
    }
    this.busy = true;
    this.actionError = '';
    try {
      this.applyReport(await searchResearch(this.queryDraft.trim()));
      this.section = 'records';
    } catch (err) {
      this.actionError = (err as Error).message;
    } finally {
      this.busy = false;
    }
  }

  /** 记下一条候选的取舍；点已经选中的那一项等于取消选择。 */
  async decide(paperId: string, current: string, choice: string): Promise<void> {
    if (this.pendingId.length > 0) {
      return;
    }
    const next: string = current === choice ? 'undecided' : choice;
    this.pendingId = paperId;
    this.actionError = '';
    try {
      this.applyReport(await decideResearchCandidate(paperId, next, ''));
    } catch (err) {
      this.actionError = (err as Error).message;
    } finally {
      this.pendingId = '';
    }
  }

  /** 对已标记「调研」的候选做评判。 */
  async assess(): Promise<void> {
    if (this.busy) {
      return;
    }
    this.busy = true;
    this.actionError = '';
    try {
      this.applyReport(await assessResearchCandidates());
    } catch (err) {
      this.actionError = (err as Error).message;
    } finally {
      this.busy = false;
    }
  }

  /** 一行现状：候选数 · 已调研 · 已舍弃 · 已评判。 */
  private statusText(): string {
    if (this.counts.records === 0 && this.query.length === 0) {
      return '';
    }
    return this.trf('lit.status', [
      `${this.counts.records}`, `${this.counts.investigate}`, `${this.counts.discard}`, `${this.counts.assessed}`
    ]);
  }

  /** 分段导航的项。色点说的是这一段通不通，不是它有多少条。 */
  private railItems(): RailItemSpec[] {
    // 有调研没评判时，候选段的点变成告警色：这条链还差一步。
    const waiting: boolean = this.counts.investigate > this.counts.assessed;
    let recordsTone: string = 'muted';
    if (this.records.length > 0) {
      recordsTone = waiting ? 'warn' : 'ok';
    }
    return [
      {
        key: 'query',
        label: this.tr('lit.section.query'),
        tone: this.failures.length > 0 ? 'warn' : (this.records.length > 0 ? 'ok' : 'muted')
      },
      {
        key: 'records',
        label: this.tr('lit.section.records'),
        tone: recordsTone
      }
    ];
  }

  /** 取舍的可选项：调研 / 舍弃。 */
  private decisionChoices(): ChoiceSpec[] {
    return [
      { key: 'investigate', label: this.tr('lit.decideInvestigate'), tone: 'ok' },
      { key: 'discard', label: this.tr('lit.decideDiscard'), tone: 'warn' }
    ];
  }

  /** 分量行的文本：把分数的来源摊开，而不是只给一个数字。 */
  private partsText(item: ResearchRecord): string {
    const parts: RelevanceParts | undefined = item.relevance_parts;
    if (parts === undefined) {
      return '';
    }
    return [
      this.trf('lit.partTerms', [partValue(parts.terms)]),
      this.trf('lit.partTask', [partValue(parts.task)]),
      this.trf('lit.partCode', [partValue(parts.code)]),
      this.trf('lit.partRecency', [partValue(parts.recency)])
    ].join(' · ');
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

  /**
   * 一段次要信息（证据取值、评判时间这类）。
   *
   * @Builder 的返回值不能链属性，所以间距由参数传进来，调用处不要写 `.margin()`。
   */
  @Builder
  Muted(text: string, spaceTop: number) {
    Text(text)
      .fontSize(12)
      .fontColor(AppTheme.TEXT_TERTIARY)
      .width('100%')
      .margin({ top: spaceTop })
  }

  /** 评判结果卡：结论 + 建议 + 证据 + 找到的仓库。 */
  @Builder
  ReviewBlock(assessment: CandidateAssessment) {
    Column() {
      Flex({ wrap: FlexWrap.Wrap }) {
        StatusBadge({
          text: this.trf('lit.verdict', [verdictText(this.lang, assessment.verdict)]),
          tone: verdictTone(assessment.verdict)
        })
        StatusBadge({
          text: `${this.tr('lit.openSource')}：${openSourceText(this.lang, assessment)}`,
          tone: openSourceTone(assessment)
        })
          .margin({ left: 8 })
        StatusBadge({
          text: `${this.tr('lit.worthReproducing')}：${assessment.worth_reproducing ? this.tr('lit.worthYes') : this.tr('lit.worthNo')}`,
          tone: assessment.worth_reproducing ? 'ok' : 'muted'
        })
          .margin({ left: 8 })
      }
      .width('100%')

      Text(adviceText(this.lang, assessment.verdict))
        .fontSize(13)
        .fontColor(AppTheme.TEXT_PRIMARY)
        .width('100%')
        .margin({ top: 12 })

      // 官方归属单独说清楚：检索源不给作者归属，所以这一项只能是「无法证明」。
      this.Muted(
        `${this.tr('lit.officialCode')}：${assessment.has_official_code ? '✓' : this.tr('lit.officialCodeNone')}`,
        8
      )

      Flex({ wrap: FlexWrap.Wrap }) {
        ForEach(reviewSignals(assessment), (signal: CandidateSignal) => {
          Text(`${signalLabel(this.lang, signal.key)} ${signalDetail(this.lang, signal)}`)
            .fontSize(12)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .backgroundColor(AppTheme.SURFACE)
            .borderRadius(6)
            .padding({ left: 10, right: 10, top: 4, bottom: 4 })
            .margin({ right: 8, top: 8 })
        }, (signal: CandidateSignal) => `${signal.key}-${signal.detail}`)
      }
      .width('100%')

      if (assessment.code_candidates.length > 0) {
        Text(this.tr('lit.codeCandidates'))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .width('100%')
          .margin({ top: 14 })
        ForEach(assessment.code_candidates, (repo: CodeCandidate) => {
          Text(this.codeCandidateText(repo))
            .fontSize(12)
            .fontColor(AppTheme.PRIMARY)
            .width('100%')
            .margin({ top: 6 })
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }, (repo: CodeCandidate) => repo.repository)
      }

      this.Muted(this.trf('lit.assessedAt', [formatTimestamp(assessment.assessed_at)]), 12)
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding(14)
    .backgroundColor(AppTheme.PAGE_BG)
    .borderRadius(AppTheme.RADIUS)
    .margin({ top: 12 })
  }

  /** 一行候选实现仓库：仓库名 · 标题重合 · 许可 · 星数。 */
  private codeCandidateText(repo: CodeCandidate): string {
    const pieces: string[] = [repo.repository, this.trf('lit.codeOverlap', [formatNumber(repo.title_overlap, 2)])];
    if (repo.license !== null && repo.license.length > 0) {
      pieces.push(repo.license);
    }
    if (repo.stars !== null) {
      pieces.push(this.trf('lit.codeStars', [`${repo.stars}`]));
    }
    return pieces.join(' · ');
  }

  @Builder
  RecordRow(item: ResearchRecord) {
    Column() {
      Text(item.title)
        .fontSize(14)
        .fontWeight(FontWeight.Medium)
        .fontColor(AppTheme.TEXT_PRIMARY)
        .maxLines(2)
        .textOverflow({ overflow: TextOverflow.Ellipsis })

      Text([
        item.venue === null || item.venue.length === 0 ? this.tr('lit.venueUnknown') : item.venue,
        item.year === null ? this.tr('lit.yearUnknown') : `${item.year}`,
        item.authors.length > 0 ? item.authors.join(this.tr('lit.authorSeparator')) : this.tr('lit.authorsUnknown')
      ].join(' · '))
        .fontSize(12)
        .fontColor(AppTheme.TEXT_TERTIARY)
        .margin({ top: 8 })
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })

      Row() {
        Text(this.trf('lit.relevance', [formatNumber(item.relevance_score, 3)]))
          .fontSize(13)
          .fontWeight(FontWeight.Medium)
          .fontColor(AppTheme.TEXT_PRIMARY)
        if (this.partsText(item).length > 0) {
          Text(this.partsText(item))
            .fontSize(12)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .margin({ left: 12 })
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .margin({ top: 10 })

      Row() {
        Text(this.tr('lit.decisionLabel'))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
        StatusBadge({
          text: decisionText(this.lang, item.decision),
          tone: decisionTone(item.decision)
        })
          .margin({ left: 8 })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .margin({ top: 12 })

      ChoiceChips({
        items: this.decisionChoices(),
        active: item.decision === 'undecided' ? '' : item.decision,
        disabled: this.pendingId === item.paper_id,
        onSelect: (key: string) => {
          this.decide(item.paper_id, item.decision, key);
        }
      })
        .margin({ top: 8 })

      if (item.assessment !== null) {
        this.ReviewBlock(item.assessment)
      }

      if (item.url !== null && item.url.length > 0) {
        Text(item.url)
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .margin({ top: 10 })
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ top: 16, bottom: 16 })
    .border({ width: { bottom: 1 }, color: AppTheme.BORDER_SOFT })
  }

  /** 检索条件段：人工检索词 + 触发检索 + 本轮条件与失败源。 */
  @Builder
  QuerySection() {
    CardPanel({
      title: this.tr('lit.queryInfo')
    }) {
      Column() {
        Row() {
          TextInput({ text: this.queryDraft, placeholder: this.tr('lit.queryPlaceholder') })
            .layoutWeight(1)
            .height(38)
            .fontSize(13)
            .backgroundColor(AppTheme.PAGE_BG)
            .borderRadius(AppTheme.RADIUS_SM)
            .enabled(!this.busy)
            .onChange((value: string) => {
              this.queryDraft = value;
            })

          Text(this.busy ? this.tr('lit.searching') : this.tr(this.records.length > 0 ? 'lit.rerunSearch' : 'lit.runSearch'))
            .fontSize(13)
            .fontColor(Color.White)
            .backgroundColor(AppTheme.PRIMARY)
            .borderRadius(AppTheme.RADIUS_SM)
            .padding({ left: 16, right: 16, top: 9, bottom: 9 })
            .margin({ left: 10 })
            .opacity(this.busy ? 0.6 : 1)
            .onClick(() => {
              this.runSearch();
            })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 表单提示：说明留空会发生什么，属于操作本身的说明。
        this.Muted(this.tr('lit.fromSpecHint'), 8)

        Text(this.trf('lit.query', [this.query.length > 0 ? this.query : '—']))
          .fontSize(13)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .width('100%')
          .margin({ top: 18 })
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        Text(this.trf('lit.searchedAt', [this.searchedAt]))
          .fontSize(13)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .margin({ top: 10 })

        Row() {
          Text(this.tr('lit.dataSources'))
            .fontSize(13)
            .fontColor(AppTheme.TEXT_SECONDARY)
          ForEach(this.sources, (source: string) => {
            Text(source)
              .fontSize(12)
              .fontColor(AppTheme.TEXT_SECONDARY)
              .backgroundColor(AppTheme.PAGE_BG)
              .borderRadius(6)
              .padding({ left: 10, right: 10, top: 4, bottom: 4 })
              .margin({ left: 10 })
          }, (source: string) => source)
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)
        .margin({ top: 12 })

        if (this.failures.length > 0) {
          Column() {
            Text(this.tr('lit.failedSourcesHint'))
              .fontSize(13)
              .fontColor(AppTheme.WARN_TEXT)
            ForEach(this.failures, (item: SourceFailure) => {
              Text(this.trf('lit.providerFailure', [item.provider, item.message]))
                .fontSize(12)
                .fontColor(AppTheme.WARN_TEXT)
                .margin({ top: 6 })
                .maxLines(2)
                .textOverflow({ overflow: TextOverflow.Ellipsis })
            }, (item: SourceFailure) => item.provider)
          }
          .alignItems(HorizontalAlign.Start)
          .width('100%')
          .padding(14)
          .backgroundColor(AppTheme.WARN_SOFT)
          .borderRadius(AppTheme.RADIUS_SM)
          .margin({ top: 14 })
        }

        if (this.actionError.length > 0) {
          Text(this.trf('lit.actionFailed', [this.actionError]))
            .fontSize(12)
            .fontColor(AppTheme.DANGER)
            .width('100%')
            .margin({ top: 14 })
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
  }

  /** 候选段：逐条取舍 + 对调研过的做评判。 */
  @Builder
  CandidatesSection() {
    CardPanel({
      title: this.tr('lit.records')
    }) {
      Column() {
        Row() {
          Text(this.trf('lit.assessSummary', [
            `${this.counts.investigate}`, `${this.counts.discard}`, `${this.counts.assessed}`
          ]))
            .fontSize(13)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .layoutWeight(1)

          Text(this.busy ? this.tr('lit.assessing') : this.tr('lit.assessRun'))
            .fontSize(13)
            .fontColor(Color.White)
            .backgroundColor(this.counts.investigate > 0 && !this.busy ? AppTheme.PRIMARY : AppTheme.TEXT_TERTIARY)
            .borderRadius(AppTheme.RADIUS_SM)
            .padding({ left: 16, right: 16, top: 9, bottom: 9 })
            .onClick(() => {
              this.assess();
            })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        if (this.actionError.length > 0) {
          Text(this.trf('lit.actionFailed', [this.actionError]))
            .fontSize(12)
            .fontColor(AppTheme.DANGER)
            .width('100%')
            .margin({ top: 12 })
        }

        if (this.records.length === 0) {
          EmptyHint({ text: this.tr('lit.noRecords') })
            .margin({ top: 12 })
        } else {
          if (this.counts.investigate === 0) {
            // 上一步还没做：评判只对「调研」的候选做，这里说清楚要先去上面选。
            this.Muted(this.tr('lit.assessNone'), 12)
          }

          Column() {
            ForEach(this.records, (item: ResearchRecord) => {
              this.RecordRow(item)
            }, (item: ResearchRecord) => `${item.paper_id}-${item.decision}-${item.assessment === null ? 'none' : 'assessed'}`)
          }
          .width('100%')
          .margin({ top: 8 })

          // 「收录不等于复现或背书」是记录清单的免责说明，属于内容而不是标题注脚。
          this.Muted(this.tr('lit.recordsNote'), 16)
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
  }

  build() {
    Column({ space: 20 }) {
      PageHeader({
        title: this.tr('nav.literature'),
        status: this.statusText(),
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

      if (this.section === 'records') {
        this.CandidatesSection()
      } else {
        this.QuerySection()
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
