import AppTheme from '../common/AppTheme';
import { fetchAccount } from '../common/BackendClient';
import IconPaths from '../common/IconPaths';
import { LANG_EN, LANG_ZH, langName, setLang, tFor, tfFor } from '../common/I18n';
import { AppIcon } from './AppIcon';

/**
 * 账户菜单：点击顶栏头像弹出。
 *
 * 阻塞项数量与后端状态由页面传入；账户名和余额在菜单展开时从服务端刷新。
 * 语言切换直接调 I18n 的 setLang，界面靠 AppStorage 广播整体重绘。
 */
@Component
export struct UserMenu {
  /**
   * 当前语言。ArkUI 只重建读到状态变量的节点，所以本组件所有文案都走 this.tr()，
   * 由它读一次 this.lang，等于把用到的节点登记到语言变化上。
   */
  @StorageLink('lang') lang: string = 'zh';
  /** 待处理阻塞项数量，为 0 时显示「全部已处理」。 */
  @Prop blockerCount: number = 0;
  /** 后端是否连通，决定「后端连接」显示正常还是离线。 */
  @Prop backendOnline: boolean = true;
  @State accountUsername: string = '';
  @State accountCredits: number = 0;
  /** 关闭菜单。 */
  onClose: () => void = () => {
  };
  /** 重新取一次数据。 */
  onRefresh: () => void = () => {
  };
  /** 跳转到某个侧栏页面。 */
  onNavigate: (key: string) => void = () => {
  };
  /** 回到项目选择页。 */
  onSwitchProject: () => void = () => {
  };
  onLogout: () => void = () => {
  };
  /** 语言选项是否展开。 */
  @State langExpanded: boolean = false;

  aboutToAppear(): void {
    this.refreshAccount();
  }

  private async refreshAccount(): Promise<void> {
    try {
      const account = await fetchAccount();
      this.accountUsername = account.username;
      this.accountCredits = account.credits;
    } catch (error) {
      // The menu remains usable if the account balance cannot be refreshed.
    }
  }

  /** 取文案：读一次 lang，让调用它的节点订阅语言变化。 */
  private tr(key: string): string {
    return tFor(this.lang, key);
  }

  /** 带占位符取文案。 */
  private trf(key: string, args: string[]): string {
    return tfFor(this.lang, key, args);
  }

  /** 当前语言的中文/英文写法。 */
  private currentLangName(): string {
    return langName(this.lang);
  }

  /** 一行入口：图标 + 文案 + 右侧说明 + 尖角，整行可点。 */
  @Builder
  EntryRow(commands: string, labelKey: string, valueKey: string, valueColor: ResourceColor, onTap: () => void) {
    Row() {
      AppIcon({ commands: commands, color: AppTheme.TEXT_SECONDARY, filled: false, iconSize: 18 * AppTheme.UI_SCALE })
      Text(this.tr(labelKey))
        .fontSize(13 * AppTheme.UI_SCALE)
        .fontColor(AppTheme.TEXT_PRIMARY)
        .margin({ left: 10 * AppTheme.UI_SCALE })
        .layoutWeight(1)
      if (valueKey.length > 0) {
        Text(this.tr(valueKey))
          .fontSize(12 * AppTheme.UI_SCALE)
          .fontColor(valueColor)
          .margin({ right: 6 * AppTheme.UI_SCALE })
      }
      AppIcon({ commands: IconPaths.CHEVRON_SMALL, color: AppTheme.TEXT_TERTIARY, filled: false, iconSize: 14 * AppTheme.UI_SCALE })
    }
    .width('100%')
    .height(38 * AppTheme.UI_SCALE)
    .onClick(() => {
      onTap();
    })
  }

  /** 「语言」行：右侧显示当前语言名，点击展开两个选项。 */
  @Builder
  LangRow() {
    Row() {
      AppIcon({ commands: IconPaths.GLOBE, color: AppTheme.TEXT_SECONDARY, filled: false, iconSize: 18 * AppTheme.UI_SCALE })
      Text(this.tr('menu.language'))
        .fontSize(13 * AppTheme.UI_SCALE)
        .fontColor(AppTheme.TEXT_PRIMARY)
        .margin({ left: 10 * AppTheme.UI_SCALE })
        .layoutWeight(1)
      Text(this.currentLangName())
        .fontSize(12 * AppTheme.UI_SCALE)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .margin({ right: 6 * AppTheme.UI_SCALE })
      AppIcon({ commands: IconPaths.CHEVRON_SMALL, color: AppTheme.TEXT_TERTIARY, filled: false, iconSize: 14 * AppTheme.UI_SCALE })
    }
    .width('100%')
    .height(38 * AppTheme.UI_SCALE)
    .onClick(() => {
      this.langExpanded = !this.langExpanded;
    })
  }

  /** 语言下拉里的一项，当前语言带对勾。语言名用该语言自己的写法，不随界面语言变。 */
  @Builder
  LangOption(value: string) {
    Row() {
      Text(langName(value))
        .fontSize(13 * AppTheme.UI_SCALE)
        .fontColor(AppTheme.TEXT_PRIMARY)
        .layoutWeight(1)
      if (this.lang === value) {
        AppIcon({ commands: IconPaths.CHECK, color: AppTheme.PRIMARY, filled: false, iconSize: 14 * AppTheme.UI_SCALE })
      }
    }
    .width('100%')
    .height(34 * AppTheme.UI_SCALE)
    .padding({ left: 40 * AppTheme.UI_SCALE })
    .onClick(() => {
      setLang(value);
      this.onClose();
    })
  }

  build() {
    Column() {
      Row() {
        Stack({ alignContent: Alignment.Center }) {
          Image($r('app.media.logo_mark'))
            .width(26 * AppTheme.UI_SCALE)
            .height(26 * AppTheme.UI_SCALE)
            .objectFit(ImageFit.Contain)
        }
        .width(40 * AppTheme.UI_SCALE)
        .height(40 * AppTheme.UI_SCALE)
        .backgroundColor(AppTheme.PRIMARY_SOFT)
        .borderRadius(12 * AppTheme.UI_SCALE)
        Column() {
          Text(this.accountUsername)
            .fontSize(14 * AppTheme.UI_SCALE)
            .fontWeight(FontWeight.Medium)
            .fontColor(AppTheme.TEXT_PRIMARY)
          Text(`${this.tr('auth.balance')}：${this.accountCredits.toFixed(2)}`)
            .fontSize(12 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .margin({ top: 4 * AppTheme.UI_SCALE })
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)
        .margin({ left: 12 * AppTheme.UI_SCALE })

        Text(this.tr('menu.badge'))
          .fontSize(11 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.PRIMARY_DARK)
          .backgroundColor(AppTheme.PRIMARY_SOFT)
          .borderRadius(6 * AppTheme.UI_SCALE)
          .padding({ left: 8 * AppTheme.UI_SCALE, right: 8 * AppTheme.UI_SCALE, top: 3 * AppTheme.UI_SCALE, bottom: 3 * AppTheme.UI_SCALE })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Row() {
        Text(this.tr('menu.refresh'))
          .fontSize(13 * AppTheme.UI_SCALE)
          .fontWeight(FontWeight.Medium)
          .fontColor(AppTheme.PRIMARY_DARK)
      }
      .width('100%')
      .height(36 * AppTheme.UI_SCALE)
      .justifyContent(FlexAlign.Center)
      .backgroundColor(AppTheme.PRIMARY_SOFT)
      .borderRadius(AppTheme.RADIUS_SM)
      .margin({ top: 16 * AppTheme.UI_SCALE })
      .onClick(() => {
        this.onRefresh();
        this.onClose();
      })

      Column() {
        Row() {
          Text(this.tr('menu.blockedTitle'))
            .fontSize(13 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.TEXT_SECONDARY)
          Blank()
          Text(this.blockerCount > 0
            ? this.trf('menu.blockedUnit', [`${this.blockerCount}`])
            : this.tr('menu.blockedNone'))
            .fontSize(13 * AppTheme.UI_SCALE)
            .fontWeight(FontWeight.Medium)
            .fontColor(this.blockerCount > 0 ? AppTheme.DANGER : AppTheme.PRIMARY_DARK)
        }
        .width('100%')

        Text(this.tr('menu.blockedHint'))
          .fontSize(11 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .margin({ top: 6 * AppTheme.UI_SCALE })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
      .padding(12 * AppTheme.UI_SCALE)
      .backgroundColor(AppTheme.PAGE_BG)
      .borderRadius(AppTheme.RADIUS_SM)
      .margin({ top: 12 * AppTheme.UI_SCALE })

      Column() {
        this.EntryRow(IconPaths.FOLDER, 'menu.switchProject', '', AppTheme.TEXT_SECONDARY, () => {
          this.onSwitchProject();
          this.onClose();
        })

        this.LangRow()

        if (this.langExpanded) {
          this.LangOption(LANG_ZH)
          this.LangOption(LANG_EN)
        }

        this.EntryRow(IconPaths.LINK, 'menu.backend',
          this.backendOnline ? 'menu.backendOk' : 'menu.backendDown',
          this.backendOnline ? AppTheme.PRIMARY_DARK : AppTheme.DANGER, () => {
            this.onNavigate('settings');
            this.onClose();
          })

        Row() {
          AppIcon({ commands: IconPaths.BELL, color: AppTheme.TEXT_SECONDARY, filled: false, iconSize: 18 * AppTheme.UI_SCALE })
          Text(this.tr('menu.messages'))
            .fontSize(13 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.TEXT_PRIMARY)
            .margin({ left: 10 * AppTheme.UI_SCALE })
            .layoutWeight(1)
          if (this.blockerCount > 0) {
            Text(`${this.blockerCount}`)
              .fontSize(11 * AppTheme.UI_SCALE)
              .fontColor(Color.White)
              .backgroundColor(AppTheme.DANGER)
              .borderRadius(9 * AppTheme.UI_SCALE)
              .padding({ left: 6 * AppTheme.UI_SCALE, right: 6 * AppTheme.UI_SCALE, top: 1 * AppTheme.UI_SCALE, bottom: 1 * AppTheme.UI_SCALE })
              .margin({ right: 6 * AppTheme.UI_SCALE })
          }
          AppIcon({ commands: IconPaths.CHEVRON_SMALL, color: AppTheme.TEXT_TERTIARY, filled: false, iconSize: 14 * AppTheme.UI_SCALE })
        }
        .width('100%')
        .height(38 * AppTheme.UI_SCALE)
        .onClick(() => {
          this.onNavigate('workflow');
          this.onClose();
        })

        this.EntryRow(IconPaths.SLIDERS, 'menu.settings', '', AppTheme.TEXT_SECONDARY, () => {
          this.onNavigate('settings');
          this.onClose();
        })
      }
      .width('100%')
      .margin({ top: 10 * AppTheme.UI_SCALE })

      Divider()
        .color(AppTheme.BORDER)
        .margin({ top: 8 * AppTheme.UI_SCALE, bottom: 4 * AppTheme.UI_SCALE })

      this.EntryRow(IconPaths.LOGOUT, 'auth.signOut', '', AppTheme.TEXT_SECONDARY, () => {
        this.onLogout();
      })
    }
    .alignItems(HorizontalAlign.Start)
    .width(300 * AppTheme.UI_SCALE)
    .padding(16 * AppTheme.UI_SCALE)
    .backgroundColor(AppTheme.SURFACE)
    .borderRadius(AppTheme.RADIUS_LG)
    .border({ width: 1, color: AppTheme.BORDER })
    .shadow({ radius: 24, color: '#22000000', offsetX: 0, offsetY: 8 })
  }
}
