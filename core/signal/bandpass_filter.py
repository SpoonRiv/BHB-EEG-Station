#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 实时 EEG IIR 带通滤波器（对 EEG 通道做状态保持的 Butterworth bandpass，触发通道不处理）
作者: Spoon
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi


@dataclass(frozen=True)
class BandpassFilterConfig:
    """
    Butterworth 带通滤波器配置。

    Attributes:
        sampling_rate_hz: 采样率（Hz）。
        lowcut_hz: 带通下限频率（Hz）。
        highcut_hz: 带通上限频率（Hz）。
        order: Butterworth 滤波器阶数（默认 4）。
        channel_count: 输入通道数（包含可选触发通道）。
        has_trigger_channel: 是否包含触发通道（触发通道不滤波）。
        enabled: 是否启用带通滤波（默认 True；关闭时不处理直接透传）。
    """

    sampling_rate_hz: int
    lowcut_hz: float
    highcut_hz: float
    order: int = 4
    channel_count: int = 0
    has_trigger_channel: bool = False
    enabled: bool = True


class BandpassFilter:
    """
    状态保持的 IIR Butterworth 带通滤波器（用于实时波形展示）。

    说明：
        - 使用 SOS（二阶节）形式以保证数值稳定性，支持高阶（最高 12 阶）；
        - 为保证跨 chunk 连续性，内部维护每个通道的滤波状态；
        - 仅处理 EEG 通道，不处理触发通道（若存在，默认在最后一列）。
    """

    def __init__(self, cfg: BandpassFilterConfig):
        self._sampling_rate_hz = int(cfg.sampling_rate_hz)
        self._lowcut_hz = float(cfg.lowcut_hz)
        self._highcut_hz = float(cfg.highcut_hz)
        self._order = int(cfg.order)
        self._enabled = bool(cfg.enabled)

        self._channel_count = max(0, int(cfg.channel_count))
        self._has_trigger = bool(cfg.has_trigger_channel)
        self._n_filter_ch = self._channel_count - (1 if self._has_trigger else 0)

        # SOS 系数与 per-channel 状态
        self._sos: Optional[np.ndarray] = None
        self._states: Optional[list] = None
        self._primed = False

        if self._enabled:
            self._build_sos(self._lowcut_hz, self._highcut_hz, self._order)

    # ------------------------------------------------------------------
    #  内部工具
    # ------------------------------------------------------------------

    def _build_sos(self, lowcut_hz: float, highcut_hz: float, order: int) -> None:
        """计算 SOS 系数并重置状态。"""
        fs = float(self._sampling_rate_hz)
        nyq = fs / 2.0
        low = max(float(lowcut_hz), 1e-6)
        high = min(float(highcut_hz), nyq - 1e-6)
        if low >= high:
            # 参数非法时退化为直通
            self._sos = None
            self._states = None
            self._primed = False
            return
        self._sos = butter(
            order, [low, high], btype="band", fs=fs, output="sos"
        )
        self._states = None
        self._primed = False

    # ------------------------------------------------------------------
    #  公开 API
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """重置滤波状态。"""
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
        if not chunk or not self._enabled:
            return chunk
        if self._n_filter_ch <= 0:
            return chunk
        if self._sos is None:
            return chunk

        arr = np.asarray(chunk, dtype=np.float64)
        if arr.ndim != 2:
            return chunk
        if self._channel_count > 0 and arr.shape[1] < self._channel_count:
            return chunk
        if self._channel_count > 0 and arr.shape[1] != self._channel_count:
            arr = arr[:, : self._channel_count]

        # 惰性初始化 per-channel 状态
        if self._states is None:
            zi_template = sosfilt_zi(self._sos).astype(np.float64)  # (n_sections, 2)
            self._states = [np.copy(zi_template) for _ in range(self._n_filter_ch)]
            self._primed = False

        # 首样本 priming：用各通道首个采样值缩放 zi，避免阶跃瞬态
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

    def reconfigure(
        self,
        enabled: bool,
        lowcut_hz: float,
        highcut_hz: float,
        order: int,
    ) -> None:
        """
        动态更新带通滤波器参数。

        Args:
            enabled: 是否启用。
            lowcut_hz: 新的下限频率（Hz）。
            highcut_hz: 新的上限频率（Hz）。
            order: 新的滤波器阶数。
        """
        self._enabled = bool(enabled)
        self._lowcut_hz = float(lowcut_hz)
        self._highcut_hz = float(highcut_hz)
        self._order = int(order)
        if self._enabled:
            self._build_sos(self._lowcut_hz, self._highcut_hz, self._order)
        else:
            self._sos = None
            self._states = None
            self._primed = False

    # ------------------------------------------------------------------
    #  只读属性（供 API GET 返回当前配置）
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def lowcut_hz(self) -> float:
        return self._lowcut_hz

    @property
    def highcut_hz(self) -> float:
        return self._highcut_hz

    @property
    def order(self) -> int:
        return self._order
