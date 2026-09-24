import AppTheme from '../common/AppTheme';
import IconPaths from '../common/IconPaths';
import { tFor } from '../common/I18n';
import { AppIcon } from './AppIcon';

/** 顶栏：品牌区 + 当前项目 + 通知 + 头像。 */
@Component
export struct TopBar {
  /**
   * 当前语言。ArkUI 只重建读到状态变量的节点，所以本组件所有文案都走 this.tr()，
   * 由它读一次 this.lang，等于把用到的节点登记到语言变化上。
   */
  @StorageLink('lang') lang: string = 'zh';

  /** 取文案：读一次 lang，让调用它的节点订阅语言变化。 */
  private tr(key: string): string {
    return tFor(this.lang, key);
  }

  /** 当前项目名，显示在右上角；点它回到项目选择页。 */
  @Prop projectName: string = '';
  /** 点击顶栏头像，由页面负责弹出账户菜单。 */
  onAvatarClick: () => void = () => {
  };
  /** 点击项目名，回到项目选择页。 */
  onSwitchProject: () => void = () => {
  };

  build() {
    Row() {
      Row() {
        // 品牌标记（无文字版 logo）；旁边的文字走 i18n，所以这里不放带中文标语的那张。
        Image($r('app.media.logo_mark'))
          .width(30)
          .height(30)
          .objectFit(ImageFit.Contain)
        Text('You Just Lead')
          .fontSize(19)
          .fontWeight(FontWeight.Bold)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .margin({ left: 12 })
        Divider()
          .vertical(true)
          .height(20)
          .color(AppTheme.BORDER)
          .margin({ left: 16, right: 16 })
        Text(this.tr('topbar.tagline'))
          .fontSize(14)
          .fontColor(AppTheme.TEXT_SECONDARY)
      }
      .alignItems(VerticalAlign.Center)

      Blank()

      Row() {
        // 当前项目是侧栏那些模块的上一层容器，所以它放在顶栏，而不是侧栏里的一项。
        Row() {
          AppIcon({ commands: IconPaths.FOLDER, color: AppTheme.PRIMARY_DARK, filled: false, iconSize: 16 })
          Text(this.projectName.length > 0 ? this.projectName : this.tr('topbar.noProject'))
            .fontSize(14)
            .fontWeight(FontWeight.Medium)
            .fontColor(AppTheme.TEXT_PRIMARY)
            .margin({ left: 8 })
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          AppIcon({ commands: IconPaths.CHEVRON_SMALL, color: AppTheme.TEXT_TERTIARY, filled: false, iconSize: 14 })
            .margin({ left: 6 })
        }
        .constraintSize({ maxWidth: 280 })
        .height(38)
        .padding({ left: 14, right: 14 })
        .backgroundColor(AppTheme.PRIMARY_SOFT)
        .borderRadius(AppTheme.RADIUS_SM)
        .alignItems(VerticalAlign.Center)
        .onClick(() => {
          this.onSwitchProject();
        })

        Stack({ alignContent: Alignment.TopEnd }) {
          AppIcon({
            commands: IconPaths.BELL,
            color: AppTheme.TEXT_SECONDARY,
            filled: false,
            iconSize: 24
          })
          Row()
            .width(7)
            .height(7)
            .borderRadius(4)
            .backgroundColor(AppTheme.DANGER)
        }
        .margin({ left: 16 })

        // 账户入口：软绿圆底上放品牌标记，和左边整块品牌区区分开。
        Stack({ alignContent: Alignment.Center }) {
          Image($r('app.media.logo_mark'))
            .width(22)
            .height(22)
            .objectFit(ImageFit.Contain)
        }
        .width(34)
        .height(34)
        .backgroundColor(AppTheme.PRIMARY_SOFT)
        .borderRadius(17)
        .margin({ left: 12 })
        .onClick(() => {
          this.onAvatarClick();
        })
      }
      .alignItems(VerticalAlign.Center)
    }
    .width('100%')
    .height(AppTheme.TOPBAR_HEIGHT)
    .padding({ left: 24, right: 24 })
    .backgroundColor(AppTheme.SURFACE)
    .alignItems(VerticalAlign.Center)
  }
}
