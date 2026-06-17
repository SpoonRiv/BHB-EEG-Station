/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 阻抗页面逻辑（WebSocket 接收阻抗向量、地形图着色、列表刷新、调试面板与模式启停）。

修改日志:
- 2026-05-04: 1.0.0 创建文件
- 2026-05-04: 1.0.1 阻抗 UI 改为低频刷新：WS 仅缓存最新值，定时器节流渲染；副标题按“是否收到数据”动态显示
- 2026-05-04: 1.0.2 阻抗按钮与连接/运行态联动；移除“最新数据(…前)”提示条
- 2026-05-04: 1.0.3 阈值改为双滑块区间，可交互调整绿/黄/红分段
- 2026-05-04: 1.0.4 阈值滑条步进与上限由后端配置下发
- 2026-05-04: 1.0.5 阈值支持数值输入；去掉未知/未接触；阈值区间三按钮铺满并增加分段标线
- 2026-05-04: 1.0.6 移除阈值数值输入，仅保留双滑块
- 2026-05-04: 1.0.7 列表卡片去掉位置标签与“预留”文案，降低单元高度以避免滚动
- 2026-05-04: 1.0.8 8通道列表改为4行2列，16通道改为4行4列（与设备页通道选择一致）
- 2026-05-04: 1.0.9 将通道状态（如偏高）移动到通道名右侧展示
- 2026-05-04: 1.0.10 阈值三档标识右侧增加“默认”按钮，一键恢复默认阈值
- 2026-05-04: 1.0.11 阻抗列表分组：电极阻抗与参考电极阻抗
- 2026-05-04: 1.0.12 配置字段更名：impedance.mode_channels -> impedance.n_channels（与三模式命名一致）
- 2026-05-17: 1.0.13 阻抗地形图电极位置由后端配置下发，前端仅做渲染与回退
- 2026-05-17: 1.0.14 阻抗可视化自检：补充 LSL 解析状态提示，便于定位“无阻抗值”
- 2026-05-19: 1.0.15 移除页面副标题动态状态文案，仅保留固定说明文本
- 2026-06-11: 1.0.16 阻抗列表标题改为 x10Ω，并移除单元格内单位显示
- 2026-06-17: 1.0.17 BIAS 参考电极按当前参考通道名显示（如 Pz），并用于地形图定位
- 2026-06-17: 1.0.18 阻抗单位标识调整为 ✖10Ω，并优化分组标题样式（去掉括号）
- 2026-06-17: 1.0.19 阻抗列表文案调整：*10 Ω 与工作电极阻抗
- 2026-06-17: 1.0.20 去掉工作电极阻抗标题中的通道数字样

作者: Spoon
版本: 1.0.20
*/

import { getConfig, getStatus, modeStart, modeStop } from './api.js';
import { createImpedanceTopomap } from './impedance_topomap.js';

let wsImp = null;
let wsDebug = null;

let impPageActive = false;
let impStatusTimer = null;
let impRenderTimer = null;

let impNames = [];
let impModeChannels = 8;
let impUi = { refresh_hz: 1, good_max_ohm: 5000, warn_max_ohm: 20000, slider_max_ohm: 30000, slider_step_ohm: 100 };
let impValues = [];
let impLastTsSec = 0;
let impLastRecvAtMs = 0;
let impValuesByName = {};
let impValuesDirty = false;
let impTaskActive = false;
let impRefName = '';

let topo = null;
let listHost = null;
let gridMainEl = null;
let gridExtraEl = null;
let listItems = new Map();
let selectedName = '';
let listTitleMainEl = null;
let listTitleExtraEl = null;

let debugLines = [];
let debugFilterText = '';
let debugPaused = false;
let debugBufferedLines = [];

function formatLocalTsSeconds(tsSeconds) {
  const t = Number(tsSeconds);
  const dt = new Date((Number.isFinite(t) ? t : Date.now() / 1000) * 1000);
  const pad2 = (n) => String(n).padStart(2, '0');
  const pad3 = (n) => String(n).padStart(3, '0');
  return `${dt.getFullYear()}-${pad2(dt.getMonth() + 1)}-${pad2(dt.getDate())} ${pad2(dt.getHours())}:${pad2(dt.getMinutes())}:${pad2(dt.getSeconds())}.${pad3(dt.getMilliseconds())}`;
}

function formatDebugEvent(ev) {
  const ts = formatLocalTsSeconds(ev.ts);
  const tag = String(ev.tag || 'DEBUG');
  const msg = ev.message || '';
  let dataStr = '';
  if (ev.data && Object.keys(ev.data).length > 0) {
    dataStr = JSON.stringify(ev.data);
  }
  const tagWidth = 12;
  const tagPadded = tag.length >= tagWidth ? tag.slice(0, tagWidth) : tag.padEnd(tagWidth, ' ');
  return `${ts}\t[${tagPadded}]\t${msg}\t${dataStr}`;
}

function renderDebug() {
  const el = document.getElementById('imp-debug-log');
  if (!el) return;
  const shouldStickToBottom = (el.scrollTop + el.clientHeight) >= (el.scrollHeight - 6);
  const f = (debugFilterText || '').trim().toLowerCase();
  const out = f ? debugLines.filter(l => l.toLowerCase().includes(f)) : debugLines;
  el.textContent = out.join('\n');
  if (!debugPaused && shouldStickToBottom) el.scrollTop = el.scrollHeight;
}

function setBadge(kind, text) {
  const badge = document.getElementById('imp-badge');
  const textEl = document.getElementById('imp-badge-text');
  if (!badge || !textEl) return;
  badge.classList.remove('active', 'warn', 'error');
  if (kind === 'active') badge.classList.add('active');
  else if (kind === 'warn') badge.classList.add('warn');
  else if (kind === 'error') badge.classList.add('error');
  textEl.textContent = String(text || '');
}

function renderImpControlButtons(running, connected, taskActive) {
  const startBtn = document.getElementById('btn-imp-start');
  const stopBtn = document.getElementById('btn-imp-stop');
  if (startBtn) startBtn.disabled = (!running) || (!connected) || !!taskActive;
  if (stopBtn) stopBtn.disabled = (!running) || (!connected) || !taskActive;
}

function clampThresholds(goodMax, warnMax, sliderMax) {
  const max = Math.max(1, Number(sliderMax) || 50000);
  let g = Math.max(0, Math.min(max - 1, Math.round(Number(goodMax) || 0)));
  let w = Math.max(g + 1, Math.min(max, Math.round(Number(warnMax) || (g + 1))));
  if (w <= g) w = Math.min(max, g + 1);
  if (g >= max) g = max - 1;
  if (w > max) w = max;
  if (w <= g) w = Math.min(max, g + 1);
  return { g, w, max };
}

function applyThresholds(nextGoodMax, nextWarnMax) {
  const t = clampThresholds(nextGoodMax, nextWarnMax, impUi.slider_max_ohm);
  impUi.good_max_ohm = t.g;
  impUi.warn_max_ohm = t.w;
  if (topo) topo.setThresholds({ goodMaxOhm: t.g, warnMaxOhm: t.w });
  renderLegend();
  if (topo) topo.update(impValuesByName);
  updateList(impValuesByName);
}

function updateTrack(trackEl, goodMax, warnMax, sliderMax) {
  if (!trackEl) return;
  const max = Math.max(1, Number(sliderMax) || 50000);
  const p1 = Math.max(0, Math.min(100, (Number(goodMax) / max) * 100));
  const p2 = Math.max(0, Math.min(100, (Number(warnMax) / max) * 100));
  trackEl.style.background = `linear-gradient(90deg, var(--good) 0%, var(--good) ${p1}%, var(--warn) ${p1}%, var(--warn) ${p2}%, var(--bad) ${p2}%, var(--bad) 100%)`;
  const m1 = trackEl.querySelector('.imp-range-mark[data-kind="g"]');
  const m2 = trackEl.querySelector('.imp-range-mark[data-kind="w"]');
  if (m1) m1.style.left = `calc(${p1}% - 1px)`;
  if (m2) m2.style.left = `calc(${p2}% - 1px)`;
}

function renderLegend() {
  const host = document.getElementById('imp-legend');
  if (!host) return;
  host.innerHTML = '';

  const t = clampThresholds(impUi.good_max_ohm, impUi.warn_max_ohm, impUi.slider_max_ohm);
  impUi.good_max_ohm = t.g;
  impUi.warn_max_ohm = t.w;
  impUi.slider_max_ohm = t.max;

  const box = document.createElement('div');
  box.className = 'imp-th';

  const row = document.createElement('div');
  row.className = 'imp-th-row';
  const title = document.createElement('div');
  title.className = 'imp-th-title';
  title.textContent = '阈值：';
  row.appendChild(title);

  const pills = document.createElement('div');
  pills.className = 'imp-th-pills';
  const pillG = document.createElement('span');
  pillG.className = 'imp-pill good';
  pillG.textContent = `0~${t.g}*10 Ω`;
  const pillW = document.createElement('span');
  pillW.className = 'imp-pill warn';
  pillW.textContent = `${t.g}~${t.w}*10 Ω`;
  const pillB = document.createElement('span');
  pillB.className = 'imp-pill bad';
  pillB.textContent = `>${t.w}*10 Ω`;
  pills.appendChild(pillG);
  pills.appendChild(pillW);
  pills.appendChild(pillB);

  const btnDefault = document.createElement('button');
  btnDefault.className = 'btn imp-th-default';
  btnDefault.textContent = '默认';
  btnDefault.onclick = () => applyThresholds(5000, 20000);
  pills.appendChild(btnDefault);

  const range = document.createElement('div');
  range.className = 'imp-range';
  const track = document.createElement('div');
  track.className = 'imp-range-track';
  const markG = document.createElement('div');
  markG.className = 'imp-range-mark';
  markG.dataset.kind = 'g';
  const markW = document.createElement('div');
  markW.className = 'imp-range-mark';
  markW.dataset.kind = 'w';
  track.appendChild(markG);
  track.appendChild(markW);
  updateTrack(track, t.g, t.w, t.max);
  range.appendChild(track);

  const r1 = document.createElement('input');
  r1.type = 'range';
  r1.min = '0';
  r1.max = String(t.max);
  r1.value = String(t.g);
  r1.step = String(Math.max(1, Math.round(Number(impUi.slider_step_ohm) || 100)));

  const r2 = document.createElement('input');
  r2.type = 'range';
  r2.min = '0';
  r2.max = String(t.max);
  r2.value = String(t.w);
  r2.step = String(Math.max(1, Math.round(Number(impUi.slider_step_ohm) || 100)));

  r1.oninput = () => {
    const next = clampThresholds(r1.value, r2.value, t.max);
    r1.value = String(next.g);
    r2.value = String(next.w);
    updateTrack(track, next.g, next.w, next.max);
    impUi.good_max_ohm = next.g;
    impUi.warn_max_ohm = next.w;
    if (topo) topo.setThresholds({ goodMaxOhm: next.g, warnMaxOhm: next.w });
    pillG.textContent = `0~${next.g}*10 Ω`;
    pillW.textContent = `${next.g}~${next.w}*10 Ω`;
    pillB.textContent = `>${next.w}*10 Ω`;
    if (topo) topo.update(impValuesByName);
    updateList(impValuesByName);
  };

  r2.oninput = () => {
    const next = clampThresholds(r1.value, r2.value, t.max);
    r1.value = String(next.g);
    r2.value = String(next.w);
    updateTrack(track, next.g, next.w, next.max);
    impUi.good_max_ohm = next.g;
    impUi.warn_max_ohm = next.w;
    if (topo) topo.setThresholds({ goodMaxOhm: next.g, warnMaxOhm: next.w });
    pillG.textContent = `0~${next.g}*10 Ω`;
    pillW.textContent = `${next.g}~${next.w}*10 Ω`;
    pillB.textContent = `>${next.w}*10 Ω`;
    if (topo) topo.update(impValuesByName);
    updateList(impValuesByName);
  };

  range.appendChild(r1);
  range.appendChild(r2);

  box.appendChild(row);
  box.appendChild(pills);
  box.appendChild(range);
  host.appendChild(box);
}

function classifyOhm(v) {
  const x = Number(v);
  if (!Number.isFinite(x) || x <= 0) return 'unknown';
  if (x <= impUi.good_max_ohm) return 'good';
  if (x <= impUi.warn_max_ohm) return 'warn';
  return 'bad';
}

function ensureGridHosts() {
  if (!listHost) listHost = document.getElementById('imp-list');
  if (!gridMainEl) gridMainEl = document.getElementById('imp-grid-main');
  if (!gridExtraEl) gridExtraEl = document.getElementById('imp-grid-extra');
  if (listHost && gridMainEl && !listTitleMainEl) {
    const existing = listHost.querySelector('.imp-list-group-title-main');
    if (existing) listTitleMainEl = existing;
    else {
      const el = document.createElement('div');
      el.className = 'imp-list-group-title imp-list-group-title-main';
      listHost.insertBefore(el, gridMainEl);
      listTitleMainEl = el;
    }
  }
  if (listHost && gridExtraEl && !listTitleExtraEl) {
    const existing = listHost.querySelector('.imp-list-group-title-extra');
    if (existing) listTitleExtraEl = existing;
    else {
      const el = document.createElement('div');
      el.className = 'imp-list-group-title imp-list-group-title-extra';
      listHost.insertBefore(el, gridExtraEl);
      listTitleExtraEl = el;
    }
  }
}

function setSelectedCell(name) {
  selectedName = String(name || '');
  if (topo) topo.setSelected(selectedName);
  for (const [k, el] of listItems.entries()) {
    if (k === selectedName) el.classList.add('imp-selected');
    else el.classList.remove('imp-selected');
  }
}

function createCell(name, disabled) {
  const cell = document.createElement('div');
  cell.className = `imp-cell imp-unknown${disabled ? ' disabled' : ''}`;
  cell.dataset.name = String(name || '');
  cell.dataset.disabled = disabled ? '1' : '0';

  const top = document.createElement('div');
  top.className = 'imp-cell-top';

  const n = document.createElement('div');
  n.className = 'imp-cell-name';
  n.textContent = name ? String(name) : '';

  const state = document.createElement('div');
  state.className = 'imp-cell-state';
  state.textContent = disabled ? '' : '未知';

  top.appendChild(n);
  top.appendChild(state);

  const value = document.createElement('div');
  value.className = 'imp-cell-value';
  value.textContent = disabled ? '' : '--';

  cell.appendChild(top);
  cell.appendChild(value);

  if (!disabled && name) {
    cell.onclick = () => setSelectedCell(name);
  }

  return cell;
}

function ensureList() {
  ensureGridHosts();
  if (!listHost || !gridMainEl || !gridExtraEl) return;
  gridMainEl.innerHTML = '';
  gridExtraEl.innerHTML = '';
  listItems.clear();

  const all = Array.isArray(impNames) ? impNames : [];
  const extras = [];
  const mains = [];
  for (const x of all) {
    const s = String(x || '').trim();
    if (!s) continue;
    if ((impRefName && s.toUpperCase() === impRefName.toUpperCase()) || s.toUpperCase() === 'BIAS' || s.toUpperCase() === 'TDCS') extras.push(s);
    else mains.push(s);
  }

  const slots = Math.max(1, Math.min(16, Math.round(Number(impModeChannels) || mains.length || 8)));
  if (listTitleMainEl) listTitleMainEl.textContent = '工作电极阻抗';
  if (listTitleExtraEl) listTitleExtraEl.textContent = '参考电极阻抗';
  const cols = slots <= 8 ? 2 : 4;
  gridMainEl.style.setProperty('--imp-grid-cols', String(cols));
  for (let i = 0; i < slots; i++) {
    const name = i < mains.length ? mains[i] : '';
    const cell = createCell(name, !name);
    gridMainEl.appendChild(cell);
    if (name) listItems.set(name, cell);
  }

  const extraNames = [];
  for (const x of extras) {
    const s = String(x || '').trim();
    if (!s) continue;
    if (!extraNames.includes(s)) extraNames.push(s);
  }
  for (const s of [(impRefName || 'BIAS'), 'tDCS']) {
    if (extraNames.includes(s) || extraNames.includes(s.toUpperCase())) {
      if (!extraNames.includes(s)) extraNames.push(s);
    }
  }
  const orderedExtras = [];
  for (const want of [(impRefName || 'BIAS'), 'tDCS']) {
    const hit = extraNames.find(x => String(x).toUpperCase() === want.toUpperCase());
    if (hit) orderedExtras.push(hit);
  }

  const extraFill = orderedExtras.length > 0 ? orderedExtras : extras;
  const extraSlots = 2;
  for (let i = 0; i < extraSlots; i++) {
    const name = i < extraFill.length ? extraFill[i] : '';
    const cell = createCell(name, !name);
    gridExtraEl.appendChild(cell);
    if (name) listItems.set(name, cell);
  }
}

function updateList(valuesByName) {
  ensureGridHosts();
  if (!listHost) return;
  const vm = valuesByName && typeof valuesByName === 'object' ? valuesByName : {};
  for (const [name, cell] of listItems.entries()) {
    if (!cell) continue;
    const disabled = String(cell.dataset.disabled || '') === '1';
    if (disabled) continue;
    const value = vm[name];
    const kind = classifyOhm(value);
    cell.classList.remove('imp-good', 'imp-warn', 'imp-bad', 'imp-unknown');
    cell.classList.add(`imp-${kind}`);
    const valueEl = cell.querySelector('.imp-cell-value');
    const stateEl = cell.querySelector('.imp-cell-state');
    if (valueEl) {
      const x = Number(value);
      valueEl.textContent = Number.isFinite(x) ? `${Math.round(x)}` : '--';
    }
    if (stateEl) {
      stateEl.textContent = kind === 'good' ? '良好' : (kind === 'warn' ? '可用' : (kind === 'bad' ? '偏高' : '未知'));
    }
  }
}

function renderBadgeByFreshness() {
  const now = Date.now();
  if (!impLastRecvAtMs) {
    setBadge('warn', '等待数据');
    return;
  }
  const ageMs = Math.max(0, now - impLastRecvAtMs);
  if (ageMs < 2000) setBadge('active', '数据更新中');
  else if (ageMs < 6000) setBadge('warn', '数据延迟');
  else setBadge('error', '数据超时');
}

function renderSubtitle(stateText) {
  return;
}

async function refreshImpStatusHint() {
  try {
    const st = await getStatus();
    const dev = st && st.device ? st.device : null;
    const running = !!(dev && dev.running);
    const last = dev && dev.last ? dev.last : null;
    const lastType = last && last.type ? String(last.type) : '';
    const connected = lastType === 'connected' || lastType === 'ready';
    const taskActive = !!(dev && dev.task_running) && String(dev.task_mode || '') === 'impedance';
    const lsl = !!(st && st.impedance_lsl_streaming);
    const lslDetail = st && st.impedance_lsl ? st.impedance_lsl : null;
    if (!running) {
      impTaskActive = false;
      renderImpControlButtons(false, false, false);
      renderSubtitle('设备未连接（请先在设备页连接）');
      return;
    }
    impTaskActive = taskActive;
    renderImpControlButtons(running, connected, taskActive);
    if (!lsl) {
      const extra = lslDetail && lslDetail.last_error ? `；LSL：${String(lslDetail.last_error)}` : '';
      if (taskActive) renderSubtitle(`数据连接：解析中（等待数据）${extra}`);
      else renderSubtitle(`数据连接：未启动（请点击“开启阻抗检测”）${extra}`);
      return;
    }
    const ageMs = impLastRecvAtMs ? Math.max(0, Date.now() - impLastRecvAtMs) : null;
    const hasRecent = ageMs !== null && ageMs < 3000;
    const hasAny = !!impLastRecvAtMs;
    if (hasRecent) renderSubtitle('数据连接：已连接（数据流）');
    else if (hasAny) renderSubtitle('数据连接：已连接（数据延迟）');
    else renderSubtitle('数据连接：已连接（等待数据）');
  } catch (_) {
    renderSubtitle('后端未响应');
  }
}

function closeWs(ws) {
  try { if (ws) ws.close(); } catch (_) {}
}

function connectImpWs() {
  closeWs(wsImp);
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  wsImp = new WebSocket(`${proto}://${location.host}/ws/impedance`);
  wsImp.onmessage = (evt) => {
    try {
      const msg = JSON.parse(evt.data);
      if (!msg || msg.type !== 'impedance_data') return;
      const d = msg.data || {};
      const values = Array.isArray(d.values) ? d.values : [];
      impValues = values;
      impLastTsSec = Number(d.ts) || (Date.now() / 1000);
      impLastRecvAtMs = Date.now();

      const map = {};
      for (let i = 0; i < Math.min(impNames.length, values.length); i++) {
        map[impNames[i]] = values[i];
      }
      impValuesByName = map;
      impValuesDirty = true;
    } catch (_) {}
  };
}

function connectDebugWs() {
  closeWs(wsDebug);
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  wsDebug = new WebSocket(`${proto}://${location.host}/ws/debug`);
  wsDebug.onmessage = (evt) => {
    try {
      const msg = JSON.parse(evt.data);
      if (!msg || typeof msg !== 'object') return;
      if (msg.type === 'debug_init') {
        const events = Array.isArray(msg.events) ? msg.events : [];
        debugLines = events.map(formatDebugEvent).slice(-500);
        renderDebug();
        return;
      }
      if (msg.type === 'debug_event' && msg.event) {
        const line = formatDebugEvent(msg.event);
        if (debugPaused) {
          debugBufferedLines.push(line);
          return;
        }
        debugLines.push(line);
        if (debugLines.length > 500) debugLines = debugLines.slice(-500);
        renderDebug();
      }
    } catch (_) {}
  };
}

function bindControls() {
  const btnStart = document.getElementById('btn-imp-start');
  const btnStop = document.getElementById('btn-imp-stop');
  const btnClear = document.getElementById('imp-debug-clear');
  const btnPause = document.getElementById('imp-debug-pause');
  const filter = document.getElementById('imp-debug-filter');

  if (btnStart) {
    btnStart.onclick = async () => {
      btnStart.disabled = true;
      try {
        await modeStart('impedance');
      } catch (_) {
      } finally {
        await refreshImpStatusHint();
      }
    };
  }
  if (btnStop) {
    btnStop.onclick = async () => {
      btnStop.disabled = true;
      try {
        await modeStop('impedance');
      } catch (_) {
      } finally {
        await refreshImpStatusHint();
      }
    };
  }
  if (btnClear) {
    btnClear.onclick = () => {
      debugLines = [];
      debugBufferedLines = [];
      renderDebug();
    };
  }
  if (btnPause) {
    btnPause.onclick = () => {
      debugPaused = !debugPaused;
      btnPause.textContent = debugPaused ? '继续滚动' : '暂停输出';
      if (!debugPaused && debugBufferedLines.length) {
        debugLines.push(...debugBufferedLines);
        debugBufferedLines = [];
        if (debugLines.length > 500) debugLines = debugLines.slice(-500);
        renderDebug();
      }
    };
    btnPause.textContent = '暂停输出';
  }
  if (filter) {
    filter.oninput = () => {
      debugFilterText = String(filter.value || '');
      renderDebug();
    };
  }
}

async function initImpedanceUiOnce() {
  let electrodePositions = null;
  let electrodeAliases = null;
  try {
    const cfg = await getConfig();
    impRefName = cfg && typeof cfg.ref_channel_name === 'string' ? String(cfg.ref_channel_name || '').trim() : '';
    const imp = cfg && cfg.impedance ? cfg.impedance : null;
    const names = imp && Array.isArray(imp.channel_names) ? imp.channel_names : [];
    impNames = names.map(x => String(x || '').trim()).filter(Boolean);
    if (impRefName) {
      const idx = impNames.findIndex(x => String(x).toUpperCase() === 'BIAS');
      if (idx >= 0) {
        const hasDup = impNames.some((x, i) => i !== idx && String(x).toUpperCase() === impRefName.toUpperCase());
        if (!hasDup) impNames[idx] = impRefName;
      }
    }
    impModeChannels = imp && Number.isFinite(Number(imp.n_channels)) ? Math.round(Number(imp.n_channels)) : impModeChannels;
    impUi = imp && imp.ui ? {
      refresh_hz: Number(imp.ui.refresh_hz) || 1,
      good_max_ohm: Number(imp.ui.good_max_ohm) || 5000,
      warn_max_ohm: Number(imp.ui.warn_max_ohm) || 20000,
      slider_max_ohm: Number(imp.ui.slider_max_ohm) || 30000,
      slider_step_ohm: Number(imp.ui.slider_step_ohm) || 100,
    } : impUi;
    const layout = cfg && cfg.electrode_layout_1020 ? cfg.electrode_layout_1020 : null;
    if (layout && layout.positions && typeof layout.positions === 'object') {
      electrodePositions = layout.positions;
      electrodeAliases = (layout.aliases && typeof layout.aliases === 'object') ? layout.aliases : null;
    }
  } catch (_) {}

  renderLegend();
  ensureList();

  const topoHost = document.getElementById('imp-topomap-svg');
  topo = createImpedanceTopomap(topoHost, impNames, { good_max_ohm: impUi.good_max_ohm, warn_max_ohm: impUi.warn_max_ohm }, electrodePositions, electrodeAliases);
  if (topo) {
    topo.setOnSelect((name) => {
      const cell = listItems.get(name);
      if (cell) {
        cell.scrollIntoView({ behavior: 'smooth', block: 'center' });
        setSelectedCell(name);
      }
    });
  }
}

function startTimers() {
  const hz = Math.max(1, Number(impUi.refresh_hz) || 1);
  if (impRenderTimer) clearInterval(impRenderTimer);
  if (impStatusTimer) clearInterval(impStatusTimer);
  impRenderTimer = setInterval(() => {
    if (impValuesDirty) {
      impValuesDirty = false;
      if (topo) topo.update(impValuesByName);
      updateList(impValuesByName);
    }
    renderBadgeByFreshness();
  }, Math.round(1000 / hz));
  refreshImpStatusHint();
  impStatusTimer = setInterval(refreshImpStatusHint, 1000);
}

function stopTimers() {
  if (impRenderTimer) clearInterval(impRenderTimer);
  if (impStatusTimer) clearInterval(impStatusTimer);
  impRenderTimer = null;
  impStatusTimer = null;
}

export async function enterImpedancePage() {
  impPageActive = true;
  debugLines = [];
  debugFilterText = '';
  debugPaused = false;
  debugBufferedLines = [];
  impLastRecvAtMs = 0;
  impLastTsSec = 0;
  impValues = [];
  impValuesByName = {};
  impValuesDirty = false;
  impTaskActive = false;
  selectedName = '';
  setBadge('warn', '等待数据');
  bindControls();
  await initImpedanceUiOnce();
  connectImpWs();
  connectDebugWs();
  startTimers();
}

export function leaveImpedancePage() {
  impPageActive = false;
  stopTimers();
  closeWs(wsImp);
  closeWs(wsDebug);
  wsImp = null;
  wsDebug = null;
}
