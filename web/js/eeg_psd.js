/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: EEG 频谱与频带特征视图：展示实时 Welch PSD、频带能量、微分熵及多/单通道切换
作者: Spoon
*/

import { triggerStart, triggerStop } from './api.js';
import { createSelectableTopomap } from './impedance_topomap.js';

const PSD_DISPLAY_MIN_HZ = 1;
const PSD_DISPLAY_MAX_HZ = 45;

const GEAR_SVG = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>';
const CLOSE_SVG = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';

const FALLBACK_BANDS = [
  { key: 'delta', name: 'Delta', symbol: '', fmin_hz: 1, fmax_hz: 4 },
  { key: 'theta', name: 'Theta', symbol: '', fmin_hz: 4, fmax_hz: 8 },
  { key: 'alpha', name: 'Alpha', symbol: '', fmin_hz: 8, fmax_hz: 13 },
  { key: 'beta', name: 'Beta', symbol: '', fmin_hz: 13, fmax_hz: 30 },
  { key: 'gamma', name: 'Gamma', symbol: '', fmin_hz: 30, fmax_hz: 45 },
];

// 与 attention_monitor.py 保持一致，图例、频谱底色和柱状图共用这组颜色。
const BAND_COLORS = {
  delta: '#8DA0CB',
  theta: '#66C2A5',
  alpha: '#FFD166',
  beta: '#06D6A0',
  gamma: '#EF476F',
};

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function formatHz(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '--';
  return Number.isInteger(n) ? String(n) : String(Number(n.toFixed(1)));
}

function formatPower(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n < 0) return '--';
  if (n >= 10000) return n.toExponential(2);
  if (n >= 100) return n.toFixed(1);
  if (n >= 1) return n.toFixed(2);
  return n.toFixed(3);
}

function hexToRgba(hex, alpha) {
  const raw = String(hex || '').replace('#', '');
  if (!/^[0-9a-fA-F]{6}$/.test(raw)) return `rgba(56, 189, 248, ${alpha})`;
  const r = Number.parseInt(raw.slice(0, 2), 16);
  const g = Number.parseInt(raw.slice(2, 4), 16);
  const b = Number.parseInt(raw.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

export class EegPsdView {
  constructor({
    channelNames,
    triggerEnabled = false,
    triggerActive = null,
    electrodePositions = null,
    electrodeAliases = null,
  }) {
    this.channelNames = Array.isArray(channelNames) ? channelNames.map(String) : [];
    this.mode = 'time';
    this.scopeMode = 'average';
    this.bandMetricMode = 'energy';
    this.activeChannel = this.channelNames[0] || '';
    this.ws = null;
    this.reconnectTimer = null;
    this.reconnectAttempt = 0;
    this.disposed = false;
    this.psdPayload = null;
    this.theme = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';

    this.elControls = null;
    this.elTimeView = null;
    this.elPsdView = null;
    this.elToolbar = null;
    this.elScopeControls = null;
    this.elYAxisControls = null;
    this.elSignalTitle = null;
    this.elSpectrumChart = null;
    this.elBandChart = null;
    this.elBandTitle = null;
    this.elBandMetricControls = null;
    this.elSettingsPopover = null;
    this.elLegend = null;

    this.spectrumChart = null;
    this.bandChart = null;
    this.topomap = null;
    this.toggleBtn = null;
    this.scopeToggle = null;
    this.settingsToggleBtn = null;
    this.elTopomapSection = null;
    this.triggerStartBtn = null;
    this.triggerStopBtn = null;
    this.bandMetricButtons = [];
    this.onModeChange = null;
    this.legendSignature = '';

    this.triggerEnabled = !!triggerEnabled;
    this.triggerActive = triggerActive === null || triggerActive === undefined ? null : !!triggerActive;
    this.triggerPending = false;
    this.electrodePositions = electrodePositions && typeof electrodePositions === 'object' ? electrodePositions : null;
    this.electrodeAliases = electrodeAliases && typeof electrodeAliases === 'object' ? electrodeAliases : null;
  }

  mount({ controlsId, timeViewId, psdViewId, chartId, bandChartId, toolbarId, scopeControlsId, yAxisControlsId, onModeChange }) {
    this.disposed = false;
    this.elControls = document.getElementById(controlsId);
    this.elTimeView = document.getElementById(timeViewId);
    this.elPsdView = document.getElementById(psdViewId);
    this.elToolbar = document.getElementById(toolbarId);
    this.elScopeControls = document.getElementById(scopeControlsId);
    this.elYAxisControls = document.getElementById(yAxisControlsId);
    this.elSignalTitle = document.getElementById('eeg-signal-title');
    this.elSpectrumChart = document.getElementById(chartId);
    this.elBandChart = document.getElementById(bandChartId);
    this.elBandTitle = document.getElementById('band-power-title');
    this.elBandMetricControls = document.getElementById('band-metric-controls');
    this.onModeChange = typeof onModeChange === 'function' ? onModeChange : null;

    this._buildControls();
    this._buildToolbar();
    this._buildSettingsPopover();
    this._buildBandMetricControls();
    this._initTopomap();
    this._initCharts();
    this._syncScopeControls();
    this.setMode(this.mode, true);
  }

  setTheme(theme) {
    this.theme = String(theme || 'light') === 'light' ? 'light' : 'dark';
    this._renderIfReady();
  }

  resize() {
    for (const chart of [this.spectrumChart, this.bandChart]) {
      if (!chart) continue;
      try { chart.resize(); } catch (_) {}
    }
  }

  setMode(mode, silent = false) {
    const next = mode === 'psd' ? 'psd' : 'time';
    this.mode = next;
    this._setSettingsPopoverOpen(false);
    if (this.elTimeView) this.elTimeView.classList.toggle('eeg-view--hidden', next !== 'time');
    if (this.elPsdView) this.elPsdView.classList.toggle('eeg-view--hidden', next !== 'psd');
    if (this.elSignalTitle) {
      this.elSignalTitle.textContent = next === 'psd'
        ? '脑电功率谱与频带特征（频域）'
        : '实时脑电信号（时域）';
    }
    this._syncButtons();
    if (!silent && this.onModeChange) this.onModeChange(next);
    if (next === 'psd') this.connect();
    else this.close();
    if (next === 'psd') this._renderIfReady();
    requestAnimationFrame(() => this.resize());
  }

  connect() {
    if (this.disposed || this.mode !== 'psd' || this.ws) return;
    this._clearReconnectTimer();
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${proto}://${window.location.host}/ws/psd`;
    let socket;
    try {
      socket = new WebSocket(url);
    } catch (_) {
      this._scheduleReconnect();
      return;
    }
    this.ws = socket;
    socket.onmessage = (event) => {
      if (this.ws !== socket || this.disposed || this.mode !== 'psd') return;
      try {
        const msg = JSON.parse(event.data);
        if (msg && msg.type === 'psd_data' && msg.data) {
          this.reconnectAttempt = 0;
          this.psdPayload = msg.data;
          this._renderIfReady();
        }
      } catch (_) {}
    };
    socket.onclose = () => {
      if (this.ws !== socket) return;
      this.ws = null;
      if (this.mode === 'psd' && !this.disposed) {
        this._scheduleReconnect();
      }
    };
  }

  close() {
    this._clearReconnectTimer();
    this.reconnectAttempt = 0;
    const socket = this.ws;
    this.ws = null;
    if (socket) {
      try { socket.close(); } catch (_) {}
    }
    this._setSettingsPopoverOpen(false);
  }

  dispose() {
    this.disposed = true;
    this.close();
    for (const chart of [this.spectrumChart, this.bandChart]) {
      if (!chart) continue;
      try { chart.dispose(); } catch (_) {}
    }
    this.spectrumChart = null;
    this.bandChart = null;
    this.topomap = null;
  }

  _clearReconnectTimer() {
    if (this.reconnectTimer === null) return;
    window.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
  }

  _scheduleReconnect() {
    if (this.disposed || this.mode !== 'psd' || this.ws || this.reconnectTimer !== null) return;
    const delayMs = Math.min(5000, 750 * (2 ** Math.min(this.reconnectAttempt, 3)));
    this.reconnectAttempt += 1;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delayMs);
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
    btn.onclick = () => this.setMode(this.mode === 'psd' ? 'time' : 'psd');
    wrap.appendChild(btn);

    const btnStart = document.createElement('button');
    btnStart.type = 'button';
    btnStart.className = 'btn btn--ghost eeg-view-btn eeg-trigger-start-btn';
    btnStart.textContent = '开始trigger';
    btnStart.onclick = async () => this._sendTriggerStart();
    wrap.appendChild(btnStart);

    const btnStop = document.createElement('button');
    btnStop.type = 'button';
    btnStop.className = 'btn btn--ghost eeg-view-btn eeg-trigger-stop-btn';
    btnStop.textContent = '停止trigger';
    btnStop.onclick = async () => this._sendTriggerStop();
    wrap.appendChild(btnStop);

    this.elControls.appendChild(wrap);
    this.toggleBtn = btn;
    this.triggerStartBtn = btnStart;
    this.triggerStopBtn = btnStop;
    this._syncTriggerButtons();
  }

  _buildToolbar() {
    if (!this.elToolbar) return;
    this.elToolbar.innerHTML = '';
    if (this.elScopeControls) this.elScopeControls.innerHTML = '';
    const row = document.createElement('div');
    row.className = 'band-toolbar-row';

    const legend = document.createElement('div');
    legend.className = 'band-legend';
    legend.setAttribute('aria-label', '频带范围图例');

    const metaArea = document.createElement('div');
    metaArea.className = 'spectrum-toolbar-meta';
    metaArea.appendChild(legend);

    row.appendChild(metaArea);
    this.elToolbar.appendChild(row);

    this.elLegend = legend;
    this._renderBandLegend(FALLBACK_BANDS);
  }

  _buildSettingsPopover() {
    const wrap = this.elScopeControls;
    if (!wrap) return;
    wrap.innerHTML = '';

    const toggleBtn = document.createElement('button');
    toggleBtn.type = 'button';
    toggleBtn.className = 'btn btn--sm btn--icon btn--ghost eeg-settings-toggle-btn';
    toggleBtn.innerHTML = GEAR_SVG;
    toggleBtn.title = '频谱设置';
    toggleBtn.setAttribute('aria-expanded', 'false');
    wrap.appendChild(toggleBtn);

    const popover = document.createElement('aside');
    popover.className = 'eeg-settings-popover eeg-psd-settings-popover';
    popover.hidden = true;

    const head = document.createElement('div');
    head.className = 'eeg-settings-popover-head';
    const headTitle = document.createElement('div');
    headTitle.className = 'band-panel-title';
    headTitle.textContent = '频谱设置';
    head.appendChild(headTitle);
    popover.appendChild(head);

    const body = document.createElement('div');
    body.className = 'eeg-settings-popover-body';

    // === Section 1: 数据源（通道平均开关） ===
    const sec1 = document.createElement('div');
    sec1.className = 'eeg-settings-section';
    const sec1Title = document.createElement('div');
    sec1Title.className = 'eeg-settings-section-title';
    sec1Title.textContent = '数据源';
    sec1.appendChild(sec1Title);

    const rowAvg = document.createElement('div');
    rowAvg.className = 'eeg-settings-row';
    const avgText = document.createElement('span');
    avgText.className = 'eeg-settings-label';
    avgText.textContent = '通道平均';
    const avgLabel = document.createElement('label');
    avgLabel.className = 'ios-switch';
    avgLabel.title = '开启为通道平均，关闭为单通道';
    const avgInput = document.createElement('input');
    avgInput.type = 'checkbox';
    avgInput.checked = this.scopeMode === 'average';
    avgInput.setAttribute('role', 'switch');
    avgInput.setAttribute('aria-label', '通道平均');
    avgInput.onchange = () => this._setScopeMode(avgInput.checked ? 'average' : 'channel');
    const avgSlider = document.createElement('span');
    avgSlider.className = 'ios-slider';
    avgLabel.appendChild(avgInput);
    avgLabel.appendChild(avgSlider);
    rowAvg.appendChild(avgText);
    rowAvg.appendChild(avgLabel);
    sec1.appendChild(rowAvg);
    body.appendChild(sec1);

    // === Section 2: 选择通道（地形图） ===
    const sec2 = document.createElement('div');
    sec2.className = 'eeg-settings-section eeg-settings-topomap-section';
    const sec2Title = document.createElement('div');
    sec2Title.className = 'eeg-settings-section-title';
    sec2Title.textContent = '选择通道';
    sec2.appendChild(sec2Title);

    const mapHint = document.createElement('div');
    mapHint.className = 'eeg-settings-hint';
    mapHint.textContent = '点击电极后，两张图同步切换到该通道';
    sec2.appendChild(mapHint);

    const mapWrap = document.createElement('div');
    mapWrap.className = 'band-channel-map topomap-canvas';
    const mapHost = document.createElement('div');
    mapHost.id = 'band-channel-topomap';
    mapHost.className = 'topomap-svg band-power-map';
    mapWrap.appendChild(mapHost);
    sec2.appendChild(mapWrap);
    body.appendChild(sec2);

    popover.appendChild(body);
    wrap.appendChild(popover);

    toggleBtn.onclick = () => this._setSettingsPopoverOpen(popover.hidden);

    this.settingsToggleBtn = toggleBtn;
    this.elSettingsPopover = popover;
    this.scopeToggle = avgInput;
    this.elTopomapSection = sec2;
  }

  _buildBandMetricControls() {
    if (!this.elBandMetricControls) return;
    this.elBandMetricControls.innerHTML = '';
    this.bandMetricButtons = [];

    const options = [
      { key: 'energy', label: '%', ariaLabel: '相对功率百分比', title: '显示各频段相对功率' },
      { key: 'de', label: 'DE', ariaLabel: '微分熵 DE', title: '显示各频段微分熵（Differential Entropy）' },
    ];
    for (const option of options) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn seg-btn band-metric-btn';
      button.dataset.metric = option.key;
      button.textContent = option.label;
      button.setAttribute('aria-label', option.ariaLabel);
      button.title = option.title;
      button.onclick = () => this._setBandMetricMode(option.key);
      this.elBandMetricControls.appendChild(button);
      this.bandMetricButtons.push(button);
    }
    this._syncBandMetricControls();
  }

  _setBandMetricMode(mode) {
    const next = mode === 'de' ? 'de' : 'energy';
    if (this.bandMetricMode === next) return;
    this.bandMetricMode = next;
    this._syncBandMetricControls();
    this._renderIfReady();
  }

  _syncBandMetricControls() {
    const isDe = this.bandMetricMode === 'de';
    if (this.elBandTitle) {
      this.elBandTitle.textContent = isDe ? '各频段微分熵' : '各频段相对功率';
    }
    for (const button of this.bandMetricButtons) {
      const active = button.dataset.metric === this.bandMetricMode;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    }
  }

  _initTopomap() {
    const host = document.getElementById('band-channel-topomap');
    this.topomap = createSelectableTopomap(
      host,
      this.channelNames,
      this.electrodePositions,
      this.electrodeAliases,
    );
    if (!this.topomap) return;
    this.topomap.setOnSelect((name) => this._setActiveChannel(name));
    this.topomap.setSelected(this.activeChannel);
  }

  _setSettingsPopoverOpen(open) {
    const shouldOpen = !!open;
    if (this.elSettingsPopover) this.elSettingsPopover.hidden = !shouldOpen;
    if (this.settingsToggleBtn) {
      this.settingsToggleBtn.innerHTML = shouldOpen ? CLOSE_SVG : GEAR_SVG;
      this.settingsToggleBtn.setAttribute('aria-expanded', shouldOpen ? 'true' : 'false');
    }
    if (shouldOpen && this.topomap) this.topomap.setSelected(this.activeChannel);
  }

  _initCharts() {
    if (!window.echarts || typeof window.echarts.init !== 'function') return;
    if (this.elSpectrumChart) this.spectrumChart = window.echarts.init(this.elSpectrumChart, null, { renderer: 'canvas' });
    if (this.elBandChart) this.bandChart = window.echarts.init(this.elBandChart, null, { renderer: 'canvas' });
    this._renderWaitingCharts('等待频谱数据');
  }

  _setScopeMode(mode) {
    this.scopeMode = mode === 'channel' ? 'channel' : 'average';
    if (!this.activeChannel && this.channelNames.length) this.activeChannel = this.channelNames[0];
    this._syncScopeControls();
    this._renderIfReady();
    requestAnimationFrame(() => this.resize());
  }

  _syncScopeControls() {
    const isChannel = this.scopeMode === 'channel';
    if (this.scopeToggle) this.scopeToggle.checked = !isChannel;
    if (this.elTopomapSection) this.elTopomapSection.classList.toggle('is-dim', !isChannel);
  }

  _setActiveChannel(name) {
    const next = String(name || '');
    if (!this.channelNames.includes(next)) return;
    this.activeChannel = next;
    if (this.topomap) this.topomap.setSelected(next);
    if (this.scopeMode === 'channel') this._renderIfReady();
  }

  _syncButtons() {
    const isMonitor = this.mode === 'psd';
    if (this.toggleBtn) {
      this.toggleBtn.setAttribute('aria-pressed', isMonitor ? 'true' : 'false');
      this.toggleBtn.textContent = '时域/频域';
    }
    if (this.elToolbar) this.elToolbar.style.display = isMonitor ? '' : 'none';
    if (this.elScopeControls) this.elScopeControls.hidden = !isMonitor;
    if (this.elYAxisControls) this.elYAxisControls.hidden = isMonitor;
    this._syncTriggerButtons();
  }

  _syncTriggerButtons() {
    const enabled = !!this.triggerEnabled;
    const active = this.triggerActive;
    const pending = !!this.triggerPending;
    if (this.triggerStartBtn) this.triggerStartBtn.disabled = !enabled || pending || active === true;
    if (this.triggerStopBtn) this.triggerStopBtn.disabled = !enabled || pending || active === false;
  }

  async _sendTriggerStart() {
    if (!this.triggerEnabled || this.triggerPending) return;
    this.triggerPending = true;
    this._syncTriggerButtons();
    try {
      await triggerStart();
      this.triggerActive = true;
    } catch (error) {
      try { console.warn(error); } catch (_) {}
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
    } catch (error) {
      try { console.warn(error); } catch (_) {}
    } finally {
      this.triggerPending = false;
      this._syncTriggerButtons();
    }
  }

  _bandsFromPayload() {
    const raw = this.psdPayload && this.psdPayload.band_power
      ? this.psdPayload.band_power.bands
      : null;
    if (!Array.isArray(raw) || !raw.length) return FALLBACK_BANDS;
    return raw.map((band, index) => ({
      key: String(band && band.key ? band.key : `band-${index}`),
      name: String(band && band.name ? band.name : `Band ${index + 1}`),
      symbol: String(band && band.symbol ? band.symbol : ''),
      fmin_hz: Number(band && band.fmin_hz),
      fmax_hz: Number(band && band.fmax_hz),
    }));
  }

  _renderBandLegend(bands) {
    if (!this.elLegend) return;
    const signature = bands.map((band) => `${band.key}:${band.fmin_hz}:${band.fmax_hz}`).join('|');
    if (signature === this.legendSignature) return;
    this.legendSignature = signature;
    this.elLegend.innerHTML = '';
    for (const band of bands) {
      const item = document.createElement('span');
      item.className = 'band-legend-item';
      const dot = document.createElement('span');
      dot.className = 'band-legend-dot';
      dot.style.backgroundColor = BAND_COLORS[band.key] || '#38BDF8';
      const label = document.createElement('span');
      label.textContent = `${band.name} ${formatHz(band.fmin_hz)}–${formatHz(band.fmax_hz)} Hz`;
      item.appendChild(dot);
      item.appendChild(label);
      this.elLegend.appendChild(item);
    }
  }

  _displayRange() {
    return { fmin: PSD_DISPLAY_MIN_HZ, fmax: PSD_DISPLAY_MAX_HZ };
  }

  _sourceLabel() {
    return this.scopeMode === 'channel' ? (this.activeChannel || '单通道') : '全通道平均';
  }

  _normalizeBandRow(row, bandCount) {
    if (!row || typeof row !== 'object') return null;
    const absolute = Array.isArray(row.absolute)
      ? row.absolute.slice(0, bandCount).map((value) => Math.max(0, Number(value) || 0))
      : [];
    let values = Array.isArray(row.relative_pct)
      ? row.relative_pct.slice(0, bandCount).map((value) => Math.max(0, Number(value) || 0))
      : [];
    if (values.length < bandCount && absolute.length >= bandCount) {
      const sum = absolute.reduce((total, value) => total + value, 0);
      values = absolute.map((value) => (sum > 0 ? (value * 100) / sum : 0));
    }
    if (values.length < bandCount) return null;
    const sum = values.reduce((total, value) => total + value, 0);
    if (sum > 0) values = values.map((value) => (value * 100) / sum);
    const differentialEntropy = Array.isArray(row.differential_entropy)
      ? row.differential_entropy.slice(0, bandCount).map((value) => {
        if (value === null || value === undefined) return null;
        const number = Number(value);
        return Number.isFinite(number) ? number : null;
      })
      : [];
    return {
      values,
      absolute: absolute.length >= bandCount ? absolute : new Array(bandCount).fill(null),
      differentialEntropy: differentialEntropy.length >= bandCount
        ? differentialEntropy
        : new Array(bandCount).fill(null),
      totalPower: Number.isFinite(Number(row.total)) ? Number(row.total) : null,
    };
  }

  _averageBandData(bandCount) {
    const average = this.psdPayload && this.psdPayload.average;
    if (average && average.band_power) {
      const normalized = this._normalizeBandRow(average.band_power, bandCount);
      if (normalized) return normalized;
    }

    const channels = this.psdPayload && this.psdPayload.band_power
      ? this.psdPayload.band_power.channels
      : null;
    if (!channels || typeof channels !== 'object') return null;
    const rows = this.channelNames
      .map((name) => channels[name])
      .filter((row) => row && Array.isArray(row.absolute) && row.absolute.length >= bandCount);
    if (!rows.length) return null;
    const absolute = new Array(bandCount).fill(0);
    for (const row of rows) {
      for (let i = 0; i < bandCount; i++) absolute[i] += Math.max(0, Number(row.absolute[i]) || 0);
    }
    for (let i = 0; i < bandCount; i++) absolute[i] /= rows.length;
    const total = absolute.reduce((sum, value) => sum + value, 0);
    const differentialEntropy = new Array(bandCount).fill(null);
    for (let i = 0; i < bandCount; i++) {
      const values = rows
        .map((row) => Array.isArray(row.differential_entropy) ? row.differential_entropy[i] : null)
        .filter((value) => value !== null && value !== undefined && Number.isFinite(Number(value)))
        .map(Number);
      if (values.length) {
        differentialEntropy[i] = values.reduce((sum, value) => sum + value, 0) / values.length;
      }
    }
    return this._normalizeBandRow({ absolute, differential_entropy: differentialEntropy, total }, bandCount);
  }

  _sourceBandData(bandCount) {
    if (this.scopeMode === 'average') return this._averageBandData(bandCount);
    const channels = this.psdPayload && this.psdPayload.band_power
      ? this.psdPayload.band_power.channels
      : null;
    return this._normalizeBandRow(channels ? channels[this.activeChannel] : null, bandCount);
  }

  _sourceSpectrum() {
    const payload = this.psdPayload;
    if (!payload || !Array.isArray(payload.freq_hz)) return null;
    const targetLength = payload.freq_hz.length;
    if (this.scopeMode === 'channel') {
      const values = payload.channels && payload.channels[this.activeChannel];
      return Array.isArray(values) && values.length === targetLength ? values.map(Number) : null;
    }
    const average = payload.average && payload.average.spectrum;
    if (Array.isArray(average) && average.length === targetLength) return average.map(Number);

    const rows = this.channelNames
      .map((name) => payload.channels && payload.channels[name])
      .filter((values) => Array.isArray(values) && values.length === targetLength);
    if (!rows.length) return null;
    const isDb = String(payload.unit || '').toLowerCase() === 'db';
    const result = new Array(targetLength).fill(0);
    for (let i = 0; i < targetLength; i++) {
      let sum = 0;
      for (const values of rows) {
        const value = Number(values[i]);
        sum += isDb ? 10 ** (value / 10) : value;
      }
      const mean = sum / rows.length;
      result[i] = isDb ? 10 * Math.log10(Math.max(mean, 1e-20)) : mean;
    }
    return result;
  }

  _chartTheme() {
    const isLight = this.theme === 'light';
    return {
      axis: isLight ? '#273449' : 'rgba(236, 242, 255, 0.78)',
      muted: isLight ? '#64748B' : 'rgba(196, 210, 230, 0.62)',
      split: isLight ? 'rgba(39, 52, 73, 0.11)' : 'rgba(210, 226, 248, 0.09)',
      tooltipBg: isLight ? 'rgba(255, 255, 255, 0.98)' : 'rgba(8, 13, 23, 0.97)',
      tooltipBorder: isLight ? 'rgba(39, 52, 73, 0.16)' : 'rgba(148, 184, 225, 0.22)',
      line: isLight ? '#118AB2' : '#38BDF8',
    };
  }

  _waitingOption(message) {
    const colors = this._chartTheme();
    return {
      backgroundColor: 'transparent',
      title: {
        text: message,
        left: 'center',
        top: 'middle',
        textStyle: { color: colors.muted, fontSize: 13, fontWeight: 650 },
      },
      xAxis: { show: false },
      yAxis: { show: false },
      series: [],
      animation: false,
    };
  }

  _renderWaitingCharts(message) {
    const option = this._waitingOption(message);
    if (this.spectrumChart) this.spectrumChart.setOption(option, true, false);
    if (this.bandChart) this.bandChart.setOption(option, true, false);
  }

  _renderIfReady() {
    const payload = this.psdPayload;
    if (!payload || !Array.isArray(payload.freq_hz) || !payload.freq_hz.length) {
      this._renderWaitingCharts('等待频谱数据');
      return;
    }
    const bands = this._bandsFromPayload();
    const spectrum = this._sourceSpectrum();
    const bandData = this._sourceBandData(bands.length);
    if (!spectrum || !bandData) {
      this._renderWaitingCharts('当前数据范围暂无可用数据');
      return;
    }
    this._renderBandLegend(bands);
    this._renderSpectrumChart(bands, spectrum);
    this._renderBandChart(bands, bandData);
  }

  _renderSpectrumChart(bands, spectrum) {
    if (!this.spectrumChart || !this.psdPayload) return;
    const frequencies = this.psdPayload.freq_hz;
    const source = this._sourceLabel();
    const range = this._displayRange();
    const unit = String(this.psdPayload.unit || '');
    const colors = this._chartTheme();
    const data = frequencies.map((frequency, index) => [Number(frequency), Number(spectrum[index])]);
    const markAreaData = bands.map((band) => ([
      {
        name: band.name,
        xAxis: Number(band.fmin_hz),
        itemStyle: { color: hexToRgba(BAND_COLORS[band.key] || '#38BDF8', this.theme === 'light' ? 0.12 : 0.09) },
      },
      { xAxis: Number(band.fmax_hz) },
    ]));

    this.spectrumChart.setOption({
      backgroundColor: 'transparent',
      title: { show: false },
      grid: { top: 12, right: 18, bottom: 42, left: 58, containLabel: false },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross', label: { backgroundColor: colors.axis } },
        backgroundColor: colors.tooltipBg,
        borderColor: colors.tooltipBorder,
        textStyle: { color: colors.axis },
        formatter: (params) => {
          const item = Array.isArray(params) ? params[0] : params;
          if (!item || !Array.isArray(item.value)) return '';
          return `<div class="band-tooltip-title">${escapeHtml(source)}</div><div>${Number(item.value[0]).toFixed(1)} Hz</div><strong>${Number(item.value[1]).toFixed(2)} ${escapeHtml(unit)}</strong>`;
        },
      },
      xAxis: {
        type: 'value',
        min: range.fmin,
        max: range.fmax,
        name: '频率 (Hz)',
        nameLocation: 'middle',
        nameGap: 28,
        nameTextStyle: { color: colors.axis, fontWeight: 750 },
        axisLine: { lineStyle: { color: colors.split } },
        axisTick: { show: false },
        axisLabel: { color: colors.axis },
        splitLine: { lineStyle: { color: colors.split, type: 'dashed' } },
      },
      yAxis: {
        type: unit.toLowerCase() === 'db' ? 'value' : 'log',
        scale: true,
        name: unit ? `PSD (${unit})` : 'PSD',
        nameLocation: 'middle',
        nameGap: 42,
        nameTextStyle: { color: colors.axis, fontWeight: 750 },
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: colors.axis },
        splitLine: { lineStyle: { color: colors.split, type: 'dashed' } },
      },
      series: [{
        name: source,
        type: 'line',
        data,
        showSymbol: false,
        smooth: 0.08,
        sampling: 'lttb',
        lineStyle: { width: 2, color: colors.line },
        itemStyle: { color: colors.line },
        markArea: { silent: true, label: { show: false }, data: markAreaData },
      }],
      animation: false,
    }, true, false);
  }

  _renderBandChart(bands, row) {
    if (!this.bandChart) return;
    const source = this._sourceLabel();
    const colors = this._chartTheme();
    const isDe = this.bandMetricMode === 'de';
    const metricValues = isDe ? row.differentialEntropy : row.values;
    if (!Array.isArray(metricValues)
      || metricValues.length < bands.length
      || metricValues.some((value) => (
        value === null || value === undefined || !Number.isFinite(Number(value))
      ))) {
      this.bandChart.setOption(
        this._waitingOption(isDe ? '当前数据无法计算微分熵' : '当前数据范围暂无可用数据'),
        true,
        false,
      );
      return;
    }

    let yMin = 0;
    let yMax = 100;
    if (isDe) {
      const minValue = Math.min(...metricValues);
      const maxValue = Math.max(...metricValues);
      const padding = Math.max(0.5, (maxValue - minValue) * 0.18);
      yMin = minValue < 0 ? Math.floor((minValue - padding) * 2) / 2 : 0;
      yMax = maxValue > 0 ? Math.ceil((maxValue + padding) * 2) / 2 : 0;
      if (yMax <= yMin) yMax = yMin + 1;
    } else {
      const maxValue = Math.max(0, ...metricValues);
      yMax = Math.min(100, Math.max(50, Math.ceil((maxValue * 1.25) / 10) * 10));
    }

    const categories = bands.map((band) => `${band.name}`);
    const data = bands.map((band, index) => {
      const value = Number(Number(metricValues[index]).toFixed(3));
      return {
        value,
        itemStyle: {
          color: BAND_COLORS[band.key] || '#38BDF8',
          borderRadius: value >= 0 ? [7, 7, 2, 2] : [2, 2, 7, 7],
        },
        label: isDe ? { position: value >= 0 ? 'top' : 'bottom' } : undefined,
      };
    });

    this.bandChart.setOption({
      backgroundColor: 'transparent',
      title: { show: false },
      grid: { top: 28, right: 18, bottom: 42, left: 54, containLabel: false },
      tooltip: {
        trigger: 'item',
        backgroundColor: colors.tooltipBg,
        borderColor: colors.tooltipBorder,
        textStyle: { color: colors.axis },
        formatter: (item) => {
          const band = bands[item.dataIndex];
          const absolute = row.absolute[item.dataIndex];
          const power = absolute === null ? '' : `<div>功率 ${formatPower(absolute)} μV²</div>`;
          const metric = isDe
            ? `<strong>DE ${Number(item.value).toFixed(3)} nat</strong>`
            : `<strong>${Number(item.value).toFixed(1)}%</strong>`;
          return `<div class="band-tooltip-title">${escapeHtml(source)} · ${escapeHtml(band.name)}</div><div>${formatHz(band.fmin_hz)}–${formatHz(band.fmax_hz)} Hz</div>${power}${metric}`;
        },
      },
      xAxis: {
        type: 'category',
        data: categories,
        axisLine: { lineStyle: { color: colors.split } },
        axisTick: { show: false },
        axisLabel: { color: colors.axis, fontWeight: 750, interval: 0, margin: 13 },
      },
      yAxis: {
        type: 'value',
        min: yMin,
        max: yMax,
        name: isDe ? '微分熵 (nat)' : '相对功率 (%)',
        nameLocation: 'middle',
        nameGap: 38,
        nameTextStyle: { color: colors.axis, fontWeight: 750 },
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: colors.axis, formatter: isDe ? '{value}' : '{value}%' },
        splitLine: { lineStyle: { color: colors.split, type: 'dashed' } },
      },
      series: [{
        name: source,
        type: 'bar',
        data,
        barMaxWidth: 68,
        label: {
          show: true,
          position: 'top',
          color: colors.axis,
          fontWeight: 800,
          formatter: (item) => isDe
            ? Number(item.value).toFixed(2)
            : `${Number(item.value).toFixed(1)}%`,
        },
      }],
      animation: true,
      animationDuration: 220,
      animationDurationUpdate: 320,
      animationEasingUpdate: 'cubicOut',
    }, true, false);
  }
}
