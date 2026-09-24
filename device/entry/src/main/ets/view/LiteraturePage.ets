import { fetchResearch, ResearchRecord, ResearchReport } from '../common/BackendClient';
import AppTheme from '../common/AppTheme';
import { formatNumber, formatTimestamp } from '../common/Format';
import { tFor, tfFor } from '../common/I18n';
import { CardPanel, EmptyHint, PageHeader, RailItemSpec, SectionRail, StatusBadge } from './Widgets';

/** 某个数据源的失败记录：provider 与后端错误原文分开存，展示时才拼，避免文案被定死。 */
interface SourceFailure {
  provider: string;
  message: string;
}

/** 复现优先级的可读名称。语言作为参数，由调用处在渲染时把 this.lang 传进来。 */
function priorityText(lang: string, value: string | null): string {
  if (value === null || value.length === 0) {
    return tFor(lang, 'lit.unrated');
  }
  if (value === 'high') {
    return tFor(lang, 'lit.priorityHigh');
  }
  if (value === 'medium') {
    return tFor(lang, 'lit.priorityMedium');
  }
  if (value === 'low') {
    return tFor(lang, 'lit.priorityLow');
  }
  return value;
}

/** 复现优先级的徽章色调。 */
function priorityBadgeTone(value: string | null): string {
  if (value === 'high') {
    return 'ok';
  }
  if (value === 'medium') {
    return 'warn';
  }
  return 'muted';
}

/**
 * 文献页：公开文献雷达的检索记录。
 *
 * 只展示检索到的原始记录，收录不等于复现或背书。
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
  /**
   * 当前分段：query / records。
   *
   * 记录一多，检索条件就会被顶到看不见。分成两段之后，条件与清单各占一屏。
   */
  @State section: string = 'query';

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
      const report: ResearchReport = await fetchResearch();
      this.query = report.query === null ? '' : report.query;
      this.searchedAt = formatTimestamp(report.searched_at);
      this.sources = report.sources;
      this.records = report.records;

      const failures: SourceFailure[] = [];
      for (const provider of Object.keys(report.provider_failures)) {
        failures.push({ provider: provider, message: report.provider_failures[provider] });
      }
      this.failures = failures;
    } catch (err) {
      const error = err as Error;
      this.errorText = error.message;
    } finally {
      this.loading = false;
    }
  }

  /** 带官方代码的论文数量。 */
  private withCode(): number {
    let count: number = 0;
    for (const item of this.records) {
      if (item.official_code === true || (item.code_url !== null && item.code_url.length > 0)) {
        count++;
      }
    }
    return count;
  }

  /** 一行现状：记录数 · 来源数 · 带代码条数 · 失败源数。 */
  private statusText(): string {
    if (this.records.length === 0 && this.query.length === 0) {
      return '';
    }
    return this.trf('lit.status', [
      `${this.records.length}`, `${this.sources.length}`, `${this.withCode()}`, `${this.failures.length}`
    ]);
  }

  /** 分段导航的项。色点说的是这一段通不通，不是它有多少条。 */
  private railItems(): RailItemSpec[] {
    return [
      {
        key: 'query',
        label: this.tr('lit.section.query'),
        tone: this.failures.length > 0 ? 'warn' : (this.records.length > 0 ? 'ok' : 'muted')
      },
      {
        key: 'records',
        label: this.tr('lit.section.records'),
        tone: this.records.length > 0 ? 'ok' : 'muted'
      }
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
        StatusBadge({
          text: priorityText(this.lang, item.reproduction_priority),
          tone: priorityBadgeTone(item.reproduction_priority)
        })
        Text(this.trf('lit.relevance', [formatNumber(item.relevance_score, 3)]))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .margin({ left: 12 })
        if (item.code_url !== null && item.code_url.length > 0) {
          Text(item.official_code === true ? this.tr('lit.officialCode') : this.tr('lit.codeLink'))
            .fontSize(12)
            .fontColor(AppTheme.PRIMARY)
            .margin({ left: 12 })
        }
      }
      .margin({ top: 10 })
      .alignItems(VerticalAlign.Center)

      if (item.url !== null && item.url.length > 0) {
        Text(item.url)
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .margin({ top: 8 })
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ top: 14, bottom: 14 })
    .border({ width: { bottom: 1 }, color: AppTheme.BORDER_SOFT })
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
        CardPanel({
          title: this.tr('lit.records')
        }) {
          if (this.records.length === 0) {
            EmptyHint({ text: this.tr('lit.noRecords') })
          } else {
            Column() {
              ForEach(this.records, (item: ResearchRecord) => {
                this.RecordRow(item)
              }, (item: ResearchRecord) => item.paper_id)
            }
            .width('100%')

            // 「收录不等于复现或背书」是记录清单的免责说明，属于内容而不是标题注脚。
            Text(this.tr('lit.recordsNote'))
              .fontSize(12)
              .fontColor(AppTheme.TEXT_TERTIARY)
              .width('100%')
              .margin({ top: 16 })
          }
        }
      } else {
        CardPanel({
          title: this.tr('lit.queryInfo')
        }) {
          Column() {
            Text(this.trf('lit.query', [this.query.length > 0 ? this.query : '—']))
              .fontSize(13)
              .fontColor(AppTheme.TEXT_PRIMARY)
              .width('100%')
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
          }
          .width('100%')
          .alignItems(HorizontalAlign.Start)
        }
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
