/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 前端控制与渲染逻辑（WebSocket 实时接收 EEG 数据、调用后端 API、使用 ECharts 绘制波形）

修改日志:
- 2026-04-30: 1.0.0 创建文件
- 2026-05-04: 1.0.1 连接状态与日志文案去括号/去英文，设备名去尾部括号后缀
- 2026-05-04: 1.0.2 配置字段更名：mode_channels -> n_channels（与三模式命名一致）

作者: Spoon
版本: 1.0.2
*/

const WS_URL = `ws://${window.location.host}/ws/eeg`;
const WS_DEBUG_URL = `ws://${window.location.host}/ws/debug`;
const API_START = `/api/start`;
const API_STOP = `/api/stop`;
const API_CONFIG = `/api/config`;
const API_STATUS = `/api/status`;
const API_DEBUG_EVENTS = `/api/debug/events`;

// 全局状态
let ws = null;
let charts = [];
let chartData = [];
let channels = 8;
let channelNames = [];
let maxPoints = 500;
let pingTimer = null;
let updateRequested = false;
let statusPollTimer = null;
let configuredDeviceName = "";
let connectAttempt = false;
let connectAttemptTs = 0;

let globalYMin = Infinity;
let globalYMax = -Infinity;

function stripTrailingParenSuffix(text) {
    let s = String(text || '').trim();
    for (let i = 0; i < 3; i++) {
        const next = s.replace(/\s*[\(\（][^()\（\）]{0,64}[\)\）]\s*$/g, '').trim();
        if (next === s) break;
        s = next;
    }
    return s;
}

function normalizeDeviceName(name) {
    const raw = String(name || '').trim();
    const cleaned = stripTrailingParenSuffix(raw);
    return cleaned || raw || "未知设备";
}

function normalizeDeviceMessage(msg) {
    const raw = stripTrailingParenSuffix(String(msg || '').trim());
    if (!raw) return "";
    const lower = raw.toLowerCase();
    if (lower === "not connected" || lower === "not_connected") return "未连接";
    const replaced = raw
        .replace(/not connected/ig, "未连接")
        .replace(/timeout/ig, "超时")
        .replace(/disconnected/ig, "已断开");
    if (/[a-zA-Z]/.test(replaced)) return "";
    return replaced;
}

// DOM 元素
const btnStart = document.getElementById('btn-start');
const btnStop = document.getElementById('btn-stop');
const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');
const chartsGrid = document.getElementById('charts-grid');
const debugLog = document.getElementById('debug-log');
const debugFilter = document.getElementById('debug-filter');
const debugClear = document.getElementById('debug-clear');

let debugWs = null;
let debugLines = [];
let debugFilterText = "";

// 初始化图表网格
function initCharts() {
    chartsGrid.innerHTML = '';
    charts = [];
    chartData = Array.from({ length: channels }, () => []);

    for (let i = 0; i < channels; i++) {
        // 创建容器
        const container = document.createElement('div');
        container.className = 'chart-container';
        
        const title = document.createElement('div');
        title.className = 'chart-title';
        title.innerText = channelNames[i] ? `${channelNames[i]}` : `通道 ${i + 1}`;
        container.appendChild(title);
        
        const chartDiv = document.createElement('div');
        chartDiv.className = 'echarts-instance';
        chartDiv.id = `chart-ch${i}`;
        container.appendChild(chartDiv);
        
        chartsGrid.appendChild(container);
        
        // 初始化 ECharts
        const chart = echarts.init(chartDiv, 'dark', { renderer: 'canvas' });
        const option = {
            backgroundColor: 'transparent',
            grid: {
                top: 20,
                bottom: 10,
                left: 60,
                right: 10
            },
            xAxis: {
                type: 'value',
                show: false,
                boundaryGap: false,
                min: 'dataMin',
                max: 'dataMax'
            },
            yAxis: {
                type: 'value',
                scale: true, // 允许自适应范围
                axisLabel: {
                    formatter: function (value) {
                        const v = Number(value);
                        if (!Number.isFinite(v)) {
                            return '';
                        }
                        if (Math.abs(v) > 1001) {
                            return v.toExponential(0);
                        }
                        return v.toFixed(0);
                    }
                },
                splitLine: {
                    lineStyle: {
                        color: '#30363d',
                        type: 'dashed'
                    }
                }
            },
            series: [{
                type: 'line',
                showSymbol: false,
                hoverAnimation: false,
                data: [],
                lineStyle: {
                    color: '#58a6ff',
                    width: 1.5
                }
            }],
            animation: false // 关闭动画，优化高频渲染性能
        };
        chart.setOption(option);
        charts.push(chart);
    }
}

// 建立 WebSocket 连接
function connectWebSocket() {
    ws = new WebSocket(WS_URL);
    if (pingTimer) {
        clearInterval(pingTimer);
        pingTimer = null;
    }
    
    ws.onopen = () => {
        console.log("WebSocket 已连接。");
        pingTimer = setInterval(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send("ping");
            }
        }, 10000);
    };
    
    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === "eeg_data") {
            handleEEGData(msg.data);
        }
    };
    
    ws.onclose = () => {
        console.log("WebSocket 已断开。");
        if (pingTimer) {
            clearInterval(pingTimer);
            pingTimer = null;
        }
        setTimeout(connectWebSocket, 3000); // 断线重连
    };
    
    ws.onerror = (err) => {
        console.error("WebSocket 发生错误：", err);
    };

}

function setDeviceIndicator(mode, text) {
    statusDot.classList.remove('active');
    statusDot.classList.remove('error');
    if (mode === 'active') {
        statusDot.classList.add('active');
    } else if (mode === 'error') {
        statusDot.classList.add('error');
    }
    if (typeof text === 'string' && text.length > 0) {
        statusText.innerText = text;
    }
}

function applyDeviceStatus(deviceStatus) {
    const st = (deviceStatus && deviceStatus.last) ? deviceStatus.last : null;
    const configured = (deviceStatus && deviceStatus.configured_name) ? String(deviceStatus.configured_name) : "";
    if (!configuredDeviceName && configured) {
        configuredDeviceName = configured;
    }
    const name = normalizeDeviceName(st && st.name ? String(st.name) : (configuredDeviceName || "未知设备"));
    const t = st && st.type ? String(st.type) : "idle";
    const msg = normalizeDeviceMessage(st && st.message ? String(st.message) : "");

    if (t === "connected") {
        connectAttempt = false;
        setDeviceIndicator("active", `已连接：${name}`);
        btnStop.disabled = false;
        btnStart.disabled = true;
        return;
    }
    if (t === "connecting") {
        setDeviceIndicator("", `连接中：${name}`);
        return;
    }
    if (t === "error") {
        connectAttempt = false;
        const suffix = msg ? `：${msg}` : "";
        setDeviceIndicator("error", `连接失败：${name}${suffix}`);
        btnStart.disabled = false;
        btnStop.disabled = true;
        return;
    }
    if (t === "stopped") {
        const elapsed = Date.now() - connectAttemptTs;
        if (connectAttempt && elapsed > 3000) {
            const suffix = msg ? `：${msg}` : "";
            setDeviceIndicator("error", `连接失败：${name}${suffix}`);
        } else {
            setDeviceIndicator("", configuredDeviceName ? `设备未连接，期望：${configuredDeviceName}` : "设备未连接");
        }
        btnStart.disabled = false;
        btnStop.disabled = true;
        return;
    }
    const elapsed = Date.now() - connectAttemptTs;
    if (connectAttempt && elapsed > 3000) {
        const suffix = msg ? `：${msg}` : "";
        setDeviceIndicator("error", `连接失败：${name}${suffix}`);
        btnStart.disabled = false;
        btnStop.disabled = true;
        return;
    }
    setDeviceIndicator("", configuredDeviceName ? `设备未连接，期望：${configuredDeviceName}` : "设备未连接");
}

async function refreshStatusOnce() {
    try {
        const res = await fetch(API_STATUS);
        const data = await res.json();
        if (data && data.device) {
            applyDeviceStatus(data.device);
        }
    } catch (_) {}
}

function startStatusPolling() {
    if (statusPollTimer) {
        clearInterval(statusPollTimer);
        statusPollTimer = null;
    }
    refreshStatusOnce();
    statusPollTimer = setInterval(refreshStatusOnce, 1000);
}

function formatLocalTsSeconds(tsSeconds) {
    const t = Number(tsSeconds);
    const dt = new Date((Number.isFinite(t) ? t : Date.now() / 1000) * 1000);
    const pad2 = (n) => String(n).padStart(2, '0');
    const pad3 = (n) => String(n).padStart(3, '0');
    const y = dt.getFullYear();
    const mo = pad2(dt.getMonth() + 1);
    const d = pad2(dt.getDate());
    const h = pad2(dt.getHours());
    const mi = pad2(dt.getMinutes());
    const s = pad2(dt.getSeconds());
    const ms = pad3(dt.getMilliseconds());
    return `${y}-${mo}-${d} ${h}:${mi}:${s}.${ms}`;
}

function formatDebugEvent(ev) {
    const ts = formatLocalTsSeconds(ev.ts);
    const tag = String(ev.tag || "DEBUG");
    const msg = ev.message || "";
    let dataStr = "";
    if (ev.data && Object.keys(ev.data).length > 0) {
        dataStr = JSON.stringify(ev.data);
    }
    const tagWidth = 12;
    const tagPadded = tag.length >= tagWidth ? tag.slice(0, tagWidth) : tag.padEnd(tagWidth, ' ');
    return `${ts}\t[${tagPadded}]\t${msg}\t${dataStr}`;
}

function renderDebug() {
    if (!debugLog) return;
    const f = (debugFilterText || "").trim().toLowerCase();
    const out = f ? debugLines.filter(l => l.toLowerCase().includes(f)) : debugLines;
    debugLog.textContent = out.join("\n");
    debugLog.scrollTop = debugLog.scrollHeight;
}

async function bootstrapDebug() {
    if (!debugLog) return;

    if (debugClear) {
        debugClear.addEventListener("click", () => {
            debugLines = [];
            renderDebug();
        });
    }
    if (debugFilter) {
        debugFilter.addEventListener("input", (e) => {
            debugFilterText = e.target.value || "";
            renderDebug();
        });
    }

    try {
        const res = await fetch(API_DEBUG_EVENTS);
        const data = await res.json();
        if (data.enabled && Array.isArray(data.events)) {
            for (const ev of data.events) {
                debugLines.push(formatDebugEvent(ev));
            }
            renderDebug();
        }
    } catch (_) {}

    connectDebugWs();
}

function connectDebugWs() {
    if (!debugLog) return;
    debugWs = new WebSocket(WS_DEBUG_URL);
    debugWs.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === "debug_init" && Array.isArray(msg.events)) {
                for (const ev of msg.events) {
                    debugLines.push(formatDebugEvent(ev));
                }
                if (debugLines.length > 2000) {
                    debugLines = debugLines.slice(-2000);
                }
                renderDebug();
                return;
            }
            if (msg.type === "debug_event" && msg.event) {
                debugLines.push(formatDebugEvent(msg.event));
                if (debugLines.length > 2000) {
                    debugLines = debugLines.slice(-2000);
                }
                renderDebug();
            }
        } catch (_) {}
    };
    debugWs.onclose = () => {
        setTimeout(connectDebugWs, 1000);
    };
}

// 处理后端传来的脑电数据 (Chunk)
function handleEEGData(chunk) {
    // chunk: [ [ch1, ch2, ..., chN, trigger?], [...], ... ]
    let currentChunkMin = Infinity;
    let currentChunkMax = -Infinity;

    for (let sample of chunk) {
        if (!Array.isArray(sample) || sample.length < channels) {
            continue;
        }
        for (let i = 0; i < channels; i++) {
            // ECharts 如果是 value 轴，data 最好是 [x, y] 格式
            // 我们以数组长度为 x，或者简单地自增
            let lastX = chartData[i].length > 0 ? chartData[i][chartData[i].length - 1][0] : 0;
            const y = Number(sample[i]);
            if (Number.isNaN(y)) {
                continue;
            }
            
            if (y < currentChunkMin) currentChunkMin = y;
            if (y > currentChunkMax) currentChunkMax = y;

            chartData[i].push([lastX + 1, y]);
            if (chartData[i].length > maxPoints) {
                chartData[i].shift(); // 维持最大点数
            }
        }
    }
    
    if (currentChunkMin < Infinity && currentChunkMax > -Infinity) {
        const margin = (currentChunkMax - currentChunkMin) * 0.1;
        const targetMin = currentChunkMin - margin;
        const targetMax = currentChunkMax + margin;
        
        if (globalYMin === Infinity) {
            globalYMin = targetMin;
            globalYMax = targetMax;
        } else {
            globalYMin = globalYMin * 0.9 + targetMin * 0.1;
            globalYMax = globalYMax * 0.9 + targetMax * 0.1;
        }
    }

    if (!updateRequested) {
        updateRequested = true;
        requestAnimationFrame(updateCharts);
    }
}

// 批量更新图表
function updateCharts() {
    updateRequested = false;
    
    const yAxisMin = globalYMin === Infinity ? null : Math.floor(globalYMin);
    const yAxisMax = globalYMax === -Infinity ? null : Math.ceil(globalYMax);

    for (let i = 0; i < channels; i++) {
        charts[i].setOption({
            yAxis: {
                min: yAxisMin,
                max: yAxisMax
            },
            series: [{
                data: chartData[i]
            }]
        }, false, false);
    }
}

// 绑定按钮事件
btnStart.addEventListener('click', async () => {
    btnStart.disabled = true;
    connectAttempt = true;
    connectAttemptTs = Date.now();
    setDeviceIndicator("", `连接中：${configuredDeviceName || "未知设备"}`);
    try {
        const res = await fetch(API_START);
        const data = await res.json();
        console.log("开始采集响应：", data);
        if (data.status === "success") {
            btnStop.disabled = false;
            if (data.device) {
                applyDeviceStatus(data.device);
            } else {
                refreshStatusOnce();
            }
        } else {
            alert(data.message);
            if (data.device) {
                applyDeviceStatus(data.device);
            } else {
                setDeviceIndicator("error", `连接失败：${configuredDeviceName || "未知设备"}（${data.message || "启动失败"}）`);
                btnStart.disabled = false;
                btnStop.disabled = true;
            }
        }
    } catch (e) {
        console.error(e);
        setDeviceIndicator("error", `连接失败：${configuredDeviceName || "未知设备"}（请求失败）`);
        btnStart.disabled = false;
        btnStop.disabled = true;
        alert("调用开始采集接口失败");
    }
});

btnStop.addEventListener('click', async () => {
    btnStop.disabled = true;
    connectAttempt = false;
    try {
        const res = await fetch(API_STOP);
        const data = await res.json();
        console.log("停止采集响应：", data);
        if (data.status === "success") {
            btnStart.disabled = false;
            if (data.device) {
                applyDeviceStatus(data.device);
            } else {
                refreshStatusOnce();
            }
        } else {
            alert(data.message);
            btnStop.disabled = false;
            refreshStatusOnce();
        }
    } catch (e) {
        console.error(e);
        btnStop.disabled = false;
        alert("调用停止采集接口失败");
    }
});

// 窗口大小调整时自动 resize
window.addEventListener('resize', () => {
    charts.forEach(chart => chart.resize());
});

async function loadConfig() {
    const res = await fetch(API_CONFIG);
    const cfg = await res.json();
    channels = cfg.n_channels || 8;
    channelNames = Array.isArray(cfg.channel_names) ? cfg.channel_names : [];
    const samplingRate = cfg.sampling_rate_hz || 250;
    maxPoints = Math.max(50, Math.floor(samplingRate * 2));
}

async function init() {
    try {
        await loadConfig();
        initCharts();
        connectWebSocket();
        bootstrapDebug();
        startStatusPolling();
    } catch (e) {
        console.error(e);
        initCharts();
        connectWebSocket();
        bootstrapDebug();
        startStatusPolling();
    }
}

init();
