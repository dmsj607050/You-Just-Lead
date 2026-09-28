/* You Just Lead — Windows 端 UI 原子组件。
 *
 * 与 `Widgets.ets` 一一对应：同名组件、同样的参数语义、同样的色调映射。
 * 全部返回 HTML 字符串，交互靠 `data-action` 属性 + 事件委托（见 app.js），
 * 这样不需要任何构建工具，也不会因为重渲染而丢事件绑定。
 */

const ICONS = {
  // 与 IconPaths.ets 同一条路径数据，保证两个端的图标是同一个形状。
  grid: 'M4 4 L10 4 L10 10 L4 10 Z M14 4 L20 4 L20 10 L14 10 Z M4 14 L10 14 L10 20 L4 20 Z M14 14 L20 14 L20 20 L14 20 Z',
  flow: 'M3 5 L11 5 L11 12 L3 12 Z M13 12 L21 12 L21 19 L13 19 Z M11 8.5 L13 8.5 M13 15.5 L11 15.5 M13 8.5 L13 15.5',
  flask: 'M9 4 L9 9 L4 19 L20 19 L15 9 L15 4 M7 4 L17 4',
  book: 'M4 5 L11 7 L11 20 L4 18 Z M20 5 L13 7 L13 20 L20 18 Z',
  chart: 'M4 20 L20 20 M7 20 L7 12 M12 20 L12 7 M17 20 L17 15',
  pen: 'M4 20 L7 19 L19 7 L17 5 L5 17 Z M16 6 L18 8',
  trace:
    'M9 5 L7 5 L4 8 L7 11 L9 11 M15 5 L17 5 L20 8 L17 11 L15 11 M4 8 L20 8 M9 19 L7 19 L4 16 L7 13 L9 13 M15 13 L17 13 L20 16 L17 19 L15 19 M4 16 L20 16',
  box: 'M4 7 L12 3 L20 7 L20 17 L12 21 L4 17 Z M4 7 L12 11 L20 7 M12 11 L12 21',
  sliders: 'M4 7 L20 7 M4 12 L20 12 M4 17 L20 17 M9 5 L9 9 M15 10 L15 14 M7 15 L7 19',
  // 循环：八边形逼近的圆环。刻意只用直线指令 —— 与鸿蒙端 `IconPaths.LOOP` 是同一串路径，
  // 两个端的这一项图标必须长得一样。
  loop: 'M19 12 L16.95 16.95 L12 19 L7.05 16.95 L5 12 L7.05 7.05 L12 5 L16.95 7.05 Z',
  check: 'M5 12 L10 17 L19 7',
};

function icon(name, size = 18) {
  const path = ICONS[name] || ICONS.grid;
  return (
    `<svg class="nav-icon" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" ` +
    `stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">` +
    `<path d="${path}"/></svg>`
  );
}

/** 一律走转义。工作区里的路径、模型输出、论文标题都会进到界面里。 */
function esc(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const TONES = ['ok', 'warn', 'danger', 'muted'];

function tone(value, fallback = 'muted') {
  return TONES.includes(value) ? value : fallback;
}

// ---------------------------------------------------------------- 原子组件

function PageHeader(title, status, options = {}) {
  const statusLine = status ? `<div class="page-status">${esc(status)}</div>` : '';
  const refresh = options.hideRefresh
    ? ''
    : `<button class="page-refresh" data-action="${esc(options.refreshAction || 'refresh')}">刷新</button>`;
  return (
    '<div class="page-header">' +
    `<div class="page-header-main"><div class="page-title">${esc(title)}</div>${statusLine}</div>` +
    refresh +
    '</div>'
  );
}

/** 白色卡片。`weight` 不需要：并排时用 `.card-row` 包住即可（flex 会平分）。 */
function Card(title, content, options = {}) {
  const head = title ? `<div class="card-title">${esc(title)}</div>` : '';
  const extra = options.className ? ` ${esc(options.className)}` : '';
  return `<div class="card${extra}">${head}${content}</div>`;
}

function CardRow(cards) {
  return `<div class="card-row">${cards.join('')}</div>`;
}

function KeyValueRow(label, value, options = {}) {
  const shown = value === null || value === undefined || value === '' ? '—' : value;
  const empty = shown === '—' ? ' empty' : '';
  const mono = options.mono ? ' mono' : '';
  return (
    '<div class="kv-row">' +
    `<div class="kv-label">${esc(label)}</div>` +
    `<div class="kv-value${mono}${empty}">${options.raw ? shown : esc(shown)}</div>` +
    '</div>'
  );
}

function Badge(text, toneName = 'muted') {
  return `<span class="badge ${tone(toneName)}">${esc(text)}</span>`;
}

function EmptyHint(text) {
  return `<div class="empty-hint">${esc(text)}</div>`;
}

/**
 * 分段导航。左侧色点表达的是「这条链通不通」（ok/warn/danger/muted），
 * 不是数量 —— 与端侧一致，别把它当成进度指示。
 */
function Rail(items, active, action = 'section') {
  const html = items
    .map((item) => {
      const cls = item.key === active ? ' active' : '';
      const dot = item.tone ? `<span class="rail-dot ${tone(item.tone)}"></span>` : '';
      return (
        `<button class="rail-item${cls}" data-action="${esc(action)}" data-key="${esc(item.key)}">` +
        `${dot}${esc(item.label)}</button>`
      );
    })
    .join('');
  return `<div class="rail">${html}</div>`;
}

/** 单条记录的二选一（调研/舍弃这类）。与 Rail 语义不同，别混用。 */
function Chips(items, active, options = {}) {
  const action = options.action || 'chip';
  const disabled = options.disabled ? ' disabled' : '';
  const html = items
    .map((item) => {
      const cls = item.key === active ? ` active tone-${tone(item.tone, 'muted')}` : '';
      return (
        `<button class="chip${cls}"${disabled} data-action="${esc(action)}" ` +
        `data-key="${esc(item.key)}"${item.extra ? ` data-extra="${esc(item.extra)}"` : ''}>${esc(item.label)}</button>`
      );
    })
    .join('');
  return `<div class="chips">${html}</div>`;
}

/** 归一按本组最大值，有值的条最少给 3%（避免「1」和「0」看起来一样）。 */
function BarList(items, toneName = 'primary') {
  if (!items || !items.length) return EmptyHint('暂无数据');
  const max = Math.max(...items.map((item) => Number(item.value) || 0), 0);
  const html = items
    .map((item) => {
      const value = Number(item.value) || 0;
      const percent = max > 0 ? Math.max(value > 0 ? 3 : 0, Math.round((value / max) * 100)) : 0;
      const text = item.valueText !== undefined ? item.valueText : String(value);
      return (
        '<div>' +
        `<div class="bar-head"><div class="bar-label">${esc(item.label)}</div>` +
        `<div class="bar-value">${esc(text)}</div></div>` +
        `<div class="bar-track"><div class="bar-fill ${tone(toneName, 'primary')}" style="width:${percent}%"></div></div>` +
        '</div>'
      );
    })
    .join('');
  return `<div class="bars">${html}</div>`;
}

function ProgressBar(label, current, total, toneName = '') {
  const safeTotal = Number(total) || 0;
  const safeCurrent = Number(current) || 0;
  const ratio = safeTotal > 0 ? safeCurrent / safeTotal : 0;
  const percent = Math.max(safeCurrent > 0 ? 3 : 0, Math.min(100, Math.round(ratio * 100)));
  // 留空自动：达成用主色，未达成用提示色 —— 与端侧同一规则。
  const resolved = toneName || (safeTotal > 0 && safeCurrent >= safeTotal ? 'primary' : 'warn');
  const css = resolved === 'primary' ? '' : resolved;
  return (
    '<div>' +
    `<div class="bar-head"><div class="bar-label">${esc(label)}</div>` +
    `<div class="bar-value">${esc(safeCurrent)}/${esc(safeTotal)}</div></div>` +
    `<div class="bar-track"><div class="bar-fill ${css}" style="width:${percent}%"></div></div>` +
    '</div>'
  );
}

function Notice(text, toneName = '') {
  const cls = toneName ? ` ${esc(toneName)}` : '';
  return `<div class="notice${cls}">${esc(text)}</div>`;
}

function MonoBlock(text) {
  return `<div class="mono-block">${esc(text)}</div>`;
}

function Stepper(steps, activeIndex) {
  const parts = [];
  steps.forEach((label, index) => {
    if (index < activeIndex) {
      parts.push(`<div class="step-done">${icon('check', 14)}</div>`);
    } else if (index === activeIndex) {
      parts.push(`<div class="step-active"><span class="dot"></span>${esc(label)}</div>`);
    } else {
      parts.push('<div class="step-idle"><span class="dot"></span></div>');
    }
    if (index < steps.length - 1) parts.push('<div class="step-line"></div>');
  });
  return `<div class="stepper">${parts.join('')}</div>`;
}

window.UI = {
  ICONS,
  BarList,
  Badge,
  Card,
  CardRow,
  Chips,
  EmptyHint,
  KeyValueRow,
  MonoBlock,
  Notice,
  PageHeader,
  ProgressBar,
  Rail,
  Stepper,
  esc,
  icon,
  tone,
};
