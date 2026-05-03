/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 模式选择页逻辑（进入 EEG/阻抗/tDCS 页面）

修改日志:
- 2026-05-02: 1.0.0 新增模式选择页
- 2026-05-03: 1.0.1 移除底部弹窗提示，统一改为按钮状态/页面导航反馈

作者: Spoon
版本: 1.0.1
*/

import { modeSelect } from './api.js';
import { navigate } from './router.js';

export function initModePage() {
  const eeg = document.getElementById('mode-eeg');
  const imp = document.getElementById('mode-impedance');
  const tdcs = document.getElementById('mode-tdcs');
  if (!eeg || !imp || !tdcs) return;

  eeg.addEventListener('click', async () => {
    try { await modeSelect('eeg'); } catch (_) {}
    await navigate('#eeg');
  });

  imp.addEventListener('click', async () => {
    try { await modeSelect('impedance'); } catch (_) {}
    await navigate('#impedance');
  });

  tdcs.addEventListener('click', async () => {
    try { await modeSelect('tdcs'); } catch (_) {}
    await navigate('#tdcs');
  });
}
