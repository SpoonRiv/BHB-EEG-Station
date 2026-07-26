/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: EEG 频域（PSD）视图：WebSocket 接收 PSD 数据、通道勾选、ECharts 渲染与主题适配
作者: Spoon
*/

import { triggerStart, triggerStop } from './api.js';

export class EegPsdView {
  constructor({ channelNames, fmaxHz, triggerEnabled = false, triggerActive = null }) {
    this.channelNames = Array.isArray(channelNames) ? channelNames.slice() : [];
    this.colorByName = new Map();
    this._initColors();
    this.mode = 'time';
    this.ws = null;
    this.psdPayload = null;
    this.legendSelected = null;
    this.elControls = null;
    this.elTimeView = null;
    this.elPsdView = null;
    this.elChart = null;
    this.elToolbar = null;
    this.chart = null;
    this.theme = 'light';
    this.onModeChange = null;
    this.toggleBtn = null;
    this.triggerStartBtn = null;
    this.triggerStopBtn = null;
    this.triggerEnabled = !!triggerEnabled;
    this.triggerActive = triggerActive === null || triggerActive === undefined ? null : !!triggerActive;
    this.triggerPending = false;
    this.chkAll = null;
    this.chkByName = new Map();
    this.fmaxHz = Number.isFinite(Number(fmaxHz)) ? Number(fmaxHz) : null;
  }

  mount({ controlsId, timeViewId, psdViewId, chartId, toolbarId, onModeChange }) {
    this.elControls = document.getElementById(controlsId);
    this.elTimeView = document.getElementById(timeViewId);
    this.elPsdView = document.getElementById(psdViewId);
    this.elChart = document.getElementById(chartId);
    this.elToolbar = document.getElementById(toolbarId);
    this.onModeChange = typeof onModeChange === 'function' ? onModeChange : null;

    this._buildControls();
    this._initChart();
    this._buildToolbar();
    this.setMode(this.mode, true);
  }

  setTheme(theme) {
    const t = String(theme || 'light') === 'light' ? 'light' : 'dark';
    this.theme = t;
    this._applyTheme();
  }

  resize() {
    if (!this.chart) return;
    try { this.chart.resize(); } catch (_) {}
  }

  setMode(mode, silent = false) {
    const m = mode === 'psd' ? 'psd' : 'time';
    this.mode = m;
    if (this.elTimeView) this.elTimeView.classList.toggle('eeg-view--hidden', m !== 'time');
    if (this.elPsdView) this.elPsdView.classList.toggle('eeg-view--hidden', m !== 'psd');
    this._syncButtons();
    if (!silent && this.onModeChange) this.onModeChange(m);
    if (m === 'psd') this.connect();
    else this.close();
    if (m === 'psd') this._renderIfReady();
    this.resize();
  }

  connect() {
    if (this.ws) return;
    const url = `ws://${window.location.host}/ws/psd`;
    this.ws = new WebSocket(url);
    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg && msg.type === 'psd_data' && msg.data) {
          this.psdPayload = msg.data;
          if (this.mode === 'psd') this._renderIfReady();
        }
      } catch (_) {}
    };
    this.ws.onclose = () => {
      this.ws = null;
    };
  }

  close() {
    if (this.ws) {
      try { this.ws.close(); } catch (_) {}
      this.ws = null;
    }
  }

  dispose() {
    this.close();
    if (this.chart) {
      try { this.chart.dispose(); } catch (_) {}
      this.chart = null;
    }
  }

  _palette() {
    return [
      '#00D1FF', '#1366E9', '#74F0FF', '#7C4DFF',
      '#28E0A9', '#FFB020', '#FF4D7D', '#C7FF5B',
      '#36D4FF', '#5B7CFF', '#00FFA8', '#FF7AE6',
      '#0BE4FF', '#8EE9FF', '#8B5CF6', '#F97316'
    ];
  }

  _initColors() {
    const colors = this._palette();
    this.colorByName.clear();
    for (let i = 0; i < this.channelNames.length; i++) {
      this.colorByName.set(String(this.channelNames[i]), colors[i % colors.length]);
    }
  }

  _buildControls() {
    if (!this.elControls) return;
    this.elControls.innerHTML = '';
    const wrap = document.createElement('div');
    wrap.className = 'eeg-view-controls-row';

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn--ghost eeg-mode-toggle-btn';
    btn.setAttribute('aria-pressed', 'false');
    btn.textContent = '时域/频域';
    btn.onclick = () => {
      this.setMode(this.mode === 'psd' ? 'time' : 'psd');
    };
    wrap.appendChild(btn);

    const btnStart = document.createElement('button');
    btnStart.type = 'button';
    btnStart.className = 'btn btn--ghost eeg-view-btn eeg-trigger-start-btn';
    btnStart.textContent = '开始trigger';
    btnStart.onclick = async () => {
      await this._sendTriggerStart();
    };
    wrap.appendChild(btnStart);

    const btnStop = document.createElement('button');
    btnStop.type = 'button';
    btnStop.className = 'btn btn--ghost eeg-view-btn eeg-trigger-stop-btn';
    btnStop.textContent = '停止trigger';
    btnStop.onclick = async () => {
      await this._sendTriggerStop();
    };
    wrap.appendChild(btnStop);

    this.elControls.appendChild(wrap);
    this.toggleBtn = btn;
    this.triggerStartBtn = btnStart;
    this.triggerStopBtn = btnStop;
    this._syncTriggerButtons();
  }

  _syncButtons() {
    const isPsd = this.mode === 'psd';
    if (this.toggleBtn) {
      this.toggleBtn.setAttribute('aria-pressed', isPsd ? 'true' : 'false');
      this.toggleBtn.textContent = '时域/频域';
    }
    if (this.elToolbar) this.elToolbar.style.display = isPsd ? '' : 'none';
    this._syncTriggerButtons();
  }

  _syncTriggerButtons() {
    const enabled = !!this.triggerEnabled;
    const active = this.triggerActive;
    const pending = !!this.triggerPending;

    if (this.triggerStartBtn) {
      this.triggerStartBtn.disabled = !enabled || pending || active === true;
    }
    if (this.triggerStopBtn) {
      this.triggerStopBtn.disabled = !enabled || pending || active === false;
    }
  }

  async _sendTriggerStart() {
    if (!this.triggerEnabled || this.triggerPending) return;
    this.triggerPending = true;
    this._syncTriggerButtons();
    try {
      await triggerStart();
      this.triggerActive = true;
    } catch (e) {
      try { console.warn(e); } catch (_) {}
    } finally {
      this.triggerPending = false;
      this._syncTriggerButtons();
    }
  }

  async _sendTriggerStop() {
    if (!this.triggerEnabled || this.triggerPending) return;
    this.triggerPending = true;
    this._syncTriggerButtons();
    try {
      await triggerStop();
      this.triggerActive = false;
    } catch (e) {
      try { console.warn(e); } catch (_) {}
    } finally {
      this.triggerPending = false;
      this._syncTriggerButtons();
    }
  }

  selectAll() {
    if (!this.chart) return;
    const sel = {};
    for (const name of this.channelNames) {
      sel[String(name)] = true;
    }
    this.legendSelected = sel;
    this.chart.setOption({ legend: { selected: sel } }, false, false);
  }

  _buildToolbar() {
    if (!this.elToolbar) return;
    this.elToolbar.innerHTML = '';
    this.chkByName.clear();

    const row = document.createElement('div');
    row.className = 'check-row';

    const allLabel = document.createElement('label');
    allLabel.className = 'check psd-check-all';
    const all = document.createElement('input');
    all.type = 'checkbox';
    all.checked = true;
    const allText = document.createElement('span');
    allText.textContent = '全选';
    allLabel.appendChild(all);
    allLabel.appendChild(allText);

    all.onchange = () => {
      const checked = !!all.checked;
      for (const name of this.channelNames) {
        const input = this.chkByName.get(String(name));
        if (input) input.checked = checked;
      }
      this._syncLegendSelectedFromCheckboxes();
      all.indeterminate = false;
    };

    row.appendChild(allLabel);
    this.chkAll = all;

    for (const name of this.channelNames) {
      const label = document.createElement('label');
      label.className = 'check psd-check-item';
      const color = this.colorByName.get(String(name));
      if (color) label.style.setProperty('--psd-accent', color);
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.checked = true;
      const text = document.createElement('span');
      text.textContent = String(name);
      label.appendChild(input);
      label.appendChild(text);
      input.onchange = () => {
        this._syncLegendSelectedFromCheckboxes();
      };
      this.chkByName.set(String(name), input);
      row.appendChild(label);
    }

    this.elToolbar.appendChild(row);
    this._syncLegendSelectedFromCheckboxes();
  }

  _syncLegendSelectedFromCheckboxes() {
    const sel = {};
    let nOn = 0;
    let nTotal = 0;
    for (const name of this.channelNames) {
      const n = String(name);
      const input = this.chkByName.get(n);
      if (!input) continue;
      nTotal += 1;
      const on = !!input.checked;
      if (on) nOn += 1;
      sel[n] = on;
    }
    this.legendSelected = sel;
    if (this.chkAll) {
      this.chkAll.checked = nTotal > 0 && nOn === nTotal;
      this.chkAll.indeterminate = nOn > 0 && nOn < nTotal;
    }
    if (this.chart) {
      this.chart.setOption({ legend: { selected: sel } }, false, false);
    }
    this._renderIfReady();
  }

  _initChart() {
    if (!this.elChart) return;
    if (!window.echarts || typeof window.echarts.init !== 'function') return;
    this.chart = window.echarts.init(this.elChart, null, { renderer: 'canvas' });
    try {
      this.chart.on('legendselectchanged', (ev) => {
        if (ev && ev.selected) this.legendSelected = ev.selected;
      });
    } catch (_) {}
    this._applyTheme();
  }

  _applyTheme() {
    if (!this.chart) return;
    const isLight = this.theme === 'light';
    const axisColor = isLight ? '#111827' : 'rgba(255, 255, 255, 0.78)';
    const splitColor = isLight ? 'rgba(17, 24, 39, 0.10)' : 'rgba(255, 255, 255, 0.08)';
    const legendColor = isLight ? '#0b1020' : 'rgba(255, 255, 255, 0.86)';
    const xAxisMax = Number.isFinite(this.fmaxHz) ? this.fmaxHz : null;
    this.chart.setOption({
      backgroundColor: 'transparent',
      grid: { top: 28, bottom: 52, left: 72, right: 24, containLabel: true },
      tooltip: { trigger: 'axis', axisPointer: { type: 'line' } },
      legend: {
        show: false,
        type: 'scroll',
        top: 6,
        left: 12,
        right: 12,
        textStyle: { color: legendColor, fontWeight: 800 },
      },
      xAxis: {
        type: 'value',
        name: '频率 (Hz)',
        nameLocation: 'middle',
        nameGap: 34,
        nameTextStyle: { color: axisColor, fontWeight: 900 },
        min: 0,
        ...(xAxisMax === null ? {} : { max: xAxisMax }),
        axisLine: { show: true, lineStyle: { color: splitColor } },
        axisTick: { show: false },
        axisLabel: { color: axisColor },
        splitLine: { lineStyle: { color: splitColor, type: 'dashed' } },
      },
      yAxis: {
        type: 'value',
        nameLocation: 'middle',
        nameGap: 58,
        axisLine: { show: true, lineStyle: { color: splitColor } },
        axisTick: { show: false },
        axisLabel: { color: axisColor },
        splitLine: { lineStyle: { color: splitColor, type: 'dashed' } },
      },
      series: [],
      animation: false,
    }, true, false);
  }

  _renderIfReady() {
    if (!this.chart) return;
    const p = this.psdPayload;
    if (!p || !Array.isArray(p.freq_hz) || !p.channels || typeof p.channels !== 'object') return;
    const freq = p.freq_hz;
    if (freq.length <= 0) return;
    const unit = p.unit ? String(p.unit) : '';
    const yAxisName = unit ? `功率谱密度 (${unit})` : '功率谱密度';
    const cfgMax = Number.isFinite(this.fmaxHz) ? this.fmaxHz : null;
    let xMax = null;
    if (cfgMax !== null) {
      xMax = cfgMax;
    } else {
      const last = Number(freq[freq.length - 1]);
      xMax = Number.isFinite(last) ? Math.ceil(last) : null;
    }

    const series = [];
    for (const name of this.channelNames) {
      const y = p.channels[name];
      if (!Array.isArray(y) || y.length !== freq.length) continue;
      const data = new Array(freq.length);
      for (let i = 0; i < freq.length; i++) {
        data[i] = [freq[i], y[i]];
      }
      const color = this.colorByName.get(String(name)) || this._palette()[0];
      series.push({
        name: String(name),
        type: 'line',
        showSymbol: false,
        hoverAnimation: false,
        data,
        lineStyle: { width: 2.0, color },
      });
    }

    this.chart.setOption({
      xAxis: xMax === null ? {} : { max: xMax },
      yAxis: {
        name: yAxisName,
        nameLocation: 'middle',
        nameGap: 58,
        nameTextStyle: { color: this.theme === 'light' ? '#111827' : 'rgba(255, 255, 255, 0.78)', fontWeight: 900 },
      },
      legend: this.legendSelected ? { selected: this.legendSelected } : {},
      series,
    }, false, false);
  }
}
