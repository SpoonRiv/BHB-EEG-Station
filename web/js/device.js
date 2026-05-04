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

作者: Spoon
版本: 1.0.7
*/

import { bleConnect, bleDevices, bleDisconnect, eegChannelOptions, getStatus } from './api.js';
import { navigate } from './router.js';
import { initTopomapPanel } from './eeg_topomap.js';

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

function renderSelect(selectEl, devices) {
  selectEl.innerHTML = '';

  const optAuto = document.createElement('option');
  optAuto.value = '';
  optAuto.textContent = '自动扫描并连接';
  selectEl.appendChild(optAuto);

  for (const d of devices) {
    const opt = document.createElement('option');
    opt.value = d.address || '';
    const rssi = (d.rssi === null || typeof d.rssi === 'undefined') ? '' : `｜信号 ${d.rssi}`;
    const displayName = normalizeDeviceName(d.name || '未知设备');
    opt.textContent = `${displayName}｜${d.address || '-'}${rssi}`;
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

  setDeviceStatus('', '状态：未连接，请先扫描并选择设备');
  selectEl.disabled = true;
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
    setDeviceStatus('', '状态：扫描中…');
    try {
      const data = await bleDevices(3.0, true);
      const list = (data && Array.isArray(data.devices)) ? data.devices : [];
      if (list.length > 0) {
        renderSelect(selectEl, list);
        selectEl.disabled = false;
        setDeviceStatus('success', `状态：扫描到 ${list.length} 个设备，请选择后点击连接`);
      } else {
        selectEl.innerHTML = '<option value="">未扫描到设备</option>';
        setDeviceStatus('error', '状态：未扫描到设备，请确认设备已开机并靠近');
      }
    } catch (e) {
      selectEl.innerHTML = '<option value="">扫描失败</option>';
      const err = normalizeDeviceMessage(e && (e.message || e)) || '未知错误';
      setDeviceStatus('error', `状态：扫描失败：${err}`);
    } finally {
      btnScan.disabled = false;
    }
  });

  btnConnect.addEventListener('click', async () => {
    btnConnect.disabled = true;
    setDeviceStatus('', '状态：连接中…');
    const address = selectEl.value || null;
    const selectedOpt = selectEl.selectedOptions && selectEl.selectedOptions[0] ? selectEl.selectedOptions[0] : null;
    const name = selectedOpt ? (selectedOpt.dataset.name || null) : null;
    try {
      const res = await bleConnect(address, name);
      if (res && res.status === 'success') {
        lastConnReady = true;
        setDeviceStatus('success', '状态：已连接，请先确认通道选择并点击“应用到系统”');
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
        setDeviceStatus('', '状态：已断开，请先扫描并选择设备');
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
          setDeviceStatus('success', `状态：已连接 ${name}，通道已应用`);
          if (!autoNavigated && (location.hash === '#device' || !location.hash)) {
            autoNavigated = true;
            await navigate('#mode');
          }
        } else {
          setDeviceStatus('success', `状态：已连接 ${name}`);
          autoNavigated = false;
        }
      }
      else if (t === 'connecting') setDeviceStatus('', `状态：连接中 ${name}`);
      else if (t === 'error') setDeviceStatus('error', `状态：失败 ${name}${msg ? `：${msg}` : ''}`.trim());
      else if (t === 'disconnected' || t === 'stopped') {
        autoNavigated = false;
        lastConnReady = false;
        setDeviceStatus('', `状态：已断开 ${name || ''}`.trim());
      }
      else {
        lastConnReady = false;
        setDeviceStatus('', '状态：未连接，请先扫描并选择设备');
      }
    } catch (_) {}
  }

  setInterval(refreshHint, 1200);
  refreshHint();
}
