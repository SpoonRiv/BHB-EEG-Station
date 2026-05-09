/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 前端入口（初始化路由、页面模块、状态轮询与顶部导航）

修改日志:
- 2026-05-02: 1.0.0 新增页面流入口
- 2026-05-02: 1.0.1 主题切换默认日间并允许按钮切换
- 2026-05-02: 1.0.2 状态轮询失败时提示后端未响应，避免前端显示陈旧连接状态
- 2026-05-03: 1.0.3 移除底部弹窗提示，统一改为按钮状态反馈
- 2026-05-03: 1.0.4 增加离线存储页面路由
- 2026-05-03: 1.0.5 断联与停止采集时显示“连接已断开”，避免误报“连接失败”
- 2026-05-03: 1.0.6 任务运行中锁定右上角导航按钮，禁止返回设备/模式页面
- 2026-05-04: 1.0.7 接入阻抗页面模块（WS 数据与可视化）
- 2026-05-04: 1.0.8 连接状态展示移除括号与英文提示，设备名去尾部括号后缀
- 2026-05-04: 1.0.9 连接状态文案规范：仅“未连接”与“连接失败：设备名”
- 2026-05-04: 1.0.10 拆分电刺激页面模块（tdcs.js），路由进入时初始化占位逻辑
- 2026-05-04: 1.0.10 非连接状态时顶部指示灯显示为红色
- 2026-05-09: 1.0.11 新增SSVEP刺激模式

作者: Spoon , Fengye
版本: 1.0.10
*/

import { getConfig, getStatus } from './api.js';
import { initDevicePage } from './device.js';
import { initModePage } from './mode.js';
import { enterEegPage, leaveEegPage } from './eeg.js';
import { enterImpedancePage, leaveImpedancePage } from './impedance.js';
import { enterOfflinePage, leaveOfflinePage } from './offline.js';
import { enterTdcsPage, leaveTdcsPage } from './tdcs.js';
import { registerRoute, startRouter, navigate } from './router.js';
import { setConnBadge } from './ui.js';
import { enterSsvepPage, leaveSsvepPage, initSsvepPage } from './ssvep.js';

let statusTimer = null;
let navLocked = false;

function stripTrailingParenSuffix(text) {
  let s = String(text || '').trim();
  for (let i = 0; i < 3; i++) {
    const next = s.replace(/\s*[\(\（][^()\（\）]{0,64}[\)\）]\s*$/g, '').trim();
    if (next === s) break;
    s = next;
  }
  return s;
}

function normalizeDeviceName(name) {
  const raw = String(name || '').trim();
  const cleaned = stripTrailingParenSuffix(raw);
  return cleaned || raw || '未知设备';
}

function normalizeDeviceMessage(msg) {
  const raw = stripTrailingParenSuffix(String(msg || '').trim());
  if (!raw) return '';
  const lower = raw.toLowerCase();
  if (lower === 'not connected' || lower === 'not_connected') return '未连接';
  const replaced = raw
    .replace(/not connected/ig, '未连接')
    .replace(/timeout/ig, '超时')
    .replace(/disconnected/ig, '已断开');
  if (/[a-zA-Z]/.test(replaced)) return '';
  return replaced;
}

function applyConnBadge(deviceStatus) {
  const last = deviceStatus && deviceStatus.last ? deviceStatus.last : null;
  const configured = deviceStatus && deviceStatus.configured_name ? String(deviceStatus.configured_name) : '';
  const name = normalizeDeviceName(last && last.name ? String(last.name) : (configured || '未知设备'));
  const t = last && last.type ? String(last.type) : 'idle';
  const msg = normalizeDeviceMessage(last && last.message ? String(last.message) : '');

  if (t === 'connected' || t === 'ready') {
    setConnBadge('active', `已连接：${name}`);
    return;
  }
  if (t === 'connecting') {
    setConnBadge('error', `连接中：${name}`);
    return;
  }
  if (t === 'error') {
    void msg;
    setConnBadge('error', `连接失败：${name}`);
    return;
  }
  if (t === 'disconnected' || t === 'stopped') {
    setConnBadge('error', `连接已断开：${name}`);
    return;
  }
  void configured;
  setConnBadge('error', '未连接');
}

function applyNavLock(deviceStatus) {
  const running = Boolean(deviceStatus && deviceStatus.task_running);
  navLocked = running;
  const navDevice = document.getElementById('nav-device');
  const navMode = document.getElementById('nav-mode');
  if (navDevice) navDevice.disabled = running;
  if (navMode) navMode.disabled = running;
}

async function refreshStatusOnce() {
  try {
    const data = await getStatus();
    if (data && data.device) {
      applyConnBadge(data.device);
      applyNavLock(data.device);
    }

   const btnStart = document.getElementById('btn-ssvep-start');
    if (btnStart && btnStart.disabled && data.ssvep_running === false) {
        console.log("轮询检测到 SSVEP 已停止，恢复按钮");
        btnStart.disabled = false;
        btnStart.innerText = "启动刺激实验";
        
        const runStateText = document.getElementById('ssvep-run-state');
        if (runStateText) runStateText.innerText = "未运行";
        
        const statusStrip = document.getElementById('ssvep-status');
        if (statusStrip) {
            statusStrip.innerText = "等待启动...";
            statusStrip.className = "hint-strip";
        }
    }
  } catch (_) {
    setConnBadge('error', '后端未响应');
  }
}

function startStatusPolling() {
  if (statusTimer) clearInterval(statusTimer);
  refreshStatusOnce();
  statusTimer = setInterval(refreshStatusOnce, 1000);
}

function bindHeaderNav() {
  const navDevice = document.getElementById('nav-device');
  const navMode = document.getElementById('nav-mode');
  if (navDevice) {
    navDevice.onclick = () => {
      if (navLocked) return;
      navigate('#device');
    };
  }
  if (navMode) {
    navMode.onclick = () => {
      if (navLocked) return;
      navigate('#mode');
    };
  }
}

function setTheme(theme) {
  const t = theme === 'light' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', t);
  try { localStorage.setItem('bhb_theme', t); } catch (_) {}
  const btn = document.getElementById('theme-toggle');
  if (!btn) return;
  btn.innerHTML = t === 'light'
    ? '<span class="icon" aria-hidden="true">☾</span>'
    : '<span class="icon" aria-hidden="true">☀</span>';
  try {
    window.dispatchEvent(new CustomEvent('bhb-theme-change', { detail: { theme: t } }));
  } catch (_) {}
}

function initThemeToggle() {
  const btn = document.getElementById('theme-toggle');
  let initial = 'light';
  try { initial = localStorage.getItem('bhb_theme') || 'light'; } catch (_) {}
  setTheme(initial);
  if (btn) {
    btn.onclick = () => {
      const current = document.documentElement.getAttribute('data-theme') || 'dark';
      setTheme(current === 'light' ? 'dark' : 'light');
    };
  }
}

async function initVersionLabel() {
  const el = document.getElementById('brand-sub');
  if (!el) return;
  try {
    const cfg = await getConfig();
    const v = cfg && cfg.ui_version ? String(cfg.ui_version) : '1.0.0';
    el.textContent = `v${v}`;
  } catch (_) {}
}

function initRoutes() {
  registerRoute('#device', { pageId: 'page-device' });
  registerRoute('#mode', { pageId: 'page-mode' });
  registerRoute('#eeg', { pageId: 'page-eeg', onEnter: enterEegPage, onLeave: leaveEegPage });
  registerRoute('#offline', { pageId: 'page-offline', onEnter: enterOfflinePage, onLeave: leaveOfflinePage });
  registerRoute('#impedance', { pageId: 'page-impedance', onEnter: enterImpedancePage, onLeave: leaveImpedancePage });
  registerRoute('#tdcs', { pageId: 'page-tdcs', onEnter: enterTdcsPage, onLeave: leaveTdcsPage });
  registerRoute('#ssvep', { pageId: 'page-ssvep', onEnter: enterSsvepPage, onLeave: leaveSsvepPage });
}


function init() {
  initDevicePage();
  initModePage();
  initSsvepPage(); // 初始化 SSVEP 页面事件
  initRoutes();
  bindHeaderNav();
  initThemeToggle();
  initVersionLabel();
  startStatusPolling();
  startRouter();
}

init();
