/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: EEG 频域（PSD）视图：WebSocket 接收 PSD 数据、通道勾选、ECharts 渲染与主题适配

修改日志:
- 2026-05-29: 1.0.0 创建文件
- 2026-05-29: 1.0.1 移除左侧勾选列表：改为图例点选并增加“全选”；仅在频域模式连接 PSD WebSocket
- 2026-05-30: 1.0.2 频域切换改为单开关；通道选择改为居中复选框条（含全选），频域时不显示图例
- 2026-05-30: 1.0.3 切换开关改为 iOS 风格（与动态Y轴一致），不改变控件与电量位置
- 2026-05-30: 1.0.4 切换按钮改为独立大号“时域/频域”拨片按钮；全选区分并按曲线颜色渲染复选框
- 2026-05-30: 1.0.5 频域图内边距与网格留白调整（四边等距观感更一致）
- 2026-05-30: 1.0.6 频域初始态显示坐标轴；网格使用 containLabel 保持四边等距观感
- 2026-05-30: 1.0.7 切换控件使用主按钮风格并启用扫光（保持开关形态）
- 2026-05-30: 1.0.8 初始态显示坐标轴但不固定纵轴范围（避免与 dB/线性模式不一致）
- 2026-05-30: 1.0.9 频域横坐标固定为 0-100Hz；切换按钮改为仿日夜模式按钮（文本“时域/频域”）
- 2026-05-30: 1.0.10 时域/频域切换按钮不随状态变色，且文案按当前模式显示“时域/频域”
- 2026-05-30: 1.0.11 频域横坐标上限跟随后端配置 fmax_hz（默认 80Hz）
- 2026-05-30: 1.0.12 时域/频域切换按钮文案固定为“时域/频域”

作者: Spoon
版本: 1.0.12
*/

export class EegPsdView {
  constructor({ channelNames, fmaxHz }) {
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
    if (this.chart) {
      try { this.chart.resize(); } catch (_) {}
    }
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
    btn.className = 'btn btn--sm btn--ghost eeg-mode-toggle-btn';
    btn.setAttribute('aria-pressed', 'false');
    btn.textContent = '时域/频域';
    btn.onclick = () => {
      this.setMode(this.mode === 'psd' ? 'time' : 'psd');
    };
    wrap.appendChild(btn);
    this.elControls.appendChild(wrap);
    this.toggleBtn = btn;
  }

  _syncButtons() {
    const isPsd = this.mode === 'psd';
    if (this.toggleBtn) {
      this.toggleBtn.setAttribute('aria-pressed', isPsd ? 'true' : 'false');
      this.toggleBtn.textContent = '时域/频域';
    }
    if (this.elToolbar) this.elToolbar.style.display = isPsd ? '' : 'none';
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
      grid: { top: 14, bottom: 14, left: 14, right: 14, containLabel: true },
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
        name: 'Hz',
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
      yAxis: { name: unit, nameTextStyle: { color: this.theme === 'light' ? '#111827' : 'rgba(255, 255, 255, 0.78)', fontWeight: 900 } },
      legend: this.legendSelected ? { selected: this.legendSelected } : {},
      series,
    }, false, false);
  }
}
