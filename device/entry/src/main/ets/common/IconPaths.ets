/**
 * 图标路径库。
 *
 * 全部使用直线指令绘制，坐标系与渲染尺寸一致（24 表示 24×24）。
 * 不依赖任何图片资源，避免缺资源导致图标不显示。
 */
export default class IconPaths {
  /** 文件夹：项目。 */
  static readonly FOLDER: string =
    'M3 7 L10 7 L12 10 L21 10 L21 19 L3 19 Z';

  /** 流程节点：工作流。 */
  static readonly FLOW: string =
    'M3 5 L11 5 L11 12 L3 12 Z M13 12 L21 12 L21 19 L13 19 Z M11 8.5 L13 8.5 M13 15.5 L11 15.5 M13 8.5 L13 15.5';

  /** 烧瓶：实验。 */
  static readonly FLASK: string =
    'M9 4 L9 9 L4 19 L20 19 L15 9 L15 4 M7 4 L17 4';

  /** 摊开的书：文献。 */
  static readonly BOOK: string =
    'M4 5 L11 7 L11 20 L4 18 Z M20 5 L13 7 L13 20 L20 18 Z';

  /** 柱状图：数据。 */
  static readonly CHART: string =
    'M4 20 L20 20 M7 20 L7 12 M12 20 L12 7 M17 20 L17 15';

  /** 笔：写作。 */
  static readonly PEN: string =
    'M4 20 L7 19 L19 7 L17 5 L5 17 Z M16 6 L18 8';

  /** 链条：溯源（每一环都扣在上一环上）。 */
  static readonly TRACE: string =
    'M9 5 L7 5 L4 8 L7 11 L9 11 M15 5 L17 5 L20 8 L17 11 L15 11 M4 8 L20 8 M9 19 L7 19 L4 16 L7 13 L9 13 M15 13 L17 13 L20 16 L17 19 L15 19 M4 16 L20 16';

  /** 滑杆：设置。 */
  static readonly SLIDERS: string =
    'M4 7 L20 7 M4 12 L20 12 M4 17 L20 17 M9 5 L9 9 M15 10 L15 14 M7 15 L7 19';

  /** 铃铛：通知。 */
  static readonly BELL: string =
    'M6 17 L6 11 L9 6 L15 6 L18 11 L18 17 Z M4 17 L20 17 M10 17 L10 20 L14 20 L14 17';

  /** 放大镜：搜索。 */
  static readonly SEARCH: string =
    'M7 4 L13 4 L16 7 L16 13 L13 16 L7 16 L4 13 L4 7 Z M16 16 L20 20';

  /** 加号。 */
  static readonly PLUS: string =
    'M12 5 L12 19 M5 12 L19 12';

  /** 小号加号，按 16 坐标系绘制。 */
  static readonly PLUS_SMALL: string =
    'M8 3.5 L8 12.5 M3.5 8 L12.5 8';

  /** 小号右尖角，按 16 坐标系绘制。 */
  static readonly CHEVRON_SMALL: string =
    'M6 3 L11 8 L6 13';

  /** 对勾。 */
  static readonly CHECK: string =
    'M5 12 L10 17 L19 7';

  /** 向右的尖角。 */
  static readonly CHEVRON: string =
    'M9 6 L15 12 L9 18';

  /** 网格视图。 */
  static readonly GRID: string =
    'M4 4 L10 4 L10 10 L4 10 Z M14 4 L20 4 L20 10 L14 10 Z M4 14 L10 14 L10 20 L4 20 Z M14 14 L20 14 L20 20 L14 20 Z';

  /** 列表视图。 */
  static readonly LIST: string =
    'M4 6 L20 6 M4 12 L20 12 M4 18 L20 18';

  /** 四角星：强调小标记，按 16 坐标系绘制。 */
  static readonly SPARK: string =
    'M8 2.5 L9.7 6.3 L13.5 8 L9.7 9.7 L8 13.5 L6.3 9.7 L2.5 8 L6.3 6.3 Z';

  /** 文档：事件与记录。 */
  static readonly DOC: string =
    'M6 3 L14 3 L18 7 L18 21 L6 21 Z M14 3 L14 7 L18 7 M9 12 L15 12 M9 16 L15 16';

  /** 地球：语言切换。十二边形逼近圆形，仍只用直线指令。 */
  static readonly GLOBE: string =
    'M12 3.5 L16.2 4.6 L19.4 7.8 L20.5 12 L19.4 16.2 L16.2 19.4 L12 20.5 L7.8 19.4 L4.6 16.2 ' +
    'L3.5 12 L4.6 7.8 L7.8 4.6 Z M3.5 12 L20.5 12 M8.4 6 L8.4 18 M15.6 6 L15.6 18';

  /** 链条：后端连接。 */
  static readonly LINK: string =
    'M9.5 8 L7.5 8 L5 10.5 L5 13.5 L7.5 16 L9.5 16 M14.5 8 L16.5 8 L19 10.5 L19 13.5 L16.5 16 ' +
    'L14.5 16 M8.5 12 L15.5 12';

  /** 门口箭头：退出应用。 */
  static readonly LOGOUT: string =
    'M13 4 L5 4 L5 20 L13 20 M10.5 12 L20 12 M17 9 L20 12 L17 15';

  /** 远山：横幅装饰，按 280×110 坐标系绘制。 */
  static readonly RIDGE_BACK: string =
    'M0 110 L52 44 L88 78 L136 24 L200 110 Z';

  /** 近山：横幅装饰，按 280×110 坐标系绘制。 */
  static readonly RIDGE_FRONT: string =
    'M36 110 L104 52 L172 110 Z';
}
