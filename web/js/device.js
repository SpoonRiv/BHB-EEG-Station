/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 设备选择页逻辑（扫描 -> 下拉选择 -> 连接/断开）

修改日志:
- 2026-05-02: 1.0.0 新增设备选择页
- 2026-05-03: 1.0.1 增加 10-20 通道选择地形图面板初始化

作者: Spoon
版本: 1.0.1
*/

import { bleConnect, bleDevices, bleDisconnect, getStatus } from './api.js';
import { navigate } from './router.js';
import { initTopomapPanel } from './topomap.js';

function renderSelect(selectEl, devices) {
  selectEl.innerHTML = '';

  const optAuto = document.createElement('option');
  optAuto.value = '';
  optAuto.textContent = '自动扫描并连接';
  selectEl.appendChild(optAuto);

  for (const d of devices) {
    const opt = document.createElement('option');
    opt.value = d.address || '';
    const rssi = (d.rssi === null || typeof d.rssi === 'undefined') ? '' : ` RSSI ${d.rssi}`;
    opt.textContent = `${d.name || 'Unknown'} (${d.address || '-'})${rssi}`;
    opt.dataset.name = d.name || '';
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

  setDeviceStatus('', '状态：未连接（请先扫描并选择设备）');
  selectEl.disabled = true;

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
        setDeviceStatus('success', `状态：扫描到 ${list.length} 个设备（请选择后点击连接）`);
      } else {
        selectEl.innerHTML = '<option value="">未扫描到设备</option>';
        setDeviceStatus('error', '状态：未扫描到设备（请确认设备已开机并靠近）');
      }
    } catch (e) {
      selectEl.innerHTML = '<option value="">扫描失败</option>';
      setDeviceStatus('error', `状态：扫描失败（${e.message || e}）`);
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
        setDeviceStatus('success', '状态：已连接（可进入模式选择）');
        await navigate('#mode');
      } else {
        setDeviceStatus('error', `状态：连接失败（${(res && res.message) ? res.message : '未知错误'}）`);
      }
    } catch (e) {
      setDeviceStatus('error', `状态：连接失败（${e.message || e}）`);
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
        setDeviceStatus('', '状态：已断开（请先扫描并选择设备）');
      } else {
        setDeviceStatus('error', `状态：断开失败（${(res && res.message) ? res.message : '未知错误'}）`);
      }
    } catch (e) {
      setDeviceStatus('error', `状态：断开失败（${e.message || e}）`);
    } finally {
      btnDisconnect.disabled = false;
    }
  });

  async function refreshHint() {
    try {
      const st = await getStatus();
      const last = st && st.device && st.device.last ? st.device.last : null;
      const t = last && last.type ? String(last.type) : 'idle';
      const name = last && last.name ? String(last.name) : '';
      const msg = last && last.message ? String(last.message) : '';
      if (t === 'connected' || t === 'ready') setDeviceStatus('success', `状态：已连接 ${name}`);
      else if (t === 'connecting') setDeviceStatus('', `状态：连接中 ${name}`);
      else if (t === 'error') setDeviceStatus('error', `状态：失败 ${name}${msg ? `（${msg}）` : ''}`);
      else setDeviceStatus('', '状态：未连接（请先扫描并选择设备）');
    } catch (_) {}
  }

  setInterval(refreshHint, 1200);
  refreshHint();
}
