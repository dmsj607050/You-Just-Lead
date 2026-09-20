import AppTheme from '../common/AppTheme';
import { priorityLabel } from '../common/Format';
import { tFor } from '../common/I18n';

/** 「下一步」细条：展示后端给出的最高优先级动作。 */
@Component
export struct NextStepStrip {
  /** 动作描述，为空表示当前没有待办。 */
  @Prop action: string = '';
  /** 后端优先级枚举。 */
  @Prop priority: string = '';
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
    Row() {
      Text(this.tr('overview.nextStep'))
        .fontSize(12)
        .fontColor(AppTheme.PRIMARY_DARK)
        .backgroundColor(AppTheme.PRIMARY_SOFT)
        .borderRadius(6)
        .padding({ left: 10, right: 10, top: 4, bottom: 4 })

      if (this.action.length > 0) {
        Text(this.action)
          .fontSize(14)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .layoutWeight(1)
          .margin({ left: 12 })
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        Text(priorityLabel(this.lang, this.priority))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_SECONDARY)
      } else {
        Text(this.tr('overview.noPendingActions'))
          .fontSize(14)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .layoutWeight(1)
          .margin({ left: 12 })
      }
    }
    .width('100%')
    .padding({ left: 20, right: 20, top: 14, bottom: 14 })
    .backgroundColor(AppTheme.SURFACE)
    .borderRadius(AppTheme.RADIUS)
    .border({ width: 1, color: AppTheme.BORDER })
    .alignItems(VerticalAlign.Center)
    .margin({ top: 16 })
  }
}
