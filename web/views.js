/* You Just Lead — Windows 端页面。
 *
 * 沿用鸿蒙端的组织方式：每页「标题 + 一行现状 + 分段导航 + 一次只渲染一段」。
 * 每个函数接收该页的取数结果，返回 HTML 字符串；交互通过 `Views.on_<action>` 注册。
 *
 * 对结构还没完全对上的端点，这里用 `kvCard` 做通用渲染而不是硬猜字段名 ——
 * 猜错的字段名会让界面显示一片空白，那比少显示几项更糟。
 */

const Views = {};

// ------------------------------------------------------------------ 小工具

function text(value) {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function count(value, suffix) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  return `${number}${suffix || ''}`;
}

/** 通用键值卡：给结构还不固定的端点用。 */
function kvCard(title, payload, skip) {
  if (!payload || typeof payload !== 'object') return UI.Card(title, UI.EmptyHint('暂无数据'));
  const ignored = new Set(skip || []);
  const rows = Object.entries(payload)
    .filter(([key, value]) => !ignored.has(key) && typeof value !== 'object')
    .map(([key, value]) => UI.KeyValueRow(key, text(value)));
  const listRows = Object.entries(payload)
    .filter(([key, value]) => !ignored.has(key) && Array.isArray(value) && value.length)
    .map(([key, value]) => UI.KeyValueRow(key, `${value.length} 项`, { mono: true }));
  const body = rows.concat(listRows).join('') || UI.EmptyHint('暂无数据');
  return UI.Card(title, body);
}

function badgeToneForState(value) {
  const raw = String(value || '').toLowerCase();
  // 科研对象的色调由契约给出（后端定义、界面不猜）。剩下的运行态（训练作业、草案、
  // 溯源链）不属于科研契约，留在本地这张表里。
  const declared = Contract.toneOf(raw);
  if (declared) return declared;
  if (['completed', 'ok', 'ready', 'approved'].includes(raw)) return 'ok';
  if (['failed', 'error', 'danger', 'blocked'].includes(raw)) return 'danger';
  if (['running', 'queued', 'pending', 'awaiting_human_approval', 'warn'].includes(raw)) return 'warn';
  return 'muted';
}

/** 动作的中文名。定义在后端契约里（`schemas/research.py`），界面不抄第二份。 */
function actionLabel(name) {
  return Contract.actionLabel(name) || name || '';
}

/** 判定值的中文名。同样来自契约 —— 加一个新判定时界面自动就有了名字。 */
function verdictLabel(name) {
  return Contract.verdictLabel(name) || name || '';
}

/** 假设 / 分支状态的中文名。内部取值（active / killed）不该直接印给用户看。 */
function statusLabel(name) {
  return Contract.statusLabel(name) || name || '';
}

function traceExperimentStatus(name) {
  const labels = {
    planned: '计划中',
    queued: '排队中',
    running: '运行中',
    awaiting_human_approval: '等待人工批准',
    completed: '已完成',
    failed: '失败',
  };
  return labels[name] || text(name);
}

function traceApprovalSummary(approval) {
  if (!approval || typeof approval !== 'object') return '审批记录缺失';
  if (approval.recorded) {
    return `审批已核验 · ${text(approval.approved_at)}`;
  }
  const reasons = {
    missing_config_digest: '缺少配置指纹',
    invalid_config_digest: '配置指纹格式无效',
    missing: '未找到记录',
    unreadable: '记录无法读取',
    wrong_type: '记录类型不匹配',
    digest_mismatch: '配置指纹不匹配',
    incomplete: '记录信息不完整',
  };
  return `审批未核验 · ${reasons[approval.verification] || '原因未知'}`;
}

// ------------------------------------------------------------------ 概览

const STAGE_LABELS = {
  rules_capture: '采集规则',
  rules_review: '复核规则',
  data_audit: '数据审计',
  baseline_design: '基线设计',
  evidence_led_iteration: '证据驱动的迭代',
};

Views.overview = function (data) {
  if (!data) return '';
  const competition = data.competition || {};
  const summary = data.summary || {};
  const readiness = competition.rule_readiness || {};
  const workflow = data.workflow || {};
  const gaps = readiness.gaps || [];

  const status =
    `${STAGE_LABELS[workflow.stage] || workflow.stage || '未知阶段'} · ` +
    `数据 ${count(summary.data_files)} 个文件（${count(summary.data_issues)} 处问题） · ` +
    `研究记录 ${count(summary.research_records)} · ` +
    `已完成实验 ${count(summary.completed_experiments)}`;

  const railItems = [
    { key: 'project', label: '项目', tone: readiness.ready ? 'ok' : gaps.length ? 'danger' : 'warn' },
    { key: 'workflow', label: '工作流', tone: (workflow.blockers || []).length ? 'warn' : 'ok' },
    { key: 'capabilities', label: '能力', tone: (data.capabilities && data.capabilities.runners || []).length ? 'ok' : 'muted' },
    { key: 'recent', label: '最近更新', tone: (data.recent_events || []).length ? 'ok' : 'muted' },
  ];

  const section = State.sections.overview;
  let body = '';

  if (section === 'project') {
    const rows = [
      UI.KeyValueRow('竞赛', competition.name),
      UI.KeyValueRow('任务类型', competition.task_type, { mono: true }),
      UI.KeyValueRow('主指标', competition.metric),
      UI.KeyValueRow('适配器', competition.preferred_runner, { mono: true }),
      UI.KeyValueRow('需要人工确认', competition.requires_human_confirmation ? '是' : '否'),
      UI.KeyValueRow('最后更新', workflow.stage ? (STAGE_LABELS[workflow.stage] || workflow.stage) : null),
    ].join('');
    const total = (readiness.required_fields || []).length;
    const missing = gaps.length;
    const progress = UI.ProgressBar('规则字段完成度', total - missing, total);
    const blockers = (workflow.blockers || []).length
      ? `<div class="kv-row"><div class="kv-label">阻塞项</div><div class="kv-value">` +
        (workflow.blockers || []).map((item) => UI.Badge(item, 'warn')).join(' ') +
        '</div></div>'
      : '';
    body = UI.Card('项目', rows + progress + blockers);
  } else if (section === 'workflow') {
    const actions = (data.next_actions || []);
    const first = actions[0];
    const head = first
      ? `<div class="action-box"><div class="action-name">${UI.esc(text(first.action || first.title))}</div>` +
        `<div class="action-reason">${UI.esc(text(first.reason || first.detail))}</div></div>`
      : UI.EmptyHint('暂无建议动作');
    const steps = ['规则', '数据', '基线', '实验', '证据', '论文', '提交', '发布'];
    const index = Object.keys(STAGE_LABELS).indexOf(workflow.stage);
    body = UI.Card('下一步', head + '<div style="margin-top:16px">' + UI.Stepper(steps, Math.max(0, index)) + '</div>');
  } else if (section === 'capabilities') {
    const runners = (data.capabilities && data.capabilities.runners) || [];
    body = UI.Card(
      '内置能力',
      runners.length
        ? runners
            .map((item) => {
              const name = typeof item === 'string' ? item : item.name || item.runner || JSON.stringify(item);
              const detail = typeof item === 'object' && item.description ? `<div class="list-sub">${UI.esc(item.description)}</div>` : '';
              return `<div class="list-row"><div class="list-main"><div class="list-title">${UI.esc(name)}</div>${detail}</div></div>`;
            })
            .join('')
        : UI.EmptyHint('暂无适配器')
    );
  } else {
    const events = data.recent_events || [];
    body = UI.Card(
      '最近更新',
      events.length
        ? events
            .map((item) => {
              const title = item.event_type || item.type || '事件';
              const when = item.created_at || item.at || '';
              const detail = item.payload ? JSON.stringify(item.payload).slice(0, 200) : '';
              return (
                '<div class="list-row"><div class="list-main">' +
                `<div class="list-title">${UI.esc(title)}</div>` +
                `<div class="list-sub">${UI.esc(when)}${detail ? ' · ' + UI.esc(detail) : ''}</div>` +
                '</div></div>'
              );
            })
            .join('')
        : UI.EmptyHint('暂无记录')
    );
  }

  return (
    UI.PageHeader('概览', status) +
    UI.Rail(railItems, section) +
    body
  );
};

// ------------------------------------------------------------------ 研究循环

Views.loop = function (data) {
  if (!data) return '';
  const summary = data.summary || {};
  const hyp = summary.hypotheses || {};
  const exp = summary.experiments || {};
  const branches = summary.branches || {};
  const prediction = data.next_action || {};
  const running = data.running;

  const undesignable = exp.undesignable || [];
  const status =
    `假设 ${count(hyp.total)}（可证伪 ${count(hyp.falsifiable)}） · ` +
    `实验 ${count(exp.total)} · ` +
    `分支 ${count((branches.active || []).length)}/${count(branches.total)} 活跃 · ` +
    `证据 ${count((data.evidence || []).length)}` +
    // 空设计单独说：它们不会跑，所以既不算"待核查"，也不算"在推进"。
    (undesignable.length ? ` · 其中 ${count(undesignable.length)} 个设计跑不起来` : '');

  // 「当前」这条的颜色表达的是"还有没有下一步"：编排器认为没事可做了就是绿的。
  // 哪些动作算结束由契约说了算，界面不自己认字符串。
  const predicted = Contract.action(prediction.action) || {};
  const railItems = [
    { key: 'now', label: '当前', tone: predicted.terminal ? 'ok' : 'warn' },
    { key: 'hypotheses', label: '假设', tone: (hyp.falsifiable || 0) > 0 ? 'ok' : 'danger' },
    { key: 'evidence', label: '证据', tone: (data.evidence || []).length ? 'ok' : 'muted' },
    { key: 'history', label: '决策轨迹', tone: (data.decisions || []).length ? 'ok' : 'muted' },
  ];

  // 循环是"跑起来才存在"的东西，所以操作区放在最显眼的位置，而不是藏在设置里。
  const controls =
    '<div class="action-box">' +
    `<div class="action-name">${UI.esc(actionLabel(prediction.action) || '未知')}</div>` +
    `<div class="action-reason">${UI.esc(text(prediction.reason))}</div>` +
    `<div style="margin-top:14px;display:flex;gap:10px;align-items:center">` +
    (running
      ? `<button class="btn" disabled>推进中（${UI.esc(running)}）</button>`
      : '<button class="btn" data-action="loop-step" data-key="1">推进一步</button>' +
        '<button class="btn ghost" data-action="loop-step" data-key="3">连推三步</button>') +
    '<button class="btn ghost" data-action="loop-backfill">重新回填实验记录</button>' +
    '</div>' +
    '<div class="meta-line">每一步都会真调模型：先由编排器决定做什么，再交给执行器带工具去做。' +
    '要动算力的动作（跑训练、复现）不会被自动触发，它们会停在这里等人批准。</div>' +
    '</div>';

  const section = State.sections.loop;
  let body = '';

  if (section === 'now') {
    const metrics = [
      ['all', hyp.total, '假设总数'],
      ['all', hyp.falsifiable, '可被实验判决'],
      ['all', exp.total, '实验总数'],
      // 「跑完没核查」与「跑不起来的空设计」分开数：前者是欠着的活，后者是走不通的路。
      ['all', (exp.awaiting_evidence || []).length, '跑完没核查'],
      ['all', (exp.undesignable || []).length, '设计跑不起来'],
    ]
      .map(
        ([, value, label]) =>
          `<div class="loop-metric"><div class="num">${UI.esc(count(value))}</div>` +
          `<div class="label">${UI.esc(label)}</div></div>`
      )
      .join('');
    const jobs = (data.jobs || [])
      .map((job) => {
        const steps = (job.steps || [])
          .map(
            (step, index) =>
              '<div class="timeline-item">' +
              `<div class="timeline-index">${index + 1}</div>` +
              '<div class="timeline-body">' +
              `<div class="timeline-action">${UI.esc(actionLabel(step.decision && step.decision.action))} ` +
              `<span class="badge ${badgeToneForState(step.status)}">${UI.esc(statusLabel(step.status))}</span></div>` +
              `<div class="timeline-detail">${UI.esc(step.detail)}</div>` +
              '</div></div>'
          )
          .join('');
        const head =
          `${UI.Badge(statusLabel(job.status), badgeToneForState(job.status))} ` +
          `<span class="meta-line">${UI.esc(job.job_id)} · 最多 ${UI.esc(count(job.max_steps))} 步` +
          (job.stopped_because ? ` · 停止于「${UI.esc(job.stopped_because)}」` : '') +
          (job.error ? ` · ${UI.esc(job.error)}` : '') +
          '</span>';
        const pending = (job.pending_approvals || []).length
          ? UI.Notice(
              `等待人工批准：${(job.pending_approvals || []).map((item) => actionLabel(item)).join('、')} —— 它们没被执行，但也没挡住其他路线。`,
              'warn'
            )
          : '';
        return head + pending + (steps || UI.EmptyHint('这一步还没记录'));
      })
      .join('<div class="sidebar-divider"></div>');
    body =
      `<div class="loop-hero">${metrics}</div>` +
      controls +
      UI.Card('最近的推进', jobs || UI.EmptyHint('还没有推进过。点「推进一步」让循环开始。'));
  } else if (section === 'hypotheses') {
    const hypotheses = data.hypotheses || [];
    // 哪条假设上挂着"跑不起来"的设计。模型写下那段理由不容易，别只留在作业日志里；
    // 更早的记录里没有这段理由（那时还没记它），所以也要给出没有理由时的说法，
    // 否则页面上会出现"有 3 个跑不起来"却哪里都不解释的情况。
    const undesignableIds = exp.undesignable || [];
    const blocked = {};
    (data.experiments || []).forEach((item) => {
      if (undesignableIds.indexOf(item.experiment_id) < 0) return;
      blocked[item.hypothesis_id] =
        item.blocked || '没有对照也没有配置（生成它时还没有记下原因）';
    });
    body = UI.Card(
      '假设池',
      hypotheses.length
        ? hypotheses
            .map((item) => {
              // 可证伪的判据由后端给出（`Hypothesis.is_falsifiable()`），界面不自己再实现一遍。
              const falsifiable = item.falsifiable === true;
              const killed = item.status === 'killed';
              const predictions = (item.predictions || []).map((line) => `<li>${UI.esc(line)}</li>`).join('');
              const falsifiers = (item.falsifiers || []).map((line) => `<li>${UI.esc(line)}</li>`).join('');
              const rationale = (item.rationale || []).map((line) => `<li>${UI.esc(line)}</li>`).join('');
              const blocker = blocked[item.hypothesis_id]
                ? UI.Notice(`这次设计跑不起来：${blocked[item.hypothesis_id]}`, 'warn')
                : '';
              return (
                `<div class="hypothesis-card${killed ? ' killed' : ''}">` +
                '<div class="hypothesis-head">' +
                `<div class="hypothesis-id">${UI.esc(item.hypothesis_id)}</div>` +
                `<div class="hypothesis-statement">${UI.esc(item.statement)}</div>` +
                UI.Badge(statusLabel(item.status), badgeToneForState(item.status)) +
                (falsifiable ? '' : UI.Badge('不可证伪', 'warn')) +
                '</div>' +
                (predictions ? `<div class="meta-line">预测</div><ul class="sub-list">${predictions}</ul>` : '') +
                (falsifiers ? `<div class="meta-line">什么结果会否定它</div><ul class="sub-list">${falsifiers}</ul>` : '') +
                (rationale ? `<div class="meta-line">依据</div><ul class="sub-list">${rationale}</ul>` : '') +
                blocker +
                (!predictions && !falsifiers
                  ? '<div class="meta-line">既没有预测也没有反证条件 —— 编排器会先要求把它补成可判决的，补不动就终止这条路线。</div>'
                  : '') +
                '</div>'
              );
            })
            .join('')
        : UI.EmptyHint('还没有假设。循环会先检索文献，再据此提出假设。')
    );
  } else if (section === 'evidence') {
    const evidence = data.evidence || [];
    // 核查项的名称与顺序来自契约（`GET /api/research/contract`），取值由后端成对发出
    // （`checks: [{name, value}]`）—— 界面两边都不自己抄。
    const titles = {};
    Contract.checks().forEach((item) => {
      titles[item.name] = item.title;
    });
    body = UI.Card(
      '证据核查',
      evidence.length
        ? evidence
            .map((item) => {
              const rows = (item.checks || [])
                .map((check) => {
                  const value = check.value;
                  // 三态：true / false / null。null 是「没人查过」，不能显示成「不合格」。
                  const tone = value === true ? 'ok' : value === false ? 'danger' : 'muted';
                  const shown = value === true ? '是' : value === false ? '否' : '未核查';
                  const label = titles[check.name] || check.name;
                  return `<div class="kv-row"><div class="kv-label">${UI.esc(label)}</div><div class="kv-value">${UI.Badge(shown, tone)}</div></div>`;
                })
                .join('');
              return (
                `<div class="hypothesis-card">` +
                `<div class="hypothesis-head"><div class="hypothesis-id">${UI.esc(item.experiment_id)}</div>` +
                `<div class="hypothesis-statement">${UI.esc(verdictLabel(item.verdict))}</div>` +
                UI.Badge(verdictLabel(item.verdict), badgeToneForState(item.verdict)) +
                '</div>' + rows +
                (item.notes ? `<div class="meta-line">${UI.esc(item.notes)}</div>` : '') +
                '</div>'
              );
            })
            .join('')
        : UI.EmptyHint('还没有核查过任何实验。')
    );
  } else {
    const decisions = (data.decisions || []).slice().reverse();
    body = UI.Card(
      '决策轨迹',
      decisions.length
        ? decisions
            .map(
              (item, index) =>
                '<div class="timeline-item">' +
                `<div class="timeline-index">${decisions.length - index}</div>` +
                '<div class="timeline-body">' +
                `<div class="timeline-action">${UI.esc(actionLabel(item.action))} ` +
                `<span class="meta-line">${UI.esc(text(item.target_id))}</span></div>` +
                `<div class="timeline-detail">${UI.esc(text(item.reason))}</div>` +
                '</div></div>'
            )
            .join('')
        : UI.EmptyHint('这个工作区还没有推进过循环。')
    );
  }

  return UI.PageHeader('研究循环', status) + UI.Rail(railItems, section) + body;
};

// ------------------------------------------------------------------ 其余页面

Views.workflow = function (data) {
  if (!data) return '';
  const workflow = (data.workflow) || {};
  const actions = (data.actions && data.actions.actions) || [];
  const sections = [
    { key: 'status', label: '现状', tone: (workflow.blockers || []).length ? 'warn' : 'ok' },
    { key: 'blockers', label: '阻塞项', tone: (workflow.blockers || []).length ? 'danger' : 'ok' },
    { key: 'actions', label: '建议动作', tone: actions.length ? 'ok' : 'muted' },
  ];
  const section = State.sections.workflow;
  const status = `${STAGE_LABELS[workflow.stage] || workflow.stage || '—'} · 已完成实验 ${count(workflow.completed_experiments)}`;

  let body = '';
  if (section === 'status') {
    const components = workflow.components || {};
    const rows = ['rules', 'data_audit', 'research', 'baseline', 'approvals']
      .map((key) => {
        const value = components[key];
        const tone = value === true ? 'ok' : value === false ? 'danger' : 'muted';
        return `<div class="kv-row"><div class="kv-label">${UI.esc(key)}</div><div class="kv-value">${UI.Badge(yesNo(value), tone)}</div></div>`;
      })
      .join('');
    body = UI.Card(
      '工作流现状',
      rows +
        UI.KeyValueRow('自动执行', workflow.automatic_execution ? '开启' : '关闭（高风险动作由人批准）') +
        UI.KeyValueRow('推荐适配器', workflow.recommended_runner, { mono: true })
    );
  } else if (section === 'blockers') {
    const blockers = workflow.blockers || [];
    body = UI.Card('阻塞项', blockers.length ? blockers.map((item, index) => `<div class="timeline-item"><div class="timeline-index">${index + 1}</div><div class="timeline-body"><div class="timeline-detail">${UI.esc(text(item))}</div></div></div>`).join('') : UI.EmptyHint('当前没有阻塞项'));
  } else {
    body = UI.Card(
      '建议动作',
      actions.length
        ? actions
            .map(
              (item) =>
                '<div class="list-row"><div class="list-main">' +
                `<div class="list-title">${UI.esc(text(item.action || item.title || item))}</div>` +
                `<div class="list-sub">${UI.esc(text(item.reason || item.detail || item.evidence))}</div>` +
                '</div>' +
                (item.priority ? `<div class="list-side">${UI.Badge(item.priority, badgeToneForState(item.priority))}</div>` : '') +
                '</div>'
            )
            .join('')
        : UI.EmptyHint('暂无建议动作')
    );
    body += kvCard('规则报告', data.rules, ['markdown']);
  }
  return UI.PageHeader('工作流', status) + UI.Rail(sections, section) + body;
};

function yesNo(value) {
  if (value === true) return '就绪';
  if (value === false) return '未就绪';
  return '未知';
}

Views.experiment = function (data) {
  if (!data) return '';
  const experiments = (data.experiments && data.experiments.experiments) || [];
  const jobs = (data.jobs && data.jobs.jobs) || [];
  const drafts = (data.drafts && data.drafts.drafts) || [];
  const sections = [
    { key: 'ledger', label: '实验台账', tone: experiments.length ? 'ok' : 'muted' },
    { key: 'jobs', label: '训练作业', tone: jobs.some((job) => job.status === 'running') ? 'warn' : 'muted' },
    { key: 'drafts', label: '待批草案', tone: drafts.length ? 'warn' : 'ok' },
  ];
  const section = State.sections.experiment;
  const status = `在册 ${count(experiments.length)} 个实验 · 作业 ${count(jobs.length)} 个 · 待批草案 ${count(drafts.length)}`;

  const sectionBody = {
    ledger: () =>
      UI.Card(
        '实验台账',
        experiments.length
          ? experiments
              .map((item) => {
                const id = item.id || item.experiment_id;
                return (
                  '<div class="list-row"><div class="list-main">' +
                  `<div class="list-title">${UI.esc(id)} · ${UI.esc(text(item.change_type)) || '—'}</div>` +
                  `<div class="list-sub">${UI.esc(text(item.hypothesis))}</div>` +
                  '</div><div class="list-side">' +
                  UI.Badge(text(item.status), badgeToneForState(item.status)) +
                  `<div class="list-sub">${UI.esc(text(item.validation_metric))}</div>` +
                  '</div></div>'
                );
              })
              .join('')
          : UI.EmptyHint('还没有实验记录')
      ),
    jobs: () =>
      UI.Card(
        '训练作业',
        jobs.length
          ? jobs
              .map(
                (item) =>
                  '<div class="list-row"><div class="list-main">' +
                  `<div class="list-title">${UI.esc(text(item.job_id || item.id))}</div>` +
                  `<div class="list-sub">${UI.esc(text(item.config_path))} · ${UI.esc(text(item.submitted_at))}</div>` +
                  (item.error ? `<div class="list-sub">${UI.esc(text(item.error))}</div>` : '') +
                  '</div><div class="list-side">' + UI.Badge(text(item.status), badgeToneForState(item.status)) + '</div></div>'
              )
              .join('')
          : UI.EmptyHint('还没有训练作业')
      ),
    drafts: () =>
      UI.Card(
        '待批草案',
        drafts.length
          ? drafts
              .map(
                (item) =>
                  '<div class="list-row"><div class="list-main">' +
                  `<div class="list-title">${UI.esc(text(item.draft_id || item.id))}</div>` +
                  `<div class="list-sub">${UI.esc(text(item.hypothesis))}</div>` +
                  '</div><div class="list-side">' + UI.Badge(text(item.status), badgeToneForState(item.status)) + '</div></div>'
              )
              .join('')
          : UI.EmptyHint('没有待批准的草案')
      ),
  };

  return UI.PageHeader('实验', status) + UI.Rail(sections, section) + (sectionBody[section] || (() => ''))();
};

Views.literature = function (data) {
  if (!data) return '';
  const records = data.records || [];
  const counts = data.counts || {};
  const sections = [
    { key: 'query', label: '检索条件', tone: data.query ? 'ok' : 'muted' },
    { key: 'records', label: '候选', tone: records.length ? 'ok' : 'muted' },
  ];
  const section = State.sections.literature;
  const status = `检索式「${text(data.query)}」 · 候选 ${count(records.length)} 条 · 已调研 ${count(counts.investigate)} · 已舍弃 ${count(counts.discard)}`;

  let body = '';
  if (section === 'query') {
    const sources = (data.sources || []).map((item) => UI.Badge(item, 'ok')).join(' ');
    const failures = Object.entries(data.provider_failures || {});
    body =
      UI.Card(
        '检索',
        UI.KeyValueRow('检索式', data.query, { mono: true }) +
          UI.KeyValueRow('检索时间', data.searched_at) +
          `<div class="kv-row"><div class="kv-label">数据源</div><div class="kv-value">${sources || '—'}</div></div>`
      ) +
      (failures.length
        ? UI.Notice(failures.map(([name, reason]) => `${name}：${reason}`).join('；'), 'warn')
        : '');
  } else {
    body = UI.Card(
      '候选文献',
      records.length
        ? records
            .map((item) => {
              const parts = item.relevance_parts || {};
              const detail = ['terms', 'task', 'code', 'recency']
                .filter((key) => parts[key] !== null && parts[key] !== undefined)
                .map((key) => `${key} ${Number(parts[key]).toFixed(2)}`)
                .join(' · ');
              return (
                '<div class="list-row"><div class="list-main">' +
                `<div class="list-title">${UI.esc(text(item.title))}</div>` +
                `<div class="list-sub">${UI.esc(text(item.paper_id))} · ${UI.esc(text(item.year))} · ${UI.esc(text(item.source))}</div>` +
                `<div class="list-sub">相关度 ${UI.esc(Number(item.relevance || 0).toFixed(3))}${detail ? '（' + UI.esc(detail) + '）' : ''}</div>` +
                '</div><div class="list-side">' +
                UI.Badge(text(item.decision), badgeToneForState(item.decision)) +
                '</div></div>'
              );
            })
            .join('')
        : UI.EmptyHint('还没有候选。先在「检索条件」里发起一次检索。')
    );
  }
  return UI.PageHeader('文献', status) + UI.Rail(sections, section) + body;
};

Views.data = function (data) {
  if (!data) return '';
  const sections = [
    { key: 'source', label: '数据源', tone: data.data_dir ? 'ok' : 'muted' },
    { key: 'images', label: '图像', tone: (data.images && data.images.count) ? 'ok' : 'muted' },
    { key: 'kinds', label: '文件类型', tone: Object.keys(data.file_kinds || {}).length ? 'ok' : 'muted' },
    { key: 'issues', label: '问题', tone: (data.exact_duplicate_groups || []).length ? 'warn' : 'ok' },
  ];
  const section = State.sections.data;
  const status = `数据目录 ${text(data.data_dir)} · 文件 ${count(data.file_count)} 个 · 问题 ${count((data.exact_duplicate_groups || []).length)} 处`;

  let body = '';
  if (section === 'source') {
    body = UI.Card(
      '数据源',
      UI.KeyValueRow('数据目录', data.data_dir, { mono: true }) +
        UI.KeyValueRow('审计时间', data.audited_at) +
        UI.KeyValueRow('清单哈希', data.manifest_hash, { mono: true }) +
        UI.KeyValueRow('结构版本', data.layout_version, { mono: true })
    );
  } else if (section === 'images') {
    const images = data.images || {};
    const channels = images.channels || {};
    const bars = Object.entries(channels).map(([label, value]) => ({ label, value, valueText: String(value) }));
    body = UI.Card(
      '图像统计',
      UI.KeyValueRow('图像数', text(images.count)) +
        (bars.length ? `<div class="meta-line">通道分布</div>${UI.BarList(bars)}` : '')
    );
  } else if (section === 'kinds') {
    const kinds = Object.entries(data.file_kinds || {}).map(([label, value]) => ({ label, value, valueText: String(value) }));
    const splits = Object.entries(data.splits || {}).map(([label, value]) => ({ label, value, valueText: String(value) }));
    body = UI.CardRow([
      UI.Card('文件类型', kinds.length ? UI.BarList(kinds) : UI.EmptyHint('暂无')),
      UI.Card('数据划分', splits.length ? UI.BarList(splits) : UI.EmptyHint('暂无')),
    ]);
  } else {
    const groups = data.exact_duplicate_groups || [];
    body = UI.Card(
      '问题',
      groups.length
        ? groups
            .map((group, index) => `<div class="list-row"><div class="list-main"><div class="list-title">重复组 ${index + 1}</div><div class="list-sub">${UI.esc((group || []).join('  ·  '))}</div></div></div>`)
            .join('')
        : UI.EmptyHint('没有发现精确重复')
    );
  }
  return UI.PageHeader('数据', status) + UI.Rail(sections, section) + body;
};

Views.writing = function (data) {
  if (!data) return '';
  const status = `生成于 ${text(data.generated_at)} · 包目录 ${text(data.package_dir)}`;
  return (
    UI.PageHeader('写作', status) +
    kvCard('论文包', data, ['submission']) +
    kvCard('提交合约', data.submission)
  );
};

Views.trace = function (data) {
  if (!data) return '';
  const rule = data.rule || {};
  const experimentChain = data.experiments || {};
  const experiments = Array.isArray(experimentChain.experiments) ? experimentChain.experiments : [];
  const researchChain = data.research || {};
  const researchRecords = Array.isArray(researchChain.records) ? researchChain.records : [];
  const sections = [
    { key: 'rule', label: '规则链', tone: rule.ready ? 'ok' : 'danger' },
    { key: 'data', label: '数据链', tone: data.data ? 'ok' : 'muted' },
    { key: 'experiment', label: '实验链', tone: experiments.length ? 'ok' : 'muted' },
    { key: 'research', label: '研究链', tone: researchRecords.length ? 'ok' : 'muted' },
    { key: 'paper', label: '论文链', tone: data.paper ? 'ok' : 'muted' },
  ];
  const section = State.sections.trace;
  const status = `生成于 ${text(data.generated_at)} · 工作区 ${text(data.workspace)}`;

  let body = '';
  if (section === 'rule') {
    const gaps = rule.gaps || [];
    body = UI.Card(
      '规则链',
      UI.KeyValueRow('就绪', rule.ready ? '是' : '否') +
        UI.KeyValueRow('档案', rule.profile) +
        UI.KeyValueRow('缺口', rule.gap_count === undefined ? (gaps.length ? `${gaps.length} 项` : '—') : (rule.gap_count ? `${rule.gap_count} 项` : '无')) +
        (gaps.length ? `<ul class="sub-list">${gaps.map((item) => `<li>${UI.esc(text(item.field || item))}</li>`).join('')}</ul>` : '')
    );
  } else if (section === 'data') {
    body = kvCard('数据链', data.data);
  } else if (section === 'experiment') {
    body = UI.Card(
      '实验链',
      experiments.length
        ? experiments
            .map(
              (item) => {
                const statusSummary = item.status_consistent === false
                  ? `结果 ${traceExperimentStatus(item.result_status)} · 清单 ${traceExperimentStatus(item.manifest_status)}`
                  : traceExperimentStatus(item.status);
                const approval = item.approval || {};
                const approvalNote = approval.recorded && approval.note
                  ? `<details class="trace-approval-note"><summary>查看批准备注</summary><div>${UI.esc(text(approval.note))}</div></details>`
                  : '';
                return '<div class="list-row"><div class="list-main">' +
                `<div class="list-title">${UI.esc(text(item.experiment_id || item.id))}</div>` +
                `<div class="list-sub">${UI.esc(statusSummary)} · ${UI.esc(text(item.result_path))}</div>` +
                `<div class="list-sub">${UI.esc(traceApprovalSummary(approval))}</div>${approvalNote}` +
                '</div></div>';
              })
            .join('')
        : UI.EmptyHint('还没有实验')
    );
  } else if (section === 'research') {
    body = UI.Card(
      '研究链',
      researchRecords.length
        ? researchRecords
            .slice(0, 8)
            .map((item) => `<div class="list-row"><div class="list-main"><div class="list-title">${UI.esc(text(item.title || item.paper_id))}</div><div class="list-sub">${UI.esc(text(item.source))} · ${UI.esc(text(item.year))}</div></div></div>`)
            .join('')
        : UI.EmptyHint('还没有研究记录')
    );
  } else {
    body = kvCard('论文链', data.paper);
  }
  return UI.PageHeader('溯源', status) + UI.Rail(sections, section) + body;
};

Views.reproduction = function (data) {
  if (!data) return '';
  const plans = data.plans || [];
  const runs = data.runs || [];
  const docker = data.docker || {};
  const sections = [
    { key: 'plans', label: '复现计划', tone: plans.length ? 'ok' : 'muted' },
    { key: 'runs', label: '运行记录', tone: runs.length ? 'ok' : 'muted' },
  ];
  const section = State.sections.reproduction;
  const status = `计划 ${count(plans.length)} 个 · 运行 ${count(runs.length)} 次 · Docker ${docker.available ? '可用' : '不可用'}`;

  const banner = docker.available
    ? ''
    : UI.Notice(`容器执行不可用：${text(docker.reason)}。计划仍可生成，但跑不了。`, 'warn');

  const body =
    section === 'plans'
      ? UI.Card(
          '复现计划',
          plans.length
            ? plans
                .map(
                  (item) =>
                    '<div class="list-row"><div class="list-main">' +
                    `<div class="list-title">${UI.esc(text(item.plan_id))}</div>` +
                    `<div class="list-sub">${UI.esc(text(item.repository))}</div>` +
                    `<div class="list-sub">commit ${UI.esc(text(item.commit))} · 镜像 ${UI.esc(text(item.image))}</div>` +
                    '</div><div class="list-side">' + UI.Badge(text(item.status), badgeToneForState(item.status)) + '</div></div>'
                )
                .join('')
            : UI.EmptyHint('还没有复现计划')
        )
      : UI.Card(
          '运行记录',
          runs.length
            ? runs
                .map((item) => {
                  const phases = (item.phases || [])
                    .map((phase) => `<div class="list-sub">${UI.esc(text(phase.name))} · ${UI.esc(text(phase.exit_code))} · ${UI.esc(text(phase.duration_seconds))}s</div>`)
                    .join('');
                  return (
                    '<div class="list-row"><div class="list-main">' +
                    `<div class="list-title">${UI.esc(text(item.run_id))}</div>` +
                    `<div class="list-sub">${UI.esc(text(item.command))}</div>` + phases +
                    '</div><div class="list-side">' + UI.Badge(text(item.status), badgeToneForState(item.status)) + '</div></div>'
                  );
                })
                .join('')
            : UI.EmptyHint('还没有运行记录')
        );

  return UI.PageHeader('复现', status) + banner + UI.Rail(sections, section) + body;
};

Views.settings = function (data) {
  if (!data) return '';
  const health = data.health || {};
  const models = data.providers || {};
  const runtime = data.runtime || {};
  const sections = [
    { key: 'workspace', label: '工作区', tone: health.workspace ? 'ok' : 'warn' },
    { key: 'backend', label: '后端', tone: health.status === 'ok' ? 'ok' : 'danger' },
    { key: 'model', label: '模型', tone: models.configured ? 'ok' : 'warn' },
    { key: 'runtime', label: '运行时', tone: 'muted' },
  ];
  const section = State.sections.settings;
  const status = `后端 ${text(health.status)} · 工作区 ${text(health.workspace)}`;

  const bodies = {
    workspace: () => UI.Card('工作区', UI.KeyValueRow('路径', health.workspace, { mono: true })),
    backend: () =>
      UI.Card(
        '后端',
        UI.KeyValueRow('服务地址', window.location.origin, { mono: true }) +
          UI.KeyValueRow('健康状态', health.status) +
          UI.KeyValueRow('工作区', health.workspace, { mono: true })
      ),
    model: () => Views._modelSection(data.providers || {}),
    runtime: () =>
      UI.Card(
        '运行时',
        UI.KeyValueRow('平台', runtime.platform) +
          UI.KeyValueRow('Python', runtime.python) +
          UI.KeyValueRow('GPU', (runtime.gpus || []).length ? `${(runtime.gpus || []).length} 块` : '无')
      ),
  };
  return UI.PageHeader('设置', status) + UI.Rail(sections, section) + (bodies[section] || (() => ''))();
};

/**
 * 「设置 → 模型」：模型来源可以同时存多套，选一套当前使用。
 *
 * 「来源」是任意 **OpenAI 兼容**服务，DeepSeek 只是预设之一 —— 所以这里没有
 * "某家供应商"的专门代码，换一家就是换个地址。
 *
 * 预设清单来自后端 `GET /api/settings/providers`，**界面不自己抄一份**：
 * 后端加一家、界面自动出现。这和科研契约是同一条原则（见 docs/architecture.md D9）。
 */
Views._modelSection = function (models) {
  const providers = models.providers || [];
  const presets = models.presets || [];
  const active = providers.find((item) => item.id === models.active) || null;

  const keyText = (item) => {
    if (item.has_key) return '密钥已存';
    return item.key_required ? '密钥未填' : '不需要密钥';
  };

  const currentCard = UI.Card(
    '当前使用',
    active
      ? UI.KeyValueRow('名称', active.name) +
        UI.KeyValueRow('模型', active.model, { mono: true }) +
        UI.KeyValueRow('服务地址', active.base_url, { mono: true }) +
        UI.KeyValueRow('密钥', keyText(active)) +
        UI.KeyValueRow('密钥来源', models.key_source || '—') +
        '<div class="btn-row spaced"><button class="btn ghost" data-action="provider-test" data-key="' +
        UI.esc(active.id) +
        '">测试连接</button></div>'
      : UI.Notice(
          '还没有配置任何模型来源。从下面的预设里挑一家，填一次就能用了；之后想换别家，再添一套。',
          'warn'
        )
  );

  const rows = providers
    .map((item) => {
      const badge = item.id === models.active ? ' ' + UI.Badge('使用中', 'ok') : '';
      const actions =
        (item.id === models.active
          ? ''
          : '<button class="btn ghost" data-action="provider-activate" data-key="' + UI.esc(item.id) + '">设为当前</button>') +
        '<button class="btn ghost" data-action="provider-test" data-key="' + UI.esc(item.id) + '">测试</button>' +
        '<button class="btn ghost" data-action="provider-edit" data-key="' + UI.esc(item.id) + '">编辑</button>' +
        '<button class="btn ghost" data-action="provider-delete" data-key="' + UI.esc(item.id) + '">删除</button>';
      return (
        '<div class="list-row">' +
        '<div class="list-main">' +
        '<div class="list-title">' +
        UI.esc(item.name) +
        badge +
        '</div>' +
        '<div class="list-sub">' +
        UI.esc(item.model || '（没有模型名）') +
        ' · ' +
        UI.esc(item.base_url) +
        ' · ' +
        keyText(item) +
        (item.docs_url ? ' · ' + UI.esc(item.docs_url) : '') +
        '</div>' +
        '</div>' +
        '<div class="list-side btn-row">' +
        actions +
        '</div>' +
        '</div>'
      );
    })
    .join('');

  const listCard = UI.Card(
    '所有来源',
    (rows || UI.EmptyHint('还没有任何来源。')) +
      '<div class="btn-row spaced"><button class="btn" data-action="provider-new">新增来源</button></div>'
  );

  const message = State.providerMessage;
  const messageCard = message && message.text ? UI.Notice(message.text, message.tone || '') : '';

  return currentCard + messageCard + listCard + (State.providerForm ? Views._providerForm(models) : '');
};

/** 新增/编辑表单。字段值来自 `State.drafts`，由 app.js 的 input 监听写入。 */
Views._providerForm = function (models) {
  const editing = State.providerForm;
  const existing = editing === 'new' ? null : (models.providers || []).find((item) => item.id === editing) || null;
  const drafts = State.drafts;
  const value = (key, fallback) => {
    const raw = drafts[key] !== undefined ? drafts[key] : fallback || '';
    return UI.esc(raw);
  };
  const field = (label, key, fallback, type) =>
    '<div class="list-row"><div class="list-main">' +
    '<div class="list-sub">' +
    UI.esc(label) +
    '</div>' +
    '<input class="input" type="' +
    (type || 'text') +
    '" data-draft="' +
    UI.esc(key) +
    '" value="' +
    value(key, fallback) +
    '"></div></div>';

  const presetButtons = (models.presets || [])
    .filter((item) => item.base_url)
    .map(
      (item) =>
        '<button class="btn ghost" data-action="provider-preset" data-key="' +
        UI.esc(item.id) +
        '">' +
        UI.esc(item.name) +
        '</button>'
    )
    .join('');

  return UI.Card(
    editing === 'new' ? '新增来源' : '编辑来源',
    '<div class="list-sub">挑一个预设会自动填好名称与服务地址；只接 OpenAI 兼容的服务，' +
      '所以地址不对可以直接改，不需要等代码适配。</div>' +
      '<div class="btn-row spaced">' +
      presetButtons +
      '</div>' +
      field('名称', 'provider-name', existing && existing.name) +
      field('服务地址（OpenAI 兼容端点）', 'provider-url', existing && existing.base_url) +
      field('模型名', 'provider-model', existing && existing.model) +
      field('密钥', 'provider-key', '', 'password') +
      '<div class="list-sub">密钥留空＝不改动已存的那把（改地址或模型时不用重填）。' +
      '密钥只写进 Windows 凭据管理器，不落在这个配置文件里。</div>' +
      '<div class="btn-row spaced end">' +
      '<button class="btn" data-action="provider-save">保存</button>' +
      '<button class="btn ghost" data-action="provider-cancel">取消</button>' +
      '</div>'
  );
};

/** 重新取一次这一页的数据（改完之后让列表立刻反映出来）。 */
Views._reloadSettings = async function () {
  try {
    State.data.settings.providers = await API.get('/api/settings/providers');
  } catch (error) {
    State.providerMessage = { tone: 'danger', text: error.message || String(error) };
  }
  render();
};

Views.on_provider_new = function () {
  State.providerForm = 'new';
  State.providerMessage = { tone: '', text: '' };
  Object.assign(State.drafts, {
    'provider-preset': 'custom',
    'provider-name': '',
    'provider-url': '',
    'provider-model': '',
    'provider-key': '',
  });
  render();
};

Views.on_provider_edit = function (_target, key) {
  const models = (State.data.settings || {}).providers || {};
  const item = (models.providers || []).find((one) => one.id === key);
  if (!item) return;
  State.providerForm = key;
  State.providerMessage = { tone: '', text: '' };
  Object.assign(State.drafts, {
    'provider-preset': item.preset,
    'provider-name': item.name,
    'provider-url': item.base_url,
    'provider-model': item.model,
    // 密钥从不回显，所以这里永远是空的 —— 留空即不改。
    'provider-key': '',
  });
  render();
};

Views.on_provider_cancel = function () {
  State.providerForm = '';
  State.providerMessage = { tone: '', text: '' };
  render();
};

Views.on_provider_preset = function (_target, key) {
  const models = (State.data.settings || {}).providers || {};
  const preset = (models.presets || []).find((one) => one.id === key);
  if (!preset) return;
  Object.assign(State.drafts, {
    'provider-preset': preset.id,
    'provider-name': preset.name,
    'provider-url': preset.base_url,
  });
  render();
};

Views.on_provider_save = async function () {
  const payload = {
    name: State.drafts['provider-name'] || '',
    base_url: State.drafts['provider-url'] || '',
    model: State.drafts['provider-model'] || '',
    api_key: State.drafts['provider-key'] || '',
    preset: State.drafts['provider-preset'] || 'custom',
  };
  if (State.providerForm !== 'new') payload.id = State.providerForm;
  try {
    State.data.settings.providers = await API.post('/api/settings/providers', payload);
    State.providerForm = '';
    State.providerMessage = { tone: '', text: '已保存。' };
  } catch (error) {
    State.providerMessage = { tone: 'danger', text: error.message || String(error) };
  }
  render();
};

Views.on_provider_activate = async function (_target, key) {
  try {
    State.data.settings.providers = await API.post('/api/settings/providers/active', { id: key });
    State.providerMessage = { tone: '', text: '已切换。' };
  } catch (error) {
    State.providerMessage = { tone: 'danger', text: error.message || String(error) };
  }
  render();
};

Views.on_provider_delete = async function (_target, key) {
  const models = (State.data.settings || {}).providers || {};
  const item = (models.providers || []).find((one) => one.id === key);
  if (!window.confirm(`删除「${item ? item.name : key}」？密钥记录会留在凭据管理器里，这里只是不再使用它。`)) {
    return;
  }
  try {
    State.data.settings.providers = await API.post('/api/settings/providers/delete', { id: key });
    State.providerMessage = { tone: '', text: '已删除。' };
  } catch (error) {
    State.providerMessage = { tone: 'danger', text: error.message || String(error) };
  }
  render();
};

Views.on_provider_test = async function (_target, key) {
  State.providerMessage = { tone: '', text: '正在测试…' };
  render();
  try {
    const outcome = await API.post('/api/settings/providers/test', key ? { id: key } : {});
    State.providerMessage = {
      tone: outcome.ok ? '' : 'danger',
      text: (outcome.ok ? '连接正常：' : '连不上：') + (outcome.message || '') + (outcome.model ? `（${outcome.model}）` : ''),
    };
  } catch (error) {
    State.providerMessage = { tone: 'danger', text: error.message || String(error) };
  }
  render();
};
