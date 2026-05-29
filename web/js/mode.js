/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 模式选择页逻辑（进入 EEG/阻抗/tDCS 页面）

修改日志:
- 2026-05-02: 1.0.0 新增模式选择页
- 2026-05-03: 1.0.1 移除底部弹窗提示，统一改为按钮状态/页面导航反馈
- 2026-05-04: 1.0.2 按配置启用/禁用电刺激入口（tdcs.enabled）
- 2026-05-04: 1.0.3 按通道模式禁用电刺激入口（tdcs.supported_channel_modes + n_channels）
- 2026-05-09: 1.0.4 (Fengye) 增加刺激模式卡片及入口事件（已移除）
- 2026-05-17: 1.0.5 移除刺激模式入口逻辑
- 2026-05-17: 1.0.6 模式页新增 SSVEP/MI 占位入口点击提示
- 2026-05-17: 1.0.7 模式页新增 P300 占位入口点击提示
- 2026-05-24: 1.0.8 按设备能力禁用电刺激入口（无电刺激模块时置灰）
- 2026-05-29: 1.0.9 监听状态/配置变更，连接带刺激模块后自动更新电刺激入口可用性

作者: Spoon
版本: 1.0.9
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
  btn.disabled = !!disabled;
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
  const p300 = document.getElementById('mode-p300');
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

  bindComingSoon(ssvep, 'SSVEP');
  bindComingSoon(mi, 'MI');
  bindComingSoon(p300, 'P300');
}
