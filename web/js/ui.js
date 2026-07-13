/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 前端 UI 小组件（Toast、连接徽章、页面切换）
作者: Spoon
*/

export function toast(message) {
  void message;
}

export function setActivePage(pageId) {
  const body = document.querySelector('.app-body');
  if (body) body.classList.toggle('no-scroll', pageId === 'page-mode');
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
