/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 模式选择页逻辑（进入 EEG/阻抗/tDCS 页面）

修改日志:
- 2026-05-02: 1.0.0 新增模式选择页
- 2026-05-03: 1.0.1 移除底部弹窗提示，统一改为按钮状态/页面导航反馈
- 2026-05-04: 1.0.2 按配置启用/禁用电刺激入口（tdcs.enabled）

作者: Spoon
版本: 1.0.2
*/

import { getConfig, modeSelect } from './api.js';
import { navigate } from './router.js';

function setModeDisabled(btn, disabled, reason) {
  if (!btn) return;
  btn.disabled = !!disabled;
  const desc = btn.querySelector('.mode-desc');
  if (desc && disabled) desc.textContent = reason || '当前功能已禁用';
}

export function initModePage() {
  const eeg = document.getElementById('mode-eeg');
  const imp = document.getElementById('mode-impedance');
  const tdcs = document.getElementById('mode-tdcs');
  if (!eeg || !imp || !tdcs) return;

  void (async () => {
    try {
      const cfg = await getConfig();
      const enabled = !!(cfg && cfg.tdcs && cfg.tdcs.enabled);
      if (!enabled) setModeDisabled(tdcs, true, '电刺激模式已在配置中禁用（tdcs.enabled=false）');
    } catch (_) {}
  })();

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
}
