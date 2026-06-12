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
- 2026-05-09: 1.0.11 (Fengye) 新增刺激模式
- 2026-05-17: 1.0.12 移除刺激模式路由与状态联动
- 2026-05-17: 1.0.13 主题切换图标改为 SVG，统一与按钮科技风样式
- 2026-05-17: 1.0.14 增加鼠标聚光交互：指针所在区域点亮极光背景
- 2026-05-17: 1.0.15 日间模式增强聚光强度，让特效同样明显
- 2026-05-17: 1.0.16 回归简约高级风：移除鼠标跟随聚光交互
- 2026-05-17: 1.0.17 顶栏分段导航同步路由激活态
- 2026-05-17: 1.0.18 顶栏分段导航取消选中时触发反向扫光动效
- 2026-05-17: 1.0.19 延长分段导航扫光时长并增强取消选中可见性
- 2026-05-17: 1.0.20 统一按钮扫光触发（悬浮与取消选中参数一致，确保右->左可见）
- 2026-05-29: 1.0.21 设备能力变化时自动刷新配置并通知模式页更新入口可用性
- 2026-05-30: 1.0.22 日间/夜间切换按钮图标与主题语义对齐（日间显示太阳，夜间显示月亮）
- 2026-06-11: 1.0.23 同步头部工作区的页面信息与系统状态，配合 UI 视觉焕新

作者: Spoon , Fengye
版本: 1.0.23
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

let statusTimer = null;
let navLocked = false;
const btnShineTimers = new WeakMap();
let btnShineTimeoutMs = 1100;
let lastStatusSnapshot = null;
let lastTdcsCapabilityKey = null;
let configRefreshInFlight = false;

const THEME_ICON_MOON = `
  <svg class="theme-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <path d="M21 14.5a8.5 8.5 0 0 1-11.5-11A9 9 0 1 0 21 14.5z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  </svg>
`;

const THEME_ICON_SUN = `
  <svg class="theme-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <circle cx="12" cy="12" r="4" fill="none" stroke="currentColor" stroke-width="2"/>
    <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M19.8 4.2l-2.1 2.1M6.3 17.7l-2.1 2.1" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
  </svg>
`;

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

function setHeaderStatusText(text) {
  const el = document.getElementById('header-status-text');
  if (!el) return;
  el.textContent = String(text || '等待连接');
}

function updateHeaderPageMeta() {
  const titleEl = document.getElementById('header-page-title');
  const descEl = document.getElementById('header-page-desc');
  if (!titleEl || !descEl) return;

  const raw = String(window.location.hash || '').trim();
  const hash = raw ? (raw.startsWith('#') ? raw : `#${raw}`) : '#device';
  const pageId = `page-${hash.replace(/^#/, '')}`;
  const pageEl = document.getElementById(pageId);

  const title = pageEl && pageEl.dataset && pageEl.dataset.pageTitle
    ? String(pageEl.dataset.pageTitle)
    : '设备准备';
  const desc = pageEl && pageEl.dataset && pageEl.dataset.pageDesc
    ? String(pageEl.dataset.pageDesc)
    : '完成设备扫描、通道配置与参考电极设置';

  titleEl.textContent = title;
  descEl.textContent = desc;
}

function applyConnBadge(deviceStatus) {
  const last = deviceStatus && deviceStatus.last ? deviceStatus.last : null;
  const configured = deviceStatus && deviceStatus.configured_name ? String(deviceStatus.configured_name) : '';
  const name = normalizeDeviceName(last && last.name ? String(last.name) : (configured || '未知设备'));
  const t = last && last.type ? String(last.type) : 'idle';
  const msg = normalizeDeviceMessage(last && last.message ? String(last.message) : '');

  if (t === 'connected' || t === 'ready') {
    setConnBadge('active', `已连接：${name}`);
    setHeaderStatusText(`已连接 ${name}`);
    return;
  }
  if (t === 'connecting') {
    setConnBadge('error', `连接中：${name}`);
    setHeaderStatusText(`连接中 ${name}`);
    return;
  }
  if (t === 'error') {
    void msg;
    setConnBadge('error', `连接失败：${name}`);
    setHeaderStatusText(`连接失败 ${name}`);
    return;
  }
  if (t === 'disconnected' || t === 'stopped') {
    setConnBadge('error', `连接已断开：${name}`);
    setHeaderStatusText(`连接已断开 ${name}`);
    return;
  }
  void configured;
  setConnBadge('error', '未连接');
  setHeaderStatusText('等待连接');
}

function applyNavLock(deviceStatus) {
  const running = Boolean(deviceStatus && deviceStatus.task_running);
  navLocked = running;
  const navDevice = document.getElementById('nav-device');
  const navMode = document.getElementById('nav-mode');
  if (navDevice) navDevice.disabled = running;
  if (navMode) navMode.disabled = running;
}

function getTdcsCapabilityKey(status) {
  const device = status && status.device ? status.device : null;
  const last = device && device.last ? device.last : null;
  const moduleInfo = device && device.module && typeof device.module === 'object' ? device.module : null;
  const cap = device && device.capabilities ? device.capabilities.tdcs : undefined;
  const t = last && last.type ? String(last.type) : '';
  const name = last && last.name ? String(last.name) : '';
  const eeg = moduleInfo && Number.isFinite(Number(moduleInfo.eeg_channels)) ? Number(moduleInfo.eeg_channels) : null;
  const stim = moduleInfo && Number.isFinite(Number(moduleInfo.stim_channels)) ? Number(moduleInfo.stim_channels) : null;
  const capStr = cap === undefined ? 'u' : String(cap);
  const eegStr = eeg === null ? 'n' : String(eeg);
  const stimStr = stim === null ? 'n' : String(stim);
  return `${t}|${name}|${capStr}|${eegStr}|${stimStr}`;
}

async function refreshConfigAndBroadcast() {
  if (configRefreshInFlight) return;
  configRefreshInFlight = true;
  try {
    const cfg = await getConfig();
    try {
      window.dispatchEvent(new CustomEvent('app:config', { detail: cfg }));
    } catch (_) {}
  } catch (_) {
  } finally {
    configRefreshInFlight = false;
  }
}

async function refreshStatusOnce() {
  try {
    const data = await getStatus();
    lastStatusSnapshot = data;
    if (data && data.device) {
      applyConnBadge(data.device);
      applyNavLock(data.device);
    }
    try {
      window.dispatchEvent(new CustomEvent('app:status', { detail: data }));
    } catch (_) {}
    const nextKey = getTdcsCapabilityKey(data);
    if (nextKey !== lastTdcsCapabilityKey) {
      lastTdcsCapabilityKey = nextKey;
      await refreshConfigAndBroadcast();
    }
  } catch (_) {
    setConnBadge('error', '后端未响应');
    setHeaderStatusText('后端未响应');
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

function updateHeaderNavActive() {
  const navDevice = document.getElementById('nav-device');
  const navMode = document.getElementById('nav-mode');
  const raw = String(window.location.hash || '').trim();
  const hash = raw ? (raw.startsWith('#') ? raw : `#${raw}`) : '#device';
  const deviceActive = hash === '#device';
  const modeActive = hash === '#mode';

  const applyBtnShine = (btn, type) => {
    if (!btn) return;
    const last = btnShineTimers.get(btn);
    if (last) clearTimeout(last);
    btn.classList.remove('btn-shine-in', 'btn-shine-out');
    void btn.offsetWidth;
    btn.classList.add(type);
    const timer = setTimeout(() => {
      btn.classList.remove(type);
      btnShineTimers.delete(btn);
    }, btnShineTimeoutMs);
    btnShineTimers.set(btn, timer);
  };

  if (navDevice) {
    const wasActive = navDevice.classList.contains('is-active');
    navDevice.classList.toggle('is-active', deviceActive);
    navDevice.setAttribute('aria-pressed', deviceActive ? 'true' : 'false');
    if (wasActive && !deviceActive) applyBtnShine(navDevice, 'btn-shine-out');
    if (!wasActive && deviceActive) applyBtnShine(navDevice, 'btn-shine-in');
  }
  if (navMode) {
    const wasActive = navMode.classList.contains('is-active');
    navMode.classList.toggle('is-active', modeActive);
    navMode.setAttribute('aria-pressed', modeActive ? 'true' : 'false');
    if (wasActive && !modeActive) applyBtnShine(navMode, 'btn-shine-out');
    if (!wasActive && modeActive) applyBtnShine(navMode, 'btn-shine-in');
  }

  updateHeaderPageMeta();
}

function parseDurationMs(value, fallbackMs) {
  const raw = String(value || '').trim();
  if (!raw) return fallbackMs;
  if (raw.endsWith('ms')) {
    const n = Number(raw.slice(0, -2).trim());
    return Number.isFinite(n) ? n : fallbackMs;
  }
  if (raw.endsWith('s')) {
    const n = Number(raw.slice(0, -1).trim());
    return Number.isFinite(n) ? n * 1000 : fallbackMs;
  }
  const n = Number(raw);
  return Number.isFinite(n) ? n : fallbackMs;
}

function initButtonShine() {
  const root = document.documentElement;
  const cssDuration = getComputedStyle(root).getPropertyValue('--btn-shine-duration');
  btnShineTimeoutMs = parseDurationMs(cssDuration, 900) + 160;

  const getBtn = (target) => {
    if (!target || typeof target.closest !== 'function') return null;
    return target.closest('.btn');
  };

  const applyBtnShine = (btn, type) => {
    if (!btn || btn.disabled) return;
    const last = btnShineTimers.get(btn);
    if (last) clearTimeout(last);
    btn.classList.remove('btn-shine-in', 'btn-shine-out');
    void btn.offsetWidth;
    btn.classList.add(type);
    const timer = setTimeout(() => {
      btn.classList.remove(type);
      btnShineTimers.delete(btn);
    }, btnShineTimeoutMs);
    btnShineTimers.set(btn, timer);
  };

  document.addEventListener('pointerover', (e) => {
    const btn = getBtn(e.target);
    if (!btn) return;
    if (e.relatedTarget && btn.contains(e.relatedTarget)) return;
    applyBtnShine(btn, 'btn-shine-in');
  });

  document.addEventListener('pointerout', (e) => {
    const btn = getBtn(e.target);
    if (!btn) return;
    if (e.relatedTarget && btn.contains(e.relatedTarget)) return;
    applyBtnShine(btn, 'btn-shine-out');
  });
}

function setTheme(theme) {
  const t = theme === 'light' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', t);
  try { localStorage.setItem('bhb_theme', t); } catch (_) {}
  const btn = document.getElementById('theme-toggle');
  if (!btn) return;
  btn.innerHTML = t === 'light' ? THEME_ICON_SUN : THEME_ICON_MOON;
  btn.setAttribute('aria-label', t === 'light' ? '日间模式（点击切换夜间模式）' : '夜间模式（点击切换日间模式）');
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
    const v = cfg && cfg.ui_version ? String(cfg.ui_version) : '2.0.1';
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
}


function init() {
  initDevicePage();
  initModePage();
  initRoutes();
  bindHeaderNav();
  updateHeaderNavActive();
  window.addEventListener('hashchange', updateHeaderNavActive);
  initButtonShine();
  initThemeToggle();
  initVersionLabel();
  startStatusPolling();
  startRouter();
}

init();
