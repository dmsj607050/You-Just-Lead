/**
 * 全局视觉常量。
 *
 * 与设计稿保持一致：浅灰绿底、白色卡片、绿色主色。
 * 调整外观只改这里，页面代码不需要动。
 */
export default class AppTheme {
  /** 主色：用于主按钮、激活态、进度。 */
  static readonly PRIMARY: string = '#12805C';
  static readonly PRIMARY_DARK: string = '#0E6A4C';
  static readonly PRIMARY_SOFT: string = '#E8F5EE';
  static readonly PRIMARY_SOFT_ALT: string = '#F1F8F4';

  /** 页面与卡片。 */
  static readonly PAGE_BG: string = '#F6F8F7';
  static readonly SURFACE: string = '#FFFFFF';
  static readonly BORDER: string = '#E8ECEA';
  static readonly BORDER_SOFT: string = '#F0F3F1';

  /** 文字层级。 */
  static readonly TEXT_PRIMARY: string = '#1A1F1C';
  static readonly TEXT_SECONDARY: string = '#5C6660';
  static readonly TEXT_TERTIARY: string = '#9AA5A0';

  /** 状态色。 */
  static readonly DANGER: string = '#C0392B';
  static readonly DANGER_SOFT: string = '#FDF1EF';
  static readonly WARN_TEXT: string = '#B25E09';
  static readonly WARN_SOFT: string = '#FFF3E4';

  /** 顶栏与侧栏尺寸。 */
  static readonly TOPBAR_HEIGHT: number = 64;
  static readonly SIDEBAR_WIDTH: number = 232;

  /** 内容区最大宽度。宽屏下上限，普通 2in1 窗口内不生效，保持内容铺满。 */
  static readonly CONTENT_MAX_WIDTH: number = 1440;

  /** 圆角。 */
  static readonly RADIUS_SM: number = 8;
  static readonly RADIUS: number = 12;
  static readonly RADIUS_LG: number = 16;
}
