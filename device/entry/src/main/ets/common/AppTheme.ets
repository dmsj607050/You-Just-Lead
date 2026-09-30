/**
 * 全局视觉资源。
 *
 * 颜色通过系统资源解析：浅色值放在 base，深色值放在 dark；其余尺寸仍是固定设计值。
 * 页面只引用语义令牌，不自行判断系统主题。
 */
export default class AppTheme {
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

  /** 顶栏与侧栏尺寸。 */
  static readonly TOPBAR_HEIGHT: number = 56;
  static readonly SIDEBAR_WIDTH: number = 198;

  /** 内容区最大宽度。宽屏下上限，普通 2in1 窗口内不生效，保持内容铺满。 */
  static readonly CONTENT_MAX_WIDTH: number = 1440;

  /** 圆角。 */
  static readonly RADIUS_SM: number = 8;
  static readonly RADIUS: number = 12;
  static readonly RADIUS_LG: number = 16;
}
