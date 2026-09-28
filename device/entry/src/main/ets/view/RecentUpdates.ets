import AppTheme from '../common/AppTheme';
import IconPaths from '../common/IconPaths';
import { eventTitle, relativeTime } from '../common/Format';
import { tFor } from '../common/I18n';
import { UpdateSpec } from '../common/ViewTypes';
import { AppIcon } from './AppIcon';

/** 最近更新：后端事件流的精简列表。 */
@Component
export struct RecentUpdates {
  @Prop updates: UpdateSpec[] = [];
  /**
   * 当前语言。ArkUI 只重建读到状态变量的节点，所以本组件所有文案都走 this.tr()，
   * 由它读一次 this.lang，等于把用到的节点登记到语言变化上。
   */
  @StorageLink('lang') lang: string = 'zh';

  /** 取文案：读一次 lang，让调用它的节点订阅语言变化。 */
  private tr(key: string): string {
    return tFor(this.lang, key);
  }

  build() {
    Column() {
      Row() {
        Text(this.tr('overview.recentUpdates'))
          .fontSize(17)
          .fontWeight(FontWeight.Bold)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .layoutWeight(1)
      }
      .width('100%')
      .margin({ bottom: 8 })

      if (this.updates.length === 0) {
        Text(this.tr('overview.noRecords'))
          .fontSize(14)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .margin({ top: 12 })
      } else {
        ForEach(this.updates, (item: UpdateSpec) => {
          Row() {
            Stack({ alignContent: Alignment.Center }) {
              AppIcon({
                commands: IconPaths.DOC,
                color: AppTheme.PRIMARY,
                filled: false,
                iconSize: 18
              })
            }
            .width(34)
            .height(34)
            .backgroundColor(AppTheme.PRIMARY_SOFT)
            .borderRadius(AppTheme.RADIUS_SM)

            Column() {
              Text(eventTitle(this.lang, item.eventType))
                .fontSize(14)
                .fontColor(AppTheme.TEXT_PRIMARY)
                .maxLines(1)
                .textOverflow({ overflow: TextOverflow.Ellipsis })
              Text(item.eventType)
                .fontSize(12)
                .fontColor(AppTheme.TEXT_TERTIARY)
                .margin({ top: 4 })
                .maxLines(1)
                .textOverflow({ overflow: TextOverflow.Ellipsis })
            }
            .alignItems(HorizontalAlign.Start)
            .layoutWeight(1)
            .margin({ left: 12 })

            Text(relativeTime(this.lang, item.createdAt))
              .fontSize(12)
              .fontColor(AppTheme.TEXT_TERTIARY)
          }
          .width('100%')
          .alignItems(VerticalAlign.Center)
          .padding({ top: 12, bottom: 12 })
          .border({ width: { bottom: 1 }, color: AppTheme.BORDER_SOFT })
        }, (item: UpdateSpec, index: number) => `${index}-${item.eventType}`)
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding(24)
    .backgroundColor(AppTheme.SURFACE)
    .borderRadius(AppTheme.RADIUS_LG)
    .border({ width: 1, color: AppTheme.BORDER })
  }
}
