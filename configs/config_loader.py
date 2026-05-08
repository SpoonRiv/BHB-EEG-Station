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
- 2026-05-04: 1.1.10 增加阻抗检测配置（协议/LSL/UI阈值）
- 2026-05-04: 1.1.11 调整阻抗默认刷新频率与 buffer_size（更低频）
- 2026-05-04: 1.1.12 阻抗阈值默认改为 5000/20000，并增加阈值滑条上限配置
- 2026-05-04: 1.1.13 阻抗阈值滑条步进改为可配置（slider_step_ohm）
- 2026-05-04: 1.1.14 阻抗阈值滑条默认上限调整为 25000
- 2026-05-04: 1.1.15 增加电刺激（tDCS）配置段占位（enabled/ui）
- 2026-05-04: 1.1.16 统一三模式命名（eeg/impedance/tdcs），并显式区分 8/16 通道配置字段
- 2026-05-07: 1.1.17 增加前端 WS 待处理上限与离线写入队列上限配置，降低长时间运行卡顿风险
- 2026-05-08: 1.1.18 增加动态 y 轴分档与更新频率配置，并下调默认渲染/转发频率以降低长时间渲染压力

作者: Spoon
版本: 1.1.18
"""

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

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
    n_channels: int
    channel_names: List[str]
    ref_channel_name: str


@dataclass(frozen=True)
class EegConfig:
    n_channels: int
    sampling_rate_hz: int
    channel_names: List[str]
    ref_channel_name: str
    ref_selectable_channels: List[str]
    lsl: LslConfig
    supported_channel_modes: List[int]
    montage_1020_channels: List[str]
    presets: List[ChannelPresetConfig]
    protocol: "EegProtocolConfig"


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
class EegProtocolVariantConfig:
    frame: FrameProtocolConfig


@dataclass(frozen=True)
class EegProtocolConfig:
    """
    EEG 帧协议配置（按通道模式区分）。

    Attributes:
        ch8: 8 通道协议
        ch16: 16 通道协议（可选；当 eeg.n_channels=16 时必须提供）
    """

    ch8: EegProtocolVariantConfig
    ch16: Optional[EegProtocolVariantConfig]


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
    writer_queue_max_chunks: int
    writer_queue_full_policy: str


@dataclass(frozen=True)
class WaveformUiConfig:
    time_window_sec: float
    render_fps_hz: int
    max_render_points_per_channel: int
    global_scale: bool
    max_pending_ws_chunks: int
    y_axis_step: float
    y_axis_update_hz: float


@dataclass(frozen=True)
class UiConfig:
    waveform: WaveformUiConfig


@dataclass(frozen=True)
class ImpedanceFrameConfig:
    header: List[int]
    frame_len_bytes_ch8: int
    frame_len_bytes_ch16: int
    include_bias: bool
    include_tdcs_if_ch8: bool
    gain_scale: float


@dataclass(frozen=True)
class ImpedanceLslConfig:
    stream_name: str
    stream_type: str
    sampling_rate_hz: int


@dataclass(frozen=True)
class ImpedanceStreamingConfig:
    buffer_size: int


@dataclass(frozen=True)
class ImpedanceUiConfig:
    refresh_hz: int
    good_max_ohm: int
    warn_max_ohm: int
    slider_max_ohm: int
    slider_step_ohm: int


@dataclass(frozen=True)
class ImpedanceConfig:
    enabled: bool
    n_channels: int
    frame: ImpedanceFrameConfig
    lsl: ImpedanceLslConfig
    streaming: ImpedanceStreamingConfig
    ui: ImpedanceUiConfig


@dataclass(frozen=True)
class TdcsUiConfig:
    show_reserved: bool


@dataclass(frozen=True)
class TdcsConfig:
    enabled: bool
    supported_channel_modes: List[int]
    ui: TdcsUiConfig


@dataclass(frozen=True)
class AppConfig:
    app_ui_version: str
    ui: UiConfig
    bluetooth: BluetoothConfig
    eeg: EegConfig
    impedance: ImpedanceConfig
    tdcs: TdcsConfig
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
    cmd_raw = bluetooth_raw.get("command_bytes") or bluetooth_raw.get("commands", {}) or {}

    eeg_raw = raw.get("eeg", {})
    lsl_raw = eeg_raw.get("lsl", {})

    eeg_protocol_raw: Dict[str, Any] = {}
    proto_candidate = eeg_raw.get("protocol", None)
    if isinstance(proto_candidate, dict) and proto_candidate:
        eeg_protocol_raw = proto_candidate
    else:
        proto_candidate = raw.get("protocol", {})
        if isinstance(proto_candidate, dict) and proto_candidate:
            eeg_protocol_raw = proto_candidate

    impedance_raw = raw.get("impedance", {}) or {}
    impedance_frame_raw = impedance_raw.get("frame", {}) or {}
    impedance_lsl_raw = impedance_raw.get("lsl", {}) or {}
    impedance_streaming_raw = impedance_raw.get("streaming", {}) or {}
    impedance_ui_raw = impedance_raw.get("ui", {}) or {}

    tdcs_raw = raw.get("tdcs", {}) or {}
    tdcs_ui_raw = tdcs_raw.get("ui", {}) or {}

    server_raw = raw.get("server", {})
    streaming_raw = raw.get("streaming", {})
    debug_raw = raw.get("debug", {})
    signal_raw = raw.get("signal", {}) or {}
    offline_raw = raw.get("offline", {}) or {}
    app_raw = raw.get("app", {}) or {}
    ui_raw = raw.get("ui", {}) or {}
    waveform_ui_raw = ui_raw.get("waveform", {}) or {}
    app_ui_version = str(app_raw.get("ui_version") or app_raw.get("version") or "1.0.0").strip() or "1.0.0"

    n_channels = int(eeg_raw.get("n_channels", eeg_raw.get("mode_channels", 8)))
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
        supported_modes = [n_channels]
    if n_channels not in supported_modes:
        supported_modes.append(n_channels)
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
                p_mode = int(item.get("n_channels", item.get("mode_channels", 0)))
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
            presets.append(ChannelPresetConfig(name=name, n_channels=p_mode, channel_names=p_names, ref_channel_name=p_ref))

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
    max_pending_ws_chunks = int(waveform_ui_raw.get("max_pending_ws_chunks", 2))
    if max_pending_ws_chunks < 1:
        max_pending_ws_chunks = 1
    if max_pending_ws_chunks > 20:
        max_pending_ws_chunks = 20
    y_axis_step = float(waveform_ui_raw.get("y_axis_step", 50.0))
    if not (y_axis_step == y_axis_step):
        y_axis_step = 50.0
    y_axis_update_hz = float(waveform_ui_raw.get("y_axis_update_hz", 2.0))
    if not (y_axis_update_hz == y_axis_update_hz):
        y_axis_update_hz = 2.0
    if y_axis_update_hz < 0.2:
        y_axis_update_hz = 0.2
    if y_axis_update_hz > 20.0:
        y_axis_update_hz = 20.0

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

    init_commands_cfg = _as_u8_list_list(cmd_raw.get("init_commands", cmd_raw.get("init", [])))
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

    def _build_frame_protocol(frame_cfg_raw: Dict[str, Any]) -> FrameProtocolConfig:
        return FrameProtocolConfig(
            header_len_bytes=int(frame_cfg_raw.get("header_len_bytes", 3)),
            bytes_per_sample_per_channel=int(frame_cfg_raw.get("bytes_per_sample_per_channel", 3)),
            samples_per_frame=int(frame_cfg_raw.get("samples_per_frame", 5)),
            trigger_len_bytes=int(frame_cfg_raw.get("trigger_len_bytes", 1)),
            imu_len_bytes=int(frame_cfg_raw.get("imu_len_bytes", 12)),
            battery_len_bytes=int(frame_cfg_raw.get("battery_len_bytes", 2)),
            tail_len_bytes=int(frame_cfg_raw.get("tail_len_bytes", 2)),
        )

    ch8_variant_raw: Dict[str, Any]
    if isinstance(eeg_protocol_raw.get("ch8"), dict):
        ch8_variant_raw = eeg_protocol_raw.get("ch8", {}) or {}
    else:
        ch8_variant_raw = eeg_protocol_raw
    ch8_frame_raw = ch8_variant_raw.get("frame", {}) if isinstance(ch8_variant_raw.get("frame", {}), dict) else {}
    ch8_proto = EegProtocolVariantConfig(frame=_build_frame_protocol(ch8_frame_raw))

    ch16_proto: Optional[EegProtocolVariantConfig] = None
    ch16_variant = eeg_protocol_raw.get("ch16", None)
    if isinstance(ch16_variant, dict) and ch16_variant:
        ch16_frame_raw = ch16_variant.get("frame", {}) if isinstance(ch16_variant.get("frame", {}), dict) else {}
        if ch16_frame_raw:
            ch16_proto = EegProtocolVariantConfig(frame=_build_frame_protocol(ch16_frame_raw))

    if int(n_channels) == 16 and ch16_proto is None:
        raise ValueError("eeg.n_channels=16 时必须配置 eeg.protocol.ch16.frame")

    eeg = EegConfig(
        n_channels=n_channels,
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
        protocol=EegProtocolConfig(ch8=ch8_proto, ch16=ch16_proto),
    )

    impedance_n_channels = int(impedance_raw.get("n_channels", impedance_raw.get("mode_channels", n_channels)))
    if impedance_n_channels <= 0:
        impedance_n_channels = n_channels
    header_cfg = _as_u8_list(impedance_frame_raw.get("header", [0x55, 0x66]))
    if len(header_cfg) != 2:
        header_cfg = [0x55, 0x66]
    frame_len_ch8 = int(impedance_frame_raw.get("frame_len_bytes_ch8", 46))
    frame_len_ch16 = int(impedance_frame_raw.get("frame_len_bytes_ch16", 74))
    if frame_len_ch8 <= 0:
        frame_len_ch8 = 46
    if frame_len_ch16 <= 0:
        frame_len_ch16 = 74
    gain_scale = float(impedance_frame_raw.get("gain_scale", 10000.0))
    if gain_scale <= 0:
        gain_scale = 10000.0
    imp_buffer_size = max(1, int(impedance_streaming_raw.get("buffer_size", 5)))
    imp_refresh_hz = max(1, int(impedance_ui_raw.get("refresh_hz", 1)))
    good_max_ohm = max(1, int(impedance_ui_raw.get("good_max_ohm", 5000)))
    warn_max_ohm = max(good_max_ohm + 1, int(impedance_ui_raw.get("warn_max_ohm", 20000)))
    slider_max_ohm = max(warn_max_ohm + 1, int(impedance_ui_raw.get("slider_max_ohm", 25000)))
    slider_step_ohm = max(1, int(impedance_ui_raw.get("slider_step_ohm", 100)))
    impedance = ImpedanceConfig(
        enabled=bool(impedance_raw.get("enabled", True)),
        n_channels=impedance_n_channels,
        frame=ImpedanceFrameConfig(
            header=header_cfg,
            frame_len_bytes_ch8=frame_len_ch8,
            frame_len_bytes_ch16=frame_len_ch16,
            include_bias=bool(impedance_frame_raw.get("include_bias", True)),
            include_tdcs_if_ch8=bool(impedance_frame_raw.get("include_tdcs_if_ch8", True)),
            gain_scale=gain_scale,
        ),
        lsl=ImpedanceLslConfig(
            stream_name=str(impedance_lsl_raw.get("stream_name", "BHB-IMP")),
            stream_type=str(impedance_lsl_raw.get("stream_type", "Impedance")),
            sampling_rate_hz=int(impedance_lsl_raw.get("sampling_rate_hz", 0)),
        ),
        streaming=ImpedanceStreamingConfig(
            buffer_size=imp_buffer_size,
        ),
        ui=ImpedanceUiConfig(
            refresh_hz=imp_refresh_hz,
            good_max_ohm=good_max_ohm,
            warn_max_ohm=warn_max_ohm,
            slider_max_ohm=slider_max_ohm,
            slider_step_ohm=slider_step_ohm,
        ),
    )

    tdcs_supported_modes_raw = tdcs_raw.get("supported_channel_modes", [8]) or [8]
    tdcs_supported_modes: List[int] = []
    if isinstance(tdcs_supported_modes_raw, list):
        for v in tdcs_supported_modes_raw:
            try:
                iv = int(v)
            except Exception:
                continue
            if iv <= 0:
                continue
            if iv not in tdcs_supported_modes:
                tdcs_supported_modes.append(iv)
    if not tdcs_supported_modes:
        tdcs_supported_modes = [8]
    tdcs_supported_modes.sort()
    tdcs = TdcsConfig(
        enabled=bool(tdcs_raw.get("enabled", True)),
        supported_channel_modes=tdcs_supported_modes,
        ui=TdcsUiConfig(
            show_reserved=bool(tdcs_ui_raw.get("show_reserved", True)),
        ),
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
    writer_queue_max_chunks = int(offline_raw.get("writer_queue_max_chunks", 50))
    if writer_queue_max_chunks < 1:
        writer_queue_max_chunks = 1
    if writer_queue_max_chunks > 1000:
        writer_queue_max_chunks = 1000
    writer_queue_full_policy = str(offline_raw.get("writer_queue_full_policy", "merge") or "merge").strip().lower()
    if writer_queue_full_policy not in ("merge", "drop_oldest", "drop_newest"):
        writer_queue_full_policy = "merge"
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
        writer_queue_max_chunks=writer_queue_max_chunks,
        writer_queue_full_policy=writer_queue_full_policy,
    )

    ui = UiConfig(
        waveform=WaveformUiConfig(
            time_window_sec=time_window_sec,
            render_fps_hz=render_fps_hz,
            max_render_points_per_channel=max_render_points_per_channel,
            global_scale=global_scale,
            max_pending_ws_chunks=max_pending_ws_chunks,
            y_axis_step=y_axis_step,
            y_axis_update_hz=y_axis_update_hz,
        )
    )

    return AppConfig(
        app_ui_version=app_ui_version,
        ui=ui,
        bluetooth=bluetooth,
        eeg=eeg,
        impedance=impedance,
        tdcs=tdcs,
        server=server,
        streaming=streaming,
        debug=debug,
        signal=signal,
        offline=offline,
    )
