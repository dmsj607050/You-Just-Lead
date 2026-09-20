import AppTheme from '../common/AppTheme';
import IconPaths from '../common/IconPaths';
import { tFor, tfFor } from '../common/I18n';
import { StepSpec } from '../common/ViewTypes';
import { AppIcon } from './AppIcon';
import { WorkflowStepper } from './WorkflowStepper';

/** 项目卡片：竞赛信息 + 规则就绪度 + 内嵌工作流步骤条。 */
@Component
export struct ProjectCard {
  /**
   * 当前语言。ArkUI 只重建读到状态变量的节点，所以本组件所有文案都走 this.tr()，
   * 由它读一次 this.lang，等于把用到的节点登记到语言变化上。
   */
  @StorageLink('lang') lang: string = 'zh';
  @Prop competitionName: string = '';
  @Prop taskType: string = '';
  @Prop runner: string = '';
  @Prop metric: string = '';
  @Prop ruleTotal: number = 0;
  @Prop ruleMissing: number = 0;
  @Prop blockerCount: number = 0;
  /** 已格式化的最后更新时间，为空则不显示。 */
  @Prop lastUpdated: string = '';
  @Prop steps: StepSpec[] = [];

  /** 取文案：读一次 lang，让调用它的节点订阅语言变化。 */
  private tr(key: string): string {
    return tFor(this.lang, key);
  }

  /** 带占位符取文案。 */
  private trf(key: string, args: string[]): string {
    return tfFor(this.lang, key, args);
  }

  /**
   * 竞赛信息行：只拼真正填了值的部分。
   * 新建项目还没填规则时三个字段都是空的，不留「 · 主指标  · 适配器 」这种空占位。
   */
  private metaText(): string {
    const parts: string[] = [];
    if (this.taskType.length > 0) {
      parts.push(this.taskType);
    }
    if (this.metric.length > 0) {
      parts.push(this.trf('card.mainMetric', [this.metric]));
    }
    if (this.runner.length > 0) {
      parts.push(this.trf('card.adapter', [this.runner]));
    }
    return parts.join(' · ');
  }

  build() {
    Column() {
      Row() {
        Row() {
          Stack({ alignContent: Alignment.Center }) {
            AppIcon({
              commands: IconPaths.FOLDER,
              color: AppTheme.PRIMARY,
              filled: true,
              iconSize: 24
            })
          }
          .width(44)
          .height(44)
          .backgroundColor(AppTheme.PRIMARY_SOFT)
          .borderRadius(AppTheme.RADIUS_SM)

          Column() {
            Text(this.competitionName.length > 0 ? this.competitionName : this.tr('card.noCompetition'))
              .fontSize(20)
              .fontWeight(FontWeight.Bold)
              .fontColor(AppTheme.TEXT_PRIMARY)
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
            if (this.metaText().length > 0) {
              Text(this.metaText())
                .fontSize(13)
                .fontColor(AppTheme.TEXT_SECONDARY)
                .margin({ top: 6 })
                .maxLines(1)
                .textOverflow({ overflow: TextOverflow.Ellipsis })
            }
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1)
          .margin({ left: 14 })
        }
        .alignItems(VerticalAlign.Center)
        .layoutWeight(1)

        Column() {
          Row() {
            Row().width(7).height(7).borderRadius(4).backgroundColor(AppTheme.PRIMARY)
            Text(this.tr('card.inProgress'))
              .fontSize(13)
              .fontColor(AppTheme.PRIMARY_DARK)
              .margin({ left: 6 })
          }
          .alignItems(VerticalAlign.Center)

          if (this.lastUpdated.length > 0) {
            Text(this.trf('card.lastUpdated', [this.lastUpdated]))
              .fontSize(12)
              .fontColor(AppTheme.TEXT_TERTIARY)
              .margin({ top: 8 })
          }

          if (this.ruleTotal > 0) {
            Text(this.trf('card.ruleFields', [`${this.ruleTotal - this.ruleMissing}`, `${this.ruleTotal}`]))
              .fontSize(12)
              .fontColor(AppTheme.TEXT_TERTIARY)
              .margin({ top: 8 })
          }
          Text(this.trf('card.blockers', [`${this.blockerCount}`]))
            .fontSize(12)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .margin({ top: 4 })
        }
        .alignItems(HorizontalAlign.End)
      }
      .width('100%')
      .alignItems(VerticalAlign.Top)

      if (this.metaText().length > 0) {
        Row() {
          if (this.taskType.length > 0) {
            Text(this.taskType)
              .fontSize(12)
              .fontColor(AppTheme.TEXT_SECONDARY)
              .backgroundColor(AppTheme.PAGE_BG)
              .borderRadius(6)
              .padding({ left: 10, right: 10, top: 4, bottom: 4 })
          }
          if (this.runner.length > 0) {
            Text(this.runner)
              .fontSize(12)
              .fontColor(AppTheme.TEXT_SECONDARY)
              .backgroundColor(AppTheme.PAGE_BG)
              .borderRadius(6)
              .padding({ left: 10, right: 10, top: 4, bottom: 4 })
              .margin({ left: 8 })
          }
          if (this.metric.length > 0) {
            Text(this.trf('card.metric', [this.metric]))
              .fontSize(12)
              .fontColor(AppTheme.TEXT_SECONDARY)
              .backgroundColor(AppTheme.PAGE_BG)
              .borderRadius(6)
              .padding({ left: 10, right: 10, top: 4, bottom: 4 })
              .margin({ left: 8 })
          }
        }
        .width('100%')
        .margin({ top: 16 })
      }

      Column() {
        Row() {
          Text(this.tr('card.workflow'))
            .fontSize(14)
            .fontWeight(FontWeight.Medium)
            .fontColor(AppTheme.TEXT_PRIMARY)
            .layoutWeight(1)
          Text(this.tr('card.viewDetails'))
            .fontSize(13)
            .fontColor(AppTheme.PRIMARY)
        }
        .width('100%')
        .margin({ bottom: 20 })

        WorkflowStepper({ steps: this.steps })
      }
      .width('100%')
      .padding({ left: 20, right: 20, top: 18, bottom: 12 })
      .margin({ top: 18 })
      .backgroundColor(AppTheme.PAGE_BG)
      .borderRadius(AppTheme.RADIUS)
    }
    .width('100%')
    .padding(24)
    .backgroundColor(AppTheme.SURFACE)
    .borderRadius(AppTheme.RADIUS_LG)
    .border({ width: 1, color: AppTheme.BORDER })
  }
}
