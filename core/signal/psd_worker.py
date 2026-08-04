#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 在线 PSD 频域分析（缓存最近窗口并计算 Welch 功率谱密度，供 WebSocket 推送使用）
作者: Spoon
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


# 与 attention_monitor.py 一致的 EEG 节律频带。
# 相对功率以这些频带的功率和为分母，当前覆盖 1~45 Hz。
EEG_BANDS: Tuple[Tuple[str, str, str, float, float], ...] = (
    ("delta", "Delta", "", 1.0, 4.0),
    ("theta", "Theta", "", 4.0, 8.0),
    ("alpha", "Alpha", "", 8.0, 13.0),
    ("beta", "Beta", "", 13.0, 30.0),
    ("gamma", "Gamma", "", 30.0, 45.0),
)
PSD_DISPLAY_FMIN_HZ = 1.0
PSD_DISPLAY_FMAX_HZ = 45.0

@dataclass(frozen=True)
class PsdWorkerConfig:
    """
    在线 PSD 计算配置。
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
    在线 PSD 计算器。
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
        units_per_count: Optional[float] = None,
    ):
        self.cfg = cfg
        self.sampling_rate_hz = int(max(1, sampling_rate_hz))
        self.channel_names = list(eeg_channel_names)
        self.n_channels = int(len(self.channel_names))
        self.has_trigger_channel = bool(has_trigger_channel)
        self.count_divisor = float(count_divisor) if float(count_divisor) > 0 else 120.0
        try:
            parsed_units_per_count = float(units_per_count) if units_per_count is not None else None
        except Exception:
            parsed_units_per_count = None
        self.units_per_count = (
            parsed_units_per_count
            if parsed_units_per_count is not None and np.isfinite(parsed_units_per_count) and parsed_units_per_count > 0
            else None
        )
        self.notch_freq_hz = float(notch_freq_hz)
        self.notch_quality_factor = float(notch_quality_factor)

        self._window_points = int(max(8, round(float(cfg.window_sec) * float(self.sampling_rate_hz))))
        self._buf: List[Deque[float]] = [deque(maxlen=self._window_points) for _ in range(self.n_channels)]
        self._lock = threading.Lock()

        self._notch_ba: Optional[Tuple[np.ndarray, np.ndarray]] = None
        self._ts_last: float = 0.0
        self._data_version: int = 0
        self._last_snapshot_version: int = -1

    def reset(self) -> None:
        """
        清空缓存。
        """
        with self._lock:
            for d in self._buf:
                d.clear()
            self._ts_last = 0.0
            self._data_version = 0
            self._last_snapshot_version = -1

    def append_chunk(self, chunk: List[List[float]]) -> None:
        """
        追加一个 EEG 数据块到环形缓存。
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
        if self.units_per_count is not None:
            # 8 通道：raw_signed × 2 × Vref × 1e6 / (ADC gain × G × 2^bits)。
            eeg = eeg * float(self.units_per_count)
        elif self.count_divisor != 1.0:
            # 16 通道兼容旧协议。
            eeg = eeg / float(self.count_divisor)

        with self._lock:
            for ch in range(self.n_channels):
                self._buf[ch].extend(eeg[:, ch].tolist())
            self._data_version += int(eeg.shape[0])

    def snapshot_window(self) -> Optional[np.ndarray]:
        """
        获取当前窗口快照。
        """
        if not self.cfg.enabled:
            return None
        with self._lock:
            if self.n_channels <= 0:
                return None
            if len(self._buf[0]) < self._window_points:
                return None
            if self._data_version <= self._last_snapshot_version:
                return None
            out = np.empty((self.n_channels, self._window_points), dtype=np.float32)
            for ch in range(self.n_channels):
                out[ch, :] = np.asarray(self._buf[ch], dtype=np.float32)
            self._last_snapshot_version = self._data_version
            self._ts_last = time.time()
            return out

    def compute_psd_payload(self, window: np.ndarray) -> Optional[Dict[str, object]]:
        """
        计算 PSD，并构造 WebSocket 推送载荷。
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

        # 此页面固定展示 1–45 Hz，不随旧配置或本地覆盖扩大/缩小。
        fmin = PSD_DISPLAY_FMIN_HZ
        fmax = min(PSD_DISPLAY_FMAX_HZ, nyq)
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

        # 频带功率必须在线性、未裁剪的 Welch PSD 上积分，不能受 PSD 横轴
        # fmin/fmax 配置影响，也不能对 dB 数值直接积分。
        linear_psd = psd
        band_power = np.zeros((self.n_channels, len(EEG_BANDS)), dtype=np.float64)
        for band_idx, (_, _, _, band_low, band_high) in enumerate(EEG_BANDS):
            # Welch bins rarely land exactly on the EEG-band boundaries. Add
            # interpolated boundary samples before integrating so narrow bands
            # (especially Delta/Theta) do not lose their edge intervals.
            integration_low = max(float(band_low), float(freq[0]))
            integration_high = min(float(band_high), float(freq[-1]))
            if integration_low >= integration_high:
                continue

            interior_mask = (freq > integration_low) & (freq < integration_high)
            band_freq = np.concatenate(
                (
                    np.asarray([integration_low], dtype=np.float64),
                    freq[interior_mask],
                    np.asarray([integration_high], dtype=np.float64),
                )
            )
            low_psd = np.asarray(
                [np.interp(integration_low, freq, row) for row in linear_psd],
                dtype=np.float64,
            )[:, None]
            high_psd = np.asarray(
                [np.interp(integration_high, freq, row) for row in linear_psd],
                dtype=np.float64,
            )[:, None]
            band_values = np.concatenate(
                (low_psd, linear_psd[:, interior_mask], high_psd),
                axis=1,
            )
            band_power[:, band_idx] = np.trapezoid(
                band_values,
                band_freq,
                axis=1,
            )

        band_power = np.nan_to_num(band_power, nan=0.0, posinf=0.0, neginf=0.0)
        band_power = np.maximum(band_power, 0.0)
        band_total = np.sum(band_power, axis=1)
        band_relative_pct = np.divide(
            band_power * 100.0,
            band_total[:, None],
            out=np.zeros_like(band_power),
            where=band_total[:, None] > 0.0,
        )

        average_band_power = np.mean(band_power, axis=0)
        average_band_total = float(np.sum(average_band_power))
        average_band_relative_pct = np.divide(
            average_band_power * 100.0,
            average_band_total,
            out=np.zeros_like(average_band_power),
            where=average_band_total > 0.0,
        )

        display_low = max(float(fmin), float(freq[0]))
        display_high = min(float(fmax), float(freq[-1]))
        if display_low >= display_high:
            return None

        # Welch 频点由 fs / nfft 决定，通常不会恰好落在 1 Hz 和 45 Hz。
        # 补齐显示边界，确保曲线从横轴起点连续绘制到终点，不产生边缘留白。
        display_mask = (freq > display_low) & (freq < display_high)
        display_freq = np.concatenate(
            (
                np.asarray([display_low], dtype=np.float64),
                freq[display_mask],
                np.asarray([display_high], dtype=np.float64),
            )
        )
        display_low_psd = np.asarray(
            [np.interp(display_low, freq, row) for row in linear_psd],
            dtype=np.float64,
        )[:, None]
        display_high_psd = np.asarray(
            [np.interp(display_high, freq, row) for row in linear_psd],
            dtype=np.float64,
        )[:, None]
        psd = np.concatenate(
            (display_low_psd, linear_psd[:, display_mask], display_high_psd),
            axis=1,
        )
        freq = display_freq
        average_psd = np.mean(psd, axis=0)

        unit = "uV^2/Hz"
        if bool(self.cfg.to_db):
            psd = 10.0 * np.log10(np.maximum(psd, 1e-20))
            average_psd = 10.0 * np.log10(np.maximum(average_psd, 1e-20))
            unit = "dB"

        channels: Dict[str, List[float]] = {}
        band_channels: Dict[str, Dict[str, object]] = {}
        for i, name in enumerate(self.channel_names):
            channels[str(name)] = psd[i, :].astype(np.float32).tolist()
            band_channels[str(name)] = {
                "absolute": band_power[i, :].astype(np.float32).tolist(),
                "relative_pct": band_relative_pct[i, :].astype(np.float32).tolist(),
                "total": float(band_total[i]),
            }

        ts = float(self._ts_last) if self._ts_last > 0 else float(time.time())
        return {
            "ts": ts,
            "freq_hz": freq.astype(np.float32).tolist(),
            "channels": channels,
            "unit": unit,
            "display_fmin_hz": float(fmin),
            "display_fmax_hz": float(fmax),
            "sample_count": int(window.shape[1]),
            "average": {
                "label": "全通道平均",
                "channel_count": int(self.n_channels),
                "spectrum": average_psd.astype(np.float32).tolist(),
                "band_power": {
                    "absolute": average_band_power.astype(np.float32).tolist(),
                    "relative_pct": average_band_relative_pct.astype(np.float32).tolist(),
                    "total": average_band_total,
                },
            },
            "band_power": {
                "bands": [
                    {
                        "key": key,
                        "name": name,
                        "symbol": symbol,
                        "fmin_hz": low,
                        "fmax_hz": high,
                    }
                    for key, name, symbol, low, high in EEG_BANDS
                ],
                "channels": band_channels,
                "absolute_unit": "uV^2",
                "relative_unit": "%",
                "normalization": "sum_of_listed_bands",
                "normalization_fmin_hz": float(EEG_BANDS[0][3]),
                "normalization_fmax_hz": float(min(EEG_BANDS[-1][4], nyq)),
                "normalization_complete": bool(nyq >= EEG_BANDS[-1][4]),
            },
        }

    def get_update_interval_sec(self) -> float:
        """
        将更新频率转换为秒级间隔。
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
