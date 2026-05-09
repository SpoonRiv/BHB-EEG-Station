/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: SSVEP 实验页面模块
实现逻辑: 调用后端 /api/mode/start 和 stop，并监听调试事件以获取 FBCCA 识别结果

修改日志:
- 2026-05-09: 1.0.0 新增页面流路由

作者: Fengye
版本: 1.0.0
*/

import { postModeStart, postModeStop } from './api.js';
import { navigate } from './router.js';

let isRunning = false;

export function initSsvepPage() {
  const btnStart = document.getElementById('btn-ssvep-start');
  const btnStop = document.getElementById('btn-ssvep-stop');

  if (btnStart) {
    btnStart.onclick = async () => {
      try {
        btnStart.disabled = true;
        const res = await postModeStart('ssvep');
        if (res.status === 'success') {
          updateState(true, '刺激程序运行中...');
        } else {
          alert('启动失败: ' + res.message);
          btnStart.disabled = false;
        }
      } catch (e) {
        alert('接口异常');
        btnStart.disabled = false;
      }
    };
  }

  if (btnStop) {
    btnStop.onclick = async () => {
      try {
        const res = await postModeStop('ssvep');
        updateState(false, '程序已停止');
      } catch (e) {
        console.error(e);
      }
    };
  }
}

export function enterSsvepPage() {
  console.log('Entering SSVEP Page');
  // 这里可以初始化调试日志监听逻辑（参考 eeg.js 的实现）
  updateState(false, '准备就绪');
}

export function leaveSsvepPage() {
  console.log('Leaving SSVEP Page');
}

function updateState(running, text) {
  isRunning = running;
  const statusEl = document.getElementById('ssvep-status');
  const stateEl = document.getElementById('ssvep-run-state');
  const btnStart = document.getElementById('btn-ssvep-start');

  if (statusEl) statusEl.textContent = text;
  if (stateEl) stateEl.textContent = running ? '运行中' : '未运行';
  if (btnStart) btnStart.disabled = running;
}