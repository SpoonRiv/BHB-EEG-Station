/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 离线存储页面逻辑（停止采集后导出 CSV/EDF，可选带通滤波另存）

修改日志:
- 2026-05-03: 1.0.0 创建文件
- 2026-05-03: 1.0.1 页面提示补充 50Hz 工频陷波（不可关闭）

作者: Spoon
版本: 1.0.1
*/

import { getConfig, offlineExport } from './api.js';
import { navigate } from './router.js';

let pageActive = false;
let lastSessionId = '';

function getLastSessionId() {
  try { return sessionStorage.getItem('bhb_last_eeg_session') || ''; } catch (_) {}
  return '';
}

function getLastSessionDir() {
  try { return sessionStorage.getItem('bhb_last_eeg_session_dir') || ''; } catch (_) {}
  return '';
}

function setStatus(text, kind) {
  const box = document.getElementById('offline-status');
  if (!box) return;
  box.classList.remove('success', 'error');
  if (kind === 'success') box.classList.add('success');
  if (kind === 'error') box.classList.add('error');
  box.textContent = text || '';
}

function setSessionInfo(session) {
  const idEl = document.getElementById('offline-session-id');
  const dirEl = document.getElementById('offline-session-dir');
  if (idEl) idEl.textContent = session && session.session_id ? String(session.session_id) : '--';
  if (dirEl) dirEl.textContent = session && session.session_dir ? String(session.session_dir) : '--';
}

function setFilterVisible(enabled) {
  const block = document.getElementById('offline-filter-block');
  const filteredBlock = document.getElementById('offline-filtered-block');
  if (block) block.style.display = enabled ? '' : 'none';
  if (filteredBlock) filteredBlock.style.display = enabled ? '' : 'none';
}

function buildTargets() {
  const rawCsv = !!document.getElementById('offline-raw-csv')?.checked;
  const rawEdf = !!document.getElementById('offline-raw-edf')?.checked;
  const filCsv = !!document.getElementById('offline-fil-csv')?.checked;
  const filEdf = !!document.getElementById('offline-fil-edf')?.checked;
  const out = [];
  if (rawCsv) out.push({ kind: 'raw', fmt: 'csv' });
  if (rawEdf) out.push({ kind: 'raw', fmt: 'edf' });
  if (filCsv) out.push({ kind: 'filtered', fmt: 'csv' });
  if (filEdf) out.push({ kind: 'filtered', fmt: 'edf' });
  return out;
}

function readNumber(id, fallback) {
  const el = document.getElementById(id);
  if (!el) return fallback;
  const v = Number(el.value);
  if (!Number.isFinite(v)) return fallback;
  return v;
}

function setDefaultsFromConfig(cfg) {
  const offline = cfg && cfg.offline ? cfg.offline : null;
  const notchEl = document.getElementById('offline-notch-hint');
  if (notchEl) {
    const notch = offline && offline.notch ? offline.notch : (cfg && cfg.signal && cfg.signal.notch ? cfg.signal.notch : null);
    const hz = notch && typeof notch.freq_hz === 'number' ? notch.freq_hz : 50;
    notchEl.textContent = `系统默认对所有数据执行 ${hz}Hz 工频陷波（不可关闭），带通滤波在此页面可选。`;
  }
  const fd = offline && offline.filter_defaults ? offline.filter_defaults : null;
  const low = fd && typeof fd.lowcut_hz_default === 'number' ? fd.lowcut_hz_default : 3.0;
  const high = fd && typeof fd.highcut_hz_default === 'number' ? fd.highcut_hz_default : 50.0;

  const lowEl = document.getElementById('offline-lowcut');
  const highEl = document.getElementById('offline-highcut');
  if (lowEl) lowEl.value = String(low);
  if (highEl) highEl.value = String(high);
}

export async function enterOfflinePage() {
  pageActive = true;
  lastSessionId = getLastSessionId();
  const lastSessionDir = getLastSessionDir();
  setStatus(lastSessionId ? '请选择导出选项并点击“导出文件”。' : '未检测到最近会话，请先进入 EEG 页面开始/停止一次采集。', lastSessionId ? '' : 'error');
  setSessionInfo(null);

  const backBtn = document.getElementById('btn-offline-back');
  const exportBtn = document.getElementById('btn-offline-export');
  const filterToggle = document.getElementById('offline-filter-enable');
  const baseRaw = document.getElementById('offline-base-raw');
  const baseFil = document.getElementById('offline-base-filtered');

  if (baseRaw && !baseRaw.value) baseRaw.value = 'eeg';
  if (baseFil && !baseFil.value) baseFil.value = 'eeg_filtered';

  if (filterToggle) {
    filterToggle.onchange = () => {
      setFilterVisible(!!filterToggle.checked);
    };
    setFilterVisible(!!filterToggle.checked);
  }

  if (backBtn) backBtn.onclick = async () => { await navigate('#mode'); };

  if (exportBtn) {
    exportBtn.disabled = !lastSessionId;
    exportBtn.onclick = async () => {
      if (!lastSessionId) return;
      const targets = buildTargets();
      if (!targets.length) {
        setStatus('请至少选择一种导出文件（CSV/EDF 或滤波后文件）。', 'error');
        return;
      }

      const filterEnabled = !!document.getElementById('offline-filter-enable')?.checked;
      const wantFiltered = targets.some(t => t.kind === 'filtered');
      if (wantFiltered && !filterEnabled) {
        setStatus('已选择“滤波后文件”，请先勾选“启用带通滤波”。', 'error');
        return;
      }

      const baseNameRaw = String(document.getElementById('offline-base-raw')?.value || 'eeg').trim();
      const baseNameFiltered = String(document.getElementById('offline-base-filtered')?.value || 'eeg_filtered').trim();

      const lowcut = readNumber('offline-lowcut', 3.0);
      const highcut = readNumber('offline-highcut', 50.0);
      if (filterEnabled) {
        if (!(lowcut > 0) || !(highcut > 0) || !(highcut > lowcut)) {
          setStatus('滤波参数非法：需要满足 0 < 低频截止 < 高频截止。', 'error');
          return;
        }
      }

      exportBtn.disabled = true;
      setStatus('导出中，请稍候…', '');
      try {
        const payload = {
          session_id: lastSessionId,
          base_name_raw: baseNameRaw,
          base_name_filtered: baseNameFiltered,
          targets,
          bandpass: { enabled: filterEnabled, lowcut_hz: lowcut, highcut_hz: highcut },
        };
        const res = await offlineExport(payload);
        const outputs = res && res.result && Array.isArray(res.result.outputs) ? res.result.outputs : [];
        if (!outputs.length) {
          setStatus('未生成任何文件（请检查导出选项）。', 'error');
          return;
        }
        const lines = outputs.map(o => `- ${o.kind}/${o.fmt}: ${o.path}`).join('\n');
        setStatus(`导出完成：\n${lines}`, 'success');
      } catch (e) {
        setStatus(`导出失败：${e && e.message ? e.message : '未知错误'}`, 'error');
      } finally {
        exportBtn.disabled = false;
      }
    };
  }

  try {
    const cfg = await getConfig();
    setDefaultsFromConfig(cfg);
  } catch (_) {}

  if (!lastSessionId) return;
  try {
    setSessionInfo({ session_id: lastSessionId, session_dir: lastSessionDir });
  } catch (_) {}
}

export async function leaveOfflinePage() {
  pageActive = false;
}
