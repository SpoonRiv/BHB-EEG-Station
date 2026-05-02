/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 前端 UI 小组件（Toast、连接徽章、页面切换）

修改日志:
- 2026-05-02: 1.0.0 新增 UI 工具集

作者: Spoon
版本: 1.0.0
*/

let toastTimer = null;

export function toast(message) {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = String(message || '');
  el.classList.add('show');
  if (toastTimer) {
    clearTimeout(toastTimer);
    toastTimer = null;
  }
  toastTimer = setTimeout(() => {
    el.classList.remove('show');
  }, 2200);
}

export function setActivePage(pageId) {
  const pages = document.querySelectorAll('.page');
  pages.forEach(p => p.classList.remove('active'));
  const el = document.getElementById(pageId);
  if (el) el.classList.add('active');
}

export function setConnBadge(mode, text) {
  const badge = document.getElementById('conn-badge');
  const label = document.getElementById('conn-text');
  if (!badge || !label) return;
  badge.classList.remove('active');
  badge.classList.remove('error');
  if (mode === 'active') badge.classList.add('active');
  if (mode === 'error') badge.classList.add('error');
  label.textContent = String(text || '');
}
