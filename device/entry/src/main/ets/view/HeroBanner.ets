import AppTheme from '../common/AppTheme';
import IconPaths from '../common/IconPaths';
import { tFor, tfFor } from '../common/I18n';
import { AppIcon } from './AppIcon';

/** 横幅：欢迎语 + 三个特性点 + 右侧山影装饰。 */
@Component
export struct HeroBanner {
  /**
   * 当前语言。ArkUI 只重建读到状态变量的节点，所以本组件所有文案都走 this.tr()，
   * 由它读一次 this.lang，等于把用到的节点登记到语言变化上。
   */
  @StorageLink('lang') lang: string = 'zh';
  /** 当前竞赛名，为空时退回通用欢迎语。 */
  @Prop competitionName: string = '';

  /** 取文案：读一次 lang，让调用它的节点订阅语言变化。 */
  private tr(key: string): string {
    return tFor(this.lang, key);
  }

  /** 带占位符取文案。 */
  private trf(key: string, args: string[]): string {
    return tfFor(this.lang, key, args);
  }

  @Builder
  Feature(textKey: string) {
    Row() {
      AppIcon({
        commands: IconPaths.SPARK,
        color: AppTheme.PRIMARY,
        filled: true,
        iconSize: 16
      })
      Text(this.tr(textKey))
        .fontSize(14)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .margin({ left: 8 })
    }
    .alignItems(VerticalAlign.Center)
    .margin({ right: 28 })
  }

  build() {
    Row() {
      Column() {
        Text(this.trf('hero.welcome', [this.competitionName.length > 0 ? this.competitionName : this.tr('hero.welcomeFallback')]))
          .fontSize(28)
          .fontWeight(FontWeight.Bold)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })

        Row() {
          this.Feature('hero.flow')
          this.Feature('hero.insight')
          this.Feature('hero.impact')
        }
        .alignItems(VerticalAlign.Center)
        .margin({ top: 22 })
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)

      Stack({ alignContent: Alignment.BottomEnd }) {
        Path()
          .width(280)
          .height(110)
          .commands(IconPaths.RIDGE_BACK)
          .fill('#3312805C')
        Path()
          .width(280)
          .height(110)
          .commands(IconPaths.RIDGE_FRONT)
          .fill('#4D12805C')
        Column() {
          Text('Human in the loop.')
            .fontSize(13)
            .fontColor(AppTheme.PRIMARY_DARK)
          Text('A brighter tomorrow.')
            .fontSize(13)
            .fontColor(AppTheme.PRIMARY_DARK)
            .margin({ top: 4 })
        }
        .alignItems(HorizontalAlign.End)
        .margin({ right: 12, bottom: 12 })
      }
      .width(280)
      .height(110)
    }
    .width('100%')
    .padding({ left: 32, right: 32, top: 30, bottom: 30 })
    .borderRadius(AppTheme.RADIUS_LG)
    .linearGradient({
      angle: 135,
      colors: [[AppTheme.PRIMARY_SOFT_ALT, 0.0], [AppTheme.PRIMARY_SOFT, 1.0]]
    })
    .alignItems(VerticalAlign.Center)
  }
}
