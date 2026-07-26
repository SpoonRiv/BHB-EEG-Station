/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 模式选择页逻辑（进入 EEG/阻抗/tDCS 页面）
作者: Spoon
*/

import { getConfig, getStatus, modeSelect } from './api.js';
import { navigate } from './router.js';

function ensureDefaultDesc(btn) {
  if (!btn) return '';
  const desc = btn.querySelector('.mode-desc');
  if (!desc) return '';
  if (!btn.dataset.defaultDesc) btn.dataset.defaultDesc = desc.textContent || '';
  return btn.dataset.defaultDesc || '';
}

function setModeDisabled(btn, disabled, reason) {
  if (!btn) return;
  const defaultDesc = ensureDefaultDesc(btn);
  const state = btn.querySelector('.mode-card__state');
  const stateLabel = state ? state.querySelector('span') : null;
  if (stateLabel && !stateLabel.dataset.defaultLabel) {
    stateLabel.dataset.defaultLabel = stateLabel.textContent || 'READY';
  }
  btn.disabled = !!disabled;
  if (state) state.classList.toggle('mode-card__state--unavailable', !!disabled);
  if (stateLabel) {
    stateLabel.textContent = disabled
      ? 'UNAVAILABLE'
      : (stateLabel.dataset.defaultLabel || 'READY');
  }
  const desc = btn.querySelector('.mode-desc');
  if (!desc) return;
  if (disabled) {
    desc.textContent = reason || '当前功能已禁用';
    return;
  }
  desc.textContent = defaultDesc || desc.textContent;
}

function applyTdcsAvailability(btn, cfg, st) {
  if (!btn || !cfg) return;
  const nChannels = cfg && cfg.n_channels ? Number(cfg.n_channels) : 8;
  const configEnabled = !!(cfg && cfg.tdcs && cfg.tdcs.enabled);
  const effectiveEnabled = (cfg && cfg.tdcs && typeof cfg.tdcs.effective_enabled === 'boolean')
    ? !!cfg.tdcs.effective_enabled
    : configEnabled;

  const statusCapable = Boolean(st && st.device && st.device.capabilities && st.device.capabilities.tdcs);
  const statusKnown = Boolean(st && st.device && st.device.module && typeof st.device.module === 'object');

  if (!effectiveEnabled || (configEnabled && statusKnown && !statusCapable)) {
    let reason = '当前功能已禁用';
    if (!configEnabled) {
      reason = '电刺激模式已在配置中禁用（tdcs.enabled=false）';
    } else if (cfg && cfg.tdcs && cfg.tdcs.capable === false) {
      reason = '当前设备不带电刺激模块，电刺激模式已禁用';
    } else if (statusKnown && !statusCapable) {
      reason = '当前设备不带电刺激模块，电刺激模式已禁用';
    }
    setModeDisabled(btn, true, reason);
    return;
  }

  const supported = (cfg && cfg.tdcs && Array.isArray(cfg.tdcs.supported_channel_modes))
    ? cfg.tdcs.supported_channel_modes.map(Number).filter(Number.isFinite)
    : [];
  if (supported.length && !supported.includes(nChannels)) {
    setModeDisabled(btn, true, `当前 ${nChannels} 通道模式不支持电刺激（tdcs.supported_channel_modes=${supported.join(', ')}）`);
    return;
  }

  setModeDisabled(btn, false);
}

export function initModePage() {
  const eeg = document.getElementById('mode-eeg');
  const imp = document.getElementById('mode-impedance');
  const tdcs = document.getElementById('mode-tdcs');
  const ssvep = document.getElementById('mode-ssvep');
  const mi = document.getElementById('mode-mi');
  if (!eeg || !imp || !tdcs) return;

  ensureDefaultDesc(tdcs);
  let lastCfg = null;
  let lastStatus = null;

  const applyLatest = () => {
    if (!lastCfg) return;
    applyTdcsAvailability(tdcs, lastCfg, lastStatus);
  };

  void (async () => {
    try {
      const results = await Promise.allSettled([getConfig(), getStatus()]);
      if (results[0].status === 'fulfilled') lastCfg = results[0].value;
      if (results[1].status === 'fulfilled') lastStatus = results[1].value;
      applyLatest();
    } catch (_) {}
  })();

  window.addEventListener('app:config', (e) => {
    lastCfg = e && e.detail ? e.detail : null;
    applyLatest();
  });

  window.addEventListener('app:status', (e) => {
    lastStatus = e && e.detail ? e.detail : null;
    applyLatest();
  });

  eeg.addEventListener('click', async () => {
    try { await modeSelect('eeg'); } catch (_) {}
    await navigate('#eeg');
  });

  imp.addEventListener('click', async () => {
    try { await modeSelect('impedance'); } catch (_) {}
    await navigate('#impedance');
  });

  tdcs.addEventListener('click', async () => {
    if (tdcs.disabled) return;
    try { await modeSelect('tdcs'); } catch (_) {}
    await navigate('#tdcs');
  });

  const bindComingSoon = (btn, label) => {
    if (!btn) return;
    btn.addEventListener('click', () => {
      window.alert(`${label} 功能开发中，敬请期待`);
    });
  };

  bindComingSoon(ssvep, '稳态视觉诱发电位（SSVEP）');
  bindComingSoon(mi, '运动想象（MI）');
}
