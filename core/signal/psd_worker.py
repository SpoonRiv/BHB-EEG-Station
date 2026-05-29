#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 在线 PSD 频域分析（缓存最近窗口并计算 Welch 功率谱密度，供 WebSocket 推送使用）

修改日志:
- 2026-05-29: 1.0.0 创建文件

作者: Spoon
版本: 1.0.0
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np
from scipy.signal import filtfilt, iirnotch, welch


@dataclass(frozen=True)
class PsdWorkerConfig:
    """
    在线 PSD 计算配置。

    Attributes:
        enabled: 是否启用 PSD 计算。
        window_sec: 计算窗口长度（秒）。
        update_hz: 推送/计算频率（Hz）。
        nfft: Welch/FFT 长度。
        fmin_hz: 频段下限（Hz）。
        fmax_hz: 频段上限（Hz）。
        to_db: 是否将 PSD 转换为 dB（10*log10）。
        apply_notch: 是否对窗口应用陷波（窗口内零相位）。
    """

    enabled: bool
    window_sec: float
    update_hz: float
    nfft: int
    fmin_hz: float
    fmax_hz: float
    to_db: bool
    apply_notch: bool


class PsdWorker:
    """
    在线 PSD 计算器（线程安全：append 与 snapshot 分离）。

    设计要点：
    - append_chunk 必须足够轻量：仅缓存最近 window_sec 的数据；
    - compute_psd_payload 可能较慢：应在后台线程调用，避免阻塞事件循环；
    - 输入 chunk 形如 [sample][channel]，可包含触发通道；PSD 仅对 EEG 通道计算。
    """

    def __init__(
        self,
        cfg: PsdWorkerConfig,
        sampling_rate_hz: int,
        eeg_channel_names: List[str],
        count_divisor: float,
        has_trigger_channel: bool,
        notch_freq_hz: float,
        notch_quality_factor: float,
    ):
        self.cfg = cfg
        self.sampling_rate_hz = int(max(1, sampling_rate_hz))
        self.channel_names = list(eeg_channel_names)
        self.n_channels = int(len(self.channel_names))
        self.has_trigger_channel = bool(has_trigger_channel)
        self.count_divisor = float(count_divisor) if float(count_divisor) > 0 else 120.0
        self.notch_freq_hz = float(notch_freq_hz)
        self.notch_quality_factor = float(notch_quality_factor)

        self._window_points = int(max(8, round(float(cfg.window_sec) * float(self.sampling_rate_hz))))
        self._buf: List[Deque[float]] = [deque(maxlen=self._window_points) for _ in range(self.n_channels)]
        self._lock = threading.Lock()

        self._notch_ba: Optional[Tuple[np.ndarray, np.ndarray]] = None
        self._ts_last: float = 0.0

    def reset(self) -> None:
        """
        清空缓存（用于开始/停止采集时重置，避免混入旧窗口）。
        """
        with self._lock:
            for d in self._buf:
                d.clear()
            self._ts_last = 0.0

    def append_chunk(self, chunk: List[List[float]]) -> None:
        """
        追加一个 EEG chunk 到环形缓存。

        Args:
            chunk: 形如 [sample][channel] 的二维数组。
        """
        if not self.cfg.enabled:
            return
        if not chunk or self.n_channels <= 0:
            return

        try:
            arr = np.asarray(chunk, dtype=np.float32)
        except Exception:
            return
        if arr.ndim != 2:
            return
        if arr.shape[1] < self.n_channels:
            return

        eeg = arr[:, : self.n_channels]
        if self.count_divisor != 1.0:
            eeg = eeg / float(self.count_divisor)

        with self._lock:
            for ch in range(self.n_channels):
                self._buf[ch].extend(eeg[:, ch].tolist())

    def snapshot_window(self) -> Optional[np.ndarray]:
        """
        获取当前窗口快照（复制后返回，避免在锁内做耗时计算）。

        Returns:
            Optional[np.ndarray]: shape=(n_channels, n_points)；若数据不足返回 None。
        """
        if not self.cfg.enabled:
            return None
        with self._lock:
            if self.n_channels <= 0:
                return None
            if len(self._buf[0]) < self._window_points:
                return None
            out = np.empty((self.n_channels, self._window_points), dtype=np.float32)
            for ch in range(self.n_channels):
                out[ch, :] = np.asarray(self._buf[ch], dtype=np.float32)
            self._ts_last = time.time()
            return out

    def compute_psd_payload(self, window: np.ndarray) -> Optional[Dict[str, object]]:
        """
        基于窗口数据计算 PSD，并构造可直接用于 WebSocket JSON 推送的 payload。

        注意：
            该函数可能耗时，应在后台线程执行（例如 asyncio.to_thread）。

        Args:
            window: shape=(n_channels, n_points)

        Returns:
            Optional[Dict[str, object]]: {"ts","freq_hz","channels","unit"}；失败返回 None。
        """
        if not self.cfg.enabled:
            return None
        if window is None:
            return None
        if not isinstance(window, np.ndarray) or window.ndim != 2:
            return None
        if window.shape[0] != self.n_channels:
            return None

        data = window.astype(np.float64, copy=False)
        fs = float(self.sampling_rate_hz)
        nyq = fs / 2.0

        fmin = float(self.cfg.fmin_hz)
        fmax = float(self.cfg.fmax_hz)
        if fmin < 0:
            fmin = 0.0
        if fmax <= 0:
            fmax = nyq
        if fmax > nyq:
            fmax = nyq
        if fmin >= fmax:
            fmin = 0.0

        if bool(self.cfg.apply_notch):
            b, a = self._get_notch_ba(fs)
            if b is not None and a is not None and data.shape[1] >= 32:
                try:
                    data = filtfilt(b, a, data, axis=1).astype(np.float64, copy=False)
                except Exception:
                    pass

        nfft = int(self.cfg.nfft)
        nperseg = min(int(max(16, data.shape[1])), int(max(16, nfft)))
        try:
            freq, psd = welch(
                data,
                fs=fs,
                nperseg=nperseg,
                nfft=nfft,
                axis=1,
                scaling="density",
            )
        except Exception:
            return None

        mask = (freq >= fmin) & (freq <= fmax)
        if not np.any(mask):
            return None
        freq = freq[mask]
        psd = psd[:, mask]

        unit = "uV^2/Hz"
        if bool(self.cfg.to_db):
            psd = 10.0 * np.log10(np.maximum(psd, 1e-20))
            unit = "dB"

        channels: Dict[str, List[float]] = {}
        for i, name in enumerate(self.channel_names):
            channels[str(name)] = psd[i, :].astype(np.float32).tolist()

        ts = float(self._ts_last) if self._ts_last > 0 else float(time.time())
        return {
            "ts": ts,
            "freq_hz": freq.astype(np.float32).tolist(),
            "channels": channels,
            "unit": unit,
        }

    def get_update_interval_sec(self) -> float:
        """
        将 update_hz 转换为秒级间隔。
        """
        hz = float(self.cfg.update_hz)
        if not math.isfinite(hz) or hz <= 0:
            hz = 1.0
        return 1.0 / hz

    def _get_notch_ba(self, fs: float) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        if self._notch_ba is not None:
            return self._notch_ba
        f0 = float(self.notch_freq_hz)
        if not math.isfinite(f0):
            return None, None
        if f0 <= 0:
            return None, None
        if f0 >= (float(fs) / 2.0):
            return None, None
        try:
            b, a = iirnotch(
                w0=f0,
                Q=float(self.notch_quality_factor),
                fs=float(fs),
            )
        except Exception:
            return None, None
        self._notch_ba = (b, a)
        return self._notch_ba
