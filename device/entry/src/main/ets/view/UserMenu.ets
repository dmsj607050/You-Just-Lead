import { common } from '@kit.AbilityKit';
import AppTheme from '../common/AppTheme';
import IconPaths from '../common/IconPaths';
import { LANG_EN, LANG_ZH, langName, setLang, tFor, tfFor } from '../common/I18n';
import { AppIcon } from './AppIcon';

/**
 * 账户菜单：点击顶栏头像弹出。
 *
 * 只做展示与回传，不自己取数：阻塞项数量、后端状态都由页面传入，
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
  /** 语言选项是否展开。 */
  @State langExpanded: boolean = false;

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
  EntryRow(commands: string, labelKey: string, valueKey: string, valueColor: string, onTap: () => void) {
    Row() {
      AppIcon({ commands: commands, color: AppTheme.TEXT_SECONDARY, filled: false, iconSize: 18 })
      Text(this.tr(labelKey))
        .fontSize(13)
        .fontColor(AppTheme.TEXT_PRIMARY)
        .margin({ left: 10 })
        .layoutWeight(1)
      if (valueKey.length > 0) {
        Text(this.tr(valueKey))
          .fontSize(12)
          .fontColor(valueColor)
          .margin({ right: 6 })
      }
      AppIcon({ commands: IconPaths.CHEVRON_SMALL, color: AppTheme.TEXT_TERTIARY, filled: false, iconSize: 14 })
    }
    .width('100%')
    .height(38)
    .onClick(() => {
      onTap();
    })
  }

  /** 「语言」行：右侧显示当前语言名，点击展开两个选项。 */
  @Builder
  LangRow() {
    Row() {
      AppIcon({ commands: IconPaths.GLOBE, color: AppTheme.TEXT_SECONDARY, filled: false, iconSize: 18 })
      Text(this.tr('menu.language'))
        .fontSize(13)
        .fontColor(AppTheme.TEXT_PRIMARY)
        .margin({ left: 10 })
        .layoutWeight(1)
      Text(this.currentLangName())
        .fontSize(12)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .margin({ right: 6 })
      AppIcon({ commands: IconPaths.CHEVRON_SMALL, color: AppTheme.TEXT_TERTIARY, filled: false, iconSize: 14 })
    }
    .width('100%')
    .height(38)
    .onClick(() => {
      this.langExpanded = !this.langExpanded;
    })
  }

  /** 语言下拉里的一项，当前语言带对勾。语言名用该语言自己的写法，不随界面语言变。 */
  @Builder
  LangOption(value: string) {
    Row() {
      Text(langName(value))
        .fontSize(13)
        .fontColor(AppTheme.TEXT_PRIMARY)
        .layoutWeight(1)
      if (this.lang === value) {
        AppIcon({ commands: IconPaths.CHECK, color: AppTheme.PRIMARY, filled: false, iconSize: 14 })
      }
    }
    .width('100%')
    .height(34)
    .padding({ left: 40 })
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
            .width(26)
            .height(26)
            .objectFit(ImageFit.Contain)
        }
        .width(40)
        .height(40)
        .backgroundColor(AppTheme.PRIMARY_SOFT)
        .borderRadius(12)
        Column() {
          Text(this.tr('menu.workspace'))
            .fontSize(14)
            .fontWeight(FontWeight.Medium)
            .fontColor(AppTheme.TEXT_PRIMARY)
          Text('You Just Lead')
            .fontSize(12)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .margin({ top: 4 })
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)
        .margin({ left: 12 })

        Text(this.tr('menu.badge'))
          .fontSize(11)
          .fontColor(AppTheme.PRIMARY_DARK)
          .backgroundColor(AppTheme.PRIMARY_SOFT)
          .borderRadius(6)
          .padding({ left: 8, right: 8, top: 3, bottom: 3 })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Row() {
        Text(this.tr('menu.refresh'))
          .fontSize(13)
          .fontWeight(FontWeight.Medium)
          .fontColor(AppTheme.PRIMARY_DARK)
      }
      .width('100%')
      .height(36)
      .justifyContent(FlexAlign.Center)
      .backgroundColor(AppTheme.PRIMARY_SOFT)
      .borderRadius(AppTheme.RADIUS_SM)
      .margin({ top: 16 })
      .onClick(() => {
        this.onRefresh();
        this.onClose();
      })

      Column() {
        Row() {
          Text(this.tr('menu.blockedTitle'))
            .fontSize(13)
            .fontColor(AppTheme.TEXT_SECONDARY)
          Blank()
          Text(this.blockerCount > 0
            ? this.trf('menu.blockedUnit', [`${this.blockerCount}`])
            : this.tr('menu.blockedNone'))
            .fontSize(13)
            .fontWeight(FontWeight.Medium)
            .fontColor(this.blockerCount > 0 ? AppTheme.DANGER : AppTheme.PRIMARY_DARK)
        }
        .width('100%')

        Text(this.tr('menu.blockedHint'))
          .fontSize(11)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .margin({ top: 6 })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
      .padding(12)
      .backgroundColor(AppTheme.PAGE_BG)
      .borderRadius(AppTheme.RADIUS_SM)
      .margin({ top: 12 })

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
          AppIcon({ commands: IconPaths.BELL, color: AppTheme.TEXT_SECONDARY, filled: false, iconSize: 18 })
          Text(this.tr('menu.messages'))
            .fontSize(13)
            .fontColor(AppTheme.TEXT_PRIMARY)
            .margin({ left: 10 })
            .layoutWeight(1)
          if (this.blockerCount > 0) {
            Text(`${this.blockerCount}`)
              .fontSize(11)
              .fontColor(Color.White)
              .backgroundColor(AppTheme.DANGER)
              .borderRadius(9)
              .padding({ left: 6, right: 6, top: 1, bottom: 1 })
              .margin({ right: 6 })
          }
          AppIcon({ commands: IconPaths.CHEVRON_SMALL, color: AppTheme.TEXT_TERTIARY, filled: false, iconSize: 14 })
        }
        .width('100%')
        .height(38)
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
      .margin({ top: 10 })

      Divider()
        .color(AppTheme.BORDER)
        .margin({ top: 8, bottom: 4 })

      this.EntryRow(IconPaths.LOGOUT, 'menu.quit', '', AppTheme.TEXT_SECONDARY, () => {
        // getContext 已废弃，用 UIContext 取宿主 Ability 的上下文。
        const context = this.getUIContext().getHostContext() as common.UIAbilityContext;
        context.terminateSelf();
      })
    }
    .alignItems(HorizontalAlign.Start)
    .width(300)
    .padding(16)
    .backgroundColor(AppTheme.SURFACE)
    .borderRadius(AppTheme.RADIUS_LG)
    .border({ width: 1, color: AppTheme.BORDER })
    .shadow({ radius: 24, color: '#22000000', offsetX: 0, offsetY: 8 })
  }
}
