#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: EEG 离线录制与导出服务（会话目录管理、raw 追加写入、可选带通滤波导出 CSV/EDF）

修改日志:
- 2026-05-03: 1.0.0 创建文件
- 2026-05-03: 1.0.1 EDF 导出改为分块写入以降低内存占用并减少失败概率
- 2026-05-03: 1.0.2 修复 EDF header 字段：pyedflib 需要 sex 键而非 gender
- 2026-05-03: 1.0.3 增加 50Hz 工频陷波：导出 raw/filtered 均先陷波再（可选）带通
- 2026-05-03: 1.0.4 导出链路统一使用“陷波+可选带通”流式处理，确保 raw/filtered 均执行 50Hz 陷波

作者: Spoon
版本: 1.0.4
"""

from __future__ import annotations

import csv
import json
import os
import queue
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from scipy.signal import butter, iirnotch, lfilter, lfilter_zi


@dataclass(frozen=True)
class OfflineSessionInfo:
    """
    离线录制会话信息。

    Attributes:
        session_id: 会话唯一标识（用于前端/接口传递）。
        session_dir: 会话目录绝对路径。
        started_at_iso: 会话开始时间（ISO8601）。
        stopped_at_iso: 会话停止时间（ISO8601，未停止则为 None）。
        sampling_rate_hz: 采样率。
        channel_names: 通道名列表（含可选触发通道）。
        total_samples: 总采样点数（逐采样点计数）。
        physical_unit: 物理单位（用于 EDF 元信息与 CSV 表头提示）。
        uv_per_count: 原始计数到 uV 的缩放因子（导出时应用）。
    """

    session_id: str
    session_dir: str
    started_at_iso: str
    stopped_at_iso: Optional[str]
    sampling_rate_hz: int
    channel_names: List[str]
    total_samples: int
    physical_unit: str
    uv_per_count: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "session_dir": self.session_dir,
            "started_at": self.started_at_iso,
            "stopped_at": self.stopped_at_iso,
            "sampling_rate_hz": int(self.sampling_rate_hz),
            "channel_names": list(self.channel_names),
            "total_samples": int(self.total_samples),
            "physical_unit": str(self.physical_unit),
            "uv_per_count": float(self.uv_per_count),
        }


@dataclass(frozen=True)
class BandpassConfig:
    """
    带通滤波配置。

    Attributes:
        enabled: 是否启用滤波。
        lowcut_hz: 低频截止（Hz）。
        highcut_hz: 高频截止（Hz）。
        order: 滤波器阶数。
    """

    enabled: bool
    lowcut_hz: float
    highcut_hz: float
    order: int = 5


@dataclass(frozen=True)
class ExportTarget:
    """
    导出目标描述。

    Attributes:
        kind: "raw" 或 "filtered"。
        fmt: "csv" 或 "edf"。
        filename: 目标文件名（不含路径）。
    """

    kind: str
    fmt: str
    filename: str


class _ChunkBinaryWriter:
    """
    raw 数据追加写入器：以 float32 行优先方式写入文件。

    设计要点：
        - append() 只做轻量队列入队，避免阻塞 FastAPI 事件循环；
        - 后台线程按入队顺序写入，保证样本顺序不乱。
    """

    def __init__(self, file_path: str):
        self._file_path = file_path
        self._q: "queue.Queue[Optional[np.ndarray]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop_requested = False
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        os.makedirs(os.path.dirname(self._file_path), exist_ok=True)
        self._thread = threading.Thread(target=self._run, name="offline-writer", daemon=True)
        self._thread.start()

    def append(self, arr: np.ndarray) -> None:
        if not self._started or self._stop_requested:
            return
        self._q.put(arr)

    def stop(self) -> None:
        if not self._started or self._stop_requested:
            return
        self._stop_requested = True
        self._q.put(None)
        if self._thread:
            self._thread.join(timeout=5.0)
        self._thread = None

    def _run(self) -> None:
        try:
            with open(self._file_path, "ab") as f:
                while True:
                    item = self._q.get()
                    if item is None:
                        return
                    f.write(item.tobytes(order="C"))
        except Exception:
            return


def _safe_filename(name: str, default_stem: str) -> str:
    v = str(name or "").strip()
    if not v:
        v = default_stem
    v = re.sub(r'[<>:"/\\\\|?*]+', "_", v)
    v = re.sub(r"\s+", " ", v).strip()
    v = v.strip(". ")
    return v or default_stem


def _ensure_ext(filename: str, ext: str) -> str:
    e = ext.lower().lstrip(".")
    if filename.lower().endswith(f".{e}"):
        return filename
    return f"{filename}.{e}"


def _butter_bandpass(lowcut_hz: float, highcut_hz: float, fs_hz: float, order: int) -> Tuple[np.ndarray, np.ndarray]:
    nyq = 0.5 * float(fs_hz)
    low = float(lowcut_hz) / nyq
    high = float(highcut_hz) / nyq
    b, a = butter(int(order), [low, high], btype="band")
    return b, a


def _iter_blocks(total: int, block_size: int) -> Iterable[Tuple[int, int]]:
    step = max(1, int(block_size))
    start = 0
    while start < total:
        end = min(total, start + step)
        yield start, end
        start = end


class OfflineService:
    """
    EEG 离线录制与导出服务。

    职责边界：
        - 管理“录制会话目录”的唯一确定性与元数据；
        - 在采集/推送过程中追加写入 raw 数据（float32）；
        - 在采集停止后按用户选择导出 CSV/EDF，并可另存滤波文件；
        - 不负责 BLE/LSL 的采集控制，仅消费上层传入的 chunk。
    """

    def __init__(
        self,
        project_root_dir: str,
        root_dir: str,
        sampling_rate_hz: int,
        channel_names: Sequence[str],
        trigger_enabled: bool,
        trigger_label: str,
        physical_unit: str,
        uv_per_count: float,
        notch_freq_hz: float,
        notch_quality_factor: float,
        filter_order_default: int,
        filter_lowcut_default_hz: float,
        filter_highcut_default_hz: float,
    ):
        self._project_root_dir = str(project_root_dir)
        self._root_dir = str(root_dir or "offlinedata")
        self._sampling_rate_hz = int(sampling_rate_hz)
        self._base_channel_names = [str(x) for x in (channel_names or [])]
        self._trigger_enabled = bool(trigger_enabled)
        self._trigger_label = str(trigger_label or "TRIG")
        self._physical_unit = str(physical_unit or "uV")
        self._uv_per_count = float(uv_per_count)
        self._notch_freq_hz = float(notch_freq_hz)
        self._notch_quality_factor = float(notch_quality_factor)
        self._filter_order_default = max(1, int(filter_order_default))
        self._filter_lowcut_default_hz = float(filter_lowcut_default_hz)
        self._filter_highcut_default_hz = float(filter_highcut_default_hz)

        self._active: Optional[OfflineSessionInfo] = None
        self._raw_path: Optional[str] = None
        self._meta_path: Optional[str] = None
        self._writer: Optional[_ChunkBinaryWriter] = None
        self._lock = threading.Lock()

    @property
    def active_session_id(self) -> Optional[str]:
        with self._lock:
            return self._active.session_id if self._active else None

    @property
    def filter_defaults(self) -> Dict[str, Any]:
        return {
            "order": int(self._filter_order_default),
            "lowcut_hz_default": float(self._filter_lowcut_default_hz),
            "highcut_hz_default": float(self._filter_highcut_default_hz),
        }

    def start_session(self) -> OfflineSessionInfo:
        """
        开始离线录制会话。

        Returns:
            OfflineSessionInfo: 新创建的会话信息。

        Raises:
            RuntimeError: 已存在进行中的会话。
        """
        with self._lock:
            if self._active is not None:
                raise RuntimeError("已有进行中的离线录制会话")

            now = datetime.now()
            date_part = now.strftime("%Y%m%d")
            time_part = now.strftime("%H%M%S")
            base_dir = os.path.join(self._project_root_dir, self._root_dir, date_part)
            os.makedirs(base_dir, exist_ok=True)

            idx = 0
            while True:
                folder = f"eeg_{time_part}_{idx:02d}"
                session_dir = os.path.join(base_dir, folder)
                if not os.path.exists(session_dir):
                    break
                idx += 1

            os.makedirs(session_dir, exist_ok=True)

            session_id = f"{date_part}_{folder}"
            ch_names = list(self._base_channel_names)
            if self._trigger_enabled:
                ch_names = ch_names + [self._trigger_label]

            info = OfflineSessionInfo(
                session_id=session_id,
                session_dir=session_dir,
                started_at_iso=now.isoformat(timespec="seconds"),
                stopped_at_iso=None,
                sampling_rate_hz=int(self._sampling_rate_hz),
                channel_names=ch_names,
                total_samples=0,
                physical_unit=self._physical_unit,
                uv_per_count=float(self._uv_per_count),
            )
            raw_path = os.path.join(session_dir, "raw_float32.bin")
            meta_path = os.path.join(session_dir, "meta.json")
            self._raw_path = raw_path
            self._meta_path = meta_path

            writer = _ChunkBinaryWriter(raw_path)
            writer.start()
            self._writer = writer
            self._active = info
            self._write_meta(info, status="recording")
            return info

    def append_chunk(self, chunk: List[List[float]]) -> None:
        """
        追加一个 LSL chunk 到当前会话。

        Args:
            chunk: 形如 [sample][channel] 的二维数组。
        """
        with self._lock:
            if self._active is None or self._writer is None:
                return
            expected_ch = len(self._active.channel_names)

        arr = np.asarray(chunk, dtype=np.float32)
        if arr.ndim != 2:
            return
        if expected_ch > 0 and arr.shape[1] < expected_ch:
            return
        if expected_ch > 0 and arr.shape[1] != expected_ch:
            arr = arr[:, :expected_ch]

        with self._lock:
            if self._active is None or self._writer is None:
                return
            self._active = OfflineSessionInfo(
                session_id=self._active.session_id,
                session_dir=self._active.session_dir,
                started_at_iso=self._active.started_at_iso,
                stopped_at_iso=self._active.stopped_at_iso,
                sampling_rate_hz=self._active.sampling_rate_hz,
                channel_names=self._active.channel_names,
                total_samples=int(self._active.total_samples + int(arr.shape[0])),
                physical_unit=self._active.physical_unit,
                uv_per_count=self._active.uv_per_count,
            )
            self._writer.append(arr)

    def stop_session(self) -> Optional[OfflineSessionInfo]:
        """
        停止当前会话并落盘元信息。

        Returns:
            Optional[OfflineSessionInfo]: 若存在会话则返回停止后的会话信息，否则返回 None。
        """
        with self._lock:
            if self._active is None:
                return None
            info = self._active
            writer = self._writer
            self._writer = None
            self._active = None
            raw_path = self._raw_path
            meta_path = self._meta_path
            self._raw_path = None
            self._meta_path = None

        if writer:
            writer.stop()

        stopped = OfflineSessionInfo(
            session_id=info.session_id,
            session_dir=info.session_dir,
            started_at_iso=info.started_at_iso,
            stopped_at_iso=datetime.now().isoformat(timespec="seconds"),
            sampling_rate_hz=info.sampling_rate_hz,
            channel_names=info.channel_names,
            total_samples=info.total_samples,
            physical_unit=info.physical_unit,
            uv_per_count=info.uv_per_count,
        )
        try:
            if raw_path:
                samples = self._infer_total_samples(raw_path, len(info.channel_names))
                if samples is not None:
                    stopped = OfflineSessionInfo(
                        session_id=stopped.session_id,
                        session_dir=stopped.session_dir,
                        started_at_iso=stopped.started_at_iso,
                        stopped_at_iso=stopped.stopped_at_iso,
                        sampling_rate_hz=stopped.sampling_rate_hz,
                        channel_names=stopped.channel_names,
                        total_samples=int(samples),
                        physical_unit=stopped.physical_unit,
                        uv_per_count=stopped.uv_per_count,
                    )
        except Exception:
            pass
        try:
            if meta_path:
                self._write_meta(stopped, status="stopped")
        except Exception:
            pass
        return stopped

    def load_session(self, session_id: str) -> OfflineSessionInfo:
        """
        读取会话元信息。

        Args:
            session_id: 会话 ID。

        Returns:
            OfflineSessionInfo: 会话信息。

        Raises:
            FileNotFoundError: meta.json 不存在或会话目录不存在。
            ValueError: meta.json 内容非法。
        """
        sid = str(session_id or "").strip()
        if not sid:
            raise ValueError("session_id 不能为空")
        session_dir = self._find_session_dir_by_id(sid)
        meta_path = os.path.join(session_dir, "meta.json")
        with open(meta_path, "r", encoding="utf-8") as f:
            raw = json.load(f) or {}
        ch_names = list(raw.get("channel_names") or [])
        return OfflineSessionInfo(
            session_id=str(raw.get("session_id") or sid),
            session_dir=session_dir,
            started_at_iso=str(raw.get("started_at") or ""),
            stopped_at_iso=str(raw.get("stopped_at") or "") or None,
            sampling_rate_hz=int(raw.get("sampling_rate_hz") or 0),
            channel_names=[str(x) for x in ch_names],
            total_samples=int(raw.get("total_samples") or 0),
            physical_unit=str(raw.get("physical_unit") or "uV"),
            uv_per_count=float(raw.get("uv_per_count") or 0.0),
        )

    def export(
        self,
        session_id: str,
        base_name_raw: str,
        targets: Sequence[ExportTarget],
        bandpass: Optional[BandpassConfig],
        base_name_filtered: Optional[str] = None,
        block_size_samples: int = 20000,
    ) -> Dict[str, Any]:
        """
        导出会话数据为 CSV/EDF。

        Args:
            session_id: 会话 ID。
            base_name_raw: 原始数据基名（不含扩展名）。
            targets: 导出目标列表。
            bandpass: 滤波配置（None 视为禁用）。
            base_name_filtered: 滤波文件基名（不含扩展名），为空则使用 base_name_raw + '_filtered'。
            block_size_samples: 逐块处理的采样点数，用于降低内存占用。

        Returns:
            Dict[str, Any]: {session_id, outputs:[{kind, fmt, path, samples, channels}]}。
        """
        info = self.load_session(session_id)
        session_dir = info.session_dir
        raw_path = os.path.join(session_dir, "raw_float32.bin")
        if not os.path.exists(raw_path):
            raise FileNotFoundError("raw 数据文件不存在")

        n_ch = len(info.channel_names)
        total_samples = self._infer_total_samples(raw_path, n_ch) or int(info.total_samples)
        if total_samples <= 0:
            raise ValueError("会话无数据，无法导出")

        raw_stem = _safe_filename(base_name_raw, default_stem="eeg")
        filtered_stem = _safe_filename(base_name_filtered or f"{raw_stem}_filtered", default_stem=f"{raw_stem}_filtered")

        kind_to_stem = {"raw": raw_stem, "filtered": filtered_stem}
        safe_targets: List[ExportTarget] = []
        for t in targets:
            k = str(t.kind or "").strip().lower()
            f = str(t.fmt or "").strip().lower()
            if k not in ("raw", "filtered"):
                continue
            if f not in ("csv", "edf"):
                continue
            safe_targets.append(ExportTarget(kind=k, fmt=f, filename=str(t.filename or "").strip()))
        if not safe_targets:
            return {"session_id": info.session_id, "outputs": []}

        want_filtered = any(t.kind == "filtered" for t in safe_targets)
        bp = bandpass or BandpassConfig(enabled=False, lowcut_hz=self._filter_lowcut_default_hz, highcut_hz=self._filter_highcut_default_hz, order=self._filter_order_default)
        if want_filtered and not bp.enabled:
            raise ValueError("已选择导出滤波文件，但未启用滤波")
        self._validate_bandpass(cfg=bp, sampling_rate_hz=int(info.sampling_rate_hz), need_enabled=want_filtered)

        data = np.memmap(raw_path, dtype=np.float32, mode="r")
        data = data.reshape((total_samples, n_ch))

        out_records: List[Dict[str, Any]] = []
        for target in safe_targets:
            stem = kind_to_stem.get(target.kind, raw_stem)
            if target.filename:
                fn = _safe_filename(target.filename, default_stem=stem)
            else:
                fn = stem
            fn = _ensure_ext(fn, target.fmt)
            out_path = os.path.join(session_dir, fn)

            if target.kind == "raw":
                self._export_one(data=data, info=info, out_path=out_path, fmt=target.fmt, block_size_samples=block_size_samples)
            else:
                self._export_filtered(
                    data=data,
                    info=info,
                    out_path=out_path,
                    fmt=target.fmt,
                    bandpass=bp,
                    block_size_samples=block_size_samples,
                )

            out_records.append(
                {
                    "kind": target.kind,
                    "fmt": target.fmt,
                    "path": out_path,
                    "samples": int(total_samples),
                    "channels": int(n_ch),
                }
            )

        return {"session_id": info.session_id, "outputs": out_records}

    def _validate_bandpass(self, cfg: BandpassConfig, sampling_rate_hz: int, need_enabled: bool) -> None:
        if not need_enabled:
            return
        if not cfg.enabled:
            raise ValueError("滤波未启用")
        fs = float(sampling_rate_hz)
        nyq = 0.5 * fs
        low = float(cfg.lowcut_hz)
        high = float(cfg.highcut_hz)
        order = int(cfg.order)
        if order < 1:
            raise ValueError("滤波器阶数必须 >= 1")
        if not (np.isfinite(low) and np.isfinite(high) and np.isfinite(nyq)):
            raise ValueError("滤波参数非法")
        if low <= 0 or high <= 0:
            raise ValueError("滤波截止频率必须 > 0")
        if not (high > low):
            raise ValueError("滤波参数非法：需要满足 低频截止 < 高频截止")
        if high >= nyq:
            raise ValueError(f"滤波参数非法：高频截止必须小于奈奎斯特频率 {nyq:g}Hz")

    def _export_filtered(
        self,
        data: np.ndarray,
        info: OfflineSessionInfo,
        out_path: str,
        fmt: str,
        bandpass: BandpassConfig,
        block_size_samples: int,
    ) -> None:
        scaled = self._scale_view(data=data, uv_per_count=info.uv_per_count)
        if fmt == "csv":
            self._write_csv_filtered(
                out_path=out_path,
                data=scaled,
                channel_names=info.channel_names,
                sampling_rate_hz=info.sampling_rate_hz,
                physical_unit=info.physical_unit,
                bandpass=bandpass,
                block_size_samples=block_size_samples,
            )
            return
        if fmt == "edf":
            self._write_edf_filtered(
                out_path=out_path,
                data=scaled,
                channel_names=info.channel_names,
                sampling_rate_hz=info.sampling_rate_hz,
                physical_unit=info.physical_unit,
                bandpass=bandpass,
                block_size_samples=block_size_samples,
            )
            return
        raise ValueError("不支持的导出格式")

    def _export_one(self, data: np.ndarray, info: OfflineSessionInfo, out_path: str, fmt: str, block_size_samples: int) -> None:
        scaled = self._scale_view(data=data, uv_per_count=info.uv_per_count)
        if fmt == "csv":
            self._write_csv(
                out_path=out_path,
                data=scaled,
                channel_names=info.channel_names,
                sampling_rate_hz=info.sampling_rate_hz,
                physical_unit=info.physical_unit,
                block_size_samples=block_size_samples,
            )
            return
        if fmt == "edf":
            self._write_edf(
                out_path=out_path,
                data=scaled,
                channel_names=info.channel_names,
                sampling_rate_hz=info.sampling_rate_hz,
                physical_unit=info.physical_unit,
                block_size_samples=block_size_samples,
            )
            return
        raise ValueError("不支持的导出格式")

    def _scale_view(self, data: np.ndarray, uv_per_count: float) -> np.ndarray:
        factor = float(uv_per_count)
        if not np.isfinite(factor) or factor <= 0:
            factor = 1.0
        if factor == 1.0:
            return data
        return data * factor

    def _design_notch(self, sampling_rate_hz: int) -> Tuple[np.ndarray, np.ndarray]:
        fs = float(sampling_rate_hz)
        f0 = float(self._notch_freq_hz)
        q = float(self._notch_quality_factor)
        if not np.isfinite(f0) or f0 <= 0:
            f0 = 50.0
        if not np.isfinite(q) or q <= 0:
            q = 30.0
        b, a = iirnotch(w0=f0, Q=q, fs=fs)
        return b, a

    def _iter_notch_bandpass_blocks(
        self,
        data: np.ndarray,
        sampling_rate_hz: int,
        bandpass: Optional[BandpassConfig],
        block_size_samples: int,
    ) -> Iterable[np.ndarray]:
        n_ch = int(data.shape[1])
        has_trigger = self._trigger_enabled and n_ch == (len(self._base_channel_names) + 1)
        n_filter_ch = n_ch - (1 if has_trigger else 0)
        if n_filter_ch <= 0:
            for s, e in _iter_blocks(int(data.shape[0]), int(block_size_samples)):
                yield np.asarray(data[s:e, :], dtype=np.float64)
            return

        b_n, a_n = self._design_notch(int(sampling_rate_hz))
        zi_n = lfilter_zi(b_n, a_n).astype(np.float64)
        states_n = np.tile(zi_n.reshape(1, -1), (n_filter_ch, 1))
        notch_primed = False

        use_bp = bool(bandpass and bandpass.enabled)
        b_b = a_b = None
        states_b = None
        bp_primed = False
        if use_bp:
            b_b, a_b = _butter_bandpass(float(bandpass.lowcut_hz), float(bandpass.highcut_hz), float(sampling_rate_hz), int(bandpass.order))
            zi_b = lfilter_zi(b_b, a_b).astype(np.float64)
            states_b = np.tile(zi_b.reshape(1, -1), (n_filter_ch, 1))

        for s, e in _iter_blocks(int(data.shape[0]), int(block_size_samples)):
            block = np.asarray(data[s:e, :], dtype=np.float64)
            if block.shape[0] <= 0:
                continue

            if not notch_primed:
                for ch in range(n_filter_ch):
                    states_n[ch] = states_n[ch] * float(block[0, ch])
                notch_primed = True

            y = np.empty_like(block, dtype=np.float64)
            for ch in range(n_filter_ch):
                yn, zf = lfilter(b_n, a_n, block[:, ch], zi=states_n[ch])
                states_n[ch] = zf
                y[:, ch] = yn
            if has_trigger:
                y[:, -1] = block[:, -1]

            if use_bp and b_b is not None and a_b is not None and states_b is not None:
                if not bp_primed:
                    for ch in range(n_filter_ch):
                        states_b[ch] = states_b[ch] * float(y[0, ch])
                    bp_primed = True
                out = np.empty_like(y, dtype=np.float64)
                for ch in range(n_filter_ch):
                    yb, zf = lfilter(b_b, a_b, y[:, ch], zi=states_b[ch])
                    states_b[ch] = zf
                    out[:, ch] = yb
                if has_trigger:
                    out[:, -1] = y[:, -1]
                yield out
            else:
                yield y

    def _bandpass_apply_block(
        self,
        block: np.ndarray,
        b: np.ndarray,
        a: np.ndarray,
        states: np.ndarray,
        n_filter_ch: int,
        has_trigger: bool,
    ) -> np.ndarray:
        out = np.empty_like(block, dtype=np.float64)
        for ch in range(n_filter_ch):
            y, zf = lfilter(b, a, block[:, ch], zi=states[ch])
            states[ch] = zf
            out[:, ch] = y
        if has_trigger:
            out[:, -1] = block[:, -1]
        return out

    def _bandpass_stream(self, data: np.ndarray, info: OfflineSessionInfo, cfg: BandpassConfig, block_size_samples: int) -> np.ndarray:
        if not cfg.enabled:
            return data
        n_ch = int(data.shape[1])
        has_trigger = self._trigger_enabled and n_ch == (len(self._base_channel_names) + 1)
        n_filter_ch = n_ch - (1 if has_trigger else 0)

        b, a = _butter_bandpass(cfg.lowcut_hz, cfg.highcut_hz, info.sampling_rate_hz, cfg.order)
        zi = lfilter_zi(b, a).astype(np.float64)
        states = np.tile(zi.reshape(1, -1), (n_filter_ch, 1))
        out = np.empty_like(data, dtype=np.float32)

        for s, e in _iter_blocks(int(data.shape[0]), int(block_size_samples)):
            block = np.asarray(data[s:e, :], dtype=np.float64)
            for ch in range(n_filter_ch):
                y, zf = lfilter(b, a, block[:, ch], zi=states[ch])
                states[ch] = zf
                out[s:e, ch] = y.astype(np.float32)
            if has_trigger:
                out[s:e, -1] = np.asarray(data[s:e, -1], dtype=np.float32)
        return out

    def _write_csv(
        self,
        out_path: str,
        data: np.ndarray,
        channel_names: Sequence[str],
        sampling_rate_hz: int,
        physical_unit: str,
        block_size_samples: int,
    ) -> None:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        header = [f"{str(ch)}({physical_unit})" for ch in channel_names]
        with open(out_path, "w", encoding="utf_8_sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["sampling_rate_hz", int(sampling_rate_hz)])
            w.writerow(header)
            for block in self._iter_notch_bandpass_blocks(
                data=data,
                sampling_rate_hz=int(sampling_rate_hz),
                bandpass=None,
                block_size_samples=int(block_size_samples),
            ):
                for row in block:
                    w.writerow([float(x) for x in row.tolist()])

    def _write_csv_filtered(
        self,
        out_path: str,
        data: np.ndarray,
        channel_names: Sequence[str],
        sampling_rate_hz: int,
        physical_unit: str,
        bandpass: BandpassConfig,
        block_size_samples: int,
    ) -> None:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        header = [f"{str(ch)}({physical_unit})" for ch in channel_names]

        with open(out_path, "w", encoding="utf_8_sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["sampling_rate_hz", int(sampling_rate_hz)])
            w.writerow(header)
            for block in self._iter_notch_bandpass_blocks(
                data=data,
                sampling_rate_hz=int(sampling_rate_hz),
                bandpass=bandpass,
                block_size_samples=int(block_size_samples),
            ):
                for row in block:
                    w.writerow([float(x) for x in row.tolist()])

    def _write_edf(
        self,
        out_path: str,
        data: np.ndarray,
        channel_names: Sequence[str],
        sampling_rate_hz: int,
        physical_unit: str,
        block_size_samples: int,
    ) -> None:
        try:
            import pyedflib
        except Exception as e:
            raise RuntimeError(f"缺少依赖 pyedflib：{e}")

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        n_ch = int(data.shape[1])

        ch_min = [float("inf")] * n_ch
        ch_max = [float("-inf")] * n_ch
        for block in self._iter_notch_bandpass_blocks(
            data=data,
            sampling_rate_hz=int(sampling_rate_hz),
            bandpass=None,
            block_size_samples=int(block_size_samples),
        ):
            bmin = np.min(block, axis=0)
            bmax = np.max(block, axis=0)
            for i in range(n_ch):
                ch_min[i] = float(min(ch_min[i], float(bmin[i])))
                ch_max[i] = float(max(ch_max[i], float(bmax[i])))

        header = {
            "technician": "",
            "patientname": "Anonymous",
            "recording_additional": "EEG Recording",
            "startdate": datetime.now(),
            "sex": "X",
            "birthdate": "",
            "patient_additional": "",
            "patientcode": "",
            "equipment": "",
            "admincode": "",
        }

        with pyedflib.EdfWriter(out_path, n_channels=n_ch) as writer:
            writer.setHeader(header)
            signal_headers = []
            for i, name in enumerate(channel_names):
                pmin = ch_min[i]
                pmax = ch_max[i]
                if not np.isfinite(pmin) or not np.isfinite(pmax) or pmin == pmax:
                    pmin = -100.0
                    pmax = 100.0
                signal_headers.append(
                    {
                        "label": str(name),
                        "dimension": str(physical_unit),
                        "sample_frequency": int(sampling_rate_hz),
                        "physical_min": float(pmin),
                        "physical_max": float(pmax),
                        "digital_min": -32768,
                        "digital_max": 32767,
                    }
                )
            writer.setSignalHeaders(signal_headers)
            for block in self._iter_notch_bandpass_blocks(
                data=data,
                sampling_rate_hz=int(sampling_rate_hz),
                bandpass=None,
                block_size_samples=int(block_size_samples),
            ):
                if block.shape[0] <= 0:
                    continue
                sigs = [block[:, i].copy() for i in range(n_ch)]
                writer.writeSamples(sigs)

    def _write_edf_filtered(
        self,
        out_path: str,
        data: np.ndarray,
        channel_names: Sequence[str],
        sampling_rate_hz: int,
        physical_unit: str,
        bandpass: BandpassConfig,
        block_size_samples: int,
    ) -> None:
        try:
            import pyedflib
        except Exception as e:
            raise RuntimeError(f"缺少依赖 pyedflib：{e}")

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        n_ch = int(data.shape[1])

        ch_min = [float("inf")] * n_ch
        ch_max = [float("-inf")] * n_ch
        for block in self._iter_notch_bandpass_blocks(
            data=data,
            sampling_rate_hz=int(sampling_rate_hz),
            bandpass=bandpass,
            block_size_samples=int(block_size_samples),
        ):
            bmin = np.min(block, axis=0)
            bmax = np.max(block, axis=0)
            for i in range(n_ch):
                ch_min[i] = float(min(ch_min[i], float(bmin[i])))
                ch_max[i] = float(max(ch_max[i], float(bmax[i])))

        header = {
            "technician": "",
            "patientname": "Anonymous",
            "recording_additional": "EEG Recording",
            "startdate": datetime.now(),
            "sex": "X",
            "birthdate": "",
            "patient_additional": "",
            "patientcode": "",
            "equipment": "",
            "admincode": "",
        }

        with pyedflib.EdfWriter(out_path, n_channels=n_ch) as writer:
            writer.setHeader(header)
            signal_headers = []
            for i, name in enumerate(channel_names):
                pmin = ch_min[i]
                pmax = ch_max[i]
                if not np.isfinite(pmin) or not np.isfinite(pmax) or pmin == pmax:
                    pmin = -100.0
                    pmax = 100.0
                signal_headers.append(
                    {
                        "label": str(name),
                        "dimension": str(physical_unit),
                        "sample_frequency": int(sampling_rate_hz),
                        "physical_min": float(pmin),
                        "physical_max": float(pmax),
                        "digital_min": -32768,
                        "digital_max": 32767,
                    }
                )
            writer.setSignalHeaders(signal_headers)
            for block in self._iter_notch_bandpass_blocks(
                data=data,
                sampling_rate_hz=int(sampling_rate_hz),
                bandpass=bandpass,
                block_size_samples=int(block_size_samples),
            ):
                if block.shape[0] <= 0:
                    continue
                sigs = [block[:, i].copy() for i in range(n_ch)]
                writer.writeSamples(sigs)

    def _write_meta(self, info: OfflineSessionInfo, status: str) -> None:
        if not self._meta_path:
            meta_path = os.path.join(info.session_dir, "meta.json")
        else:
            meta_path = self._meta_path
        payload = info.to_dict()
        payload["status"] = str(status)
        payload["raw_file"] = "raw_float32.bin"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _infer_total_samples(self, raw_path: str, n_ch: int) -> Optional[int]:
        if n_ch <= 0:
            return None
        size = os.path.getsize(raw_path)
        bytes_per_sample = int(n_ch) * 4
        if bytes_per_sample <= 0:
            return None
        return int(size // bytes_per_sample)

    def _find_session_dir_by_id(self, session_id: str) -> str:
        sid = str(session_id)
        base = os.path.join(self._project_root_dir, self._root_dir)
        if not os.path.isdir(base):
            raise FileNotFoundError("离线目录不存在")
        parts = sid.split("_", 1)
        if len(parts) != 2:
            raise FileNotFoundError("session_id 非法")
        date_part, folder = parts[0], parts[1]
        cand = os.path.join(base, date_part, folder)
        if os.path.isdir(cand):
            return cand
        raise FileNotFoundError("会话目录不存在")
