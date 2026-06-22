#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: BLE EEG 帧协议解析（校验帧完整性，解析 EEG/触发/电量/IMU 并输出采样点序列）

修改日志:
- 2026-04-30: 1.0.0 创建文件
- 2026-06-20: 1.0.1 精简内部注释与 Docstring，便于软著代码展示

作者: Spoon
版本: 1.0.1
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class FrameSpec:
    """
    BLE EEG 帧协议描述。
    """
    channels: int
    header_len_bytes: int
    bytes_per_sample_per_channel: int
    samples_per_frame: int
    trigger_len_bytes: int
    imu_len_bytes: int
    battery_len_bytes: int
    tail_len_bytes: int

    @property
    def eeg_payload_len_bytes(self) -> int:
        return self.channels * self.bytes_per_sample_per_channel * self.samples_per_frame

    @property
    def frame_len_bytes(self) -> int:
        return (
            self.header_len_bytes
            + self.eeg_payload_len_bytes
            + self.trigger_len_bytes
            + self.imu_len_bytes
            + self.battery_len_bytes
            + self.tail_len_bytes
        )

    def validate_checksum(self, frame: bytes) -> bool:
        """
        校验帧长、帧头和帧尾。
        """
        if len(frame) != self.frame_len_bytes:
            return False
            
        tail_idx = self.frame_len_bytes - 1
        if frame[0] != 0xAA or frame[1] != 0xBB:
            return False
        if frame[tail_idx] != 0xCC:
            return False
        return True


def parse_imu(imu_bytes: bytes) -> Dict[str, int]:
    """
    解析 IMU 姿态数据。
    """
    valid = imu_bytes[:6]
    if len(valid) < 6:
        return {}
    return {
        "yaw": int.from_bytes(valid[0:2], byteorder="big", signed=True),
        "roll": int.from_bytes(valid[2:4], byteorder="big", signed=True),
        "pitch": int.from_bytes(valid[4:6], byteorder="big", signed=True),
    }


def parse_frame_to_samples(frame: bytes, spec: FrameSpec) -> Tuple[List[List[float]], int, Dict[str, int]]:
    """
    将单帧数据解析为采样点、电量和 IMU 信息。
    """
    head_end = spec.header_len_bytes
    eeg_end = head_end + spec.eeg_payload_len_bytes
    trig_end = eeg_end + spec.trigger_len_bytes
    imu_end = trig_end + spec.imu_len_bytes
    bat_end = imu_end + spec.battery_len_bytes

    eeg_bytes = frame[head_end:eeg_end]
    trig_bytes = frame[eeg_end:trig_end]
    imu_bytes = frame[trig_end:imu_end]
    battery_bytes = frame[imu_end:bat_end]

    trigger_val = 0
    if len(trig_bytes) >= 1:
        trigger_val = int.from_bytes(trig_bytes[:1], byteorder="big", signed=False)

    battery_level = 0
    if len(battery_bytes) == spec.battery_len_bytes and spec.battery_len_bytes > 0:
        battery_level = int.from_bytes(battery_bytes, byteorder="big", signed=False)

    imu = parse_imu(imu_bytes)

    samples: List[List[float]] = []
    bytes_per_sample_all_channels = spec.channels * spec.bytes_per_sample_per_channel
    for frame_idx in range(spec.samples_per_frame):
        base = frame_idx * bytes_per_sample_all_channels
        sample: List[float] = []
        for ch_idx in range(spec.channels):
            start = base + ch_idx * spec.bytes_per_sample_per_channel
            end = start + spec.bytes_per_sample_per_channel
            raw = int.from_bytes(eeg_bytes[start:end], byteorder="big", signed=True)
            sample.append(float(raw))
            
        sample.append(float(trigger_val))
        samples.append(sample)

    return samples, battery_level, imu
