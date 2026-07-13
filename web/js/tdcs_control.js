/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: tDCS 控制面板（根据后端下发的两级指令元数据生成按钮，并支持带参指令编码与下发）
作者: Spoon
*/

import { getTwoLevelCommands, sendTwoLevelCommand } from './api.js';

let bound = false;
let commands = null;
let containerEl = null;
let reportFn = null;

const TDCS_L1 = 0x07;

function normalizeInt(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return null;
  return Math.trunc(n);
}

function clampInt(n, min, max) {
  const x = normalizeInt(n);
  if (x === null) return null;
  if (x < min) return min;
  if (x > max) return max;
  return x;
}

function toU16beBytes(u16) {
  const v = clampInt(u16, 0, 65535);
  if (v === null) return null;
  return [(v >> 8) & 0xFF, v & 0xFF];
}

function setReport(fn) {
  reportFn = typeof fn === 'function' ? fn : null;
}

function report(text, kind) {
  if (reportFn) reportFn(text, kind);
}

function el(tag, className, text) {
  const e = document.createElement(tag);
  if (className) e.className = className;
  if (text !== undefined) e.textContent = String(text);
  return e;
}

async function doSend(l1, l2, data, label) {
  try {
    report(`正在下发：${label || '控制指令'}…`, '');
    const res = await sendTwoLevelCommand(l1, l2, data || null);
    const ok = !!(res && res.status === 'success');
    if (ok) {
      report(`已下发：${label || '控制指令'}（请查看 CMD_TX）`, 'success');
    } else {
      const msg = res && res.message ? String(res.message) : '下发失败';
      report(`下发失败：${msg}`, 'error');
    }
  } catch (e) {
    report(`下发失败：${String(e && e.message ? e.message : e)}`, 'error');
  }
}

function buildTdcsParamEncoder(l2) {
  const v = intOrNull(l2);
  if (v === 0x10) {
    return {
      label: '输出电流（mA）',
      placeholder: '例如：2.0',
      encode: (text) => {
        const n = Number(String(text || '').trim());
        if (!Number.isFinite(n) || n < 0) return null;
        const u16 = Math.round((n * 65536) / 20.0);
        return toU16beBytes(u16);
      },
      preview: (text) => {
        const n = Number(String(text || '').trim());
        if (!Number.isFinite(n) || n < 0) return null;
        return Math.round((n * 65536) / 20.0);
      },
    };
  }
  if (v === 0x20) {
    return {
      label: '缓升时间（秒）',
      placeholder: '例如：1.0',
      encode: (text) => {
        const n = Number(String(text || '').trim());
        if (!Number.isFinite(n) || n < 0) return null;
        const u16 = Math.round(n * 10.0);
        return toU16beBytes(u16);
      },
      preview: (text) => {
        const n = Number(String(text || '').trim());
        if (!Number.isFinite(n) || n < 0) return null;
        return Math.round(n * 10.0);
      },
    };
  }
  if (v === 0x21) {
    return {
      label: '稳定时间（秒）',
      placeholder: '例如：10',
      encode: (text) => {
        const n = Number(String(text || '').trim());
        if (!Number.isFinite(n) || n < 0) return null;
        const u16 = Math.round(n);
        return toU16beBytes(u16);
      },
      preview: (text) => {
        const n = Number(String(text || '').trim());
        if (!Number.isFinite(n) || n < 0) return null;
        return Math.round(n);
      },
    };
  }
  if (v === 0x22) {
    return {
      label: '缓降时间（秒）',
      placeholder: '例如：1.0',
      encode: (text) => {
        const n = Number(String(text || '').trim());
        if (!Number.isFinite(n) || n < 0) return null;
        const u16 = Math.round(n * 10.0);
        return toU16beBytes(u16);
      },
      preview: (text) => {
        const n = Number(String(text || '').trim());
        if (!Number.isFinite(n) || n < 0) return null;
        return Math.round(n * 10.0);
      },
    };
  }
  if (v === 0x23) {
    return {
      label: '报警阈值（mA）',
      placeholder: '例如：2.6',
      encode: (text) => {
        const n = Number(String(text || '').trim());
        if (!Number.isFinite(n) || n < 0) return null;
        const u16 = Math.round(n * 8000.0);
        return toU16beBytes(u16);
      },
      preview: (text) => {
        const n = Number(String(text || '').trim());
        if (!Number.isFinite(n) || n < 0) return null;
        return Math.round(n * 8000.0);
      },
    };
  }
  return null;
}

function intOrNull(v) {
  const n = normalizeInt(v);
  return n === null ? null : (n & 0xFF);
}

function renderTdcsButtons(cmds) {
  const root = el('div', 'tdcs-controls');
  const all = Array.isArray(cmds && cmds.commands) ? cmds.commands : [];
  const tdcs = all.find((x) => intOrNull(x && x.l1) === TDCS_L1) || null;
  const children = Array.isArray(tdcs && tdcs.children) ? tdcs.children : [];
  const preferredOrder = new Map([
    [0x10, 0],
    [0x21, 1],
    [0x15, 2],
    [0x16, 3],
    [0x20, 4],
    [0x22, 5],
    [0x23, 6],
  ]);
  const orderedChildren = [...children].sort((a, b) => {
    const la = intOrNull(a && a.l2);
    const lb = intOrNull(b && b.l2);
    const ka = la === null ? 9999 : (preferredOrder.has(la) ? preferredOrder.get(la) : 1000 + la);
    const kb = lb === null ? 9999 : (preferredOrder.has(lb) ? preferredOrder.get(lb) : 1000 + lb);
    return ka - kb;
  });

  const grid = el('div', 'tdcs-ops-grid');
  for (const c of orderedChildren) {
    const l2 = intOrNull(c && c.l2);
    if (l2 === null) continue;
    if (l2 === 0x01 || l2 === 0x02) continue;
    const payloadSpec = String(c.payload_spec || 'none');
    const fullTitle = String(c.desc || c.name || '').trim() || '操作';
    const help = String(c.help || '').trim() || '';

    const shortTitle = (() => {
      if (l2 === 0x15) return '使能高压';
      if (l2 === 0x16) return '禁止高压';
      if (l2 === 0x10) return '设置电流';
      if (l2 === 0x20) return '缓升时间';
      if (l2 === 0x21) return '稳定时间';
      if (l2 === 0x22) return '缓降时间';
      if (l2 === 0x23) return '报警阈值';
      return fullTitle;
    })();

    const card = el('div', 'tdcs-op-card');
    const head = el('div', 'tdcs-op-head');
    const btn = el('button', 'btn tdcs-op-btn', shortTitle);
    const desc = el('div', 'tdcs-op-desc', help || '');
    if (!help) desc.style.display = 'none';

    if (payloadSpec === 'none') {
      btn.onclick = async () => { await doSend(TDCS_L1, l2, null, fullTitle); };
      head.appendChild(btn);
      head.appendChild(el('div', 'tdcs-op-right'));
      card.appendChild(head);
      card.appendChild(desc);
      grid.appendChild(card);
      continue;
    }

    if (payloadSpec === 'u16be') {
      const encoder = buildTdcsParamEncoder(l2);
      const input = el('input', 'tdcs-op-input');
      input.type = 'text';
      input.inputMode = 'decimal';
      input.placeholder = encoder ? encoder.placeholder : '';
      btn.onclick = async () => {
        if (!encoder) {
          report('该操作需要参数，但未找到编码规则', 'error');
          return;
        }
        const bytes = encoder.encode(input.value);
        if (!bytes) {
          report('参数格式错误：请输入有效数值', 'error');
          return;
        }
        await doSend(TDCS_L1, l2, bytes, fullTitle);
      };
      head.appendChild(btn);
      const right = el('div', 'tdcs-op-right');
      if (encoder && encoder.label) {
        input.setAttribute('aria-label', String(encoder.label));
      }
      right.appendChild(input);
      head.appendChild(right);
      card.appendChild(head);
      card.appendChild(desc);
      grid.appendChild(card);
      continue;
    }

    btn.onclick = async () => {
      report('当前 UI 仅提供 tDCS 操作按钮（不支持该指令的附加数据格式）', 'error');
    };
    head.appendChild(btn);
    head.appendChild(el('div', 'tdcs-op-right'));
    card.appendChild(head);
    card.appendChild(desc);
    grid.appendChild(card);
  }

  root.appendChild(grid);
  return root;
}

async function ensureCommands() {
  if (commands) return commands;
  commands = await getTwoLevelCommands();
  return commands;
}

export async function initTdcsControlPanel(opts) {
  if (bound) return;
  bound = true;
  containerEl = document.getElementById((opts && opts.containerId) || 'tdcs-controls');
  setReport(opts && opts.report);
  if (!containerEl) return;
  try {
    const cmds = await ensureCommands();
    containerEl.innerHTML = '';
    containerEl.appendChild(renderTdcsButtons(cmds));
  } catch (e) {
    containerEl.innerHTML = '';
    containerEl.appendChild(el('div', 'hint-strip error', `控制面板加载失败：${String(e && e.message ? e.message : e)}`));
  }
}
