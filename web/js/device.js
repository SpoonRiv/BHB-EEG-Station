/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 设备选择页逻辑（扫描 -> 下拉选择 -> 连接/断开）

修改日志:
- 2026-05-02: 1.0.0 新增设备选择页
- 2026-05-03: 1.0.1 增加 10-20 通道选择地形图面板初始化
- 2026-05-03: 1.0.2 断联与停止采集时显示“已断开”，避免误报“连接失败”
- 2026-05-04: 1.0.3 仅当蓝牙已连接且通道选择已完成并应用后，才自动跳转到模式页
- 2026-05-04: 1.0.4 设备名/错误提示移除括号与英文后缀，设备列表展示不再使用括号
- 2026-05-04: 1.0.5 自动跳转需同时满足：蓝牙连接成功 + 本次会话通道“应用成功”提示出现
- 2026-05-04: 1.0.6 配置字段更名：mode_channels -> n_channels（与三模式命名一致）
- 2026-05-04: 1.0.7 文件更名适配：topomap.js -> eeg_topomap.js
- 2026-05-17: 1.0.8 设备列表改为列表框选择（移除“自动扫描并连接”）
- 2026-05-17: 1.0.9 扫描列表标记“最近连接”设备（本机记忆）
- 2026-05-17: 1.0.10 设备列表回退为下拉选择（保留“最近连接”标记）
- 2026-05-17: 1.0.11 扫描成功状态提示文案调整
- 2026-05-17: 1.0.12 设备页状态文案规范统一（扫描/选择/连接）
- 2026-05-17: 1.0.13 “请选择设备”作为占位提示不出现在下拉选项中
- 2026-06-11: 1.0.14 设备列表接入自定义圆角下拉菜单，并保持与原生 select 值同步

作者: Spoon
版本: 1.0.14
*/

import { bleConnect, bleDevices, bleDisconnect, eegChannelOptions, getStatus } from './api.js';
import { navigate } from './router.js';
import { initTopomapPanel } from './eeg_topomap.js';

const RECENT_BLE_KEY = 'bhb_recent_ble_address';

function getRecentBleAddress() {
  try { return String(localStorage.getItem(RECENT_BLE_KEY) || '').trim() || null; } catch (_) { return null; }
}

function setRecentBleAddress(address) {
  const v = String(address || '').trim();
  if (!v) return;
  try { localStorage.setItem(RECENT_BLE_KEY, v); } catch (_) {}
}

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

function getSelectedDeviceInfo(selectEl) {
  const address = selectEl && selectEl.value ? String(selectEl.value || '').trim() : '';
  if (!address) return null;
  const selectedOpt = selectEl.selectedOptions && selectEl.selectedOptions[0] ? selectEl.selectedOptions[0] : null;
  const name = selectedOpt ? String(selectedOpt.dataset.name || '').trim() : '';
  return {
    address,
    name: name || null,
  };
}

function getSelectDisplayText(selectEl) {
  if (!selectEl) return '';
  const selectedOpt = selectEl.selectedOptions && selectEl.selectedOptions[0]
    ? selectEl.selectedOptions[0]
    : (selectEl.options && selectEl.options[0] ? selectEl.options[0] : null);
  return selectedOpt ? String(selectedOpt.textContent || '').trim() : '';
}

function setupCustomDeviceSelect(selectEl) {
  const shell = document.getElementById('device-select-shell');
  const trigger = document.getElementById('device-select-trigger');
  const textEl = document.getElementById('device-select-text');
  const menuEl = document.getElementById('device-select-menu');

  if (!shell || !trigger || !textEl || !menuEl || !selectEl) {
    return {
      sync() {},
      close() {},
    };
  }

  const closeMenu = () => {
    shell.classList.remove('is-open');
    trigger.setAttribute('aria-expanded', 'false');
    menuEl.hidden = true;
  };

  const renderMenu = () => {
    const currentValue = String(selectEl.value || '').trim();
    const options = Array.from(selectEl.options || []).filter((opt) => {
      const value = String(opt.value || '').trim();
      return !opt.hidden && !opt.disabled && !!value;
    });

    menuEl.innerHTML = '';

    for (const opt of options) {
      const item = document.createElement('button');
      const rawText = String(opt.textContent || '').trim();
      const isRecent = rawText.includes('【最近连接】');
      const mainText = isRecent ? rawText.replace(/\s*【最近连接】\s*$/, '').trim() : rawText;

      item.type = 'button';
      item.className = 'custom-select__option';
      item.setAttribute('role', 'option');
      item.setAttribute('aria-selected', String(String(opt.value || '').trim() === currentValue));
      if (String(opt.value || '').trim() === currentValue) item.classList.add('is-selected');

      const textSpan = document.createElement('span');
      textSpan.className = 'custom-select__option-text';
      textSpan.textContent = mainText;
      item.appendChild(textSpan);

      if (isRecent) {
        const badgeSpan = document.createElement('span');
        badgeSpan.className = 'custom-select__option-badge';
        badgeSpan.textContent = '最近连接';
        item.appendChild(badgeSpan);
      }

      item.addEventListener('click', () => {
        selectEl.value = String(opt.value || '').trim();
        selectEl.dispatchEvent(new Event('change', { bubbles: true }));
        closeMenu();
      });

      menuEl.appendChild(item);
    }
  };

  const sync = () => {
    textEl.textContent = getSelectDisplayText(selectEl) || '请选择设备';
    shell.classList.toggle('is-disabled', !!selectEl.disabled);
    shell.classList.toggle('has-value', !!String(selectEl.value || '').trim());
    trigger.disabled = !!selectEl.disabled;
    renderMenu();
    if (selectEl.disabled || !menuEl.childElementCount) closeMenu();
  };

  trigger.addEventListener('click', () => {
    if (trigger.disabled || !menuEl.childElementCount) return;
    const willOpen = !shell.classList.contains('is-open');
    if (!willOpen) {
      closeMenu();
      return;
    }
    renderMenu();
    shell.classList.add('is-open');
    trigger.setAttribute('aria-expanded', 'true');
    menuEl.hidden = false;
  });

  document.addEventListener('pointerdown', (event) => {
    if (!shell.contains(event.target)) closeMenu();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeMenu();
  });

  sync();
  return { sync, close: closeMenu };
}

function renderSelect(selectEl, devices) {
  selectEl.innerHTML = '';

  const optPrompt = document.createElement('option');
  optPrompt.value = '';
  optPrompt.textContent = '请选择设备';
  optPrompt.disabled = true;
  optPrompt.hidden = true;
  optPrompt.selected = true;
  selectEl.appendChild(optPrompt);

  const recentAddr = getRecentBleAddress();

  for (const d of devices) {
    const opt = document.createElement('option');
    opt.value = d.address || '';
    const rssi = (d.rssi === null || typeof d.rssi === 'undefined') ? '' : `｜信号 ${d.rssi}`;
    const displayName = normalizeDeviceName(d.name || '未知设备');
    const isRecent = recentAddr && d.address && String(d.address) === String(recentAddr);
    const badge = isRecent ? ' 【最近连接】' : '';
    opt.textContent = `${displayName}｜${d.address || '-'}${rssi}${badge}`;
    opt.dataset.name = displayName === '未知设备' ? '' : displayName;
    selectEl.appendChild(opt);
  }
}

function setDeviceStatus(level, text) {
  const box = document.getElementById('device-status');
  if (!box) return;
  box.classList.remove('success');
  box.classList.remove('error');
  if (level === 'success') box.classList.add('success');
  if (level === 'error') box.classList.add('error');
  box.textContent = String(text || '');
}

export function initDevicePage() {
  const btnScan = document.getElementById('btn-scan');
  const btnConnect = document.getElementById('btn-connect');
  const btnDisconnect = document.getElementById('btn-disconnect');
  const selectEl = document.getElementById('device-select');

  if (!btnScan || !btnConnect || !btnDisconnect || !selectEl) return;

  initTopomapPanel();
  const customSelect = setupCustomDeviceSelect(selectEl);

  let scanState = { status: 'idle', count: 0, message: '' };

  function renderIdleHint() {
    const sel = getSelectedDeviceInfo(selectEl);
    if (scanState.status === 'scanning') {
      setDeviceStatus('', '状态：正在扫描中');
      return;
    }
    if (scanState.status === 'failed') {
      const msg = scanState.message ? `：${scanState.message}` : '';
      setDeviceStatus('error', `状态：扫描失败${msg}`);
      return;
    }
    if (scanState.status === 'empty') {
      setDeviceStatus('error', '状态：未扫描到设备，请确认设备已开机并靠近');
      return;
    }
    if (scanState.status === 'success') {
      if (sel) {
        setDeviceStatus('success', `状态：已选择：${sel.name || sel.address}`);
      } else {
        setDeviceStatus('success', `状态：成功扫描到 ${scanState.count} 个设备，请选择`);
      }
      return;
    }
    setDeviceStatus('', '状态：请点击“扫描”');
  }

  renderIdleHint();
  selectEl.disabled = true;
  customSelect.sync();
  let autoNavigated = false;
  let lastChannelCheckAtMs = 0;
  let lastChannelReady = false;
  let lastConnReady = false;
  let channelAppliedOk = false;

  window.addEventListener('bhb-channel-selection-dirty', () => {
    channelAppliedOk = false;
    autoNavigated = false;
  });

  window.addEventListener('bhb-channel-applied', () => {
    channelAppliedOk = true;
    autoNavigated = false;
    if (lastConnReady && (location.hash === '#device' || !location.hash)) {
      void (async () => {
        const ok = await checkChannelReady();
        if (ok && channelAppliedOk && !autoNavigated) {
          autoNavigated = true;
          await navigate('#mode');
        }
      })();
    }
  });

  async function checkChannelReady() {
    const now = Date.now();
    if (now - lastChannelCheckAtMs < 1200) return lastChannelReady;
    lastChannelCheckAtMs = now;
    try {
      const opt = await eegChannelOptions();
      const pending = opt && opt.pending ? opt.pending : null;
      const effective = opt && opt.effective ? opt.effective : null;
      const pMode = pending ? Number(pending.n_channels) : 0;
      const pNames = pending && Array.isArray(pending.channel_names) ? pending.channel_names : [];
      const pRef = pending ? String(pending.ref_channel_name || '') : '';
      const eMode = effective ? Number(effective.n_channels) : 0;
      const eNames = effective && Array.isArray(effective.channel_names) ? effective.channel_names : [];
      const eRef = effective ? String(effective.ref_channel_name || '') : '';
      const selectedFull = pMode > 0 && pNames.length === pMode && !!pRef;
      const applied = selectedFull
        && eMode === pMode
        && eNames.length === pNames.length
        && eNames.every((x, i) => String(x) === String(pNames[i]))
        && String(eRef) === String(pRef);
      lastChannelReady = !!applied;
      return lastChannelReady;
    } catch (_) {
      lastChannelReady = false;
      return false;
    }
  }

  btnScan.addEventListener('click', async () => {
    btnScan.disabled = true;
    selectEl.disabled = true;
    customSelect.sync();
    scanState = { status: 'scanning', count: 0, message: '' };
    renderIdleHint();
    try {
      const data = await bleDevices(3.0, true);
      const list = (data && Array.isArray(data.devices)) ? data.devices : [];
      if (list.length > 0) {
        renderSelect(selectEl, list);
        selectEl.disabled = false;
        customSelect.sync();
        scanState = { status: 'success', count: list.length, message: '' };
        renderIdleHint();
      } else {
        selectEl.innerHTML = '<option value="" selected>未扫描到设备</option>';
        customSelect.sync();
        scanState = { status: 'empty', count: 0, message: '' };
        renderIdleHint();
      }
    } catch (e) {
      selectEl.innerHTML = '<option value="" selected>扫描失败</option>';
      customSelect.sync();
      const err = normalizeDeviceMessage(e && (e.message || e)) || '未知错误';
      scanState = { status: 'failed', count: 0, message: err };
      renderIdleHint();
    } finally {
      btnScan.disabled = false;
    }
  });

  btnConnect.addEventListener('click', async () => {
    btnConnect.disabled = true;
    const sel = getSelectedDeviceInfo(selectEl);
    try {
      if (!sel) {
        setDeviceStatus('error', '状态：请先选择设备');
        return;
      }
      setDeviceStatus('', `状态：连接中：${sel.name || sel.address}`);
      const res = await bleConnect(sel.address, sel.name);
      if (res && res.status === 'success') {
        setRecentBleAddress(sel.address);
        lastConnReady = true;
        setDeviceStatus('success', `状态：成功连接，请确认通道并点击“应用到系统”`);
        autoNavigated = false;
        const ok = await checkChannelReady();
        if (ok && channelAppliedOk) {
          autoNavigated = true;
          await navigate('#mode');
        }
      } else {
        lastConnReady = false;
        const err = normalizeDeviceMessage(res && res.message ? res.message : '') || ((res && res.message) ? '' : '未知错误');
        setDeviceStatus('error', err ? `状态：连接失败：${err}` : '状态：连接失败');
      }
    } catch (e) {
      lastConnReady = false;
      const err = normalizeDeviceMessage(e && (e.message || e)) || '未知错误';
      setDeviceStatus('error', `状态：连接失败：${err}`);
    } finally {
      btnConnect.disabled = false;
    }
  });

  btnDisconnect.addEventListener('click', async () => {
    btnDisconnect.disabled = true;
    setDeviceStatus('', '状态：断开中…');
    try {
      const res = await bleDisconnect();
      if (res && res.status === 'success') {
        lastConnReady = false;
        autoNavigated = false;
        renderIdleHint();
      } else {
        const err = normalizeDeviceMessage(res && res.message ? res.message : '') || ((res && res.message) ? '' : '未知错误');
        setDeviceStatus('error', err ? `状态：断开失败：${err}` : '状态：断开失败');
      }
    } catch (e) {
      lastConnReady = false;
      const err = normalizeDeviceMessage(e && (e.message || e)) || '未知错误';
      setDeviceStatus('error', `状态：断开失败：${err}`);
    } finally {
      btnDisconnect.disabled = false;
    }
  });

  selectEl.addEventListener('change', () => {
    customSelect.sync();
    if (lastConnReady) return;
    if (scanState.status !== 'success') return;
    renderIdleHint();
  });

  async function refreshHint() {
    try {
      const st = await getStatus();
      const last = st && st.device && st.device.last ? st.device.last : null;
      const t = last && last.type ? String(last.type) : 'idle';
      const name = normalizeDeviceName(last && last.name ? String(last.name) : '');
      const msg = normalizeDeviceMessage(last && last.message ? String(last.message) : '');
      if (t === 'connected' || t === 'ready') {
        lastConnReady = true;
        const ok = await checkChannelReady();
        if (ok && channelAppliedOk) {
          setDeviceStatus('success', `状态：成功连接，通道已应用`);
          if (!autoNavigated && (location.hash === '#device' || !location.hash)) {
            autoNavigated = true;
            await navigate('#mode');
          }
        } else {
          setDeviceStatus('success', `状态：成功连接，请确认通道并点击“应用到系统”`);
          autoNavigated = false;
        }
      }
      else if (t === 'connecting') setDeviceStatus('', `状态：连接中：${name || '设备'}`);
      else if (t === 'error') setDeviceStatus('error', `状态：连接失败${name ? `：${name}` : ''}${msg ? `：${msg}` : ''}`.trim());
      else if (t === 'disconnected' || t === 'stopped') {
        autoNavigated = false;
        lastConnReady = false;
        renderIdleHint();
      }
      else {
        lastConnReady = false;
        renderIdleHint();
      }
    } catch (_) {}
  }

  setInterval(refreshHint, 1200);
  refreshHint();
}
