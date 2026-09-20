import { DataAuditReport, fetchDataAudit } from '../common/BackendClient';
import AppTheme from '../common/AppTheme';
import { formatBytes, formatNumber, formatTimestamp } from '../common/Format';
import { tFor, tfFor } from '../common/I18n';
import { CardPanel, EmptyHint, KeyValueRow, PageHeader, StatTileGrid } from './Widgets';

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
  CountRow(item: NameCount, label: string) {
    Row() {
      Text(label)
        .fontSize(13)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .layoutWeight(1)
      Text(`${item.count}`)
        .fontSize(13)
        .fontColor(AppTheme.TEXT_PRIMARY)
    }
    .width('100%')
    .padding({ top: 10, bottom: 10 })
    .border({ width: { bottom: 1 }, color: AppTheme.BORDER_SOFT })
  }

  build() {
    Column({ space: 20 }) {
      PageHeader({
        title: this.tr('nav.data'),
        subtitle: this.tr('data.subtitle'),
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
            label: this.tr('data.fileCount'),
            value: this.audit === null ? '—' : `${this.audit.file_count}`,
            hint: this.tr('data.fileCountHint')
          },
          {
            label: this.tr('data.issueCount'),
            value: this.audit === null ? '—' : `${this.audit.issue_count}`,
            hint: this.tr('data.issueCountHint')
          },
          {
            label: this.tr('data.totalSize'),
            value: this.audit === null ? '—' : formatBytes(this.audit.total_bytes),
            hint: this.tr('data.totalSizeHint')
          },
          {
            label: this.tr('data.duplicateGroups'),
            value: this.audit === null ? '—' : `${this.audit.exact_duplicate_groups.length}`,
            hint: this.tr('data.duplicateGroupsHint')
          }
        ]
      })

      CardPanel({
        title: this.tr('data.auditSource'),
        subtitle: this.tr('data.auditSourceHint')
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

      CardPanel({
        title: this.tr('data.imagesAndMasks'),
        subtitle: this.tr('data.imagesAndMasksHint')
      }) {
        Column() {
          KeyValueRow({
            label: this.tr('data.imageCount'),
            value: this.audit === null ? '—' : `${this.audit.images.count}`
          })
          KeyValueRow({
            label: this.tr('data.imageSize'),
            value: this.audit === null || this.audit.images.width === null
              ? '—'
              : `${this.audit.images.width} × ${this.audit.images.height}`
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
            value: this.audit === null
              ? '—'
              : formatNumber(this.audit.segmentation_masks.foreground_ratio, 4)
          })
        }
        .width('100%')
      }

      Row({ space: 20 }) {
        CardPanel({
          title: this.tr('data.fileKinds'),
          subtitle: this.tr('data.fileKindsHint'),
          weight: 1
        }) {
          if (this.kindRows.length === 0) {
            EmptyHint({ text: this.tr('data.noFileKinds') })
          } else {
            Column() {
              ForEach(this.kindRows, (item: NameCount) => {
                this.CountRow(item, kindLabel(this.lang, item.name))
              }, (item: NameCount) => item.name)
            }
            .width('100%')
          }
        }

        CardPanel({
          title: this.tr('data.splits'),
          subtitle: this.tr('data.splitsHint'),
          weight: 1
        }) {
          if (this.splitRows.length === 0) {
            EmptyHint({ text: this.tr('data.noSplits') })
          } else {
            Column() {
              ForEach(this.splitRows, (item: NameCount) => {
                this.CountRow(item, splitLabel(this.lang, item.name))
              }, (item: NameCount) => item.name)
            }
            .width('100%')
          }
        }
      }
      .width('100%')
      .alignItems(VerticalAlign.Top)

      CardPanel({
        title: this.tr('data.duplicatesAndTables'),
        subtitle: this.tr('data.duplicatesAndTablesHint')
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
