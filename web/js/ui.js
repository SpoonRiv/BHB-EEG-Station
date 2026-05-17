/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 前端 UI 小组件（Toast、连接徽章、页面切换）

修改日志:
- 2026-05-02: 1.0.0 新增 UI 工具集
- 2026-05-03: 1.0.1 移除底部弹窗提示，统一改为按钮状态/输出窗口反馈
- 2026-05-17: 1.0.2 模式页激活时禁用 app-body 纵向滚动条，确保全屏无滑条

作者: Spoon
版本: 1.0.2
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
