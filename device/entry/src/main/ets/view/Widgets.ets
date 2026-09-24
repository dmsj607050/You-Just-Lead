import AppTheme from '../common/AppTheme';
import { tFor } from '../common/I18n';

/**
 * 跨页面复用的展示原子。
 *
 * 只放与业务无关的纯展示组件，页面之间靠它们保持视觉一致。
 * 所有输入都用 @Prop：数据是异步取回的，普通成员不会随父组件刷新。
 */

/** 页面标题区：大标题 + 一行说明 + 刷新入口。 */
@Component
export struct PageHeader {
  /**
   * 当前语言。ArkUI 只重建读到状态变量的节点，所以本组件所有文案都走 this.tr()，
   * 由它读一次 this.lang，等于把用到的节点登记到语言变化上。
   */
  @StorageLink('lang') lang: string = 'zh';

  /** 取文案：读一次 lang，让调用它的节点订阅语言变化。 */
  private tr(key: string): string {
    return tFor(this.lang, key);
  }

  @Prop title: string = '';
  /**
   * 一行现状：把「现在是什么状态」压成一句带数字的话。
   *
   * 标题下面只留这一行。原先还有一行灰色的说明文字（「数据先过审计再进训练…」那类），
   * 它既不是数据也不是结论，只是把标题复述了一遍，已删除。
   */
  @Prop status: string = '';
  /** 点击「刷新」重新取一次数据。 */
  onRefresh: () => void = () => {
  };

  build() {
    Row() {
      Column() {
        Text(this.title)
          .fontSize(24)
          .fontWeight(FontWeight.Bold)
          .fontColor(AppTheme.TEXT_PRIMARY)
        if (this.status.length > 0) {
          Text(this.status)
            .fontSize(14)
            .fontWeight(FontWeight.Medium)
            .fontColor(AppTheme.TEXT_PRIMARY)
            .margin({ top: 10 })
        }
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)

      Text(this.tr('common.refresh'))
        .fontSize(13)
        .fontColor(AppTheme.PRIMARY)
        .padding({ left: 12, right: 12, top: 6, bottom: 6 })
        .onClick(() => {
          this.onRefresh();
        })
    }
    .width('100%')
    .alignItems(VerticalAlign.Top)
  }
}

/** 白色卡片容器，可带标题。 */
@Component
export struct CardPanel {
  @Prop title: string = '';
  /** 放在 Row 中并排时用它分配宽度，0 表示按自身尺寸。 */
  @Prop weight: number = 0;
  @BuilderParam content: () => void = this.emptyContent;

  @Builder
  emptyContent() {
  }

  build() {
    Column() {
      if (this.title.length > 0) {
        Column() {
          Text(this.title)
            .fontSize(17)
            .fontWeight(FontWeight.Bold)
            .fontColor(AppTheme.TEXT_PRIMARY)
        }
        .alignItems(HorizontalAlign.Start)
        .width('100%')
        .margin({ bottom: 16 })
      }

      this.content()
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .layoutWeight(this.weight)
    .padding(24)
    .backgroundColor(AppTheme.SURFACE)
    .borderRadius(AppTheme.RADIUS_LG)
    .border({ width: 1, color: AppTheme.BORDER })
  }
}

/** 一个指标块的数据。 */
export interface StatTileSpec {
  label: string;
  value: string;
  hint: string;
}

/** 指标块：一个数字加一行说明。 */
@Component
export struct StatTile {
  @Prop label: string = '';
  @Prop value: string = '';
  @Prop hint: string = '';

  /** 值可能是数字，也可能是型号这类长文本，长文本用小一号字避免被截断。 */
  private valueFontSize(): number {
    if (this.value.length > 16) {
      return 15;
    }
    if (this.value.length > 11) {
      return 17;
    }
    return 22;
  }

  build() {
    Column() {
      Text(this.value)
        .fontSize(this.valueFontSize())
        .fontWeight(FontWeight.Bold)
        .fontColor(AppTheme.TEXT_PRIMARY)
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
      Text(this.label)
        .fontSize(12)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .margin({ top: 6 })
      if (this.hint.length > 0) {
        Text(this.hint)
          .fontSize(11)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .margin({ top: 4 })
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }
    }
    .alignItems(HorizontalAlign.Start)
    .layoutWeight(1)
    .padding({ left: 16, right: 16, top: 16, bottom: 16 })
    .backgroundColor(AppTheme.PAGE_BG)
    .borderRadius(AppTheme.RADIUS)
  }
}

/**
 * 指标行：宽窗口一行四个，窄窗口自动折成两行两列。
 *
 * 固定四块——页面上的指标本来就是四个一组，折行规则写在一处即可。
 * 这里用子组件而不是 @Builder 渲染每一块：@Builder 按值传对象不会随数据刷新。
 */
@Component
export struct StatTileGrid {
  @Prop items: StatTileSpec[] = [];
  /** 窗口变窄时换行，避免数值被截断成半截。 */
  @State stacked: boolean = false;

  build() {
    Column() {
      if (this.items.length === 4) {
        if (this.stacked) {
          Column({ space: 12 }) {
            Row({ space: 12 }) {
              StatTile({
                label: this.items[0].label,
                value: this.items[0].value,
                hint: this.items[0].hint
              })
              StatTile({
                label: this.items[1].label,
                value: this.items[1].value,
                hint: this.items[1].hint
              })
            }
            .width('100%')
            .alignItems(VerticalAlign.Top)

            Row({ space: 12 }) {
              StatTile({
                label: this.items[2].label,
                value: this.items[2].value,
                hint: this.items[2].hint
              })
              StatTile({
                label: this.items[3].label,
                value: this.items[3].value,
                hint: this.items[3].hint
              })
            }
            .width('100%')
            .alignItems(VerticalAlign.Top)
          }
          .width('100%')
        } else {
          Row({ space: 12 }) {
            StatTile({
              label: this.items[0].label,
              value: this.items[0].value,
              hint: this.items[0].hint
            })
            StatTile({
              label: this.items[1].label,
              value: this.items[1].value,
              hint: this.items[1].hint
            })
            StatTile({
              label: this.items[2].label,
              value: this.items[2].value,
              hint: this.items[2].hint
            })
            StatTile({
              label: this.items[3].label,
              value: this.items[3].value,
              hint: this.items[3].hint
            })
          }
          .width('100%')
          .alignItems(VerticalAlign.Top)
        }
      }
    }
    .width('100%')
    .onAreaChange((oldValue: Area, newValue: Area) => {
      const width: number = Number(newValue.width);
      this.stacked = width > 0 && width < 760;
    })
  }
}

/** 一行「标签 + 值」，值过长时截断。 */
@Component
export struct KeyValueRow {
  @Prop label: string = '';
  @Prop value: string = '';
  /** 值为长路径或哈希时用等宽感更强的样式呈现。 */
  @Prop mono: boolean = false;

  build() {
    Row() {
      Text(this.label)
        .fontSize(13)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .width(150)
      Text(this.value.length > 0 ? this.value : '—')
        .fontSize(this.mono ? 12 : 13)
        .fontColor(AppTheme.TEXT_PRIMARY)
        .layoutWeight(1)
        .maxLines(2)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
    }
    .width('100%')
    .alignItems(VerticalAlign.Top)
    .padding({ top: 9, bottom: 9 })
  }
}

/** 状态徽章。tone 取 ok / warn / danger / muted。 */
@Component
export struct StatusBadge {
  @Prop text: string = '';
  @Prop tone: string = 'muted';

  private badgeTextColor(): string {
    if (this.tone === 'ok') {
      return AppTheme.PRIMARY_DARK;
    }
    if (this.tone === 'warn') {
      return AppTheme.WARN_TEXT;
    }
    if (this.tone === 'danger') {
      return AppTheme.DANGER;
    }
    return AppTheme.TEXT_SECONDARY;
  }

  private badgeBackgroundColor(): string {
    if (this.tone === 'ok') {
      return AppTheme.PRIMARY_SOFT;
    }
    if (this.tone === 'warn') {
      return AppTheme.WARN_SOFT;
    }
    if (this.tone === 'danger') {
      return AppTheme.DANGER_SOFT;
    }
    return AppTheme.PAGE_BG;
  }

  build() {
    Text(this.text)
      .fontSize(12)
      .fontColor(this.badgeTextColor())
      .backgroundColor(this.badgeBackgroundColor())
      .borderRadius(6)
      .padding({ left: 10, right: 10, top: 4, bottom: 4 })
  }
}

/** 空态提示。 */
@Component
export struct EmptyHint {
  @Prop text: string = '';

  build() {
    Text(this.text)
      .fontSize(13)
      .fontColor(AppTheme.TEXT_TERTIARY)
      .width('100%')
      .padding({ top: 12, bottom: 12 })
  }
}

/** 分段导航的一项：段落标识 + 短标签 + 这一段的健康度。 */
export interface RailItemSpec {
  key: string;
  /** 已翻译的短标签。文案表里的键由调用方取，这里只收结果。 */
  label: string;
  /** ok / warn / danger / muted，决定左侧色点的颜色。 */
  tone: string;
}

/** 健康度 -> 色点颜色。 */
function railToneColor(tone: string): string {
  if (tone === 'ok') {
    return AppTheme.PRIMARY;
  }
  if (tone === 'warn') {
    return AppTheme.WARN_TEXT;
  }
  if (tone === 'danger') {
    return AppTheme.DANGER;
  }
  return AppTheme.TEXT_TERTIARY;
}

/**
 * 分段导航条：把一个长页面切成几段，一次只渲染一段。
 *
 * 每一项左边带一个色点，回答的是「这条链通不通」；具体数字留在段里，不在这里堆——
 * 那正是这类页面变成十几屏长滚动的原因。
 *
 * 用 Flex 自动折行而不是固定宽度，窄窗口（手机）下会排成两行，不会把标签挤断。
 */
@Component
export struct SectionRail {
  @Prop items: RailItemSpec[] = [];
  /** 当前选中的段落标识。 */
  @Prop active: string = '';
  /** 点某一项时回调它的 key。 */
  onSelect: (key: string) => void = () => {
  };

  build() {
    Flex({ wrap: FlexWrap.Wrap }) {
      ForEach(this.items, (item: RailItemSpec) => {
        Row() {
          Row()
            .width(6)
            .height(6)
            .borderRadius(3)
            .backgroundColor(railToneColor(item.tone))
          Text(item.label)
            .fontSize(13)
            .fontWeight(item.key === this.active ? FontWeight.Medium : FontWeight.Normal)
            .fontColor(item.key === this.active ? AppTheme.PRIMARY_DARK : AppTheme.TEXT_SECONDARY)
            .margin({ left: 8 })
        }
        .alignItems(VerticalAlign.Center)
        .padding({ left: 14, right: 14, top: 9, bottom: 9 })
        .backgroundColor(item.key === this.active ? AppTheme.PRIMARY_SOFT : AppTheme.PAGE_BG)
        .borderRadius(AppTheme.RADIUS)
        .margin({ right: 10, bottom: 10 })
        .onClick(() => {
          this.onSelect(item.key);
        })
      }, (item: RailItemSpec) => `${item.key}-${item.key === this.active}-${item.tone}-${item.label}`)
    }
    .width('100%')
  }
}

/** 分布条的一项。 */
export interface BarItemSpec {
  label: string;
  value: number;
  /** 右侧显示的文本；留空就用数值本身。 */
  valueText: string;
}

/**
 * 分布条：一行一个标签 + 一根横条 + 数值。
 *
 * 原来这类分布是「标签 …… 数字」的纯文本行，看不出谁多谁少。条长按这一组里的最大值
 * 归一，差异一眼可见 —— 用图形说一件本来就是图形的事。
 *
 * 条形是布局元素拼的（轨道 + 填充），不用图片也不用 Canvas。
 */
@Component
export struct BarList {
  @Prop items: BarItemSpec[] = [];
  /** 条的颜色：primary / warn / muted。 */
  @Prop tone: string = 'primary';

  private maxValue(): number {
    let max: number = 0;
    for (const item of this.items) {
      if (item.value > max) {
        max = item.value;
      }
    }
    return max;
  }

  private percent(value: number): number {
    const max: number = this.maxValue();
    if (max <= 0 || value <= 0) {
      return 0;
    }
    // 有值的条至少给一点长度，否则「1」和「0」看起来一样。
    return Math.max(3, Math.round((value / max) * 100));
  }

  private barColor(): string {
    if (this.tone === 'warn') {
      return AppTheme.WARN_TEXT;
    }
    if (this.tone === 'muted') {
      return AppTheme.TEXT_TERTIARY;
    }
    return AppTheme.PRIMARY;
  }

  build() {
    Column({ space: 12 }) {
      ForEach(this.items, (item: BarItemSpec) => {
        Column() {
          Row() {
            Text(item.label)
              .fontSize(13)
              .fontColor(AppTheme.TEXT_PRIMARY)
              .layoutWeight(1)
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
            Text(item.valueText.length > 0 ? item.valueText : `${item.value}`)
              .fontSize(13)
              .fontColor(AppTheme.TEXT_SECONDARY)
              .margin({ left: 12 })
          }
          .width('100%')

          Row() {
            Row()
              .width(`${this.percent(item.value)}%`)
              .height(6)
              .borderRadius(3)
              .backgroundColor(this.barColor())
          }
          .width('100%')
          .height(6)
          .borderRadius(3)
          .backgroundColor(AppTheme.PAGE_BG)
          .margin({ top: 6 })
        }
        .width('100%')
      }, (item: BarItemSpec) => `${item.label}-${item.value}-${item.valueText}-${this.tone}`)
    }
    .width('100%')
  }
}

/**
 * 比例条：左边说的是「哪件事」，右边是「几分之几」，中间用长度表示比例。
 *
 * 「必填 24 项、缺口 0 项」这类结论本来就是比例关系，写成文字要读两遍才明白，
 * 画成条一眼就知道走到哪了。
 */
@Component
export struct ProgressBar {
  @Prop label: string = '';
  @Prop current: number = 0;
  @Prop total: number = 0;
  /** 达成时用主色，未达成用告警色；留空按是否达成自动选。 */
  @Prop tone: string = '';

  private done(): boolean {
    return this.total > 0 && this.current >= this.total;
  }

  private percent(): number {
    if (this.total <= 0) {
      return 0;
    }
    const ratio: number = this.current / this.total;
    return Math.max(this.current > 0 ? 3 : 0, Math.min(100, Math.round(ratio * 100)));
  }

  private barColor(): string {
    if (this.tone === 'warn') {
      return AppTheme.WARN_TEXT;
    }
    if (this.tone === 'ok') {
      return AppTheme.PRIMARY;
    }
    return this.done() ? AppTheme.PRIMARY : AppTheme.WARN_TEXT;
  }

  build() {
    Column() {
      Row() {
        Text(this.label)
          .fontSize(13)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .layoutWeight(1)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        Text(`${this.current}/${this.total}`)
          .fontSize(13)
          .fontWeight(FontWeight.Medium)
          .fontColor(this.barColor())
          .margin({ left: 12 })
      }
      .width('100%')

      Row() {
        Row()
          .width(`${this.percent()}%`)
          .height(6)
          .borderRadius(3)
          .backgroundColor(this.barColor())
      }
      .width('100%')
      .height(6)
      .borderRadius(3)
      .backgroundColor(AppTheme.PAGE_BG)
      .margin({ top: 6 })
    }
    .width('100%')
  }
}
