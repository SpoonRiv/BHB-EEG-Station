/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 电刺激（tDCS）页面占位逻辑（按配置启用/禁用、下发 start/stop 指令、预留参数区）

修改日志:
- 2026-05-04: 1.0.0 创建文件
- 2026-05-04: 1.0.1 根据后端 status 字段判断成功/失败并展示错误消息
- 2026-05-04: 1.0.2 增加调试输出窗口（ws/debug，过滤/清空/暂停）

作者: Spoon
版本: 1.0.2
*/

import { getConfig, modeStart, modeStop } from './api.js';

let pageActive = false;
let bound = false;

let debugWs = null;
let debugLines = [];
let debugBufferedLines = [];
let debugPaused = false;
let debugFilterText = '';

function setStatus(text, kind) {
  const box = document.getElementById('tdcs-status');
  if (!box) return;
  box.classList.remove('success', 'error');
  if (kind === 'success') box.classList.add('success');
  if (kind === 'error') box.classList.add('error');
  box.textContent = text || '';
}

function setReservedVisible(visible) {
  const el = document.getElementById('tdcs-reserved');
  if (!el) return;
  el.style.display = visible ? '' : 'none';
}

function setButtonsEnabled(enabled) {
  const startBtn = document.getElementById('btn-tdcs-start');
  const stopBtn = document.getElementById('btn-tdcs-stop');
  if (startBtn) startBtn.disabled = !enabled;
  if (stopBtn) stopBtn.disabled = !enabled;
}

function formatLocalTsSeconds(tsSeconds) {
  const t = Number(tsSeconds);
  const dt = new Date((Number.isFinite(t) ? t : Date.now() / 1000) * 1000);
  const pad2 = (n) => String(n).padStart(2, '0');
  const pad3 = (n) => String(n).padStart(3, '0');
  return `${dt.getFullYear()}-${pad2(dt.getMonth() + 1)}-${pad2(dt.getDate())} ${pad2(dt.getHours())}:${pad2(dt.getMinutes())}:${pad2(dt.getSeconds())}.${pad3(dt.getMilliseconds())}`;
}

function formatDebugEvent(ev) {
  const ts = formatLocalTsSeconds(ev && ev.ts);
  const tag = String((ev && ev.tag) || 'DEBUG');
  const msg = ev && ev.message ? String(ev.message) : '';
  let dataStr = '';
  const data = ev && ev.data && typeof ev.data === 'object' ? ev.data : null;
  if (data && Object.keys(data).length > 0) {
    try { dataStr = JSON.stringify(data); } catch (_) {}
  }
  const tagWidth = 12;
  const tagPadded = tag.length >= tagWidth ? tag.slice(0, tagWidth) : tag.padEnd(tagWidth, ' ');
  return `${ts}\t[${tagPadded}]\t${msg}\t${dataStr}`;
}

function renderTdcsDebug() {
  const el = document.getElementById('tdcs-debug-log');
  if (!el) return;
  const shouldStickToBottom = (el.scrollTop + el.clientHeight) >= (el.scrollHeight - 6);
  const f = (debugFilterText || '').trim().toLowerCase();
  const out = f ? debugLines.filter(l => l.toLowerCase().includes(f)) : debugLines;
  el.textContent = out.join('\n');
  if (!debugPaused && shouldStickToBottom) {
    el.scrollTop = el.scrollHeight;
  }
}

function closeWs(ws) {
  try { if (ws) ws.close(); } catch (_) {}
}

function connectTdcsDebugWs() {
  closeWs(debugWs);
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  debugWs = new WebSocket(`${proto}://${location.host}/ws/debug`);
  debugWs.onmessage = (evt) => {
    try {
      const msg = JSON.parse(evt.data);
      if (!msg || typeof msg !== 'object') return;
      if (msg.type === 'debug_init') {
        const events = Array.isArray(msg.events) ? msg.events : [];
        debugLines = events.map(formatDebugEvent).slice(-500);
        debugBufferedLines = [];
        renderTdcsDebug();
        return;
      }
      if (msg.type === 'debug_event' && msg.event) {
        const line = formatDebugEvent(msg.event);
        if (debugPaused) {
          debugBufferedLines.push(line);
          if (debugBufferedLines.length > 500) debugBufferedLines = debugBufferedLines.slice(-500);
          return;
        }
        debugLines.push(line);
        if (debugLines.length > 500) debugLines = debugLines.slice(-500);
        renderTdcsDebug();
      }
    } catch (_) {}
  };
}

function bootstrapTdcsDebug() {
  const filter = document.getElementById('tdcs-debug-filter');
  const clearBtn = document.getElementById('tdcs-debug-clear');
  const pauseBtn = document.getElementById('tdcs-debug-pause');
  if (clearBtn) {
    clearBtn.onclick = () => {
      debugLines = [];
      debugBufferedLines = [];
      renderTdcsDebug();
    };
  }
  if (pauseBtn) {
    pauseBtn.textContent = debugPaused ? '继续滚动' : '暂停输出';
    pauseBtn.onclick = () => {
      debugPaused = !debugPaused;
      pauseBtn.textContent = debugPaused ? '继续滚动' : '暂停输出';
      if (!debugPaused && debugBufferedLines.length) {
        debugLines.push(...debugBufferedLines);
        debugBufferedLines = [];
        if (debugLines.length > 500) debugLines = debugLines.slice(-500);
        renderTdcsDebug();
      }
    };
  }
  if (filter) {
    filter.oninput = () => {
      debugFilterText = String(filter.value || '');
      renderTdcsDebug();
    };
  }
}

async function loadAndApplyConfig() {
  let cfg = null;
  try {
    cfg = await getConfig();
  } catch (_) {}
  const enabled = !!(cfg && cfg.tdcs && cfg.tdcs.enabled);
  const showReserved = !(cfg && cfg.tdcs && cfg.tdcs.ui && cfg.tdcs.ui.show_reserved === false);
  setReservedVisible(showReserved);
  if (!enabled) {
    setButtonsEnabled(false);
    setStatus('当前配置已禁用电刺激模式（tdcs.enabled=false）', 'error');
    return;
  }
  setButtonsEnabled(true);
  setStatus('电刺激页面占位：当前仅保留 start/stop 指令通路；参数与安全校验后续接入。', '');
}

function ensureBound() {
  if (bound) return;
  bound = true;
  bootstrapTdcsDebug();
  const startBtn = document.getElementById('btn-tdcs-start');
  const stopBtn = document.getElementById('btn-tdcs-stop');
  if (startBtn) {
    startBtn.onclick = async () => {
      if (!pageActive) return;
      startBtn.disabled = true;
      try {
        setStatus('正在下发：开启电刺激…', '');
        const res = await modeStart('tdcs');
        const ok = !!(res && res.status === 'success');
        if (ok) {
          setStatus('已下发：开启电刺激（设备侧执行过程后续接入状态回传）', 'success');
        } else {
          const msg = res && res.message ? String(res.message) : '开启失败';
          setStatus(`开启失败：${msg}`, 'error');
        }
      } catch (e) {
        setStatus(`开启失败：${String(e && e.message ? e.message : e)}`, 'error');
      } finally {
        startBtn.disabled = false;
      }
    };
  }
  if (stopBtn) {
    stopBtn.onclick = async () => {
      if (!pageActive) return;
      stopBtn.disabled = true;
      try {
        setStatus('正在下发：停止电刺激…', '');
        const res = await modeStop('tdcs');
        const ok = !!(res && res.status === 'success');
        if (ok) {
          setStatus('已下发：停止电刺激', 'success');
        } else {
          const msg = res && res.message ? String(res.message) : '停止失败';
          setStatus(`停止失败：${msg}`, 'error');
        }
      } catch (e) {
        setStatus(`停止失败：${String(e && e.message ? e.message : e)}`, 'error');
      } finally {
        stopBtn.disabled = false;
      }
    };
  }
}

export async function enterTdcsPage() {
  pageActive = true;
  ensureBound();
  connectTdcsDebugWs();
  await loadAndApplyConfig();
}

export function leaveTdcsPage() {
  pageActive = false;
  closeWs(debugWs);
  debugWs = null;
}
