/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 前端 API 封装（BLE 扫描/连接/模式控制/状态查询）

修改日志:
- 2026-05-02: 1.0.0 新增页面流 API
- 2026-05-03: 1.0.1 增加离线导出接口封装
- 2026-05-03: 1.0.2 增加离线会话查询接口封装
- 2026-05-03: 1.0.3 增加 10-20 通道选择与常用组合接口封装

作者: Spoon
版本: 1.0.3
*/

async function fetchJson(url, options) {
  const res = await fetch(url, options);
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (_) {}
  if (!res.ok) {
    const msg = (data && (data.message || data.detail)) ? (data.message || data.detail) : `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

export async function getConfig() {
  return fetchJson('/api/config');
}

export async function getStatus() {
  return fetchJson('/api/status');
}

export async function bleDevices(timeoutSec = 3.0, whitelistOnly = true) {
  const qs = new URLSearchParams({
    timeout_sec: String(timeoutSec),
    whitelist_only: whitelistOnly ? 'true' : 'false',
  });
  return fetchJson(`/api/ble/devices?${qs.toString()}`);
}

export async function bleConnect(address, name) {
  return fetchJson('/api/ble/connect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ address: address || null, name: name || null }),
  });
}

export async function bleDisconnect() {
  return fetchJson('/api/ble/disconnect', { method: 'POST' });
}

export async function modeSelect(mode) {
  return fetchJson('/api/mode/select', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode }),
  });
}

export async function modeStart(mode) {
  return fetchJson('/api/mode/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode }),
  });
}

export async function modeStop(mode) {
  return fetchJson('/api/mode/stop', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode }),
  });
}

export async function getDebugEvents(limit = 200) {
  const qs = new URLSearchParams({ limit: String(limit) });
  return fetchJson(`/api/debug/events?${qs.toString()}`);
}

export async function offlineExport(payload) {
  return fetchJson('/api/offline/export', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  });
}

export async function offlineSession(sessionId) {
  const sid = String(sessionId || '').trim();
  const qs = new URLSearchParams({ session_id: sid });
  return fetchJson(`/api/offline/session?${qs.toString()}`);
}

export async function eegChannelOptions() {
  return fetchJson('/api/eeg/channel/options');
}

export async function eegChannelGetSelection() {
  return fetchJson('/api/eeg/channel/selection');
}

export async function eegChannelSetSelection(payload) {
  return fetchJson('/api/eeg/channel/selection', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  });
}

export async function eegChannelApply() {
  return fetchJson('/api/eeg/channel/apply', { method: 'POST' });
}

export async function eegChannelPresetUpsertLocal(payload) {
  return fetchJson('/api/eeg/channel/presets/local', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  });
}

export async function eegChannelPresetDeleteLocal(name) {
  return fetchJson('/api/eeg/channel/presets/local/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: name || '' }),
  });
}
