#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 阻抗帧解析（将 BLE 通知数据帧解析为阻抗欧姆值向量），供采集进程推送到 LSL 与 UI 可视化使用。

修改日志:
- 2026-05-04: 1.0.0 新增阻抗帧解析（CH8/CH16，含 BIAS 与可选 tDCS）
- 2026-05-04: 1.0.1 字段更名：mode_channels -> n_channels（显式区分 8/16 通道）

作者: Spoon
版本: 1.0.1
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np


@dataclass(frozen=True)
class ImpedanceFrameSpec:
    """
    阻抗帧协议规格。

    Attributes:
        header: 帧头字节序列，固定为 [0x55, 0x66]。
        n_channels: 脑电电极通道数（8 或 16）。
        frame_len_bytes: 整帧长度（字节）。
        include_bias: 是否解析 BIAS 阻抗（位于帧尾）。
        include_tdcs: 是否解析 tDCS 电极阻抗（仅 CH8 协议帧尾包含）。
        gain_scale: 增益系数计算中的比例因子，协议约定为 10000.0。
    """

    header: Tuple[int, int]
    n_channels: int
    frame_len_bytes: int
    include_bias: bool
    include_tdcs: bool
    gain_scale: float


def _read_i16_be(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], byteorder="big", signed=True)


def parse_impedance_frame(frame: bytes, spec: ImpedanceFrameSpec) -> Tuple[List[float], float, Optional[float], Optional[float]]:
    """
    解析单个阻抗帧。

    计算依据（来自协议文档与旧版脚本验证）：
    - gain_coeff = 1 / (gain_scale * sqrt(gain_real^2 + gain_imag^2))
    - Z = 1 / (gain_coeff * sqrt(real^2 + imag^2))

    Args:
        frame: 原始字节帧，长度应为 spec.frame_len_bytes。
        spec: 协议规格。

    Returns:
        Tuple[List[float], float, Optional[float], Optional[float]]:
            - channels_ohm: 电极通道阻抗（长度=spec.mode_channels）
            - gain_coeff: 增益系数
            - bias_ohm: BIAS 阻抗（若未启用则为 None）
            - tdcs_ohm: tDCS 电极阻抗（若未启用则为 None）

    Raises:
        ValueError: 帧头/长度不匹配或通道数非法。
    """

    if len(frame) != int(spec.frame_len_bytes):
        raise ValueError(f"frame length mismatch: {len(frame)} != {spec.frame_len_bytes}")
    if len(spec.header) != 2:
        raise ValueError("invalid header length")
    if frame[0] != (spec.header[0] & 0xFF) or frame[1] != (spec.header[1] & 0xFF):
        raise ValueError("frame header mismatch")
    if int(spec.n_channels) not in (8, 16):
        raise ValueError(f"invalid n_channels: {spec.n_channels}")

    gain_real = _read_i16_be(frame, 2)
    gain_imag = _read_i16_be(frame, 4)
    denom_gain = float(gain_real * gain_real + gain_imag * gain_imag)
    if denom_gain <= 0:
        gain_coeff = 0.0
    else:
        gain_coeff = 1.0 / (float(spec.gain_scale) * float(np.sqrt(denom_gain)))

    channels: List[float] = []
    base = 6
    for ch in range(int(spec.n_channels)):
        off = base + ch * 4
        real = _read_i16_be(frame, off)
        imag = _read_i16_be(frame, off + 2)
        denom = float(real * real + imag * imag)
        if denom <= 0 or gain_coeff <= 0:
            channels.append(0.0)
        else:
            channels.append(1.0 / (gain_coeff * float(np.sqrt(denom))))

    bias_ohm: Optional[float] = None
    tdcs_ohm: Optional[float] = None

    tail_base = base + int(spec.n_channels) * 4
    if spec.include_bias:
        bias_real = _read_i16_be(frame, tail_base)
        bias_imag = _read_i16_be(frame, tail_base + 2)
        denom = float(bias_real * bias_real + bias_imag * bias_imag)
        if denom <= 0 or gain_coeff <= 0:
            bias_ohm = 0.0
        else:
            bias_ohm = 1.0 / (gain_coeff * float(np.sqrt(denom)))
        tail_base += 4

    if spec.include_tdcs:
        tdcs_real = _read_i16_be(frame, tail_base)
        tdcs_imag = _read_i16_be(frame, tail_base + 2)
        denom = float(tdcs_real * tdcs_real + tdcs_imag * tdcs_imag)
        if denom <= 0 or gain_coeff <= 0:
            tdcs_ohm = 0.0
        else:
            tdcs_ohm = 1.0 / (gain_coeff * float(np.sqrt(denom)))

    return channels, float(gain_coeff), bias_ohm, tdcs_ohm


def build_impedance_vector(
    channels_ohm: Sequence[float],
    bias_ohm: Optional[float],
    tdcs_ohm: Optional[float],
) -> List[float]:
    """
    将解析结果组装为用于推送 LSL/WS 的向量。

    Args:
        channels_ohm: 电极通道阻抗。
        bias_ohm: BIAS 阻抗（可选）。
        tdcs_ohm: tDCS 电极阻抗（可选）。

    Returns:
        List[float]: 形如 [CH..., BIAS?, tDCS?] 的阻抗向量。
    """

    out: List[float] = [float(x) for x in channels_ohm]
    if bias_ohm is not None:
        out.append(float(bias_ohm))
    if tdcs_ohm is not None:
        out.append(float(tdcs_ohm))
    return out
