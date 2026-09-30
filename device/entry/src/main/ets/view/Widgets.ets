import AppTheme from '../common/AppTheme';
import { tFor } from '../common/I18n';
import { AppIcon } from './AppIcon';

/**
 * 跨页面复用的展示原子。
 *
 * 只放与业务无关的纯展示组件，页面之间靠它们保持视觉一致。
 * 所有输入都用 @Prop：数据是异步取回的，普通成员不会随父组件刷新。
 */

/**
 * 页面顶部状态条：一行现状 + 刷新入口。
 *
 * 原来这里还有个 24 号的大标题，和左侧面板里高亮的那一项完全重复 —— 面板上已经写着
 * 「文献」，页面顶部再写一遍只是白占高度。标题删掉之后组件也不再收 title 参数。
 */
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

  /**
   * 一行现状：把「现在是什么状态」压成一句带数字的话。
   *
   * 这是页面顶部唯一的一行字，取不到数据时留空。
   */
  @Prop status: string = '';
  /** 点击「刷新」重新取一次数据。 */
  onRefresh: () => void = () => {
  };

  build() {
    Row() {
      // 空着也占满剩余宽度，刷新才会贴在最右边、位置不随文案长短跳。
      Text(this.status)
        .fontSize(14 * AppTheme.UI_SCALE)
        .fontWeight(FontWeight.Medium)
        .fontColor(AppTheme.TEXT_PRIMARY)
        .layoutWeight(1)

      Text(this.tr('common.refresh'))
        .fontSize(13 * AppTheme.UI_SCALE)
        .fontColor(AppTheme.PRIMARY)
        .padding({ left: 12 * AppTheme.UI_SCALE, right: 12 * AppTheme.UI_SCALE, top: 6 * AppTheme.UI_SCALE, bottom: 6 * AppTheme.UI_SCALE })
        .onClick(() => {
          this.onRefresh();
        })
    }
    .width('100%')
    .alignItems(VerticalAlign.Center)
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
            .fontSize(17 * AppTheme.UI_SCALE)
            .fontWeight(FontWeight.Bold)
            .fontColor(AppTheme.TEXT_PRIMARY)
        }
        .alignItems(HorizontalAlign.Start)
        .width('100%')
        .margin({ bottom: 16 * AppTheme.UI_SCALE })
      }

      this.content()
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .layoutWeight(this.weight)
    .padding(24 * AppTheme.UI_SCALE)
    .backgroundColor(AppTheme.SURFACE)
    .borderRadius(AppTheme.RADIUS_LG)
    .border({ width: 1, color: AppTheme.BORDER })
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
        .fontSize(13 * AppTheme.UI_SCALE)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .width(150 * AppTheme.UI_SCALE)
      Text(this.value.length > 0 ? this.value : '—')
        .fontSize(this.mono ? 12 * AppTheme.UI_SCALE : 13 * AppTheme.UI_SCALE)
        .fontColor(AppTheme.TEXT_PRIMARY)
        .layoutWeight(1)
        .maxLines(2)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
    }
    .width('100%')
    .alignItems(VerticalAlign.Top)
    .padding({ top: 9 * AppTheme.UI_SCALE, bottom: 9 * AppTheme.UI_SCALE })
  }
}

/** 状态徽章。tone 取 ok / warn / danger / muted。 */
@Component
export struct StatusBadge {
  @Prop text: string = '';
  @Prop tone: string = 'muted';

  private badgeTextColor(): ResourceColor {
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

  private badgeBackgroundColor(): ResourceColor {
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
      .fontSize(12 * AppTheme.UI_SCALE)
      .fontColor(this.badgeTextColor())
      .backgroundColor(this.badgeBackgroundColor())
      .borderRadius(6 * AppTheme.UI_SCALE)
      .padding({ left: 10 * AppTheme.UI_SCALE, right: 10 * AppTheme.UI_SCALE, top: 4 * AppTheme.UI_SCALE, bottom: 4 * AppTheme.UI_SCALE })
  }
}

/**
 * 一个数字块：上面是大数字，下面是它是什么。
 *
 * 这里刻意用 `@Prop` 而不是给 `@Builder` 传参：**`@Builder` 的参数按值取，参数变了不会刷新 UI**。
 * 真机上正是这么暴露的 —— 同一批状态算出来的现状行是对的，这五个数字却一直停在初始的 0。
 * 展开占位由调用方给（`MetricCard({...}).layoutWeight(1)`）：组件内部加权重管不到父容器。
 */
@Component
export struct MetricCard {
  @Prop label: string = '';
  @Prop value: string = '';
  @Prop tone: string = 'muted';

  build() {
    Column() {
      Text(this.value)
        .fontSize(26 * AppTheme.UI_SCALE)
        .fontWeight(FontWeight.Bold)
        .fontColor(this.tone === 'warn' ? AppTheme.WARN_TEXT : AppTheme.TEXT_PRIMARY)
      Text(this.label)
        .fontSize(12 * AppTheme.UI_SCALE)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .margin({ top: 6 * AppTheme.UI_SCALE })
        .maxLines(2)
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ left: 16 * AppTheme.UI_SCALE, right: 16 * AppTheme.UI_SCALE, top: 14 * AppTheme.UI_SCALE, bottom: 14 * AppTheme.UI_SCALE })
    .backgroundColor(AppTheme.SURFACE)
    .borderRadius(AppTheme.RADIUS_LG)
    .border({ width: 1, color: AppTheme.BORDER })
  }
}

/** 空态提示。 */
@Component
export struct EmptyHint {
  @Prop text: string = '';

  build() {
    Text(this.text)
      .fontSize(13 * AppTheme.UI_SCALE)
      .fontColor(AppTheme.TEXT_TERTIARY)
      .width('100%')
      .padding({ top: 12 * AppTheme.UI_SCALE, bottom: 12 * AppTheme.UI_SCALE })
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
function railToneColor(tone: string): ResourceColor {
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
            .width(6 * AppTheme.UI_SCALE)
            .height(6 * AppTheme.UI_SCALE)
            .borderRadius(3 * AppTheme.UI_SCALE)
            .backgroundColor(railToneColor(item.tone))
          Text(item.label)
            .fontSize(13 * AppTheme.UI_SCALE)
            .fontWeight(item.key === this.active ? FontWeight.Medium : FontWeight.Normal)
            .fontColor(item.key === this.active ? AppTheme.PRIMARY_DARK : AppTheme.TEXT_SECONDARY)
            .margin({ left: 8 * AppTheme.UI_SCALE })
        }
        .alignItems(VerticalAlign.Center)
        .padding({ left: 14 * AppTheme.UI_SCALE, right: 14 * AppTheme.UI_SCALE, top: 9 * AppTheme.UI_SCALE, bottom: 9 * AppTheme.UI_SCALE })
        .backgroundColor(item.key === this.active ? AppTheme.PRIMARY_SOFT : AppTheme.PAGE_BG)
        .borderRadius(AppTheme.RADIUS)
        .margin({ right: 10 * AppTheme.UI_SCALE, bottom: 10 * AppTheme.UI_SCALE })
        .onClick(() => {
          this.onSelect(item.key);
        })
      }, (item: RailItemSpec) => `${item.key}-${item.key === this.active}-${item.tone}-${item.label}`)
    }
    .width('100%')
  }
}

/** 可选项的一项。 */
export interface ChoiceSpec {
  key: string;
  /** 已翻译的短标签。 */
  label: string;
  /** ok / warn / muted，决定选中时的底色与文字色。 */
  tone: string;
}

/** 选中态的底色。 */
function choiceBackground(tone: string): ResourceColor {
  if (tone === 'ok') {
    return AppTheme.PRIMARY_SOFT;
  }
  if (tone === 'warn') {
    return AppTheme.WARN_SOFT;
  }
  if (tone === 'danger') {
    return AppTheme.DANGER_SOFT;
  }
  return AppTheme.PAGE_BG;
}

/** 选中态的文字色。 */
function choiceTextColor(tone: string): ResourceColor {
  if (tone === 'ok') {
    return AppTheme.PRIMARY_DARK;
  }
  if (tone === 'warn') {
    return AppTheme.WARN_TEXT;
  }
  if (tone === 'danger') {
    return AppTheme.DANGER;
  }
  return AppTheme.TEXT_SECONDARY;
}

/**
 * 可选列表：一排互斥的小块，选中那一块用底色标出来。
 *
 * 与 `SectionRail` 的区别是用途：那个是切换页面分段，这个是在一段里对**一条记录**做取舍
 * （调研 / 舍弃）。所以它不参与分段高亮的样式，选中态也用各自的色调说话。
 */
@Component
export struct ChoiceChips {
  @Prop items: ChoiceSpec[] = [];
  /** 当前选中的 key；空串表示一项都没选。 */
  @Prop active: string = '';
  /** 提交中禁用，避免连点两次写出两条相反的取舍。 */
  @Prop disabled: boolean = false;
  onSelect: (key: string) => void = () => {
  };

  build() {
    Flex({ wrap: FlexWrap.Wrap }) {
      ForEach(this.items, (item: ChoiceSpec) => {
        Text(item.label)
          .fontSize(12 * AppTheme.UI_SCALE)
          .fontColor(item.key === this.active ? choiceTextColor(item.tone) : AppTheme.TEXT_SECONDARY)
          .backgroundColor(item.key === this.active ? choiceBackground(item.tone) : AppTheme.PAGE_BG)
          .borderRadius(6 * AppTheme.UI_SCALE)
          .padding({ left: 12 * AppTheme.UI_SCALE, right: 12 * AppTheme.UI_SCALE, top: 6 * AppTheme.UI_SCALE, bottom: 6 * AppTheme.UI_SCALE })
          .margin({ right: 8 * AppTheme.UI_SCALE, bottom: 8 * AppTheme.UI_SCALE })
          .opacity(this.disabled ? 0.5 : 1)
          .onClick(() => {
            if (!this.disabled) {
              this.onSelect(item.key);
            }
          })
      }, (item: ChoiceSpec) => `${item.key}-${item.key === this.active}-${item.label}`)
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

  private barColor(): ResourceColor {
    if (this.tone === 'warn') {
      return AppTheme.WARN_TEXT;
    }
    if (this.tone === 'muted') {
      return AppTheme.TEXT_TERTIARY;
    }
    return AppTheme.PRIMARY;
  }

  build() {
    Column({ space: 12 * AppTheme.UI_SCALE }) {
      ForEach(this.items, (item: BarItemSpec) => {
        Column() {
          Row() {
            Text(item.label)
              .fontSize(13 * AppTheme.UI_SCALE)
              .fontColor(AppTheme.TEXT_PRIMARY)
              .layoutWeight(1)
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
            Text(item.valueText.length > 0 ? item.valueText : `${item.value}`)
              .fontSize(13 * AppTheme.UI_SCALE)
              .fontColor(AppTheme.TEXT_SECONDARY)
              .margin({ left: 12 * AppTheme.UI_SCALE })
          }
          .width('100%')

          Row() {
            Row()
              .width(`${this.percent(item.value)}%`)
              .height(6 * AppTheme.UI_SCALE)
              .borderRadius(3 * AppTheme.UI_SCALE)
              .backgroundColor(this.barColor())
          }
          .width('100%')
          .height(6 * AppTheme.UI_SCALE)
          .borderRadius(3 * AppTheme.UI_SCALE)
          .backgroundColor(AppTheme.PAGE_BG)
          .margin({ top: 6 * AppTheme.UI_SCALE })
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

  private barColor(): ResourceColor {
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
          .fontSize(13 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .layoutWeight(1)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        Text(`${this.current}/${this.total}`)
          .fontSize(13 * AppTheme.UI_SCALE)
          .fontWeight(FontWeight.Medium)
          .fontColor(this.barColor())
          .margin({ left: 12 * AppTheme.UI_SCALE })
      }
      .width('100%')

      Row() {
        Row()
          .width(`${this.percent()}%`)
          .height(6 * AppTheme.UI_SCALE)
          .borderRadius(3 * AppTheme.UI_SCALE)
          .backgroundColor(this.barColor())
      }
      .width('100%')
      .height(6 * AppTheme.UI_SCALE)
      .borderRadius(3 * AppTheme.UI_SCALE)
      .backgroundColor(AppTheme.PAGE_BG)
      .margin({ top: 6 * AppTheme.UI_SCALE })
    }
    .width('100%')
  }
}

// ---- 设置页就绪状态与配置卡片用到的一组控件 ----
//
// 与上面几个的区别：上面的是「一行标签 + 一个值」，这一组带色点、图标、开关与操作按钮，
// 用来把「现在能不能用、哪里缺、缺了怎么办」一眼说清。色调口径与 StatusBadge 一致。

/** 色调 -> 文字色。ok / warn / danger / muted。 */
function toneTextColor(tone: string): ResourceColor {
  if (tone === 'ok') {
    return AppTheme.PRIMARY_DARK;
  }
  if (tone === 'warn') {
    return AppTheme.WARN_TEXT;
  }
  if (tone === 'danger') {
    return AppTheme.DANGER;
  }
  return AppTheme.TEXT_SECONDARY;
}

/** 色调 -> 底色。 */
function toneBackground(tone: string): ResourceColor {
  if (tone === 'ok') {
    return AppTheme.PRIMARY_SOFT;
  }
  if (tone === 'warn') {
    return AppTheme.WARN_SOFT;
  }
  if (tone === 'danger') {
    return AppTheme.DANGER_SOFT;
  }
  return AppTheme.PAGE_BG;
}

/** 色调 -> 色点颜色。点比文字更醒目，所以用饱和色而不是文字色。 */
function toneDotColor(tone: string): ResourceColor {
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

/** 状态胶囊：一个色点 + 一句短状态（正常 / 未配置 / 未连接）。 */
@Component
export struct StatusPill {
  @Prop label: string = '';
  @Prop tone: string = 'muted';

  build() {
    Row() {
      Row()
        .width(7 * AppTheme.UI_SCALE)
        .height(7 * AppTheme.UI_SCALE)
        .borderRadius(4 * AppTheme.UI_SCALE)
        .backgroundColor(toneDotColor(this.tone))
      Text(this.label)
        .fontSize(12 * AppTheme.UI_SCALE)
        .fontColor(toneTextColor(this.tone))
        .margin({ left: 6 * AppTheme.UI_SCALE })
    }
    .alignItems(VerticalAlign.Center)
    .padding({ left: 9 * AppTheme.UI_SCALE, right: 9 * AppTheme.UI_SCALE, top: 4 * AppTheme.UI_SCALE, bottom: 4 * AppTheme.UI_SCALE })
    .backgroundColor(toneBackground(this.tone))
    .borderRadius(6 * AppTheme.UI_SCALE)
  }
}

/** 圆角方块里的图标：卡片头与状态磁贴都用它，保证图标的底色口径一致。 */
@Component
export struct IconChip {
  @Prop icon: string = '';
  @Prop tone: string = 'muted';
  /** 方块边长。**不能叫 `size`**：那是组件的内置属性名，同名会报不可赋值。 */
  @Prop chipSize: number = 32;

  build() {
    Stack() {
      AppIcon({
        commands: this.icon,
        color: toneTextColor(this.tone),
        filled: false,
        iconSize: Math.round(this.chipSize * 0.56)
      })
    }
    .width(this.chipSize)
    .height(this.chipSize)
    .backgroundColor(toneBackground(this.tone))
    .borderRadius(Math.round(this.chipSize * 0.3))
  }
}

/**
 * 区块卡片：中文主标题 + 英文副标题 +（可选）右上角一个操作。
 *
 * 副标题不是装饰：这个产品里「就绪状态」「模型与运行时」这类词在两端、在文档里都要对得上，
 * 英文那行是给同一套术语留的锚点，也让人一眼看出这一块管的是什么。
 */
@Component
export struct SectionCard {
  @Prop title: string = '';
  @Prop subtitle: string = '';
  /** 卡片头左侧图标；留空则不画。 */
  @Prop icon: string = '';
  @Prop iconTone: string = 'muted';
  /** 右上角操作文案；留空则不画。 */
  @Prop actionLabel: string = '';
  /** 右上角操作的色调：primary / danger / muted。 */
  @Prop actionTone: string = 'primary';
  @Prop actionActive: boolean = true;
  /** 放在 Row 中并排时用它分配宽度，0 表示按自身尺寸。与 CardPanel 同一口径。 */
  @Prop weight: number = 0;
  onAction: () => void = () => {
  };
  @BuilderParam content: () => void = this.emptyContent;

  @Builder
  emptyContent() {
  }

  build() {
    Column() {
      Row() {
        if (this.icon.length > 0) {
          IconChip({ icon: this.icon, tone: this.iconTone, chipSize: 34 * AppTheme.UI_SCALE })
            .margin({ right: 12 * AppTheme.UI_SCALE })
        }
        Column() {
          Text(this.title)
            .fontSize(16 * AppTheme.UI_SCALE)
            .fontWeight(FontWeight.Bold)
            .fontColor(AppTheme.TEXT_PRIMARY)
          if (this.subtitle.length > 0) {
            Text(this.subtitle)
              .fontSize(11 * AppTheme.UI_SCALE)
              .fontColor(AppTheme.TEXT_TERTIARY)
              .margin({ top: 3 * AppTheme.UI_SCALE })
          }
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)

        if (this.actionLabel.length > 0) {
          Text(this.actionLabel)
            .fontSize(12 * AppTheme.UI_SCALE)
            .fontColor(this.actionActive
              ? (this.actionTone === 'danger'
                ? AppTheme.DANGER
                : (this.actionTone === 'muted' ? AppTheme.TEXT_TERTIARY : AppTheme.PRIMARY))
              : AppTheme.TEXT_TERTIARY)
            .padding({ left: 8 * AppTheme.UI_SCALE, top: 4 * AppTheme.UI_SCALE, bottom: 4 * AppTheme.UI_SCALE })
            .enabled(this.actionActive)
            .onClick(() => {
              if (this.actionActive) {
                this.onAction();
              }
            })
        }
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .margin({ bottom: 16 * AppTheme.UI_SCALE })

      this.content()
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .layoutWeight(this.weight)
    .padding(20 * AppTheme.UI_SCALE)
    .backgroundColor(AppTheme.SURFACE)
    .borderRadius(AppTheme.RADIUS_LG)
    .border({ width: 1, color: AppTheme.BORDER })
  }
}

/**
 * 状态磁贴：一项能力现在怎么样。
 *
 * 与 `MetricCard` 的区别：那个只给一个数字，这个要给「什么能力 + 正常不正常 + 现在是什么 +
 * 缺了会影响什么」四件事 —— 设置页的价值恰恰在这四件事一起看。
 */
@Component
export struct StatusTile {
  @Prop icon: string = '';
  @Prop title: string = '';
  @Prop subtitle: string = '';
  @Prop tone: string = 'muted';
  @Prop pill: string = '';
  /** 当前值（模型名、设备名）。可以为空。 */
  @Prop value: string = '';
  /** 这一项对用户意味着什么。 */
  @Prop note: string = '';

  build() {
    Column() {
      Row() {
        IconChip({ icon: this.icon, tone: this.tone, chipSize: 36 * AppTheme.UI_SCALE })
          .margin({ right: 12 * AppTheme.UI_SCALE })
        Column() {
          Text(this.title)
            .fontSize(14 * AppTheme.UI_SCALE)
            .fontWeight(FontWeight.Medium)
            .fontColor(AppTheme.TEXT_PRIMARY)
            .maxLines(1)
          if (this.subtitle.length > 0) {
            Text(this.subtitle)
              .fontSize(10 * AppTheme.UI_SCALE)
              .fontColor(AppTheme.TEXT_TERTIARY)
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
              .margin({ top: 2 * AppTheme.UI_SCALE })
          }
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)

        if (this.pill.length > 0) {
          StatusPill({ label: this.pill, tone: this.tone })
        }
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      if (this.value.length > 0) {
        Text(this.value)
          .fontSize(15 * AppTheme.UI_SCALE)
          .fontWeight(FontWeight.Medium)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .width('100%')
          .margin({ top: 12 * AppTheme.UI_SCALE })
      }
      if (this.note.length > 0) {
        Text(this.note)
          .fontSize(12 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .width('100%')
          .maxLines(3)
          .margin({ top: this.value.length > 0 ? 6 * AppTheme.UI_SCALE : 12 * AppTheme.UI_SCALE })
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding(16 * AppTheme.UI_SCALE)
    .backgroundColor(AppTheme.SURFACE)
    .borderRadius(AppTheme.RADIUS_LG)
    .border({ width: 1, color: AppTheme.BORDER })
  }
}

/** 权限开关行：图标 + 一句话 + 开关。说明文字交代「开了会发生什么」。 */
@Component
export struct ToggleRow {
  @Prop icon: string = '';
  @Prop label: string = '';
  @Prop note: string = '';
  @Prop checked: boolean = false;
  /** 正在写入时禁用，避免连点两次写出两个相反的值。 */
  @Prop busy: boolean = false;
  onToggle: (value: boolean) => void = () => {
  };

  build() {
    Row() {
      AppIcon({
        commands: this.icon,
        color: this.checked ? AppTheme.PRIMARY : AppTheme.TEXT_TERTIARY,
        filled: false,
        iconSize: 20 * AppTheme.UI_SCALE
      })
      Column() {
        Text(this.label)
          .fontSize(13 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.TEXT_PRIMARY)
        if (this.note.length > 0) {
          Text(this.note)
            .fontSize(11 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .margin({ top: 3 * AppTheme.UI_SCALE })
            .maxLines(2)
        }
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
      .margin({ left: 10 * AppTheme.UI_SCALE, right: 12 * AppTheme.UI_SCALE })

      Toggle({ type: ToggleType.Switch, isOn: this.checked })
        .selectedColor(AppTheme.PRIMARY)
        .enabled(!this.busy)
        .onChange((isOn: boolean) => {
          this.onToggle(isOn);
        })
    }
    .width('100%')
    .alignItems(VerticalAlign.Center)
    .padding({ top: 10 * AppTheme.UI_SCALE, bottom: 10 * AppTheme.UI_SCALE })
    .opacity(this.busy ? 0.6 : 1)
  }
}

/** 小操作按钮：图标 + 文字。tone 取 outline / primary / danger。 */
@Component
export struct ChipButton {
  @Prop icon: string = '';
  @Prop label: string = '';
  @Prop tone: string = 'outline';
  @Prop active: boolean = true;
  onTap: () => void = () => {
  };

  private textColor(): ResourceColor {
    if (!this.active) {
      return AppTheme.TEXT_TERTIARY;
    }
    if (this.tone === 'primary') {
      return Color.White;
    }
    if (this.tone === 'danger') {
      return AppTheme.DANGER;
    }
    return AppTheme.TEXT_PRIMARY;
  }

  build() {
    Row() {
      if (this.icon.length > 0) {
        AppIcon({
          commands: this.icon,
          color: this.textColor(),
          filled: false,
          iconSize: 16 * AppTheme.UI_SCALE
        })
          .margin({ right: 6 * AppTheme.UI_SCALE })
      }
      Text(this.label)
        .fontSize(13 * AppTheme.UI_SCALE)
        .fontColor(this.textColor())
    }
    .alignItems(VerticalAlign.Center)
    .padding({ left: 14 * AppTheme.UI_SCALE, right: 14 * AppTheme.UI_SCALE, top: 9 * AppTheme.UI_SCALE, bottom: 9 * AppTheme.UI_SCALE })
    .backgroundColor(this.tone === 'primary'
      ? AppTheme.PRIMARY
      : (this.tone === 'danger' ? AppTheme.DANGER_SOFT : AppTheme.SURFACE))
    .borderRadius(AppTheme.RADIUS_SM)
    .border({
      width: this.tone === 'outline' ? 1 : 0,
      color: AppTheme.BORDER
    })
    .opacity(this.active ? 1 : 0.5)
    .enabled(this.active)
    .onClick(() => {
      if (this.active) {
        this.onTap();
      }
    })
  }
}

/** 一行「标签 + 值」，值右侧可以带一个状态胶囊。 */
@Component
export struct InfoRow {
  @Prop label: string = '';
  @Prop value: string = '';
  @Prop mono: boolean = false;
  /** 值右侧的状态胶囊；留空则不画。 */
  @Prop pill: string = '';
  @Prop tone: string = 'muted';
  @Prop labelWidth: number = 132;

  build() {
    Row() {
      Text(this.label)
        .fontSize(13 * AppTheme.UI_SCALE)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .width(this.labelWidth)
      Text(this.value.length > 0 ? this.value : '—')
        .fontSize(this.mono ? 12 * AppTheme.UI_SCALE : 13 * AppTheme.UI_SCALE)
        .fontColor(AppTheme.TEXT_PRIMARY)
        .layoutWeight(1)
        .maxLines(2)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
      if (this.pill.length > 0) {
        StatusPill({ label: this.pill, tone: this.tone })
          .margin({ left: 8 * AppTheme.UI_SCALE })
      }
    }
    .width('100%')
    .alignItems(VerticalAlign.Center)
    .padding({ top: 9 * AppTheme.UI_SCALE, bottom: 9 * AppTheme.UI_SCALE })
  }
}
