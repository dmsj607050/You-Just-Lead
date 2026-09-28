/* 渲染探针：把真实的 web/ 脚本加载起来，用真实数据渲染一遍。
 *
 * 为什么需要它：`node --check` 只证明语法对，`test_web_assets.py` 只证明端点对得上。
 * 但视图里一个没定义的变量（例如把界面里那份动作名表删掉、改成从契约取之后忘了改用法）
 * 语法完全合法，只在用户点开那一页时才炸成白屏。这个探针把那一步提前到测试里。
 *
 * 这里**不做任何改写**：加载的就是后端 serve 出去的那三个文件。改了就不是在测真实的界面。
 *
 * 两种模式：
 *
 *   node render_probe.js <契约.json> <快照.json>
 *     在线渲染：给一份契约与一份研究循环快照，把四段各渲染一遍。
 *
 *   node render_probe.js --offline <离线包目录>
 *     离线渲染：先加载离线包里的 snapshot.js，再加载同目录的三个脚本，跑一次 boot()，
 *     并统计"有没有碰过网络"。离线页的价值就在"不碰网络也能读出状态"这一条上。
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const webRoot = path.join(__dirname, '..', '..', 'web');
const OFFLINE_MODE = process.argv[2] === '--offline';
const bundleDir = OFFLINE_MODE ? process.argv[3] : webRoot;
const scriptRoot = OFFLINE_MODE ? bundleDir : webRoot;

// 浏览器的那几个全局。跟界面脚本的接触面越小越好，缺哪个补哪个。
global.window = global;
global.addEventListener = () => {};
global.document = { addEventListener: () => {}, getElementById: () => null, body: { innerHTML: '' } };
global.location = { hash: '', origin: 'http://127.0.0.1:8765' };
global.localStorage = { getItem: () => null, setItem: () => {} };
let networkCalls = 0;
global.fetch = () => {
  networkCalls += 1;
  return Promise.reject(new Error('the render probe must not touch the network'));
};

// 名字刻意不叫 `load`：app.js 里也有一个 `load`（取页数据），而它是在全局上下文里
// 声明的函数声明。同名的话，下面那个 `load('loop')` 会解析到本文件这个（模块作用域的）
// 读文件函数上，报一个跟界面毫无关系的 ENOENT。
function loadScript(file) {
  vm.runInThisContext(fs.readFileSync(file, 'utf8'), { filename: file });
}

if (OFFLINE_MODE) {
  // 顺序与离线页里 index.html 的顺序一致：快照必须在 app.js 之前。
  loadScript(path.join(bundleDir, 'snapshot.js'));
}
for (const name of ['ui.js', 'views.js', 'app.js']) {
  loadScript(path.join(scriptRoot, name));
}

function renderLoopSections(snapshot) {
  const rendered = {};
  for (const section of ['now', 'hypotheses', 'evidence', 'history']) {
    State.sections.loop = section;
    rendered[section] = Views.loop(snapshot);
  }
  return rendered;
}

if (!OFFLINE_MODE) {
  Contract.data = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  Contract.offline = false;
  const snapshot = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
  process.stdout.write(JSON.stringify(renderLoopSections(snapshot)));
} else {
  (async () => {
    // 走一次"从 hash 进来、再点开研究循环这一页"的真实路径：
    // boot() 会去取契约与当前页的数据，这两步在离线包里都必须由快照回答。
    window.location.hash = '#loop';
    await boot();
    const report = {
      network_calls: networkCalls,
      offline_flag: !!window.__OFFLINE_SNAPSHOT__,
      offline_generated_at: (window.__OFFLINE_SNAPSHOT__ || {}).generated_at || '',
      contract_actions: Contract.data ? Contract.data.actions.length : 0,
      contract_offline: Contract.offline,
      pages_loaded: Object.keys(State.data).sort(),
      loop_offline_at: State.offline.loop || '',
      banner: offlineBanner('loop'),
      loop_sections: renderLoopSections(State.data.loop),
    };
    process.stdout.write(JSON.stringify(report));
  })().catch((error) => {
    process.stderr.write(String(error && error.stack ? error.stack : error));
    process.exit(1);
  });
}
