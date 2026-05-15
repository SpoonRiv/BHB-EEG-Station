#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 实时 EEG 带通滤波器（对 EEG 通道做状态保持的 IIR bandpass，触发通道不处理）

修改日志:
- 2026-05-15: 1.0.0 创建文件

作者: Spoon
版本: 1.0.0
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi


@dataclass(frozen=True)
class BandpassFilterConfig:
    """
    带通滤波器配置。

    Attributes:
        sampling_rate_hz: 采样率（Hz）。
        lowcut_hz: 低截止频率（Hz）。
        highcut_hz: 高截止频率（Hz）。
        order: 滤波器阶数（Butterworth）。
        channel_count: 输入通道数（包含可选触发通道）。
        has_trigger_channel: 是否包含触发通道（触发通道不滤波）。
    """

    sampling_rate_hz: int
    lowcut_hz: float
    highcut_hz: float
    order: int
    channel_count: int
    has_trigger_channel: bool


class BandpassFilter:
    """
    状态保持的 IIR 带通滤波器（用于实时波形展示）。

    说明：
        - 为保证跨 chunk 连续性，内部维护每个通道的滤波状态；
        - 仅处理 EEG 通道，不处理触发通道（若存在，默认在最后一列）。
    """

    def __init__(self, cfg: BandpassFilterConfig):
        self.cfg = cfg
        fs = float(cfg.sampling_rate_hz)
        low = float(cfg.lowcut_hz)
        high = float(cfg.highcut_hz)
        order = max(1, int(cfg.order))
        self._sos = butter(N=order, Wn=[low, high], btype="bandpass", fs=fs, output="sos")

        self._channel_count = max(0, int(cfg.channel_count))
        self._has_trigger = bool(cfg.has_trigger_channel)
        self._n_filter_ch = self._channel_count - (1 if self._has_trigger else 0)

        self._states: Optional[np.ndarray] = None
        self._primed = False

    def reset(self) -> None:
        """
        重置滤波状态。
        """
        self._states = None
        self._primed = False

    def apply(self, chunk: List[List[float]]) -> List[List[float]]:
        """
        对一个 chunk 应用带通滤波。

        Args:
            chunk: 形如 [sample][channel] 的二维数组。

        Returns:
            List[List[float]]: 同形状的滤波后数据。
        """
        if not chunk:
            return chunk
        if self._n_filter_ch <= 0:
            return chunk

        arr = np.asarray(chunk, dtype=np.float64)
        if arr.ndim != 2:
            return chunk
        if self._channel_count > 0 and arr.shape[1] < self._channel_count:
            return chunk
        if self._channel_count > 0 and arr.shape[1] != self._channel_count:
            arr = arr[:, : self._channel_count]

        if self._states is None:
            zi = sosfilt_zi(self._sos).astype(np.float64)
            self._states = np.tile(zi.reshape(1, *zi.shape), (self._n_filter_ch, 1, 1))
            self._primed = False

        if not self._primed:
            for ch in range(self._n_filter_ch):
                self._states[ch] = self._states[ch] * float(arr[0, ch])
            self._primed = True

        out = np.empty_like(arr, dtype=np.float64)
        for ch in range(self._n_filter_ch):
            y, zf = sosfilt(self._sos, arr[:, ch], zi=self._states[ch])
            self._states[ch] = zf
            out[:, ch] = y
        if self._has_trigger:
            out[:, -1] = arr[:, -1]
        return out.astype(np.float32).tolist()
