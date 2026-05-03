#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 加载并校验 configs/config.yaml，生成强类型配置对象（dataclass）

修改日志:
- 2026-04-30: 1.0.0 创建文件
- 2026-05-02: 1.1.0 增加设备与模式页面流，拆分脚本入口
- 2026-05-02: 1.1.1 增加 LSL 解析超时与重试配置，提升波形推流稳定性
- 2026-05-03: 1.1.2 增加离线存储与导出配置（offlinedata/滤波默认值）
- 2026-05-03: 1.1.3 增加信号预处理配置（50Hz 陷波参数）
- 2026-05-03: 1.1.4 增加 WebSocket 广播队列配置，避免停采集时发送积压
- 2026-05-03: 1.1.5 增加 UI 波形显示配置（时间窗/刷新率/降采样上限）
- 2026-05-03: 1.1.6 配置命名区分“后端转发频率”和“前端渲染频率”
- 2026-05-03: 1.1.7 支持本机覆盖配置与通道预设（10-20通道列表/常用组合/通道模式）
- 2026-05-03: 1.1.8 增加参考电极候选配置（供 UI 下拉选择）
- 2026-05-03: 1.1.9 通道预设增加参考电极字段（ref_channel_name）

作者: Spoon
版本: 1.1.9
"""

import os
from dataclasses import dataclass
from typing import Any, Dict, List

import yaml

from configs.local_overrides import deep_merge_dict, get_local_override_path, load_yaml_file


@dataclass(frozen=True)
class BluetoothGattConfig:
    notify_char_handle: int
    write_char_handle: int


@dataclass(frozen=True)
class BluetoothCommandConfig:
    init_commands: List[List[int]]
    start_eeg: List[int]
    stop_eeg: List[int]
    start_impedance: List[int]
    stop_impedance: List[int]
    start_tdcs: List[int]
    stop_tdcs: List[int]


@dataclass(frozen=True)
class BluetoothScanConfig:
    max_retries: int
    retry_interval_sec: float


@dataclass(frozen=True)
class BluetoothConfig:
    device_names: List[str]
    target_device: str
    mac_address: str
    scan: BluetoothScanConfig
    gatt: BluetoothGattConfig
    commands: BluetoothCommandConfig


@dataclass(frozen=True)
class LslConfig:
    stream_name: str
    stream_type: str
    include_trigger_channel: bool


@dataclass(frozen=True)
class ChannelPresetConfig:
    name: str
    mode_channels: int
    channel_names: List[str]
    ref_channel_name: str


@dataclass(frozen=True)
class EegConfig:
    mode_channels: int
    sampling_rate_hz: int
    channel_names: List[str]
    ref_channel_name: str
    ref_selectable_channels: List[str]
    lsl: LslConfig
    supported_channel_modes: List[int]
    montage_1020_channels: List[str]
    presets: List[ChannelPresetConfig]


@dataclass(frozen=True)
class FrameProtocolConfig:
    header_len_bytes: int
    bytes_per_sample_per_channel: int
    samples_per_frame: int
    trigger_len_bytes: int
    imu_len_bytes: int
    battery_len_bytes: int
    tail_len_bytes: int


@dataclass(frozen=True)
class ProtocolConfig:
    frame: FrameProtocolConfig


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int


@dataclass(frozen=True)
class StreamingConfig:
    ws_send_fps_hz: int
    buffer_size: int
    lsl_resolve_timeout_sec: float
    lsl_resolve_retry_interval_sec: float
    ws_queue_max_chunks: int
    ws_send_timeout_sec: float


@dataclass(frozen=True)
class DebugConfig:
    ui_enabled: bool
    max_events: int


@dataclass(frozen=True)
class NotchConfig:
    freq_hz: float
    quality_factor: float


@dataclass(frozen=True)
class SignalConfig:
    notch: NotchConfig


@dataclass(frozen=True)
class OfflineExportConfig:
    physical_unit: str
    uv_per_count: float
    trigger_label: str


@dataclass(frozen=True)
class OfflineFilterConfig:
    order: int
    lowcut_hz_default: float
    highcut_hz_default: float


@dataclass(frozen=True)
class OfflineConfig:
    root_dir: str
    export: OfflineExportConfig
    filter: OfflineFilterConfig


@dataclass(frozen=True)
class WaveformUiConfig:
    time_window_sec: float
    render_fps_hz: int
    max_render_points_per_channel: int
    global_scale: bool


@dataclass(frozen=True)
class UiConfig:
    waveform: WaveformUiConfig


@dataclass(frozen=True)
class AppConfig:
    app_ui_version: str
    ui: UiConfig
    bluetooth: BluetoothConfig
    eeg: EegConfig
    protocol: ProtocolConfig
    server: ServerConfig
    streaming: StreamingConfig
    debug: DebugConfig
    signal: SignalConfig
    offline: OfflineConfig


def load_config(config_path: str) -> AppConfig:
    """
    加载 configs/config.yaml，生成强类型配置对象。

    注意：
        当前重构后的项目不再依赖任何旧版 ini 文件（如 BHBconfig.ini），保持单一配置入口。
    """
    with open(config_path, "r", encoding="utf-8") as f:
        raw: Dict[str, Any] = yaml.safe_load(f) or {}
    override_path = get_local_override_path(config_path)
    override_raw = load_yaml_file(override_path)
    if override_raw:
        raw = deep_merge_dict(raw, override_raw)

    bluetooth_raw = raw.get("bluetooth", {})
    scan_raw = bluetooth_raw.get("scan", {})
    gatt_raw = bluetooth_raw.get("gatt", {})
    cmd_raw = bluetooth_raw.get("commands", {}) or {}

    eeg_raw = raw.get("eeg", {})
    lsl_raw = eeg_raw.get("lsl", {})

    protocol_raw = raw.get("protocol", {})
    frame_raw = protocol_raw.get("frame", {})

    server_raw = raw.get("server", {})
    streaming_raw = raw.get("streaming", {})
    debug_raw = raw.get("debug", {})
    signal_raw = raw.get("signal", {}) or {}
    offline_raw = raw.get("offline", {}) or {}
    app_raw = raw.get("app", {}) or {}
    ui_raw = raw.get("ui", {}) or {}
    waveform_ui_raw = ui_raw.get("waveform", {}) or {}
    app_ui_version = str(app_raw.get("ui_version") or app_raw.get("version") or "1.0.0").strip() or "1.0.0"

    mode_channels = int(eeg_raw.get("mode_channels", 8))
    channel_names_cfg = list(eeg_raw.get("channel_names", []) or [])
    ref_channel_cfg = str(eeg_raw.get("ref_channel_name", "") or "")
    ref_selectable_raw = eeg_raw.get("ref_selectable_channels", eeg_raw.get("ref_candidates", None))
    ref_selectable: List[str] = []
    if isinstance(ref_selectable_raw, list):
        for v in ref_selectable_raw:
            s = str(v or "").strip()
            if not s:
                continue
            if s not in ref_selectable:
                ref_selectable.append(s)
    if not ref_selectable:
        ref_selectable = ["Fz", "Cz", "Pz"]
    supported_modes_raw = eeg_raw.get("supported_channel_modes", []) or []
    supported_modes: List[int] = []
    if isinstance(supported_modes_raw, list):
        for v in supported_modes_raw:
            try:
                iv = int(v)
            except Exception:
                continue
            if iv <= 0:
                continue
            if iv not in supported_modes:
                supported_modes.append(iv)
    if not supported_modes:
        supported_modes = [mode_channels]
    if mode_channels not in supported_modes:
        supported_modes.append(mode_channels)
    supported_modes.sort()

    montage_channels_raw = eeg_raw.get("montage_1020_channels", []) or []
    montage_channels: List[str] = []
    if isinstance(montage_channels_raw, list):
        for v in montage_channels_raw:
            s = str(v or "").strip()
            if not s:
                continue
            if s not in montage_channels:
                montage_channels.append(s)

    presets_raw = eeg_raw.get("presets", []) or []
    presets: List[ChannelPresetConfig] = []
    if isinstance(presets_raw, list):
        for item in presets_raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "") or "").strip()
            if not name:
                continue
            try:
                p_mode = int(item.get("mode_channels", 0))
            except Exception:
                p_mode = 0
            p_names_raw = item.get("channel_names", []) or []
            p_names: List[str] = []
            if isinstance(p_names_raw, list):
                for x in p_names_raw:
                    xs = str(x or "").strip()
                    if xs:
                        p_names.append(xs)
            if p_mode <= 0 or not p_names:
                continue
            p_ref = str(item.get("ref_channel_name", "") or "").strip()
            if not p_ref:
                p_ref = str(ref_channel_cfg or "").strip() or "Pz"
            presets.append(ChannelPresetConfig(name=name, mode_channels=p_mode, channel_names=p_names, ref_channel_name=p_ref))

    device_names_cfg = list(bluetooth_raw.get("device_names", []) or [])

    sampling_rate_hz = int(eeg_raw.get("sampling_rate_hz", 250))
    ws_send_fps_hz = int(streaming_raw.get("ws_send_fps_hz", streaming_raw.get("update_fps", 25)))
    buffer_size = int(streaming_raw.get("buffer_size", 0))
    if buffer_size <= 0:
        buffer_size = max(1, int(round(sampling_rate_hz / max(1, ws_send_fps_hz))))

    lsl_resolve_timeout_sec = float(streaming_raw.get("lsl_resolve_timeout_sec", 1.0))
    lsl_resolve_retry_interval_sec = float(streaming_raw.get("lsl_resolve_retry_interval_sec", 0.5))
    if lsl_resolve_timeout_sec < 0.05:
        lsl_resolve_timeout_sec = 0.05
    if lsl_resolve_retry_interval_sec < 0.05:
        lsl_resolve_retry_interval_sec = 0.05
    ws_queue_max_chunks = int(streaming_raw.get("ws_queue_max_chunks", 5))
    if ws_queue_max_chunks < 1:
        ws_queue_max_chunks = 1
    if ws_queue_max_chunks > 100:
        ws_queue_max_chunks = 100
    ws_send_timeout_sec = float(streaming_raw.get("ws_send_timeout_sec", 0.5))
    if ws_send_timeout_sec < 0.05:
        ws_send_timeout_sec = 0.05
    if ws_send_timeout_sec > 5.0:
        ws_send_timeout_sec = 5.0

    time_window_sec = float(waveform_ui_raw.get("time_window_sec", 2.0))
    if time_window_sec < 0.2:
        time_window_sec = 0.2
    if time_window_sec > 30.0:
        time_window_sec = 30.0
    render_fps_hz = int(waveform_ui_raw.get("render_fps_hz", waveform_ui_raw.get("render_fps", 25)))
    if render_fps_hz < 5:
        render_fps_hz = 5
    if render_fps_hz > 60:
        render_fps_hz = 60
    max_render_points_per_channel = int(waveform_ui_raw.get("max_render_points_per_channel", 800))
    if max_render_points_per_channel < 50:
        max_render_points_per_channel = 50
    if max_render_points_per_channel > 5000:
        max_render_points_per_channel = 5000
    global_scale = bool(waveform_ui_raw.get("global_scale", True))

    def _as_u8_list(items: Any) -> List[int]:
        if not isinstance(items, list):
            raise ValueError("commands must be a list")
        out: List[int] = []
        for v in items:
            iv = int(v)
            if iv < 0 or iv > 255:
                raise ValueError("command byte must be in [0, 255]")
            out.append(iv)
        return out

    def _as_u8_list_list(items: Any) -> List[List[int]]:
        if items is None:
            return []
        if not isinstance(items, list):
            raise ValueError("init_commands must be a list of list")
        out: List[List[int]] = []
        for one in items:
            out.append(_as_u8_list(one))
        return out

    init_commands_cfg = _as_u8_list_list(cmd_raw.get("init", []))
    start_eeg_cfg = _as_u8_list(cmd_raw.get("start_eeg") or cmd_raw.get("start_stream") or [0x02, 0x01])
    stop_eeg_cfg = _as_u8_list(cmd_raw.get("stop_eeg") or cmd_raw.get("stop_stream") or [0x02, 0x02])
    start_impedance_cfg = _as_u8_list(cmd_raw.get("start_impedance", [0x03, 0x01]))
    stop_impedance_cfg = _as_u8_list(cmd_raw.get("stop_impedance", [0x03, 0x02]))
    start_tdcs_cfg = _as_u8_list(cmd_raw.get("start_tdcs", [0x07, 0x01]))
    stop_tdcs_cfg = _as_u8_list(cmd_raw.get("stop_tdcs", [0x07, 0x02]))

    bluetooth = BluetoothConfig(
        device_names=device_names_cfg,
        target_device=str(bluetooth_raw.get("target_device", "")),
        mac_address=str(bluetooth_raw.get("mac_address", "")),
        scan=BluetoothScanConfig(
            max_retries=int(scan_raw.get("max_retries", 10)),
            retry_interval_sec=float(scan_raw.get("retry_interval_sec", 1.0)),
        ),
        gatt=BluetoothGattConfig(
            notify_char_handle=int(gatt_raw.get("notify_char_handle", 5)),
            write_char_handle=int(gatt_raw.get("write_char_handle", 8)),
        ),
        commands=BluetoothCommandConfig(
            init_commands=init_commands_cfg,
            start_eeg=start_eeg_cfg,
            stop_eeg=stop_eeg_cfg,
            start_impedance=start_impedance_cfg,
            stop_impedance=stop_impedance_cfg,
            start_tdcs=start_tdcs_cfg,
            stop_tdcs=stop_tdcs_cfg,
        ),
    )

    eeg = EegConfig(
        mode_channels=mode_channels,
        sampling_rate_hz=sampling_rate_hz,
        channel_names=channel_names_cfg,
        ref_channel_name=ref_channel_cfg,
        ref_selectable_channels=ref_selectable,
        lsl=LslConfig(
            stream_name=str(lsl_raw.get("stream_name", "BHB-EEG")),
            stream_type=str(lsl_raw.get("stream_type", "EEG")),
            include_trigger_channel=bool(lsl_raw.get("include_trigger_channel", True)),
        ),
        supported_channel_modes=supported_modes,
        montage_1020_channels=montage_channels,
        presets=presets,
    )

    protocol = ProtocolConfig(
        frame=FrameProtocolConfig(
            header_len_bytes=int(frame_raw.get("header_len_bytes", 3)),
            bytes_per_sample_per_channel=int(frame_raw.get("bytes_per_sample_per_channel", 3)),
            samples_per_frame=int(frame_raw.get("samples_per_frame", 5)),
            trigger_len_bytes=int(frame_raw.get("trigger_len_bytes", 1)),
            imu_len_bytes=int(frame_raw.get("imu_len_bytes", 12)),
            battery_len_bytes=int(frame_raw.get("battery_len_bytes", 2)),
            tail_len_bytes=int(frame_raw.get("tail_len_bytes", 2)),
        )
    )

    server = ServerConfig(
        host=str(server_raw.get("host", "127.0.0.1")),
        port=int(server_raw.get("port", 8000)),
    )

    streaming = StreamingConfig(
        ws_send_fps_hz=ws_send_fps_hz,
        buffer_size=buffer_size,
        lsl_resolve_timeout_sec=lsl_resolve_timeout_sec,
        lsl_resolve_retry_interval_sec=lsl_resolve_retry_interval_sec,
        ws_queue_max_chunks=ws_queue_max_chunks,
        ws_send_timeout_sec=ws_send_timeout_sec,
    )

    debug = DebugConfig(
        ui_enabled=bool(debug_raw.get("ui_enabled", True)),
        max_events=int(debug_raw.get("max_events", 500)),
    )

    notch_raw = signal_raw.get("notch", {}) or {}
    notch_freq_hz = float(notch_raw.get("freq_hz", 50.0))
    notch_q = float(notch_raw.get("quality_factor", 30.0))
    if notch_freq_hz <= 0:
        notch_freq_hz = 50.0
    if notch_q <= 0:
        notch_q = 30.0
    signal = SignalConfig(
        notch=NotchConfig(freq_hz=notch_freq_hz, quality_factor=notch_q),
    )

    export_raw = offline_raw.get("export", {}) or {}
    filter_raw = offline_raw.get("filter", {}) or {}
    offline = OfflineConfig(
        root_dir=str(offline_raw.get("root_dir", "offlinedata") or "offlinedata"),
        export=OfflineExportConfig(
            physical_unit=str(export_raw.get("physical_unit", "uV") or "uV"),
            uv_per_count=float(export_raw.get("uv_per_count", 0.0833)),
            trigger_label=str(export_raw.get("trigger_label", "TRIG") or "TRIG"),
        ),
        filter=OfflineFilterConfig(
            order=max(1, int(filter_raw.get("order", 5))),
            lowcut_hz_default=float(filter_raw.get("lowcut_hz_default", 3.0)),
            highcut_hz_default=float(filter_raw.get("highcut_hz_default", 50.0)),
        ),
    )

    ui = UiConfig(
        waveform=WaveformUiConfig(
            time_window_sec=time_window_sec,
            render_fps_hz=render_fps_hz,
            max_render_points_per_channel=max_render_points_per_channel,
            global_scale=global_scale,
        )
    )

    return AppConfig(
        app_ui_version=app_ui_version,
        ui=ui,
        bluetooth=bluetooth,
        eeg=eeg,
        protocol=protocol,
        server=server,
        streaming=streaming,
        debug=debug,
        signal=signal,
        offline=offline,
    )
