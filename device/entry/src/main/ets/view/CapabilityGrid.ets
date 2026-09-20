import AppTheme from '../common/AppTheme';
import IconPaths from '../common/IconPaths';
import { RunnerCapability } from '../common/BackendClient';
import { tFor } from '../common/I18n';
import { AppIcon } from './AppIcon';

/** 内置能力：训练适配器卡片网格，带搜索与网格/列表切换。 */
@Component
export struct CapabilityGrid {
  /**
   * 当前语言。ArkUI 只重建读到状态变量的节点，所以本组件所有文案都走 this.tr()，
   * 由它读一次 this.lang，等于把用到的节点登记到语言变化上。
   */
  @StorageLink('lang') lang: string = 'zh';
  @Prop runners: RunnerCapability[] = [];
  /** 搜索词保存在卡片内部，父组件不需要关心。 */
  @State keyword: string = '';
  @State gridView: boolean = true;

  /** 取文案：读一次 lang，让调用它的节点订阅语言变化。 */
  private tr(key: string): string {
    return tFor(this.lang, key);
  }

  /** 按搜索词过滤适配器，名称与类型都参与匹配。 */
  private visibleRunners(): RunnerCapability[] {
    const key: string = this.keyword.trim().toLowerCase();
    if (key.length === 0) {
      return this.runners;
    }
    return this.runners.filter((item: RunnerCapability) =>
      item.runner.toLowerCase().includes(key) || item.kind.toLowerCase().includes(key));
  }

  @Builder
  ViewToggleButton(commands: string, active: boolean, grid: boolean) {
    Stack({ alignContent: Alignment.Center }) {
      AppIcon({
        commands: commands,
        color: active ? '#FFFFFF' : AppTheme.TEXT_SECONDARY,
        filled: false,
        iconSize: 20
      })
    }
    .width(32)
    .height(32)
    .backgroundColor(active ? AppTheme.PRIMARY : Color.Transparent)
    .borderRadius(6)
    .onClick(() => {
      this.gridView = grid;
    })
  }

  @Builder
  RunnerCard(item: RunnerCapability) {
    Column() {
      Text(item.runner)
        .fontSize(15)
        .fontWeight(FontWeight.Medium)
        .fontColor(AppTheme.TEXT_PRIMARY)
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
      Text(item.kind)
        .fontSize(12)
        .fontColor(AppTheme.PRIMARY)
        .margin({ top: 6 })
      Text(item.data_contract)
        .fontSize(12)
        .fontColor(AppTheme.TEXT_TERTIARY)
        .maxLines(3)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
        .margin({ top: 10 })
    }
    .alignItems(HorizontalAlign.Start)
    .width(this.gridView ? '32%' : '100%')
    .height(this.gridView ? 156 : 92)
    .padding(16)
    .backgroundColor(AppTheme.SURFACE)
    .borderRadius(AppTheme.RADIUS)
    .border({ width: 1, color: AppTheme.BORDER })
    .margin({ bottom: 14 })
  }

  build() {
    Column() {
      Row() {
        Column() {
          Text(this.tr('cap.title'))
            .fontSize(17)
            .fontWeight(FontWeight.Bold)
            .fontColor(AppTheme.TEXT_PRIMARY)
          Text(this.tr('cap.subtitle'))
            .fontSize(12)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .margin({ top: 6 })
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)

        Search({ value: this.keyword, placeholder: this.tr('cap.searchPlaceholder') })
          .width(220)
          .height(36)
          .backgroundColor(AppTheme.SURFACE)
          .onChange((value: string) => {
            this.keyword = value;
          })

        Row() {
          this.ViewToggleButton(IconPaths.GRID, this.gridView, true)
          this.ViewToggleButton(IconPaths.LIST, !this.gridView, false)
        }
        .margin({ left: 10 })
        .padding(2)
        .backgroundColor(AppTheme.SURFACE)
        .borderRadius(AppTheme.RADIUS_SM)
        .border({ width: 1, color: AppTheme.BORDER })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .margin({ bottom: 18 })

      if (this.runners.length === 0) {
        Text(this.tr('cap.empty'))
          .fontSize(14)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .padding({ top: 8, bottom: 8 })
      } else {
        Flex({ wrap: FlexWrap.Wrap, justifyContent: FlexAlign.SpaceBetween }) {
          ForEach(this.visibleRunners(), (item: RunnerCapability) => {
            this.RunnerCard(item)
          }, (item: RunnerCapability) => item.runner)
        }
        .width('100%')
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
  }
}
