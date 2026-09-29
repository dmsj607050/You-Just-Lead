/* You Just Lead — Windows 端主控。
 *
 * 三层：状态（这里）、视图（views.js 返回 HTML 字符串）、原子组件（ui.js）。
 * 没有框架也没有构建步骤：界面由后端自己 serve，双击 exe 就能用。
 *
 * 之所以不用前端框架，是因为这个界面要跟鸿蒙端逐屏对齐 —— 鸿蒙那边就是手写的
 * ArkUI 结构，这里照搬同一套"分段 + 一次渲染一段"的组织方式，比套一层组件库更直。
 */

/**
 * 离线快照。由 `app/offline_bundle.py` 生成：桌面外壳在后端不可达时打开的那份静态页
 * 会带上它，内容是「最后一次成功取到的响应」。
 *
 * 它只在离线页里存在。线上那份页面永远拿不到这个全局变量，所以下面的分支不影响正常运行。
 */
const OFFLINE = window.__OFFLINE_SNAPSHOT__ || null;

const API = {
  /**
   * 统一请求。敏感端点要带 X-YJL-Token：后端在回环模式下会忽略它，
   * 但绑定到局域网时它是唯一凭据，所以这里始终发送。
   */
  async request(path, options = {}) {
    if (OFFLINE) {
      // 离线页不打网络：它能回答的只有快照里存过的那几条。口径是"最后一次成功响应"，
      // 而不是"猜一个数据" —— 猜出来的状态会让人以为后端还活着。
      const saved = (OFFLINE.responses || {})[path];
      if (saved !== undefined && (options.method || 'GET') === 'GET') return saved;
      throw new Error('离线快照：这一页没有本地数据，或者这个操作需要后端在线');
    }
    const response = await fetch(path, {
      method: options.method || 'GET',
      headers: { 'Content-Type': 'application/json', 'X-YJL-Token': '' },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
    const text = await response.text();
    let payload = null;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch (error) {
        payload = { error: text };
      }
    }
    if (!response.ok) {
      const detail = (payload && (payload.error || payload.detail)) || `HTTP ${response.status}`;
      throw new Error(detail);
    }
    return payload;
  },
  get: (path) => API.request(path),
  post: (path, body) => API.request(path, { method: 'POST', body: body || {} }),
};

// ------------------------------------------------------------------ 科研契约

/**
 * 契约的持有者与查询器。
 *
 * **这里不抄任何动作名或核查项。** 之前界面自己写了一份中文对照表，和后端各改各的，
 * 迟早会出现"界面显示一个后端已经不存在的动作"。现在文案只从 `/api/research/contract` 取，
 * 后端那份定义在 `schemas/research.py`，是唯一来源。
 *
 * 契约没取到时查询器返回空串，视图会退回显示原始动作名 —— 显示英文总比显示空白好，
 * 也比编一个中文名出来好。
 */
const Contract = {
  data: null,
  //: 契约来自缓存而不是本次请求。离线时仍然要能显示中文名，所以这一位要标出来。
  offline: false,

  _entry(list, name) {
    const items = (Contract.data && Contract.data[list]) || [];
    return items.find((item) => item.name === name) || null;
  },
  actionLabel(name) {
    const entry = Contract._entry('actions', name);
    return entry ? entry.label : '';
  },
  action(name) {
    return Contract._entry('actions', name);
  },
  //: 核查项的界面顺序与正向问法，都由契约给出。
  checks() {
    return (Contract.data && Contract.data.checks) || [];
  },
  //: 判定值 / 状态 / 作业与步骤状态的色调。界面不按字符串猜颜色。
  toneOf(name) {
    for (const list of Contract.TONE_LISTS) {
      const entry = Contract._entry(list, name);
      if (entry) return entry.tone || 'muted';
    }
    return '';
  },
  verdictLabel(name) {
    const entry = Contract._entry('verdicts', name);
    return entry ? entry.label : '';
  },
  //: 假设 / 分支 / 作业 / 步骤状态的中文名。内部取值（active、applied）不该直接印给用户看。
  statusLabel(name) {
    for (const list of Contract.NAME_LISTS) {
      const entry = Contract._entry(list, name);
      if (entry && entry.label) return entry.label;
    }
    return '';
  },
};

/** 契约里"名字 → 中文名/色调"的几组清单。界面按这些清单查，不自己写名单。 */
Contract.NAME_LISTS = ['hypothesis_statuses', 'branch_statuses', 'job_statuses', 'step_statuses'];
Contract.TONE_LISTS = ['verdicts'].concat(Contract.NAME_LISTS);

// ------------------------------------------------------------------ 离线缓存

/**
 * `localStorage` 里的上一份成功结果。
 *
 * 鸿蒙端在端侧直接读工作区文件，后端断了也还能看（`LocalStatusPage.ets`）。Windows 端的
 * 界面跑在浏览器窗口里，读不到本机文件 —— 能对等做到的是**把上一份成功结果留下来**：
 * 后端不在时依然读得到"上次看到的状态"，并明确标出这是离线数据。
 *
 * 这不是把旧数据伪装成新的：界面上会写清同步时间，顶部也换成离线色。缓存损坏或写不进去
 * （隐私模式）都不该让界面起不来，所以读写一律吞掉异常。
 */
const CACHE_KEY = 'yjl.offline.v2';

function readCache() {
  try {
    const raw = window.localStorage.getItem(CACHE_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch (error) {
    return {};
  }
}

function writeCache(cache) {
  try {
    window.localStorage.setItem(CACHE_KEY, JSON.stringify(cache));
  } catch (error) {
    /* 存不下就算了：缓存是可用性手段，不是数据来源。 */
  }
}

/** 记下这一页刚取到的结果。只存成功的那一次 —— 失败不该覆盖好的缓存。 */
function rememberPage(key, data) {
  const cache = readCache();
  cache.pages = cache.pages || {};
  cache.pages[key] = { at: new Date().toISOString(), data: data };
  writeCache(cache);
}

function cachedPage(key) {
  const cache = readCache();
  const entry = cache.pages ? cache.pages[key] : null;
  return entry && entry.data !== undefined ? entry : null;
}

function rememberContract(data) {
  const cache = readCache();
  cache.contract = { at: new Date().toISOString(), data: data };
  writeCache(cache);
}

function cachedContract() {
  const cache = readCache();
  return cache.contract && cache.contract.data ? cache.contract : null;
}

/** 页面 → 取数函数。切换页面时按需拉，拉过的留在缓存里，点「刷新」才重取。 */
const LOADERS = {
  overview: async () => API.get('/api/dashboard'),
  workflow: async () => ({
    workflow: await API.get('/api/workflow'),
    actions: await API.get('/api/next-actions'),
    rules: await API.get('/api/rules/report'),
  }),
  experiment: async () => ({
    experiments: await API.get('/api/experiments'),
    jobs: await API.get('/api/experiments/jobs'),
    drafts: await API.get('/api/experiments/drafts'),
  }),
  literature: async () => API.get('/api/research'),
  data: async () => API.get('/api/data-audit'),
  writing: async () => API.get('/api/paper'),
  trace: async () => API.get('/api/trace'),
  reproduction: async () => API.get('/api/reproductions'),
  loop: async () => API.get('/api/research/loop'),
  settings: async () => ({
    health: await API.get('/health'),
    providers: await API.get('/api/settings/providers'),
    runtime: await API.get('/api/runtime/local'),
  }),
};

const State = {
  nav: 'overview',
  data: {},
  errors: {},
  loading: {},
  // 这一页的当前数据是不是从离线缓存来的；值是那次同步的时间。
  offline: {},
  // 「设置 → 模型」里正在编辑哪一套：'' 收起、'new' 新建、否则是那套的 id。
  providerForm: '',
  // 「设置 → 模型」里最后一次操作的结果（测试连接、保存、切换）。为空的形态是 {tone, text}。
  providerMessage: null,
  // 每页自己的分段选择。与端侧一样，一屏只渲染一段。
  sections: {
    overview: 'project',
    workflow: 'status',
    experiment: 'ledger',
    literature: 'query',
    data: 'source',
    writing: 'package',
    trace: 'rule',
    reproduction: 'plans',
    loop: 'now',
    settings: 'workspace',
  },
  // 各页的输入草稿：重渲染后要能原样回到输入框里。
  drafts: {},
  // 循环作业提交后的轮询句柄。
  polling: null,
};

const NAV_ITEMS = [
  { key: 'overview', label: '概览', icon: 'grid' },
  { key: 'workflow', label: '工作流', icon: 'flow' },
  { key: 'experiment', label: '实验', icon: 'flask' },
  { key: 'literature', label: '文献', icon: 'book' },
  { key: 'data', label: '数据', icon: 'chart' },
  { key: 'writing', label: '写作', icon: 'pen' },
  { key: 'trace', label: '溯源', icon: 'trace' },
  { key: 'reproduction', label: '复现', icon: 'box' },
  // 研究循环是本项目自己的东西，端侧列表里没有，但它才是这条流水线的引擎。
  { key: 'loop', label: '研究循环', icon: 'loop' },
];

function sidebarHtml() {
  const items = NAV_ITEMS.map((item) => {
    const active = item.key === State.nav ? ' active' : '';
    return (
      `<button class="nav-item${active}" data-action="nav" data-key="${item.key}">` +
      `${UI.icon(item.icon)}<span>${UI.esc(item.label)}</span></button>`
    );
  }).join('');
  const settingsActive = State.nav === 'settings' ? ' active' : '';
  return (
    items +
    '<div class="sidebar-divider"></div>' +
    `<button class="nav-item${settingsActive}" data-action="nav" data-key="settings">` +
    `${UI.icon('sliders')}<span>设置</span></button>` +
    '<div class="sidebar-quote">更好的问题<br/>会带来更好的世界</div>'
  );
}

const TOPBAR = `<div class="topbar">
  <div class="brand">
    <svg class="brand-mark" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
      <path d="M4 18 L12 4 L20 18 M7.5 13 L16.5 13"/>
    </svg>
    <span>You Just Lead</span>
  </div>
  <div class="topbar-spacer"></div>
  <span id="backend-state"></span>
</div>
<div class="topbar-divider"></div>`;

function renderBackendState() {
  const node = document.getElementById('backend-state');
  if (!node) return;
  // 后端不在时给出一个总是可见的答案。离线与"连不上"是两件事：离线是"有旧数据可看"，
  // 连不上是"什么都没有" —— 混成一种颜色会让人分不清要不要去启动后端。
  const offline = Object.values(State.offline).some(Boolean);
  const failed = !offline && Object.values(State.errors).some(Boolean);
  const checked = Object.keys(State.data).length > 0;
  const toneName = failed ? 'danger' : offline ? 'warn' : checked ? 'ok' : 'muted';
  const label = failed
    ? '后端未连接'
    : offline
      ? '离线：显示上次同步的数据'
      : checked
        ? '本地服务运行中'
        : '连接中';
  node.innerHTML = UI.Badge(label, toneName);
}

async function load(key, options = {}) {
  const loader = LOADERS[key];
  if (!loader) return;
  if (State.loading[key]) return;
  if (State.data[key] !== undefined && !options.force) return;

  State.loading[key] = true;
  State.errors[key] = '';
  render();
  try {
    State.data[key] = await loader();
    // 离线快照里取到的数据要标出来源时间，否则界面看起来跟在线一样。
    State.offline[key] = OFFLINE ? OFFLINE.generated_at : '';
    rememberPage(key, State.data[key]);
  } catch (error) {
    const cached = cachedPage(key);
    if (cached) {
      // 有上一份就显示它，并标清"这是什么时候的数据"。只读页面这样处理是安全的：
      // 写操作（推进一步、批准）不会走缓存，它们在后端不在时本来就该失败。
      State.data[key] = cached.data;
      State.offline[key] = cached.at;
      State.errors[key] = '';
    } else {
      State.errors[key] = error.message || String(error);
    }
  } finally {
    State.loading[key] = false;
    render();
  }
}

function currentView() {
  const loader = LOADERS[State.nav];
  if (!loader) return UI.Notice(`没有这一页：${State.nav}`, 'danger');

  const error = State.errors[State.nav];
  if (error) {
    return (
      UI.Notice(`取数据失败：${error}`, 'danger') +
      '<div class="page-loading">确认后端在运行（默认 127.0.0.1:8765），然后点右上角刷新。</div>'
    );
  }

  if (State.loading[State.nav] && State.data[State.nav] === undefined) {
    return '<div class="page-loading">正在读取…</div>';
  }

  const view = Views[State.nav];
  if (!view) return UI.Notice(`这一页还没实现：${State.nav}`, 'warn');
  const banner = offlineBanner(State.nav);
  return banner + view(State.data[State.nav]);
}

/** 离线提示条。说清三件事：这是离线、数据是什么时候的、写操作不会生效。 */
function offlineBanner(key) {
  const at = State.offline[key];
  if (!at) return '';
  const reason = OFFLINE
    ? '这是后端起不来时打开的静态快照'
    : '后端当前不可达，这里显示的是同步到本机的那一份';
  return UI.Notice(
    `离线模式：${reason}（${at}）。要推进循环或批准实验，先让后端跑起来。`,
    'warn'
  );
}

function render() {
  const content = document.getElementById('content');
  if (content) content.innerHTML = currentView();
  const sidebar = document.getElementById('sidebar');
  if (sidebar) sidebar.innerHTML = sidebarHtml();
  renderBackendState();
}

/** 用地址栏 hash 记住当前页：刷新不跳回概览，也方便直接打开某一页（比如 #loop）。 */
function navFromHash() {
  const key = (window.location.hash || '').replace(/^#/, '');
  const known = NAV_ITEMS.some((item) => item.key === key) || key === 'settings';
  return known ? key : 'overview';
}

// ------------------------------------------------------------------ 交互

/** 提交一次循环推进，然后轮询到它跑完为止。 */
async function stepLoop(maxSteps) {
  try {
    const job = await API.post('/api/research/loop/step', { max_steps: maxSteps });
    State.drafts.loopJob = job.job_id;
    render();
    pollLoop();
  } catch (error) {
    State.errors.loop = error.message || String(error);
    render();
  }
}

function pollLoop() {
  if (State.polling) clearTimeout(State.polling);
  State.polling = setTimeout(async () => {
    try {
      const snapshot = await API.get('/api/research/loop');
      State.data.loop = snapshot;
      State.errors.loop = '';
      if (snapshot.running) {
        State.drafts.loopRunning = snapshot.running;
        render();
        pollLoop();
        return;
      }
      State.drafts.loopRunning = '';
    } catch (error) {
      State.errors.loop = error.message || String(error);
    }
    render();
  }, 3000);
}

document.addEventListener('click', async (event) => {
  const target = event.target.closest('[data-action]');
  if (!target) return;
  const action = target.dataset.action;
  const key = target.dataset.key;

  if (action === 'nav') {
    State.nav = key;
    if (window.location.hash !== `#${key}`) window.location.hash = key;
    render();
    load(key);
    return;
  }
  if (action === 'section') {
    State.sections[State.nav] = key;
    render();
    return;
  }
  if (action === 'refresh') {
    State.data[State.nav] = undefined;
    await load(State.nav, { force: true });
    return;
  }
  if (action === 'loop-step') {
    if (OFFLINE) {
      State.errors.loop = '离线快照里不能推进循环：请先让后端跑起来。';
      render();
      return;
    }
    await stepLoop(Number(key) || 1);
    return;
  }
  if (action === 'loop-backfill') {
    if (OFFLINE) {
      State.errors.loop = '离线快照里不能回填：请先让后端跑起来。';
      render();
      return;
    }
    try {
      State.data.loop = await API.post('/api/research/loop/backfill', {});
      State.errors.loop = '';
    } catch (error) {
      State.errors.loop = error.message || String(error);
    }
    render();
    return;
  }

  const handler = Views[`on_${action}`];
  if (handler) handler(target, key);
});

document.addEventListener('input', (event) => {
  const field = event.target.closest('[data-draft]');
  if (field) State.drafts[field.dataset.draft] = field.value;
});

window.addEventListener('hashchange', () => {
  const key = navFromHash();
  if (key === State.nav) return;
  State.nav = key;
  render();
  load(key);
});

/** 取科研契约：先请求，失败就退回本机缓存的那一份。两份都没有时保持 null。 */
async function loadContract() {
  if (OFFLINE) {
    Contract.data = OFFLINE.contract || null;
    Contract.offline = true;
    return;
  }
  try {
    // 路径写字面量，不抽常量：`test_web_assets.py` 靠正则从 app.js 里提取端点，
    // 抽成常量会让这条防线静默失效。
    Contract.data = await API.get('/api/research/contract');
    Contract.offline = false;
    rememberContract(Contract.data);
  } catch (error) {
    const cached = cachedContract();
    if (cached) {
      // 离线时仍然显示中文名，而不是把动作名原样丢给用户猜。
      Contract.data = cached.data;
      Contract.offline = true;
    }
  }
}

async function boot() {
  State.nav = navFromHash();
  document.body.innerHTML = `<div class="app">${TOPBAR}<div class="body">
    <div class="sidebar" id="sidebar"></div>
    <div class="content" id="content"></div>
  </div></div>`;
  render();
  // 先取契约再取页面数据：视图渲染要用契约里的中文名与色调，
  // 反过来会出现"第一屏全是英文动作名，刷新一下又变中文"的抖动。
  await loadContract();
  render();
  await load(State.nav);
}

window.addEventListener('DOMContentLoaded', boot);
