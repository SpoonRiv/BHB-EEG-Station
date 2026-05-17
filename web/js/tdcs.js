/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 电刺激（tDCS）页面逻辑（按配置启用/禁用、监测数据展示、下发 start/stop 与两级控制指令）

修改日志:
- 2026-05-04: 1.0.0 创建文件
- 2026-05-04: 1.0.1 根据后端 status 字段判断成功/失败并展示错误消息
- 2026-05-04: 1.0.2 增加调试输出窗口（ws/debug，过滤/清空/暂停）
- 2026-05-04: 1.0.3 按 task_running/task_mode 刷新按钮状态：运行中禁用“开始”并启用“停止”，并与顶部导航锁定一致
- 2026-05-04: 1.0.4 点击 start/stop 时立即临时禁用顶部导航按钮，避免状态轮询延迟导致误操作
- 2026-05-04: 1.0.5 页面内状态轮询同步顶部导航锁定（以 task_running 为准），停止后无需等待全局轮询即可解锁
- 2026-05-09: 1.0.6 增加电量徽标渲染与 tDCS 监测数据展示（TDCS_FRAME）
- 2026-05-09: 1.0.7 去掉“设备未连接”提示框样式，页面改为数据/控制双栏分框
- 2026-05-12: 1.0.8 接入两级指令控制面板（动态生成按钮并下发到采集进程）
- 2026-05-12: 1.0.9 状态提示改为无框文本并在空内容时隐藏（参考阻抗检测风格）
- 2026-05-12: 1.0.10 tDCS 页面不再展示“设备未连接”提示文案（保持页面简洁）
- 2026-05-17: 1.0.11 更新电刺激页面状态提示文案（占位 -> 已实现）
- 2026-05-17: 1.0.12 固定电量徽标“电量”字样位置，并与 EEG 页面保持一致
- 2026-05-17: 1.0.13 电量徽标数值靠左显示；未连接时提示灯默认红色

作者: Spoon
版本: 1.0.13
*/

import { getConfig, getStatus, modeStart, modeStop } from './api.js';
import { initTdcsControlPanel } from './tdcs_control.js';

let pageActive = false;
let bound = false;
let statusTimer = null;
let tdcsConfigEnabled = false;

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
  const t = String(text || '').trim();
  box.textContent = t;
  box.style.display = t ? '' : 'none';
}

function renderBatteryBadge(battery, running) {
  const badge = document.getElementById('tdcs-battery-badge');
  const textEl = document.getElementById('tdcs-battery-text');
  if (!badge || !textEl) return;

  badge.classList.remove('active', 'warn', 'error');

  if (!running) {
    textEl.textContent = '--';
    badge.classList.add('error');
    return;
  }

  const v = battery && typeof battery.value === 'number' ? battery.value : null;
  if (v === null || !Number.isFinite(v)) {
    textEl.textContent = '获取中';
    badge.classList.add('warn');
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

function setReservedVisible(visible) {
  const el = document.getElementById('tdcs-reserved');
  if (!el) return;
  el.style.display = visible ? '' : 'none';
}

function renderTdcsControlButtons(running, connected, taskActive) {
  const startBtn = document.getElementById('btn-tdcs-start');
  const stopBtn = document.getElementById('btn-tdcs-stop');
  const enabled = !!tdcsConfigEnabled;
  if (startBtn) startBtn.disabled = (!enabled) || (!running) || (!connected) || !!taskActive;
  if (stopBtn) stopBtn.disabled = (!enabled) || (!running) || (!connected) || !taskActive;
}

function setHeaderNavDisabled(disabled) {
  const navDevice = document.getElementById('nav-device');
  const navMode = document.getElementById('nav-mode');
  if (navDevice) navDevice.disabled = !!disabled;
  if (navMode) navMode.disabled = !!disabled;
}

async function refreshTdcsStatusHint() {
  try {
    const st = await getStatus();
    const dev = st && st.device ? st.device : null;
    const running = !!(dev && dev.running);
    const last = dev && dev.last ? dev.last : null;
    const lastType = last && last.type ? String(last.type) : '';
    const connected = lastType === 'connected' || lastType === 'ready';
    const taskRunning = !!(dev && dev.task_running);
    const taskActive = taskRunning && String(dev.task_mode || '') === 'tdcs';
    setHeaderNavDisabled(taskRunning);
    renderTdcsControlButtons(running, connected, taskActive);
    renderBatteryBadge(dev && dev.battery ? dev.battery : null, running);
    if (!tdcsConfigEnabled) {
      setStatus('当前配置已禁用电刺激模式（tdcs.enabled=false）', 'error');
      return;
    }
    if (!running) {
      setStatus('', '');
      return;
    }
    if (!connected) {
      setStatus('设备连接未就绪（请等待连接完成或回到设备页排查）', 'error');
      return;
    }
    if (taskActive) {
      setStatus('电刺激运行中：已锁定“开始/设备/模式”等入口，请点击“停止电刺激”结束。', 'success');
      return;
    }
    setStatus('电刺激就绪：可在右侧控制面板下发参数/操作指令；点击“开启电刺激”进入运行态后将锁定入口。', '');
  } catch (_) {
    renderTdcsControlButtons(false, false, false);
    if (tdcsConfigEnabled) setStatus('后端未响应', 'error');
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
        if (msg.event.tag === 'TDCS_FRAME' && msg.event.data) {
          const d = msg.event.data;
          
          const outCurrUa = document.getElementById('tdcs-out-curr-ua');
          if (outCurrUa) {
            const v = `${Number(d.out_curr_uA).toFixed(2)} `;
            const unit = outCurrUa.querySelector('.tdcs-unit');
            if (unit) {
              if (outCurrUa.childNodes.length > 0) outCurrUa.childNodes[0].textContent = v;
              else outCurrUa.textContent = v;
            } else {
              outCurrUa.textContent = `${Number(d.out_curr_uA).toFixed(2)} uA`;
            }
          }
          
          const hvUv = document.getElementById('tdcs-hv-uv');
          if (hvUv) {
            const v = `${Number(d.hv_uV).toFixed(2)} `;
            const unit = hvUv.querySelector('.tdcs-unit');
            if (unit) {
              if (hvUv.childNodes.length > 0) hvUv.childNodes[0].textContent = v;
              else hvUv.textContent = v;
            } else {
              hvUv.textContent = `${Number(d.hv_uV).toFixed(2)} uV`;
            }
          }
          
          const outCurrRaw = document.getElementById('tdcs-out-curr-raw');
          if (outCurrRaw) outCurrRaw.textContent = d.out_curr_raw;
          
          const hvRaw = document.getElementById('tdcs-hv-raw');
          if (hvRaw) hvRaw.textContent = d.hv_raw;
          
          const stateWorking = document.getElementById('tdcs-state-working');
          if (stateWorking) {
            stateWorking.classList.remove('active', 'warn', 'error');
            stateWorking.classList.add(d.is_working ? 'active' : 'warn');
            stateWorking.querySelector('div:last-child').textContent = `CCS工作状态：${d.is_working ? '工作中' : '停止工作'}`;
          }
          
          const stateOpen = document.getElementById('tdcs-state-open');
          if (stateOpen) {
            stateOpen.classList.remove('active', 'warn', 'error');
            stateOpen.classList.add(d.open_circuit ? 'error' : 'active');
            stateOpen.querySelector('div:last-child').textContent = `负载开路故障：${d.open_circuit ? '开路故障' : '无故障'}`;
          }
          
          const stateOver = document.getElementById('tdcs-state-over');
          if (stateOver) {
            stateOver.classList.remove('active', 'warn', 'error');
            stateOver.classList.add(d.over_current ? 'error' : 'active');
            stateOver.querySelector('div:last-child').textContent = `负载过流故障：${d.over_current ? '过流故障' : '无故障'}`;
          }
        }
        
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
  tdcsConfigEnabled = enabled;
  const showReserved = !(cfg && cfg.tdcs && cfg.tdcs.ui && cfg.tdcs.ui.show_reserved === false);
  setReservedVisible(showReserved);
  await refreshTdcsStatusHint();
}

function ensureBound() {
  if (bound) return;
  bound = true;
  bootstrapTdcsDebug();
  void initTdcsControlPanel({ containerId: 'tdcs-controls', report: setStatus });
  const startBtn = document.getElementById('btn-tdcs-start');
  const stopBtn = document.getElementById('btn-tdcs-stop');
  if (startBtn) {
    startBtn.onclick = async () => {
      if (!pageActive) return;
      startBtn.disabled = true;
      setHeaderNavDisabled(true);
      try {
        setStatus('正在下发：开启电刺激…', '');
        const res = await modeStart('tdcs');
        const ok = !!(res && res.status === 'success');
        if (ok) {
          setStatus('已下发：开启电刺激（等待设备侧进入运行态…）', 'success');
        } else {
          const msg = res && res.message ? String(res.message) : '开启失败';
          setStatus(`开启失败：${msg}`, 'error');
        }
      } catch (e) {
        setStatus(`开启失败：${String(e && e.message ? e.message : e)}`, 'error');
      } finally {
        await refreshTdcsStatusHint();
      }
    };
  }
  if (stopBtn) {
    stopBtn.onclick = async () => {
      if (!pageActive) return;
      stopBtn.disabled = true;
      setHeaderNavDisabled(true);
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
        await refreshTdcsStatusHint();
      }
    };
  }
}

export async function enterTdcsPage() {
  pageActive = true;
  ensureBound();
  connectTdcsDebugWs();
  await loadAndApplyConfig();
  if (statusTimer) clearInterval(statusTimer);
  statusTimer = setInterval(() => { if (pageActive) void refreshTdcsStatusHint(); }, 1000);
}

export function leaveTdcsPage() {
  pageActive = false;
  if (statusTimer) clearInterval(statusTimer);
  statusTimer = null;
  closeWs(debugWs);
  debugWs = null;
}
