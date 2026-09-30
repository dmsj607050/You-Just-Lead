import AppTheme from '../common/AppTheme';
import IconPaths from '../common/IconPaths';
import { tFor } from '../common/I18n';
import { NavItem, NAV_ITEMS } from '../common/ViewTypes';
import { AppIcon } from './AppIcon';

/** 侧栏：可滚动的分组导航 + 固定设置入口。 */
@Component
export struct SideNav {
  /**
   * 当前语言。ArkUI 只重建读到状态变量的节点，所以本组件所有文案都走 this.tr()，
   * 由它读一次 this.lang，等于把用到的节点登记到语言变化上。
   */
  @StorageLink('lang') lang: string = 'zh';

  /** 取文案：读一次 lang，让调用它的节点订阅语言变化。 */
  private tr(key: string): string {
    return tFor(this.lang, key);
  }

  /** 导航分组固定，模块顺序由共享导航表决定。 */
  private navGroupKeys(): string[] {
    return ['workspace', 'research', 'outputs'];
  }

  private itemsForGroup(groupKey: string): NavItem[] {
    return NAV_ITEMS.filter((item: NavItem) => item.group === groupKey);
  }

  /** 当前选中的导航 key。 */
  @Prop activeKey: string = 'project';
  /** 阻塞项数量，大于 0 时在工作流项上显示角标。 */
  @Prop blockerCount: number = 0;
  /** 点击导航项。 */
  onSelect: (key: string) => void = () => {
  };

  build() {
    Column() {
      Scroll() {
        Column() {
          ForEach(this.navGroupKeys(), (groupKey: string) => {
            Column() {
              Text(this.tr(`nav.group.${groupKey}`))
                .fontSize(11)
                .fontWeight(FontWeight.Medium)
                .fontColor(AppTheme.TEXT_TERTIARY)
                .margin({ left: 12, bottom: 6 })

              ForEach(this.itemsForGroup(groupKey), (item: NavItem) => {
                Row() {
                  AppIcon({
                    commands: item.icon,
                    color: this.activeKey === item.key ? AppTheme.PRIMARY : AppTheme.TEXT_TERTIARY,
                    filled: false,
                    iconSize: 24
                  })
                  Text(this.tr(`nav.${item.key}`))
                    .fontSize(15)
                    .fontWeight(this.activeKey === item.key ? FontWeight.Medium : FontWeight.Normal)
                    .fontColor(this.activeKey === item.key ? AppTheme.PRIMARY_DARK : AppTheme.TEXT_SECONDARY)
                    .margin({ left: 12 })
                    .layoutWeight(1)
                  if (item.key === 'workflow' && this.blockerCount > 0) {
                    Text(`${this.blockerCount}`)
                      .fontSize(11)
                      .fontColor(Color.White)
                      .backgroundColor(AppTheme.DANGER)
                      .borderRadius(9)
                      .padding({ left: 6, right: 6, top: 1, bottom: 1 })
                  }
                }
                .width('100%')
                .height(44)
                .padding({ left: 12, right: 12 })
                .backgroundColor(this.activeKey === item.key ? AppTheme.PRIMARY_SOFT : Color.Transparent)
                .borderRadius(AppTheme.RADIUS_SM)
                .margin({ bottom: 4 })
                .onClick(() => {
                  this.onSelect(item.key);
                })
              }, (item: NavItem) => item.key)
            }
            .width('100%')
            .margin({ bottom: 10 })
          }, (groupKey: string) => groupKey)
        }
        .width('100%')
      }
      .layoutWeight(1)
      .scrollBar(BarState.Auto)

      Divider()
        .color(AppTheme.BORDER)
        .margin({ top: 12, bottom: 12 })

      Row() {
        AppIcon({
          commands: IconPaths.SLIDERS,
          color: this.activeKey === 'settings' ? AppTheme.PRIMARY : AppTheme.TEXT_TERTIARY,
          filled: false,
          iconSize: 24
        })
        Text(this.tr('nav.settings'))
          .fontSize(15)
          .fontColor(this.activeKey === 'settings' ? AppTheme.PRIMARY_DARK : AppTheme.TEXT_SECONDARY)
          .margin({ left: 12 })
      }
      .width('100%')
      .height(44)
      .padding({ left: 12, right: 12 })
      .backgroundColor(this.activeKey === 'settings' ? AppTheme.PRIMARY_SOFT : Color.Transparent)
      .borderRadius(AppTheme.RADIUS_SM)
      .onClick(() => {
        this.onSelect('settings');
      })

    }
    .width('100%')
    .height('100%')
    .padding({ left: 14, right: 14, top: 16, bottom: 20 })
    .backgroundColor(AppTheme.SURFACE)
    .alignItems(HorizontalAlign.Start)
  }
}
