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
  @State compactHeader: boolean = false;
  @State tightHeader: boolean = false;

  /** 取文案：读一次 lang，让调用它的节点订阅语言变化。 */
  private tr(key: string): string {
    return tFor(this.lang, key);
  }

  /** 当前项目名，显示在右上角；点它回到项目选择页。 */
  @Prop projectName: string = '';
  @Prop blockerCount: number = 0;
  /** 点击顶栏头像，由页面负责弹出账户菜单。 */
  onAvatarClick: () => void = () => {
  };
  /** 通知入口跳到工作流的状态与阻塞项。 */
  onNotificationsClick: () => void = () => {
  };
  /** 点击项目名，回到项目选择页。 */
  onSwitchProject: () => void = () => {
  };

  build() {
    Row() {
      Row() {
        // 品牌标记（无文字版 logo）；旁边的文字走 i18n，所以这里不放带中文标语的那张。
        Image($r('app.media.logo_mark'))
          .width(this.tightHeader ? 22 * AppTheme.UI_SCALE : (this.compactHeader ? 24 * AppTheme.UI_SCALE : 30 * AppTheme.UI_SCALE))
          .height(this.tightHeader ? 22 * AppTheme.UI_SCALE : (this.compactHeader ? 24 * AppTheme.UI_SCALE : 30 * AppTheme.UI_SCALE))
          .objectFit(ImageFit.Contain)
        Text('You Just Lead')
          .fontSize(this.tightHeader ? 14 * AppTheme.UI_SCALE : (this.compactHeader ? 16 * AppTheme.UI_SCALE : 19 * AppTheme.UI_SCALE))
          .fontWeight(FontWeight.Bold)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .margin({ left: this.tightHeader ? 6 * AppTheme.UI_SCALE : (this.compactHeader ? 8 * AppTheme.UI_SCALE : 12 * AppTheme.UI_SCALE) })
        if (!this.compactHeader) {
          Divider()
            .vertical(true)
            .height(20 * AppTheme.UI_SCALE)
            .color(AppTheme.BORDER)
            .margin({ left: 16 * AppTheme.UI_SCALE, right: 16 * AppTheme.UI_SCALE })
          Text(this.tr('topbar.tagline'))
            .fontSize(14 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.TEXT_SECONDARY)
        }
      }
      .alignItems(VerticalAlign.Center)

      Blank()

      Row() {
        // 当前项目是侧栏那些模块的上一层容器，所以它放在顶栏，而不是侧栏里的一项。
        Row() {
          AppIcon({ commands: IconPaths.FOLDER, color: AppTheme.PRIMARY_DARK, filled: false, iconSize: 16 * AppTheme.UI_SCALE })
          Text(this.projectName.length > 0 ? this.projectName : this.tr('topbar.noProject'))
            .fontSize(14 * AppTheme.UI_SCALE)
            .fontWeight(FontWeight.Medium)
            .fontColor(AppTheme.TEXT_PRIMARY)
            .margin({ left: 8 * AppTheme.UI_SCALE })
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          AppIcon({ commands: IconPaths.CHEVRON_SMALL, color: AppTheme.TEXT_TERTIARY, filled: false, iconSize: 14 * AppTheme.UI_SCALE })
            .margin({ left: 6 * AppTheme.UI_SCALE })
        }
        .constraintSize({
          maxWidth: (this.tightHeader ? 108 : (this.compactHeader ? 148 : 228)) * AppTheme.UI_SCALE
        })
        .height(38 * AppTheme.UI_SCALE)
        .padding({ left: this.tightHeader ? 7 * AppTheme.UI_SCALE : (this.compactHeader ? 10 * AppTheme.UI_SCALE : 14 * AppTheme.UI_SCALE), right: this.tightHeader ? 7 * AppTheme.UI_SCALE : (this.compactHeader ? 10 * AppTheme.UI_SCALE : 14 * AppTheme.UI_SCALE) })
        .backgroundColor(AppTheme.PRIMARY_SOFT)
        .borderRadius(AppTheme.RADIUS_SM)
        .alignItems(VerticalAlign.Center)
        .onClick(() => {
          this.onSwitchProject();
        })

        if (!this.tightHeader) {
          Stack({ alignContent: Alignment.TopEnd }) {
            AppIcon({
              commands: IconPaths.BELL,
              color: AppTheme.TEXT_SECONDARY,
              filled: false,
              iconSize: this.compactHeader ? 20 : 24
            })
            if (this.blockerCount > 0) {
              Text(this.blockerCount > 9 ? '9+' : `${this.blockerCount}`)
                .fontSize(8 * AppTheme.UI_SCALE)
                .fontColor(Color.White)
                .backgroundColor(AppTheme.DANGER)
                .borderRadius(7 * AppTheme.UI_SCALE)
                .padding({ left: 3 * AppTheme.UI_SCALE, right: 3 * AppTheme.UI_SCALE, top: 1 * AppTheme.UI_SCALE, bottom: 1 * AppTheme.UI_SCALE })
            }
          }
          .width(30 * AppTheme.UI_SCALE)
          .height(30 * AppTheme.UI_SCALE)
          .margin({ left: this.compactHeader ? 6 * AppTheme.UI_SCALE : 16 * AppTheme.UI_SCALE })
          .onClick(() => {
            this.onNotificationsClick();
          })
        }

        // 账户入口：软绿圆底上放品牌标记，和左边整块品牌区区分开。
        Stack({ alignContent: Alignment.Center }) {
          Image($r('app.media.logo_mark'))
            .width(22 * AppTheme.UI_SCALE)
            .height(22 * AppTheme.UI_SCALE)
            .objectFit(ImageFit.Contain)
        }
        .width(34 * AppTheme.UI_SCALE)
        .height(34 * AppTheme.UI_SCALE)
        .backgroundColor(AppTheme.PRIMARY_SOFT)
        .borderRadius(17 * AppTheme.UI_SCALE)
        .margin({ left: this.tightHeader ? 6 * AppTheme.UI_SCALE : (this.compactHeader ? 8 * AppTheme.UI_SCALE : 12 * AppTheme.UI_SCALE) })
        .onClick(() => {
          this.onAvatarClick();
        })
      }
      .alignItems(VerticalAlign.Center)
    }
    .width('100%')
    .height(AppTheme.TOPBAR_HEIGHT)
    .padding({ left: this.tightHeader ? 10 * AppTheme.UI_SCALE : (this.compactHeader ? 12 * AppTheme.UI_SCALE : 24 * AppTheme.UI_SCALE), right: this.tightHeader ? 10 * AppTheme.UI_SCALE : (this.compactHeader ? 12 * AppTheme.UI_SCALE : 24 * AppTheme.UI_SCALE) })
    .backgroundColor(AppTheme.SURFACE)
    .alignItems(VerticalAlign.Center)
    .onAreaChange((_oldArea: Area, newArea: Area) => {
      const width = Number(newArea.width);
      const compact = width < 680;
      const tight = width < 440;
      if (this.compactHeader !== compact) {
        this.compactHeader = compact;
      }
      if (this.tightHeader !== tight) {
        this.tightHeader = tight;
      }
    })
  }
}
