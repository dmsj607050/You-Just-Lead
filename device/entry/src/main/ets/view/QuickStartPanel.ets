import AppTheme from '../common/AppTheme';
import IconPaths from '../common/IconPaths';
import { tFor } from '../common/I18n';
import { QuickAction, QUICK_ACTIONS } from '../common/ViewTypes';
import { AppIcon } from './AppIcon';

/** 快速开始：宽窗口两列，窄窗口单列铺开。 */
@Component
export struct QuickStartPanel {
  /**
   * 当前语言。ArkUI 只重建读到状态变量的节点，所以本组件所有文案都走 this.tr()，
   * 由它读一次 this.lang，等于把用到的节点登记到语言变化上。
   */
  @StorageLink('lang') lang: string = 'zh';

  /** 取文案：读一次 lang，让调用它的节点订阅语言变化。 */
  private tr(key: string): string {
    return tFor(this.lang, key);
  }

  /** 点击任一入口，回传目标导航 key。 */
  onNavigate: (key: string) => void = () => {
  };
  /** 卡片变窄时用单列，避免两列把标题挤成两行。 */
  @State stacked: boolean = false;

  build() {
    Column() {
      Text(this.tr('quick.title'))
        .fontSize(17)
        .fontWeight(FontWeight.Bold)
        .fontColor(AppTheme.TEXT_PRIMARY)
        .margin({ bottom: 14 })

      Flex({ wrap: FlexWrap.Wrap, justifyContent: FlexAlign.SpaceBetween }) {
        ForEach(QUICK_ACTIONS, (item: QuickAction) => {
          Row() {
            Column() {
              Text(this.tr(item.titleKey))
                .fontSize(14)
                .fontColor(AppTheme.TEXT_PRIMARY)
              Text(this.tr(item.detailKey))
                .fontSize(12)
                .fontColor(AppTheme.TEXT_TERTIARY)
                .margin({ top: 5 })
                .maxLines(1)
                .textOverflow({ overflow: TextOverflow.Ellipsis })
            }
            .alignItems(HorizontalAlign.Start)
            .layoutWeight(1)

            AppIcon({
              commands: IconPaths.CHEVRON_SMALL,
              color: AppTheme.TEXT_TERTIARY,
              filled: false,
              iconSize: 16
            })
          }
          .width(this.stacked ? '100%' : '48.5%')
          .padding({ left: 14, right: 14, top: 14, bottom: 14 })
          .backgroundColor(AppTheme.PAGE_BG)
          .borderRadius(AppTheme.RADIUS_SM)
          .alignItems(VerticalAlign.Center)
          .margin({ bottom: 10 })
          .onClick(() => {
            this.onNavigate(item.nav);
          })
        }, (item: QuickAction) => item.key)
      }
      .width('100%')
      .onAreaChange((oldValue: Area, newValue: Area) => {
        const width: number = Number(newValue.width);
        this.stacked = width > 0 && width < 330;
      })
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding(24)
    .backgroundColor(AppTheme.SURFACE)
    .borderRadius(AppTheme.RADIUS_LG)
    .border({ width: 1, color: AppTheme.BORDER })
  }
}
