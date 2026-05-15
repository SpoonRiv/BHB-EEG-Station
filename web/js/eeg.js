/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: EEG 页面逻辑（WebSocket 接收波形、ECharts 渲染、调试面板、模式启停）

修改日志:
- 2026-05-02: 1.0.0 新增 EEG 页面模块化实现
- 2026-05-02: 1.0.1 日间模式使用黑色波形并提升对比度
- 2026-05-02: 1.0.2 日间模式波形固定为黑色（更易辨识）
- 2026-05-02: 1.0.3 支持主题切换时实时更新波形颜色（日间黑/夜间白）
- 2026-05-02: 1.0.4 补充数据连接状态提示与断线自动重连，避免“无波形但无提示”
- 2026-05-02: 1.0.5 EEG 页面补充采集状态提示与数据心跳检测，便于定位“已连接但无波形”
- 2026-05-03: 1.0.6 EEG 页面增加电量徽标展示
- 2026-05-03: 1.0.7 修复电量展示刷新与按钮状态；暂停按钮改为暂停输出/继续滚动
- 2026-05-03: 1.0.8 修复暂停按钮初始化文案并强化开始采集互斥逻辑
- 2026-05-03: 1.0.9 取消开始/停止弹窗提示并改为按钮锁定；停止按钮按“会话锁”启用
- 2026-05-03: 1.1.0 停止采集后自动进入离线存储页并携带会话信息
- 2026-05-03: 1.1.1 页面提示补充 50Hz （不可关闭）
- 2026-05-03: 1.1.2 合并 EEG 波形提示为一行；去除电量“无更新”提示
- 2026-05-03: 1.1.3 停止采集时立即关闭 WS 并阻止重连，避免“停止中仍刷新”
- 2026-05-03: 1.1.4 停止采集后缓存会话元信息，供离线页展示采集时长与数据尺寸
- 2026-05-03: 1.1.5 波形展示改为环形缓冲+限帧渲染+降采样渲染，降低卡顿且不丢数据
- 2026-05-03: 1.1.6 滚动查看多通道时仅渲染可视区域，避免滚动导致渲染卡死
- 2026-05-03: 1.1.7 修复窗口尺寸变化时的可视渲染范围与降采样缓存刷新
- 2026-05-03: 1.1.8 配置命名区分“后端转发频率”和“前端渲染频率”
- 2026-05-04: 1.1.9 配置字段更名：mode_channels -> n_channels（与三模式命名一致）
- 2026-05-07: 1.1.10 修复长时间运行卡顿：离开页面释放图表实例；WS 数据增加背压并启用懒更新渲染
- 2026-05-07: 1.1.11 调试面板渲染加入限帧与批量刷新，避免高频调试事件导致主线程满载卡顿
- 2026-05-08: 1.1.12 动态 y 轴分档+限频更新，降低 Layout/Pre-paint；并按配置降低波形刷新频率
- 2026-05-15: 1.1.13 EEG 页面提示补充 0.5-80Hz 带通滤波（默认开启）

作者: Spoon
版本: 1.1.13
*/

import { getConfig, getStatus, modeStart, modeStop } from './api.js';
import { navigate } from './router.js';

let wsEeg = null;
let wsDebug = null;

let charts = [];
let channels = 8;
let channelNames = [];
let maxPoints = 500;

let eegSamplingRateHz = 250;
let eegWindowSec = 2.0;
let eegRenderFps = 25;
let eegMaxRenderPointsPerChannel = 800;
let eegGlobalScale = true;
let eegYAxisStep = 50;
let eegYAxisUpdateHz = 2;
let eegLastYAxisUpdateAtMs = 0;
let eegPendingMin = Infinity;
let eegPendingMax = -Infinity;
let eegLastAppliedYAxisMin = null;
let eegLastAppliedYAxisMax = null;

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
let lastEegDataAtMs = 0;
let eegWsState = 'disconnected';
let eegHasData = false;
let eegStatusHint = '';
let eegSessionLocked = false;
let eegStopping = false;

function renderBatteryBadge(battery, running, streaming) {
  const badge = document.getElementById('battery-badge');
  const textEl = document.getElementById('battery-text');
  if (!badge || !textEl) return;

  badge.classList.remove('active', 'warn', 'error');

  if (!running) {
    textEl.textContent = '电量：--';
    return;
  }

  if (streaming && (!battery || typeof battery !== 'object')) {
    textEl.textContent = '电量：获取中';
    badge.classList.add('warn');
    return;
  }

  const v = battery && typeof battery.value === 'number' ? battery.value : null;
  if (v === null || !Number.isFinite(v)) {
    textEl.textContent = streaming ? '电量：获取中' : '电量：--';
    if (streaming) badge.classList.add('warn');
    return;
  }

  const isPercent = Number.isInteger(v) && v >= 0 && v <= 100;
  if (isPercent) {
    textEl.textContent = `电量：${v}%`;
    if (v >= 50) badge.classList.add('active');
    else if (v >= 20) badge.classList.add('warn');
    else badge.classList.add('error');
    return;
  }

  textEl.textContent = `电量：${v}`;
}

function renderEegControlButtons(running, streaming) {
  const startBtn = document.getElementById('btn-eeg-start');
  const stopBtn = document.getElementById('btn-eeg-stop');
  if (startBtn) startBtn.disabled = (!running) || !!streaming || eegSessionLocked;
  if (stopBtn) stopBtn.disabled = (!running) || !eegSessionLocked;
}

function renderEegSubtitle() {
  const sub = document.getElementById('eeg-sub');
  if (!sub) return;
  if (eegStatusHint) {
    sub.textContent = eegStatusHint;
    return;
  }
  const wsText = eegWsState === 'connected'
    ? '数据连接：已连接'
    : (eegWsState === 'error' ? '数据连接：异常' : '数据连接：已断开');
  const dataText = eegWsState === 'connected' ? (eegHasData ? '（数据流）' : '（等待数据）') : '';
  sub.textContent = `${wsText}${dataText}`;
}

async function refreshEegStatusHint() {
  try {
    const st = await getStatus();
    const dev = st && st.device ? st.device : null;
    const running = !!(dev && dev.running);
    const streaming = !!(st && st.lsl_streaming);
    renderBatteryBadge(dev && dev.battery ? dev.battery : null, running, streaming);
    if (!running) eegSessionLocked = false;
    renderEegControlButtons(running, streaming);
    if (!running) {
      eegStatusHint = '设备未连接（请先在设备页连接）';
    } else if (!streaming) {
      eegStatusHint = '采集未启动（请点击“开始采集”）';
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
      grid: { top: 24, bottom: 12, left: 64, right: 10 },
      xAxis: { type: 'value', show: false, boundaryGap: false, min: -eegWindowSec, max: 0 },
      yAxis: {
        type: 'value',
        scale: true,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          color: isLight ? '#111827' : 'rgba(255, 255, 255, 0.78)',
          formatter: function (value) {
            const v = Number(value);
            if (!Number.isFinite(v)) return '';
            if (Math.abs(v) > 1001) return v.toExponential(0);
            return v.toFixed(0);
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
  let yAxisMin = globalYMin === Infinity ? null : Math.floor(globalYMin);
  let yAxisMax = globalYMax === -Infinity ? null : Math.ceil(globalYMax);
  const step = Number(eegYAxisStep);
  if (Number.isFinite(step) && step > 0 && yAxisMin !== null && yAxisMax !== null) {
    yAxisMin = Math.floor(yAxisMin / step) * step;
    yAxisMax = Math.ceil(yAxisMax / step) * step;
    if (yAxisMin === yAxisMax) {
      yAxisMin = yAxisMin - step;
      yAxisMax = yAxisMax + step;
    }
  }
  const applyYAxis = eegGlobalScale && (yAxisMin !== eegLastAppliedYAxisMin || yAxisMax !== eegLastAppliedYAxisMax);
  if (applyYAxis) {
    eegLastAppliedYAxisMin = yAxisMin;
    eegLastAppliedYAxisMax = yAxisMax;
  }

  for (let i = 0; i < channels; i++) {
    if (eegVisibleMask.length === channels && !eegVisibleMask[i]) continue;
    const ch = charts[i];
    if (!ch) continue;
    const ring = eegRings[i];
    const tgt = eegTargetPointsCache[i] > 0 ? eegTargetPointsCache[i] : computeTargetPointsForChart(ch);
    const points = buildSeriesPoints(ring, eegSamplingRateHz, tgt);
    ch.setOption({
      xAxis: { min: -eegWindowSec, max: 0 },
      ...(eegGlobalScale ? (applyYAxis ? { yAxis: { min: yAxisMin, max: yAxisMax } } : {}) : { yAxis: { min: null, max: null } }),
      series: [{ data: points }],
    }, false, true);
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
  consumePendingEegChunks(1);
  const now = performance.now();
  const intervalMs = 1000 / Math.max(5, Number(eegRenderFps) || 25);
  if (eegDataDirty && (now - eegLastRenderAtMs) >= intervalMs) {
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
    maxPoints = Math.max(50, Math.floor(Math.max(1, eegSamplingRateHz) * Math.max(0.2, eegWindowSec)));
    eegLastYAxisUpdateAtMs = 0;
    eegPendingMin = Infinity;
    eegPendingMax = -Infinity;
    eegLastAppliedYAxisMin = null;
    eegLastAppliedYAxisMax = null;
    const notchEl = document.getElementById('eeg-notch-hint');
    if (notchEl) {
      const notch = cfg && cfg.signal && cfg.signal.notch ? cfg.signal.notch : null;
      const hz = notch && typeof notch.freq_hz === 'number' ? notch.freq_hz : 50;
      const bp = cfg && cfg.signal && cfg.signal.bandpass ? cfg.signal.bandpass : null;
      const bpEnabled = bp && typeof bp.enabled === 'boolean' ? bp.enabled : true;
      const low = bp && typeof bp.lowcut_hz === 'number' ? bp.lowcut_hz : 0.5;
      const high = bp && typeof bp.highcut_hz === 'number' ? bp.highcut_hz : 80.0;
      notchEl.textContent = bpEnabled
        ? ` ｜ 默认开启 ${hz}Hz 工频陷波 ｜ 默认开启 ${low}-${high}Hz 带通滤波`
        : ` ｜ 默认开启 ${hz}Hz 工频陷波`;
    }
  } catch (_) {}

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
  renderEegSubtitle();
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
  if (themeListenerAttached && themeChangeHandler) {
    window.removeEventListener('bhb-theme-change', themeChangeHandler);
    themeListenerAttached = false;
    themeChangeHandler = null;
  }
  eegPendingEegChunks = [];
  disposeCharts();
}
