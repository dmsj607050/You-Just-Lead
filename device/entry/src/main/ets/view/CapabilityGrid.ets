import AppTheme from '../common/AppTheme';
import IconPaths from '../common/IconPaths';
import { RunnerCapability } from '../common/BackendClient';
import { runnerContractLabel, runnerKindLabel, runnerLabel } from '../common/Format';
import { tFor, tfFor } from '../common/I18n';
import { AppIcon } from './AppIcon';

/** 内置能力：训练适配器卡片网格，带实时搜索与网格/列表切换。 */
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

  /** 带占位符取文案。 */
  private trf(key: string, args: string[]): string {
    return tfFor(this.lang, key, args);
  }

  /**
   * 按搜索词过滤适配器。
   *
   * 标识与译文都参与匹配：中文界面下搜「分类」要能搜到，搜 `tabular` 也要能搜到 ——
   * 卡片上只显示译文，但标识仍是配置里的名字，不能搜不到。
   */
  private visibleRunners(): RunnerCapability[] {
    const key: string = this.keyword.trim().toLowerCase();
    if (key.length === 0) {
      return this.runners;
    }
    return this.runners.filter((item: RunnerCapability) =>
      item.runner.toLowerCase().includes(key) || item.kind.toLowerCase().includes(key)
      || runnerLabel(this.lang, item.runner).toLowerCase().includes(key)
      || runnerKindLabel(this.lang, item.kind).toLowerCase().includes(key));
  }

  /** 有没有搜过：搜过但没命中，要给一句空态，而不是留一片空白。 */
  private searching(): boolean {
    return this.keyword.trim().length > 0;
  }

  /**
   * 网格模式下的补位下标。
   *
   * 卡片行用 SpaceBetween 排，最后一行不满三个时，剩下的那两三张会被拉到左右两头。
   * 补几个等宽空位进去，最后一行就还是从左边开始排。
   */
  private fillers(): number[] {
    if (!this.gridView) {
      return [];
    }
    const rest: number = this.visibleRunners().length % 3;
    return rest === 0 ? [] : [0, 1].slice(0, 3 - rest);
  }

  @Builder
  ViewToggleButton(commands: string, active: boolean, grid: boolean) {
    Stack({ alignContent: Alignment.Center }) {
      AppIcon({
        commands: commands,
        color: active ? '#FFFFFF' : AppTheme.TEXT_SECONDARY,
        filled: false,
        iconSize: 20 * AppTheme.UI_SCALE
      })
    }
    .width(32 * AppTheme.UI_SCALE)
    .height(32 * AppTheme.UI_SCALE)
    .backgroundColor(active ? AppTheme.PRIMARY : Color.Transparent)
    .borderRadius(6 * AppTheme.UI_SCALE)
    .onClick(() => {
      this.gridView = grid;
    })
  }

  /**
   * 搜索框。
   *
   * 不用 Search 组件：它的默认底色与圆角跟这一套界面不一致，也塞不下自绘的清空按钮。
   * 放大镜 + 输入 + 清空，三段一行。
   */
  @Builder
  SearchBox() {
    Row() {
      AppIcon({
        commands: IconPaths.SEARCH,
        color: AppTheme.TEXT_TERTIARY,
        filled: false,
        iconSize: 16 * AppTheme.UI_SCALE
      })

      TextInput({ text: this.keyword, placeholder: this.tr('cap.searchPlaceholder') })
        .fontSize(13 * AppTheme.UI_SCALE)
        .placeholderFont({ size: 13 * AppTheme.UI_SCALE })
        .backgroundColor(Color.Transparent)
        .height(34 * AppTheme.UI_SCALE)
        .padding({ left: 8 * AppTheme.UI_SCALE, right: 8 * AppTheme.UI_SCALE })
        .layoutWeight(1)
        .onChange((value: string) => {
          this.keyword = value;
        })

      if (this.searching()) {
        Text(this.tr('cap.clear'))
          .fontSize(12 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.PRIMARY)
          .padding({ left: 8 * AppTheme.UI_SCALE, right: 4 * AppTheme.UI_SCALE, top: 6 * AppTheme.UI_SCALE, bottom: 6 * AppTheme.UI_SCALE })
          .onClick(() => {
            this.keyword = '';
          })
      }
    }
    .width(272 * AppTheme.UI_SCALE)
    .height(38 * AppTheme.UI_SCALE)
    .padding({ left: 12 * AppTheme.UI_SCALE, right: 8 * AppTheme.UI_SCALE })
    .backgroundColor(AppTheme.SURFACE)
    .borderRadius(AppTheme.RADIUS_SM)
    .border({ width: 1, color: AppTheme.BORDER })
    .alignItems(VerticalAlign.Center)
  }

  /** 一张适配器卡片：图标 + 名称 + 类型 + 数据契约。 */
  @Builder
  RunnerCard(item: RunnerCapability) {
    Column() {
      Row() {
        Stack({ alignContent: Alignment.Center }) {
          AppIcon({
            commands: IconPaths.FLASK,
            color: AppTheme.PRIMARY,
            filled: false,
            iconSize: 22 * AppTheme.UI_SCALE
          })
        }
        .width(40 * AppTheme.UI_SCALE)
        .height(40 * AppTheme.UI_SCALE)
        .backgroundColor(AppTheme.PRIMARY_SOFT)
        .borderRadius(AppTheme.RADIUS_SM)

        Text(runnerLabel(this.lang, item.runner))
          .fontSize(15 * AppTheme.UI_SCALE)
          .fontWeight(FontWeight.Medium)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .layoutWeight(1)
          .margin({ left: 12 * AppTheme.UI_SCALE })
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Text(runnerKindLabel(this.lang, item.kind))
        .fontSize(12 * AppTheme.UI_SCALE)
        .fontColor(AppTheme.PRIMARY_DARK)
        .backgroundColor(AppTheme.PRIMARY_SOFT)
        .borderRadius(6 * AppTheme.UI_SCALE)
        .padding({ left: 8 * AppTheme.UI_SCALE, right: 8 * AppTheme.UI_SCALE, top: 3 * AppTheme.UI_SCALE, bottom: 3 * AppTheme.UI_SCALE })
        .margin({ top: 14 * AppTheme.UI_SCALE })

      Text(runnerContractLabel(this.lang, item.runner, item.data_contract))
        .fontSize(12 * AppTheme.UI_SCALE)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .maxLines(4)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
        .margin({ top: 12 * AppTheme.UI_SCALE })
    }
    .alignItems(HorizontalAlign.Start)
    .width(this.gridView ? '32%' : '100%')
    .height(this.gridView ? 182 * AppTheme.UI_SCALE : 108 * AppTheme.UI_SCALE)
    .padding(18 * AppTheme.UI_SCALE)
    .backgroundColor(AppTheme.SURFACE)
    .borderRadius(AppTheme.RADIUS)
    .border({ width: 1, color: AppTheme.BORDER })
    .margin({ bottom: 14 * AppTheme.UI_SCALE })
  }

  build() {
    Column() {
      Row() {
        Text(this.tr('cap.title'))
          .fontSize(17 * AppTheme.UI_SCALE)
          .fontWeight(FontWeight.Bold)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .layoutWeight(1)

        this.SearchBox()

        Row() {
          this.ViewToggleButton(IconPaths.GRID, this.gridView, true)
          this.ViewToggleButton(IconPaths.LIST, !this.gridView, false)
        }
        .margin({ left: 12 * AppTheme.UI_SCALE })
        .padding(2 * AppTheme.UI_SCALE)
        .backgroundColor(AppTheme.SURFACE)
        .borderRadius(AppTheme.RADIUS_SM)
        .border({ width: 1, color: AppTheme.BORDER })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      // 搜索反馈只在搜的时候出现：命中几条、一共几条，不用去数卡片。
      if (this.searching()) {
        Text(this.trf('cap.matchCount', [`${this.visibleRunners().length}`, `${this.runners.length}`]))
          .fontSize(12 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .margin({ top: 12 * AppTheme.UI_SCALE })
      }

      Column() {
        if (this.runners.length === 0) {
          Text(this.tr('cap.empty'))
            .fontSize(14 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .padding({ top: 8 * AppTheme.UI_SCALE, bottom: 8 * AppTheme.UI_SCALE })
        } else if (this.visibleRunners().length === 0) {
          Text(this.tr('cap.noMatch'))
            .fontSize(14 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .padding({ top: 8 * AppTheme.UI_SCALE, bottom: 8 * AppTheme.UI_SCALE })
        } else {
          Flex({ wrap: FlexWrap.Wrap, justifyContent: FlexAlign.SpaceBetween }) {
            ForEach(this.visibleRunners(), (item: RunnerCapability) => {
              this.RunnerCard(item)
            }, (item: RunnerCapability) => `${item.runner}-${this.gridView}-${this.lang}`)
            ForEach(this.fillers(), (index: number) => {
              Row().width('32%')
            }, (index: number) => `filler-${index}`)
          }
          .width('100%')
        }
      }
      .alignItems(HorizontalAlign.Start)
      .width('100%')
      .margin({ top: 18 * AppTheme.UI_SCALE })
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
  }
}
