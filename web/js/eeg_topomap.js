/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 设备页 10-20 通道选择地形图交互（电极按钮、顺序编辑、常用组合与应用到系统）

修改日志:
- 2026-05-03: 1.0.0 创建文件
- 2026-05-03: 1.0.1 美化地形图 SVG（更柔和的头部底图与更现代的描边），电极交互改为无位移阴影，日间模式电极文字改为黑色
- 2026-05-03: 1.0.2 线条与字号更细；悬浮仅增强阴影与轻微浮动（选中态不位移）
- 2026-05-03: 1.0.3 已选通道改为网格并支持拖拽排序，地形图线条更细
- 2026-05-03: 1.0.4 常用组合下拉仅保留占位不出现在列表项，选项使用前置方括号标签
- 2026-05-03: 1.0.5 未选满通道时徽标浅红提示
- 2026-05-03: 1.0.6 缩小背景蓝色光晕，避免触及边缘形成直边
- 2026-05-03: 1.0.7 未选满时应用失败提示跟随“已选 x / n”，选满徽标转为绿色
- 2026-05-03: 1.0.8 移除底部“当前已应用”提示行，仅保留错误/成功状态提示
- 2026-05-03: 1.0.9 应用成功后将“实际应用通道+参考”写入绿色徽标消息
- 2026-05-03: 1.0.10 徽标改为“计数+消息”两列布局，消息自动换行且不顶格
- 2026-05-03: 1.0.11 增加参考电极下拉选择（与通道选择分离并随待应用一起保存）
- 2026-05-03: 1.0.12 参考电极改为三按钮互斥选择，并与预设套用/保存联动
- 2026-05-04: 1.0.13 已选通道拖拽排序体验优化：拖拽预览跟随、插入占位提示与更平滑的位移动画
- 2026-05-04: 1.0.14 通道选择变更/应用成功向外派发事件，用于设备页自动跳转门禁
- 2026-05-04: 1.0.15 配置字段更名：mode_channels -> n_channels（与三模式命名一致）
- 2026-05-04: 1.0.16 文件更名为 eeg_topomap.js，命名与 impedance_topomap.js 保持一致
- 2026-05-17: 1.0.17 电极位置由后端配置下发，前端仅做渲染与兼容回退
- 2026-05-17: 1.0.18 电极默认回退与按钮命名切换为标准 10-20（T7/T8），移除扩展电极
- 2026-05-17: 1.0.19 电极默认回退扩展为 64 通道帽布局（10-10），支持完整电极分布绘制
- 2026-05-17: 1.0.20 参考电极选择改为可取消，并在地形图用绿色标识；支持右键电极快速切换参考电极
- 2026-05-17: 1.0.21 参考电极支持从地形图点选（Shift+点击/右键），不再限制为三选一
- 2026-05-17: 1.0.22 移除参考电极三按钮快捷选择，改为同款卡片展示当前参考电极（无编号），参考电极从地形图点选
- 2026-05-17: 1.0.23 参考电极卡片支持“点按进入选取模式”，下一次左键点击地形图电极将其设为参考
- 2026-05-17: 1.0.24 更新地形图提示文案，突出“参考电极卡片 -> 地形图点选”流程
- 2026-05-17: 1.0.25 参考电极卡片对齐已选通道样式：编号改为 REF；UI 不使用绿色；移除底部状态提示元素
- 2026-05-17: 1.0.26 参考电极卡片宽度对齐单个已选通道卡片；编号由 REF 改为 R
- 2026-05-17: 1.0.27 未选择参考电极时显示空虚线框（无文字提示），点击进入/退出参考电极选取模式
- 2026-05-17: 1.0.28 参考电极仅支持在地形图右键点选，移除 Shift+左键点选
- 2026-05-17: 1.0.29 阻抗通道常用组合展示包含参考电极（8+1），并将参考电极纳入“就绪”判断
- 2026-05-17: 1.0.30 常用组合保存校验失败时使用徽标提示（名称/通道数/参考电极）
- 2026-05-17: 1.0.31 已选通道区域高度锁定（清空不影响下方布局）；常用组合下拉去掉括号详情
- 2026-05-17: 1.0.32 参考通道卡片移除不可拖拽的“六点”图标
- 2026-05-17: 1.0.32 参考电极右键选择不直接覆盖：已有参考时需先右键同一电极取消，再右键新电极设置
- 2026-05-17: 1.0.33 参考电极与工作通道互斥：右键不能设为已选工作通道，左键不能选择当前参考电极
- 2026-05-29: 1.0.34 清空按钮同步清空参考电极选择状态
- 2026-05-29: 1.0.35 工作通道为空时展示占位虚线框
- 2026-05-29: 1.0.36 工作通道占位虚线框数量与通道数一致（不足部分补齐）

作者: Spoon
版本: 1.0.36
*/

import {
  eegChannelApply,
  eegChannelOptions,
  eegChannelPresetDeleteLocal,
  eegChannelPresetUpsertLocal,
  eegChannelSetSelection,
} from './api.js';

const DEFAULT_ELECTRODE_POS = {
  Fpz: { x: 50, y: 6 },
  Fp1: { x: 38, y: 10 },
  Fp2: { x: 62, y: 10 },
  AF3: { x: 42, y: 16 },
  AF4: { x: 58, y: 16 },
  F7: { x: 18, y: 22 },
  F5: { x: 26, y: 24 },
  F3: { x: 34, y: 26 },
  F1: { x: 42, y: 24 },
  Fz: { x: 50, y: 26 },
  F2: { x: 58, y: 24 },
  F4: { x: 66, y: 26 },
  F6: { x: 74, y: 24 },
  F8: { x: 82, y: 22 },
  FT7: { x: 12, y: 34 },
  FC5: { x: 26, y: 36 },
  FC3: { x: 34, y: 36 },
  FC1: { x: 42, y: 36 },
  FCz: { x: 50, y: 36 },
  FC2: { x: 58, y: 36 },
  FC4: { x: 66, y: 36 },
  FC6: { x: 74, y: 36 },
  FT8: { x: 88, y: 34 },
  T7: { x: 12, y: 44 },
  C5: { x: 26, y: 44 },
  C3: { x: 32, y: 44 },
  C1: { x: 42, y: 44 },
  Cz: { x: 50, y: 44 },
  C2: { x: 58, y: 44 },
  C4: { x: 68, y: 44 },
  C6: { x: 74, y: 44 },
  T8: { x: 88, y: 44 },
  TP7: { x: 12, y: 56 },
  CP5: { x: 26, y: 56 },
  CP3: { x: 34, y: 56 },
  CP1: { x: 42, y: 56 },
  CPz: { x: 50, y: 56 },
  CP2: { x: 58, y: 56 },
  CP4: { x: 66, y: 56 },
  CP6: { x: 74, y: 56 },
  TP8: { x: 88, y: 56 },
  P7: { x: 22, y: 64 },
  P5: { x: 26, y: 64 },
  P3: { x: 34, y: 62 },
  P1: { x: 42, y: 64 },
  Pz: { x: 50, y: 66 },
  P2: { x: 58, y: 64 },
  P4: { x: 66, y: 62 },
  P6: { x: 74, y: 64 },
  P8: { x: 78, y: 64 },
  PO7: { x: 18, y: 74 },
  PO5: { x: 30, y: 74 },
  PO3: { x: 40, y: 74 },
  POz: { x: 50, y: 74 },
  PO4: { x: 60, y: 74 },
  PO6: { x: 70, y: 74 },
  PO8: { x: 82, y: 74 },
  O1: { x: 42, y: 84 },
  Oz: { x: 50, y: 86 },
  O2: { x: 58, y: 84 },
  CB1: { x: 46, y: 92 },
  CB2: { x: 54, y: 92 },
  A1: { x: 4, y: 50 },
  A2: { x: 96, y: 50 },
};

function getElectrodePos(name, positions, aliases) {
  const n = String(name || '').trim();
  if (!n) return null;
  if (positions && positions[n]) return positions[n];
  const a = aliases && aliases[n];
  if (a && positions && positions[a]) return positions[a];
  return DEFAULT_ELECTRODE_POS[n] || null;
}

function normalizeUnique(items) {
  const out = [];
  for (const x of (items || [])) {
    const s = String(x || '').trim();
    if (!s) continue;
    if (!out.includes(s)) out.push(s);
  }
  return out;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (typeof text !== 'undefined') node.textContent = String(text);
  return node;
}

function createSvgRoot() {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 100 100');
  svg.setAttribute('width', '100%');
  svg.setAttribute('height', '100%');
  svg.style.maxHeight = '100%';
  svg.style.display = 'block';
  return svg;
}

function drawHead(svg) {
  const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
  const grad = document.createElementNS('http://www.w3.org/2000/svg', 'radialGradient');
  grad.setAttribute('id', 'bhb_head_bg');
  grad.setAttribute('cx', '50%');
  grad.setAttribute('cy', '45%');
  grad.setAttribute('r', '54%');
  const s0 = document.createElementNS('http://www.w3.org/2000/svg', 'stop');
  s0.setAttribute('offset', '0%');
  s0.setAttribute('stop-color', 'rgb(49, 215, 255)');
  s0.setAttribute('stop-opacity', '0.075');
  const s1 = document.createElementNS('http://www.w3.org/2000/svg', 'stop');
  s1.setAttribute('offset', '72%');
  s1.setAttribute('stop-color', 'rgb(49, 215, 255)');
  s1.setAttribute('stop-opacity', '0.028');
  const s2 = document.createElementNS('http://www.w3.org/2000/svg', 'stop');
  s2.setAttribute('offset', '100%');
  s2.setAttribute('stop-color', 'rgb(49, 215, 255)');
  s2.setAttribute('stop-opacity', '0');
  grad.appendChild(s0);
  grad.appendChild(s1);
  grad.appendChild(s2);
  defs.appendChild(grad);
  svg.appendChild(defs);

  const bg = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
  bg.setAttribute('x', '0');
  bg.setAttribute('y', '0');
  bg.setAttribute('width', '100');
  bg.setAttribute('height', '100');
  bg.setAttribute('fill', 'url(#bhb_head_bg)');
  svg.appendChild(bg);

  const outline = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  outline.setAttribute('d', 'M50 6 C22 6 8 26 8 55 C8 80 25 94 50 94 C75 94 92 80 92 55 C92 26 78 6 50 6 Z');
  outline.setAttribute('fill', 'rgba(0,0,0,0)');
  outline.setAttribute('stroke', 'rgba(120,170,210,0.42)');
  outline.setAttribute('stroke-width', '0.86');
  svg.appendChild(outline);

  const nose = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  nose.setAttribute('d', 'M50 6 L45 14 L55 14 Z');
  nose.setAttribute('fill', 'rgba(120,170,210,0.14)');
  nose.setAttribute('stroke', 'rgba(120,170,210,0.42)');
  nose.setAttribute('stroke-width', '0.64');
  svg.appendChild(nose);

  const earL = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  earL.setAttribute('d', 'M7 50 C3 48 3 42 7 40 C9 39 10 41 10 45 C10 49 9 51 7 50 Z');
  earL.setAttribute('fill', 'rgba(120,170,210,0.08)');
  earL.setAttribute('stroke', 'rgba(120,170,210,0.38)');
  earL.setAttribute('stroke-width', '0.64');
  svg.appendChild(earL);

  const earR = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  earR.setAttribute('d', 'M93 50 C97 48 97 42 93 40 C91 39 90 41 90 45 C90 49 91 51 93 50 Z');
  earR.setAttribute('fill', 'rgba(120,170,210,0.08)');
  earR.setAttribute('stroke', 'rgba(120,170,210,0.38)');
  earR.setAttribute('stroke-width', '0.64');
  svg.appendChild(earR);

  const guide = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  guide.setAttribute('d', 'M50 18 L50 86 M18 55 L82 55');
  guide.setAttribute('fill', 'none');
  guide.setAttribute('stroke', 'rgba(120,170,210,0.10)');
  guide.setAttribute('stroke-width', '0.42');
  svg.appendChild(guide);
}

function renderElectrodes(svg, channels, selected, maxCount, onToggle, positions, aliases, refName, onRefToggle, refCandidates) {
  const selectedSet = new Set(selected || []);
  const ref = String(refName || '').trim();
  const total = Array.isArray(channels) ? channels.length : 0;
  const r = total >= 60 ? 2.7 : (total >= 40 ? 3.2 : 4.4);
  const fontSize = total >= 60 ? 2.1 : (total >= 40 ? 2.6 : 3.55);
  const dy = total >= 60 ? 0.7 : 0.9;
  for (const name of channels) {
    const pos = getElectrodePos(name, positions, aliases);
    if (!pos) continue;
    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.classList.add('electrode');
    if (selectedSet.has(name)) g.classList.add('selected');
    if (ref && name === ref) g.classList.add('ref-selected');

    const canAdd = selectedSet.has(name) || selectedSet.size < maxCount;
    if (!canAdd) g.classList.add('disabled');
    g.dataset.name = name;

    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.classList.add('electrode-circle');
    circle.setAttribute('cx', String(pos.x));
    circle.setAttribute('cy', String(pos.y));
    circle.setAttribute('r', String(r));
    g.appendChild(circle);

    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.classList.add('electrode-text');
    text.setAttribute('x', String(pos.x));
    text.setAttribute('y', String(pos.y + dy));
    text.setAttribute('text-anchor', 'middle');
    text.setAttribute('dominant-baseline', 'middle');
    text.setAttribute('font-size', String(fontSize));
    text.setAttribute('font-weight', '650');
    text.textContent = name;
    g.appendChild(text);

    if (canAdd) g.addEventListener('click', () => onToggle(name));
    if (typeof onRefToggle === 'function') {
      g.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        onRefToggle(name);
      });
    }
    svg.appendChild(g);
  }
}

function isLocalPreset(p) {
  return p && String(p.scope || '') === 'local';
}

export function initTopomapPanel() {
  const modeSel = document.getElementById('ch-mode-select');
  const btnApply = document.getElementById('ch-apply');
  const svgHost = document.getElementById('topomap-svg');
  const listHost = document.getElementById('ch-selected-list');
  const btnClear = document.getElementById('ch-clear');
  const badge = document.getElementById('ch-count-badge');
  const refPills = document.getElementById('ch-ref-pills');
  const presetSel = document.getElementById('ch-preset-select');
  const btnPresetApply = document.getElementById('ch-preset-apply');
  const btnPresetSave = document.getElementById('ch-preset-save');
  const btnPresetDelete = document.getElementById('ch-preset-delete');
  const presetNameInput = document.getElementById('ch-preset-name');
  const sub = document.getElementById('topomap-sub');

  if (!modeSel || !btnApply || !svgHost || !listHost || !btnClear || !badge || !refPills || !presetSel || !btnPresetApply || !btnPresetSave || !btnPresetDelete || !presetNameInput) {
    return;
  }
  if (sub) {
    sub.textContent = '左键点击选择工作通道与顺序 | 右键点击选择参考通道';
  }

  let supportedModes = [];
  let availableChannels = [];
  let refCandidates = [];
  let presets = [];
  let pendingMode = 8;
  let selected = [];
  let pendingRef = '';
  let effective = { n_channels: 8, channel_names: [], ref_channel_name: '' };
  let lastError = '';
  let dragName = '';
  let dndBound = false;
  let dragInsertIndex = -1;
  let dragPlaceholderEl = null;
  let dragPreviewEl = null;
  let badgeMsg = '';
  let badgeMsgEl = null;
  let badgeMsgKind = '';
  let badgeCountEl = null;
  let badgeStrongCur = null;
  let badgeStrongTotal = null;
  let badgeStrongRef = null;
  let electrodePositions = DEFAULT_ELECTRODE_POS;
  let electrodeAliases = {};
  let refPickArmed = false;

  function setStatus() {}

  function ensureBadgeMsgEl() {
    if (badgeMsgEl) return badgeMsgEl;
    const span = el('span', 'topomap-badge-msg', '');
    badge.appendChild(span);
    badgeMsgEl = span;
    return span;
  }

  function ensureBadgeCountEls() {
    if (badgeCountEl && badgeStrongCur && badgeStrongTotal && badgeStrongRef) return;
    badge.innerHTML = '';
    badgeMsgEl = null;

    const count = el('span', 'topomap-badge-count', '');
    count.appendChild(document.createTextNode('已选 '));
    const cur = document.createElement('strong');
    cur.textContent = String(selected.length);
    count.appendChild(cur);
    count.appendChild(document.createTextNode(' / '));
    const total = document.createElement('strong');
    total.textContent = String(pendingMode);
    count.appendChild(total);
    count.appendChild(document.createTextNode(' + 参考 '));
    const ref = document.createElement('strong');
    ref.textContent = String(String(pendingRef || '').trim() ? 1 : 0);
    count.appendChild(ref);
    badge.appendChild(count);

    badgeCountEl = count;
    badgeStrongCur = cur;
    badgeStrongTotal = total;
    badgeStrongRef = ref;

    ensureBadgeMsgEl();
  }

  function setBadgeMsg(text, kind) {
    badgeMsg = String(text || '');
    badgeMsgKind = String(kind || '');
    ensureBadgeCountEls();
    const span = ensureBadgeMsgEl();
    span.classList.toggle('ok', badgeMsgKind === 'success');
    if (!badgeMsg) {
      span.textContent = '';
      span.hidden = true;
      return;
    }
    span.hidden = false;
    span.textContent = ` ${badgeMsg}`;
  }

  function updateBadge() {
    ensureBadgeCountEls();
    const a = (badge.querySelectorAll('strong') || []);
    if (a.length >= 3) {
      a[0].textContent = String(selected.length);
      a[1].textContent = String(pendingMode);
      a[2].textContent = String(String(pendingRef || '').trim() ? 1 : 0);
    }
    const hasRef = Boolean(String(pendingRef || '').trim());
    const isFull = selected.length === pendingMode && hasRef;
    const isWarn = selected.length < pendingMode || selected.length > pendingMode || !hasRef;
    badge.classList.toggle('warn', isWarn);
    badge.classList.toggle('ok', isFull);
    if (isFull && badgeMsgKind === 'error') setBadgeMsg('', '');
  }

  function updateSelectedGridCols() {
    const cols = pendingMode >= 16 ? 4 : 2;
    const rows = Math.ceil(Math.max(pendingMode, 1) / Math.max(cols, 1));
    listHost.style.setProperty('--ch-selected-cols', String(cols));
    listHost.style.setProperty('--ch-selected-rows', String(rows));
    refPills.style.setProperty('--ch-selected-cols', String(cols));
  }

  function renderModeSelect() {
    modeSel.innerHTML = '';
    const opt8 = el('option', '', '8通道');
    opt8.value = '8';
    if (supportedModes.length && !supportedModes.includes(8)) opt8.disabled = true;
    const opt16 = el('option', '', '16通道（预留）');
    opt16.value = '16';
    if (supportedModes.length && !supportedModes.includes(16)) opt16.disabled = true;
    modeSel.appendChild(opt8);
    modeSel.appendChild(opt16);
    modeSel.value = String(pendingMode);
  }

  function renderRefCard() {
    const cur = String(pendingRef || '').trim();
    refPills.innerHTML = '';
    refPills.classList.toggle('has-active', Boolean(cur));
    if (!cur) {
      const box = el('div', 'chip chip-ref chip-ref-empty');
      box.classList.toggle('armed', Boolean(refPickArmed));
      box.addEventListener('click', () => {
        refPickArmed = !refPickArmed;
        render();
      });
      refPills.appendChild(box);
      return;
    }

    const row = el('div', 'chip chip-ref');
    row.classList.toggle('armed', Boolean(refPickArmed));
    row.addEventListener('click', () => {
      refPickArmed = !refPickArmed;
      render();
    });
    const left = el('div', 'chip-left');
    const handle = el('div', 'chip-handle chip-handle-spacer', '');
    left.appendChild(handle);
    const idx = el('div', 'chip-index', 'R');
    left.appendChild(idx);
    left.appendChild(el('div', 'chip-name', cur));
    row.appendChild(left);

    const actions = el('div', 'chip-actions');
    const btnDel = el('button', 'mini-btn danger', '×');
    btnDel.onclick = (e) => {
      try { e.stopPropagation(); } catch (_) {}
      pendingRef = '';
      refPickArmed = false;
      persistPending();
    };
    actions.appendChild(btnDel);
    row.appendChild(actions);
    refPills.appendChild(row);
  }

  function renderPresetSelect() {
    const current = String(presetSel.value || '');
    presetSel.innerHTML = '';
    const opt = el('option', '', '请选择常用组合');
    opt.value = '';
    opt.disabled = true;
    opt.hidden = true;
    opt.setAttribute('disabled', '');
    opt.setAttribute('hidden', '');
    presetSel.appendChild(opt);
    let localIdx = 0;
    for (const p of (presets || [])) {
      const o = document.createElement('option');
      const scope = String(p.scope || '');
      o.value = `${scope}:${p.name}`;
      if (scope === 'local') {
        localIdx += 1;
        o.textContent = `【自定义${localIdx}】${p.name}`;
      } else {
        o.textContent = `【内置预设】${p.name}`;
      }
      presetSel.appendChild(o);
    }
    let found = false;
    for (const o of presetSel.options) {
      if (String(o.value) === current) {
        found = true;
        break;
      }
    }
    presetSel.value = found ? current : '';
  }

  function renderSelectedList() {
    listHost.innerHTML = '';
    updateSelectedGridCols();
    if (!dndBound) {
      listHost.addEventListener('dragover', (e) => {
        if (!dragName) return;
        e.preventDefault();
        try {
          e.dataTransfer.dropEffect = 'move';
        } catch (err) {
        }
        const hostRect = listHost.getBoundingClientRect();
        const scrollMargin = 32;
        if (e.clientY < hostRect.top + scrollMargin) {
          listHost.scrollTop -= 12;
        } else if (e.clientY > hostRect.bottom - scrollMargin) {
          listHost.scrollTop += 12;
        }

        const insertIdx = calcDragInsertIndex(e);
        placeDragPlaceholder(insertIdx);
      });
      listHost.addEventListener('dragleave', (e) => {
        if (!dragName) return;
        const rt = e.relatedTarget;
        if (rt && listHost.contains(rt)) return;
        clearDragPlaceholder();
      });
      listHost.addEventListener('drop', (e) => {
        if (!dragName) return;
        e.preventDefault();
        const from = selected.indexOf(dragName);
        if (from < 0) return;
        const item = selected[from];
        selected.splice(from, 1);
        const to = Number.isFinite(dragInsertIndex) && dragInsertIndex >= 0 ? Math.min(Math.max(dragInsertIndex, 0), selected.length) : selected.length;
        selected.splice(to, 0, item);
        dragName = '';
        dragInsertIndex = -1;
        clearDragPlaceholder();
        clearDragPreview();
        persistPending();
      });
      dndBound = true;
    }
    for (let i = 0; i < selected.length; i++) {
      const name = selected[i];
      const row = el('div', 'chip');
      row.dataset.name = name;
      const left = el('div', 'chip-left');
      const handle = el('div', 'chip-handle', '⋮⋮');
      handle.draggable = true;
      handle.addEventListener('dragstart', (e) => {
        dragName = name;
        row.classList.add('dragging');
        dragInsertIndex = -1;
        try {
          e.dataTransfer.setData('text/plain', name);
          e.dataTransfer.effectAllowed = 'move';
        } catch (err) {
        }
        setDragPreview(e, row);
        requestAnimationFrame(() => {
          row.classList.add('drag-hidden');
          const from = selected.indexOf(name);
          if (from >= 0) placeDragPlaceholder(from);
        });
      });
      handle.addEventListener('dragend', () => {
        dragName = '';
        row.classList.remove('dragging');
        row.classList.remove('drag-hidden');
        dragInsertIndex = -1;
        clearDragPlaceholder();
        clearDragPreview();
      });
      left.appendChild(handle);
      left.appendChild(el('div', 'chip-index', String(i + 1)));
      left.appendChild(el('div', 'chip-name', name));
      row.appendChild(left);

      const actions = el('div', 'chip-actions');
      const btnDel = el('button', 'mini-btn danger', '×');
      btnDel.onclick = () => toggle(name);
      actions.appendChild(btnDel);
      row.appendChild(actions);
      listHost.appendChild(row);
    }
    const remaining = Math.max(pendingMode - selected.length, 0);
    for (let i = 0; i < remaining; i++) {
      const empty = el('div', 'chip chip-work-empty');
      empty.setAttribute('aria-hidden', 'true');
      listHost.appendChild(empty);
    }
  }

  function getDraggableChips() {
    return Array.from(listHost.querySelectorAll('.chip[data-name]')).filter((n) => !n.classList.contains('chip-placeholder') && !n.classList.contains('drag-hidden'));
  }

  function calcDragInsertIndex(e) {
    const chips = getDraggableChips();
    if (!chips.length) return 0;

    const elAt = document.elementFromPoint(e.clientX, e.clientY);
    const chip = elAt ? elAt.closest('.chip') : null;
    if (!chip) {
      return chips.length;
    }
    if (chip.classList.contains('chip-placeholder')) {
      return Number.isFinite(dragInsertIndex) && dragInsertIndex >= 0 ? dragInsertIndex : chips.length;
    }
    if (chip.classList.contains('drag-hidden')) {
      return chips.length;
    }
    const idx = chips.indexOf(chip);
    if (idx < 0) return chips.length;
    const r = chip.getBoundingClientRect();
    const sameRow = Math.abs(e.clientY - (r.top + r.height / 2)) < r.height * 0.35;
    const after = sameRow ? (e.clientX > r.left + r.width / 2) : (e.clientY > r.top + r.height / 2);
    return after ? (idx + 1) : idx;
  }

  function ensureDragPlaceholder() {
    if (dragPlaceholderEl) return dragPlaceholderEl;
    const p = el('div', 'chip chip-placeholder');
    p.setAttribute('aria-hidden', 'true');
    dragPlaceholderEl = p;
    return dragPlaceholderEl;
  }

  function snapshotChipRects() {
    const m = new Map();
    const nodes = Array.from(listHost.querySelectorAll('.chip[data-name]')).filter((n) => !n.classList.contains('chip-placeholder') && !n.classList.contains('drag-hidden'));
    for (const n of nodes) {
      const key = n.dataset.name || '';
      if (!key) continue;
      m.set(key, n.getBoundingClientRect());
    }
    return m;
  }

  function animateFlip(before) {
    const nodes = Array.from(listHost.querySelectorAll('.chip[data-name]')).filter((n) => !n.classList.contains('chip-placeholder') && !n.classList.contains('drag-hidden'));
    for (const n of nodes) {
      const key = n.dataset.name || '';
      if (!key) continue;
      const b = before.get(key);
      if (!b) continue;
      const a = n.getBoundingClientRect();
      const dx = b.left - a.left;
      const dy = b.top - a.top;
      if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) continue;
      n.style.transform = `translate(${dx}px, ${dy}px)`;
      n.style.transition = 'transform 0s';
      requestAnimationFrame(() => {
        n.style.transition = '';
        n.style.transform = '';
      });
    }
  }

  function placeDragPlaceholder(insertIndex) {
    const p = ensureDragPlaceholder();
    const chips = getDraggableChips();
    const idx = Math.min(Math.max(Number(insertIndex) || 0, 0), chips.length);
    if (dragInsertIndex === idx && p.parentElement === listHost) return;

    const before = snapshotChipRects();
    if (idx >= chips.length) {
      listHost.appendChild(p);
    } else {
      listHost.insertBefore(p, chips[idx]);
    }
    dragInsertIndex = idx;
    animateFlip(before);
  }

  function clearDragPlaceholder() {
    if (!dragPlaceholderEl) return;
    if (dragPlaceholderEl.parentElement) dragPlaceholderEl.parentElement.removeChild(dragPlaceholderEl);
    dragPlaceholderEl = null;
  }

  function setDragPreview(e, row) {
    clearDragPreview();
    try {
      const r = row.getBoundingClientRect();
      const px = Math.max(0, Math.min(r.width, e.clientX - r.left));
      const py = Math.max(0, Math.min(r.height, e.clientY - r.top));
      const p = row.cloneNode(true);
      p.classList.add('chip-drag-preview');
      p.style.position = 'fixed';
      p.style.left = '-1000px';
      p.style.top = '-1000px';
      p.style.pointerEvents = 'none';
      document.body.appendChild(p);
      dragPreviewEl = p;
      e.dataTransfer.setDragImage(p, px, py);
    } catch (err) {
    }
  }

  function clearDragPreview() {
    if (!dragPreviewEl) return;
    if (dragPreviewEl.parentElement) dragPreviewEl.parentElement.removeChild(dragPreviewEl);
    dragPreviewEl = null;
  }

  function renderSvg() {
    svgHost.innerHTML = '';
    const svg = createSvgRoot();
    drawHead(svg);
    renderElectrodes(svg, availableChannels, selected, pendingMode, (name) => {
      if (refPickArmed) {
        refPickArmed = false;
        toggleRef(name);
        return;
      }
      toggle(name);
    }, electrodePositions, electrodeAliases, pendingRef, (name) => {
      if (refPickArmed) refPickArmed = false;
      toggleRef(name);
    });
    svgHost.appendChild(svg);
  }

  function render() {
    updateBadge();
    renderModeSelect();
    renderRefCard();
    renderPresetSelect();
    renderSelectedList();
    renderSvg();
    setStatus();
  }

  function intOr(v, fallback) {
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  }

  async function persistPending() {
    try { window.dispatchEvent(new CustomEvent('bhb-channel-selection-dirty')); } catch (_) {}
    if (badgeMsg) setBadgeMsg('', '');
    try {
      await eegChannelSetSelection({ n_channels: pendingMode, channel_names: selected, ref_channel_name: pendingRef });
      lastError = '';
    } catch (e) {
      lastError = `保存选择失败：${e && e.message ? e.message : e}`;
    }
    render();
  }

  function toggle(name) {
    const n = String(name || '').trim();
    if (!n) return;
    if (String(pendingRef || '').trim() === n) return;
    const idx = selected.indexOf(n);
    if (idx >= 0) {
      selected.splice(idx, 1);
      persistPending();
      return;
    }
    if (selected.length >= pendingMode) return;
    selected.push(n);
    persistPending();
  }

  function toggleRef(name) {
    const n = String(name || '').trim();
    if (!n) return;
    if (availableChannels.length && !availableChannels.includes(n)) return;
    if (selected.includes(n)) return;
    const cur = String(pendingRef || '').trim();
    if (cur && cur !== n) return;
    pendingRef = cur === n ? '' : n;
    persistPending();
  }

  function move(from, to) {
    if (from < 0 || to < 0 || from >= selected.length || to >= selected.length) return;
    const item = selected[from];
    selected.splice(from, 1);
    selected.splice(to, 0, item);
    persistPending();
  }

  async function loadAll() {
    try {
      const data = await eegChannelOptions();
      supportedModes = normalizeUnique((data && data.supported_channel_modes) || []).map((x) => Number(x)).filter((x) => Number.isFinite(x));
      availableChannels = normalizeUnique((data && data.available_channels) || []);
      const layout = data && data.electrode_layout_1020 ? data.electrode_layout_1020 : null;
      if (layout && layout.positions && typeof layout.positions === 'object') {
        electrodePositions = layout.positions;
        electrodeAliases = (layout.aliases && typeof layout.aliases === 'object') ? layout.aliases : {};
      } else {
        electrodePositions = DEFAULT_ELECTRODE_POS;
        electrodeAliases = {};
      }
      refCandidates = normalizeUnique((data && data.ref_candidates) || []);
      presets = (data && Array.isArray(data.presets)) ? data.presets : [];
      const p = data && data.pending ? data.pending : null;
      pendingMode = intOr(p && p.n_channels, 8);
      selected = normalizeUnique((p && p.channel_names) || []);
      pendingRef = String((p && p.ref_channel_name) || '').trim();
      effective = data && data.effective ? data.effective : effective;
      if (!pendingRef) pendingRef = String(effective.ref_channel_name || '').trim();
      lastError = '';
      if (badgeMsg) setBadgeMsg('', '');
    } catch (e) {
      lastError = `加载通道配置失败：${e && e.message ? e.message : e}`;
    }
    if (selected.length > pendingMode) selected = selected.slice(0, pendingMode);
    render();
  }

  modeSel.addEventListener('change', async () => {
    const v = Number(modeSel.value);
    if (!Number.isFinite(v) || v <= 0) return;
    pendingMode = v;
    if (selected.length > pendingMode) selected = selected.slice(0, pendingMode);
    await persistPending();
  });

  btnClear.onclick = async () => {
    selected = [];
    pendingRef = '';
    refPickArmed = false;
    await persistPending();
  };

  btnPresetApply.onclick = async () => {
    const v = String(presetSel.value || '');
    if (!v) return;
    const idx = presets.findIndex((p) => `${p.scope}:${p.name}` === v);
    if (idx < 0) return;
    const p = presets[idx];
    pendingMode = intOr(p.n_channels, pendingMode);
    selected = normalizeUnique(p.channel_names || []).slice(0, pendingMode);
    const ref = String(p.ref_channel_name || '').trim();
    if (ref) pendingRef = ref;
    await persistPending();
  };

  btnPresetSave.onclick = async () => {
    const name = String(presetNameInput.value || '').trim();
    if (!name) {
      lastError = '';
      setBadgeMsg('保存失败：请输入常用组合名称', 'error');
      render();
      return;
    }
    if (selected.length !== pendingMode) {
      lastError = '';
      setBadgeMsg(`保存失败：请先选择满 ${pendingMode} 个通道再保存`, 'error');
      render();
      return;
    }
    if (!String(pendingRef || '').trim()) {
      lastError = '';
      setBadgeMsg('保存失败：请先选择参考电极再保存', 'error');
      render();
      return;
    }
    try {
      await eegChannelPresetUpsertLocal({ name, n_channels: pendingMode, channel_names: selected, ref_channel_name: pendingRef });
      presetNameInput.value = '';
      lastError = '';
      await loadAll();
    } catch (e) {
      lastError = `保存常用组合失败：${e && e.message ? e.message : e}`;
      render();
    }
  };

  btnPresetDelete.onclick = async () => {
    const v = String(presetSel.value || '');
    if (!v) return;
    const idx = presets.findIndex((p) => `${p.scope}:${p.name}` === v);
    if (idx < 0) return;
    const p = presets[idx];
    if (!isLocalPreset(p)) {
      lastError = '只能删除“本机”常用组合';
      render();
      return;
    }
    try {
      await eegChannelPresetDeleteLocal(p.name);
      lastError = '';
      await loadAll();
    } catch (e) {
      lastError = `删除常用组合失败：${e && e.message ? e.message : e}`;
      render();
    }
  };

  btnApply.onclick = async () => {
    if (selected.length !== pendingMode) {
      setBadgeMsg(`应用失败：请先选择满 ${pendingMode} 个通道，再点击应用`, 'error');
      return;
    }
    if (!String(pendingRef || '').trim()) {
      setBadgeMsg('应用失败：请先选择参考电极，再点击应用', 'error');
      return;
    }
    btnApply.disabled = true;
    try {
      const res = await eegChannelApply();
      if (res && res.status === 'success') {
        lastError = '';
        await loadAll();
        const effMode = intOr(effective.n_channels, pendingMode);
        const effNames = normalizeUnique(effective.channel_names || []);
        const ref = String(effective.ref_channel_name || '').trim();
        const hint = `已应用：${effMode}ch [${effNames.join(', ')}]${ref ? ` ｜ 参考：${ref}` : ''}`;
        setBadgeMsg(hint, 'success');
        try {
          window.dispatchEvent(new CustomEvent('bhb-channel-applied', {
            detail: { n_channels: effMode, channel_names: effNames, ref_channel_name: ref },
          }));
        } catch (_) {}
      } else {
        const msg = (res && res.message) ? String(res.message) : '应用失败';
        if (msg.includes('请先选择满') && msg.includes('通道')) {
          setBadgeMsg(msg, 'error');
          lastError = '';
        } else {
          lastError = msg;
        }
        render();
      }
    } catch (e) {
      lastError = `应用失败：${e && e.message ? e.message : e}`;
      render();
    } finally {
      btnApply.disabled = false;
    }
  };

  loadAll();
}
