/* 全球水电数据平台 — 前端应用逻辑
   纯原生 JS，无构建步骤。通过 pywebview.api.<method> 调用 Python 后端。
   页面路由 + 各页面渲染。ECharts 可选：未加载时图表区显示占位，不报错。 */

const api = () => window.pywebview && window.pywebview.api;
const hasECharts = () => typeof window.echarts !== 'undefined';

let appState = { route: 'dashboard', params: {}, pageStates: Object.create(null) };

// ---------- 页面交互状态 ----------
// 页面使用 main-content 整块重绘。若在导航前不保存草稿，任何输入、筛选、
// 处理结果都会在返回时丢失。这里保持“本次应用会话”的 UI 状态；正式数据仍只
// 由后端保存。密码和 FileList 出于安全/浏览器限制不缓存。
function routeStateKey(route, params = {}) {
  const normalized = Object.keys(params).filter(key => !key.startsWith('__')).sort().reduce((out, key) => {
    out[key] = params[key];
    return out;
  }, {});
  return `${route}:${JSON.stringify(normalized)}`;
}

// 内部导航选项不属于页面业务参数，也不应该生成另一份页面草稿。
function routeParams(params = {}) {
  return Object.keys(params).filter(key => !key.startsWith('__')).reduce((out, key) => {
    out[key] = params[key];
    return out;
  }, {});
}

function shouldRestorePageState(params = {}) {
  return params.__skipRestore !== true;
}

function controlStateKey(node, ordinal) {
  if (node.id) return `id:${node.id}`;
  if (node.name) return `name:${node.name}:${ordinal}`;
  return `node:${node.tagName}:${node.type || ''}:${ordinal}`;
}

function snapshotCurrentPageState() {
  const main = el('main-content');
  if (!main || !appState.route || !main.children.length) return;

  const controls = {};
  const seen = new Map();
  main.querySelectorAll('input, textarea, select, [contenteditable="true"]').forEach(node => {
    const type = (node.type || '').toLowerCase();
    // FileList 不能在浏览器中安全复原；密码也不应在内存页面缓存中保存。
    if (type === 'file' || type === 'password' || node.dataset.noPersist !== undefined) return;
    const base = node.id || node.name || `${node.tagName}:${type}`;
    const ordinal = seen.get(base) || 0;
    seen.set(base, ordinal + 1);
    const key = controlStateKey(node, ordinal);
    const state = { tag: node.tagName, type };
    if (node.tagName === 'SELECT' && node.multiple) {
      state.value = Array.from(node.options).filter(option => option.selected).map(option => option.value);
    } else if (type === 'checkbox' || type === 'radio') {
      state.checked = node.checked;
    } else if (node.isContentEditable) {
      state.value = node.innerHTML;
    } else {
      state.value = node.value;
    }
    controls[key] = state;
  });

  const regions = {};
  main.querySelectorAll('[data-persist-region]').forEach(node => {
    const key = node.dataset.persistRegion || node.id;
    if (!key) return;
    regions[key] = {
      html: node.innerHTML,
      className: node.className,
      style: node.getAttribute('style'),
    };
  });

  appState.pageStates[routeStateKey(appState.route, appState.params)] = {
    controls,
    regions,
    scrollTop: main.scrollTop,
  };
}

function restorePageState(route, params = {}) {
  const saved = appState.pageStates[routeStateKey(route, params)];
  const main = el('main-content');
  if (!saved || !main) return;

  const seen = new Map();
  main.querySelectorAll('input, textarea, select, [contenteditable="true"]').forEach(node => {
    const type = (node.type || '').toLowerCase();
    if (type === 'file' || type === 'password' || node.dataset.noPersist !== undefined) return;
    const base = node.id || node.name || `${node.tagName}:${type}`;
    const ordinal = seen.get(base) || 0;
    seen.set(base, ordinal + 1);
    const state = saved.controls[controlStateKey(node, ordinal)];
    if (!state) return;
    if (node.tagName === 'SELECT' && node.multiple && Array.isArray(state.value)) {
      Array.from(node.options).forEach(option => { option.selected = state.value.includes(option.value); });
    } else if (type === 'checkbox' || type === 'radio') {
      node.checked = Boolean(state.checked);
    } else if (node.isContentEditable) {
      node.innerHTML = state.value || '';
    } else if (state.value !== undefined) {
      node.value = state.value;
    }
  });

  main.querySelectorAll('[data-persist-region]').forEach(node => {
    const savedRegion = saved.regions[node.dataset.persistRegion || node.id];
    if (!savedRegion) return;
    node.innerHTML = savedRegion.html;
    node.className = savedRegion.className;
    if (savedRegion.style === null) node.removeAttribute('style');
    else node.setAttribute('style', savedRegion.style);
  });
  main.scrollTop = saved.scrollTop || 0;
}

// ---------- 工具 ----------
function el(id) { return document.getElementById(id); }
function fmt(n) {
  if (n === null || n === undefined) return '—';
  return Number(n).toLocaleString('en-US');
}
function esc(s) {
  if (s === null || s === undefined) return '';
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

// 业务状态 → 中文标签 + 样式类（基线第 5 节）
function statusLabel(pub, review) {
  if (pub === 'publishable') return ['已确认', 'st-published'];
  if (review === 'open' || review === 'pending') return ['待复核', 'st-review'];
  if (review === 'conflict') return ['来源冲突', 'st-conflict'];
  if (!pub && !review) return ['缺失', 'st-missing'];
  return [pub || review || '—', 'st-neutral'];
}
function prioLabel(tier) {
  const t = (tier || '').toLowerCase();
  if (t.includes('1') || t === 'high' || t === '高') return ['高', 'prio-high'];
  if (t.includes('2') || t === 'mid' || t === '中') return ['中', 'prio-mid'];
  return ['低', 'prio-low'];
}

// ---------- 通用模态框组件 ----------
function showModal(title, content, options = {}) {
  const modalId = 'app-modal';
  let existing = el(modalId);
  if (existing) existing.remove();

  const modal = document.createElement('div');
  modal.id = modalId;
  modal.className = 'modal-overlay';
  modal.innerHTML = `
    <div class="modal-container" style="max-width:${options.width || '800px'}">
      <div class="modal-header">
        <div class="modal-title">${esc(title)}</div>
        <button class="modal-close" onclick="closeModal()">&times;</button>
      </div>
      <div class="modal-body">${content}</div>
      ${options.footer ? `<div class="modal-footer">${options.footer}</div>` : ''}
    </div>
  `;

  document.body.appendChild(modal);

  // 点击遮罩关闭
  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeModal();
  });

  // ESC键关闭
  const escHandler = (e) => {
    if (e.key === 'Escape') {
      closeModal();
      document.removeEventListener('keydown', escHandler);
    }
  };
  document.addEventListener('keydown', escHandler);
}

function closeModal() {
  const modal = el('app-modal');
  if (modal) modal.remove();
}

// ---------- 使用指南 / 首次引导 ----------
const GUIDE_SEEN_KEY = 'hydro_first_use_guide_seen_v1';

function completeFirstUseGuide() {
  localStorage.setItem(GUIDE_SEEN_KEY, '1');
  closeModal();
}

function openGuideFromOnboarding() {
  completeFirstUseGuide();
  navigate('guide');
}

function showFirstUseGuide(force = false) {
  if (!force && localStorage.getItem(GUIDE_SEEN_KEY) === '1') return;
  const content = `
    <div style="line-height:1.8">
      <p style="margin-top:0">欢迎使用全球水电数据平台。请先记住：<strong>seedlist 是电站名册和数据缺口，不是可直接发布的数据。</strong></p>
      <ol style="padding-left:22px;margin:14px 0">
        <li><strong>选对象：</strong>在“水电站”搜索并确认目标电站。</li>
        <li><strong>找来源：</strong>在电站详情点击“智能发现可信来源”；也可在“智能发现”输入自然语言需求。</li>
        <li><strong>采集：</strong>创建任务或在“新增数据”提交已确认 URL/文件。</li>
        <li><strong>复核：</strong>核对电站、年度、年度实际值与原始证据后再发布。</li>
      </ol>
      <div style="padding:12px;background:var(--warning-bg);border-radius:var(--radius-sm);font-size:13px">网页能打开不等于数据可用。累计值、预测值、其他年份或其他电站的数据应拒绝。</div>
    </div>`;
  const footer = `
    <button class="btn btn-outline" onclick="completeFirstUseGuide()">稍后再说</button>
    <button class="btn btn-primary" onclick="openGuideFromOnboarding()">查看完整指南</button>`;
  showModal('首次使用引导', content, { width: '680px', footer });
}

function renderGuide() {
  const main = el('main-content');
  const steps = [
    ['1', '确认目标电站', '在“水电站”按名称、国家或容量筛选。先确认电站实体，再决定目标年份。', 'stations', '前往水电站'],
    ['2', '发现可信来源', '优先在电站详情点击“智能发现可信来源”；也可输入一句话任务。候选会融合 DeepSeek 原生搜索、程序搜索和 GEM 外链，并核对标题、年份与发布方。', 'intelligent-tasks', '前往智能发现'],
    ['3', '采集与处理', '选择来源后创建采集任务，或在“新增数据”提交已确认的 URL/PDF/表格。系统自动识别 HTML、PDF、Excel 与 CSV。', 'add-data', '前往新增数据'],
    ['4', '判断任务结果', '“成功”表示已发布；“待复核”表示候选已抽取但尚不能发布；“失败”表示该数据缺口仍需换来源。', 'tasks', '查看采集任务'],
    ['5', '复核后发布', '在“复核中心”点击“查看并复核”，逐项检查原始证据、年份、年度实际值和验证问题。可信则通过，不符则拒绝并说明原因。', 'review', '前往复核中心'],
  ];
  main.innerHTML = `
    <div class="page-header">
      <div><div class="page-title">使用指南</div>
        <div class="page-subtitle">从 seedlist 到正式数据的标准工作流</div>
      </div>
      <button class="btn btn-outline" onclick="showFirstUseGuide(true)">重新查看首次引导</button>
    </div>
    <div class="card" style="border-left:4px solid var(--primary);margin-bottom:16px">
      <div class="card-title">先理解数据状态</div>
      <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;font-size:13px;line-height:1.7">
        <div><strong style="color:var(--primary)">seedlist / 数据缺口</strong><br>待补齐的电站和年份，不是正式数据。</div>
        <div><strong style="color:var(--warning)">待复核</strong><br>候选已找到，但必须由人确认真实性和适用性。</div>
        <div><strong style="color:var(--green)">已发布</strong><br>经证据、校验和复核后，才进入数据浏览与榜单。</div>
      </div>
    </div>
    <div style="display:flex;flex-direction:column;gap:12px">
      ${steps.map(([number, title, description, route, label]) => `
        <div class="card" style="display:flex;gap:16px;align-items:center">
          <div style="width:34px;height:34px;border-radius:50%;background:var(--primary);color:white;display:flex;align-items:center;justify-content:center;font-weight:700;flex:none">${number}</div>
          <div style="flex:1"><div class="card-title" style="margin-bottom:4px">${title}</div><div style="font-size:13px;color:var(--text-muted);line-height:1.7">${description}</div></div>
          <button class="btn btn-outline btn-sm" onclick="navigate('${route}')">${label}</button>
        </div>`).join('')}
    </div>
    <div class="card" style="margin-top:16px;background:var(--warning-bg)">
      <div class="card-title">来源判定红线</div>
      <div style="font-size:13px;line-height:1.8">不要仅因链接可访问就通过。来源必须同时支持：<strong>同一电站、目标年度、年度实际发电量</strong>。累计发电量、装机容量、设计值、预测值、新闻描述或年份不匹配的数据应拒绝。</div>
    </div>`;
}

// ---------- 路由 ----------
const ROUTES = {
  dashboard: renderDashboard,
  stations: renderStations,
  'station-detail': renderStationDetail,
  'data-gaps': renderDataGaps,
  browse: renderBrowse,
  top100: renderTop100,
  'add-data': renderAddData,
  'intelligent-tasks': renderIntelligentTasks,
  'test-lab': renderTestLab,
  review: renderReview,
  projects: renderProjects,
  tasks: renderTasks,
  stats: () => renderStats(),
  sources: renderSources,
  documents: renderDocuments,
  evidence: renderEvidence,
  guide: renderGuide,
  settings: renderSettings,
};

async function navigate(route, params = {}) {
  console.log('navigate called:', route, params);
  snapshotCurrentPageState();
  const visibleParams = routeParams(params);
  const restoreSavedState = shouldRestorePageState(params);
  // 保留启动状态。pywebviewready 与兜底轮询可能同时命中；如果这里
  // 重建对象时丢掉 _booted，第二次 boot 会并发调用迁移和 dashboard。
  appState = { ...appState, route, params: visibleParams };
  // 侧栏高亮（详情页归属其列表）
  const navKey = route === 'station-detail' ? 'stations' : route;
  document.querySelectorAll('.nav-item').forEach(n =>
    n.classList.toggle('active', n.dataset.route === navKey));
  const fn = ROUTES[route];
  console.log('route function found:', !!fn);
  if (fn) {
    await fn(visibleParams);
    // 仅在当前路由仍然相同的情况下恢复。异步加载期间若用户已跳转，
    // 不应把旧页面草稿写到新页面。
    if (restoreSavedState && appState.route === route && routeStateKey(route, appState.params) === routeStateKey(route, visibleParams)) {
      restorePageState(route, visibleParams);
    }
  }
}

// ---------- 统一可信来源发现：自然语言入口 ----------
function renderIntelligentTasks() {
  const main = el('main-content');
  main.innerHTML = `
    <div class="page-header">
      <div><div class="page-title">智能发现可信来源</div>
        <div class="page-subtitle">用一句话创建来源规划；融合 DeepSeek 原生联网搜索、程序搜索与 GEM 外链后，再由规则校验和您的候选确认。</div>
      </div>
    </div>
    <div class="card" style="max-width:1000px">
      <div class="card-title">描述要收集的资料</div>
      <div style="font-size:13px;color:var(--text-muted);margin:6px 0 12px">示例：收集乌东德水电站 2024 年发电量，只接受国家能源局、三峡集团或正式年报，优先 PDF。</div>
      <textarea id="intelligent-task-prompt" rows="5" maxlength="2000" style="width:100%;resize:vertical;padding:12px;border:1px solid var(--border);border-radius:var(--radius-sm);font:inherit" placeholder="输入自然语言任务…"></textarea>
      <div style="display:flex;align-items:center;gap:12px;margin-top:12px">
        <button class="btn btn-primary" onclick="submitIntelligentTask()">智能发现可信来源</button>
        <span style="font-size:12px;color:var(--text-muted)">此步不会下载资料或写入正式数据；只会创建智能规划任务和候选台账。</span>
      </div>
    </div>
    <div id="intelligent-task-result" data-persist-region="intelligent-task-result" style="margin-top:16px"></div>`;
}

async function submitIntelligentTask() {
  const prompt = (el('intelligent-task-prompt')?.value || '').trim();
  if (!prompt) { alert('请输入任务描述。'); return; }
  const output = el('intelligent-task-result');
  output.innerHTML = '<div class="card"><div class="spinner">正在融合 DeepSeek 联网搜索、程序搜索与 GEM 外链…</div></div>';
  try {
    const result = await api().create_intelligent_task(prompt, false);
    if (!result.success) throw new Error(result.error || '智能任务创建失败');
    renderIntelligentTaskResult(result);
  } catch (e) {
    output.innerHTML = `<div class="card"><div class="empty">智能发现失败：${esc(e.message || e)}</div></div>`;
  }
}

function renderIntelligentTaskResult(result) {
  const output = el('intelligent-task-result');
  const intent = result.intent || {};
  const intentText = [
    intent.station_name ? `电站：${esc(intent.station_name)}` : '',
    intent.target_period ? `年份：${esc(intent.target_period)}` : '',
    intent.metric === 'capacity' ? '指标：装机容量' : (intent.metric ? '指标：发电量' : ''),
    intent.source_policy === 'official_only' ? '来源：仅官方' : (intent.source_policy ? '来源：官方或权威' : '')
  ].filter(Boolean).join('　·　');
  if (result.status === 'needs_input') {
    const matches = (result.station_matches || []).map(item => esc(item.canonical_name)).join('、');
    output.innerHTML = `<div class="card"><div class="card-title">需要补充电站名称</div><p>${esc(result.message || '')}</p>${matches ? `<p style="color:var(--text-muted);font-size:13px">可能匹配：${matches}</p>` : ''}</div>`;
    return;
  }
  const rows = (result.items || []).map(item => {
    const url = item.final_url || item.canonical_url || item.url;
    const state = item.access_status === 'requires_browser' ? '需浏览器验证' : '可访问';
    const stateClass = item.access_status === 'requires_browser' ? 'st-neutral' : 'st-published';
    return `<tr>
      <td style="max-width:310px;word-break:break-all"><a href="${esc(url)}" target="_blank">${esc(item.link_text || url)}</a><br><span style="font-size:12px;color:var(--text-muted)">${esc(item.section_title || '')}</span></td>
      <td><span class="badge-status st-neutral">${esc(item.source_type || 'reference')}</span></td>
      <td><span class="badge-status ${stateClass}">${state}</span></td>
      <td style="max-width:260px;font-size:12px;color:var(--text-muted)">${esc(item.match_reason || '')}</td>
      <td><button class="btn btn-outline btn-sm" onclick="queueIntelligentCandidate('${esc(result.plan_id)}','${encodeURIComponent(url)}')">创建采集任务</button></td>
    </tr>`;
  }).join('') || '<tr><td colspan="5" class="empty">没有通过预检的候选；未创建采集任务。</td></tr>';
  output.innerHTML = `<div class="card">
    <div class="card-title">可信来源发现结果</div>
    <p style="font-size:13px;color:var(--text-muted);margin:6px 0">${intentText || '任务意图已记录'}</p>
    <p style="font-size:13px;margin-bottom:14px">${esc(result.message || '')}</p>
    <table class="data-table"><thead><tr><th>来源</th><th>类型</th><th>访问状态</th><th>判定理由</th><th>操作</th></tr></thead><tbody>${rows}</tbody></table>
  </div>`;
}

async function queueIntelligentCandidate(planId, encodedUrl) {
  try {
    const result = await api().create_collection_task_from_intelligent_plan(planId, decodeURIComponent(encodedUrl));
    if (!result.success) throw new Error(result.error || '创建采集任务失败');
    alert(`已创建采集任务：${result.task_id}\n该任务仅会使用您刚确认的候选来源。`);
    navigate('tasks');
  } catch (e) {
    alert(`创建采集任务失败：${e.message || e}`);
  }
}

// ---------- 工作台 ----------
async function renderDashboard() {
  const main = el('main-content');
  main.innerHTML = '<div class="spinner">加载工作台…</div>';
  console.log('[Dashboard] Starting to load dashboard...');
  let d;
  try {
    console.log('[Dashboard] Calling api().get_dashboard()...');
    d = await api().get_dashboard();
    console.log('[Dashboard] Got dashboard data:', d);
  }
  catch (e) {
    console.error('[Dashboard] Error loading dashboard:', e);
    try {
      const info = await api().get_data_space_info('production');
      if (info && info.migration_required) {
        const blocked = Number(info.foreign_key_violations || 0) > 0;
        main.innerHTML = `
          <div class="card" style="border-left:4px solid #f59e0b;background:#fffbeb;">
            <div style="font-size:18px;font-weight:700;margin-bottom:8px;">数据库需要迁移</div>
            <div style="color:var(--text-muted);line-height:1.8;">
              当前 schema v${esc(info.schema_version)}，程序需要 v${esc(info.target_schema_version)}。
              ${blocked ? `检测到 ${esc(info.foreign_key_violations)} 项外键问题，迁移已保护性阻止。` : '请先备份，然后在测试实验室中明确确认迁移。'}
            </div>
            <button class="btn btn-primary" style="margin-top:14px;" onclick="navigate('test-lab')">前往数据库管理</button>
          </div>`;
        return;
      }
    } catch (infoError) {
      console.warn('[Dashboard] Could not read data-space status:', infoError);
    }
    main.innerHTML = `<div class="empty">加载失败：${esc(e)}</div>`;
    return;
  }

  const c = d.asset_cards;
  // 线性 SVG 图标（与侧栏同族），替代 emoji，去掉"AI 味"
  const ICONS = {
    stations: '<svg viewBox="0 0 24 24"><path d="M3 21h18"/><path d="M5 21V7l8-4v18"/><path d="M19 21V11l-6-4"/></svg>',
    projects: '<svg viewBox="0 0 24 24"><path d="M9 2h6a1 1 0 0 1 1 1v1h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2V3a1 1 0 0 1 1-1z"/><path d="M9 12h6M9 16h6"/></svg>',
    documents: '<svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>',
    records: '<svg viewBox="0 0 24 24"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/></svg>',
    gaps: '<svg viewBox="0 0 24 24"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/></svg>',
    review: '<svg viewBox="0 0 24 24"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>',
  };
  const upArrow = '<svg viewBox="0 0 24 24" width="11" height="11" style="stroke:var(--green);fill:none;stroke-width:3"><path d="M12 19V5M5 12l7-7 7 7"/></svg>';
  const kpi = (iconKey, cls, value, label, sub, trend) => `
    <div class="kpi">
      <div class="kpi-icon ${cls}">${ICONS[iconKey]}</div>
      <div>
        <div class="kpi-value">${fmt(value)}${trend ? `<span class="kpi-trend">${upArrow}${trend}</span>` : ''}</div>
        <div class="kpi-label">${label}</div>
        <div class="kpi-sub">${sub}</div>
      </div>
    </div>`;

  const todoRows = d.todo.map(t => `
    <div style="display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--border)">
      <span style="width:20px;height:20px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:${t.count > 0 ? 'var(--red-bg)' : 'var(--green-bg)'}">
        <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="${t.count > 0 ? 'var(--red)' : 'var(--green)'}" stroke-width="2.5">${
          t.count > 0
            ? '<path d="M12 8v4M12 16h.01"/>'
            : '<path d="M20 6 9 17l-5-5"/>'
        }</svg>
      </span>
      <span>${esc(t.label)}</span>
      <strong style="margin-left:auto;margin-right:12px">${t.count}</strong>
      <button class="btn btn-outline btn-sm" onclick="navigate('${t.route}')">${esc(t.action)}</button>
    </div>`).join('');

  const gapsRows = d.gaps.length ? d.gaps.map(g => {
    const [pl, pc] = prioLabel(g.priority_tier);
    return `<tr class="clickable" onclick="navigate('station-detail',{id:'${esc(g.entity_id)}'})">
      <td><span class="prio ${pc}">${pl}</span></td>
      <td>${esc(g.name || g.entity_id)}</td>
      <td>${esc(g.target_period || '—')}</td>
      <td>${esc(g.status)}</td>
      <td><button class="btn btn-outline btn-sm">处理</button></td>
    </tr>`;
  }).join('') : `<tr><td colspan="5" class="empty" style="padding:24px">暂无数据缺口——采集任务产生后会显示在这里</td></tr>`;

  const recentRows = d.recent.length ? d.recent.map(r => {
    const [sl, sc] = statusLabel(r.publication_status, r.review_status);
    return `<div style="padding:12px 0;border-bottom:1px solid var(--border)">
      <div style="display:flex;align-items:center;gap:8px">
        <strong>${esc(r.canonical_name || r.entity_id)}</strong>
        <span class="badge-status ${sc}" style="margin-left:auto">${sl}</span>
      </div>
      <div style="color:var(--text-muted);font-size:12px;margin-top:4px">
        ${esc(r.period_label)} · ${esc(r.value_type)} · ${fmt(r.generation_gwh)} GWh</div>
    </div>`;
  }).join('') : `<div class="empty" style="padding:24px">暂无最近工作记录</div>`;

  main.innerHTML = `
    <div class="kpi-row">
      ${kpi('stations','icon-blue',c.stations,'水电站','全球已收录')}
      ${kpi('projects','icon-green',c.projects,'项目','已收录')}
      ${kpi('documents','icon-purple',c.documents,'归档文档','份')}
      ${kpi('records','icon-orange',c.accepted_records,'已确认记录','条·可用于榜单')}
      ${kpi('gaps','icon-red',c.data_gaps,'数据缺口','待处理')}
      ${kpi('review','icon-cyan',c.pending_reviews,'待复核','条候选')}
    </div>

    <div class="grid-3">
      <div class="card">
        <div class="card-title">数据质量概况</div>
        <div id="quality-chart" class="chart-box"></div>
        <div style="text-align:center;color:var(--text-muted);font-size:13px;margin-top:8px">
          总记录数 <strong>${fmt(d.quality.total)}</strong></div>
      </div>
      <div class="card">
        <div class="card-title">当前需要处理</div>
        ${todoRows}
      </div>
      <div class="card">
        <div class="card-title">最近工作 <span class="link" onclick="navigate('browse')">全部 ›</span></div>
        ${recentRows}
      </div>
    </div>

    <div class="card" style="margin-bottom:20px;border-left:4px solid var(--primary)">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap">
        <div>
          <div class="card-title" style="margin-bottom:4px">运行环境</div>
          <div id="data-mode-help" style="font-size:12px;color:var(--text-muted)">正式数据：结果会写入正式数据库并参与后续统计。</div>
        </div>
        <select id="input-data-mode" onchange="updateDataModeHelp()" style="min-width:190px;padding:9px;border:1px solid var(--border);border-radius:var(--radius-sm)">
          <option value="production">正式数据</option>
          <option value="test">测试数据（隔离）</option>
        </select>
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="card-title">数据缺口（高优先级）
          <span class="link" onclick="navigate('data-gaps')">全部 ›</span></div>
        <table><thead><tr><th>优先级</th><th>水电站</th><th>年份</th><th>当前情况</th><th>操作</th></tr></thead>
          <tbody>${gapsRows}</tbody></table>
      </div>
      <div class="card">
        <div class="card-title">数据覆盖情况（按年份）
          <span class="link" onclick="navigate('stats')">完整统计 ›</span></div>
        <div id="coverage-chart" class="chart-box"></div>
      </div>
    </div>`;

  drawQualityChart(d.quality);
  drawCoverageChart(d.coverage_by_year);
  updateNavBadges(c);
}

function updateNavBadges(c) {
  const set = (id, n) => {
    const b = el(id); if (!b) return;
    if (n > 0) { b.textContent = n; b.style.display = ''; } else { b.style.display = 'none'; }
  };
  set('nav-gaps-badge', c.data_gaps);
  set('nav-review-badge', c.pending_reviews);
}

function drawQualityChart(quality) {
  const box = el('quality-chart');
  if (!box) return;
  if (!hasECharts() || quality.total === 0) {
    box.innerHTML = `<div class="empty">暂无正式记录<br>
      <span style="font-size:12px">采集与复核后此处显示质量分布</span></div>`;
    return;
  }
  const chart = echarts.init(box);
  chart.setOption({
    tooltip: { trigger: 'item' },
    series: [{
      type: 'pie', radius: ['55%', '78%'], center: ['50%', '48%'],
      label: { show: false },
      data: quality.buckets.map(b => ({ name: b.label, value: b.count }))
    }],
    color: ['#21a366', '#e0a516', '#e0483d', '#3b82c4', '#e07a1f']
  });
}

function drawCoverageChart(byYear) {
  const box = el('coverage-chart');
  if (!box) return;
  if (!hasECharts() || !byYear.length) {
    box.innerHTML = `<div class="empty">暂无按年份的正式记录</div>`;
    return;
  }
  const chart = echarts.init(box);
  chart.setOption({
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: byYear.map(r => r.year) },
    yAxis: { type: 'value' },
    series: [{ type: 'bar', data: byYear.map(r => r.accepted), color: '#2f66f5' }]
  });
}

// ---------- 水电站列表 ----------
async function renderStations(params) {
  const main = el('main-content');
  main.innerHTML = '<div class="spinner">加载水电站…</div>';
  const search = params.search || '';
  let countries = [];
  try { countries = await api().list_countries(); } catch (e) {}

  const countryOpts = ['<option value="">全部国家/地区</option>']
    .concat(countries.map(c => `<option value="${esc(c.country)}">${esc(c.country)} (${c.n})</option>`))
    .join('');

  main.innerHTML = `
    <div class="page-header">
      <div><div class="page-title">水电站</div>
        <div class="page-subtitle" id="station-count">加载中…</div></div>
    </div>
    <div class="filters">
      <input type="text" id="f-search" placeholder="搜索名称/别名" value="${esc(search)}" style="width:220px">
      <select id="f-country">${countryOpts}</select>
      <select id="f-capacity">
        <option value="">全部容量</option>
        <option value="10000">≥ 10,000 MW</option>
        <option value="1000">≥ 1,000 MW</option>
        <option value="100">≥ 100 MW</option>
      </select>
      <button class="btn btn-primary" onclick="applyStationFilter()">筛选</button>
    </div>
    <div class="card" style="padding:0">
      <table>
        <thead><tr><th>水电站</th><th>国家/地区</th><th>装机容量</th>
          <th>运行状态</th><th>运营方</th><th>河流</th></tr></thead>
        <tbody id="station-rows"><tr><td colspan="6" class="spinner">加载中…</td></tr></tbody>
      </table>
    </div>`;

  el('f-search').addEventListener('keydown', e => { if (e.key === 'Enter') applyStationFilter(); });
  loadStationRows(search);
}

async function loadStationRows(search) {
  const country = el('f-country') ? el('f-country').value : '';
  const minCap = el('f-capacity') ? el('f-capacity').value : '';
  let res;
  try {
    res = await api().list_stations(search || null, country || null, null,
      minCap ? Number(minCap) : null, null, 100, 0);
  } catch (e) {
    el('station-rows').innerHTML = `<tr><td colspan="6" class="empty">加载失败：${esc(e)}</td></tr>`;
    return;
  }
  el('station-count').textContent = `共 ${fmt(res.total)} 座水电站` +
    (res.total > res.items.length ? `（显示前 ${res.items.length} 座）` : '');
  el('station-rows').innerHTML = res.items.length ? res.items.map(s => `
    <tr class="clickable" onclick="navigate('station-detail',{id:'${esc(s.entity_id)}'})">
      <td><strong>${esc(s.canonical_name)}</strong></td>
      <td>${esc(s.country || '—')}</td>
      <td>${s.capacity_mw ? fmt(s.capacity_mw) + ' MW' : '—'}</td>
      <td>${esc(s.status || '—')}</td>
      <td>${esc(s.operator || '—')}</td>
      <td>${esc(s.river || '—')}</td>
    </tr>`).join('') : `<tr><td colspan="6" class="empty">没有匹配的水电站</td></tr>`;
}

function applyStationFilter() { loadStationRows(el('f-search').value); }

// ---------- 水电站详情 ----------
async function renderStationDetail(params) {
  const main = el('main-content');
  main.innerHTML = '<div class="spinner">加载详情…</div>';
  console.log('[DEBUG] renderStationDetail called with params:', params);
  let d;
  try {
    d = await api().get_station_detail(params.id);
    console.log('[DEBUG] Received data from backend:', d);
    console.log('[DEBUG] Generation array length:', d?.generation?.length);
  }
  catch (e) {
    console.error('[DEBUG] Error loading station detail:', e);
    main.innerHTML = `<div class="empty">加载失败：${esc(e)}</div>`;
    return;
  }
  if (!d) {
    console.log('[DEBUG] No data returned from backend');
    main.innerHTML = '<div class="empty">未找到该水电站</div>';
    return;
  }

  const s = d.station;
  const loc = [s.country, s.state_province, s.river].filter(Boolean).join(' · ');

  const genRows = d.generation.length ? d.generation.map(g => {
    const [sl, sc] = statusLabel(g.publication_status, g.review_status);
    return `<tr>
      <td>${esc(g.period_label)}</td>
      <td>${esc(g.value_type === 'actual' ? '实际' : g.value_type)}</td>
      <td>${esc(g.value_raw || '—')} ${esc(g.unit_raw || '')}</td>
      <td><strong>${fmt(g.generation_gwh)}</strong> GWh</td>
      <td><span class="badge-status ${sc}">${sl}</span></td>
      <td>${esc(g.source_title || '—')}</td>
    </tr>`;
  }).join('') : `<tr><td colspan="6" class="empty" style="padding:24px">
      暂无发电量记录——可通过采集流程为该电站寻找数据</td></tr>`;

  main.innerHTML = `
    <div class="page-header">
      <div>
        <div class="page-subtitle"><span class="link" style="cursor:pointer" onclick="navigate('stations')">水电站</span> › 详情</div>
        <div class="page-title">${esc(s.canonical_name)}</div>
        <div class="page-subtitle">${esc(loc || '—')}</div>
      </div>
      <div style="display:flex;gap:8px">
        <button class="btn btn-primary" onclick="discoverTrustedSources('${s.entity_id}')">智能发现可信来源</button>
        <button class="btn btn-outline" onclick="navigate('add-data')">提交已有来源</button>
      </div>
    </div>

    <div class="grid-4" style="margin-bottom:20px">
      <div class="card"><div class="kpi-label">装机容量</div>
        <div class="kpi-value">${s.capacity_mw ? fmt(s.capacity_mw) + ' MW' : '—'}</div></div>
      <div class="card"><div class="kpi-label">运行状态</div>
        <div class="kpi-value" style="font-size:18px">${esc(s.status || '—')}</div></div>
      <div class="card"><div class="kpi-label">数据覆盖</div>
        <div class="kpi-value">${d.coverage.record_count} <span style="font-size:13px;color:var(--text-muted)">条记录</span></div></div>
      <div class="card"><div class="kpi-label">最新数据年份</div>
        <div class="kpi-value">${esc(d.coverage.latest_year || '—')}</div></div>
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="card-title">基本信息</div>
        <table>
          <tr><td style="color:var(--text-muted);width:120px">运营方</td><td>${esc(s.operator || '—')}</td></tr>
          <tr><td style="color:var(--text-muted)">所有者</td><td>${esc(s.owner || '—')}</td></tr>
          <tr><td style="color:var(--text-muted)">河流</td><td>${esc(s.river || '—')}</td></tr>
          <tr><td style="color:var(--text-muted)">投产年份</td><td>${esc(s.commissioning_year || '—')}</td></tr>
          <tr><td style="color:var(--text-muted)">机组数</td><td>${esc(s.turbines || '—')}</td></tr>
          <tr><td style="color:var(--text-muted)">坐标</td><td>${s.latitude ? s.latitude + ', ' + s.longitude : '—'}</td></tr>
        </table>
      </div>
      <div class="card">
        <div class="card-title">别名与来源</div>
        <table>
          <tr><td style="color:var(--text-muted);width:120px">别名</td><td>${esc(s.aliases || '—')}</td></tr>
          <tr><td style="color:var(--text-muted)">当地名称</td><td>${esc(s.local_name || '—')}</td></tr>
          <tr><td style="color:var(--text-muted)">优先级</td><td>${esc(s.priority_tier || '—')}</td></tr>
          <tr><td style="color:var(--text-muted)">数据来源</td><td>${esc(s.source_seed || '—')}</td></tr>
          ${s.gem_wiki_url ? `<tr><td style="color:var(--text-muted)">GEM Wiki</td><td><a href="${esc(s.gem_wiki_url)}" target="_blank">查看</a></td></tr>` : ''}
        </table>
      </div>
    </div>

    <div class="card" style="margin-top:20px">
      <div class="card-title">年度发电量</div>
      <table><thead><tr><th>年份</th><th>类型</th><th>原始值</th>
        <th>标准值</th><th>状态</th><th>来源</th></tr></thead>
        <tbody>${genRows}</tbody></table>
    </div>`;
}

// ---------- 统一可信来源发现 ----------
async function discoverTrustedSources(entityId, presetYear = null) {
  const defaultYear = String(new Date().getFullYear() - 1);
  const enteredYear = presetYear || prompt('输入需要收集的目标年份：', defaultYear);
  if (enteredYear === null) return;
  const year = enteredYear.trim();
  if (!/^\d{4}$/.test(year)) {
    alert('年份必须为四位数字。');
    return;
  }
  const enteredPeriodType = prompt('输入期间类型：calendar_year=自然年，fiscal_year=财政年度', 'calendar_year');
  if (enteredPeriodType === null) return;
  const periodType = enteredPeriodType.trim().toLowerCase() || 'calendar_year';
  if (!['calendar_year', 'fiscal_year'].includes(periodType)) {
    alert('期间类型只能是 calendar_year（自然年）或 fiscal_year（财政年度）。');
    return;
  }

  showModal('正在智能发现可信来源', '<div class="spinner">正在融合 DeepSeek 联网搜索、程序搜索与 GEM 外链…</div>', { width: '760px' });
  try {
    // 兼容旧调用方的前三个参数，并显式传递期间类型，避免财政年度被当作自然年。
    const result = await api().discover_trusted_sources(entityId, year, 10, periodType);
    if (!result.success) throw new Error(result.error || '来源发现失败');
    const items = result.items || [];
    const reviewItems = result.review_items || [];
    const excludedItems = result.excluded_items || [];
    const providerDiagnostics = result.provider_diagnostics || [];
    const rows = items.length ? items.map(item => {
      const url = item.final_url || item.canonical_url || item.url;
      const encodedUrl = encodeURIComponent(url);
      const encodedTitle = encodeURIComponent(item.link_text || item.section_title || '智能发现可信来源');
      const encodedStationName = encodeURIComponent(result.entity_name || entityId);
      const score = Number(item.combined_score || 0).toFixed(2);
      const access = item.access_status === 'requires_browser' ? '需浏览器验证' : '可访问';
      const accessClass = item.access_status === 'requires_browser' ? 'st-neutral' : 'st-published';
      const period = item.period_scope === 'annual' ? '<span class="badge-status st-published">全年口径已确认</span>' : '<span class="badge-status st-neutral">期间需人工核实</span>';
      const channelMap = {
        deepseek_responses_web_search: 'DeepSeek 原生搜索',
        deepseek_planned_web_search: '程序搜索 + DeepSeek 筛选',
        gem_wiki_external_link: 'GEM 外链线索',
        html_attachment_link: '入口页公开附件',
        official_site_navigation: '已验证官网站内导航',
        official_site_sitemap: '已验证官网 Sitemap'
      };
      const channel = channelMap[item.discovery_method] || item.discovery_method || '统一发现';
      return `<tr>
        <td style="max-width:290px;word-break:break-all"><a href="${esc(url)}" target="_blank">${esc(item.link_text || url)}</a><br><span style="font-size:12px;color:var(--text-muted)">${esc(item.section_title || channel)}</span></td>
        <td><span class="badge-status st-neutral">${esc(item.source_type || 'reference')}</span><br><span style="font-size:12px;color:var(--text-muted)">${esc(channel)}</span></td>
        <td><span class="badge-status ${accessClass}">${access}</span></td>
        <td style="max-width:260px;font-size:12px;color:var(--text-muted)">${period}<br>${esc(item.match_reason || '')}${item.relevance_evidence ? `<br><span style="color:var(--text)">证据：${esc(item.relevance_evidence)}</span>` : ''}<br><span>综合评分：${score}</span></td>
        <td style="white-space:nowrap"><a class="btn btn-outline btn-sm" href="${esc(url)}" target="_blank">查看核实</a> <button class="btn btn-primary btn-sm" onclick="useDiscoveredSource('${entityId}','${year}','${periodType}','${encodedUrl}','${encodedTitle}','${encodedStationName}')">使用此来源</button></td>
      </tr>`;
    }).join('') : '<tr><td colspan="5" class="empty">未找到同时匹配电站、年份、年度发电量且可访问的来源。不会创建采集任务。</td></tr>';
    const reviewRows = reviewItems.map(item => {
      const url = item.final_url || item.canonical_url || item.candidate_url || item.url;
      const reason = item.error || item.match_reason || '未通过自动校验，需人工打开页面核实。';
      const access = item.access_status === 'requires_browser' ? '需浏览器验证' : '可访问';
      const encodedUrl = encodeURIComponent(url);
      const encodedTitle = encodeURIComponent(item.link_text || item.section_title || '人工核实来源');
      const encodedStationName = encodeURIComponent(result.entity_name || entityId);
      return `<tr>
        <td style="max-width:290px;word-break:break-all"><a href="${esc(url)}" target="_blank">${esc(item.link_text || url)}</a><br><span style="font-size:12px;color:var(--text-muted)">${esc(item.section_title || item.discovery_method || '来源线索')}</span></td>
        <td><span class="badge-status st-warning">待人工核实</span><br><span style="font-size:12px;color:var(--text-muted)">${esc(item.source_type || 'reference')}</span></td>
        <td><span class="badge-status st-neutral">${access}</span></td>
        <td style="max-width:300px;font-size:12px;color:var(--text-muted)">${esc(reason)}</td>
        <td style="white-space:nowrap;min-width:205px"><a class="btn btn-outline btn-sm" style="white-space:nowrap;display:inline-flex" href="${esc(url)}" target="_blank">打开核实</a> <button class="btn btn-primary btn-sm" style="white-space:nowrap" onclick="useReviewedLead('${entityId}','${year}','${periodType}','${encodedUrl}','${encodedTitle}','${encodedStationName}')">已核实，带入新增数据</button></td>
      </tr>`;
    }).join('');
    const excludedRows = excludedItems.map(item => {
      const url = item.final_url || item.canonical_url || item.candidate_url || item.url;
      const status = item.status === 'rejected' ? '已人工排除'
        : item.access_status === 'unavailable' ? '不可访问'
        : item.status === 'ineligible' ? '不符合任务条件' : '已排除';
      const reason = item.error || item.match_reason || '未通过自动发现门槛。';
      const canOpen = /^https?:\/\//i.test(url || '');
      return `<tr>
        <td style="max-width:330px;word-break:break-all">${canOpen ? `<a href="${esc(url)}" target="_blank">${esc(item.link_text || url)}</a>` : esc(item.link_text || url || '—')}<br><span style="font-size:12px;color:var(--text-muted)">${esc(item.section_title || item.discovery_method || '来源审计项')}</span></td>
        <td><span class="badge-status st-failed">${esc(status)}</span></td>
        <td><span class="badge-status st-neutral">${esc(item.access_status || 'unknown')}</span></td>
        <td style="max-width:330px;font-size:12px;color:var(--text-muted)">${esc(reason)}</td>
        <td>${canOpen ? `<a class="btn btn-outline btn-sm" href="${esc(url)}" target="_blank">查看</a>` : '—'}</td>
      </tr>`;
    }).join('');
    const recommendation = result.recommendation;
    const diagnostics = providerDiagnostics.length
      ? `<div style="font-size:12px;color:var(--text-muted);margin:0 0 12px">检索通道：${providerDiagnostics.map(item => {
          const provider = esc(item.provider || 'unknown');
          const status = item.status === 'ok' ? '完成'
            : item.status === 'metrics' ? '统计'
            : item.status === 'not_configured' ? '未配置'
            : item.status === 'disabled' ? '已禁用'
            : item.status === 'rate_limited' ? '速率受限'
            : item.status === 'budget_exhausted' ? '预算耗尽'
            : item.status === 'circuit_open' ? '已熔断'
            : item.status === 'empty' ? '无结果' : '失败';
          const count = Number.isFinite(Number(item.count)) ? `，${Number(item.count)} 条` : '';
          if (item.status === 'metrics' && item.metrics) {
            const metrics = item.metrics;
            const cost = Number.isFinite(Number(metrics.estimated_cost)) ? `，估算成本 ${Number(metrics.estimated_cost).toFixed(4)}` : '';
            const calls = metrics.providers ? Object.values(metrics.providers).reduce((sum, value) => sum + Number(value.calls || 0), 0) : null;
            return `${provider}（${status}${calls === null ? '' : `，${calls} 次调用`}${cost}）`;
          }
          const detail = item.error ? `：${esc(item.error)}` : '';
          return `${provider}（${status}${count}${detail}）`;
        }).join('；')}</div>`
      : '';
    const decision = recommendation
      ? `<div style="padding:12px;background:var(--green-bg);border-radius:var(--radius-sm);margin-bottom:14px"><strong>推荐来源已找到</strong><br><span style="font-size:13px">${esc(recommendation.link_text || recommendation.final_url || recommendation.url)}：${esc(recommendation.match_reason || '')}</span></div>`
      : `<div style="padding:12px;background:var(--warning-bg);border-radius:var(--radius-sm);margin-bottom:14px"><strong>未找到可自动处理的合格来源</strong><br><span style="font-size:13px">已过滤无关、错误年份、非年度发电量或不可访问的链接。${reviewItems.length ? `另发现 ${reviewItems.length} 条待人工核实线索，已在下方列出，不能直接创建采集任务。` : ''}${excludedItems.length ? ` 另有 ${excludedItems.length} 条已排除/不可用审计项可展开查看。` : ''}</span></div>`;
    const content = `
      ${decision}
      <p style="font-size:13px;color:var(--text-muted);margin-bottom:14px">${esc(result.message || '仅完成来源发现。')}</p>
      ${diagnostics}
      <p style="font-size:12px;color:var(--text-muted);margin-bottom:14px">“使用此来源”会自动带入电站、年份、URL 和标题；随后由您点击“开始下载并处理”确认启动采集。</p>
      <table class="data-table"><thead><tr><th>来源</th><th>等级 / 发现方式</th><th>访问状态</th><th>匹配证据</th><th>操作</th></tr></thead><tbody>${rows}</tbody></table>
      ${reviewRows ? `<div style="margin-top:18px"><div style="font-weight:600;margin-bottom:8px">待人工核实线索</div><p style="font-size:12px;color:var(--text-muted);margin:0 0 8px">这些链接确实由搜索发现并可访问，但未通过自动年度校验。打开核实后，只有您确认它对应目标电站、年份与全年实际发电量，才可带入新增数据。</p><table class="data-table"><thead><tr><th>来源</th><th>状态</th><th>访问状态</th><th>未通过原因</th><th>操作</th></tr></thead><tbody>${reviewRows}</tbody></table></div>` : ''}
      ${excludedRows ? `<details style="margin-top:18px"><summary style="cursor:pointer;font-weight:600">已排除 / 不可用审计项（${excludedItems.length}）</summary><p style="font-size:12px;color:var(--text-muted);margin:8px 0">这些链接保留用于解释发现结果；没有“使用此来源”按钮，不能直接创建任务或进入正式数据。</p><table class="data-table"><thead><tr><th>来源</th><th>状态</th><th>访问状态</th><th>排除原因</th><th>操作</th></tr></thead><tbody>${excludedRows}</tbody></table></details>` : ''}`;
    showModal(`智能发现可信来源 · ${esc(result.entity_name || entityId)} · ${esc(year)} · ${periodType === 'fiscal_year' ? '财政年度' : '自然年'}`, content, {
      width: '920px', footer: '<button class="btn btn-primary" onclick="closeModal()">关闭</button>'
    });
  } catch (e) {
    showModal('来源发现失败', `<div class="empty">${esc(e.message || e)}</div>`, {
      width: '600px', footer: '<button class="btn btn-primary" onclick="closeModal()">关闭</button>'
    });
  }
}

function useDiscoveredSource(entityId, year, periodType, encodedUrl, encodedTitle, encodedStationName) {
  sessionStorage.setItem('prefill_entity_id', entityId);
  if (year) sessionStorage.setItem('prefill_year', year);
  sessionStorage.setItem('prefill_period_type', periodType || 'calendar_year');
  sessionStorage.setItem('prefill_url', decodeURIComponent(encodedUrl));
  sessionStorage.setItem('prefill_source_title', decodeURIComponent(encodedTitle));
  sessionStorage.setItem('prefill_station_name', decodeURIComponent(encodedStationName || entityId));
  closeModal();
  // 来源选择是明确的新上下文，必须优先于此前离开“新增数据”时留下的草稿。
  // 路由完成后，本次预填仍会作为该页新的草稿继续被保留。
  navigate('add-data', { __skipRestore: true });
}

function useReviewedLead(entityId, year, periodType, encodedUrl, encodedTitle, encodedStationName) {
  const approved = confirm('请确认：您已核实该来源对应目标电站、目标年份及全年实际发电量。确认后仅带入“新增数据”页面，仍需由您点击“开始下载并处理”才会创建采集任务。');
  if (!approved) return;
  useDiscoveredSource(entityId, year, periodType, encodedUrl, encodedTitle, encodedStationName);
}

// ---------- 数据缺口 ----------
async function renderDataGaps() {
  const main = el('main-content');
  main.innerHTML = '<div class="spinner">加载数据缺口…</div>';
  let detected, coverage;
  try {
    detected = await api().detect_data_gaps(200);
    coverage = await api().get_data_coverage_stats();
  }
  catch (e) { main.innerHTML = `<div class="empty">加载失败：${esc(e)}</div>`; return; }

  const priorityMap = { high: 1, medium: 2, low: 3 };
  detected.sort((a, b) => {
    const pDiff = priorityMap[a.priority] - priorityMap[b.priority];
    if (pDiff !== 0) return pDiff;
    return b.capacity_mw - a.capacity_mw;
  });

  const topGaps = detected.slice(0, 100);
  const rows = topGaps.length ? topGaps.map(g => {
    const [pl, pc] = prioLabel(g.priority);
    return `<tr class="clickable" onclick="navigate('station-detail',{id:'${esc(g.entity_id)}'})">
      <td><span class="prio ${pc}">${pl}</span></td>
      <td><strong>${esc(g.name)}</strong><br><span style="font-size:11px;color:var(--text-muted)">${fmt(g.capacity_mw)} MW · ${esc(g.country)}</span></td>
      <td>${esc(g.target_year)}</td>
      <td>${esc(g.gap_type === 'missing_year' ? '缺失年度数据' : g.gap_type)}</td>
      <td><button class="btn btn-outline btn-sm" onclick="event.stopPropagation();createTaskForGap('${esc(g.entity_id)}','${esc(g.target_year)}')">寻找可信来源</button></td>
    </tr>`;
  }).join('') : '';

  const overall = coverage.overall;
  const coverageRate = overall.total_stations > 0
    ? ((overall.stations_with_data / overall.total_stations) * 100).toFixed(1)
    : 0;

  const countryRows = coverage.by_country.slice(0, 10).map(c => {
    const rate = c.total_stations > 0
      ? ((c.stations_with_data / c.total_stations) * 100).toFixed(0)
      : 0;
    return `<tr>
      <td>${esc(c.country)}</td>
      <td>${c.total_stations}</td>
      <td>${c.stations_with_data}</td>
      <td><strong>${rate}%</strong></td>
    </tr>`;
  }).join('');

  main.innerHTML = `
    <div class="page-header">
      <div>
        <div class="page-title">数据缺口</div>
        <div class="page-subtitle">智能检测：高优先级电站缺失的年度数据 · 共检测到 ${fmt(detected.length)} 个缺口</div>
      </div>
      <div style="display:flex;gap:8px">
        <button class="btn btn-outline" onclick="exportDataGaps()">导出缺口列表</button>
        <button class="btn btn-primary" onclick="batchCreateTasks()">批量创建任务</button>
      </div>
    </div>

    <div class="grid-3" style="margin-bottom:20px">
      <div class="card">
        <div class="kpi-label">总电站数</div>
        <div class="kpi-value">${fmt(overall.total_stations)}</div>
      </div>
      <div class="card">
        <div class="kpi-label">有数据电站</div>
        <div class="kpi-value">${fmt(overall.stations_with_data)}</div>
      </div>
      <div class="card">
        <div class="kpi-label">覆盖率</div>
        <div class="kpi-value">${coverageRate}%</div>
      </div>
    </div>

    <div class="grid-2">
      <div class="card" style="padding:0">
        <div class="card-title" style="padding:16px">数据缺口列表（显示前 100 项）</div>
        <table>
          <thead><tr><th>优先级</th><th>电站</th><th>年份</th><th>类型</th><th>操作</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="5" class="empty" style="padding:24px">未检测到数据缺口</td></tr>'}</tbody>
        </table>
      </div>

      <div class="card" style="padding:0">
        <div class="card-title" style="padding:16px">国家覆盖率统计</div>
        <table>
          <thead><tr><th>国家</th><th>总电站数</th><th>有数据</th><th>覆盖率</th></tr></thead>
          <tbody>${countryRows}</tbody>
        </table>
      </div>
    </div>`;
}

async function createTaskForGap(entityId, year) {
  return discoverTrustedSources(entityId, String(year));
}

function batchCreateTasks() {
  alert('为避免在未核实来源时创建空采集任务，批量创建已停用。请先对具体电站使用“寻找可信来源”。');
}

function exportDataGaps() {
  api().detect_data_gaps(1000).then(gaps => {
    const csv = ['优先级,电站,国家,装机容量(MW),缺失年份,类型']
      .concat(gaps.map(g =>
        `${g.priority},"${g.name}","${g.country}",${g.capacity_mw},${g.target_year},${g.gap_type}`
      ))
      .join('\n');
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `数据缺口_${new Date().toISOString().split('T')[0]}.csv`;
    link.click();
  });
}

// ---------- 数据浏览 ----------
async function renderBrowse() {
  const main = el('main-content');
  main.innerHTML = '<div class="spinner">加载数据浏览…</div>';
  let res;
  try { res = await api().browse_records(null, null, null, false, 100, 0); }
  catch (e) { main.innerHTML = `<div class="empty">加载失败：${esc(e)}</div>`; return; }

  const rows = res.items.length ? res.items.map(r => {
    const [sl, sc] = statusLabel(r.publication_status, r.review_status);
    return `<tr class="clickable" onclick="navigate('station-detail',{id:'${esc(r.entity_id)}'})">
      <td><strong>${esc(r.canonical_name || r.entity_id)}</strong></td>
      <td>${esc(r.country || '—')}</td>
      <td>${esc(r.period_label)}</td>
      <td>${esc(r.value_type === 'actual' ? '实际' : r.value_type)}</td>
      <td><strong>${fmt(r.generation_gwh)}</strong> GWh</td>
      <td><span class="badge-status ${sc}">${sl}</span></td>
    </tr>`;
  }).join('') : '';

  main.innerHTML = `
    <div class="page-header"><div>
      <div class="page-title">数据浏览</div>
      <div class="page-subtitle">跨电站浏览发电量记录 · 共 ${fmt(res.total)} 条</div>
    </div></div>
    ${res.items.length ? `<div class="card" style="padding:0"><table>
      <thead><tr><th>水电站</th><th>国家</th><th>年份</th><th>类型</th>
        <th>发电量</th><th>状态</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`
      : `<div class="card"><div class="empty">暂无发电量记录<br><span style="font-size:12px">
        发电量数据通过采集→抽取→复核流程产生。当前数据库仅有电站基础档案。</span></div></div>`}`;
}

// ---------- Top 100 ----------
let top100State = { year: null, country: null };

async function renderTop100() {
  const main = el('main-content');
  main.innerHTML = '<div class="spinner">加载 Top 100…</div>';
  let list;
  try { list = await api().get_top100(top100State.year); }
  catch (e) { main.innerHTML = `<div class="empty">加载失败：${esc(e)}</div>`; return; }

  // 获取可用年份列表（从已有数据推断）
  const years = [...new Set(list.map(r => r.period_label))].sort().reverse();
  const yearOpts = ['<option value="">全部年份</option>']
    .concat(years.map(y => `<option value="${y}" ${top100State.year === y ? 'selected' : ''}>${y}</option>`))
    .join('');

  // 获取可用国家列表
  const countries = [...new Set(list.map(r => r.country).filter(Boolean))].sort();
  const countryOpts = ['<option value="">全部国家</option>']
    .concat(countries.map(c => `<option value="${esc(c)}" ${top100State.country === c ? 'selected' : ''}>${esc(c)}</option>`))
    .join('');

  // 客户端筛选（按国家）
  let filtered = list;
  if (top100State.country) {
    filtered = list.filter(r => r.country === top100State.country);
  }
  filtered = filtered.slice(0, 100);

  const rows = filtered.map((r, i) => {
    const rankClass = i < 3 ? 'rank-medal' : '';
    const medal = i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : '';
    return `<tr class="clickable" onclick="navigate('station-detail',{id:'${esc(r.entity_id)}'})">
      <td><strong class="${rankClass}">${medal} ${i + 1}</strong></td>
      <td><strong>${esc(r.canonical_name || r.entity_id)}</strong></td>
      <td>${esc(r.country || '—')}</td>
      <td>${esc(r.period_label)}</td>
      <td>${r.capacity_mw ? fmt(r.capacity_mw) + ' MW' : '—'}</td>
      <td><strong style="color:var(--primary)">${fmt(r.generation_gwh)}</strong> GWh</td>
    </tr>`;
  }).join('');

  // 统计摘要
  const totalGeneration = filtered.reduce((sum, r) => sum + (r.generation_gwh || 0), 0);
  const avgGeneration = filtered.length > 0 ? (totalGeneration / filtered.length) : 0;
  const countriesCount = new Set(filtered.map(r => r.country).filter(Boolean)).size;

  main.innerHTML = `
    <div class="page-header">
      <div>
        <div class="page-title">Top 100</div>
        <div class="page-subtitle">仅统计已发布、已确认、证据完整的正式记录</div>
      </div>
      <div style="display:flex;gap:8px">
        <select id="year-filter" onchange="filterTop100Year()" style="padding:8px;border:1px solid var(--border);border-radius:var(--radius-sm)">
          ${yearOpts}
        </select>
        <select id="country-filter" onchange="filterTop100Country()" style="padding:8px;border:1px solid var(--border);border-radius:var(--radius-sm)">
          ${countryOpts}
        </select>
        <button class="btn btn-outline" onclick="exportTop100()">导出榜单</button>
      </div>
    </div>

    <div class="grid-3" style="margin-bottom:20px">
      <div class="card" style="text-align:center">
        <div style="font-size:32px;font-weight:600;color:var(--primary)">${fmt(totalGeneration)}</div>
        <div style="color:var(--text-muted);margin-top:8px">总发电量 (GWh)</div>
      </div>
      <div class="card" style="text-align:center">
        <div style="font-size:32px;font-weight:600;color:var(--green)">${fmt(Math.round(avgGeneration))}</div>
        <div style="color:var(--text-muted);margin-top:8px">平均发电量 (GWh)</div>
      </div>
      <div class="card" style="text-align:center">
        <div style="font-size:32px;font-weight:600;color:var(--orange)">${countriesCount}</div>
        <div style="color:var(--text-muted);margin-top:8px">覆盖国家数</div>
      </div>
    </div>

    ${filtered.length ? `<div class="card" style="padding:0"><table>
      <thead><tr><th>排名</th><th>电站</th><th>国家</th><th>年份</th>
        <th>装机容量</th><th>发电量</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`
      : `<div class="card"><div class="empty">暂无正式发布记录<br><span style="font-size:12px">
        只有经过复核并发布的记录才会进入 Top 100 榜单。</span></div></div>`}`;
}

function filterTop100Year() {
  top100State.year = el('year-filter').value || null;
  renderTop100();
}

function filterTop100Country() {
  top100State.country = el('country-filter').value || null;
  renderTop100();
}

function exportTop100() {
  api().get_top100(top100State.year).then(list => {
    let filtered = list;
    if (top100State.country) {
      filtered = list.filter(r => r.country === top100State.country);
    }
    filtered = filtered.slice(0, 100);

    const csv = ['排名,电站,国家,年份,装机容量(MW),发电量(GWh)']
      .concat(filtered.map((r, i) =>
        `${i + 1},"${r.canonical_name || r.entity_id}","${r.country || ''}",${r.period_label},${r.capacity_mw || ''},${r.generation_gwh}`
      ))
      .join('\n');
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    const filename = `Top100榜单_${top100State.year || '全部年份'}_${top100State.country || '全球'}_${new Date().toISOString().split('T')[0]}.csv`;
    link.download = filename;
    link.click();
  });
}

// ---------- 占位页 ----------
function renderPlaceholder(title, desc) {
  el('main-content').innerHTML = `
    <div class="page-header"><div><div class="page-title">${esc(title)}</div></div></div>
    <div class="card"><div class="empty">${esc(desc)}</div></div>`;
}

// ---------- 测试实验室 ----------
// 测试实验室页面渲染（优化版）
async function renderTestLab() {
  const main = el('main-content');
  const currentMode = localStorage.getItem('data_mode') || 'production';
  const isTestMode = currentMode === 'test';

  main.innerHTML = `
    <div class="page-header">
      <div>
        <div class="page-title">🧪 测试实验室</div>
        <div class="page-subtitle">在隔离环境验证数据采集流程，测试结果不会写入生产数据库</div>
      </div>
    </div>

    <div class="card" style="
      background: linear-gradient(135deg, ${isTestMode ? '#fffbeb 0%, #fef3c7 100%' : '#eff6ff 0%, #dbeafe 100%'});
      border-left: 4px solid ${isTestMode ? '#f59e0b' : '#3b82f6'};
      margin-bottom: 24px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    ">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <div style="flex: 1;">
          <div style="font-size: 20px; font-weight: 700; color: ${isTestMode ? '#b45309' : '#1e40af'}; margin-bottom: 8px;">
            ${isTestMode ? '🧪' : '🏢'} 当前空间：${isTestMode ? '测试环境' : '生产环境'}
          </div>
          <div id="space-info" style="font-size: 13px; color: ${isTestMode ? '#92400e' : '#1e3a8a'}; opacity: 0.8;">
            正在加载数据库信息...
          </div>
        </div>
        <div style="display:flex; gap:12px; align-items:center;">
          <button class="btn ${isTestMode ? 'btn-primary' : 'btn-outline'}"
                  onclick="switchDataMode('${isTestMode ? 'production' : 'test'}')"
                  style="min-width: 140px; font-weight: 600;">
            ${isTestMode ? '📊' : '🧪'} 切换到${isTestMode ? '生产' : '测试'}空间
          </button>
          ${!isTestMode ? '<button id="migrate-db-btn" class="btn btn-primary" style="display:none;font-weight:600;">迁移数据库</button>' : ''}
          ${isTestMode ? '<button class="btn btn-outline" onclick="resetTestLab()" style="color: #dc2626; border-color: #fca5a5;">🗑️ 清空测试数据</button>' : ''}
        </div>
      </div>
    </div>

    <div class="grid-3" style="margin-bottom: 24px; gap: 16px;" id="space-stats"></div>

    <div class="grid-2" style="margin-bottom: 24px; gap: 16px;">
      <div class="card" style="background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%); border-top: 3px solid #0284c7;">
        <div style="display: flex; align-items: center; margin-bottom: 12px;">
          <div style="font-size: 24px; margin-right: 10px;">🏢</div>
          <div class="card-title" style="margin: 0; font-size: 16px;">生产空间</div>
        </div>
        <ul style="font-size: 13px; color: var(--text-muted); line-height: 2; margin: 0; padding-left: 20px;">
          <li><strong>数据库：</strong>hydro.db</li>
          <li><strong>用途：</strong>Top 100 榜单及正式数据</li>
          <li><strong>特点：</strong>所有数据持久化保存</li>
          <li><strong>注意：</strong>谨慎操作，避免误删</li>
        </ul>
      </div>
      <div class="card" style="background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%); border-top: 3px solid #f59e0b;">
        <div style="display: flex; align-items: center; margin-bottom: 12px;">
          <div style="font-size: 24px; margin-right: 10px;">🧪</div>
          <div class="card-title" style="margin: 0; font-size: 16px;">测试空间</div>
        </div>
        <ul style="font-size: 13px; color: var(--text-muted); line-height: 2; margin: 0; padding-left: 20px;">
          <li><strong>数据库：</strong>hydro_test.db</li>
          <li><strong>用途：</strong>验证采集和解析流程</li>
          <li><strong>特点：</strong>完全隔离的测试环境</li>
          <li><strong>操作：</strong>可随时清空重置</li>
        </ul>
      </div>
    </div>

    <div class="card" style="background: #fafafa; border: 1px solid #e5e5e5;">
      <div style="display: flex; align-items: center; margin-bottom: 16px;">
        <div style="font-size: 24px; margin-right: 10px;">📖</div>
        <div class="card-title" style="margin: 0;">使用指南</div>
      </div>
      <div style="background: white; border-radius: 8px; padding: 20px; border: 1px solid #e5e5e5;">
        <ol style="line-height: 2.2; color: var(--text); margin: 0; padding-left: 20px;">
          <li><strong>切换到测试空间：</strong>点击上方"切换到测试空间"按钮，进入隔离环境</li>
          <li><strong>测试数据采集：</strong>前往"新增数据"页面，上传文件或输入URL进行测试</li>
          <li><strong>查看测试结果：</strong>测试数据仅写入 hydro_test.db，不影响生产榜单</li>
          <li><strong>清空或返回：</strong>验证完成后可清空测试数据，或切换回生产空间继续工作</li>
        </ol>
        <div style="margin-top: 20px; padding-top: 16px; border-top: 1px solid #e5e5e5;">
          <button class="btn btn-primary" onclick="navigate('add-data')" style="font-weight: 600;">
            ➕ 前往新增数据页面
          </button>
        </div>
      </div>
    </div>
  `;

  // 加载数据
  try {
    const mode = isTestMode ? 'test' : 'production';
    const [info, stats] = await Promise.all([
      api().get_data_space_info(mode),
      isTestMode ? api().get_dashboard_test() : api().get_dashboard()
    ]);

    const dbName = info.db_path.split(/[/\\]/).pop();
    const spaceInfoEl = el('space-info');
    if (spaceInfoEl) {
      spaceInfoEl.textContent = `数据库：${dbName} · schema v${info.schema_version}`;
    }
    const migrateButton = el('migrate-db-btn');
    if (migrateButton && info.migration_required) {
      migrateButton.style.display = 'inline-block';
      migrateButton.textContent = `迁移到 v${info.target_schema_version}`;
      migrateButton.onclick = migrateProductionDatabase;
      if (info.foreign_key_violations) {
        migrateButton.disabled = true;
        migrateButton.title = `存在 ${info.foreign_key_violations} 项外键问题，需先治理`;
      }
    }

    const d = stats.counts || stats.asset_cards || stats;
    const stationCount = d.stations || 0;
    const docCount = d.documents || 0;
    const recordCount = d.records || d.generation_records || d.accepted_records || 0;

    const spaceStatsEl = el('space-stats');
    if (spaceStatsEl) {
      spaceStatsEl.innerHTML = `
        <div class="card" style="text-align:center; background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%); border-top: 3px solid #16a34a;">
          <div style="font-size:36px; font-weight:700; color:#16a34a; margin-bottom: 8px;">${stationCount}</div>
          <div style="color:#166534; font-weight:600; font-size: 14px;">电站</div>
        </div>
        <div class="card" style="text-align:center; background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border-top: 3px solid #eab308;">
          <div style="font-size:36px; font-weight:700; color:#ca8a04; margin-bottom: 8px;">${docCount}</div>
          <div style="color:#854d0e; font-weight:600; font-size: 14px;">文档</div>
        </div>
        <div class="card" style="text-align:center; background: linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%); border-top: 3px solid #3b82f6;">
          <div style="font-size:36px; font-weight:700; color:#2563eb; margin-bottom: 8px;">${recordCount}</div>
          <div style="color:#1e40af; font-weight:600; font-size: 14px;">记录</div>
        </div>
      `;
    }
  } catch (e) {
    console.error('Error loading data:', e);
    const spaceInfoEl = el('space-info');
    if (spaceInfoEl) {
      spaceInfoEl.textContent = '读取失败：' + e.message;
    }
  }
}

async function migrateProductionDatabase() {
  if (!confirm('将把生产数据库迁移到当前程序版本。系统会先检查外键问题；存在问题时不会执行迁移。是否继续？')) return;
  try {
    const result = await api().migrate_data_space('production');
    if (!result.success) {
      alert(`迁移未执行：${result.error || '未知原因'}`);
      return;
    }
    alert(result.already_current ? '数据库已经是最新版本。' : '数据库迁移完成，页面将刷新。');
    window.location.reload();
  } catch (e) {
    alert(`迁移失败：${e.message || e}`);
  }
}

function switchDataMode(newMode) {
  const currentMode = localStorage.getItem('data_mode') || 'production';

  if (newMode === currentMode) {
    alert('当前已在此数据空间');
    return;
  }

  const modeLabel = newMode === 'test' ? '测试空间' : '生产空间';
  const warning = newMode === 'production'
    ? '⚠️ 切换到生产空间后，所有操作将影响正式数据。\n\n确定要切换吗？'
    : '切换到测试空间后，所有操作将在隔离环境进行。\n\n确定要切换吗？';

  if (!confirm(warning)) return;

  localStorage.setItem('data_mode', newMode);

  alert(`✓ 已切换到${modeLabel}\n\n页面将自动刷新。`);

  // 刷新页面
  renderTestLab();
}

async function resetTestLab() {
  if (!confirm('确定清空测试数据库和测试归档文件吗？\n\n正式数据不会受到影响。')) return;
  try {
    await api().reset_test_data();
    alert('✓ 测试数据已清空');
    renderTestLab();
  } catch (e) {
    alert('清空失败：' + e.message);
  }
}

// ---------- 新增数据 ----------
let batchUploadState = { files: [], currentIndex: 0, results: [] };

// 处理历史记录（localStorage 持久化）
function getProcessHistory() {
  try {
    const history = localStorage.getItem('hydro_process_history');
    return history ? JSON.parse(history) : [];
  } catch {
    return [];
  }
}

function saveProcessHistory(history) {
  try {
    localStorage.setItem('hydro_process_history', JSON.stringify(history));
  } catch (e) {
    console.error('保存历史记录失败:', e);
  }
}

function addToHistory(record) {
  const history = getProcessHistory();
  history.unshift({
    ...record,
    timestamp: new Date().toISOString()
  });
  // 只保留最近 100 条
  if (history.length > 100) {
    history.splice(100);
  }
  saveProcessHistory(history);
}

function clearProcessHistory() {
  if (confirm('确定清空所有处理历史记录吗？')) {
    localStorage.removeItem('hydro_process_history');
    renderAddData();
  }
}

async function renderAddData() {
  console.log('renderAddData called');
  const main = el('main-content');

  // 获取历史记录
  const history = getProcessHistory();
  const historyRows = history.map(h => {
    const statusBadge = h.success
      ? '<span class="badge" style="background:var(--green-bg);color:var(--green)">成功</span>'
      : '<span class="badge" style="background:var(--red-bg);color:var(--red)">失败</span>';
    const stageBadge = h.error_stage
      ? `<span class="badge" style="background:var(--border);color:var(--text-muted)">${h.error_stage}</span>`
      : '';
    const time = new Date(h.timestamp).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
    const name = h.name || (h.url ? h.url.split('/').pop() : h.file_path?.split(/[/\\]/).pop()) || '未知';
    const message = h.success
      ? `保存 ${h.saved_count || 0} 条记录`
      : (h.error_message || '未知错误');

    return `<tr>
      <td style="font-size:12px;color:var(--text-muted)">${time}</td>
      <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(name)}">${esc(name)}</td>
      <td>${esc(h.source_id || '-')}</td>
      <td>${statusBadge} ${stageBadge}</td>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px" title="${esc(message)}">${esc(message)}</td>
    </tr>`;
  }).join('');

  main.innerHTML = `
    <div class="page-header">
      <div>
        <div class="page-title">新增数据</div>
        <div class="page-subtitle">上传文档或输入 URL，系统将自动采集、解析、抽取数据</div>
      </div>
    </div>

    <div class="card" style="margin-bottom:20px;border-left:4px solid var(--primary)">
      <div class="card-title">业务信息（必填）</div>
      <div class="grid-2">
        <div class="form-group">
          <label>目标电站 *</label>
          <div style="position:relative">
            <input type="text" id="input-station-search" placeholder="输入电站名称搜索..."
              style="width:100%;padding:8px;border:1px solid var(--border);border-radius:var(--radius-sm)"
              oninput="handleStationSearch(event)"
              onfocus="showStationDropdown()"
              onblur="hideStationDropdown()">
            <input type="hidden" id="input-station-id">
            <div id="station-dropdown" style="display:none;position:absolute;z-index:100;width:100%;max-height:200px;overflow-y:auto;background:var(--card-bg);border:1px solid var(--border);border-radius:var(--radius-sm);margin-top:2px;box-shadow:0 2px 8px rgba(0,0,0,0.1)"></div>
          </div>
        </div>
        <div class="form-group">
          <label>目标年份 *</label>
          <input type="number" id="input-target-year" placeholder="2024" min="1900" max="2100"
            style="width:100%;padding:8px;border:1px solid var(--border);border-radius:var(--radius-sm)">
        </div>
        <div class="form-group">
          <label>统计口径 *</label>
          <select id="input-period-type" style="width:100%;padding:8px;border:1px solid var(--border);border-radius:var(--radius-sm)">
            <option value="calendar_year">自然年（1月—12月）</option>
            <option value="fiscal_year">财政年度（按发布方财年）</option>
          </select>
        </div>
      </div>
      <div style="font-size:12px;color:var(--text-muted);margin-top:8px">
        ⚠️ 必须指定电站和年份才能启动可信 Pipeline 流程
      </div>
    </div>

    <div class="card" style="margin-bottom:20px;background:linear-gradient(135deg, var(--green-bg) 0%, var(--card-bg) 100%);border-left:4px solid var(--green)">
      <div class="card-title">方式 1：批量导入 CSV</div>
      <div style="font-size:13px;color:var(--text-muted);margin-bottom:12px">
        快速导入已整理的发电量数据。CSV格式要求：<code style="background:var(--border);padding:2px 6px;border-radius:3px">entity_id, period_label, generation_gwh</code>
      </div>
      <div class="form-group">
        <label>上传 CSV 文件</label>
        <input type="file" id="input-csv-file" accept=".csv" style="width:100%;padding:8px;border:1px solid var(--border);border-radius:var(--radius-sm)">
      </div>
      <div class="form-group" style="margin-top:12px">
        <label>来源标题</label>
        <input type="text" id="input-csv-source" placeholder="例如：2024年水电站发电量统计" value="CSV批量导入" style="width:100%;padding:8px;border:1px solid var(--border);border-radius:var(--radius-sm)">
      </div>
      <div style="display:flex;gap:12px;margin-top:16px">
        <button class="btn btn-primary" onclick="importCsvFile()">导入 CSV</button>
        <button class="btn btn-outline" onclick="downloadCsvTemplate()">下载模板</button>
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="card-title">方式 2：从网络下载</div>
        <div class="form-group">
          <label>文档 URL（https://...）</label>
          <input type="text" id="input-url" placeholder="https://example.com/report.pdf" style="width:100%;padding:8px;border:1px solid var(--border);border-radius:var(--radius-sm)">
        </div>
        <div class="form-group" style="margin-top:12px">
          <label>来源标题</label>
          <input type="text" id="input-source-url" placeholder="例如：三峡集团2024年报" style="width:100%;padding:8px;border:1px solid var(--border);border-radius:var(--radius-sm)">
        </div>
        <button class="btn btn-primary" onclick="startDownloadTask()" style="margin-top:16px">开始下载并处理</button>
      </div>

      <div class="card">
        <div class="card-title">方式 3：处理本地文件</div>
        <div class="form-group">
          <label>单个文件路径</label>
          <input type="text" id="input-single-file" placeholder="C:\path\to\file.pdf" style="width:100%;padding:8px;border:1px solid var(--border);border-radius:var(--radius-sm)">
        </div>
        <div class="form-group" style="margin-top:12px">
          <label>来源标题</label>
          <input type="text" id="input-source-file" placeholder="例如：国家能源局统计报告" style="width:100%;padding:8px;border:1px solid var(--border);border-radius:var(--radius-sm)">
        </div>
        <button class="btn btn-primary" onclick="startSingleFileTask()" style="margin-top:16px">开始处理</button>
      </div>
    </div>

    <div class="card" id="batch-progress" data-persist-region="batch-progress" style="margin-top:20px;display:none">
      <div class="card-title">批量处理进度</div>
      <div style="margin-bottom:12px">
        <div style="display:flex;justify-content:space-between;margin-bottom:4px">
          <span>进度：<strong id="batch-progress-text">0 / 0</strong></span>
          <span id="batch-status-text">准备中...</span>
        </div>
        <div style="width:100%;height:8px;background:var(--border);border-radius:4px;overflow:hidden">
          <div id="batch-progress-bar" style="width:0%;height:100%;background:var(--primary);transition:width 0.3s"></div>
        </div>
      </div>
      <div id="batch-log" style="font-family:monospace;font-size:11px;line-height:1.6;color:var(--text-muted);max-height:200px;overflow-y:auto"></div>
    </div>

    <div class="card" id="task-status" data-persist-region="task-status" style="margin-top:20px;display:none">
      <div class="card-title">处理进度</div>
      <div id="task-log" style="font-family:monospace;font-size:12px;line-height:1.8;color:var(--text-muted)"></div>
    </div>

    <div class="card" id="task-result" data-persist-region="task-result" style="margin-top:20px;display:none">
      <div class="card-title">抽取结果</div>
      <div id="result-content"></div>
    </div>

    <div class="card" id="task-error" data-persist-region="task-error" style="margin-top:20px;display:none;border-left:4px solid var(--red)">
      <div class="card-title" style="color:var(--red)">处理失败</div>
      <div id="error-content"></div>
    </div>

    <div class="card" id="batch-summary" data-persist-region="batch-summary" style="margin-top:20px;display:none">
      <div class="card-title">批量处理结果</div>
      <div id="batch-summary-content"></div>
    </div>

    ${history.length > 0 ? `
    <div class="card" id="history-section" style="margin-top:20px">
      <div class="card-header" style="display:flex;justify-content:space-between;align-items:center">
        <span>处理历史（最近 ${history.length} 条）</span>
        <button class="btn btn-sm btn-outline" onclick="clearProcessHistory()" style="padding:4px 12px;font-size:12px">清空历史</button>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th style="width:120px">时间</th>
            <th>文件/URL</th>
            <th style="width:120px">来源</th>
            <th style="width:100px">状态</th>
            <th>结果</th>
          </tr>
        </thead>
        <tbody>
          ${historyRows}
        </tbody>
      </table>
    </div>` : ''}`;

  // 检查是否有预填参数（从数据缺口页面跳转过来）
  const prefillEntityId = sessionStorage.getItem('prefill_entity_id');
  const prefillYear = sessionStorage.getItem('prefill_year');
  const prefillPeriodType = sessionStorage.getItem('prefill_period_type') || 'calendar_year';
  const prefillUrl = sessionStorage.getItem('prefill_url');
  const prefillSourceTitle = sessionStorage.getItem('prefill_source_title');
  const prefillStationName = sessionStorage.getItem('prefill_station_name');

  // 从“发现官方来源”进入时，电站 ID 与名称已由详情页提供。先同步写入，
  // 不能等待全量电站列表的异步请求，否则用户会看到年份已填、电站为空。
  if (prefillEntityId && prefillStationName) {
    const searchInput = el('input-station-search');
    const hiddenInput = el('input-station-id');
    if (searchInput) searchInput.value = prefillStationName;
    if (hiddenInput) hiddenInput.value = prefillEntityId;
    sessionStorage.removeItem('prefill_station_name');
  }

  if (prefillUrl) {
    sessionStorage.removeItem('prefill_url');
    sessionStorage.removeItem('prefill_source_title');
    const urlInput = el('input-url');
    const titleInput = el('input-source-url');
    if (urlInput) urlInput.value = prefillUrl;
    if (titleInput) titleInput.value = prefillSourceTitle || 'GEM Wiki 发现来源';
  }

  if (prefillEntityId && prefillYear) {
    // 清除 sessionStorage
    sessionStorage.removeItem('prefill_entity_id');
    sessionStorage.removeItem('prefill_year');
    sessionStorage.removeItem('prefill_period_type');

    // 延迟执行，等待 DOM 渲染完成
    setTimeout(async () => {
      try {
        // 获取电站列表
        if (!stationSearchCache) {
          const result = await api().get_all_stations();
          stationSearchCache = result.stations;
        }

        // 查找对应的电站
        const station = stationSearchCache.find(s => s.entity_id === prefillEntityId);

        if (station) {
          // 自动填充电站
          const searchInput = el('input-station-search');
          const hiddenInput = el('input-station-id');
          if (searchInput && hiddenInput) {
            searchInput.value = station.name_zh || station.name_en || station.canonical_name || prefillStationName || prefillEntityId;
            hiddenInput.value = station.entity_id;
          }

          // 自动填充年份
          const yearInput = el('input-target-year');
          if (yearInput) {
            yearInput.value = prefillYear;
          }
          const periodTypeInput = el('input-period-type');
          if (periodTypeInput) {
            periodTypeInput.value = prefillPeriodType;
          }

          // 高亮提示
          const businessInfoCard = main.querySelector('.card');
          if (businessInfoCard) {
            businessInfoCard.style.boxShadow = '0 0 0 3px rgba(59, 130, 246, 0.3)';
            setTimeout(() => {
              businessInfoCard.style.boxShadow = '';
            }, 2000);
          }

          console.log(`已自动填充：${station.name_zh || station.name_en || station.canonical_name} (${prefillEntityId}) - ${prefillYear}年`);
        }
      } catch (e) {
        console.error('自动填充失败:', e);
      }
    }, 100);
  }
}

// 只刷新历史记录部分（不重新渲染整个页面）
function renderAddDataHistoryOnly() {
  const history = getProcessHistory();
  const existingSection = document.getElementById('history-section');

  if (history.length === 0) {
    // 没有历史记录，移除历史区域（如果存在）
    if (existingSection) {
      existingSection.remove();
    }
    return;
  }

  // 构建历史记录行
  const historyRows = history.map(h => {
    const statusBadge = h.success
      ? '<span class="badge" style="background:var(--green-bg);color:var(--green)">成功</span>'
      : '<span class="badge" style="background:var(--red-bg);color:var(--red)">失败</span>';
    const stageBadge = h.error_stage
      ? `<span class="badge" style="background:var(--border);color:var(--text-muted)">${h.error_stage}</span>`
      : '';
    const time = new Date(h.timestamp).toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    });
    const displayName = h.name || h.url || h.file_path || '-';
    const sourceDisplay = h.source_id || '-';
    const resultText = h.success
      ? `已保存 ${h.saved_count || 0} 条记录`
      : `${stageBadge} ${h.error_code || ''} ${h.error_message || ''}`;

    return `
      <tr>
        <td>${time}</td>
        <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(displayName)}">${esc(displayName)}</td>
        <td>${esc(sourceDisplay)}</td>
        <td>${statusBadge}</td>
        <td>${resultText}</td>
      </tr>
    `;
  }).join('');

  const historyHTML = `
    <div class="card" id="history-section" style="margin-top:20px">
      <div class="card-header" style="display:flex;justify-content:space-between;align-items:center">
        <span>处理历史（最近 ${history.length} 条）</span>
        <button class="btn btn-sm btn-outline" onclick="clearProcessHistory()" style="padding:4px 12px;font-size:12px">清空历史</button>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th style="width:120px">时间</th>
            <th>文件/URL</th>
            <th style="width:120px">来源</th>
            <th style="width:100px">状态</th>
            <th>结果</th>
          </tr>
        </thead>
        <tbody>
          ${historyRows}
        </tbody>
      </table>
    </div>
  `;

  if (existingSection) {
    // 替换现有的历史区域
    existingSection.outerHTML = historyHTML;
  } else {
    // 在页面末尾添加历史区域
    const mainContent = document.getElementById('main-content');
    if (mainContent) {
      const tempDiv = document.createElement('div');
      tempDiv.innerHTML = historyHTML;
      mainContent.appendChild(tempDiv.firstElementChild);
    }
  }
}

function currentDataMode() {
  return el('input-data-mode')?.value || 'production';
}

function updateDataModeHelp() {
  const mode = currentDataMode();
  const help = el('data-mode-help');
  if (!help) return;
  help.textContent = mode === 'test'
    ? '测试数据：使用独立数据库和文件目录，不会修改正式数据、Top 100 或正式统计。可随时清空。'
    : '正式数据：结果会写入正式数据库并参与后续统计。';
  const card = help.closest('.card');
  if (card) card.style.borderLeftColor = mode === 'test' ? '#f59e0b' : 'var(--primary)';
}

let stationSearchCache = null;
let stationDropdownTimeout = null;

async function handleStationSearch(event) {
  const query = event.target.value.trim();
  const dropdown = el('station-dropdown');

  if (query.length < 2) {
    dropdown.style.display = 'none';
    return;
  }

  if (!stationSearchCache) {
    try {
      const result = await api().get_all_stations();
      stationSearchCache = result.stations || [];
    } catch (e) {
      console.error('Failed to load stations:', e);
      dropdown.style.display = 'none';
      return;
    }
  }

  const filtered = stationSearchCache.filter(s =>
    s.name_zh.includes(query) || s.name_en?.toLowerCase().includes(query.toLowerCase()) || s.entity_id.includes(query)
  ).slice(0, 10);

  if (filtered.length === 0) {
    dropdown.innerHTML = '<div style="padding:8px;color:var(--text-muted);font-size:12px">无匹配结果</div>';
    dropdown.style.display = 'block';
    return;
  }

  dropdown.innerHTML = filtered.map(s => `
    <div class="station-option" data-id="${esc(s.entity_id)}" data-name="${esc(s.name_zh)}"
      onmousedown="selectStation('${esc(s.entity_id)}', '${esc(s.name_zh)}')"
      style="padding:8px;cursor:pointer;border-bottom:1px solid var(--border)"
      onmouseover="this.style.background='var(--hover-bg)'"
      onmouseout="this.style.background='transparent'">
      <div style="font-weight:500">${esc(s.name_zh)}</div>
      <div style="font-size:11px;color:var(--text-muted)">${esc(s.entity_id)}${s.name_en ? ' · ' + esc(s.name_en) : ''}</div>
    </div>
  `).join('');
  dropdown.style.display = 'block';
}

function showStationDropdown() {
  clearTimeout(stationDropdownTimeout);
}

function hideStationDropdown() {
  stationDropdownTimeout = setTimeout(() => {
    const dropdown = el('station-dropdown');
    if (dropdown) dropdown.style.display = 'none';
  }, 200);
}

function selectStation(entityId, name) {
  el('input-station-id').value = entityId;
  el('input-station-search').value = name;
  el('station-dropdown').style.display = 'none';
}

async function startBatchUpload() {
  const filesText = el('input-batch-files').value.trim();
  const source = el('input-source-batch').value.trim();
  const entityId = el('input-station-id')?.value.trim();
  const targetPeriod = el('input-target-year')?.value.trim();
  const periodType = el('input-period-type')?.value || 'calendar_year';

  if (!entityId || !targetPeriod) {
    alert('请先选择目标电站和年份');
    return;
  }
  if (!filesText || !source) {
    alert('请填写文件路径和来源标题');
    return;
  }

  batchUploadState.files = filesText.split('\n').map(f => f.trim()).filter(f => f);
  if (batchUploadState.files.length === 0) {
    alert('请输入至少一个文件路径');
    return;
  }

  batchUploadState.currentIndex = 0;
  batchUploadState.results = [];
  batchUploadState.cancelled = false;

  el('batch-progress').style.display = '';
  el('batch-summary').style.display = 'none';
  el('cancel-batch-btn').style.display = '';
  el('batch-log').innerHTML = '';

  updateBatchProgress();

  for (let i = 0; i < batchUploadState.files.length; i++) {
    if (batchUploadState.cancelled) {
      logBatch(`\n批量处理已取消（${i}/${batchUploadState.files.length}）`);
      break;
    }

    batchUploadState.currentIndex = i;
    const file = batchUploadState.files[i];
    updateBatchProgress();
    logBatch(`[${i + 1}/${batchUploadState.files.length}] 处理: ${file}`);

    try {
      const result = await processSingleFile(
        file, source, currentDataMode(), entityId, targetPeriod, periodType,
      );
      batchUploadState.results.push({ file, success: true, result });
      logBatch(`  ✓ 成功：保存 ${result.save_result?.saved || 0} 条记录`);

      // 添加到历史记录
      addToHistory({
        success: true,
        file_path: file,
        source_id: source,
        saved_count: result.save_result?.saved || 0,
        name: file.split(/[/\\]/).pop()
      });
    } catch (e) {
      batchUploadState.results.push({ file, success: false, error: String(e) });
      logBatch(`  ✗ 失败：${e}`);

      // 添加到历史记录
      addToHistory({
        success: false,
        file_path: file,
        source_id: source,
        error_stage: 'UNKNOWN',
        error_message: String(e),
        name: file.split(/[/\\]/).pop()
      });
    }
  }

  if (!batchUploadState.cancelled) {
    batchUploadState.currentIndex = batchUploadState.files.length;
    updateBatchProgress();

    // 批量处理完成后刷新历史记录
    renderAddDataHistoryOnly();
    showBatchSummary();
  }

  el('cancel-batch-btn').style.display = 'none';
}

async function processSingleFile(
  filePath, sourceTitle, dataMode = 'production',
  entityId, targetPeriod, periodType = 'calendar_year',
) {
  return new Promise((resolve, reject) => {
    if (!entityId || !targetPeriod) {
      reject(new Error('批量处理必须指定目标电站和目标年份'));
      return;
    }
    let taskResult = null;
    let taskError = null;
    let expectedTaskId = null;
    let checkInterval = null;
    let timeoutId = null;
    const previousHandler = window.onTaskEvent;

    // 旧批量入口需要等待自己的任务完成，但不能永久接管全局事件处理器。
    // 任务结束后恢复页面主处理器，避免后续 URL/文件任务只进入旧闭包。
    const taskHandler = function(event) {
      if (expectedTaskId && event.task_id && event.task_id !== expectedTaskId) {
        return;
      }
      if (event.type === 'complete') {
        const result = event.data?.result;
        if (result?.status === 'success' || result?.status === 'needs_review') {
          taskResult = result;
        } else {
          taskError = result?.error_message || result?.error || '未知错误';
        }
      } else if (event.type === 'error') {
        taskError = event.data?.error_message || event.data?.error || event.message || '未知错误';
      }
    };
    window.onTaskEvent = taskHandler;

    const cleanup = () => {
      if (checkInterval) clearInterval(checkInterval);
      if (timeoutId) clearTimeout(timeoutId);
      if (window.onTaskEvent === taskHandler) {
        window.onTaskEvent = previousHandler;
      }
    };

    api().start_task({
      type: 'upload_file',
      file_path: filePath,
      entity_id: entityId,
      target_period: targetPeriod,
      period_type: periodType,
      source_title: sourceTitle,
      metadata: {},
      data_mode: dataMode
    }).then(startResult => {
      if (!startResult || startResult.status === 'failed') {
        cleanup();
        reject(new Error(startResult?.error_message || '任务启动失败'));
        return;
      }
      expectedTaskId = startResult.task_id || null;
      // 等待任务完成
      checkInterval = setInterval(() => {
        if (taskResult) {
          cleanup();
          resolve(taskResult);
        } else if (taskError) {
          cleanup();
          reject(taskError);
        }
      }, 100);

      // 30 秒超时
      timeoutId = setTimeout(() => {
        cleanup();
        clearInterval(checkInterval);
        if (!taskResult && !taskError) {
          reject('处理超时');
        }
      }, 30000);
    }).catch(error => {
      cleanup();
      reject(error);
    });
  });
}

function updateBatchProgress() {
  const total = batchUploadState.files.length;
  const current = batchUploadState.currentIndex + 1;
  const percent = total > 0 ? Math.round((current / total) * 100) : 0;

  el('batch-progress-text').textContent = `${current} / ${total}`;
  el('batch-progress-bar').style.width = `${percent}%`;

  if (batchUploadState.cancelled) {
    el('batch-status-text').textContent = '已取消';
  } else if (current >= total) {
    el('batch-status-text').textContent = '完成';
  } else {
    el('batch-status-text').textContent = '处理中...';
  }
}

function logBatch(message) {
  const log = el('batch-log');
  log.innerHTML += esc(message) + '\n';
  log.scrollTop = log.scrollHeight;
}

function cancelBatchUpload() {
  if (confirm('确认取消批量处理？')) {
    batchUploadState.cancelled = true;
  }
}

function showBatchSummary() {
  const success = batchUploadState.results.filter(r => r.success).length;
  const failed = batchUploadState.results.filter(r => !r.success).length;
  const totalRecords = batchUploadState.results
    .filter(r => r.success)
    .reduce((sum, r) => sum + (r.result.save_result?.saved || 0), 0);

  const failedItems = batchUploadState.results
    .filter(r => !r.success)
    .map((r, i) => `
      <div style="padding:8px;margin-bottom:8px;background:var(--red-bg);border-left:4px solid var(--red);border-radius:4px">
        <div style="font-size:12px;color:var(--text-muted)">${esc(r.file)}</div>
        <div style="color:var(--red);font-size:13px;margin-top:4px">${esc(r.error)}</div>
      </div>
    `).join('');

  el('batch-summary').style.display = '';
  el('batch-summary-content').innerHTML = `
    <div class="grid-3" style="margin-bottom:16px">
      <div style="text-align:center">
        <div style="font-size:32px;font-weight:600;color:var(--green)">${success}</div>
        <div style="color:var(--text-muted);font-size:13px">成功</div>
      </div>
      <div style="text-align:center">
        <div style="font-size:32px;font-weight:600;color:var(--red)">${failed}</div>
        <div style="color:var(--text-muted);font-size:13px">失败</div>
      </div>
      <div style="text-align:center">
        <div style="font-size:32px;font-weight:600;color:var(--primary)">${totalRecords}</div>
        <div style="color:var(--text-muted);font-size:13px">总记录数</div>
      </div>
    </div>
    ${failed > 0 ? `<div style="margin-top:16px"><strong>失败项：</strong>${failedItems}</div>` : ''}
    <div style="margin-top:16px;text-align:center">
      <button class="btn btn-primary" onclick="navigate('review')">前往复核中心</button>
    </div>
  `;
}

// ---------- CSV 批量导入 ----------
function downloadCsvTemplate() {
  const template = `entity_id,canonical_name,period_label,period_type,metric,generation_gwh,value_raw,unit_raw,value_type,measurement_scope,confidence,source_url,publisher,publish_date
three_gorges_dam,三峡水电站,2024,calendar_year,gross_generation,103400,1034,亿千瓦时,actual,plant,0.9,https://example.com,三峡集团,2025-01-15
xiluodu_dam,溪洛渡水电站,2024,calendar_year,gross_generation,60800,608,亿千瓦时,actual,plant,0.9,https://example.com,三峡集团,2025-01-15`;

  const blob = new Blob([template], { type: 'text/csv;charset=utf-8;' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = 'generation_import_template.csv';
  link.click();
  URL.revokeObjectURL(link.href);
}

async function importCsvFile() {
  const fileInput = el('input-csv-file');
  const sourceTitle = el('input-csv-source').value.trim();

  if (!fileInput.files || fileInput.files.length === 0) {
    alert('请选择CSV文件');
    return;
  }

  if (!sourceTitle) {
    alert('请输入来源标题');
    return;
  }

  const file = fileInput.files[0];

  // 显示进度
  const progressDiv = el('batch-progress');
  const statusDiv = el('batch-status-text');
  const logDiv = el('batch-log');

  progressDiv.style.display = 'block';
  statusDiv.textContent = '正在读取文件...';
  logDiv.innerHTML = '';

  try {
    // 读取文件内容
    const csvContent = await file.text();

    statusDiv.textContent = '正在导入数据...';
    logDiv.innerHTML += `<div>[${new Date().toLocaleTimeString()}] 开始导入 ${file.name}</div>`;

    // 调用API
    const result = await api().import_csv_batch(csvContent, sourceTitle);

    if (result.success) {
      logDiv.innerHTML += `<div style="color:var(--green)">[${new Date().toLocaleTimeString()}] 导入成功：${result.imported_count} 条记录</div>`;

      if (result.skipped_count > 0) {
        logDiv.innerHTML += `<div style="color:var(--yellow)">[${new Date().toLocaleTimeString()}] 跳过：${result.skipped_count} 条记录</div>`;
      }

      if (result.errors && result.errors.length > 0) {
        logDiv.innerHTML += `<div style="color:var(--red)">[${new Date().toLocaleTimeString()}] 错误信息：</div>`;
        result.errors.forEach(err => {
          logDiv.innerHTML += `<div style="color:var(--red);margin-left:16px">- ${esc(err)}</div>`;
        });
      }

      statusDiv.textContent = '导入完成';

      // 显示汇总
      const summaryDiv = el('batch-summary');
      const summaryContent = el('batch-summary-content');
      summaryDiv.style.display = 'block';
      summaryContent.innerHTML = `
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:16px">
          <div style="text-align:center">
            <div style="font-size:32px;font-weight:600;color:var(--green)">${result.imported_count}</div>
            <div style="color:var(--text-muted);font-size:13px">成功导入</div>
          </div>
          <div style="text-align:center">
            <div style="font-size:32px;font-weight:600;color:var(--yellow)">${result.skipped_count}</div>
            <div style="color:var(--text-muted);font-size:13px">跳过</div>
          </div>
          <div style="text-align:center">
            <div style="font-size:32px;font-weight:600;color:var(--primary)">${result.imported_count + result.skipped_count}</div>
            <div style="color:var(--text-muted);font-size:13px">总计</div>
          </div>
        </div>
        <div style="text-align:center">
          <button class="btn btn-primary" onclick="navigate('review')">前往复核中心</button>
        </div>
      `;

      // 清空输入
      fileInput.value = '';

      // 保存历史
      saveProcessHistory({
        timestamp: Date.now(),
        file_path: file.name,
        source_id: 'csv_import',
        success: true,
        saved_count: result.imported_count,
        name: file.name
      });

    } else {
      logDiv.innerHTML += `<div style="color:var(--red)">[${new Date().toLocaleTimeString()}] 导入失败</div>`;

      if (result.errors && result.errors.length > 0) {
        result.errors.forEach(err => {
          logDiv.innerHTML += `<div style="color:var(--red)">- ${esc(err)}</div>`;
        });
      }

      statusDiv.textContent = '导入失败';
      alert('CSV导入失败：' + (result.errors?.[0] || '未知错误'));

      // 保存历史
      saveProcessHistory({
        timestamp: Date.now(),
        file_path: file.name,
        source_id: 'csv_import',
        success: false,
        error_message: result.errors?.[0] || '未知错误',
        error_stage: 'import',
        name: file.name
      });
    }

  } catch (e) {
    logDiv.innerHTML += `<div style="color:var(--red)">[${new Date().toLocaleTimeString()}] 异常：${esc(e)}</div>`;
    statusDiv.textContent = '导入失败';
    alert('CSV导入异常：' + e);

    // 保存历史
    saveProcessHistory({
      timestamp: Date.now(),
      file_path: file.name,
      source_id: 'csv_import',
      success: false,
      error_message: String(e),
      error_stage: 'exception',
      name: file.name
    });
  }
}

async function startDownloadTask() {
  const url = el('input-url').value.trim();
  const source = el('input-source-url').value.trim();
  const entityId = el('input-station-id').value.trim();
  const targetYear = el('input-target-year').value.trim();
  const periodType = (el('input-period-type')?.value || 'calendar_year');

  if (!entityId || !targetYear) {
    alert('请先选择目标电站和年份');
    return;
  }

  if (!url || !source) {
    alert('请填写 URL 和来源标题');
    return;
  }

  el('task-status').style.display = '';
  el('task-result').style.display = 'none';
  el('task-error').style.display = 'none';
  el('task-log').innerHTML = '正在启动任务...';

  try {
    const result = await api().start_task({
      entity_id: entityId,
      target_period: targetYear,
      period_type: periodType,
      type: 'download_url',
      url: url,
      source_title: source,
      metadata: {},
      data_mode: currentDataMode()
    });

    if (result.status === 'failed') {
      showTaskError('PIPELINE', result.failure_stage || 'UNKNOWN', result.error_message || '任务失败');
      addToHistory({
        timestamp: new Date().toISOString(),
        url: url,
        source_id: source,
        success: false,
        error_stage: result.failure_stage,
        error_message: result.error_message
      });
      return;
    }

    el('task-log').innerHTML = formatPipelineResult(result);

    if (result.status === 'needs_review') {
      el('task-result').style.display = '';
      el('result-content').innerHTML = `
        <div style="padding:12px;background:var(--warning-bg);border-radius:var(--radius-sm);margin-bottom:12px">
          <strong>⚠️ 需要人工复核</strong>
          <p style="margin:8px 0 0 0;font-size:13px">数据已抽取完成，请前往 <a href="#" onclick="navigate('review');return false" style="color:var(--primary)">复核中心</a> 进行审核</p>
        </div>
        ${formatExtractedData(result.extracted_data || [])}
      `;
    } else if (result.status === 'success') {
      el('task-result').style.display = '';
      el('result-content').innerHTML = `
        <div style="padding:12px;background:var(--green-bg);border-radius:var(--radius-sm);margin-bottom:12px">
          <strong>✓ 处理成功</strong>
          <p style="margin:8px 0 0 0;font-size:13px">已保存 ${result.saved_count || 0} 条记录</p>
        </div>
      `;
    }

    addToHistory({
      timestamp: new Date().toISOString(),
      url: url,
      source_id: source,
      success: result.status === 'success' || result.status === 'needs_review',
      saved_count: result.saved_count,
      error_stage: result.failure_stage,
      error_message: result.error_message
    });

  } catch (e) {
    showTaskError('UNKNOWN', 'TASK_START_FAILED', '启动任务失败：' + e);
    addToHistory({
      timestamp: new Date().toISOString(),
      url: url,
      source_id: source,
      success: false,
      error_stage: 'TASK_START',
      error_message: String(e)
    });
  }
}

async function startSingleFileTask() {
  const filePath = el('input-single-file').value.trim();
  const source = el('input-source-file').value.trim();
  const entityId = el('input-station-id').value.trim();
  const targetYear = el('input-target-year').value.trim();
  const periodType = (el('input-period-type')?.value || 'calendar_year');

  if (!entityId || !targetYear) {
    alert('请先选择目标电站和年份');
    return;
  }

  if (!filePath || !source) {
    alert('请填写文件路径和来源标题');
    return;
  }

  el('task-status').style.display = '';
  el('task-result').style.display = 'none';
  el('task-error').style.display = 'none';
  el('task-log').innerHTML = '正在启动任务...';

  try {
    const result = await api().start_task({
      entity_id: entityId,
      target_period: targetYear,
      period_type: periodType,
      type: 'upload_file',
      file_path: filePath,
      source_title: source,
      metadata: {},
      data_mode: currentDataMode()
    });

    if (result.status === 'failed') {
      showTaskError('PIPELINE', result.failure_stage || 'UNKNOWN', result.error_message || '任务失败');
      addToHistory({
        timestamp: new Date().toISOString(),
        file_path: filePath,
        source_id: source,
        success: false,
        error_stage: result.failure_stage,
        error_message: result.error_message
      });
      return;
    }

    el('task-log').innerHTML = formatPipelineResult(result);

    if (result.status === 'needs_review') {
      el('task-result').style.display = '';
      el('result-content').innerHTML = `
        <div style="padding:12px;background:var(--warning-bg);border-radius:var(--radius-sm);margin-bottom:12px">
          <strong>⚠️ 需要人工复核</strong>
          <p style="margin:8px 0 0 0;font-size:13px">数据已抽取完成，请前往 <a href="#" onclick="navigate('review');return false" style="color:var(--primary)">复核中心</a> 进行审核</p>
        </div>
        ${formatExtractedData(result.extracted_data || [])}
      `;
    } else if (result.status === 'success') {
      el('task-result').style.display = '';
      el('result-content').innerHTML = `
        <div style="padding:12px;background:var(--green-bg);border-radius:var(--radius-sm);margin-bottom:12px">
          <strong>✓ 处理成功</strong>
          <p style="margin:8px 0 0 0;font-size:13px">已保存 ${result.saved_count || 0} 条记录</p>
        </div>
      `;
    }

    addToHistory({
      timestamp: new Date().toISOString(),
      file_path: filePath,
      source_id: source,
      success: result.status === 'success' || result.status === 'needs_review',
      saved_count: result.saved_count,
      error_stage: result.failure_stage,
      error_message: result.error_message
    });

  } catch (e) {
    showTaskError('UNKNOWN', 'TASK_START_FAILED', '启动任务失败：' + e);
    addToHistory({
      timestamp: new Date().toISOString(),
      file_path: filePath,
      source_id: source,
      success: false,
      error_stage: 'TASK_START',
      error_message: String(e)
    });
  }
}

function formatPipelineResult(result) {
  if (!result) return '无结果';

  const lines = ['<div style="font-family:monospace;font-size:12px;line-height:1.8">'];

  lines.push(`<div><strong>任务状态：</strong>${formatStatus(result.status)}</div>`);

  if (result.task_id) {
    lines.push(`<div><strong>任务 ID：</strong>${esc(result.task_id)}</div>`);
  }

  if (result.stage_results) {
    lines.push('<div style="margin-top:8px"><strong>Pipeline 执行阶段：</strong></div>');
    for (const [stage, stageResult] of Object.entries(result.stage_results)) {
      const icon = stageResult.success ? '✓' : '✗';
      const color = stageResult.success ? 'var(--green)' : 'var(--red)';
      lines.push(`<div style="margin-left:16px;color:${color}">${icon} ${stage}</div>`);
      if (stageResult.message) {
        lines.push(`<div style="margin-left:32px;font-size:11px;color:var(--text-muted)">${esc(stageResult.message)}</div>`);
      }
    }
  }

  if (result.failure_stage) {
    lines.push(`<div style="margin-top:8px;color:var(--red)"><strong>失败阶段：</strong>${esc(result.failure_stage)}</div>`);
  }

  if (result.error_message) {
    lines.push(`<div style="margin-top:8px;color:var(--red)"><strong>错误信息：</strong>${esc(result.error_message)}</div>`);
  }

  lines.push('</div>');
  return lines.join('');
}

function formatStatus(status) {
  const statusMap = {
    'success': '<span style="color:var(--green)">✓ 成功</span>',
    'failed': '<span style="color:var(--red)">✗ 失败</span>',
    'needs_review': '<span style="color:var(--warning)">⚠ 待复核</span>',
    'running': '<span style="color:var(--primary)">⟳ 运行中</span>',
    'pending': '<span style="color:var(--text-muted)">○ 待处理</span>'
  };
  return statusMap[status] || esc(status);
}

function formatExtractedData(records) {
  if (!records || records.length === 0) {
    return '<div style="padding:12px;color:var(--text-muted)">无抽取数据</div>';
  }

  const rows = records.map(r => `
    <tr>
      <td>${esc(r.entity_id || '-')}</td>
      <td>${esc(r.indicator || '-')}</td>
      <td>${esc(r.target_period || '-')}</td>
      <td>${esc(r.value || '-')}</td>
      <td>${esc(r.unit || '-')}</td>
    </tr>
  `).join('');

  return `
    <table class="data-table" style="width:100%;font-size:12px">
      <thead>
        <tr>
          <th>电站 ID</th>
          <th>指标</th>
          <th>年份</th>
          <th>数值</th>
          <th>单位</th>
        </tr>
      </thead>
      <tbody>
        ${rows}
      </tbody>
    </table>
  `;
}

function showTaskError(stage, code, message) {
  el('task-error').style.display = '';
  el('error-content').innerHTML = `
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
      <span class="badge-status st-missing">${esc(stage)}</span>
      <strong style="color:var(--red)">${esc(code)}</strong>
    </div>
    <div style="color:var(--text)">${esc(message)}</div>`;
}

// 接收后台事件
window.onTaskEvent = function(event) {
  const log = el('task-log');
  if (!log) return;

  if (event.type === 'progress') {
    log.innerHTML += '<br>' + esc(event.message);
  } else if (event.type === 'state_change') {
    const stage = (event.data.stage || '').toUpperCase();
    log.innerHTML += '<br><span class="badge-status st-neutral" style="margin-right:8px">' + stage + '</span>' + esc(event.message);
  } else if (event.type === 'complete') {
    const result = event.data.result;
    if (result.status === 'success') {
      log.innerHTML += '<br><strong style="color:var(--green)">✓ 任务完成</strong>';
      displayTaskResult(result);

      // 添加到历史记录
      addToHistory({
        success: true,
        url: el('input-url')?.value,
        file_path: null,
        source_id: el('input-source-url')?.value,
        saved_count: result.save_result?.saved || 0,
        name: result.name || (el('input-url')?.value?.split('/').pop())
      });

      // 刷新历史记录显示（延迟 1 秒让用户看到任务完成提示）
      setTimeout(() => {
        renderAddDataHistoryOnly();
      }, 1000);
    } else if (result.status === 'failed') {
      const failureStage = result.failure_stage || result.error_stage || 'UNKNOWN';
      const failureCode = result.error_code || 'PIPELINE_FAILED';
      const failureMessage = result.error || result.error_message || 'Pipeline 未返回失败原因';
      showTaskError(failureStage, failureCode, failureMessage);

      // 添加到历史记录
      addToHistory({
        success: false,
        url: el('input-url')?.value,
        file_path: null,
        source_id: el('input-source-url')?.value,
        error_stage: failureStage,
        error_code: failureCode,
        error_message: failureMessage,
        name: result.name || (el('input-url')?.value?.split('/').pop())
      });

      // 刷新历史记录显示（延迟 1 秒让用户看到错误提示）
      setTimeout(() => {
        renderAddDataHistoryOnly();
      }, 1000);
    }
  } else if (event.type === 'error') {
    showTaskError('UNKNOWN', event.data.error_type || 'ERROR', event.message);

    // 添加到历史记录
    addToHistory({
      success: false,
      url: el('input-url')?.value,
      file_path: null,
      source_id: el('input-source-url')?.value,
      error_stage: 'UNKNOWN',
      error_code: event.data.error_type || 'ERROR',
      error_message: event.message,
      name: (el('input-url')?.value?.split('/').pop()) || 'unknown'
    });

    // 刷新历史记录显示
    setTimeout(() => {
      renderAddDataHistoryOnly();
    }, 1000);
  }
};

function displayTaskResult(result) {
  el('task-result').style.display = '';
  const candidates = result.candidates || [];
  const saveResult = result.save_result || {};

  let html = `<p style="margin-bottom:12px">
    共抽取 <strong>${candidates.length}</strong> 条候选记录，
    已保存 <strong style="color:var(--green)">${saveResult.saved || 0}</strong> 条到数据库`;

  if (saveResult.needs_review > 0) {
    html += `，其中 <strong style="color:var(--orange)">${saveResult.needs_review}</strong> 条需要复核`;
  }
  if (saveResult.skipped > 0) {
    html += `，跳过 ${saveResult.skipped} 条（无效或重复）`;
  }
  html += `</p>`;

  candidates.forEach((c, i) => {
    const confClass = c.confidence === 'high' ? 'st-published' : 'st-review';
    html += `
      <div style="padding:12px;margin-bottom:10px;border:1px solid var(--border);border-radius:var(--radius-sm)">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
          <strong>#${i + 1}</strong>
          <span class="badge-status ${confClass}">${c.confidence === 'high' ? '高置信度' : '低置信度'}</span>
        </div>
        <div style="font-size:13px;line-height:1.6">
          <div>发电量: <strong style="color:var(--primary)">${c.generation_gwh || 'N/A'} GWh</strong></div>
          <div>原始值: ${esc(c.value_raw)} ${esc(c.unit_raw)}</div>
          ${c.warnings.length > 0 ? `<div style="color:var(--orange)">警告: ${esc(c.warnings.join(', '))}</div>` : ''}
          <div style="color:var(--text-muted);font-size:12px;margin-top:4px">摘录: ${esc(c.snippet)}</div>
        </div>
      </div>`;
  });

  el('result-content').innerHTML = html;
}

// ---------- 统计分析 ----------
async function renderStats() {
  const main = el('main-content');
  main.innerHTML = '<div class="spinner">加载统计数据…</div>';
  let coverage;
  try {
    coverage = await api().get_data_coverage_stats();
  }
  catch (e) { main.innerHTML = `<div class="empty">加载失败：${esc(e)}</div>`; return; }

  const overall = coverage.overall;
  const coverageRate = overall.total_stations > 0
    ? ((overall.stations_with_data / overall.total_stations) * 100).toFixed(1)
    : 0;

  const countryRows = coverage.by_country.slice(0, 10).map(c => {
    const rate = c.total_stations > 0
      ? ((c.stations_with_data / c.total_stations) * 100).toFixed(0)
      : 0;
    const barWidth = rate;
    return `<tr>
      <td><strong>${esc(c.country)}</strong></td>
      <td style="text-align:right">${c.total_stations}</td>
      <td style="text-align:right">${c.stations_with_data}</td>
      <td style="text-align:right"><strong>${rate}%</strong></td>
      <td style="width:150px">
        <div style="width:100%;height:20px;background:var(--border);border-radius:4px;overflow:hidden">
          <div style="width:${barWidth}%;height:100%;background:var(--primary);transition:width 0.3s"></div>
        </div>
      </td>
    </tr>`;
  }).join('');

  // 数据质量分析
  const qualityHtml = `
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:20px">
      <div class="card" style="text-align:center">
        <div style="font-size:48px;font-weight:600;color:var(--primary)">${fmt(overall.total_records)}</div>
        <div style="color:var(--text-muted);margin-top:8px">总记录数</div>
      </div>
      <div class="card" style="text-align:center">
        <div style="font-size:48px;font-weight:600;color:var(--green)">${coverageRate}%</div>
        <div style="color:var(--text-muted);margin-top:8px">电站覆盖率</div>
      </div>
      <div class="card" style="text-align:center">
        <div style="font-size:48px;font-weight:600;color:var(--primary)">${fmt(overall.stations_with_data)}</div>
        <div style="color:var(--text-muted);margin-top:8px">已覆盖电站</div>
      </div>
    </div>`;

  main.innerHTML = `
    <div class="page-header">
      <div>
        <div class="page-title">统计分析</div>
        <div class="page-subtitle">数据覆盖率、质量分析与趋势报告</div>
      </div>
      <div>
        <button class="btn btn-outline" onclick="exportStatsReport()">导出统计报告</button>
      </div>
    </div>

    ${qualityHtml}

    <div class="grid-2" style="margin-bottom:20px">
      <div class="card">
        <div class="card-title">按年份统计</div>
        <div id="chart-year" style="width:100%;height:300px"></div>
      </div>
      <div class="card">
        <div class="card-title">数据覆盖率分布</div>
        <div id="chart-coverage" style="width:100%;height:300px"></div>
      </div>
    </div>

    <div class="grid-2" style="margin-bottom:20px">
      <div class="card">
        <div class="card-title">Top 10 国家覆盖率</div>
        <div id="chart-country-bar" style="width:100%;height:300px"></div>
      </div>
      <div class="card">
        <div class="card-title">记录数分布</div>
        <div id="chart-records-pie" style="width:100%;height:300px"></div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">国家详细统计（Top 10）</div>
      <table>
        <thead>
          <tr>
            <th>国家</th>
            <th style="text-align:right">总电站数</th>
            <th style="text-align:right">有数据</th>
            <th style="text-align:right">覆盖率</th>
            <th style="width:150px">进度</th>
          </tr>
        </thead>
        <tbody>${countryRows}</tbody>
      </table>
    </div>`;

  // 渲染ECharts图表
  renderYearChart(coverage.by_year);
  renderCoverageChart(coverage.by_country);
  renderCountryBarChart(coverage.by_country);
  renderRecordsPieChart(coverage.by_country);
}

// ---------- ECharts 图表渲染 ----------
function renderYearChart(yearData) {
  const chartDom = el('chart-year');
  if (!chartDom || !window.echarts) return;

  const chart = echarts.init(chartDom);
  const option = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' }
    },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category',
      data: yearData.map(y => y.year),
      axisLine: { lineStyle: { color: '#e3e8f0' } },
      axisLabel: { color: '#6b7899' }
    },
    yAxis: {
      type: 'value',
      axisLine: { lineStyle: { color: '#e3e8f0' } },
      axisLabel: { color: '#6b7899' },
      splitLine: { lineStyle: { color: '#e3e8f0' } }
    },
    series: [{
      name: '记录数',
      type: 'bar',
      data: yearData.map(y => y.record_count),
      itemStyle: {
        color: '#2f66f5',
        borderRadius: [4, 4, 0, 0]
      },
      label: {
        show: true,
        position: 'top',
        color: '#6b7899',
        fontSize: 11
      }
    }]
  };
  chart.setOption(option);
}

function renderCoverageChart(countryData) {
  const chartDom = el('chart-coverage');
  if (!chartDom || !window.echarts) return;

  const chart = echarts.init(chartDom);

  // 按覆盖率分组：0-20%, 20-40%, 40-60%, 60-80%, 80-100%
  const ranges = [
    { label: '0-20%', min: 0, max: 20, count: 0 },
    { label: '20-40%', min: 20, max: 40, count: 0 },
    { label: '40-60%', min: 40, max: 60, count: 0 },
    { label: '60-80%', min: 60, max: 80, count: 0 },
    { label: '80-100%', min: 80, max: 100, count: 0 }
  ];

  countryData.forEach(c => {
    const rate = c.total_stations > 0 ? (c.stations_with_data / c.total_stations) * 100 : 0;
    for (const range of ranges) {
      if (rate >= range.min && rate < range.max) {
        range.count++;
        break;
      }
      if (rate === 100 && range.max === 100) {
        range.count++;
        break;
      }
    }
  });

  const option = {
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c} 个国家 ({d}%)'
    },
    legend: {
      orient: 'vertical',
      right: '10%',
      top: 'center',
      textStyle: { color: '#6b7899' }
    },
    series: [{
      name: '覆盖率分布',
      type: 'pie',
      radius: ['40%', '70%'],
      center: ['35%', '50%'],
      data: ranges.map(r => ({ value: r.count, name: r.label })),
      itemStyle: {
        borderRadius: 4,
        borderColor: '#fff',
        borderWidth: 2
      },
      label: {
        color: '#6b7899',
        fontSize: 12
      },
      emphasis: {
        itemStyle: {
          shadowBlur: 10,
          shadowOffsetX: 0,
          shadowColor: 'rgba(0, 0, 0, 0.5)'
        }
      }
    }]
  };
  chart.setOption(option);
}

function renderCountryBarChart(countryData) {
  const chartDom = el('chart-country-bar');
  if (!chartDom || !window.echarts) return;

  const chart = echarts.init(chartDom);
  const top10 = countryData.slice(0, 10);

  const option = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: function(params) {
        const p = params[0];
        const country = top10[p.dataIndex];
        return `${p.axisValue}<br/>覆盖率: ${p.value}%<br/>已覆盖: ${country.stations_with_data}/${country.total_stations}`;
      }
    },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'value',
      max: 100,
      axisLabel: { formatter: '{value}%', color: '#6b7899' },
      axisLine: { lineStyle: { color: '#e3e8f0' } },
      splitLine: { lineStyle: { color: '#e3e8f0' } }
    },
    yAxis: {
      type: 'category',
      data: top10.map(c => c.country),
      axisLine: { lineStyle: { color: '#e3e8f0' } },
      axisLabel: { color: '#6b7899' }
    },
    series: [{
      name: '覆盖率',
      type: 'bar',
      data: top10.map(c => {
        const rate = c.total_stations > 0 ? ((c.stations_with_data / c.total_stations) * 100).toFixed(1) : 0;
        return parseFloat(rate);
      }),
      itemStyle: {
        color: '#21a366',
        borderRadius: [0, 4, 4, 0]
      },
      label: {
        show: true,
        position: 'right',
        formatter: '{c}%',
        color: '#6b7899',
        fontSize: 11
      }
    }]
  };
  chart.setOption(option);
}

function renderRecordsPieChart(countryData) {
  const chartDom = el('chart-records-pie');
  if (!chartDom || !window.echarts) return;

  const chart = echarts.init(chartDom);
  const top5 = countryData.slice(0, 5);
  const othersCount = countryData.slice(5).reduce((sum, c) => sum + c.stations_with_data, 0);

  const data = top5.map(c => ({ value: c.stations_with_data, name: c.country }));
  if (othersCount > 0) {
    data.push({ value: othersCount, name: '其他国家' });
  }

  const option = {
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c} 个电站 ({d}%)'
    },
    legend: {
      orient: 'vertical',
      right: '10%',
      top: 'center',
      textStyle: { color: '#6b7899' }
    },
    series: [{
      name: '有数据电站数',
      type: 'pie',
      radius: '60%',
      center: ['35%', '50%'],
      data: data,
      itemStyle: {
        borderRadius: 4,
        borderColor: '#fff',
        borderWidth: 2
      },
      label: {
        color: '#6b7899',
        fontSize: 12
      },
      emphasis: {
        itemStyle: {
          shadowBlur: 10,
          shadowOffsetX: 0,
          shadowColor: 'rgba(0, 0, 0, 0.5)'
        }
      }
    }]
  };
  chart.setOption(option);
}

function exportStatsReport() {
  api().get_data_coverage_stats().then(coverage => {
    const lines = [
      '# 全球水电数据平台 - 统计报告',
      '',
      '## 总体统计',
      `- 总电站数：${coverage.overall.total_stations}`,
      `- 已覆盖电站：${coverage.overall.stations_with_data}`,
      `- 总记录数：${coverage.overall.total_records}`,
      `- 覆盖率：${((coverage.overall.stations_with_data / coverage.overall.total_stations) * 100).toFixed(1)}%`,
      '',
      '## 按年份统计',
      ''
    ].concat(
      coverage.by_year.map(y => `- ${y.year}: ${y.record_count} 条记录，覆盖 ${y.station_count} 座电站`)
    ).concat([
      '',
      '## 按国家统计（Top 20）',
      ''
    ]).concat(
      coverage.by_country.map(c => {
        const rate = ((c.stations_with_data / c.total_stations) * 100).toFixed(1);
        return `- ${c.country}: ${c.stations_with_data} / ${c.total_stations} (${rate}%)`;
      })
    ).concat([
      '',
      `报告生成时间：${new Date().toLocaleString('zh-CN')}`
    ]);

    const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `统计报告_${new Date().toISOString().split('T')[0]}.md`;
    link.click();
  });
}

// ---------- 复核中心 ----------
let reviewState = { selected: new Set(), filter: 'all' };

async function renderReview() {
  const main = el('main-content');
  main.innerHTML = '<div class="spinner">加载待复核记录…</div>';
  let res;
  try {
    const status = reviewState.filter === 'all' ? null : reviewState.filter;
    res = await api().list_review_items(status, 100, 0);
  }
  catch (e) { main.innerHTML = `<div class="empty">加载失败：${esc(e)}</div>`; return; }

  // 返回本页或刷新列表时保留仍然存在的勾选项；已不在本次结果中的项自动移除。
  const visibleReviewIds = new Set(res.items.map(item => item.id));
  reviewState.selected = new Set(
    Array.from(reviewState.selected).filter(id => visibleReviewIds.has(id))
  );

  const rows = res.items.length ? res.items.map(r => {
    const [sl, sc] = statusLabel(r.publication_status, r.review_status);
    const confClass = r.confidence === 'high' ? 'st-published' : 'st-review';
    const reviewId = String(r.id);
    const reviewIdLiteral = JSON.stringify(reviewId);
    return `<tr class="clickable" onclick='viewReviewDetail(${reviewIdLiteral})'>
      <td><input type="checkbox" data-review-id="${esc(reviewId)}" onclick='event.stopPropagation();toggleReviewSelect(${reviewIdLiteral})' id="check-${esc(reviewId)}" ${reviewState.selected.has(reviewId) ? 'checked' : ''}></td>
      <td><strong>${esc(reviewId)}</strong></td>
      <td>${esc(r.canonical_name || 'unknown')}</td>
      <td>${esc(r.period_label)}</td>
      <td><strong>${fmt(r.generation_gwh)}</strong> GWh</td>
      <td><span class="badge-status ${confClass}">${r.confidence === 'high' ? '高置信度' : '低置信度'}</span></td>
      <td><span class="badge-status ${sc}">${sl}</span></td>
      <td>${esc(r.source_title || '—')}</td>
      <td onclick="event.stopPropagation()"><button class="btn btn-outline btn-sm" onclick='viewReviewDetail(${reviewIdLiteral})'>查看并复核</button></td>
    </tr>`;
  }).join('') : '';

  const batchBar = reviewState.selected.size > 0 ? `
    <div style="position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:var(--card);padding:12px 20px;border-radius:999px;box-shadow:0 4px 12px rgba(0,0,0,0.15);display:flex;align-items:center;gap:12px;z-index:100">
      <span>已选 <strong>${reviewState.selected.size}</strong> 条</span>
      <button class="btn btn-outline btn-sm" onclick="batchApprove()">批量通过</button>
      <button class="btn btn-outline btn-sm" onclick="batchReject()">批量拒绝</button>
      <button class="btn btn-outline btn-sm" onclick="clearReviewSelection()">取消</button>
    </div>` : '';

  main.innerHTML = `
    <div class="page-header">
      <div>
        <div class="page-title">复核中心</div>
        <div class="page-subtitle">审核新增数据，决定是否发布 · 共 ${fmt(res.total)} 条待复核</div>
      </div>
      <div style="display:flex;gap:8px">
        <select id="review-filter" onchange="filterReview()" style="padding:8px;border:1px solid var(--border);border-radius:var(--radius-sm)">
          <option value="all" ${reviewState.filter === 'all' ? 'selected' : ''}>全部</option>
          <option value="draft" ${reviewState.filter === 'draft' ? 'selected' : ''}>草稿</option>
          <option value="needs_review" ${reviewState.filter === 'needs_review' ? 'selected' : ''}>待复核</option>
          <option value="has_warnings" ${reviewState.filter === 'has_warnings' ? 'selected' : ''}>有警告</option>
        </select>
        <button class="btn btn-outline" onclick="exportReviewList()">导出列表</button>
      </div>
    </div>
    ${res.items.length ? `<div class="card" style="padding:0"><table>
      <thead><tr><th style="width:40px"><input type="checkbox" onclick="toggleSelectAll()" id="select-all" ${res.items.length && reviewState.selected.size === res.items.length ? 'checked' : ''}></th><th>ID</th><th>水电站</th><th>年份</th><th>发电量</th>
        <th>置信度</th><th>状态</th><th>来源</th><th>操作</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`
      : `<div class="card"><div class="empty">当前没有待复核记录<br><span style="font-size:12px">
        新增数据会自动出现在这里等待复核</span></div></div>`}
    ${batchBar}`;
}

function toggleReviewSelect(id) {
  if (reviewState.selected.has(id)) {
    reviewState.selected.delete(id);
  } else {
    reviewState.selected.add(id);
  }
  renderReview();
}

function toggleSelectAll() {
  const checkboxes = document.querySelectorAll('input[id^="check-"]');
  const allChecked = reviewState.selected.size === checkboxes.length;
  if (allChecked) {
    reviewState.selected.clear();
  } else {
    checkboxes.forEach(cb => {
      const id = cb.dataset.reviewId;
      reviewState.selected.add(id);
    });
  }
  renderReview();
}

function clearReviewSelection() {
  reviewState.selected.clear();
  renderReview();
}

function filterReview() {
  reviewState.filter = el('review-filter').value;
  renderReview();
}

async function batchApprove() {
  if (!confirm(`确认通过 ${reviewState.selected.size} 条记录？`)) return;
  const ids = Array.from(reviewState.selected);
  let success = 0, failed = 0;
  for (const id of ids) {
    try {
      const result = await api().approve_record(id);
      ensureReviewActionSuccess(result);
      success++;
    } catch (e) {
      failed++;
      console.error(`批量通过失败 ID=${id}:`, e);
    }
  }
  alert(`批量操作完成：成功 ${success} 条，失败 ${failed} 条`);
  reviewState.selected.clear();
  renderReview();
}

async function batchReject() {
  const reason = prompt('拒绝原因（可选）：');
  if (reason === null) return;
  const ids = Array.from(reviewState.selected);
  let success = 0, failed = 0;
  for (const id of ids) {
    try {
      const result = await api().reject_record(id, reason || '批量拒绝');
      ensureReviewActionSuccess(result);
      success++;
    } catch (e) {
      failed++;
      console.error(`批量拒绝失败 ID=${id}:`, e);
    }
  }
  alert(`批量操作完成：成功 ${success} 条，失败 ${failed} 条`);
  reviewState.selected.clear();
  renderReview();
}

function exportReviewList() {
  // 简单 CSV 导出
  api().list_review_items(null, 1000, 0).then(res => {
    const csv = ['ID,水电站,年份,发电量(GWh),置信度,状态,来源']
      .concat(res.items.map(r =>
        `${r.id},"${r.canonical_name || 'unknown'}",${r.period_label},${r.generation_gwh},${r.confidence === 'high' ? '高' : '低'},"${r.publication_status}","${r.source_title || ''}"`
      ))
      .join('\n');
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `复核记录_${new Date().toISOString().split('T')[0]}.csv`;
    link.click();
  });
}

async function viewReviewDetail(recordId) {
  // 使用模态框显示详情，而不是全页面跳转
  showModal('加载中...', '<div class="spinner">加载详情…</div>', { width: '900px' });

  let d;
  try { d = await api().get_review_detail(recordId); }
  catch (e) {
    showModal('错误', `<div class="empty">加载失败：${esc(e)}</div>`);
    return;
  }
  if (!d) {
    showModal('错误', '<div class="empty">未找到该记录</div>');
    return;
  }

  const [sl, sc] = statusLabel(d.publication_status, d.review_status);
  const reviewIdLiteral = JSON.stringify(String(d.id));
  const ocrMeta = d.evidence_metadata && d.evidence_metadata.ocr;
  const ocrRegion = ocrMeta && ocrMeta.region
    ? Object.entries(ocrMeta.region).map(([k, v]) => `${k}=${v}`).join(', ')
    : '整页';

  const content = `
    <div class="grid-2" style="gap:16px">
      <div class="card">
        <div class="card-title">抽取结果</div>
        <table>
          <tr><td style="color:var(--text-muted);width:120px">水电站</td>
            <td><strong>${esc(d.canonical_name || 'unknown')}</strong></td></tr>
          <tr><td style="color:var(--text-muted)">年份</td>
            <td><strong>${esc(d.period_label)}</strong></td></tr>
          <tr><td style="color:var(--text-muted)">发电量</td>
            <td><strong style="color:var(--primary);font-size:18px">${fmt(d.generation_gwh)} GWh</strong></td></tr>
          <tr><td style="color:var(--text-muted)">原始值</td>
            <td>${esc(d.value_raw)} ${esc(d.unit_raw)}</td></tr>
          <tr><td style="color:var(--text-muted)">类型</td>
            <td>${esc(d.value_type === 'actual' ? '实际' : d.value_type)}</td></tr>
          <tr><td style="color:var(--text-muted)">置信度</td>
            <td><span class="badge-status ${d.confidence === 'high' ? 'st-published' : 'st-review'}">${d.confidence === 'high' ? '高置信度' : '低置信度'}</span></td></tr>
          <tr><td style="color:var(--text-muted)">状态</td>
            <td><span class="badge-status ${sc}">${sl}</span></td></tr>
        </table>
      </div>

      <div class="card">
        <div class="card-title">来源信息</div>
        <table>
          <tr><td style="color:var(--text-muted);width:120px">来源</td>
            <td>${esc(d.source_title || '—')}</td></tr>
          <tr><td style="color:var(--text-muted)">发布者</td>
            <td>${esc(d.publisher || '—')}</td></tr>
          <tr><td style="color:var(--text-muted)">发布日期</td>
            <td>${esc(d.publish_date || '—')}</td></tr>
          ${d.source_url ? `<tr><td style="color:var(--text-muted)">URL</td>
            <td><a href="${esc(d.source_url)}" target="_blank" style="color:var(--primary)">查看原文 →</a></td></tr>` : ''}
          <tr><td style="color:var(--text-muted)">页码</td>
            <td>${esc(d.page_number || '—')}</td></tr>
          <tr><td style="color:var(--text-muted)">表格</td>
            <td>${esc(d.table_reference || '—')}</td></tr>
          <tr><td style="color:var(--text-muted)">定位</td>
            <td><code style="font-size:12px">${esc(d.locator || '—')}</code></td></tr>
        </table>
      </div>
    </div>

    ${Array.isArray(d.candidate_flags) && d.candidate_flags.includes('OCR_DERIVED') ? `
    <div class="card" style="margin-top:16px;border-left:3px solid var(--warning)">
      <div class="card-title">OCR 识别提示</div>
      <div style="font-size:13px;line-height:1.6;color:var(--text-muted)">
        本候选来自扫描 PDF 的 OCR（${esc(d.locator || '页码未记录')}），必须人工核对原始页面后才能通过复核。
      </div>
      <table style="margin-top:8px">
        <tr><td style="color:var(--text-muted);width:120px">引擎</td><td>${esc(ocrMeta?.engine || '—')} ${esc(ocrMeta?.engine_version || '')}</td></tr>
        <tr><td style="color:var(--text-muted)">语言</td><td>${esc(ocrMeta?.language || '—')}</td></tr>
        <tr><td style="color:var(--text-muted)">识别区域</td><td><code style="font-size:12px">${esc(ocrRegion)}</code></td></tr>
        <tr><td style="color:var(--text-muted)">原图 SHA256</td><td><code style="font-size:11px;word-break:break-all">${esc(ocrMeta?.source_image_sha256 || '—')}</code></td></tr>
      </table>
      <div id="review-ocr-preview" style="margin-top:12px">
        <button class="btn btn-outline btn-sm" onclick='loadReviewOcrPreview(${reviewIdLiteral})'>查看原始页</button>
      </div>
    </div>` : ''}

    ${d.validation_issues && d.validation_issues.length > 0 ? `
    <div class="card" style="margin-top:16px">
      <div class="card-title">验证问题 (${d.validation_issues.length})</div>
      <div style="display:flex;flex-direction:column;gap:8px">
        ${d.validation_issues.map(issue => {
          const severityMap = {
            'HIGH': { label: '严重', class: 'st-conflict', icon: '⛔' },
            'MEDIUM': { label: '警告', class: 'st-review', icon: '⚠️' },
            'LOW': { label: '提示', class: 'st-neutral', icon: 'ℹ️' }
          };
          const sev = severityMap[issue.severity] || severityMap['MEDIUM'];
          return `
            <div style="padding:12px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);display:flex;gap:12px;align-items:start">
              <span style="font-size:18px">${sev.icon}</span>
              <div style="flex:1">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
                  <span class="badge-status ${sev.class}">${sev.label}</span>
                  <code style="font-size:12px;color:var(--text-muted)">${esc(issue.code)}</code>
                </div>
                <div style="font-size:13px;line-height:1.6">${esc(issue.message)}</div>
              </div>
            </div>
          `;
        }).join('')}
      </div>
    </div>` : ''}

    <div class="card" style="margin-top:16px">
      <div class="card-title">证据摘录</div>
      <div style="padding:16px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);font-family:monospace;font-size:13px;line-height:1.8;white-space:pre-wrap;max-height:200px;overflow-y:auto">${esc(d.snippet || '（无）')}</div>
    </div>

    <div class="card" style="margin-top:16px" id="review-notes-section">
      <div class="card-title">复核备注</div>
      <div id="review-notes-content" style="color:var(--text-muted);font-size:13px">暂无备注</div>
    </div>`;

  const footer = `
    <button class="btn btn-outline" onclick='addReviewNote(${reviewIdLiteral})'>添加备注</button>
    <button class="btn btn-outline" onclick='rejectRecordFromModal(${reviewIdLiteral})'>拒绝</button>
    <button class="btn btn-primary" onclick='approveRecordFromModal(${reviewIdLiteral})'>通过复核</button>
  `;

  showModal(`复核详情 #${d.id}`, content, { width: '900px', footer });
  loadReviewNotes(recordId);
}

async function loadReviewOcrPreview(reviewId) {
  const box = document.getElementById('review-ocr-preview');
  if (!box) return;
  box.innerHTML = '<div class="spinner">正在渲染原始页…</div>';
  try {
    const result = await api().get_review_ocr_preview(reviewId, null, 150);
    if (!result || result.status !== 'success') {
      box.innerHTML = `<div class="empty">${esc(result?.message || '原始页暂不可预览')}</div>`;
      return;
    }
    box.innerHTML = `
      <div style="font-size:12px;color:var(--text-muted);margin-bottom:8px">第 ${esc(result.page_number)} 页 · ${esc(result.width)}×${esc(result.height)} · ${esc(result.dpi)} DPI${result.region_highlighted ? ' · 红框为 OCR 区域' : ''}</div>
      <img src="${esc(result.image_data)}" alt="OCR 原始页预览" style="max-width:100%;max-height:560px;border:1px solid var(--border);border-radius:var(--radius-sm);display:block" />`;
  } catch (e) {
    box.innerHTML = `<div class="empty">原始页预览失败：${esc(e)}</div>`;
  }
}

function addReviewNote(recordId) {
  const note = prompt('添加复核备注：');
  if (!note) return;

  // 简单存储到 localStorage（生产环境应存数据库）
  const key = `review_note_${recordId}`;
  const notes = JSON.parse(localStorage.getItem(key) || '[]');
  notes.push({
    time: new Date().toISOString(),
    text: note
  });
  localStorage.setItem(key, JSON.stringify(notes));

  loadReviewNotes(recordId);
}

function loadReviewNotes(recordId) {
  const key = `review_note_${recordId}`;
  const notes = JSON.parse(localStorage.getItem(key) || '[]');
  const content = el('review-notes-content');
  if (!content) return;

  if (notes.length === 0) {
    content.innerHTML = '<span style="color:var(--text-muted);font-size:13px">暂无备注</span>';
  } else {
    content.innerHTML = notes.map(n => `
      <div style="padding:8px 0;border-bottom:1px solid var(--border)">
        <div style="font-size:12px;color:var(--text-muted)">${new Date(n.time).toLocaleString('zh-CN')}</div>
        <div style="margin-top:4px">${esc(n.text)}</div>
      </div>
    `).join('');
  }
}

async function approveRecordFromModal(recordId) {
  if (!confirm('确认通过复核？该记录将可用于 Top 100 等榜单。')) return;
  try {
    const result = await api().approve_record(recordId);
    ensureReviewActionSuccess(result);
    closeModal();
    renderReview();
    alert('已通过复核');
  } catch (e) {
    alert('操作失败：' + e);
  }
}

async function rejectRecordFromModal(recordId) {
  const reason = prompt('拒绝原因（可选）：');
  if (reason === null) return;
  try {
    const result = await api().reject_record(recordId, reason || '无效数据');
    ensureReviewActionSuccess(result);
    closeModal();
    renderReview();
    alert('已拒绝');
  } catch (e) {
    alert('操作失败：' + e);
  }
}

async function approveRecord(recordId) {
  if (!confirm('确认通过复核？该记录将可用于 Top 100 等榜单。')) return;
  try {
    const result = await api().approve_record(recordId);
    ensureReviewActionSuccess(result);
    alert('已通过复核');
    navigate('review');
  } catch (e) {
    alert('操作失败：' + e);
  }
}

async function rejectRecord(recordId) {
  const reason = prompt('拒绝原因（可选）：');
  if (reason === null) return;
  try {
    const result = await api().reject_record(recordId, reason || '无效数据');
    ensureReviewActionSuccess(result);
    alert('已拒绝');
    navigate('review');
  } catch (e) {
    alert('操作失败：' + e);
  }
}

function ensureReviewActionSuccess(result) {
  if (!result || result.status !== 'success') {
    throw new Error(result?.message || '复核操作失败');
  }
  return result;
}

// ---------- 全局搜索 ----------
function wireGlobalSearch() {
  const inp = el('global-search');
  if (!inp) return;
  inp.addEventListener('keydown', e => {
    if (e.key === 'Enter' && inp.value.trim()) {
      navigate('stations', { search: inp.value.trim() });
    }
  });
}

// ---------- 启动 ----------
function wireNav() {
  document.querySelectorAll('.nav-item').forEach(n =>
    n.addEventListener('click', () => navigate(n.dataset.route)));
  wireGlobalSearch();
  window.addEventListener('resize', () => {
    if (appState.route === 'dashboard') renderDashboard();
  });
}

function boot() {
  console.log('[boot] Starting boot sequence, _booted:', appState._booted);
  if (appState._booted) return;
  appState._booted = true;
  wireNav();
  console.log('[boot] Calling navigate(dashboard)...');
  navigate('dashboard').then(() => setTimeout(() => showFirstUseGuide(), 0));
}

// 轮询等待 pywebview api 的方法真正注入（避免 ready 事件与方法桩注入的竞态）
function waitForApi(attempt = 0) {
  const a = api();
  console.log(`[waitForApi] Attempt ${attempt}, api exists:`, !!a, 'get_dashboard exists:', !!(a && a.get_dashboard));
  if (a && typeof a.get_dashboard === 'function') {
    console.log('[waitForApi] API ready, calling boot()');
    boot();
    return;
  }
  if (attempt > 300) {  // ~30s 仍不可用
    console.error('[waitForApi] Timeout after 300 attempts');
    document.getElementById('main-content').innerHTML =
      '<div class="empty">应用启动超时，请关闭窗口重新打开。<br><span style="font-size:12px;color:var(--text-muted);margin-top:8px;display:block">如果问题持续，可能是后端服务异常。</span></div>';
    return;
  }
  // 前 5 秒每 100ms 检查一次，之后每 500ms 检查一次（避免过度轮询）
  const interval = attempt < 50 ? 100 : 500;
  setTimeout(() => waitForApi(attempt + 1), interval);
}

// ========== 来源管理 ==========
async function renderSources() {
  const main = el('main-content');
  main.innerHTML = '<div class="spinner">加载来源数据…</div>';

  try {
    const data = await pywebview.api.list_sources(100, 0);
    const items = data.items || [];

    main.innerHTML = `
      <div class="page-header">
        <h1>来源管理</h1>
        <p class="subtitle">管理所有数据来源，追踪每个来源的文档和记录数量</p>
      </div>
      <div class="card">
        <div class="card-header">
          <span>共 ${data.total || 0} 个来源</span>
        </div>
        ${items.length === 0 ? `
          <div class="empty">
            暂无来源数据。<br>
            <span style="font-size:13px;color:var(--text-muted);margin-top:8px;display:block">
              当您通过「新增数据」处理文档时，系统会自动创建来源记录。
            </span>
          </div>
        ` : `
          <table class="data-table">
            <thead>
              <tr>
                <th>来源 ID</th>
                <th>标题</th>
                <th>发布者</th>
                <th>文档数</th>
                <th>记录数</th>
                <th>发布时间</th>
              </tr>
            </thead>
            <tbody>
              ${items.map(s => `
                <tr>
                  <td><code>${s.source_id}</code></td>
                  <td>${s.title || '-'}</td>
                  <td>${s.publisher || '-'}</td>
                  <td>${s.document_count || 0}</td>
                  <td>${s.record_count || 0}</td>
                  <td>${s.publish_date || s.retrieved_at ? new Date(s.publish_date || s.retrieved_at).toLocaleString('zh-CN') : '-'}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        `}
      </div>
    `;
  } catch (e) {
    console.error('[renderSources] Error:', e);
    main.innerHTML = `<div class="empty">加载来源数据失败：${e.message}</div>`;
  }
}

// ========== 文档资料 ==========
async function renderDocuments() {
  const main = el('main-content');
  main.innerHTML = '<div class="spinner">加载文档数据…</div>';

  try {
    const data = await pywebview.api.list_documents(null, null, 50, 0);
    const items = data.items || [];

    main.innerHTML = `
      <div class="page-header">
        <h1>文档资料</h1>
        <p class="subtitle">查看所有已归档的文档及其处理状态</p>
      </div>
      <div class="card">
        <div class="card-header">
          <span>共 ${data.total || 0} 个文档</span>
        </div>
        ${items.length === 0 ? `
          <div class="empty">
            暂无文档数据。<br>
            <span style="font-size:13px;color:var(--text-muted);margin-top:8px;display:block">
              文档会在您完成「新增数据」中的下载或上传操作后自动归档。
            </span>
          </div>
        ` : `
          <table class="data-table">
            <thead>
              <tr>
                <th>文档 ID</th>
                <th>来源</th>
                <th>类型</th>
                <th>文件大小</th>
                <th>记录数</th>
                <th>获取时间</th>
              </tr>
            </thead>
            <tbody>
              ${items.map(d => `
                <tr>
                  <td><code>${d.document_id.substring(0, 12)}...</code></td>
                  <td>${d.source_title || d.source_id || '-'}</td>
                  <td><span class="badge">${d.content_kind || d.content_type || 'unknown'}</span></td>
                  <td>${formatBytes(d.file_size || 0)}</td>
                  <td>${d.record_count || 0}</td>
                  <td>${d.fetched_at ? new Date(d.fetched_at).toLocaleString('zh-CN') : '-'}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        `}
      </div>
    `;
  } catch (e) {
    console.error('[renderDocuments] Error:', e);
    main.innerHTML = `<div class="empty">加载文档数据失败：${e.message}</div>`;
  }
}

// ========== 证据中心 ==========
async function renderEvidence() {
  const main = el('main-content');
  main.innerHTML = '<div class="spinner">加载证据数据…</div>';

  try {
    const data = await pywebview.api.list_evidence(null, 50, 0);
    const items = data.items || [];

    main.innerHTML = `
      <div class="page-header">
        <h1>证据中心</h1>
        <p class="subtitle">浏览所有从文档中抽取的证据片段</p>
      </div>
      <div class="card">
        <div class="card-header">
          <span>共 ${data.total || 0} 条证据</span>
        </div>
        ${items.length === 0 ? `
          <div class="empty">
            暂无证据数据。<br>
            <span style="font-size:13px;color:var(--text-muted);margin-top:8px;display:block">
              证据片段会在文档解析和抽取完成后自动生成。
            </span>
          </div>
        ` : `
          <table class="data-table">
            <thead>
              <tr>
                <th>证据 ID</th>
                <th>来源</th>
                <th>内容类型</th>
                <th>片段预览</th>
                <th>页码</th>
                <th>记录数</th>
                <th>置信度</th>
              </tr>
            </thead>
            <tbody>
              ${items.map(e => `
                <tr>
                  <td><code>${e.evidence_id.substring(0, 12)}...</code></td>
                  <td>${e.source_title || '-'}</td>
                  <td><span class="badge">${e.content_kind || 'unknown'}</span></td>
                  <td style="max-width:300px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                    ${e.snippet ? e.snippet.substring(0, 80) : '-'}
                  </td>
                  <td>${e.page_number || '-'}</td>
                  <td>${e.record_count || 0}</td>
                  <td>${e.confidence || '-'}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        `}
      </div>
    `;
  } catch (e) {
    console.error('[renderEvidence] Error:', e);
    main.innerHTML = `<div class="empty">加载证据数据失败：${e.message}</div>`;
  }
}

// ========== 设置 ==========
async function renderSettings() {
  const main = el('main-content');
  main.innerHTML = '<div class="spinner">加载系统信息…</div>';

  try {
    const info = await pywebview.api.get_system_info();
    const llmConfig = await pywebview.api.get_llm_config();
    let ocrInfo = { available: false, dependencies: {}, tesseract: {}, errors: ['能力探测不可用'], recommendation: '请检查程序版本' };
    try { ocrInfo = await pywebview.api.get_ocr_capabilities(); } catch (e) { console.warn('[Settings] OCR capability probe failed:', e); }
    const db = info.database || {};
    const storage = info.storage || {};
    const ocrDeps = ocrInfo.dependencies || {};
    const ocrStatus = ocrInfo.available ? '可用' : '不可用（扫描 PDF 将转人工复核）';

    main.innerHTML = `
      <div class="page-header">
        <h1>设置</h1>
        <p class="subtitle">系统配置与数据管理</p>
      </div>

      <div class="card">
        <div class="card-header">LLM 配置</div>
        <div style="padding:16px;">
          ${llmConfig.configured ? `
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
              <div style="display:flex;align-items:center;gap:12px;">
                <div style="width:8px;height:8px;border-radius:50%;background:#10b981;"></div>
                <div>
                  <div style="font-weight:500;">${llmConfig.provider} - ${llmConfig.model}</div>
                  <div style="font-size:13px;color:var(--text-muted);margin-top:2px;">当前配置：${llmConfig.name}</div>
                </div>
              </div>
              <div style="display:flex;gap:8px;">
                <button class="btn btn-outline btn-sm" onclick="testLLMConnection()" style="min-width:90px;">测试连接</button>
                <button class="btn btn-outline btn-sm" onclick="showLLMConfigForm()">新增配置</button>
              </div>
            </div>

            ${llmConfig.configs && llmConfig.configs.length > 0 ? `
              <div style="margin-top:16px;border-top:1px solid var(--border);padding-top:16px;">
                <div style="font-weight:500;margin-bottom:12px;font-size:14px;">已配置的 API Key</div>
                <table style="width:100%;border-collapse:collapse;">
                  <thead>
                    <tr style="border-bottom:1px solid var(--border);">
                      <th style="text-align:left;padding:8px 0;font-size:13px;color:var(--text-muted);">配置名称</th>
                      <th style="text-align:left;padding:8px 0;font-size:13px;color:var(--text-muted);">API Key</th>
                      <th style="text-align:left;padding:8px 0;font-size:13px;color:var(--text-muted);">模型</th>
                      <th style="text-align:left;padding:8px 0;font-size:13px;color:var(--text-muted);">状态</th>
                      <th style="text-align:right;padding:8px 0;font-size:13px;color:var(--text-muted);">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${llmConfig.configs.map(cfg => `
                      <tr style="border-bottom:1px solid var(--border);">
                        <td style="padding:10px 0;font-weight:${cfg.is_active ? '500' : '400'};">${cfg.name}</td>
                        <td style="padding:10px 0;"><code style="font-size:11px;background:var(--page-bg);padding:2px 6px;border-radius:3px;">${cfg.api_key_masked}</code></td>
                        <td style="padding:10px 0;font-size:13px;">${cfg.model}</td>
                        <td style="padding:10px 0;">
                          ${cfg.is_active ? '<span style="color:#10b981;font-size:13px;font-weight:500;">● 使用中</span>' : '<span style="color:var(--text-muted);font-size:13px;">未激活</span>'}
                        </td>
                        <td style="padding:10px 0;text-align:right;">
                          ${!cfg.is_active ? `<button class="btn btn-outline btn-sm" onclick="switchLLMConfig('${cfg.name}')" style="margin-right:8px;padding:4px 12px;">切换</button>` : ''}
                          <button class="btn btn-outline btn-sm" onclick="deleteLLMConfig('${cfg.name}')" style="padding:4px 12px;color:#dc2626;border-color:#dc2626;">删除</button>
                        </td>
                      </tr>
                    `).join('')}
                  </tbody>
                </table>
              </div>
            ` : ''}
          ` : `
            <div style="margin-bottom:16px;padding:12px;background:var(--bg);border-radius:6px;border-left:3px solid #f59e0b;">
              <div style="font-weight:500;margin-bottom:4px;">⚠️ 未配置 LLM API Key</div>
              <div style="font-size:13px;color:var(--text-muted);">
                配置后可使用 AI 辅助功能（如智能数据提取、报告生成等）
              </div>
            </div>
            <button class="btn btn-primary" onclick="showLLMConfigForm()">
              <svg viewBox="0 0 24 24" width="16" height="16" style="stroke:currentColor;fill:none;stroke-width:2;vertical-align:middle;margin-right:6px;"><path d="M12 5v14M5 12h14"/></svg>
              配置 API Key
            </button>
          `}
          <p style="margin-top:12px;font-size:12px;color:var(--text-muted);">
            配置文件保存在：<code style="font-size:11px;">${llmConfig.config_path}</code>
          </p>
        </div>
      </div>

      <div class="card">
        <div class="card-header">数据管理</div>
        <div style="padding:16px;">
          <div style="display:flex;gap:12px;flex-wrap:wrap;">
            <button class="btn btn-outline" onclick="clearTestData()">
              <svg viewBox="0 0 24 24" width="16" height="16" style="stroke:currentColor;fill:none;stroke-width:2;vertical-align:middle;margin-right:6px;"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
              清空测试数据
            </button>
            <button class="btn btn-outline" onclick="exportDatabase()">
              <svg viewBox="0 0 24 24" width="16" height="16" style="stroke:currentColor;fill:none;stroke-width:2;vertical-align:middle;margin-right:6px;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>
              导出数据库
            </button>
            <button class="btn btn-outline" onclick="rebuildIndex()">
              <svg viewBox="0 0 24 24" width="16" height="16" style="stroke:currentColor;fill:none;stroke-width:2;vertical-align:middle;margin-right:6px;"><path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/></svg>
              重建索引
            </button>
          </div>
          <p style="margin-top:12px;font-size:13px;color:var(--text-muted);">
            注意：清空测试数据只会删除测试环境数据，不会影响正式数据库。
          </p>
        </div>
      </div>

      <div class="card">
        <div class="card-header">PDF / OCR 能力</div>
        <div style="padding:16px;">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;">
            <span style="width:9px;height:9px;border-radius:50%;background:${ocrInfo.available ? '#10b981' : '#f59e0b'};"></span>
            <strong>${esc(ocrStatus)}</strong>
          </div>
          <table class="data-table">
            <tbody>
              <tr><td>PyMuPDF</td><td>${ocrDeps.pymupdf ? '已安装' : '未安装'}</td></tr>
              <tr><td>Pillow</td><td>${ocrDeps.pillow ? '已安装' : '未安装'}</td></tr>
              <tr><td>pytesseract</td><td>${ocrDeps.pytesseract ? '已安装' : '未安装'}</td></tr>
              <tr><td>Tesseract</td><td>${esc(ocrInfo.tesseract?.version || '未检测到')}</td></tr>
              <tr><td>语言包</td><td>${esc((ocrInfo.tesseract?.languages || []).join(', ') || '未检测到')}</td></tr>
            </tbody>
          </table>
          <div style="margin-top:10px;font-size:12px;color:var(--text-muted)">${esc(ocrInfo.recommendation || '')}</div>
          ${ocrInfo.errors && ocrInfo.errors.length ? `<div style="margin-top:8px;font-size:12px;color:var(--danger)">${ocrInfo.errors.map(esc).join('<br>')}</div>` : ''}
        </div>
      </div>

      <div class="card">
        <div class="card-header">数据库统计</div>
        <table class="data-table">
          <tbody>
            <tr><td>水电站</td><td><strong>${db.stations || 0}</strong> 个</td></tr>
            <tr><td>项目</td><td><strong>${db.projects || 0}</strong> 个</td></tr>
            <tr><td>来源</td><td><strong>${db.sources || 0}</strong> 个</td></tr>
            <tr><td>文档</td><td><strong>${db.documents || 0}</strong> 个</td></tr>
            <tr><td>证据</td><td><strong>${db.evidence || 0}</strong> 条</td></tr>
            <tr><td>发电量记录</td><td><strong>${db.records || 0}</strong> 条</td></tr>
          </tbody>
        </table>
      </div>
      <div class="card">
        <div class="card-header">存储空间</div>
        <table class="data-table">
          <tbody>
            <tr><td>归档文档数</td><td><strong>${storage.total_documents || 0}</strong> 个</td></tr>
            <tr><td>总占用空间</td><td><strong>${formatBytes(storage.total_size_bytes || 0)}</strong></td></tr>
          </tbody>
        </table>
      </div>
      <div class="card">
        <div class="card-header">关于</div>
        <p style="padding:16px;line-height:1.6;color:var(--text-muted);">
          <strong>全球水电数据平台 V1</strong><br>
          采集 → 归档 → 解析 → 抽取 → 复核 → 发布<br>
          <span style="font-size:12px;margin-top:8px;display:block;">
            数据库：hydropower.sqlite
          </span>
        </p>
      </div>
    `;
  } catch (e) {
    console.error('[renderSettings] Error:', e);
    main.innerHTML = `<div class="empty">加载系统信息失败：${e.message}</div>`;
  }
}

// 工具函数：格式化字节数
function formatBytes(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
}

// ========== 设置页面操作函数 ==========
async function clearTestData() {
  if (!confirm('确定清空测试数据库吗？\n\n此操作将删除测试环境的所有数据，正式数据不受影响。')) return;
  try {
    await pywebview.api.reset_test_data();
    alert('✓ 测试数据已清空');
    renderSettings();
  } catch (e) {
    alert('清空失败：' + e.message);
  }
}

// ========== LLM 配置操作函数 ==========
function showLLMConfigForm() {
  const modal = document.createElement('div');
  modal.id = 'llm-config-modal';
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(26,39,68,0.6);display:flex;align-items:center;justify-content:center;z-index:9999;';

  modal.innerHTML = `
    <div style="background:#ffffff;border-radius:12px;width:500px;max-width:90%;box-shadow:0 20px 60px rgba(26,39,68,0.3);">
      <div style="padding:20px 24px;border-bottom:1px solid var(--border);">
        <h3 style="margin:0;font-size:18px;">配置 LLM API Key</h3>
      </div>
      <div style="padding:24px;">
        <div style="margin-bottom:20px;">
          <label style="display:block;margin-bottom:8px;font-weight:500;font-size:14px;">提供商</label>
          <select id="llm-provider" style="width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:6px;background:var(--page-bg);color:var(--text);font-size:14px;">
            <option value="deepseek">DeepSeek</option>
          </select>
          <p style="margin:6px 0 0;font-size:12px;color:var(--text-muted);">
            当前仅支持 DeepSeek，更多提供商即将支持
          </p>
        </div>

        <div style="margin-bottom:20px;">
          <label style="display:block;margin-bottom:8px;font-weight:500;font-size:14px;">配置名称</label>
          <input type="text" id="llm-config-name" placeholder="例如：default, work, personal" style="width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:6px;background:var(--page-bg);color:var(--text);font-size:14px;">
          <p style="margin:6px 0 0;font-size:12px;color:var(--text-muted);">
            为此配置指定一个名称，便于管理多个 API Key
          </p>
        </div>

        <div style="margin-bottom:20px;">
          <label style="display:block;margin-bottom:8px;font-weight:500;font-size:14px;">API Key</label>
          <input type="password" id="llm-api-key" placeholder="sk-..." style="width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:6px;background:var(--page-bg);color:var(--text);font-size:14px;font-family:monospace;">
          <p style="margin:6px 0 0;font-size:12px;color:var(--text-muted);">
            从 <a href="https://platform.deepseek.com/api_keys" target="_blank" style="color:var(--primary);">DeepSeek 控制台</a> 获取 API Key
          </p>
        </div>

        <div style="margin-bottom:20px;">
          <label style="display:block;margin-bottom:8px;font-weight:500;font-size:14px;">模型</label>
          <select id="llm-model" style="width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:6px;background:var(--page-bg);color:var(--text);font-size:14px;">
            <option value="deepseek-chat">deepseek-chat（通用对话）</option>
            <option value="deepseek-coder">deepseek-coder（代码生成）</option>
          </select>
        </div>

        <div style="padding:12px;background:var(--page-bg);border-radius:6px;border-left:3px solid #3b82f6;margin-bottom:20px;">
          <div style="font-size:13px;color:var(--text-muted);line-height:1.5;">
            <strong style="color:var(--text);">安全说明：</strong><br>
            API Key 将保存在您的用户目录（~/.hydro_platform/llm_config.json），不会随程序移动。每台电脑、每个用户需要独立配置。
          </div>
        </div>

        <div style="display:flex;gap:12px;justify-content:flex-end;">
          <button class="btn btn-outline" onclick="closeLLMConfigModal()">取消</button>
          <button class="btn btn-primary" onclick="saveLLMConfigFromForm()">保存</button>
        </div>
      </div>
    </div>
  `;

  document.body.appendChild(modal);
  document.getElementById('llm-api-key').focus();
}

function closeLLMConfigModal() {
  const modal = document.getElementById('llm-config-modal');
  if (modal) modal.remove();
}

async function saveLLMConfigFromForm() {
  const provider = document.getElementById('llm-provider').value;
  const configName = document.getElementById('llm-config-name').value.trim();
  const apiKey = document.getElementById('llm-api-key').value.trim();
  const model = document.getElementById('llm-model').value;

  if (!configName) {
    alert('请输入配置名称');
    return;
  }

  if (!apiKey) {
    alert('请输入 API Key');
    return;
  }

  if (!apiKey.startsWith('sk-')) {
    if (!confirm('API Key 格式可能不正确（通常以 sk- 开头），确定继续？')) return;
  }

  // 检查配置名称是否已存在
  try {
    const currentConfig = await pywebview.api.get_llm_config();
    const existingConfig = currentConfig.configs?.find(c => c.name === configName);

    if (existingConfig) {
      if (!confirm(`配置"${configName}"已存在，是否覆盖？\n\n当前：${existingConfig.api_key_masked}\n新的：${apiKey.substring(0, 3)}***${apiKey.substring(apiKey.length - 6)}`)) {
        return;
      }
    }
  } catch (e) {
    console.error('检查配置失败:', e);
  }

  try {
    const result = await pywebview.api.save_llm_config(provider, apiKey, model, configName);

    if (result.success) {
      closeLLMConfigModal();
      alert('✓ API Key 保存成功');
      renderSettings();
    } else {
      alert('保存失败：' + (result.error || '未知错误'));
    }
  } catch (e) {
    alert('保存失败：' + e.message);
  }
}

async function testLLMConnection() {
  const btn = event.target;
  const originalText = btn.innerHTML;
  const originalWidth = btn.offsetWidth + 'px';
  btn.disabled = true;
  btn.style.width = originalWidth;
  btn.innerHTML = '测试中...';

  try {
    const result = await pywebview.api.test_llm_connection();

    if (result.success) {
      alert(`✓ 连接成功\n\n模型：${result.model}\n${result.message}`);
    } else {
      alert(`✗ 连接失败\n\n${result.error || result.message}`);
    }
  } catch (e) {
    alert('测试失败：' + e.message);
  } finally {
    btn.disabled = false;
    btn.style.width = '';
    btn.innerHTML = originalText;
  }
}

async function switchLLMConfig(configName) {
  if (!confirm(`确定切换到配置"${configName}"吗？`)) return;

  try {
    const result = await pywebview.api.switch_llm_config('deepseek', configName);

    if (result.success) {
      alert(`✓ 已切换到配置：${configName}`);
      renderSettings();
    } else {
      alert('切换失败：' + (result.error || '未知错误'));
    }
  } catch (e) {
    alert('切换失败：' + e.message);
  }
}

async function deleteLLMConfig(configName) {
  if (!confirm(`确定删除配置"${configName}"吗？\n\n此操作不可恢复。`)) return;

  try {
    const result = await pywebview.api.delete_llm_config('deepseek', configName);

    if (result.success) {
      alert(`✓ 已删除配置：${configName}`);
      renderSettings();
    } else {
      alert('删除失败：' + (result.error || '未知错误'));
    }
  } catch (e) {
    alert('删除失败：' + e.message);
  }
}

async function exportDatabase() {
  try {
    const result = await pywebview.api.export_database();
    if (result.success) {
      alert(`✓ 数据库已导出\n\n保存位置：${result.file_path}`);
    } else {
      alert('导出失败：' + result.error);
    }
  } catch (e) {
    alert('导出失败：' + e.message);
  }
}

async function rebuildIndex() {
  if (!confirm('重建索引可能需要几分钟，确定继续吗？')) return;
  try {
    const result = await pywebview.api.rebuild_index();
    if (result.success) {
      alert('✓ 索引重建完成');
    } else {
      alert('重建失败：' + result.error);
    }
  } catch (e) {
    alert('重建失败：' + e.message);
  }
}

// ========== 项目管理 ==========
async function renderProjects() {
  const main = el('main-content');
  main.innerHTML = '<div class="spinner">加载项目数据…</div>';

  try {
    const data = await pywebview.api.list_projects(null, null, null, 50, 0);
    const items = data.items || [];

    main.innerHTML = `
      <div class="page-header">
        <div>
          <div class="page-title">项目</div>
          <div class="page-subtitle">水电项目库（包含规划中、在建、已建项目）</div>
        </div>
      </div>
      <div class="card">
        <div class="card-title">共 ${data.total || 0} 个项目</div>
        ${items.length === 0 ? `
          <div class="empty">
            暂无项目数据。<br>
            <span style="font-size:13px;color:var(--text-muted);margin-top:8px;display:block;">
              项目库将在第二阶段接入。当前专注于已运行水电站的发电量数据。
            </span>
          </div>
        ` : `
          <table>
            <thead>
              <tr>
                <th>项目名称</th>
                <th>国家</th>
                <th>省份/州</th>
                <th>河流</th>
                <th>装机容量</th>
                <th>状态</th>
                <th>运营商</th>
              </tr>
            </thead>
            <tbody>
              ${items.map(p => `
                <tr>
                  <td><strong>${esc(p.canonical_name)}</strong></td>
                  <td>${esc(p.country || '—')}</td>
                  <td>${esc(p.state_province || '—')}</td>
                  <td>${esc(p.river || '—')}</td>
                  <td>${p.capacity_mw ? fmt(p.capacity_mw) + ' MW' : '—'}</td>
                  <td><span class="badge-status st-neutral">${esc(p.status || 'unknown')}</span></td>
                  <td>${esc(p.operator || '—')}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        `}
      </div>
    `;
  } catch (e) {
    console.error('[renderProjects] Error:', e);
    main.innerHTML = `<div class="empty">加载项目数据失败：${esc(e.message || e)}</div>`;
  }
}

// ========== 任务管理 ==========
async function renderTasks() {
  const main = el('main-content');
  main.innerHTML = '<div class="spinner">加载任务数据…</div>';

  try {
    const data = await api().list_tasks(null, 200, 0);
    const items = data.items || [];
    window.__taskListItems = Object.fromEntries(items.map(t => [t.task_id, t]));
    const testTaskCount = items.filter(t => String(t.task_id || '').startsWith('test_') || String(t.entity_id || '').startsWith('test_')).length;

    main.innerHTML = `
      <div class="page-header">
        <div>
          <div class="page-title">采集任务</div>
          <div class="page-subtitle">数据采集任务的执行状态、重试与取消操作</div>
        </div>
        ${testTaskCount ? `<button class="btn btn-outline" onclick="cancelAllTestTasks()">取消 ${testTaskCount} 个测试任务</button>` : ''}
      </div>
      <div class="card">
        <div class="card-title">共 ${data.total || 0} 个任务${(data.total || 0) > items.length ? `（当前显示前 ${items.length} 个）` : ''}</div>
        ${items.length === 0 ? `
          <div class="empty">
            暂无采集任务。<br>
            <span style="font-size:13px;color:var(--text-muted);margin-top:8px;display:block;">
              任务会在系统自动发现数据缺口后创建，或通过「新增数据」手动触发。
            </span>
          </div>
        ` : `
          <table>
            <thead>
              <tr>
                <th>任务 ID</th>
                <th>实体</th>
                <th>目标期间</th>
                <th>任务类型</th>
                <th>状态</th>
                <th>失败阶段</th>
                <th>创建时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              ${items.map(t => {
                const statusClass = t.status === 'success' ? 'st-published' : t.status === 'failed' ? 'st-missing' : t.status === 'cancelled' ? 'st-neutral' : 'st-neutral';
                const taskId = encodeURIComponent(t.task_id);
                let actions = `<button class="btn btn-outline btn-sm" onclick="showTaskDetail('${taskId}')">详情</button>`;
                if (t.status === 'pending' || t.status === 'running') {
                  actions += ` <button class="btn btn-outline btn-sm" onclick="showTaskProcessingGuide('${taskId}')">来源 / 状态</button> <button class="btn btn-outline btn-sm" onclick="cancelQueuedTask('${taskId}')">取消</button>`;
                } else if (t.status === 'failed') {
                  const retry = t.source_type === 'intelligent' && t.user_specified_source
                    ? `<button class="btn btn-primary btn-sm" onclick="restartIntelligentTask('${taskId}')">使用已选来源重试</button>`
                    : `<button class="btn btn-primary btn-sm" onclick="retryFailedTask('${taskId}')">重试</button>`;
                  actions += ` ${retry} <button class="btn btn-outline btn-sm" onclick="showTaskProcessingGuide('${taskId}')">来源 / 状态</button> <button class="btn btn-outline btn-sm" onclick="cancelQueuedTask('${taskId}')">取消</button>`;
                } else if (t.status === 'needs_review') {
                  actions += ` <button class="btn btn-primary btn-sm" onclick="navigate('review')">去复核</button> <button class="btn btn-outline btn-sm" onclick="cancelQueuedTask('${taskId}')">取消</button>`;
                }
                return `
                  <tr>
                    <td><code style="font-size:11px">${esc(t.task_id.substring(0, 12))}...</code></td>
                    <td>${esc(t.entity_name || t.entity_id)}</td>
                    <td>${esc(t.target_period || '—')}<br><span style="font-size:11px;color:var(--text-muted)">${t.period_type === 'fiscal_year' ? '财政年度' : '自然年'}</span></td>
                    <td><span class="badge-status st-neutral">${esc(t.task_type || 'auto')}</span></td>
                    <td><span class="badge-status ${statusClass}">${esc(t.status)}</span></td>
                    <td>${esc(t.failure_stage || '—')}</td>
                    <td>${t.created_at ? new Date(t.created_at).toLocaleString('zh-CN') : '—'}</td>
                    <td style="white-space:nowrap">${actions}</td>
                  </tr>
                `;
              }).join('')}
            </tbody>
          </table>
        `}
      </div>
    `;
  } catch (e) {
    console.error('[renderTasks] Error:', e);
    main.innerHTML = `<div class="empty">加载任务数据失败：${esc(e.message || e)}</div>`;
  }
}

function decodeTaskId(encoded) {
  return decodeURIComponent(encoded);
}

function showTaskDetail(encodedTaskId) {
  const taskId = decodeTaskId(encodedTaskId);
  const task = window.__taskListItems?.[taskId];
  if (!task) {
    alert('任务详情已过期，请刷新列表后重试。');
    return;
  }
  const content = `
    <div class="form-group"><label>任务 ID</label><code>${esc(task.task_id)}</code></div>
    <div class="form-group"><label>实体</label><div>${esc(task.entity_name || task.entity_id)} <span style="color:var(--text-muted)">(${esc(task.entity_id)})</span></div></div>
    <div class="form-group"><label>类型 / 期间</label><div>${esc(task.task_type)} / ${esc(task.target_period || '—')}（${task.period_type === 'fiscal_year' ? '财政年度' : '自然年'}）</div></div>
    <div class="form-group"><label>状态</label><div>${esc(task.status)}</div></div>
    <div class="form-group"><label>失败信息</label><div>${esc(task.failure_stage || '—')}${task.last_error ? `<br><span style="color:var(--text-muted)">${esc(task.last_error)}</span>` : ''}</div></div>
  `;
  showModal('任务详情', content, {
    width: '620px',
    footer: '<button class="btn btn-primary" onclick="closeModal()">关闭</button>'
  });
}

async function cancelQueuedTask(encodedTaskId) {
  const taskId = decodeTaskId(encodedTaskId);
  if (!confirm(`确认取消任务？\n\n${taskId}\n\n任务记录会保留，后续不再执行。`)) return;
  try {
    const result = await api().cancel_queued_task(taskId);
    if (!result.success) throw new Error(result.error || '取消失败');
    alert('任务已取消。');
    renderTasks();
  } catch (e) {
    alert(`取消任务失败：${e.message || e}`);
  }
}

async function retryFailedTask(encodedTaskId) {
  const taskId = decodeTaskId(encodedTaskId);
  if (!confirm(`确认将失败任务重新排队？\n\n${taskId}`)) return;
  try {
    const result = await api().retry_failed_task(taskId);
    if (!result.success) throw new Error(result.error || '重试失败');
    alert('任务已重新排入待处理队列。');
    renderTasks();
  } catch (e) {
    alert(`重试任务失败：${e.message || e}`);
  }
}

async function restartIntelligentTask(encodedTaskId) {
  const taskId = decodeTaskId(encodedTaskId);
  if (!confirm(`确认使用此前已选择的智能来源重新采集？\n\n${taskId}\n\n不会要求重新填写 URL；历史运行记录会保留。`)) return;
  try {
    const result = await api().restart_intelligent_task(taskId);
    if (!result.success) throw new Error(result.error || '重新开始失败');
    alert('任务已使用已选来源重新进入队列，系统将自动执行。');
    renderTasks();
  } catch (e) {
    alert(`重新开始失败：${e.message || e}`);
  }
}

async function cancelAllTestTasks() {
  if (!confirm('确认取消全部 test_ 前缀的未完成测试任务？\n\n不会删除任务或审计记录。')) return;
  try {
    const result = await api().cancel_test_tasks();
    if (!result.success) throw new Error(result.error || '批量取消失败');
    alert(`已取消 ${result.cancelled_count} 个测试任务；跳过 ${result.skipped_count} 个终态任务。`);
    renderTasks();
  } catch (e) {
    alert(`批量取消失败：${e.message || e}`);
  }
}

function showTaskProcessingGuide(encodedTaskId) {
  const taskId = decodeTaskId(encodedTaskId);
  const task = window.__taskListItems?.[taskId];
  const source = task?.user_specified_source;
  const isIntelligent = task?.source_type === 'intelligent';
  if (source) {
    const sourceLabel = isIntelligent ? '智能规划已确认来源' : '已指定来源';
    const statusText = task?.status === 'running'
      ? '系统正在使用该来源采集，无需再填写 URL。'
      : task?.status === 'failed'
        ? `本次采集失败：${esc(task?.failure_stage || '未知阶段')}。来源仍已保存；可点击“使用已选来源重试”，无需重新填写 URL。`
        : '该任务已进入自动执行队列，通常会在下一次调度扫描时启动，无需再填写 URL。';
    const content = `
      <p><strong>${sourceLabel}</strong></p>
      <p style="word-break:break-all"><a href="${esc(source)}" target="_blank">${esc(source)}</a></p>
      <p style="font-size:13px;color:var(--text-muted)">${statusText}</p>
    `;
    const footer = task?.status === 'failed' && isIntelligent
      ? `<button class="btn btn-outline" onclick="closeModal()">关闭</button><button class="btn btn-primary" onclick="closeModal(); restartIntelligentTask('${encodedTaskId}')">使用已选来源重试</button>`
      : '<button class="btn btn-primary" onclick="closeModal(); renderTasks()">刷新状态</button>';
    showModal('智能采集任务', content, { width: '620px', footer });
    return;
  }
  const content = `
    <p>任务 <code>${esc(taskId)}</code> 需要先提供可追溯的数据来源，才能执行采集。</p>
    <p style="font-size:13px;color:var(--text-muted)">请在“新增数据”中提交来源网址或本地文件。成功采集后，任务会自动更新为复核或完成状态。</p>
  `;
  const footer = `
    <button class="btn btn-outline" onclick="closeModal()">稍后处理</button>
    <button class="btn btn-primary" onclick="closeModal(); navigate('add-data')">前往新增数据</button>
  `;
  showModal('处理采集任务', content, { width: '560px', footer });
}

// ========== 通知下拉 ==========
async function toggleNotifications(event) {
  event.stopPropagation();

  let panel = document.getElementById('notifications-panel');
  if (panel) {
    panel.remove();
    return;
  }

  const data = await pywebview.api.get_dashboard();
  const gaps = data.asset_cards.data_gaps || 0;
  const reviews = data.asset_cards.pending_reviews || 0;
  const records = data.asset_cards.accepted_records || 0;

  panel = document.createElement('div');
  panel.id = 'notifications-panel';
  panel.className = 'dropdown-panel';
  panel.style.cssText = 'position:absolute;top:60px;right:80px;width:320px;background:#ffffff;border:1px solid var(--border);border-radius:8px;box-shadow:0 4px 12px rgba(26,39,68,0.15);z-index:9999;';

  panel.innerHTML = `
    <div style="padding:12px 16px;border-bottom:1px solid var(--border);font-weight:500;">通知</div>
    <div style="max-height:400px;overflow-y:auto;">
      ${gaps > 0 ? `
        <div class="notification-item" onclick="navigate('data-gaps');document.getElementById('notifications-panel').remove();" style="padding:12px 16px;border-bottom:1px solid var(--border);cursor:pointer;">
          <div style="display:flex;align-items:start;gap:12px;">
            <svg viewBox="0 0 24 24" width="20" height="20" style="stroke:#f59e0b;fill:none;stroke-width:2;flex-shrink:0;margin-top:2px;"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/></svg>
            <div style="flex:1;">
              <div style="font-weight:500;margin-bottom:4px;">数据缺口待处理</div>
              <div style="font-size:13px;color:var(--text-muted);">发现 ${gaps} 个高优先级数据缺口</div>
              <div style="font-size:12px;color:var(--text-muted);margin-top:4px;">刚刚</div>
            </div>
          </div>
        </div>
      ` : ''}
      ${reviews > 0 ? `
        <div class="notification-item" onclick="navigate('review');document.getElementById('notifications-panel').remove();" style="padding:12px 16px;border-bottom:1px solid var(--border);cursor:pointer;">
          <div style="display:flex;align-items:start;gap:12px;">
            <svg viewBox="0 0 24 24" width="20" height="20" style="stroke:#3b82f6;fill:none;stroke-width:2;flex-shrink:0;margin-top:2px;"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
            <div style="flex:1;">
              <div style="font-weight:500;margin-bottom:4px;">待复核记录</div>
              <div style="font-size:13px;color:var(--text-muted);">有 ${reviews} 条记录需要人工复核</div>
              <div style="font-size:12px;color:var(--text-muted);margin-top:4px;">1 小时前</div>
            </div>
          </div>
        </div>
      ` : ''}
      ${records > 0 ? `
        <div class="notification-item" style="padding:12px 16px;cursor:default;">
          <div style="display:flex;align-items:start;gap:12px;">
            <svg viewBox="0 0 24 24" width="20" height="20" style="stroke:#10b981;fill:none;stroke-width:2;flex-shrink:0;margin-top:2px;"><path d="M9 11l3 3L22 4"/></svg>
            <div style="flex:1;">
              <div style="font-weight:500;margin-bottom:4px;">数据更新</div>
              <div style="font-size:13px;color:var(--text-muted);">已确认 ${records} 条发电量记录</div>
              <div style="font-size:12px;color:var(--text-muted);margin-top:4px;">今天</div>
            </div>
          </div>
        </div>
      ` : ''}
      ${gaps === 0 && reviews === 0 && records === 0 ? `
        <div style="padding:40px 16px;text-align:center;color:var(--text-muted);">
          暂无通知
        </div>
      ` : ''}
    </div>
  `;

  document.body.appendChild(panel);

  setTimeout(() => {
    document.addEventListener('click', function closePanel() {
      panel?.remove();
      document.removeEventListener('click', closePanel);
    });
  }, 0);
}

// ========== 用户菜单 ==========
function toggleUserMenu(event) {
  event.stopPropagation();

  let panel = document.getElementById('user-menu-panel');
  if (panel) {
    panel.remove();
    return;
  }

  panel = document.createElement('div');
  panel.id = 'user-menu-panel';
  panel.className = 'dropdown-panel';
  panel.style.cssText = 'position:absolute;top:60px;right:20px;width:200px;background:#ffffff;border:1px solid var(--border);border-radius:8px;box-shadow:0 4px 12px rgba(26,39,68,0.15);z-index:9999;';

  panel.innerHTML = `
    <div style="padding:12px 16px;border-bottom:1px solid var(--border);">
      <div style="font-weight:500;">研究员</div>
      <div style="font-size:13px;color:var(--text-muted);margin-top:2px;">hydropower@research.org</div>
    </div>
    <div style="padding:4px 0;">
      <div class="menu-item" onclick="navigate('settings');document.getElementById('user-menu-panel').remove();" style="padding:10px 16px;cursor:pointer;">
        <svg viewBox="0 0 24 24" width="16" height="16" style="stroke:currentColor;fill:none;stroke-width:2;vertical-align:middle;margin-right:8px;"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        设置
      </div>
      <div class="menu-item" onclick="alert('全球水电数据平台 V1\\n\\n采集 → 归档 → 解析 → 抽取 → 复核 → 发布')" style="padding:10px 16px;cursor:pointer;">
        <svg viewBox="0 0 24 24" width="16" height="16" style="stroke:currentColor;fill:none;stroke-width:2;vertical-align:middle;margin-right:8px;"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
        关于
      </div>
    </div>
    <div style="border-top:1px solid var(--border);padding:4px 0;">
      <div class="menu-item" onclick="if(confirm('确定要退出应用吗？')) pywebview.api.quit_app()" style="padding:10px 16px;cursor:pointer;color:#dc2626;">
        <svg viewBox="0 0 24 24" width="16" height="16" style="stroke:currentColor;fill:none;stroke-width:2;vertical-align:middle;margin-right:8px;"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/></svg>
        退出
      </div>
    </div>
  `;

  document.body.appendChild(panel);

  setTimeout(() => {
    document.addEventListener('click', function closePanel() {
      panel?.remove();
      document.removeEventListener('click', closePanel);
    });
  }, 0);
}

// ============ 全局搜索 ============
let searchTimeout;

function clearSearch() {
  const input = el('global-search');
  const clearBtn = el('search-clear');
  input.value = '';
  clearBtn.style.display = 'none';
  document.getElementById('search-results')?.remove();
  input.focus();
}

async function handleGlobalSearch(event) {
  const query = event.target.value.trim();
  const clearBtn = el('search-clear');

  // 显示/隐藏清空按钮
  clearBtn.style.display = event.target.value ? '' : 'none';

  clearTimeout(searchTimeout);

  document.getElementById('search-results')?.remove();

  if (query.length < 2) return;

  searchTimeout = setTimeout(async () => {
    try {
      const results = await pywebview.api.global_search(query);
      showSearchResults(results);
    } catch (e) {
      console.error('[handleGlobalSearch] Error:', e);
    }
  }, 500);
}

function showSearchResults(results) {
  const { stations, projects, sources } = results;
  const total = (stations?.length || 0) + (projects?.length || 0) + (sources?.length || 0);

  if (total === 0) return;

  const panel = document.createElement('div');
  panel.id = 'search-results';
  panel.style.cssText = 'position:absolute;top:55px;left:20px;right:20px;max-width:600px;background:var(--surface);border:1px solid var(--border);border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,0.15);z-index:9999;max-height:400px;overflow-y:auto;';

  let html = '';

  if (stations && stations.length > 0) {
    html += '<div style="padding:8px 12px;font-size:12px;color:var(--text-muted);font-weight:500;">水电站</div>';
    stations.forEach(s => {
      html += `
        <div onclick="navigate('station-detail', {id: '${esc(s.entity_id)}'});document.getElementById('search-results').remove();" style="padding:10px 16px;cursor:pointer;border-top:1px solid var(--border);">
          <div style="font-weight:500;">${esc(s.name)}</div>
          <div style="font-size:13px;color:var(--text-muted);margin-top:2px;">${esc(s.country || '—')}</div>
        </div>
      `;
    });
  }

  if (projects && projects.length > 0) {
    html += '<div style="padding:8px 12px;font-size:12px;color:var(--text-muted);font-weight:500;border-top:1px solid var(--border);">项目</div>';
    projects.forEach(p => {
      html += `
        <div onclick="navigate('projects');document.getElementById('search-results').remove();" style="padding:10px 16px;cursor:pointer;border-top:1px solid var(--border);">
          <div style="font-weight:500;">${esc(p.name)}</div>
          <div style="font-size:13px;color:var(--text-muted);margin-top:2px;">${esc(p.country || '—')}</div>
        </div>
      `;
    });
  }

  if (sources && sources.length > 0) {
    html += '<div style="padding:8px 12px;font-size:12px;color:var(--text-muted);font-weight:500;border-top:1px solid var(--border);">来源</div>';
    sources.forEach(s => {
      html += `
        <div onclick="navigate('sources');document.getElementById('search-results').remove();" style="padding:10px 16px;cursor:pointer;border-top:1px solid var(--border);">
          <div style="font-weight:500;">${esc(s.title)}</div>
          <div style="font-size:13px;color:var(--text-muted);margin-top:2px;">${esc(s.publisher || '—')}</div>
        </div>
      `;
    });
  }

  panel.innerHTML = html;

  const searchBox = document.querySelector('.search-box');
  searchBox.style.position = 'relative';
  searchBox.appendChild(panel);

  setTimeout(() => {
    document.addEventListener('click', function closePanel() {
      panel?.remove();
      document.removeEventListener('click', closePanel);
    });
  }, 0);
}

window.addEventListener('pywebviewready', () => waitForApi());
waitForApi();  // 兜底：立即也开始轮询
