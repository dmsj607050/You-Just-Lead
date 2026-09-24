import { DataAuditReport, MetricRange, fetchDataAudit } from '../common/BackendClient';
import AppTheme from '../common/AppTheme';
import { formatBytes, formatNumber, formatTimestamp } from '../common/Format';
import { tFor, tfFor } from '../common/I18n';
import { BarItemSpec, BarList, CardPanel, EmptyHint, KeyValueRow, PageHeader, RailItemSpec, SectionRail } from './Widgets';

/** Record 形式统计项转成可渲染的行。 */
interface NameCount {
  name: string;
  count: number;
}

/** 把后端返回的统计字典摊平成列表。 */
function toRows(map: Record<string, number>): NameCount[] {
  const rows: NameCount[] = [];
  for (const key of Object.keys(map)) {
    rows.push({ name: key, count: map[key] });
  }
  return rows;
}

/** 文件类型的可读名称。语言作为参数，由调用处在渲染时把 this.lang 传进来。 */
function kindLabel(lang: string, kind: string): string {
  if (kind === 'file') {
    return tFor(lang, 'data.kindFile');
  }
  if (kind === 'image') {
    return tFor(lang, 'data.kindImage');
  }
  if (kind === 'mask') {
    return tFor(lang, 'data.kindMask');
  }
  if (kind === 'table') {
    return tFor(lang, 'data.kindTable');
  }
  return kind;
}

/** 数据划分的可读名称。语言作为参数，由调用处在渲染时把 this.lang 传进来。 */
function splitLabel(lang: string, split: string): string {
  if (split === 'train') {
    return tFor(lang, 'data.splitTrain');
  }
  if (split === 'val' || split === 'valid' || split === 'validation') {
    return tFor(lang, 'data.splitValidation');
  }
  if (split === 'test') {
    return tFor(lang, 'data.splitTest');
  }
  if (split === 'unassigned') {
    return tFor(lang, 'data.splitUnassigned');
  }
  return split;
}

/**
 * 数据页：最近一次数据审计的结果。
 *
 * 审计只陈述看到的事实，这里同样只展示已记录的内容。
 */
@Component
export struct DataPage {
  /**
   * 当前语言。ArkUI 只重建读到状态变量的节点，所以本组件所有文案都走 this.tr()，
   * 由它读一次 this.lang，等于把用到的节点登记到语言变化上。
   */
  @StorageLink('lang') lang: string = 'zh';
  @State loading: boolean = false;
  @State errorText: string = '';
  @State audit: DataAuditReport | null = null;
  @State kindRows: NameCount[] = [];
  @State splitRows: NameCount[] = [];
  /**
   * 当前分段：source / images / kinds / issues。
   *
   * 原先四张卡加一排统计块堆在一列。现在一次只看一段，「多少文件、多少问题」写在标题下面一行里。
   */
  @State section: string = 'source';

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
      const report: DataAuditReport = await fetchDataAudit();
      this.audit = report;
      this.kindRows = toRows(report.file_kinds);
      this.splitRows = toRows(report.splits);
    } catch (err) {
      const error = err as Error;
      this.errorText = error.message;
    } finally {
      this.loading = false;
    }
  }

  /** 一行现状：文件数 · 总大小 · 问题数 · 重复组数。 */
  private statusText(): string {
    if (this.audit === null) {
      return '';
    }
    return this.trf('data.status', [
      `${this.audit.file_count}`,
      formatBytes(this.audit.total_bytes),
      `${this.audit.issue_count}`,
      `${this.audit.exact_duplicate_groups.length}`
    ]);
  }

  /** 分段导航的项。色点说的是这一段通不通，不是它有多少条。 */
  private railItems(): RailItemSpec[] {
    return [
      { key: 'source', label: this.tr('data.section.source'), tone: this.audit === null ? 'warn' : 'ok' },
      { key: 'images', label: this.tr('data.section.images'), tone: this.audit === null ? 'muted' : 'ok' },
      { key: 'kinds', label: this.tr('data.section.kinds'), tone: 'muted' },
      {
        key: 'issues',
        label: this.tr('data.section.issues'),
        tone: this.audit === null ? 'muted' : (this.audit.issue_count === 0 ? 'ok' : 'warn')
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

  /** 文件类型分布，给分布条用。 */
  private kindBars(): BarItemSpec[] {
    const bars: BarItemSpec[] = [];
    for (const item of this.kindRows) {
      bars.push({ label: kindLabel(this.lang, item.name), value: item.count, valueText: `${item.count}` });
    }
    return bars;
  }

  /** 划分（训练/验证/测试）分布，给分布条用。 */
  private splitBars(): BarItemSpec[] {
    const bars: BarItemSpec[] = [];
    for (const item of this.splitRows) {
      bars.push({ label: splitLabel(this.lang, item.name), value: item.count, valueText: `${item.count}` });
    }
    return bars;
  }

  /**
   * 通道分布。
   *
   * 这张表以前完全没显示过，但它是多模态数据最重要的一条事实：单通道是 16 位深度图，
   * 三通道是彩色图。数字摆在那儿，条形一眼就能看出比例。
   */
  private channelBars(): BarItemSpec[] {
    const bars: BarItemSpec[] = [];
    if (this.audit === null) {
      return bars;
    }
    const channels: Record<string, number> = this.audit.images.channels;
    for (const key of Object.keys(channels)) {
      bars.push({
        label: this.trf('data.channelLabel', [key]),
        value: channels[key],
        valueText: `${channels[key]}`
      });
    }
    return bars;
  }

  /**
   * 把范围统计压成一行。
   *
   * 后端给的 `width` / `height` 是 `{min, max, mean}` 三元组，不是一个数：
   * 直接把它塞进模板字符串会渲染成 `[object Object]`。
   */
  private rangeText(range: MetricRange | null): string {
    if (range === null) {
      return '—';
    }
    return `${range.min}–${range.max}`;
  }

  build() {
    Column({ space: 20 }) {
      PageHeader({
        title: this.tr('nav.data'),
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

      if (this.section === 'source') {
        CardPanel({
          title: this.tr('data.auditSource')
        }) {
          Column() {
            KeyValueRow({
              label: this.tr('data.dataDir'),
              value: this.audit === null ? '—' : this.audit.data_dir,
              mono: true
            })
            KeyValueRow({
              label: this.tr('data.auditTime'),
              value: this.audit === null ? '—' : formatTimestamp(this.audit.generated_at)
            })
            KeyValueRow({
              label: this.tr('data.metadataFormat'),
              value: this.audit === null ? '—' : this.audit.metadata_format
            })
            KeyValueRow({
              label: this.tr('data.inventoryHash'),
              value: this.audit === null ? '—' : this.audit.inventory_sha256,
              mono: true
            })
            KeyValueRow({
              label: this.tr('data.schemaVersion'),
              value: this.audit === null ? '—' : `v${this.audit.audit_schema_version}`
            })
          }
          .width('100%')
        }
      } else if (this.section === 'images') {
        CardPanel({
          title: this.tr('data.imagesAndMasks')
        }) {
          Column() {
            KeyValueRow({
              label: this.tr('data.imageCount'),
              value: this.audit === null ? '—' : `${this.audit.images.count}`
            })
            KeyValueRow({
              label: this.tr('data.imageSize'),
              value: this.audit === null
                ? '—'
                : `${this.rangeText(this.audit.images.width)} × ${this.rangeText(this.audit.images.height)}`
            })
            KeyValueRow({
              label: this.tr('data.maskCount'),
              value: this.audit === null ? '—' : `${this.audit.segmentation_masks.count}`
            })
            KeyValueRow({
              label: this.tr('data.emptyMasks'),
              value: this.audit === null ? '—' : `${this.audit.segmentation_masks.empty_count}`
            })
            KeyValueRow({
              label: this.tr('data.foregroundRatio'),
              value: this.audit === null || this.audit.segmentation_masks.foreground_ratio === null
                ? '—'
                : formatNumber(this.audit.segmentation_masks.foreground_ratio.mean, 4)
            })

            if (this.channelBars().length > 0) {
              Text(this.tr('data.channelDistribution'))
                .fontSize(13)
                .fontColor(AppTheme.TEXT_SECONDARY)
                .width('100%')
                .margin({ top: 16, bottom: 12 })
              BarList({ items: this.channelBars() })
            }
          }
          .width('100%')
        }
      } else if (this.section === 'kinds') {

        Row({ space: 20 }) {
          CardPanel({
            title: this.tr('data.fileKinds'),
            weight: 1
          }) {
            if (this.kindRows.length === 0) {
              EmptyHint({ text: this.tr('data.noFileKinds') })
            } else {
              BarList({ items: this.kindBars() })
            }
          }

          CardPanel({
            title: this.tr('data.splits'),
            weight: 1
          }) {
            if (this.splitRows.length === 0) {
              EmptyHint({ text: this.tr('data.noSplits') })
            } else {
              BarList({ items: this.splitBars() })
            }
          }
        }
        .width('100%')
        .alignItems(VerticalAlign.Top)
      } else {
        CardPanel({
          title: this.tr('data.duplicatesAndTables')
        }) {
          Column() {
            if (this.audit === null || this.audit.exact_duplicate_groups.length === 0) {
              EmptyHint({ text: this.tr('data.noDuplicates') })
            } else {
              ForEach(this.audit.exact_duplicate_groups, (group: string[], index: number) => {
                Column() {
                  Text(this.trf('data.duplicateGroup', [`${index + 1}`]))
                    .fontSize(13)
                    .fontColor(AppTheme.TEXT_PRIMARY)
                  ForEach(group, (file: string) => {
                    Text(file)
                      .fontSize(12)
                      .fontColor(AppTheme.TEXT_TERTIARY)
                      .margin({ top: 6 })
                      .maxLines(1)
                      .textOverflow({ overflow: TextOverflow.Ellipsis })
                  }, (file: string) => file)
                }
                .alignItems(HorizontalAlign.Start)
                .width('100%')
                .padding({ top: 12, bottom: 12 })
              }, (group: string[], index: number) => `${index}`)
            }

            if (this.audit !== null && this.audit.tables.length > 0) {
              Text(this.trf('data.tableFiles', [`${this.audit.tables.length}`]))
                .fontSize(13)
                .fontColor(AppTheme.TEXT_SECONDARY)
                .margin({ top: 12 })
            }
          }
          .width('100%')
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
