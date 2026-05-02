#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 {Company}. All rights reserved.

文件功能: 加载并校验 configs/config.yaml，生成强类型配置对象（dataclass）

修改日志:
- 2026-04-30: 1.0.0 创建文件

作者: Spoon
版本: 1.0.0
"""

import os
from dataclasses import dataclass
from typing import Any, Dict, List

import yaml


@dataclass(frozen=True)
class BluetoothGattConfig:
    notify_char_handle: int
    write_char_handle: int


@dataclass(frozen=True)
class BluetoothCommandConfig:
    init_commands: List[List[int]]
    start_stream: List[int]
    stop_stream: List[int]


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
class EegConfig:
    mode_channels: int
    sampling_rate_hz: int
    channel_names: List[str]
    ref_channel_name: str
    lsl: LslConfig


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
    update_fps: int
    buffer_size: int


@dataclass(frozen=True)
class DebugConfig:
    ui_enabled: bool
    max_events: int


@dataclass(frozen=True)
class AppConfig:
    bluetooth: BluetoothConfig
    eeg: EegConfig
    protocol: ProtocolConfig
    server: ServerConfig
    streaming: StreamingConfig
    debug: DebugConfig


def load_config(config_path: str) -> AppConfig:
    """
    加载 configs/config.yaml，生成强类型配置对象。

    注意：
        当前重构后的项目不再依赖任何旧版 ini 文件（如 BHBconfig.ini），保持单一配置入口。
    """
    with open(config_path, "r", encoding="utf-8") as f:
        raw: Dict[str, Any] = yaml.safe_load(f) or {}

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

    mode_channels = int(eeg_raw.get("mode_channels", 8))
    channel_names_cfg = list(eeg_raw.get("channel_names", []) or [])
    ref_channel_cfg = str(eeg_raw.get("ref_channel_name", "") or "")

    device_names_cfg = list(bluetooth_raw.get("device_names", []) or [])

    sampling_rate_hz = int(eeg_raw.get("sampling_rate_hz", 250))
    update_fps = int(streaming_raw.get("update_fps", 25))
    buffer_size = int(streaming_raw.get("buffer_size", 0))
    if buffer_size <= 0:
        buffer_size = max(1, int(round(sampling_rate_hz / max(1, update_fps))))

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
    start_stream_cfg = _as_u8_list(cmd_raw.get("start_stream", [0x02, 0x01]))
    stop_stream_cfg = _as_u8_list(cmd_raw.get("stop_stream", [0x02, 0x02]))

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
            start_stream=start_stream_cfg,
            stop_stream=stop_stream_cfg,
        ),
    )

    eeg = EegConfig(
        mode_channels=mode_channels,
        sampling_rate_hz=sampling_rate_hz,
        channel_names=channel_names_cfg,
        ref_channel_name=ref_channel_cfg,
        lsl=LslConfig(
            stream_name=str(lsl_raw.get("stream_name", "BHB-EEG")),
            stream_type=str(lsl_raw.get("stream_type", "EEG")),
            include_trigger_channel=bool(lsl_raw.get("include_trigger_channel", True)),
        ),
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
        update_fps=update_fps,
        buffer_size=buffer_size,
    )

    debug = DebugConfig(
        ui_enabled=bool(debug_raw.get("ui_enabled", True)),
        max_events=int(debug_raw.get("max_events", 500)),
    )

    return AppConfig(
        bluetooth=bluetooth,
        eeg=eeg,
        protocol=protocol,
        server=server,
        streaming=streaming,
        debug=debug,
    )
