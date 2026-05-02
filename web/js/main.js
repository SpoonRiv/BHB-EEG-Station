/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 前端入口（初始化路由、页面模块、状态轮询与顶部导航）

修改日志:
- 2026-05-02: 1.0.0 新增页面流入口
- 2026-05-02: 1.0.1 主题切换默认日间并允许按钮切换
- 2026-05-02: 1.0.2 状态轮询失败时提示后端未响应，避免前端显示陈旧连接状态

作者: Spoon
版本: 1.0.2
*/

import { getConfig, getStatus, modeStart, modeStop } from './api.js';
import { initDevicePage } from './device.js';
import { initModePage } from './mode.js';
import { enterEegPage, leaveEegPage } from './eeg.js';
import { registerRoute, startRouter, navigate } from './router.js';
import { setConnBadge, toast } from './ui.js';

let statusTimer = null;

function applyConnBadge(deviceStatus) {
  const last = deviceStatus && deviceStatus.last ? deviceStatus.last : null;
  const configured = deviceStatus && deviceStatus.configured_name ? String(deviceStatus.configured_name) : '';
  const name = last && last.name ? String(last.name) : (configured || '未知设备');
  const t = last && last.type ? String(last.type) : 'idle';
  const msg = last && last.message ? String(last.message) : '';

  if (t === 'connected' || t === 'ready') {
    setConnBadge('active', `已连接：${name}`);
    return;
  }
  if (t === 'connecting') {
    setConnBadge('', `连接中：${name}`);
    return;
  }
  if (t === 'error') {
    setConnBadge('error', `连接失败：${name}${msg ? `（${msg}）` : ''}`);
    return;
  }
  setConnBadge('', configured ? `未连接（期望：${configured}）` : '未连接');
}

async function refreshStatusOnce() {
  try {
    const data = await getStatus();
    if (data && data.device) applyConnBadge(data.device);
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
  if (navDevice) navDevice.onclick = () => navigate('#device');
  if (navMode) navMode.onclick = () => navigate('#mode');
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

function bindPlaceholderButtons() {
  const impStart = document.getElementById('btn-imp-start');
  const impStop = document.getElementById('btn-imp-stop');
  const tdcsStart = document.getElementById('btn-tdcs-start');
  const tdcsStop = document.getElementById('btn-tdcs-stop');

  if (impStart) {
    impStart.onclick = async () => {
      impStart.disabled = true;
      try {
        const res = await modeStart('impedance');
        toast((res && res.status === 'success') ? '开启阻抗检测模式' : ((res && res.message) || '切换失败'));
      } catch (e) {
        toast(`切换失败：${e.message || e}`);
      } finally {
        impStart.disabled = false;
      }
    };
  }
  if (impStop) {
    impStop.onclick = async () => {
      impStop.disabled = true;
      try {
        const res = await modeStop('impedance');
        toast((res && res.status === 'success') ? '阻抗检测已停止' : ((res && res.message) || '停止失败'));
      } catch (e) {
        toast(`停止失败：${e.message || e}`);
      } finally {
        impStop.disabled = false;
      }
    };
  }
  if (tdcsStart) {
    tdcsStart.onclick = async () => {
      tdcsStart.disabled = true;
      try {
        const res = await modeStart('tdcs');
        toast((res && res.status === 'success') ? '开启 tDCS 模式' : ((res && res.message) || '切换失败'));
      } catch (e) {
        toast(`切换失败：${e.message || e}`);
      } finally {
        tdcsStart.disabled = false;
      }
    };
  }
  if (tdcsStop) {
    tdcsStop.onclick = async () => {
      tdcsStop.disabled = true;
      try {
        const res = await modeStop('tdcs');
        toast((res && res.status === 'success') ? 'tDCS 已停止' : ((res && res.message) || '停止失败'));
      } catch (e) {
        toast(`停止失败：${e.message || e}`);
      } finally {
        tdcsStop.disabled = false;
      }
    };
  }
}

function initRoutes() {
  registerRoute('#device', { pageId: 'page-device' });
  registerRoute('#mode', { pageId: 'page-mode' });
  registerRoute('#eeg', { pageId: 'page-eeg', onEnter: enterEegPage, onLeave: leaveEegPage });
  registerRoute('#impedance', { pageId: 'page-impedance' });
  registerRoute('#tdcs', { pageId: 'page-tdcs' });
}

function init() {
  initDevicePage();
  initModePage();
  initRoutes();
  bindHeaderNav();
  initThemeToggle();
  initVersionLabel();
  bindPlaceholderButtons();
  startStatusPolling();
  startRouter();
}

init();
