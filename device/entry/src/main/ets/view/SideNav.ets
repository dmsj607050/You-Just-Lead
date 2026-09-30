import AppTheme from '../common/AppTheme';
import IconPaths from '../common/IconPaths';
import { tFor } from '../common/I18n';
import { NavGroupSpec, NavItem, NAV_GROUPS, groupOfNavItem, navItemsOf } from '../common/ViewTypes';
import { AppIcon } from './AppIcon';

/**
 * 侧栏：**一列两层的导航**。
 *
 * 一级是「工作区 / 研究 / 产出」三个功能域，每行是「图标 + 名称 + 右侧展开箭头」，
 * 点一行展开或收起；二级是该域下的页面，缩进排在它下面。设置也是一级入口，固定在底部。
 *
 * 2026-09-30 从「图标栏 + 面板」两列改回单列：那一版一级只剩图标、二级只剩小字，
 * 整体偏轻偏挤。现在一级是完整的导航行（图标 20、字 16、行高 44），
 * 二级比它小一级（图标 16、字 15、行高 40），层级靠**字号 + 缩进 + 底色**区分。
 *
 * 导航项只有「图标 + 名称」：不放副标题、不放说明文字。解释属于页面内部、空状态或
 * 首次引导，导航本身只回答「去哪里」。
 */

/** 二级缩进：二级的图标落在功能域的名字下面，一眼看出从属关系。 */
const CHILD_INDENT: number = 40;
/** 一级（功能域与设置）的左内边距。 */
const ROOT_INDENT: number = 12;

/**
 * 侧栏里的一行。
 *
 * 一级与二级共用同一个实现，差别只有三个：字号、缩进、右侧有没有箭头。
 * 拆成两个组件会让选中态、悬停态、角标各写两遍，改一处忘一处。
 */
@Component
struct NavRow {
  @Prop icon: string = '';
  @Prop label: string = '';
  /** 当前页面：浅品牌色底 + 品牌色文字。 */
  @Prop active: boolean = false;
  /** 当前页落在这个功能域里：收起时也能看出「你在这」。 */
  @Prop current: boolean = false;
  /** 大于 0 时在右侧显示角标（工作流上的阻塞项数）。 */
  @Prop badge: number = 0;
  /** 一级行（功能域、设置）比二级行大一号。 */
  @Prop primary: boolean = false;
  /** 有子项的行才画箭头。 */
  @Prop expandable: boolean = false;
  @Prop expanded: boolean = false;
  /** 左侧缩进，设计值（乘 UI_SCALE）。 */
  @Prop indent: number = CHILD_INDENT;
  onTap: () => void = () => {
  };
  /** 指针压上去，用于极浅的悬停底色。 */
  @State hovered: boolean = false;

  build() {
    Row() {
      AppIcon({
        commands: this.icon,
        color: this.active || this.current
          ? AppTheme.PRIMARY
          : (this.primary ? AppTheme.TEXT_SECONDARY : AppTheme.TEXT_TERTIARY),
        filled: false,
        iconSize: (this.primary ? 20 : 16) * AppTheme.UI_SCALE
      })
      Text(this.label)
        .fontSize((this.primary ? 16 : 15) * AppTheme.UI_SCALE)
        .fontWeight(this.primary || this.active ? FontWeight.Medium : FontWeight.Normal)
        .fontColor(this.active || this.current
          ? AppTheme.PRIMARY_DARK
          : (this.primary ? AppTheme.TEXT_PRIMARY : AppTheme.TEXT_SECONDARY))
        .margin({ left: (this.primary ? 10 : 9) * AppTheme.UI_SCALE })
        .layoutWeight(1)
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })

      if (this.badge > 0) {
        Text(`${this.badge}`)
          .fontSize(11 * AppTheme.UI_SCALE)
          .fontColor(Color.White)
          .backgroundColor(AppTheme.DANGER)
          .borderRadius(9 * AppTheme.UI_SCALE)
          .padding({
            left: 6 * AppTheme.UI_SCALE,
            right: 6 * AppTheme.UI_SCALE,
            top: 1 * AppTheme.UI_SCALE,
            bottom: 1 * AppTheme.UI_SCALE
          })
      }

      // 箭头放最右：收起朝右、展开朝下，方向本身就说明点下去会怎样。
      if (this.expandable) {
        AppIcon({
          commands: IconPaths.CHEVRON_SMALL,
          color: AppTheme.TEXT_TERTIARY,
          filled: false,
          iconSize: 14 * AppTheme.UI_SCALE
        })
          .margin({ left: 8 * AppTheme.UI_SCALE })
          .rotate({ angle: this.expanded ? 90 : 0 })
      }
    }
    .width('100%')
    .height((this.primary ? 44 : 40) * AppTheme.UI_SCALE)
    .padding({
      left: this.indent * AppTheme.UI_SCALE,
      right: (this.expandable ? 14 : 12) * AppTheme.UI_SCALE
    })
    .borderRadius(AppTheme.RADIUS_SM)
    .margin({ bottom: (this.primary ? 8 : 2) * AppTheme.UI_SCALE })
    // 展开着的域用极浅品牌色，当前页用稍深一档的同色系 —— 两层都亮，但亮得不一样。
    .backgroundColor(this.active
      ? AppTheme.PRIMARY_SOFT
      : ((this.expandable && this.expanded) ? AppTheme.PRIMARY_SOFT_ALT
        : (this.hovered ? AppTheme.NAV_HOVER : Color.Transparent)))
    .onHover((isHover: boolean) => {
      this.hovered = isHover;
    })
    .onClick(() => {
      this.onTap();
    })
  }
}

/** 一列两层的侧栏导航。 */
@Component
export struct SideNav {
  /**
   * 当前语言。ArkUI 只重建读到状态变量的节点，所以本组件所有文案都走 this.tr()，
   * 由它读一次 this.lang，等于把用到的节点登记到语言变化上。
   */
  @StorageLink('lang') lang: string = 'zh';

  /** 当前页面。 */
  @Prop activeKey: string = 'overview';
  /** 展开着的功能域；空串＝三个都收起。同一时刻最多展开一个。 */
  @Prop openGroup: string = 'workspace';
  /** 阻塞项数量，大于 0 时在工作流那一行上显示角标。 */
  @Prop blockerCount: number = 0;
  /** 点一级行：展开它、收起别的。 */
  onToggleGroup: (key: string) => void = () => {
  };
  /** 点二级行或设置：切页。 */
  onSelect: (key: string) => void = () => {
  };

  /** 取文案：读一次 lang，让调用它的节点订阅语言变化。 */
  private tr(key: string): string {
    return tFor(this.lang, key);
  }

  build() {
    Column() {
      // 功能域列表：条目少的时候不滚，多了才滚。设置不在这里，它固定在下面。
      Scroll() {
        Column() {
          ForEach(NAV_GROUPS, (group: NavGroupSpec) => {
            NavRow({
              icon: group.icon,
              label: this.tr(`nav.group.${group.key}`),
              current: groupOfNavItem(this.activeKey) === group.key,
              primary: true,
              expandable: true,
              expanded: this.openGroup === group.key,
              indent: ROOT_INDENT,
              onTap: () => {
                this.onToggleGroup(group.key);
              }
            })

            // 展开态**必须进 key**：ArkUI 不会因为 @Builder 里读到的状态变了就重建子树，
            // 展开/收起要真的把二级那几行建出来或拆掉，就得让这一项重建。
            if (this.openGroup === group.key) {
              ForEach(navItemsOf(group.key), (item: NavItem) => {
                NavRow({
                  icon: item.icon,
                  label: this.tr(`nav.${item.key}`),
                  active: this.activeKey === item.key,
                  badge: item.key === 'workflow' ? this.blockerCount : 0,
                  indent: CHILD_INDENT,
                  onTap: () => {
                    this.onSelect(item.key);
                  }
                })
              }, (item: NavItem) => `${item.key}-${this.openGroup}`)
            }
          }, (group: NavGroupSpec) => `${group.key}-${this.openGroup === group.key}`)
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
      }
      .layoutWeight(1)
      .align(Alignment.Top)
      .scrollBar(BarState.Off)

      Divider()
        .color(AppTheme.BORDER)
        .margin({ bottom: 10 * AppTheme.UI_SCALE })

      // 设置是一级入口（不展开，所以没有箭头），放在最下面。
      NavRow({
        icon: IconPaths.SLIDERS,
        label: this.tr('nav.settings'),
        active: this.activeKey === 'settings',
        primary: true,
        indent: ROOT_INDENT,
        onTap: () => {
          this.onSelect('settings');
        }
      })
    }
    .width(AppTheme.SIDEBAR_WIDTH)
    .height('100%')
    .padding({
      left: 10 * AppTheme.UI_SCALE,
      right: 10 * AppTheme.UI_SCALE,
      top: 12 * AppTheme.UI_SCALE,
      bottom: 12 * AppTheme.UI_SCALE
    })
    .backgroundColor(AppTheme.PAGE_BG)
    .alignItems(HorizontalAlign.Start)
    .border({ width: { right: 1 }, color: AppTheme.BORDER })
  }
}
