import AppTheme from '../common/AppTheme';
import IconPaths from '../common/IconPaths';
import { RunnerCapability } from '../common/BackendClient';
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

  /** 按搜索词过滤适配器，名称与类型都参与匹配。 */
  private visibleRunners(): RunnerCapability[] {
    const key: string = this.keyword.trim().toLowerCase();
    if (key.length === 0) {
      return this.runners;
    }
    return this.runners.filter((item: RunnerCapability) =>
      item.runner.toLowerCase().includes(key) || item.kind.toLowerCase().includes(key));
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
        iconSize: 16
      })

      TextInput({ text: this.keyword, placeholder: this.tr('cap.searchPlaceholder') })
        .fontSize(13)
        .placeholderFont({ size: 13 })
        .backgroundColor(Color.Transparent)
        .height(34)
        .padding({ left: 8, right: 8 })
        .layoutWeight(1)
        .onChange((value: string) => {
          this.keyword = value;
        })

      if (this.searching()) {
        Text(this.tr('cap.clear'))
          .fontSize(12)
          .fontColor(AppTheme.PRIMARY)
          .padding({ left: 8, right: 4, top: 6, bottom: 6 })
          .onClick(() => {
            this.keyword = '';
          })
      }
    }
    .width(272)
    .height(38)
    .padding({ left: 12, right: 8 })
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
            iconSize: 22
          })
        }
        .width(40)
        .height(40)
        .backgroundColor(AppTheme.PRIMARY_SOFT)
        .borderRadius(AppTheme.RADIUS_SM)

        Text(item.runner)
          .fontSize(15)
          .fontWeight(FontWeight.Medium)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .layoutWeight(1)
          .margin({ left: 12 })
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Text(item.kind)
        .fontSize(12)
        .fontColor(AppTheme.PRIMARY_DARK)
        .backgroundColor(AppTheme.PRIMARY_SOFT)
        .borderRadius(6)
        .padding({ left: 8, right: 8, top: 3, bottom: 3 })
        .margin({ top: 14 })

      Text(item.data_contract)
        .fontSize(12)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .maxLines(4)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
        .margin({ top: 12 })
    }
    .alignItems(HorizontalAlign.Start)
    .width(this.gridView ? '32%' : '100%')
    .height(this.gridView ? 182 : 108)
    .padding(18)
    .backgroundColor(AppTheme.SURFACE)
    .borderRadius(AppTheme.RADIUS)
    .border({ width: 1, color: AppTheme.BORDER })
    .margin({ bottom: 14 })
  }

  build() {
    Column() {
      Row() {
        Text(this.tr('cap.title'))
          .fontSize(17)
          .fontWeight(FontWeight.Bold)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .layoutWeight(1)

        this.SearchBox()

        Row() {
          this.ViewToggleButton(IconPaths.GRID, this.gridView, true)
          this.ViewToggleButton(IconPaths.LIST, !this.gridView, false)
        }
        .margin({ left: 12 })
        .padding(2)
        .backgroundColor(AppTheme.SURFACE)
        .borderRadius(AppTheme.RADIUS_SM)
        .border({ width: 1, color: AppTheme.BORDER })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      // 搜索反馈只在搜的时候出现：命中几条、一共几条，不用去数卡片。
      if (this.searching()) {
        Text(this.trf('cap.matchCount', [`${this.visibleRunners().length}`, `${this.runners.length}`]))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .margin({ top: 12 })
      }

      Column() {
        if (this.runners.length === 0) {
          Text(this.tr('cap.empty'))
            .fontSize(14)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .padding({ top: 8, bottom: 8 })
        } else if (this.visibleRunners().length === 0) {
          Text(this.tr('cap.noMatch'))
            .fontSize(14)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .padding({ top: 8, bottom: 8 })
        } else {
          Flex({ wrap: FlexWrap.Wrap, justifyContent: FlexAlign.SpaceBetween }) {
            ForEach(this.visibleRunners(), (item: RunnerCapability) => {
              this.RunnerCard(item)
            }, (item: RunnerCapability) => `${item.runner}-${this.gridView}`)
            ForEach(this.fillers(), (index: number) => {
              Row().width('32%')
            }, (index: number) => `filler-${index}`)
          }
          .width('100%')
        }
      }
      .alignItems(HorizontalAlign.Start)
      .width('100%')
      .margin({ top: 18 })
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
  }
}
