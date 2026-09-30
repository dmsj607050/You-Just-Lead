import AppTheme from '../common/AppTheme';
import { tFor } from '../common/I18n';

/** 云账号入口：用户自助注册/登录，不收集或保存模型服务密钥。 */
@Component
export struct AccountGate {
  @StorageLink('lang') lang: string = 'zh';
  @Prop busy: boolean = false;
  @Prop errorMessage: string = '';
  onSubmit: (username: string, password: string, register: boolean) => void = () => {
  };
  @State registering: boolean = false;
  @State username: string = '';
  @State password: string = '';

  private tr(key: string): string {
    return tFor(this.lang, key);
  }

  build() {
    Column() {
      Blank()
      Column() {
        Text('You Just Lead')
          .fontSize(26)
          .fontWeight(FontWeight.Bold)
          .fontColor(AppTheme.TEXT_PRIMARY)
        Text(this.tr('auth.subtitle'))
          .fontSize(14)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .margin({ top: 8 })

        Column() {
          Text(this.tr('auth.username'))
            .fontSize(13)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .margin({ bottom: 6 })
          TextInput({ text: this.username, placeholder: this.tr('auth.usernameHint') })
            .height(44)
            .fontSize(15)
            .backgroundColor(AppTheme.PAGE_BG)
            .borderRadius(AppTheme.RADIUS_SM)
            .onChange((value: string) => {
              this.username = value;
            })

          Text(this.tr('auth.password'))
            .fontSize(13)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .margin({ top: 14, bottom: 6 })
          TextInput({ text: this.password, placeholder: this.tr('auth.passwordHint') })
            .type(InputType.Password)
            .height(44)
            .fontSize(15)
            .backgroundColor(AppTheme.PAGE_BG)
            .borderRadius(AppTheme.RADIUS_SM)
            .onChange((value: string) => {
              this.password = value;
            })
        }
        .alignItems(HorizontalAlign.Start)
        .width('100%')
        .margin({ top: 24 })

        if (this.errorMessage.length > 0) {
          Text(this.errorMessage)
            .fontSize(12)
            .fontColor(AppTheme.DANGER)
            .width('100%')
            .margin({ top: 12 })
        }

        Button(this.busy
          ? this.tr('auth.working')
          : (this.registering ? this.tr('auth.register') : this.tr('auth.login')))
          .width('100%')
          .height(46)
          .fontSize(15)
          .fontColor(Color.White)
          .backgroundColor(AppTheme.PRIMARY)
          .margin({ top: 20 })
          .enabled(!this.busy && this.username.trim().length > 0 && this.password.length > 0)
          .onClick(() => {
            this.onSubmit(this.username.trim(), this.password, this.registering);
          })

        Text(this.tr('auth.creditGrant'))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .textAlign(TextAlign.Center)
          .width('100%')
          .margin({ top: 16 })
        Text(this.tr('auth.noKey'))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .textAlign(TextAlign.Center)
          .width('100%')
          .margin({ top: 8 })

        Row() {
          Text(this.registering ? this.tr('auth.haveAccount') : this.tr('auth.needAccount'))
            .fontSize(13)
            .fontColor(AppTheme.TEXT_SECONDARY)
          Text(this.registering ? this.tr('auth.goLogin') : this.tr('auth.goRegister'))
            .fontSize(13)
            .fontColor(AppTheme.PRIMARY_DARK)
            .fontWeight(FontWeight.Medium)
            .margin({ left: 6 })
            .onClick(() => {
              this.registering = !this.registering;
            })
        }
        .justifyContent(FlexAlign.Center)
        .width('100%')
        .margin({ top: 20 })
      }
      .alignItems(HorizontalAlign.Start)
      .width('100%')
      .constraintSize({ maxWidth: 440 })
      .padding(28)
      .backgroundColor(AppTheme.SURFACE)
      .borderRadius(AppTheme.RADIUS_LG)
      .border({ width: 1, color: AppTheme.BORDER })

      Blank()
    }
    .width('100%')
    .height('100%')
    .alignItems(HorizontalAlign.Center)
    .padding({ left: 24, right: 24 })
    .backgroundColor(AppTheme.PAGE_BG)
  }
}
