/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: EEG 页面逻辑（WebSocket 接收波形、ECharts 渲染、调试面板、模式启停）
作者: Spoon
*/

import { getConfig, getStatus, modeStart, modeStop } from './api.js';
import { navigate } from './router.js';
import { EegPsdView } from './eeg_psd.js';

const EEG_WAVE_FOCUS_STORAGE_KEY = 'bhb_eeg_wave_focus';

let wsEeg = null;
let wsDebug = null;
let psdView = null;

let charts = [];
let channels = 8;
let channelNames = [];
let maxPoints = 500;

let eegSamplingRateHz = 250;
let eegWindowSec = 2.0;
let eegRenderFps = 25;
let eegMaxRenderPointsPerChannel = 800;
let eegGlobalScale = true;
let psdFmaxHz = null;
let triggerEnabled = false;
let triggerActive = null;
let eegYAxisStep = 50;
let eegYAxisUpdateHz = 2;
let eegLastYAxisUpdateAtMs = 0;
let eegPendingMin = Infinity;
let eegPendingMax = -Infinity;
let eegLastAppliedYAxisMin = null;
let eegLastAppliedYAxisMax = null;
let eegYAxisDynamicEnabled = true;
let eegYAxisFixedMax = 500;
let eegYAxisFixedMaxMin = 50;
let eegYAxisFixedMaxMax = 1500;
let eegYAxisFixedMaxStep = 50;
let eegYAxisModeDirty = false;

let eegRings = [];
let eegDataDirty = false;
let eegRenderLoopActive = false;
let eegLastRenderAtMs = 0;
let globalYMin = Infinity;
let globalYMax = -Infinity;

let eegGridEl = null;
let eegChartContainers = [];
let eegVisibleMask = [];
let eegChartWidthCache = [];
let eegTargetPointsCache = [];
let eegScrollCheckRequested = false;
let eegGridScrollHandler = null;
let eegResizeHandler = null;
let eegResizeListenerAttached = false;
let eegWsMaxPendingChunks = 2;
let eegPendingEegChunks = [];

let debugLines = [];
let debugFilterText = '';
let debugPaused = false;
let debugBufferedLines = [];
let debugDirty = false;
let debugRenderLoopActive = false;
let debugLastRenderAtMs = 0;
let debugRenderFps = 8;
let themeListenerAttached = false;
let themeChangeHandler = null;
let eegPageActive = false;
let eegReconnectTimer = null;
let debugReconnectTimer = null;
let eegStatusTimer = null;
let eegDataWatchTimer = null;
let eegStatusEventBound = false;
let eegStatusEventHandler = null;
let lastEegDataAtMs = 0;
let eegWsState = 'disconnected';
let eegHasData = false;
let eegStatusHint = '';
let eegSessionLocked = false;
let eegStopping = false;
let eegViewMode = 'time';
let eegWaveFocusEnabled = false;

function renderBatteryBadge(battery, running, streaming) {
  const badge = document.getElementById('battery-badge');
  const textEl = document.getElementById('battery-text');
  if (!badge || !textEl) return;

  badge.classList.remove('active', 'warn', 'error');

  if (!running) {
    textEl.textContent = '--';
    badge.classList.add('error');
    return;
  }

  if (streaming && (!battery || typeof battery !== 'object')) {
    textEl.textContent = '获取中';
    badge.classList.add('warn');
    return;
  }

  const v = battery && typeof battery.value === 'number' ? battery.value : null;
  if (v === null || !Number.isFinite(v)) {
    textEl.textContent = streaming ? '获取中' : '--';
    if (streaming) badge.classList.add('warn');
    return;
  }

  const isPercent = Number.isInteger(v) && v >= 0 && v <= 100;
  if (isPercent) {
    textEl.textContent = `${v}%`;
    if (v >= 50) badge.classList.add('active');
    else if (v >= 20) badge.classList.add('warn');
    else badge.classList.add('error');
    return;
  }

  textEl.textContent = `${v}`;
}

function renderEegControlButtons(running, streaming) {
  const startBtn = document.getElementById('btn-eeg-start');
  const stopBtn = document.getElementById('btn-eeg-stop');
  if (startBtn) startBtn.disabled = (!running) || !!streaming || eegSessionLocked;
  if (stopBtn) stopBtn.disabled = (!running) || !eegSessionLocked;
}

function applyEegStatusSnapshot(st) {
  const dev = st && st.device ? st.device : null;
  const running = !!(dev && dev.running);
  const streaming = !!(st && st.lsl_streaming);
  const taskActive = !!(dev && dev.task_running) && String(dev.task_mode || '') === 'eeg';
  renderBatteryBadge(dev && dev.battery ? dev.battery : null, running, streaming);
  if (!running || (!taskActive && !streaming && !eegStopping)) {
    eegSessionLocked = false;
  }
  renderEegControlButtons(running, streaming);
}

function renderEegSubtitle() {
  return;
}

function resizeEegVisualsAfterLayout() {
  const resizeNow = () => {
    if (!eegPageActive) return;
    for (const chart of charts) {
      if (!chart) continue;
      try { chart.resize(); } catch (_) {}
    }
    if (psdView && typeof psdView.resize === 'function') psdView.resize();
    scheduleVisibleUpdate(true);
  };
  requestAnimationFrame(resizeNow);
  window.setTimeout(resizeNow, 160);
  window.setTimeout(resizeNow, 340);
}

function syncEegFocusLayoutMetrics(layout, debugBody) {
  if (!layout || !debugBody) return;
  const debugCard = debugBody.closest('.eeg-debug-card');
  const debugHeader = debugCard ? debugCard.querySelector('.card-header') : null;
  if (!debugCard || !debugHeader) return;

  const cardStyle = getComputedStyle(debugCard);
  const borderHeight = (parseFloat(cardStyle.borderTopWidth) || 0) + (parseFloat(cardStyle.borderBottomWidth) || 0);
  const headerHeight = Math.max(
    debugHeader.getBoundingClientRect().height,
    debugHeader.scrollHeight
  );
  const collapsedHeight = Math.max(1, Math.ceil(headerHeight + borderHeight));
  const compactLayout = window.matchMedia('(max-width: 980px)').matches;
  const expandedHeight = Math.max(
    compactLayout ? 240 : 260,
    collapsedHeight + 64
  );

  layout.style.setProperty('--focus-collapsed-row', `${collapsedHeight}px`);
  layout.style.setProperty('--focus-expanded-row', `${expandedHeight}px`);
}

function setEegWaveFocus(enabled, { persist = true, resize = true } = {}) {
  eegWaveFocusEnabled = !!enabled;
  const layout = document.querySelector('#page-eeg .eeg-layout');
  const debugBody = document.getElementById('eeg-debug-body');
  const toggle = document.getElementById('eeg-focus-toggle');
  const label = document.getElementById('eeg-focus-label');

  if (debugBody) debugBody.hidden = false;
  syncEegFocusLayoutMetrics(layout, debugBody);
  if (layout) layout.classList.toggle('eeg-layout--wave-focus', eegWaveFocusEnabled);
  if (debugBody) {
    debugBody.setAttribute('aria-hidden', eegWaveFocusEnabled ? 'true' : 'false');
    debugBody.inert = eegWaveFocusEnabled;
  }
  if (toggle) {
    const nextLabel = eegWaveFocusEnabled ? '恢复布局' : '全屏显示';
    toggle.classList.toggle('is-active', eegWaveFocusEnabled);
    toggle.setAttribute('aria-pressed', eegWaveFocusEnabled ? 'true' : 'false');
    toggle.setAttribute('aria-expanded', eegWaveFocusEnabled ? 'false' : 'true');
    toggle.setAttribute('aria-label', nextLabel);
    toggle.setAttribute('title', nextLabel);
  }
  if (label) label.textContent = eegWaveFocusEnabled ? '恢复布局' : '全屏显示';

  if (persist) {
    try { localStorage.setItem(EEG_WAVE_FOCUS_STORAGE_KEY, eegWaveFocusEnabled ? '1' : '0'); } catch (_) {}
  }
  if (resize) resizeEegVisualsAfterLayout();
}

function bindEegWaveFocusToggle() {
  const toggle = document.getElementById('eeg-focus-toggle');
  let stored = null;
  try { stored = localStorage.getItem(EEG_WAVE_FOCUS_STORAGE_KEY); } catch (_) {}
  setEegWaveFocus(stored === '1', { persist: false, resize: false });
  if (toggle) toggle.onclick = () => setEegWaveFocus(!eegWaveFocusEnabled);
}

async function refreshEegStatusHint() {
  try {
    const st = await getStatus();
    const dev = st && st.device ? st.device : null;
    const running = !!(dev && dev.running);
    const streaming = !!(st && st.lsl_streaming);
    const lsl = st && st.lsl ? st.lsl : null;
    applyEegStatusSnapshot(st);
    if (!running) {
      eegStatusHint = '设备未连接（请先在设备页连接）';
    } else if (!streaming) {
      const extra = lsl && lsl.last_error ? `；LSL：${String(lsl.last_error)}` : '';
      eegStatusHint = `采集未启动或数据总线未就绪（请点击“开始采集”）${extra}`;
    } else {
      eegStatusHint = '';
    }
  } catch (_) {
    eegStatusHint = '后端未响应';
  } finally {
    renderEegSubtitle();
  }
}

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
  const el = document.getElementById('debug-log');
  if (!el) return;
  const shouldStickToBottom = (el.scrollTop + el.clientHeight) >= (el.scrollHeight - 6);
  const f = (debugFilterText || '').trim().toLowerCase();
  const out = f ? debugLines.filter(l => l.toLowerCase().includes(f)) : debugLines;
  el.textContent = out.join('\n');
  if (!debugPaused && shouldStickToBottom) {
    el.scrollTop = el.scrollHeight;
  }
}

function debugRenderLoop() {
  if (!eegPageActive) {
    debugRenderLoopActive = false;
    return;
  }
  const now = performance.now();
  const intervalMs = 1000 / Math.max(1, Number(debugRenderFps) || 8);
  if (debugDirty && (now - debugLastRenderAtMs) >= intervalMs) {
    debugDirty = false;
    debugLastRenderAtMs = now;
    renderDebug();
  }
  requestAnimationFrame(debugRenderLoop);
}

function clampNumber(v, minV, maxV, fallback) {
  const x = Number(v);
  if (!Number.isFinite(x)) return Number(fallback);
  return Math.max(Number(minV), Math.min(Number(maxV), x));
}

function formatNumberPlain(value) {
  const v = Number(value);
  if (!Number.isFinite(v)) return '';
  const rounded = Math.round(v);
  const isIntLike = Math.abs(v - rounded) < 1e-9;
  const absV = Math.abs(v);
  const maxFracDigits = isIntLike ? 0 : (absV < 1 ? 3 : absV < 10 ? 2 : absV < 100 ? 1 : 0);
  return v.toLocaleString('en-US', { useGrouping: false, maximumFractionDigits: maxFracDigits });
}

function setYAxisMode(nextDynamicEnabled) {
  eegYAxisDynamicEnabled = !!nextDynamicEnabled;
  eegYAxisModeDirty = true;
  try { localStorage.setItem('bhb_eeg_yaxis_dynamic', eegYAxisDynamicEnabled ? '1' : '0'); } catch (_) {}
  eegLastAppliedYAxisMin = null;
  eegLastAppliedYAxisMax = null;
  eegDataDirty = true;
}

function setFixedYAxisMax(nextMax) {
  eegYAxisFixedMax = clampNumber(nextMax, eegYAxisFixedMaxMin, eegYAxisFixedMaxMax, eegYAxisFixedMax);
  try { localStorage.setItem('bhb_eeg_yaxis_fixed_max', String(eegYAxisFixedMax)); } catch (_) {}
  eegLastAppliedYAxisMin = null;
  eegLastAppliedYAxisMax = null;
  eegDataDirty = true;
}

function buildYAxisControls() {
  const host = document.getElementById('eeg-yaxis-controls');
  if (!host) return;
  host.innerHTML = '';

  const sw = document.createElement('div');
  sw.className = 'eeg-yaxis-switch';
  const swText = document.createElement('span');
  swText.className = 'eeg-yaxis-label';
  swText.textContent = '动态Y轴';
  const swLabel = document.createElement('label');
  swLabel.className = 'ios-switch';
  const dynamicInput = document.createElement('input');
  dynamicInput.type = 'checkbox';
  dynamicInput.checked = !!eegYAxisDynamicEnabled;
  const swSlider = document.createElement('span');
  swSlider.className = 'ios-slider';
  swLabel.appendChild(dynamicInput);
  swLabel.appendChild(swSlider);
  sw.appendChild(swText);
  sw.appendChild(swLabel);

  const range = document.createElement('div');
  range.className = 'imp-range';
  const track = document.createElement('div');
  track.className = 'imp-range-track';
  range.appendChild(track);

  const r = document.createElement('input');
  r.type = 'range';
  r.min = String(eegYAxisFixedMaxMin);
  r.max = String(eegYAxisFixedMaxMax);
  r.step = String(eegYAxisFixedMaxStep);
  r.value = String(eegYAxisFixedMax);
  r.disabled = !!eegYAxisDynamicEnabled;
  range.appendChild(r);

  const pill = document.createElement('div');
  pill.className = 'eeg-yaxis-pill';
  pill.textContent = `±${Math.round(Number(eegYAxisFixedMax) || 0)}`;
  if (eegYAxisDynamicEnabled) pill.classList.add('eeg-hidden');

  const applyUiState = () => {
    r.disabled = !!eegYAxisDynamicEnabled;
    pill.classList.toggle('eeg-hidden', !!eegYAxisDynamicEnabled);
    pill.textContent = `±${Math.round(Number(eegYAxisFixedMax) || 0)}`;
  };

  dynamicInput.onchange = () => {
    setYAxisMode(dynamicInput.checked);
    applyUiState();
  };

  r.oninput = () => {
    setFixedYAxisMax(r.value);
    r.value = String(eegYAxisFixedMax);
    applyUiState();
  };

  host.appendChild(sw);
  host.appendChild(range);
  host.appendChild(pill);
}

function scheduleDebugRender() {
  debugDirty = true;
  if (!debugRenderLoopActive) {
    debugRenderLoopActive = true;
    debugLastRenderAtMs = 0;
    requestAnimationFrame(debugRenderLoop);
  }
}

function initCharts() {
  const grid = document.getElementById('charts-grid');
  if (!grid) return;
  if (!window.echarts || typeof window.echarts.init !== 'function') {
    eegStatusHint = '波形可视化组件未加载（ECharts）。若处于离线环境，请避免使用外部 CDN 资源，改为本地引入。';
    renderEegSubtitle();
    return;
  }
  eegGridEl = grid;
  const isLight = (document.documentElement.getAttribute('data-theme') || 'light') === 'light';

  disposeCharts();
  grid.innerHTML = '';
  eegRings = Array.from({ length: channels }, () => new FloatRingBuffer(maxPoints));
  eegChartContainers = [];
  eegVisibleMask = Array.from({ length: channels }, () => true);
  eegChartWidthCache = Array.from({ length: channels }, () => 0);
  eegTargetPointsCache = Array.from({ length: channels }, () => 0);
  globalYMin = Infinity;
  globalYMax = -Infinity;

  for (let i = 0; i < channels; i++) {
    const container = document.createElement('div');
    container.className = 'chart-container';

    const title = document.createElement('div');
    title.className = 'chart-title';
    title.innerText = channelNames[i] ? `${channelNames[i]}` : `CH ${i + 1}`;
    container.appendChild(title);

    const chartDiv = document.createElement('div');
    chartDiv.className = 'echarts-instance';
    chartDiv.id = `chart-ch${i}`;
    container.appendChild(chartDiv);

    grid.appendChild(container);
    eegChartContainers.push(container);

    const chart = echarts.init(chartDiv, null, { renderer: 'canvas' });
    chart.setOption({
      backgroundColor: 'transparent',
      grid: { top: 12, bottom: 12, left: 120, right: 10 },
      xAxis: { type: 'value', show: false, boundaryGap: false, min: -eegWindowSec, max: 0 },
      yAxis: {
        type: 'value',
        scale: true,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          margin: 10,
          color: isLight ? '#111827' : 'rgba(255, 255, 255, 0.78)',
          formatter: function (value) {
            const v = Number(value);
            if (!Number.isFinite(v)) return '';
            if (!eegYAxisDynamicEnabled) return formatNumberPlain(v);
            if (Math.abs(v) > 1001) return v.toExponential(0);
            return formatNumberPlain(v);
          }
        },
        splitLine: {
          lineStyle: {
            color: isLight ? 'rgba(17, 24, 39, 0.10)' : 'rgba(0, 0, 0, 0.18)',
            type: 'dashed',
          }
        }
      },
      series: [{
        type: 'line',
        showSymbol: false,
        hoverAnimation: false,
        data: [],
        large: true,
        largeThreshold: 2000,
        lineStyle: { color: isLight ? '#000000' : '#ffffff', width: 1.6 }
      }],
      animation: false,
    });

    charts.push(chart);
  }

  scheduleVisibleUpdate(true);
}

function disposeCharts() {
  for (const ch of charts) {
    if (!ch) continue;
    try { ch.dispose(); } catch (_) {}
  }
  charts = [];
  eegChartContainers = [];
}

function applyThemeToCharts(theme) {
  const isLight = String(theme || (document.documentElement.getAttribute('data-theme') || 'light')) === 'light';
  const lineColor = isLight ? '#000000' : '#ffffff';
  const axisColor = isLight ? '#111827' : 'rgba(255, 255, 255, 0.78)';
  const splitColor = isLight ? 'rgba(17, 24, 39, 0.10)' : 'rgba(0, 0, 0, 0.18)';
  for (const ch of charts) {
    if (!ch) continue;
    ch.setOption({
      yAxis: {
        axisLabel: { color: axisColor },
        splitLine: { lineStyle: { color: splitColor, type: 'dashed' } },
      },
      series: [{ lineStyle: { color: lineColor, width: 1.6 } }],
    }, false, false);
  }
}

class FloatRingBuffer {
  constructor(capacity) {
    this.capacity = Math.max(1, Number(capacity) | 0);
    this.buf = new Float32Array(this.capacity);
    this.start = 0;
    this.length = 0;
  }

  push(v) {
    const x = Number(v);
    const vv = Number.isFinite(x) ? x : 0;
    if (this.length < this.capacity) {
      const idx = (this.start + this.length) % this.capacity;
      this.buf[idx] = vv;
      this.length += 1;
      return;
    }
    this.buf[this.start] = vv;
    this.start = (this.start + 1) % this.capacity;
  }

  at(i) {
    const idx = (this.start + i) % this.capacity;
    return this.buf[idx];
  }
}

function buildSeriesPoints(ring, samplingRateHz, targetPoints) {
  if (!ring || ring.length <= 0) return [];
  const sr = Math.max(1, Number(samplingRateHz) || 1);
  const n = ring.length;
  const tgt = Math.max(10, Math.min(n, Number(targetPoints) | 0));
  if (n <= tgt) {
    const out = new Array(n);
    for (let i = 0; i < n; i++) {
      out[i] = [(i - (n - 1)) / sr, ring.at(i)];
    }
    return out;
  }
  const out = [];
  const bucketSize = n / tgt;
  for (let b = 0; b < tgt; b++) {
    const s = Math.floor(b * bucketSize);
    const e = Math.min(n, Math.floor((b + 1) * bucketSize));
    if (e <= s) continue;
    let minV = Infinity;
    let maxV = -Infinity;
    let minI = s;
    let maxI = s;
    for (let i = s; i < e; i++) {
      const v = ring.at(i);
      if (v < minV) { minV = v; minI = i; }
      if (v > maxV) { maxV = v; maxI = i; }
    }
    const pushPoint = (idx, val) => { out.push([(idx - (n - 1)) / sr, val]); };
    if (minI === maxI) {
      pushPoint(minI, minV);
    } else if (minI < maxI) {
      pushPoint(minI, minV);
      pushPoint(maxI, maxV);
    } else {
      pushPoint(maxI, maxV);
      pushPoint(minI, minV);
    }
  }
  const lastV = ring.at(n - 1);
  out.push([0, lastV]);
  return out;
}

function computeTargetPointsForChart(chart) {
  const width = chart && typeof chart.getWidth === 'function' ? chart.getWidth() : 600;
  const adaptive = Math.max(80, Math.floor(width * 1.5));
  return Math.min(eegMaxRenderPointsPerChannel, adaptive);
}

function updateVisibleMask(forceAll) {
  if (!eegGridEl) return;
  if (forceAll) {
    eegVisibleMask = Array.from({ length: channels }, () => true);
    return;
  }
  const gridRect = eegGridEl.getBoundingClientRect();
  const top = gridRect.top - 200;
  const bottom = gridRect.bottom + 200;
  const mask = Array.from({ length: channels }, () => false);
  for (let i = 0; i < channels; i++) {
    const el = eegChartContainers[i];
    if (!el) continue;
    const r = el.getBoundingClientRect();
    if (r.bottom >= top && r.top <= bottom) {
      mask[i] = true;
    }
  }
  eegVisibleMask = mask;
}

function updateVisibleCaches() {
  for (let i = 0; i < channels; i++) {
    if (!eegVisibleMask[i]) continue;
    const ch = charts[i];
    if (!ch || typeof ch.getWidth !== 'function') continue;
    const w = ch.getWidth();
    if (w !== eegChartWidthCache[i]) {
      eegChartWidthCache[i] = w;
      eegTargetPointsCache[i] = computeTargetPointsForChart(ch);
    }
  }
}

function scheduleVisibleUpdate(forceAll = false) {
  if (eegScrollCheckRequested) return;
  eegScrollCheckRequested = true;
  requestAnimationFrame(() => {
    eegScrollCheckRequested = false;
    updateVisibleMask(forceAll);
    updateVisibleCaches();
    eegDataDirty = true;
  });
}

function renderCharts() {
  let yAxisPatch = null;
  if (eegYAxisDynamicEnabled) {
    if (!eegGlobalScale) {
      yAxisPatch = { min: null, max: null };
    } else {
      let yAxisMin = globalYMin === Infinity ? null : Math.floor(globalYMin);
      let yAxisMax = globalYMax === -Infinity ? null : Math.ceil(globalYMax);
      const step = Number(eegYAxisStep);
      if (yAxisMin !== null && yAxisMax !== null) {
        let maxAbs = Math.max(Math.abs(yAxisMin), Math.abs(yAxisMax));
        if (Number.isFinite(step) && step > 0) {
          maxAbs = Math.ceil(maxAbs / step) * step;
          if (maxAbs === 0) maxAbs = step;
        } else if (maxAbs === 0) {
          maxAbs = 1;
        }
        yAxisMin = -maxAbs;
        yAxisMax = maxAbs;
      }
      const applyYAxis = (yAxisMin !== eegLastAppliedYAxisMin || yAxisMax !== eegLastAppliedYAxisMax);
      if (applyYAxis && yAxisMin !== null && yAxisMax !== null) {
        eegLastAppliedYAxisMin = yAxisMin;
        eegLastAppliedYAxisMax = yAxisMax;
        yAxisPatch = { min: yAxisMin, max: yAxisMax };
      } else if (eegYAxisModeDirty) {
        eegLastAppliedYAxisMin = null;
        eegLastAppliedYAxisMax = null;
        yAxisPatch = { min: null, max: null };
      }
    }
  } else {
    const m = clampNumber(eegYAxisFixedMax, eegYAxisFixedMaxMin, eegYAxisFixedMaxMax, 500);
    const yAxisMin = -m;
    const yAxisMax = m;
    const applyYAxis = (yAxisMin !== eegLastAppliedYAxisMin || yAxisMax !== eegLastAppliedYAxisMax);
    if (applyYAxis) {
      eegLastAppliedYAxisMin = yAxisMin;
      eegLastAppliedYAxisMax = yAxisMax;
      yAxisPatch = { min: yAxisMin, max: yAxisMax };
    }
  }
  eegYAxisModeDirty = false;

  for (let i = 0; i < channels; i++) {
    if (eegVisibleMask.length === channels && !eegVisibleMask[i]) continue;
    const ch = charts[i];
    if (!ch) continue;
    const ring = eegRings[i];
    const tgt = eegTargetPointsCache[i] > 0 ? eegTargetPointsCache[i] : computeTargetPointsForChart(ch);
    const points = buildSeriesPoints(ring, eegSamplingRateHz, tgt);
    const opt = {
      xAxis: { min: -eegWindowSec, max: 0 },
      series: [{ data: points }],
    };
    if (yAxisPatch) opt.yAxis = yAxisPatch;
    ch.setOption(opt, false, true);
  }
}

function enqueuePendingEegChunk(chunk) {
  if (!chunk) return;
  const maxN = Math.max(1, Number(eegWsMaxPendingChunks) | 0);
  if (eegPendingEegChunks.length >= maxN) {
    eegPendingEegChunks[eegPendingEegChunks.length - 1] = chunk;
    return;
  }
  eegPendingEegChunks.push(chunk);
}

function consumePendingEegChunks(maxChunks) {
  const n = Math.max(0, Number(maxChunks) | 0);
  if (n <= 0) return;
  if (eegPendingEegChunks.length <= 0) return;
  const take = Math.min(n, eegPendingEegChunks.length);
  const start = eegPendingEegChunks.length - take;
  const chunks = eegPendingEegChunks.slice(start);
  eegPendingEegChunks = [];
  for (const c of chunks) {
    handleEEGData(c);
  }
}

function eegRenderLoop() {
  if (!eegPageActive) {
    eegRenderLoopActive = false;
    return;
  }
  if (eegViewMode === 'time') consumePendingEegChunks(1);
  const now = performance.now();
  const intervalMs = 1000 / Math.max(5, Number(eegRenderFps) || 25);
  if (eegViewMode === 'time' && eegDataDirty && (now - eegLastRenderAtMs) >= intervalMs) {
    eegDataDirty = false;
    eegLastRenderAtMs = now;
    renderCharts();
  }
  requestAnimationFrame(eegRenderLoop);
}

function handleEEGData(chunk) {
  lastEegDataAtMs = Date.now();
  if (!eegHasData) {
    eegHasData = true;
    renderEegSubtitle();
  }
  let currentChunkMin = Infinity;
  let currentChunkMax = -Infinity;

  for (const sample of chunk) {
    if (!Array.isArray(sample) || sample.length < channels) continue;
    for (let i = 0; i < channels; i++) {
      const y = Number(sample[i]);
      if (Number.isNaN(y)) continue;
      if (y < currentChunkMin) currentChunkMin = y;
      if (y > currentChunkMax) currentChunkMax = y;
      if (eegRings[i]) eegRings[i].push(y);
    }
  }

  if (currentChunkMin < Infinity && currentChunkMax > -Infinity) {
    if (currentChunkMin < eegPendingMin) eegPendingMin = currentChunkMin;
    if (currentChunkMax > eegPendingMax) eegPendingMax = currentChunkMax;
    const now = performance.now();
    const hz = Math.max(0.2, Number(eegYAxisUpdateHz) || 2);
    const intervalMs = 1000 / hz;
    if ((now - eegLastYAxisUpdateAtMs) >= intervalMs) {
      eegLastYAxisUpdateAtMs = now;
      const margin = (eegPendingMax - eegPendingMin) * 0.1;
      const targetMin = eegPendingMin - margin;
      const targetMax = eegPendingMax + margin;
      if (globalYMin === Infinity) {
        globalYMin = targetMin;
        globalYMax = targetMax;
      } else {
        globalYMin = globalYMin * 0.9 + targetMin * 0.1;
        globalYMax = globalYMax * 0.9 + targetMax * 0.1;
      }
      eegPendingMin = Infinity;
      eegPendingMax = -Infinity;
    }
  }

  eegDataDirty = true;
  if (!eegRenderLoopActive) {
    eegRenderLoopActive = true;
    eegLastRenderAtMs = 0;
    requestAnimationFrame(eegRenderLoop);
  }
}

function connectEegWs() {
  const url = `ws://${window.location.host}/ws/eeg`;
  wsEeg = new WebSocket(url);
  wsEeg.onopen = () => {
    eegWsState = 'connected';
    renderEegSubtitle();
  };
  wsEeg.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === 'eeg_data') {
        lastEegDataAtMs = Date.now();
        enqueuePendingEegChunk(msg.data);
      }
    } catch (_) {}
  };
  wsEeg.onerror = () => {
    eegWsState = 'error';
    renderEegSubtitle();
  };
  wsEeg.onclose = () => {
    eegWsState = 'disconnected';
    renderEegSubtitle();
    if (!eegPageActive) return;
    if (eegStopping) return;
    if (eegReconnectTimer) return;
    eegReconnectTimer = setTimeout(() => {
      eegReconnectTimer = null;
      if (eegPageActive) connectEegWs();
    }, 1000);
  };
}

function connectDebugWs() {
  const url = `ws://${window.location.host}/ws/debug`;
  wsDebug = new WebSocket(url);
  wsDebug.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === 'debug_init' && Array.isArray(msg.events)) {
        debugLines = msg.events.map(formatDebugEvent);
        if (debugLines.length > 2000) debugLines = debugLines.slice(-2000);
        if (!debugPaused) scheduleDebugRender();
        return;
      }
      if (msg.type === 'debug_event' && msg.event) {
        const line = formatDebugEvent(msg.event);
        if (debugPaused) {
          debugBufferedLines.push(line);
          if (debugBufferedLines.length > 2000) debugBufferedLines = debugBufferedLines.slice(-2000);
        } else {
          debugLines.push(line);
          if (debugLines.length > 2000) debugLines = debugLines.slice(-2000);
          scheduleDebugRender();
        }
      }
    } catch (_) {}
  };
  wsDebug.onclose = () => {
    if (!eegPageActive) return;
    if (eegStopping) return;
    if (debugReconnectTimer) return;
    debugReconnectTimer = setTimeout(() => {
      debugReconnectTimer = null;
      if (eegPageActive) connectDebugWs();
    }, 1000);
  };
}

async function bootstrapDebug() {
  const filter = document.getElementById('debug-filter');
  const clearBtn = document.getElementById('debug-clear');
  const pauseBtn = document.getElementById('debug-pause');
  if (clearBtn) {
    clearBtn.onclick = () => {
      debugLines = [];
      debugBufferedLines = [];
      scheduleDebugRender();
    };
  }
  if (pauseBtn) {
    pauseBtn.textContent = debugPaused ? '继续滚动' : '暂停输出';
    pauseBtn.onclick = () => {
      debugPaused = !debugPaused;
      pauseBtn.textContent = debugPaused ? '继续滚动' : '暂停输出';
      if (!debugPaused) {
        if (debugBufferedLines.length > 0) {
          debugLines = debugLines.concat(debugBufferedLines);
          debugBufferedLines = [];
          if (debugLines.length > 2000) debugLines = debugLines.slice(-2000);
        }
        scheduleDebugRender();
      }
    };
  }
  if (filter) {
    filter.oninput = (e) => {
      debugFilterText = e.target.value || '';
      scheduleDebugRender();
    };
  }
}

export async function enterEegPage() {
  eegPageActive = true;
  eegStopping = false;
  eegViewMode = 'time';
  lastEegDataAtMs = 0;
  eegHasData = false;
  eegWsState = 'disconnected';
  eegStatusHint = '';
  eegSessionLocked = false;
  eegPendingEegChunks = [];
  debugDirty = false;
  debugRenderLoopActive = false;
  const startBtn = document.getElementById('btn-eeg-start');
  const stopBtn = document.getElementById('btn-eeg-stop');
  if (startBtn) startBtn.disabled = false;
  if (stopBtn) stopBtn.disabled = true;
  const pauseBtn = document.getElementById('debug-pause');
  if (pauseBtn) pauseBtn.textContent = debugPaused ? '继续滚动' : '暂停输出';
  bindEegWaveFocusToggle();

  try {
    const cfg = await getConfig();
    channels = cfg && cfg.n_channels ? Number(cfg.n_channels) : 8;
    channelNames = cfg && Array.isArray(cfg.channel_names) ? cfg.channel_names : [];
    eegSamplingRateHz = cfg && cfg.sampling_rate_hz ? Number(cfg.sampling_rate_hz) : 250;
    const uiWave = cfg && cfg.ui && cfg.ui.waveform ? cfg.ui.waveform : null;
    eegWindowSec = uiWave && typeof uiWave.time_window_sec === 'number' ? Number(uiWave.time_window_sec) : 1.0;
    eegRenderFps = uiWave && typeof uiWave.render_fps_hz === 'number' ? Number(uiWave.render_fps_hz) : 25;
    eegMaxRenderPointsPerChannel = uiWave && typeof uiWave.max_render_points_per_channel === 'number'
      ? Number(uiWave.max_render_points_per_channel)
      : 800;
    eegGlobalScale = uiWave && typeof uiWave.global_scale === 'boolean' ? !!uiWave.global_scale : true;
    eegWsMaxPendingChunks = uiWave && typeof uiWave.max_pending_ws_chunks === 'number'
      ? Number(uiWave.max_pending_ws_chunks)
      : 2;
    eegYAxisStep = uiWave && typeof uiWave.y_axis_step === 'number' ? Number(uiWave.y_axis_step) : 50;
    eegYAxisUpdateHz = uiWave && typeof uiWave.y_axis_update_hz === 'number' ? Number(uiWave.y_axis_update_hz) : 2;
    eegYAxisFixedMaxMin = uiWave && typeof uiWave.y_axis_fixed_max_min === 'number' ? Number(uiWave.y_axis_fixed_max_min) : 50;
    eegYAxisFixedMaxMax = uiWave && typeof uiWave.y_axis_fixed_max_max === 'number' ? Number(uiWave.y_axis_fixed_max_max) : 1500;
    eegYAxisFixedMaxStep = uiWave && typeof uiWave.y_axis_fixed_max_step === 'number' ? Number(uiWave.y_axis_fixed_max_step) : 50;
    const dynDefault = uiWave && typeof uiWave.y_axis_dynamic_default === 'boolean' ? !!uiWave.y_axis_dynamic_default : true;
    const fixedDefault = uiWave && typeof uiWave.y_axis_fixed_max_default === 'number' ? Number(uiWave.y_axis_fixed_max_default) : 500;
    let storedDyn = null;
    let storedMax = null;
    try { storedDyn = localStorage.getItem('bhb_eeg_yaxis_dynamic'); } catch (_) {}
    try { storedMax = localStorage.getItem('bhb_eeg_yaxis_fixed_max'); } catch (_) {}
    eegYAxisDynamicEnabled = storedDyn === null ? dynDefault : (String(storedDyn) === '1');
    eegYAxisFixedMax = clampNumber(storedMax === null ? fixedDefault : storedMax, eegYAxisFixedMaxMin, eegYAxisFixedMaxMax, fixedDefault);
    maxPoints = Math.max(50, Math.floor(Math.max(1, eegSamplingRateHz) * Math.max(0.2, eegWindowSec)));
    eegLastYAxisUpdateAtMs = 0;
    eegPendingMin = Infinity;
    eegPendingMax = -Infinity;
    eegLastAppliedYAxisMin = null;
    eegLastAppliedYAxisMax = null;
    eegYAxisModeDirty = true;
    const notchEl = document.getElementById('eeg-notch-hint');
    if (notchEl) {
      const notch = cfg && cfg.signal && cfg.signal.notch ? cfg.signal.notch : null;
      const hz = notch && typeof notch.freq_hz === 'number' ? notch.freq_hz : 50;
      notchEl.textContent = ` ｜ 默认开启 ${hz}Hz 工频陷波`;
    }
    const psdCfg = cfg && cfg.signal && cfg.signal.psd ? cfg.signal.psd : null;
    const fmax = psdCfg && psdCfg.fmax_hz != null ? Number(psdCfg.fmax_hz) : null;
    psdFmaxHz = Number.isFinite(fmax) ? fmax : null;
    const trg = cfg && cfg.trigger ? cfg.trigger : null;
    triggerEnabled = trg && typeof trg.enabled === 'boolean' ? !!trg.enabled : false;
    triggerActive = (!trg || trg.active === null || trg.active === undefined) ? null : !!trg.active;
  } catch (_) {}

  buildYAxisControls();
  if (psdView) {
    try { psdView.dispose(); } catch (_) {}
    psdView = null;
  }
  psdView = new EegPsdView({ channelNames, fmaxHz: psdFmaxHz, triggerEnabled, triggerActive });
  psdView.mount({
    controlsId: 'eeg-view-controls',
    timeViewId: 'eeg-time-view',
    psdViewId: 'eeg-psd-view',
    chartId: 'psd-chart',
    toolbarId: 'psd-toolbar',
    onModeChange: (m) => {
      eegViewMode = m === 'psd' ? 'psd' : 'time';
      const yAxis = document.getElementById('eeg-yaxis-controls');
      if (yAxis) yAxis.classList.toggle('eeg-yaxis-controls--disabled', eegViewMode === 'psd');
    }
  });
  initCharts();
  if (!eegGridScrollHandler) {
    eegGridScrollHandler = () => {
      scheduleVisibleUpdate(false);
    };
  }
  if (eegGridEl) {
    try { eegGridEl.removeEventListener('scroll', eegGridScrollHandler); } catch (_) {}
    eegGridEl.addEventListener('scroll', eegGridScrollHandler, { passive: true });
  }
  if (!eegResizeListenerAttached) {
    eegResizeListenerAttached = true;
    eegResizeHandler = () => {
      if (!eegPageActive) return;
      syncEegFocusLayoutMetrics(
        document.querySelector('#page-eeg .eeg-layout'),
        document.getElementById('eeg-debug-body')
      );
      charts.forEach(c => c && c.resize());
      scheduleVisibleUpdate(true);
    };
    window.addEventListener('resize', eegResizeHandler);
  }
  scheduleVisibleUpdate(false);
  await bootstrapDebug();
  connectEegWs();
  connectDebugWs();
  eegDataDirty = false;
  if (!eegRenderLoopActive) {
    eegRenderLoopActive = true;
    eegLastRenderAtMs = 0;
    requestAnimationFrame(eegRenderLoop);
  }
  applyThemeToCharts(document.documentElement.getAttribute('data-theme') || 'light');
  if (psdView) psdView.setTheme(document.documentElement.getAttribute('data-theme') || 'light');
  renderEegSubtitle();
  if (!eegStatusEventBound) {
    eegStatusEventHandler = (event) => {
      if (!eegPageActive) return;
      applyEegStatusSnapshot(event && event.detail ? event.detail : null);
    };
    window.addEventListener('app:status', eegStatusEventHandler);
    eegStatusEventBound = true;
  }
  await refreshEegStatusHint();

  if (eegStatusTimer) { try { clearInterval(eegStatusTimer); } catch (_) {} }
  eegStatusTimer = setInterval(() => { if (eegPageActive) refreshEegStatusHint(); }, 2000);
  if (eegDataWatchTimer) { try { clearInterval(eegDataWatchTimer); } catch (_) {} }
  eegDataWatchTimer = setInterval(() => {
    if (!eegPageActive) return;
    if (eegWsState !== 'connected') return;
    if (!lastEegDataAtMs) return;
    const idleMs = Date.now() - lastEegDataAtMs;
    if (idleMs > 1500 && eegHasData) {
      eegHasData = false;
      renderEegSubtitle();
    }
  }, 500);

  if (!themeListenerAttached) {
    themeListenerAttached = true;
    themeChangeHandler = (ev) => {
      const t = ev && ev.detail && ev.detail.theme ? ev.detail.theme : (document.documentElement.getAttribute('data-theme') || 'light');
      applyThemeToCharts(t);
      if (psdView) psdView.setTheme(t);
    };
    window.addEventListener('bhb-theme-change', themeChangeHandler);
  }

  if (startBtn) {
    startBtn.onclick = async () => {
      if (eegSessionLocked) {
        return;
      }
      eegSessionLocked = true;
      startBtn.disabled = true;
      if (stopBtn) stopBtn.disabled = true;
      try {
        const res = await modeStart('eeg');
        const ok = !!(res && res.status === 'success');
        if (!ok) eegSessionLocked = false;
      } catch (e) {
        eegSessionLocked = false;
      } finally {
        await refreshEegStatusHint();
      }
    };
  }
  if (stopBtn) {
    stopBtn.onclick = async () => {
      eegStopping = true;
      eegStatusHint = '正在停止采集...';
      renderEegSubtitle();
      if (eegReconnectTimer) { try { clearTimeout(eegReconnectTimer); } catch (_) {} eegReconnectTimer = null; }
      if (debugReconnectTimer) { try { clearTimeout(debugReconnectTimer); } catch (_) {} debugReconnectTimer = null; }
      if (wsEeg) { try { wsEeg.close(); } catch (_) {} wsEeg = null; }
      if (wsDebug) { try { wsDebug.close(); } catch (_) {} wsDebug = null; }
      if (psdView) psdView.close();
      stopBtn.disabled = true;
      if (startBtn) startBtn.disabled = true;
      try {
        const res = await modeStop('eeg');
        const ok = !!(res && res.status === 'success');
        if (ok) {
          eegSessionLocked = false;
          const sess = res && res.offline && res.offline.session ? res.offline.session : null;
          const sid = sess && sess.session_id ? String(sess.session_id) : '';
          const sdir = sess && sess.session_dir ? String(sess.session_dir) : '';
          if (sid) {
            try { sessionStorage.setItem('bhb_last_eeg_session', sid); } catch (_) {}
            try { sessionStorage.setItem('bhb_last_eeg_session_dir', sdir); } catch (_) {}
            try { sessionStorage.setItem('bhb_last_eeg_session_meta', JSON.stringify(sess || {})); } catch (_) {}
            await navigate('#offline');
          }
        }
      } catch (e) {
        eegStopping = false;
      } finally {
        if (eegPageActive) eegStopping = false;
        await refreshEegStatusHint();
      }
    };
  }

}

export async function leaveEegPage() {
  eegPageActive = false;
  eegRenderLoopActive = false;
  debugRenderLoopActive = false;
  if (eegGridEl && eegGridScrollHandler) {
    try { eegGridEl.removeEventListener('scroll', eegGridScrollHandler); } catch (_) {}
  }
  eegGridEl = null;
  if (eegResizeListenerAttached && eegResizeHandler) {
    try { window.removeEventListener('resize', eegResizeHandler); } catch (_) {}
    eegResizeListenerAttached = false;
    eegResizeHandler = null;
  }
  if (eegReconnectTimer) { try { clearTimeout(eegReconnectTimer); } catch (_) {} eegReconnectTimer = null; }
  if (debugReconnectTimer) { try { clearTimeout(debugReconnectTimer); } catch (_) {} debugReconnectTimer = null; }
  if (eegStatusTimer) { try { clearInterval(eegStatusTimer); } catch (_) {} eegStatusTimer = null; }
  if (eegDataWatchTimer) { try { clearInterval(eegDataWatchTimer); } catch (_) {} eegDataWatchTimer = null; }
  if (wsEeg) { try { wsEeg.close(); } catch (_) {} wsEeg = null; }
  if (wsDebug) { try { wsDebug.close(); } catch (_) {} wsDebug = null; }
  if (psdView) { try { psdView.dispose(); } catch (_) {} psdView = null; }
  if (themeListenerAttached && themeChangeHandler) {
    window.removeEventListener('bhb-theme-change', themeChangeHandler);
    themeListenerAttached = false;
    themeChangeHandler = null;
  }
  if (eegStatusEventBound && eegStatusEventHandler) {
    window.removeEventListener('app:status', eegStatusEventHandler);
    eegStatusEventBound = false;
    eegStatusEventHandler = null;
  }
  eegPendingEegChunks = [];
  disposeCharts();
}
