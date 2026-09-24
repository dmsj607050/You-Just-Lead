import IconPaths from './IconPaths';

/**
 * 视图层共享的类型与静态数据。
 *
 * 只放「不依赖后端返回值」的结构，后端返回的类型统一在 BackendClient 里定义。
 */

/** 侧栏导航项。文案不放在这里，由 `t('nav.' + key)` 取，切换语言时才会跟着变。 */
export interface NavItem {
  key: string;
  icon: string;
}

/** 工作流步骤。 */
export interface StepSpec {
  label: string;
  /** completed / active / pending */
  status: string;
}

/** 最近更新条目。只存后端原始值，翻译放到渲染时做，切换语言时才会跟着变。 */
export interface UpdateSpec {
  eventType: string;
  createdAt: string;
}

/** 侧栏主导航。项目本身是上一层容器，由顶栏的项目切换器承担，所以这里第一项是概览。 */
export const NAV_ITEMS: NavItem[] = [
  { key: 'overview', icon: IconPaths.GRID },
  { key: 'workflow', icon: IconPaths.FLOW },
  { key: 'experiment', icon: IconPaths.FLASK },
  { key: 'literature', icon: IconPaths.BOOK },
  { key: 'data', icon: IconPaths.CHART },
  { key: 'writing', icon: IconPaths.PEN },
  { key: 'trace', icon: IconPaths.TRACE }
];
