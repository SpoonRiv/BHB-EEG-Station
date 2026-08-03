#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: BLE EEG 帧协议解析（校验帧完整性，解析 EEG/触发/电量/IMU 并输出采样点序列）
作者: Spoon
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


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
        校验帧长、帧头、帧尾和 SUM。
        """
        if len(frame) != self.frame_len_bytes:
            return False
            
        if frame[0] != 0xAA or frame[1] != 0xBB:
            return False
        if frame[-1] != 0xCC:
            return False

        # 兼容只定义帧尾、未定义 SUM 字节的协议变体。
        if self.tail_len_bytes < 2:
            return True

        # SUM covers only the protocol payload. The complete header is excluded,
        # including the sequence byte at ``header_len_bytes - 1``.
        expected_sum = sum(frame[self.header_len_bytes:-2]) & 0xFF
        return frame[-2] == expected_sum


@dataclass(frozen=True)
class FrameDecodeBatch:
    """Frames decoded from one BLE notification and its resync statistics."""

    frames: Tuple[bytes, ...]
    invalid_frames: int = 0
    dropped_bytes: int = 0


class FrameStreamDecoder:
    """Incrementally decode EEG frames from arbitrarily chunked BLE data."""

    _HEADER = b"\xAA\xBB"

    def __init__(self, spec: FrameSpec) -> None:
        self.spec = spec
        self._buffer = bytearray()

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    def clear(self) -> None:
        self._buffer.clear()

    def feed(self, data: bytes) -> FrameDecodeBatch:
        """
        Append one BLE notification and return every complete valid frame.

        Notifications are transport chunks rather than frame boundaries. In
        particular, a notification whose length equals one frame must still be
        appended to an existing partial frame instead of replacing it.
        """
        if data:
            self._buffer.extend(data)

        frames: List[bytes] = []
        invalid_frames = 0
        dropped_bytes = 0
        expected = int(self.spec.frame_len_bytes)

        while len(self._buffer) >= len(self._HEADER):
            header_pos = self._buffer.find(self._HEADER)
            if header_pos < 0:
                # Preserve a trailing 0xAA because it may be the first header
                # byte split across the next notification.
                keep = 1 if self._buffer[-1] == self._HEADER[0] else 0
                drop_count = len(self._buffer) - keep
                if drop_count:
                    del self._buffer[:drop_count]
                    dropped_bytes += drop_count
                break

            if header_pos > 0:
                del self._buffer[:header_pos]
                dropped_bytes += header_pos

            if len(self._buffer) < expected:
                break

            candidate = bytes(self._buffer[:expected])
            if self.spec.validate_checksum(candidate):
                frames.append(candidate)
                del self._buffer[:expected]
                continue

            # The apparent header may occur in garbage or a corrupted frame.
            # Advance one byte so the next real header can be found.
            invalid_frames += 1
            dropped_bytes += 1
            del self._buffer[:1]

        return FrameDecodeBatch(
            frames=tuple(frames),
            invalid_frames=invalid_frames,
            dropped_bytes=dropped_bytes,
        )


def parse_imu(imu_bytes: bytes) -> Dict[str, int]:
    """
    解析 IMU 三轴角速度和三轴加速度数据。
    """
    valid = imu_bytes[:12]
    if len(valid) < 12:
        return {}
    return {
        "gyro_x": int.from_bytes(valid[0:2], byteorder="big", signed=True),
        "gyro_y": int.from_bytes(valid[2:4], byteorder="big", signed=True),
        "gyro_z": int.from_bytes(valid[4:6], byteorder="big", signed=True),
        "accel_x": int.from_bytes(valid[6:8], byteorder="big", signed=True),
        "accel_y": int.from_bytes(valid[8:10], byteorder="big", signed=True),
        "accel_z": int.from_bytes(valid[10:12], byteorder="big", signed=True),
    }


def parse_trigger_per_sample(trig_bytes: bytes, samples_per_frame: int) -> List[float]:
    """
    将 Trigger 段展开为逐采样点的同步标记列表。

    参数:
        trig_bytes: 帧内 Trigger 原始字节段，仅首字节有效。
        samples_per_frame: 单帧包含的 EEG 采样点数量。

    返回:
        与 `samples_per_frame` 等长的列表；每个元素为 0.0 或 1.0。

    说明:
        协议约定 Trigger 段占用 1 字节，其中仅低 5 位有效，高 3 位保留。
        低 5 位按“从低位到高位”依次对应本帧 EEG 数据段中 5 个采样点的先后顺序。
        例如 `0bxxx11100` 表示前两个点异步、后 3 个点同步。
    """
    if samples_per_frame <= 0:
        return []

    trigger_byte = 0
    if len(trig_bytes) >= 1:
        trigger_byte = int.from_bytes(trig_bytes[:1], byteorder="big", signed=False)

    per_sample_trigger: List[float] = []
    valid_trigger_bits = 5
    for frame_idx in range(samples_per_frame):
        if frame_idx < valid_trigger_bits:
            bit_val = (trigger_byte >> frame_idx) & 0x01
            per_sample_trigger.append(float(bit_val))
        else:
            per_sample_trigger.append(0.0)
    return per_sample_trigger


def parse_frame_to_samples(
    frame: bytes,
    spec: FrameSpec,
) -> Tuple[List[List[float]], Optional[int], Dict[str, int]]:
    """
    将单帧数据解析为采样点、电量和 IMU 信息。

    返回的每个采样点都包含:
    - `spec.channels` 个 EEG 通道值
    - 末尾 1 个 Trigger 通道值（按协议逐点展开，而非整字节重复）
    """
    if not spec.validate_checksum(frame):
        raise ValueError("invalid EEG frame length, header, tail, or checksum")

    head_end = spec.header_len_bytes
    eeg_end = head_end + spec.eeg_payload_len_bytes
    trig_end = eeg_end + spec.trigger_len_bytes
    imu_end = trig_end + spec.imu_len_bytes
    bat_end = imu_end + spec.battery_len_bytes

    eeg_bytes = frame[head_end:eeg_end]
    trig_bytes = frame[eeg_end:trig_end]
    imu_bytes = frame[trig_end:imu_end]
    battery_bytes = frame[imu_end:bat_end]

    trigger_per_sample = parse_trigger_per_sample(trig_bytes, spec.samples_per_frame)

    battery_level: Optional[int] = None
    if len(battery_bytes) == spec.battery_len_bytes and spec.battery_len_bytes > 0:
        raw_battery_level = int.from_bytes(battery_bytes, byteorder="big", signed=False)
        if 0 <= raw_battery_level <= 100:
            battery_level = raw_battery_level

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
            
        sample.append(float(trigger_per_sample[frame_idx]))
        samples.append(sample)

    return samples, battery_level, imu
