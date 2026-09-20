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
  @Prop subtitle: string = '';
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
        if (this.subtitle.length > 0) {
          Text(this.subtitle)
            .fontSize(13)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .margin({ top: 8 })
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

/** 白色卡片容器，可带标题与说明。 */
@Component
export struct CardPanel {
  @Prop title: string = '';
  @Prop subtitle: string = '';
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
          if (this.subtitle.length > 0) {
            Text(this.subtitle)
              .fontSize(12)
              .fontColor(AppTheme.TEXT_TERTIARY)
              .margin({ top: 6 })
          }
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
