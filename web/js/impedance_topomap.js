/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 阻抗地形图渲染（10-20 电极位置 SVG + 按阈值着色 + 选中高亮）。

修改日志:
- 2026-05-04: 1.0.0 创建文件

作者: Spoon
版本: 1.0.0
*/

const ELECTRODE_POS = {
  Fp1: { x: 38, y: 10 },
  Fp2: { x: 62, y: 10 },
  AF3: { x: 42, y: 18 },
  AF4: { x: 58, y: 18 },
  F7: { x: 18, y: 22 },
  F3: { x: 34, y: 26 },
  Fz: { x: 50, y: 26 },
  F4: { x: 66, y: 26 },
  F8: { x: 82, y: 22 },
  T3: { x: 12, y: 44 },
  C3: { x: 32, y: 44 },
  Cz: { x: 50, y: 44 },
  C4: { x: 68, y: 44 },
  T4: { x: 88, y: 44 },
  P7: { x: 22, y: 64 },
  P3: { x: 34, y: 62 },
  Pz: { x: 50, y: 66 },
  P4: { x: 66, y: 62 },
  P8: { x: 78, y: 64 },
  PO7: { x: 34, y: 74 },
  PO3: { x: 40, y: 70 },
  O1: { x: 42, y: 80 },
  PO4: { x: 60, y: 70 },
  PO8: { x: 66, y: 74 },
  O2: { x: 58, y: 80 },
};

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
  grad.setAttribute('id', 'bhb_imp_head_bg');
  grad.setAttribute('cx', '50%');
  grad.setAttribute('cy', '45%');
  grad.setAttribute('r', '54%');
  const stops = [
    { o: '0%', c: 'rgb(49, 215, 255)', a: '0.075' },
    { o: '72%', c: 'rgb(49, 215, 255)', a: '0.028' },
    { o: '100%', c: 'rgb(49, 215, 255)', a: '0' },
  ];
  for (const one of stops) {
    const s = document.createElementNS('http://www.w3.org/2000/svg', 'stop');
    s.setAttribute('offset', one.o);
    s.setAttribute('stop-color', one.c);
    s.setAttribute('stop-opacity', one.a);
    grad.appendChild(s);
  }
  defs.appendChild(grad);
  svg.appendChild(defs);

  const bg = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
  bg.setAttribute('x', '0');
  bg.setAttribute('y', '0');
  bg.setAttribute('width', '100');
  bg.setAttribute('height', '100');
  bg.setAttribute('fill', 'url(#bhb_imp_head_bg)');
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

function classifyOhm(value, goodMax, warnMax) {
  const v = Number(value);
  if (!Number.isFinite(v) || v <= 0) return 'unknown';
  if (v <= goodMax) return 'good';
  if (v <= warnMax) return 'warn';
  return 'bad';
}

export function createImpedanceTopomap(hostEl, channelNames, ui) {
  if (!hostEl) return null;

  const goodMax = ui && typeof ui.good_max_ohm === 'number' ? ui.good_max_ohm : (ui && typeof ui.goodMaxOhm === 'number' ? ui.goodMaxOhm : 10000);
  const warnMax = ui && typeof ui.warn_max_ohm === 'number' ? ui.warn_max_ohm : (ui && typeof ui.warnMaxOhm === 'number' ? ui.warnMaxOhm : 30000);

  const svg = createSvgRoot();
  drawHead(svg);

  const circles = new Map();
  const groups = new Map();

  const names = Array.isArray(channelNames) ? channelNames : [];
  for (const name of names) {
    const pos = ELECTRODE_POS[name];
    if (!pos) continue;
    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.classList.add('electrode', 'imp-electrode', 'imp-unknown');
    g.dataset.name = name;

    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.classList.add('electrode-circle');
    circle.setAttribute('cx', String(pos.x));
    circle.setAttribute('cy', String(pos.y));
    circle.setAttribute('r', '4.4');
    g.appendChild(circle);

    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.classList.add('electrode-text');
    text.setAttribute('x', String(pos.x));
    text.setAttribute('y', String(pos.y + 0.9));
    text.setAttribute('text-anchor', 'middle');
    text.setAttribute('dominant-baseline', 'middle');
    text.setAttribute('font-size', '3.55');
    text.setAttribute('font-weight', '650');
    text.textContent = name;
    g.appendChild(text);

    svg.appendChild(g);
    circles.set(name, circle);
    groups.set(name, g);
  }

  hostEl.innerHTML = '';
  hostEl.appendChild(svg);

  let selected = '';
  let thresholds = { goodMaxOhm: goodMax, warnMaxOhm: warnMax };
  let onSelect = null;

  function setSelected(name) {
    selected = String(name || '');
    for (const [n, g] of groups.entries()) {
      if (n === selected) g.classList.add('imp-selected');
      else g.classList.remove('imp-selected');
    }
  }

  function setThresholds(next) {
    if (!next || typeof next !== 'object') return;
    const g = Number(next.goodMaxOhm);
    const w = Number(next.warnMaxOhm);
    if (Number.isFinite(g) && g > 0) thresholds.goodMaxOhm = g;
    if (Number.isFinite(w) && w > thresholds.goodMaxOhm) thresholds.warnMaxOhm = w;
  }

  function setOnSelect(fn) {
    onSelect = typeof fn === 'function' ? fn : null;
    for (const [n, g] of groups.entries()) {
      g.onclick = onSelect ? () => { setSelected(n); onSelect(n); } : null;
    }
  }

  function update(valuesByName) {
    const vm = valuesByName && typeof valuesByName === 'object' ? valuesByName : {};
    for (const [n, g] of groups.entries()) {
      const v = vm[n];
      const kind = classifyOhm(v, thresholds.goodMaxOhm, thresholds.warnMaxOhm);
      g.classList.remove('imp-good', 'imp-warn', 'imp-bad', 'imp-unknown');
      g.classList.add(`imp-${kind}`);
      const c = circles.get(n);
      if (c) {
        const title = `${n}: ${Number.isFinite(Number(v)) ? Math.round(Number(v)) : '--'} Ω`;
        c.setAttribute('data-title', title);
      }
    }
  }

  return { update, setSelected, setThresholds, setOnSelect };
}

