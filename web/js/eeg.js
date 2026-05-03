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
- 2026-05-03: 1.1.1 页面提示补充 50Hz 工频陷波（不可关闭）
- 2026-05-03: 1.1.2 合并 EEG 波形提示为一行；去除电量“无更新”提示

作者: Spoon
版本: 1.1.2
*/

import { getConfig, getStatus, modeStart, modeStop } from './api.js';
import { navigate } from './router.js';

let wsEeg = null;
let wsDebug = null;

let charts = [];
let chartData = [];
let channels = 8;
let channelNames = [];
let maxPoints = 500;

let updateRequested = false;
let globalYMin = Infinity;
let globalYMax = -Infinity;

let debugLines = [];
let debugFilterText = '';
let debugPaused = false;
let debugBufferedLines = [];
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

function initCharts() {
  const grid = document.getElementById('charts-grid');
  if (!grid) return;
  const isLight = (document.documentElement.getAttribute('data-theme') || 'light') === 'light';

  grid.innerHTML = '';
  charts = [];
  chartData = Array.from({ length: channels }, () => []);
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

    const chart = echarts.init(chartDiv, null, { renderer: 'canvas' });
    chart.setOption({
      backgroundColor: 'transparent',
      grid: { top: 24, bottom: 12, left: 64, right: 10 },
      xAxis: { type: 'value', show: false, boundaryGap: false, min: 'dataMin', max: 'dataMax' },
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
        lineStyle: { color: isLight ? '#000000' : '#ffffff', width: 1.6 }
      }],
      animation: false,
    });

    charts.push(chart);
  }
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

function updateCharts() {
  updateRequested = false;

  const yAxisMin = globalYMin === Infinity ? null : Math.floor(globalYMin);
  const yAxisMax = globalYMax === -Infinity ? null : Math.ceil(globalYMax);

  for (let i = 0; i < channels; i++) {
    if (!charts[i]) continue;
    charts[i].setOption({
      yAxis: { min: yAxisMin, max: yAxisMax },
      series: [{ data: chartData[i] }],
    }, false, false);
  }
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
      const lastX = chartData[i].length > 0 ? chartData[i][chartData[i].length - 1][0] : 0;
      const y = Number(sample[i]);
      if (Number.isNaN(y)) continue;
      if (y < currentChunkMin) currentChunkMin = y;
      if (y > currentChunkMax) currentChunkMax = y;
      chartData[i].push([lastX + 1, y]);
      if (chartData[i].length > maxPoints) chartData[i].shift();
    }
  }

  if (currentChunkMin < Infinity && currentChunkMax > -Infinity) {
    const margin = (currentChunkMax - currentChunkMin) * 0.1;
    const targetMin = currentChunkMin - margin;
    const targetMax = currentChunkMax + margin;
    if (globalYMin === Infinity) {
      globalYMin = targetMin;
      globalYMax = targetMax;
    } else {
      globalYMin = globalYMin * 0.9 + targetMin * 0.1;
      globalYMax = globalYMax * 0.9 + targetMax * 0.1;
    }
  }

  if (!updateRequested) {
    updateRequested = true;
    requestAnimationFrame(updateCharts);
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
      if (msg.type === 'eeg_data') handleEEGData(msg.data);
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
        if (!debugPaused) {
          renderDebug();
        }
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
          renderDebug();
        }
      }
    } catch (_) {}
  };
  wsDebug.onclose = () => {
    if (!eegPageActive) return;
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
      renderDebug();
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
        renderDebug();
      }
    };
  }
  if (filter) {
    filter.oninput = (e) => {
      debugFilterText = e.target.value || '';
      renderDebug();
    };
  }
}

export async function enterEegPage() {
  eegPageActive = true;
  lastEegDataAtMs = 0;
  eegHasData = false;
  eegWsState = 'disconnected';
  eegStatusHint = '';
  eegSessionLocked = false;
  const startBtn = document.getElementById('btn-eeg-start');
  const stopBtn = document.getElementById('btn-eeg-stop');
  if (startBtn) startBtn.disabled = false;
  if (stopBtn) stopBtn.disabled = true;
  const pauseBtn = document.getElementById('debug-pause');
  if (pauseBtn) pauseBtn.textContent = debugPaused ? '继续滚动' : '暂停输出';

  try {
    const cfg = await getConfig();
    channels = cfg && cfg.mode_channels ? Number(cfg.mode_channels) : 8;
    channelNames = cfg && Array.isArray(cfg.channel_names) ? cfg.channel_names : [];
    const samplingRate = cfg && cfg.sampling_rate_hz ? Number(cfg.sampling_rate_hz) : 250;
    maxPoints = Math.max(50, Math.floor(samplingRate * 2));
    const notchEl = document.getElementById('eeg-notch-hint');
    if (notchEl) {
      const notch = cfg && cfg.signal && cfg.signal.notch ? cfg.signal.notch : null;
      const hz = notch && typeof notch.freq_hz === 'number' ? notch.freq_hz : 50;
      notchEl.textContent = ` ｜ 默认开启 ${hz}Hz 工频陷波（不可关闭）`;
    }
  } catch (_) {}

  initCharts();
  await bootstrapDebug();
  connectEegWs();
  connectDebugWs();
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
            await navigate('#offline');
          }
        }
      } catch (e) {
      } finally {
        await refreshEegStatusHint();
      }
    };
  }

  window.addEventListener('resize', () => { charts.forEach(c => c && c.resize()); }, { once: true });
}

export async function leaveEegPage() {
  eegPageActive = false;
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
}
