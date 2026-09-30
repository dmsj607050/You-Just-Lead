/**
 * 全局视觉资源。
 *
 * 颜色通过系统资源解析：浅色值放在 base，深色值放在 dark；其余尺寸仍是固定设计值。
 * 页面只引用语义令牌，不自行判断系统主题。
 */
/**
 * 全局 UI 放大系数。
 *
 * 2026-09-30 按用户要求整体放大：**字号、间距、圆角、图标、侧栏宽度全部乘它**。
 * 端侧每个 `fontSize` / `width` / `height` / `padding` / `margin` / `space` / `iconSize`
 * 后面都写着 `* AppTheme.UI_SCALE`，所以想再大一点或小一点，只改这一个数。
 *
 * 它**不乘**这几种数：`layoutWeight` / `flexGrow`（比例，不是长度）、`maxLines`、
 * `border` 的描边宽度（发丝线，放大反而发虚）、断点阈值（那是"窗口有多宽"，
 * 跟界面放大无关）、以及 `CONTENT_MAX_WIDTH`（防超宽屏的上限）。
 */
const UI_SCALE: number = 1.3;

export default class AppTheme {
  /** 见文件头的 UI_SCALE。页面里直接用这个数乘字面量。 */
  static readonly UI_SCALE: number = UI_SCALE;

  /** 主色：用于主按钮、激活态、进度。 */
  static readonly PRIMARY = $r('app.color.primary');
  static readonly PRIMARY_DARK = $r('app.color.primary_dark');
  static readonly PRIMARY_SOFT = $r('app.color.primary_soft');
  static readonly PRIMARY_SOFT_ALT = $r('app.color.primary_soft_alt');

  /** 页面与卡片。 */
  static readonly PAGE_BG = $r('app.color.page_bg');
  static readonly SURFACE = $r('app.color.surface');
  static readonly BORDER = $r('app.color.border');
  static readonly BORDER_SOFT = $r('app.color.border_soft');

  /** 文字层级。 */
  static readonly TEXT_PRIMARY = $r('app.color.text_primary');
  static readonly TEXT_SECONDARY = $r('app.color.text_secondary');
  static readonly TEXT_TERTIARY = $r('app.color.text_tertiary');

  /** 状态色。 */
  static readonly DANGER = $r('app.color.danger');
  static readonly DANGER_SOFT = $r('app.color.danger_soft');
  static readonly WARN_TEXT = $r('app.color.warn_text');
  static readonly WARN_SOFT = $r('app.color.warn_soft');

  /** 侧栏悬停底色：比页面底色深一点点的一层浅灰绿，只在指针压上去时出现。 */
  static readonly NAV_HOVER = $r('app.color.nav_hover');

  /** 顶栏与侧栏尺寸。 */
  static readonly TOPBAR_HEIGHT: number = 56 * UI_SCALE;
  /**
   * 侧栏宽度。
   *
   * 2026-09-30 按用户要求加宽（原值 240，实际渲染 240 × 1.3 ≈ 312vp）：
   * 上一版是「图标栏 52 + 面板 146」两列，字体放大后两列都挤，一级导航只剩图标、
   * 二级只剩小字。现在改回**单列**：一级功能域是有图标有文字的整行（可展开），
   * 二级缩进排在它下面，所以宽度按一级那行重新定。
   */
  static readonly SIDEBAR_WIDTH: number = 240 * UI_SCALE;

  /**
   * 内容区最大宽度。宽屏下上限，普通 2in1 窗口内不生效，保持内容铺满。
   *
   * 2026-09-30 从 1440 提到 1800：模拟器那个 2in1 档位（3120×2080 @ density 304）
   * 的逻辑宽度约 **1642vp**，1440 的上限在它上面就生效了 —— 内容被截断在左边、右侧
   * 空出一条，看起来像"没铺满"。1800 高于常见 2in1 与笔记本窗口，所以日常不再触发；
   * 它现在只用来防超宽屏把卡片拉得过长。
   *
   * 注意：上限生效时内容是**左对齐**的（`Scroll` 直接子节点），要居中得给内容套一层
   * 居中的容器 —— 那是改动更大的一件事，暂不做。
   */
  static readonly CONTENT_MAX_WIDTH: number = 1800;

  /** 圆角。 */
  static readonly RADIUS_SM: number = 8 * UI_SCALE;
  static readonly RADIUS: number = 12 * UI_SCALE;
  static readonly RADIUS_LG: number = 16 * UI_SCALE;
}
