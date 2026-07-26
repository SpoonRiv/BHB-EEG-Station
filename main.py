#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 后端入口（FastAPI 应用、静态前端挂载、HTTP API、WebSocket 实时广播 EEG 数据）
作者: Spoon
"""

import asyncio
import queue
import threading
import os
import logging
import time
import socket
import webbrowser
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from configs.config_loader import load_config
from configs.local_overrides import get_local_override_path, load_yaml_file, write_yaml_file_atomic
from core.eeg_controller import EEGController
from core.lsl_streamer import LSLStreamer
from core.debug_bus import DebugEventBus 
from core.ble.commands import L1_COMMANDS, L2_COMMANDS
from core.ble.scanner import scan_devices
from core.ble.module_naming import parse_ble_module_name
from core.offline.offline_service import BandpassConfig, ExportTarget, OfflineService
from core.signal.notch_filter import NotchFilter, NotchFilterConfig
from core.signal.psd_worker import PsdWorker, PsdWorkerConfig
from core.trigger.trigger_service import TriggerService, TriggerServiceConfig
from ws_hub_eeg import EegWsHub, EegWsHubConfig
from ws_hub_impedance import ImpedanceWsHub, ImpedanceWsHubConfig
from ws_hub_psd import PsdWsHub, PsdWsHubConfig

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class NoCacheStaticFiles(StaticFiles):
    """
    禁用静态资源缓存，确保前端刷新时总是读取最新文件。
    """

    async def get_response(self, path: str, scope) -> Any:
        resp = await super().get_response(path, scope)
        try:
            resp.headers["Cache-Control"] = "no-store"
        except Exception:
            pass
        return resp

class AppState:
    def __init__(self):
        self.config_path = os.path.join(os.path.dirname(__file__), "configs", "config.yaml")
        self.local_override_path = get_local_override_path(self.config_path)
        self.config = load_config(self.config_path)
        self.controller = EEGController(config_path=self.config_path)
        self.debug_bus = DebugEventBus(max_events=self.config.debug.max_events)
        self._debug_forward_started = False
        self._debug_forward_queue_id: Optional[int] = None
        def _on_trigger_event(command: str, source: str) -> bool:
            ok = False
            try:
                ok = bool(self.controller.send_trigger_command(command=str(command), source=str(source)))
            except Exception:
                ok = False
            if not bool(self.config.debug.ui_enabled):
                return ok
            self.debug_bus.publish(tag="TRIGGER", message=f"收到 {command}", data={"source": str(source), "delivered": bool(ok)})
            return ok
        self.trigger = TriggerService(
            TriggerServiceConfig(
                enabled=bool(self.config.trigger.enabled),
                host=str(self.config.trigger.host),
                port=int(self.config.trigger.port),
                timeout_sec=float(self.config.trigger.timeout_sec),
            ),
            on_event=_on_trigger_event,
        )

        lsl_name = self.config.eeg.lsl.stream_name
        lsl_type = self.config.eeg.lsl.stream_type
        buffer_size = self.config.streaming.buffer_size
        resolve_timeout_sec = self.config.streaming.lsl_resolve_timeout_sec
        resolve_retry_interval_sec = self.config.streaming.lsl_resolve_retry_interval_sec

        self.streamer = LSLStreamer(
            stream_name=lsl_name,
            stream_type=lsl_type,
            buffer_size=buffer_size,
            resolve_timeout_sec=resolve_timeout_sec,
            resolve_retry_interval_sec=resolve_retry_interval_sec,
        )
        self.offline = OfflineService(
            project_root_dir=os.path.dirname(__file__),
            root_dir=self.config.offline.root_dir,
            sampling_rate_hz=self.config.eeg.sampling_rate_hz,
            channel_names=self.config.eeg.channel_names,
            trigger_enabled=self.config.eeg.lsl.include_trigger_channel,
            trigger_label=self.config.offline.export.trigger_label,
            physical_unit=self.config.offline.export.physical_unit,
            count_divisor=self.config.offline.export.count_divisor,
            notch_freq_hz=self.config.signal.notch.freq_hz,
            notch_quality_factor=self.config.signal.notch.quality_factor,
            filter_order_default=self.config.offline.filter.order,
            filter_lowcut_default_hz=self.config.offline.filter.lowcut_hz_default,
            filter_highcut_default_hz=self.config.offline.filter.highcut_hz_default,
            writer_queue_max_chunks=self.config.offline.writer_queue_max_chunks,
            writer_queue_full_policy=self.config.offline.writer_queue_full_policy,
        )
        channel_count = int(self.config.eeg.n_channels) + (1 if self.config.eeg.lsl.include_trigger_channel else 0)
        self.notch = NotchFilter(
            NotchFilterConfig(
                sampling_rate_hz=int(self.config.eeg.sampling_rate_hz),
                freq_hz=float(self.config.signal.notch.freq_hz),
                quality_factor=float(self.config.signal.notch.quality_factor),
                channel_count=channel_count,
                has_trigger_channel=bool(self.config.eeg.lsl.include_trigger_channel),
            )
        )
        self.eeg_ws_hub = EegWsHub(
            EegWsHubConfig(
                max_pending_chunks=int(self.config.streaming.ws_queue_max_chunks),
                send_timeout_sec=float(self.config.streaming.ws_send_timeout_sec),
            )
        )
        self.eeg_ws_hub.set_transform(self._apply_signal_preprocess_safe)

        imp_name = self.config.impedance.lsl.stream_name
        imp_type = self.config.impedance.lsl.stream_type
        imp_buffer_size = int(self.config.impedance.streaming.buffer_size)
        resolve_timeout_sec = self.config.streaming.lsl_resolve_timeout_sec
        resolve_retry_interval_sec = self.config.streaming.lsl_resolve_retry_interval_sec
        self.imp_streamer = LSLStreamer(
            stream_name=imp_name,
            stream_type=imp_type,
            buffer_size=imp_buffer_size,
            resolve_timeout_sec=resolve_timeout_sec,
            resolve_retry_interval_sec=resolve_retry_interval_sec,
        )
        self.imp_ws_hub = ImpedanceWsHub(
            ImpedanceWsHubConfig(
                send_timeout_sec=float(self.config.streaming.ws_send_timeout_sec),
                queue_size=1,
            )
        )

        psd_cfg = getattr(self.config.signal, "psd", None)
        self.psd_ws_hub = PsdWsHub(
            PsdWsHubConfig(
                send_timeout_sec=float(self.config.streaming.ws_send_timeout_sec),
                queue_size=1,
            )
        )
        self.psd_worker = None
        if psd_cfg is not None:
            try:
                self.psd_worker = PsdWorker(
                    PsdWorkerConfig(
                        enabled=bool(getattr(psd_cfg, "enabled", True)),
                        window_sec=float(getattr(psd_cfg, "window_sec", 2.0)),
                        update_hz=float(getattr(psd_cfg, "update_hz", 2.0)),
                        nfft=int(getattr(psd_cfg, "nfft", 512)),
                        fmin_hz=float(getattr(psd_cfg, "fmin_hz", 0.5)),
                        fmax_hz=float(getattr(psd_cfg, "fmax_hz", 80.0)),
                        to_db=bool(getattr(psd_cfg, "to_db", True)),
                        apply_notch=bool(getattr(psd_cfg, "apply_notch", True)),
                    ),
                    sampling_rate_hz=int(self.config.eeg.sampling_rate_hz),
                    eeg_channel_names=list(self.config.eeg.channel_names),
                    count_divisor=float(self.config.offline.export.count_divisor),
                    has_trigger_channel=bool(self.config.eeg.lsl.include_trigger_channel),
                    notch_freq_hz=float(self.config.signal.notch.freq_hz),
                    notch_quality_factor=float(self.config.signal.notch.quality_factor),
                )
            except Exception:
                self.psd_worker = None
        self._psd_task: Optional[asyncio.Task] = None
        self._psd_ingest_queue: Optional[queue.Queue] = None
        self._psd_ingest_stop: Optional[threading.Event] = None
        self._psd_ingest_thread: Optional[threading.Thread] = None

    def start_psd(self) -> None:
        """
        启动 PSD 计算与推送。
        """
        if self.psd_worker is None:
            return
        if not bool(self.psd_worker.cfg.enabled):
            return
        if self._psd_task and not self._psd_task.done():
            return
        if self._psd_ingest_queue is None:
            self._psd_ingest_queue = queue.Queue(maxsize=2)
        if self._psd_ingest_stop is None:
            self._psd_ingest_stop = threading.Event()
        if self._psd_ingest_thread is None or not self._psd_ingest_thread.is_alive():
            self._psd_ingest_thread = threading.Thread(target=self._psd_ingest_loop, daemon=True)
            self._psd_ingest_thread.start()
        self.psd_ws_hub.start()
        self._psd_task = asyncio.create_task(self._psd_loop())

    def stop_psd(self) -> None:
        """
        停止 PSD 计算与推送，并清空缓存。
        """
        if self._psd_task is not None:
            try:
                self._psd_task.cancel()
            except Exception:
                pass
            self._psd_task = None
        self.psd_ws_hub.stop(clear_pending=True)
        if self._psd_ingest_stop is not None:
            try:
                self._psd_ingest_stop.set()
            except Exception:
                pass
        if self._psd_ingest_thread is not None:
            try:
                self._psd_ingest_thread.join(timeout=0.4)
            except Exception:
                pass
        self._psd_ingest_thread = None
        self._psd_ingest_stop = None
        self._psd_ingest_queue = None
        if self.psd_worker is not None:
            try:
                self.psd_worker.reset()
            except Exception:
                pass

    def _psd_ingest_loop(self) -> None:
        if self.psd_worker is None:
            return
        stop = self._psd_ingest_stop
        q = self._psd_ingest_queue
        if stop is None or q is None:
            return
        had_clients = False
        while True:
            if stop.is_set():
                return
            has_clients = bool(getattr(self.psd_ws_hub, "has_clients", None) and self.psd_ws_hub.has_clients())
            if not has_clients:
                if had_clients:
                    had_clients = False
                    try:
                        self.psd_worker.reset()
                    except Exception:
                        pass
                try:
                    q.get(timeout=0.1)
                except Exception:
                    pass
                continue
            if not had_clients:
                had_clients = True
                try:
                    self.psd_worker.reset()
                except Exception:
                    pass
            try:
                item = q.get(timeout=0.2)
            except Exception:
                continue
            try:
                if item:
                    self.psd_worker.append_chunk(item)
            except Exception:
                continue

    async def _psd_loop(self) -> None:
        """
        按配置频率计算 PSD 并推送最新结果。
        """
        if self.psd_worker is None:
            return
        interval = float(self.psd_worker.get_update_interval_sec())
        if interval <= 0:
            interval = 0.5
        while True:
            try:
                await asyncio.sleep(interval)
                if not bool(getattr(self.psd_ws_hub, "has_clients", None) and self.psd_ws_hub.has_clients()):
                    continue
                window = self.psd_worker.snapshot_window()
                if window is None:
                    continue
                payload = await asyncio.to_thread(self.psd_worker.compute_psd_payload, window)
                if payload:
                    self.psd_ws_hub.enqueue_latest(payload)  # type: ignore[arg-type]
            except asyncio.CancelledError:
                return
            except Exception:
                await asyncio.sleep(0.1)

    def _load_local_raw(self) -> Dict[str, Any]:
        return load_yaml_file(self.local_override_path)

    def _save_local_raw(self, raw: Dict[str, Any]) -> None:
        write_yaml_file_atomic(self.local_override_path, raw)

    def get_pending_channel_selection(self) -> Tuple[int, List[str], str]:
        raw = self._load_local_raw()
        ui = raw.get("ui", {}) if isinstance(raw, dict) else {}
        sel = ui.get("channel_selection", {}) if isinstance(ui, dict) else {}
        mode = int(sel.get("n_channels", sel.get("mode_channels", 0)) or 0) if isinstance(sel, dict) else 0
        names_raw = sel.get("channel_names", []) if isinstance(sel, dict) else []
        ref = str(sel.get("ref_channel_name", "") or "").strip() if isinstance(sel, dict) else ""
        names: List[str] = []
        if isinstance(names_raw, list):
            for x in names_raw:
                s = str(x or "").strip()
                if s:
                    names.append(s)
        if mode <= 0:
            mode = int(self.config.eeg.n_channels)
        if not names:
            names = list(self.config.eeg.channel_names)
        if not ref:
            ref = str(self.config.eeg.ref_channel_name or "").strip()
        return mode, names, ref

    def set_pending_channel_selection(self, n_channels: int, channel_names: List[str], ref_channel_name: str) -> None:
        raw = self._load_local_raw()
        ui = raw.get("ui", {}) if isinstance(raw.get("ui", {}), dict) else {}
        ui["channel_selection"] = {
            "n_channels": int(n_channels),
            "channel_names": list(channel_names),
            "ref_channel_name": str(ref_channel_name or "").strip(),
        }
        raw["ui"] = ui
        self._save_local_raw(raw)

    def get_local_channel_presets(self) -> List[Dict[str, Any]]:
        raw = self._load_local_raw()
        ui = raw.get("ui", {}) if isinstance(raw, dict) else {}
        presets_raw = ui.get("channel_presets_local", []) if isinstance(ui, dict) else []
        presets: List[Dict[str, Any]] = []
        if isinstance(presets_raw, list):
            for item in presets_raw:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "") or "").strip()
                if not name:
                    continue
                try:
                    mode = int(item.get("n_channels", item.get("mode_channels", 0)))
                except Exception:
                    mode = 0
                ch_raw = item.get("channel_names", []) or []
                ch: List[str] = []
                if isinstance(ch_raw, list):
                    for x in ch_raw:
                        s = str(x or "").strip()
                        if s:
                            ch.append(s)
                if mode <= 0 or not ch:
                    continue
                ref = str(item.get("ref_channel_name", "") or "").strip()
                if not ref:
                    ref = str(self.config.eeg.ref_channel_name or "").strip()
                presets.append({"name": name, "n_channels": mode, "channel_names": ch, "ref_channel_name": ref})
        return presets

    def upsert_local_channel_preset(self, name: str, n_channels: int, channel_names: List[str], ref_channel_name: str) -> None:
        raw = self._load_local_raw()
        ui = raw.get("ui", {}) if isinstance(raw.get("ui", {}), dict) else {}
        presets_raw = ui.get("channel_presets_local", []) if isinstance(ui.get("channel_presets_local", []), list) else []
        out: List[Dict[str, Any]] = []
        normalized_name = str(name or "").strip()
        normalized_ref = str(ref_channel_name or "").strip()
        for item in presets_raw:
            if not isinstance(item, dict):
                continue
            n = str(item.get("name", "") or "").strip()
            if not n or n == normalized_name:
                continue
            out.append(item)
        out.append({"name": normalized_name, "n_channels": int(n_channels), "channel_names": list(channel_names), "ref_channel_name": normalized_ref})
        ui["channel_presets_local"] = out
        raw["ui"] = ui
        self._save_local_raw(raw)

    def delete_local_channel_preset(self, name: str) -> bool:
        raw = self._load_local_raw()
        ui = raw.get("ui", {}) if isinstance(raw.get("ui", {}), dict) else {}
        presets_raw = ui.get("channel_presets_local", []) if isinstance(ui.get("channel_presets_local", []), list) else []
        out: List[Dict[str, Any]] = []
        normalized_name = str(name or "").strip()
        removed = False
        for item in presets_raw:
            if not isinstance(item, dict):
                continue
            n = str(item.get("name", "") or "").strip()
            if n == normalized_name:
                removed = True
                continue
            out.append(item)
        ui["channel_presets_local"] = out
        raw["ui"] = ui
        self._save_local_raw(raw)
        return removed

    def apply_pending_channel_selection_to_effective_config(self) -> None:
        mode, names, ref = self.get_pending_channel_selection()
        raw = self._load_local_raw()
        eeg = raw.get("eeg", {}) if isinstance(raw.get("eeg", {}), dict) else {}
        eeg["n_channels"] = int(mode)
        eeg["channel_names"] = list(names)
        eeg["ref_channel_name"] = str(ref or "").strip()
        raw["eeg"] = eeg
        self._save_local_raw(raw)

    def reload_config_for_channels(self) -> None:
        self.config = load_config(self.config_path)
        self.controller.config = self.config
        self.offline = OfflineService(
            project_root_dir=os.path.dirname(__file__),
            root_dir=self.config.offline.root_dir,
            sampling_rate_hz=self.config.eeg.sampling_rate_hz,
            channel_names=self.config.eeg.channel_names,
            trigger_enabled=self.config.eeg.lsl.include_trigger_channel,
            trigger_label=self.config.offline.export.trigger_label,
            physical_unit=self.config.offline.export.physical_unit,
            count_divisor=self.config.offline.export.count_divisor,
            notch_freq_hz=self.config.signal.notch.freq_hz,
            notch_quality_factor=self.config.signal.notch.quality_factor,
            filter_order_default=self.config.offline.filter.order,
            filter_lowcut_default_hz=self.config.offline.filter.lowcut_hz_default,
            filter_highcut_default_hz=self.config.offline.filter.highcut_hz_default,
            writer_queue_max_chunks=self.config.offline.writer_queue_max_chunks,
            writer_queue_full_policy=self.config.offline.writer_queue_full_policy,
        )
        channel_count = int(self.config.eeg.n_channels) + (1 if self.config.eeg.lsl.include_trigger_channel else 0)
        self.notch = NotchFilter(
            NotchFilterConfig(
                sampling_rate_hz=int(self.config.eeg.sampling_rate_hz),
                freq_hz=float(self.config.signal.notch.freq_hz),
                quality_factor=float(self.config.signal.notch.quality_factor),
                channel_count=channel_count,
                has_trigger_channel=bool(self.config.eeg.lsl.include_trigger_channel),
            )
        )
        self.eeg_ws_hub.set_transform(self._apply_signal_preprocess_safe)

    def _apply_signal_preprocess_safe(self, chunk: List[List[float]]) -> List[List[float]]:
        """
        对实时 EEG 数据应用预处理；失败时回退到原始数据。
        """
        out = chunk
        try:
            out = self.notch.apply(out)
        except Exception:
            out = chunk
        return self._scale_eeg_chunk_like_legacy(out)

    def _scale_eeg_chunk_like_legacy(self, chunk: List[List[float]]) -> List[List[float]]:
        """
        按 count_divisor 缩放 EEG 通道，触发通道保持原值。
        """
        if not chunk:
            return chunk
        try:
            divisor = float(self.config.offline.export.count_divisor)
        except Exception:
            divisor = 120.0
        if not (divisor > 0):
            divisor = 120.0
        if divisor == 1.0:
            return chunk

        n_eeg = int(self.config.eeg.n_channels)
        has_trigger = bool(self.config.eeg.lsl.include_trigger_channel)
        out: List[List[float]] = []
        for s in chunk:
            if not s:
                out.append(s)
                continue
            if has_trigger and len(s) >= n_eeg + 1:
                eeg_scaled = [float(x) / divisor for x in s[:n_eeg]]
                trig = float(s[n_eeg])
                out.append(eeg_scaled + [trig] + [float(x) for x in s[n_eeg + 1 :]])
                continue
            out.append([float(x) / divisor for x in s])
        return out

    def on_lsl_chunk(self, chunk: List[List[float]]) -> None:
        """
        LSL 数据回调：写入离线会话，并转发到实时显示链路。
        """
        try:
            self.offline.append_chunk(chunk)
        except Exception:
            pass
        if self.psd_worker is not None and self._psd_ingest_queue is not None:
            if bool(getattr(self.psd_ws_hub, "has_clients", None) and self.psd_ws_hub.has_clients()):
                try:
                    self._psd_ingest_queue.put_nowait(chunk)
                except queue.Full:
                    try:
                        self._psd_ingest_queue.get_nowait()
                    except Exception:
                        pass
                    try:
                        self._psd_ingest_queue.put_nowait(chunk)
                    except Exception:
                        pass
        self.eeg_ws_hub.enqueue(chunk)

    def on_imp_lsl_chunk(self, chunk: List[List[float]]) -> None:
        """
        阻抗 LSL 数据回调：仅推送最新一帧。
        """
        if not chunk:
            return
        last = chunk[-1]
        try:
            self.imp_ws_hub.enqueue_latest([float(x) for x in last])
        except Exception:
            pass

    async def ensure_debug_forwarding(self) -> None:
        """
        确保调试事件转发任务绑定到当前采集进程的 debug_queue。

        当蓝牙断联后重新连接时，控制器会创建新的 multiprocessing.Queue。
        这里按当前队列身份自动重绑，避免转发任务长期卡在旧队列上。
        """
        if not bool(self.config.debug.ui_enabled):
            await self.stop_debug_forwarding()
            return
        self.debug_bus.bind_loop(asyncio.get_running_loop())
        current_queue = self.controller.debug_queue
        current_queue_id = id(current_queue) if current_queue is not None else None
        if current_queue_id is None:
            await self.stop_debug_forwarding()
            return
        if self._debug_forward_started and self._debug_forward_queue_id == current_queue_id:
            return
        await self.stop_debug_forwarding()
        self.debug_bus.start_forward_from_mp_queue(current_queue)
        self._debug_forward_started = True
        self._debug_forward_queue_id = current_queue_id

    async def stop_debug_forwarding(self) -> None:
        """
        停止调试事件队列转发任务，并清空当前绑定状态。
        """
        if self._debug_forward_started:
            await self.debug_bus.stop_forward()
        self._debug_forward_started = False
        self._debug_forward_queue_id = None

    def _has_runtime_activity(self) -> bool:
        """
        判断当前是否仍残留需要清理的运行态资源。
        """
        return any(
            [
                bool(getattr(self.streamer, "is_streaming", False)),
                bool(getattr(self.imp_streamer, "is_streaming", False)),
                bool(getattr(self.controller, "task_running", False)),
                bool(getattr(self.trigger, "server_running", False)),
                bool(self._debug_forward_started),
            ]
        )

    def should_reset_runtime_for_device(self, device_status: Optional[Dict[str, Any]]) -> bool:
        """
        根据设备状态判断是否需要执行断联后的运行态清理。

        设计说明：
            - 仅在设备已经不可用，但前端相关运行态仍残留时返回 True；
            - 已连接但处于空闲态（如 `idle/ready/connected`）不应触发清理；
            - 该判断用于修复异常断联后 `lsl_streaming/task_running` 等状态未及时复位的问题。
        """
        if not self._has_runtime_activity():
            return False
        dev = device_status if isinstance(device_status, dict) else {}
        running = bool(dev.get("running", False))
        last = dev.get("last") if isinstance(dev.get("last"), dict) else {}
        last_type = str(last.get("type", "") or "").strip().lower()
        if running and last_type in {"connected", "ready", "connecting", "idle"}:
            return False
        if last_type in {"disconnected", "error", "stopped"}:
            return True
        return not running

    def reset_runtime_after_device_loss(self) -> None:
        """
        在设备异常断联或进程退出后，统一清理前端相关运行态资源。

        清理目标：
            - EEG/阻抗 LSL 拉流与 WebSocket 推送；
            - PSD 后处理；
            - trigger 服务端与离线会话。
        """
        self.eeg_ws_hub.stop(clear_pending=True)
        self.stop_psd()
        self.streamer.stop()
        self.imp_ws_hub.stop(clear_pending=True)
        self.imp_streamer.stop()
        try:
            self.trigger.stop_server()
        except Exception:
            pass
        try:
            self.offline.stop_session()
        except Exception:
            pass

    async def reconcile_runtime_with_device(self, device_status: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        将运行态资源与当前设备状态对齐，并返回对齐后的最新设备状态。
        """
        if self.should_reset_runtime_for_device(device_status):
            self.reset_runtime_after_device_loss()
            await self.stop_debug_forwarding()
            return self.controller.get_status()
        return device_status if isinstance(device_status, dict) else self.controller.get_status()

state = AppState()


def shutdown_runtime() -> None:
    """
    关闭数据流、后台服务和采集进程。
    """
    state.eeg_ws_hub.stop(clear_pending=True)
    state.stop_psd()
    state.streamer.stop()
    state.imp_ws_hub.stop(clear_pending=True)
    state.imp_streamer.stop()
    try:
        state.trigger.stop_server()
    except Exception:
        pass
    try:
        state.offline.stop_session()
    except Exception:
        pass
    state.controller.stop_mode("eeg")
    state.controller.stop_mode("impedance")
    state.controller.stop_mode("tdcs")
    state.controller.stop_device()


def schedule_process_exit(delay_sec: float = 0.6) -> None:
    """
    在短延时后退出当前服务进程。
    """

    def _exit_later() -> None:
        """
        等待响应发出后退出进程。
        """
        try:
            time.sleep(max(0.1, float(delay_sec)))
        finally:
            os._exit(0)

    threading.Thread(target=_exit_later, daemon=True).start()


def schedule_foreground_window_minimize(delay_sec: float = 0.12) -> None:
    """
    捕获当前 Windows 前台窗口，并在响应发出后将其最小化。

    浏览器页面无法直接调用系统级最小化能力，因此由本地后端通过
    Windows API 操作用户点击按钮时所在的前台浏览器窗口。

    Args:
        delay_sec: 执行最小化前的短暂延时，确保 HTTP 响应先返回。

    Raises:
        RuntimeError: 当前平台不是 Windows，或无法获取有效前台窗口。
    """
    if os.name != "nt":
        raise RuntimeError("窗口最小化仅支持 Windows")

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindowAsync.restype = wintypes.BOOL

    window_handle = user32.GetForegroundWindow()
    if not window_handle or not user32.IsWindow(window_handle):
        raise RuntimeError("未找到可最小化的前台窗口")

    def _minimize_later() -> None:
        """
        等待前端收到响应后，最小化点击按钮时捕获到的窗口。
        """
        time.sleep(max(0.0, float(delay_sec)))
        if user32.IsWindow(window_handle):
            user32.ShowWindowAsync(window_handle, 6)

    threading.Thread(target=_minimize_later, daemon=True).start()


def get_browser_launch_url(host: str, port: int) -> str:
    """
    根据监听地址生成适合本机浏览器访问的 URL。

    Args:
        host: 服务监听地址。
        port: 服务监听端口。

    Returns:
        str: 用于打开首页的完整 URL。
    """
    normalized_host = str(host or "").strip()
    if normalized_host in {"", "0.0.0.0", "::", "[::]"}:
        normalized_host = "127.0.0.1"
    return f"http://{normalized_host}:{int(port)}/"


def resolve_offline_session_dir(session_id: str) -> str:
    """
    根据离线会话 ID 解析其对应的会话目录。

    Args:
        session_id: 离线会话 ID。

    Returns:
        str: 形如 `.../offlinedata/20260718/eeg_203602` 的会话目录绝对路径。

    Raises:
        ValueError: 会话 ID 为空，或解析出的目录不在离线根目录内。
        FileNotFoundError: 会话目录不存在。
    """
    sid = str(session_id or "").strip()
    if not sid:
        raise ValueError("session_id 不能为空")

    info = state.offline.load_session(sid)
    session_dir = os.path.abspath(str(info.session_dir))
    offline_root = os.path.abspath(os.path.join(os.path.dirname(__file__), state.config.offline.root_dir))

    try:
        if os.path.commonpath([session_dir, offline_root]) != offline_root:
            raise ValueError("目标目录不在离线数据根目录内")
    except ValueError as e:
        raise ValueError("目标目录不在离线数据根目录内") from e

    if not os.path.isdir(session_dir):
        raise FileNotFoundError(f"会话目录不存在：{session_dir}")
    return session_dir


def open_directory_with_system(path: str) -> str:
    """
    使用系统默认文件管理器打开指定目录。

    Args:
        path: 需要打开的目录绝对路径。

    Returns:
        str: 实际打开的目录绝对路径。

    Raises:
        FileNotFoundError: 目录不存在。
        RuntimeError: 当前系统无法打开目录。
    """
    target_dir = os.path.abspath(str(path or "").strip())
    if not os.path.isdir(target_dir):
        raise FileNotFoundError(f"目录不存在：{target_dir}")
    if hasattr(os, "startfile"):
        os.startfile(target_dir)
        return target_dir
    opened = webbrowser.open(f"file:///{target_dir.replace(os.sep, '/')}", new=1)
    if not opened:
        raise RuntimeError("系统文件管理器打开失败")
    return target_dir


def open_browser_when_server_ready(host: str, port: int, timeout_sec: float = 15.0) -> None:
    """
    在服务端口就绪后，使用系统默认浏览器打开上位机首页。

    设计说明：
        - 仅用于 `python main.py` 的本地直接启动场景；
        - 通过后台线程轮询端口可用性，避免浏览器过早打开导致页面不可访问；
        - 若超时仍未监听成功，则静默放弃，不影响后端正常启动。

    Args:
        host: 服务监听地址。
        port: 服务监听端口。
        timeout_sec: 等待端口就绪的最长时长（秒）。
    """
    browser_host = str(host or "").strip()
    connect_host = browser_host
    if connect_host in {"", "0.0.0.0", "::", "[::]"}:
        connect_host = "127.0.0.1"
    launch_url = get_browser_launch_url(host=browser_host, port=port)
    deadline = time.time() + max(1.0, float(timeout_sec))

    while time.time() < deadline:
        try:
            with socket.create_connection((connect_host, int(port)), timeout=0.5):
                webbrowser.open(launch_url, new=2)
                return
        except Exception:
            time.sleep(0.25)

class BleConnectRequest(BaseModel):
    address: Optional[str] = None
    name: Optional[str] = None


class ModeRequest(BaseModel):
    mode: str


class TwoLevelCommandRequest(BaseModel):
    l1: int
    l2: int
    data: Optional[List[int]] = None


class OfflineExportTargetRequest(BaseModel):
    kind: str
    fmt: str
    filename: Optional[str] = None


class OfflineBandpassRequest(BaseModel):
    enabled: bool = False
    lowcut_hz: float
    highcut_hz: float
    order: Optional[int] = None


class OfflineExportRequest(BaseModel):
    session_id: str
    base_name_raw: str = "eeg"
    base_name_filtered: Optional[str] = None
    targets: List[OfflineExportTargetRequest]
    bandpass: Optional[OfflineBandpassRequest] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 生命周期管理：启动时注册数据流回调，关闭时停止设备。
    """
    logging.info("Application starting: registering callbacks...")
    state.streamer.add_callback(state.on_lsl_chunk)
    state.imp_streamer.add_callback(state.on_imp_lsl_chunk)
    if state.config.debug.ui_enabled:
        await state.ensure_debug_forwarding()
    yield
    logging.info("Application shutting down: cleaning up resources...")
    state.eeg_ws_hub.stop(clear_pending=True)
    state.streamer.stop()
    state.imp_ws_hub.stop(clear_pending=True)
    state.imp_streamer.stop()
    try:
        state.trigger.stop_server()
    except Exception:
        pass
    await asyncio.to_thread(state.controller.stop_device)
    await state.stop_debug_forwarding()

app = FastAPI(title="BHB EEGSuite Web API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载前端静态资源
app.mount("/web", NoCacheStaticFiles(directory="web"), name="web")


@app.get("/")
async def root():
    return RedirectResponse(url="/web/index.html")


@app.get("/api/start")
async def start_eeg():
    """启动蓝牙设备与 LSL 数据流"""
    if state.config.debug.ui_enabled:
        state.debug_bus.publish(tag="UI", message="点击开始采集", data={})
    if bool(getattr(state.config, "trigger", None) and state.config.trigger.enabled):
        try:
            await asyncio.to_thread(state.trigger.start_server)
        except Exception as e:
            if state.config.debug.ui_enabled:
                state.debug_bus.publish(tag="UI", message="trigger 服务端启动失败", data={})
            return {"status": "error", "message": "trigger 服务端启动失败，请检查端口占用或配置。", "detail": str(e)}
    success = True
    if not state.controller.is_running():
        success = await asyncio.to_thread(state.controller.start_device)
        if not success:
            last = state.controller.last_status or {"type": "error", "message": "启动失败"}
            if state.config.debug.ui_enabled:
                state.debug_bus.publish(tag="UI", message="开始采集失败", data={"reason": last.get("message", "")})
            return {"status": "error", "message": last.get("message", "启动失败"), "detail": last, "device": state.controller.get_status()}
    state.controller.select_mode("eeg")
    state.controller.start_mode("eeg")
    if success:
        await state.ensure_debug_forwarding()
        try:
            state.notch.reset()
        except Exception:
            pass
        state.streamer.start()
        return {"status": "success", "message": "蓝牙采集已启动并连接成功。", "device": state.controller.get_status()}
    last = state.controller.last_status or {"type": "error", "message": "启动失败"}
    if state.config.debug.ui_enabled:
        state.debug_bus.publish(tag="UI", message="开始采集失败", data={"reason": last.get("message", "")})
    return {"status": "error", "message": last.get("message", "启动失败"), "detail": last, "device": state.controller.get_status()}

@app.get("/api/config")
async def get_config():
    """
    获取前端渲染所需的基础配置（通道数、通道名等）。
    """
    _, _, pending_ref = state.get_pending_channel_selection()
    ui_version = getattr(state.config, "app_ui_version", "1.0.0")
    eeg_n_channels = int(state.config.eeg.n_channels)
    device_status = state.controller.get_status()
    tdcs_raw = (device_status.get("capabilities", {}) if isinstance(device_status, dict) else {}).get("tdcs", None)
    tdcs_capable_known = bool(isinstance(tdcs_raw, bool))
    tdcs_capable = bool(tdcs_raw) if tdcs_capable_known else False
    imp_n_channels = int(state.config.impedance.n_channels)
    imp_names = list(state.config.eeg.channel_names[:imp_n_channels])
    if bool(state.config.impedance.frame.include_bias):
        imp_names.append("BIAS")
    if bool(state.config.impedance.frame.include_tdcs_if_ch8) and imp_n_channels == 8 and (not tdcs_capable_known or tdcs_capable):
        imp_names.append("tDCS")
    layout = getattr(state.config.eeg, "montage_1020_layout", None)
    layout_payload = None
    if layout is not None:
        layout_payload = {
            "name": str(layout.name or ""),
            "coord_system": str(layout.coord_system or ""),
            "positions": {k: {"x": float(v.x), "y": float(v.y)} for k, v in (layout.positions or {}).items()},
            "aliases": dict(layout.aliases or {}),
        }
    return {
        "ui_version": ui_version,
        "ref_channel_name": str(pending_ref or ""),
        "ui": {
            "waveform": {
                "time_window_sec": float(state.config.ui.waveform.time_window_sec),
                "render_fps_hz": int(state.config.ui.waveform.render_fps_hz),
                "max_render_points_per_channel": int(state.config.ui.waveform.max_render_points_per_channel),
                "global_scale": bool(state.config.ui.waveform.global_scale),
                "max_pending_ws_chunks": int(getattr(state.config.ui.waveform, "max_pending_ws_chunks", 2)),
                "y_axis_step": float(getattr(state.config.ui.waveform, "y_axis_step", 50.0)),
                "y_axis_update_hz": float(getattr(state.config.ui.waveform, "y_axis_update_hz", 2.0)),
                "y_axis_dynamic_default": bool(getattr(state.config.ui.waveform, "y_axis_dynamic_default", True)),
                "y_axis_fixed_max_default": float(getattr(state.config.ui.waveform, "y_axis_fixed_max_default", 500.0)),
                "y_axis_fixed_max_min": float(getattr(state.config.ui.waveform, "y_axis_fixed_max_min", 50.0)),
                "y_axis_fixed_max_max": float(getattr(state.config.ui.waveform, "y_axis_fixed_max_max", 1500.0)),
                "y_axis_fixed_max_step": float(getattr(state.config.ui.waveform, "y_axis_fixed_max_step", 50.0)),
            }
        },
        "n_channels": eeg_n_channels,
        "channel_names": state.config.eeg.channel_names,
        "sampling_rate_hz": state.config.eeg.sampling_rate_hz,
        "electrode_layout_1020": layout_payload,
        "impedance": {
            "enabled": bool(state.config.impedance.enabled),
            "n_channels": imp_n_channels,
            "channel_names": imp_names,
            "ui": {
                "refresh_hz": int(state.config.impedance.ui.refresh_hz),
                "good_max_ohm": int(state.config.impedance.ui.good_max_ohm),
                "warn_max_ohm": int(state.config.impedance.ui.warn_max_ohm),
                "slider_max_ohm": int(state.config.impedance.ui.slider_max_ohm),
                "slider_step_ohm": int(state.config.impedance.ui.slider_step_ohm),
            },
        },
        "tdcs": {
            "enabled": bool(getattr(state.config, "tdcs", None) and state.config.tdcs.enabled),
            "capable": bool(tdcs_capable) if tdcs_capable_known else None,
            "effective_enabled": bool(getattr(state.config, "tdcs", None) and state.config.tdcs.enabled) and (not tdcs_capable_known or tdcs_capable),
            "supported_channel_modes": list(getattr(state.config, "tdcs", None) and state.config.tdcs.supported_channel_modes or []),
            "ui": {
                "show_reserved": bool(getattr(state.config, "tdcs", None) and state.config.tdcs.ui.show_reserved),
            },
        },
        "trigger": {
            "enabled": bool(getattr(state.config, "trigger", None) and state.config.trigger.enabled),
            "active": getattr(state.trigger, "active", None),
            "server_running": bool(getattr(state.trigger, "server_running", False)),
        },
        "buffer_size": state.config.streaming.buffer_size,
        "ws_send_fps_hz": state.config.streaming.ws_send_fps_hz,
        "signal": {
            "notch": {
                "freq_hz": float(state.config.signal.notch.freq_hz),
                "quality_factor": float(state.config.signal.notch.quality_factor),
            },
            "psd": {
                "enabled": bool(getattr(state.config.signal.psd, "enabled", True)),
                "window_sec": float(getattr(state.config.signal.psd, "window_sec", 2.0)),
                "update_hz": float(getattr(state.config.signal.psd, "update_hz", 2.0)),
                "nfft": int(getattr(state.config.signal.psd, "nfft", 512)),
                "fmin_hz": float(getattr(state.config.signal.psd, "fmin_hz", 0.5)),
                "fmax_hz": float(getattr(state.config.signal.psd, "fmax_hz", 80.0)),
                "to_db": bool(getattr(state.config.signal.psd, "to_db", True)),
                "apply_notch": bool(getattr(state.config.signal.psd, "apply_notch", True)),
            },
        },
        "offline": {
            "root_dir": state.config.offline.root_dir,
            "physical_unit": state.config.offline.export.physical_unit,
            "count_divisor": state.config.offline.export.count_divisor,
            "trigger_label": state.config.offline.export.trigger_label,
            "filter_defaults": state.offline.filter_defaults,
            "notch": {
                "freq_hz": float(state.config.signal.notch.freq_hz),
                "quality_factor": float(state.config.signal.notch.quality_factor),
            },
        },
    }


@app.post("/api/trigger/start")
async def trigger_start():
    if state.config.debug.ui_enabled:
        state.debug_bus.publish(tag="UI", message="点击开始 trigger", data={})
    try:
        if bool(getattr(state.config, "trigger", None) and state.config.trigger.enabled) and not bool(getattr(state.trigger, "server_running", False)):
            await asyncio.to_thread(state.trigger.start_server)
        await asyncio.to_thread(state.trigger.start)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"trigger start 失败: {e}") from e
    return {"status": "success", "message": "trigger start 已发送"}


@app.post("/api/trigger/stop")
async def trigger_stop():
    if state.config.debug.ui_enabled:
        state.debug_bus.publish(tag="UI", message="点击停止 trigger", data={})
    try:
        await asyncio.to_thread(state.trigger.stop)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"trigger stop 失败: {e}") from e
    return {"status": "success", "message": "trigger end 已发送"}


class ChannelSelectionRequest(BaseModel):
    n_channels: int
    channel_names: List[str]
    ref_channel_name: Optional[str] = None


class ChannelPresetRequest(BaseModel):
    name: str
    n_channels: int
    channel_names: List[str]
    ref_channel_name: Optional[str] = None


class ChannelPresetDeleteRequest(BaseModel):
    name: str


def _normalize_channel_list(items: List[str]) -> List[str]:
    out: List[str] = []
    for x in items or []:
        s = str(x or "").strip()
        if not s:
            continue
        if s not in out:
            out.append(s)
    return out


@app.get("/api/eeg/channel/options")
async def eeg_channel_options():
    """
    获取 10-20 通道选择相关元信息（可选电极/预设/当前选择）。
    """
    pending_mode, pending_names, pending_ref = state.get_pending_channel_selection()
    available = list(state.config.eeg.montage_1020_channels or [])
    if not available:
        base = list(state.config.eeg.channel_names or [])
        ref = str(state.config.eeg.ref_channel_name or "").strip()
        if ref:
            base.append(ref)
        available = _normalize_channel_list(base)
    presets_cfg = [
        {"scope": "config", "name": p.name, "n_channels": int(p.n_channels), "channel_names": list(p.channel_names), "ref_channel_name": str(p.ref_channel_name or "")}
        for p in (state.config.eeg.presets or [])
    ]
    presets_local = [{"scope": "local", **p} for p in state.get_local_channel_presets()]
    layout = getattr(state.config.eeg, "montage_1020_layout", None)
    layout_payload = None
    if layout is not None:
        layout_payload = {
            "name": str(layout.name or ""),
            "coord_system": str(layout.coord_system or ""),
            "positions": {k: {"x": float(v.x), "y": float(v.y)} for k, v in (layout.positions or {}).items()},
            "aliases": dict(layout.aliases or {}),
        }
    return {
        "selectable_channel_modes": list(state.config.eeg.selectable_channel_modes or []),
        "supported_channel_modes": list(state.config.eeg.supported_channel_modes or []),
        "available_channels": available,
        "electrode_layout_1020": layout_payload,
        "ref_candidates": _normalize_channel_list(list(state.config.eeg.ref_selectable_channels or [])),
        "presets": presets_cfg + presets_local,
        "effective": {
            "n_channels": int(state.config.eeg.n_channels),
            "channel_names": list(state.config.eeg.channel_names),
            "ref_channel_name": str(state.config.eeg.ref_channel_name or ""),
        },
        "pending": {
            "n_channels": int(pending_mode),
            "channel_names": list(pending_names),
            "ref_channel_name": str(pending_ref or ""),
        },
    }


@app.get("/api/eeg/channel/selection")
async def eeg_channel_get_selection():
    """
    获取当前“待应用”的通道选择（本机覆盖配置 ui.channel_selection）。
    """
    mode, names, ref = state.get_pending_channel_selection()
    return {"n_channels": int(mode), "channel_names": list(names), "ref_channel_name": str(ref or "")}


@app.post("/api/eeg/channel/selection")
async def eeg_channel_set_selection(req: ChannelSelectionRequest):
    """
    保存“待应用”的通道选择（不影响正在运行的采集；仅用于 UI 记忆与后续应用）。
    """
    mode = int(req.n_channels)
    names = _normalize_channel_list(req.channel_names or [])
    ref = str(req.ref_channel_name or "").strip()
    if mode <= 0:
        raise HTTPException(status_code=400, detail="n_channels 必须为正整数")
    selectable = set(int(x) for x in (state.config.eeg.selectable_channel_modes or []))
    if selectable and mode not in selectable:
        raise HTTPException(status_code=400, detail=f"当前不提供 {mode} 通道电极选择")
    if len(names) > mode:
        raise HTTPException(status_code=400, detail="channel_names 数量不能超过 n_channels")
    available = set(_normalize_channel_list(list(state.config.eeg.montage_1020_channels or [])))
    if available:
        for n in names:
            if n not in available:
                raise HTTPException(status_code=400, detail=f"非法通道名：{n}")
    if ref:
        if available and ref not in available:
            raise HTTPException(status_code=400, detail=f"非法参考电极名：{ref}")
    state.set_pending_channel_selection(mode, names, ref)
    return {"status": "success", "n_channels": mode, "channel_names": names, "ref_channel_name": ref}


@app.post("/api/eeg/channel/apply")
async def eeg_channel_apply():
    """
    将“待应用”的通道选择写入本机覆盖配置 eeg.* 并热重载（不会写入 config.yaml）。
    """
    if bool(getattr(state.streamer, "is_streaming", False)):
        raise HTTPException(status_code=409, detail="EEG 正在推流中，禁止切换通道配置")

    mode, names, ref = state.get_pending_channel_selection()
    supported = set(int(x) for x in (state.config.eeg.supported_channel_modes or []))
    if supported and int(mode) not in supported:
        raise HTTPException(status_code=400, detail=f"当前不支持 {mode} 通道模式")
    if len(names) != int(mode):
        raise HTTPException(status_code=400, detail=f"请先选择满 {mode} 个通道，再点击应用")
    if not ref:
        ref = str(state.config.eeg.ref_channel_name or "").strip()
    candidates = _normalize_channel_list(list(state.config.eeg.ref_selectable_channels or []))
    if not ref and candidates:
        ref = candidates[0]
    if not ref:
        raise HTTPException(status_code=400, detail="请先选择参考电极，再点击应用")
    available = set(_normalize_channel_list(list(state.config.eeg.montage_1020_channels or [])))
    if available and ref not in available:
        raise HTTPException(status_code=400, detail=f"非法参考电极名：{ref}")

    if state.controller.is_running() and int(mode) != int(state.config.eeg.n_channels):
        raise HTTPException(status_code=409, detail="设备已连接，切换8/16通道需先断开蓝牙再应用")

    state.apply_pending_channel_selection_to_effective_config()
    state.reload_config_for_channels()

    return {
        "status": "success",
        "effective": {
            "n_channels": int(state.config.eeg.n_channels),
            "channel_names": list(state.config.eeg.channel_names),
            "ref_channel_name": str(state.config.eeg.ref_channel_name or ""),
        },
    }


@app.post("/api/eeg/channel/presets/local")
async def eeg_channel_preset_upsert(req: ChannelPresetRequest):
    """
    新增/更新本机常用通道组合（写入 config.local.yaml 的 ui.channel_presets_local）。
    """
    name = str(req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name 不能为空")
    mode = int(req.n_channels)
    names = _normalize_channel_list(req.channel_names or [])
    ref = str(req.ref_channel_name or "").strip()
    if mode <= 0:
        raise HTTPException(status_code=400, detail="n_channels 必须为正整数")
    if len(names) != mode:
        raise HTTPException(status_code=400, detail=f"channel_names 数量必须等于 n_channels（{mode}）")
    available = set(_normalize_channel_list(list(state.config.eeg.montage_1020_channels or [])))
    if available:
        for n in names:
            if n not in available:
                raise HTTPException(status_code=400, detail=f"非法通道名：{n}")
    if not ref:
        ref = str(state.config.eeg.ref_channel_name or "").strip()
    candidates = _normalize_channel_list(list(state.config.eeg.ref_selectable_channels or []))
    if not ref and candidates:
        ref = candidates[0]
    if not ref:
        raise HTTPException(status_code=400, detail="ref_channel_name 不能为空")
    if available and ref not in available:
        raise HTTPException(status_code=400, detail=f"非法参考电极名：{ref}")
    state.upsert_local_channel_preset(name=name, n_channels=mode, channel_names=names, ref_channel_name=ref)
    return {"status": "success"}


@app.post("/api/eeg/channel/presets/local/delete")
async def eeg_channel_preset_delete(req: ChannelPresetDeleteRequest):
    """
    删除本机常用通道组合（按 name 匹配）。
    """
    name = str(req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name 不能为空")
    removed = state.delete_local_channel_preset(name)
    return {"status": "success" if removed else "error", "removed": bool(removed)}

@app.get("/api/status")
async def get_status():
    """
    获取采集状态（用于前端连接指示与设备名展示）。
    """
    device_status = state.controller.get_status()
    device_status = await state.reconcile_runtime_with_device(device_status)
    return {
        "device": device_status,
        "lsl_streaming": bool(getattr(state.streamer, "is_streaming", False)),
        "lsl": state.streamer.get_status() if hasattr(state.streamer, "get_status") else None,
        "impedance_lsl_streaming": bool(getattr(state.imp_streamer, "is_streaming", False)),
        "impedance_lsl": state.imp_streamer.get_status() if hasattr(state.imp_streamer, "get_status") else None,
    }

@app.get("/api/stop")
async def stop_eeg():
    """停止蓝牙设备与 LSL 数据流"""
    if state.config.debug.ui_enabled:
        state.debug_bus.publish(tag="UI", message="点击停止采集", data={})
    state.eeg_ws_hub.stop(clear_pending=False)
    state.streamer.stop()
    state.controller.stop_mode("eeg")
    try:
        state.trigger.stop_server()
    except Exception:
        pass
    session = None
    try:
        session = state.offline.stop_session()
    except Exception:
        session = None
    success = await asyncio.to_thread(state.controller.stop_device)
    await state.stop_debug_forwarding()
    if success:
        return {"status": "success", "message": "采集已停止。", "device": state.controller.get_status(), "offline": {"session": session.to_dict() if session else None}}
    return {"status": "error", "message": "停止采集失败。", "device": state.controller.get_status(), "offline": {"session": session.to_dict() if session else None}}


@app.get("/api/ble/devices")
async def ble_devices(timeout_sec: float = 3.0, whitelist_only: bool = True):
    """
    扫描周边 BLE 设备（用于前端下拉选择）。

    Args:
        timeout_sec: 单次扫描时长（秒）。
        whitelist_only: 是否仅返回配置 bluetooth.device_names 命中的设备（前缀匹配）。
    """
    try:
        results = await scan_devices(timeout_sec=timeout_sec)
    except Exception as e:
        logging.exception("BLE scan failed")
        raise HTTPException(
            status_code=500,
            detail="蓝牙扫描失败，请确认系统蓝牙已开启、已授予本程序蓝牙权限，且设备已上电可被发现。",
        ) from e
    allowed = set(str(x) for x in (state.config.bluetooth.device_names or []))
    out: List[Dict[str, Any]] = []
    for one in results:
        if whitelist_only and allowed:
            one_name = str(one.name or "")
            if not any(prefix and one_name.startswith(str(prefix)) for prefix in allowed):
                continue
        info = parse_ble_module_name(str(one.name or ""), str(state.config.bluetooth.module_name_regex or ""))
        module = None
        capabilities = None
        if info is not None:
            module = {"eeg_channels": int(info.eeg_channels), "stim_channels": int(info.stim_channels)}
            capabilities = {"tdcs": bool(int(info.stim_channels) > 0)}
        elif str(one.name or "").strip() == "MSM":
            capabilities = {"tdcs": False}
        out.append({"name": one.name, "address": one.address, "rssi": one.rssi, "module": module, "capabilities": capabilities})
    out.sort(key=lambda x: (x["rssi"] is None, -(x["rssi"] or -9999), x["name"]))
    return {"devices": out}


@app.post("/api/ble/connect")
async def ble_connect(req: BleConnectRequest):
    """
    建立 BLE 连接（连接与业务模式解耦）。
    """
    current_status = state.controller.get_status()
    await state.reconcile_runtime_with_device(current_status)
    success = await asyncio.to_thread(state.controller.start_device, req.address, req.name)
    if success:
        await state.ensure_debug_forwarding()
    if success:
        return {"status": "success", "message": "蓝牙已连接。", "device": state.controller.get_status()}
    last = state.controller.last_status or {"type": "error", "message": "连接失败"}
    return {"status": "error", "message": last.get("message", "连接失败"), "detail": last, "device": state.controller.get_status()}


@app.post("/api/ble/disconnect")
async def ble_disconnect():
    """
    断开 BLE 连接并停止相关后台任务。
    """
    state.eeg_ws_hub.stop(clear_pending=True)
    state.streamer.stop()
    state.imp_ws_hub.stop(clear_pending=True)
    state.imp_streamer.stop()
    state.controller.stop_mode("eeg")
    state.controller.stop_mode("impedance")
    try:
        state.offline.stop_session()
    except Exception:
        pass
    success = await asyncio.to_thread(state.controller.stop_device)
    await state.stop_debug_forwarding()
    if success:
        return {"status": "success", "message": "蓝牙已断开。", "device": state.controller.get_status()}
    return {"status": "error", "message": "断开失败。", "device": state.controller.get_status()}


@app.post("/api/app/shutdown")
async def app_shutdown():
    """
    执行应用关机：断开蓝牙、停止后台任务，并在响应后退出当前服务进程。
    """
    try:
        await asyncio.to_thread(shutdown_runtime)
        if state.config.debug.ui_enabled:
            try:
                await state.stop_debug_forwarding()
            except Exception:
                pass
        schedule_process_exit()
        return {"status": "success", "message": "系统关闭中。"}
    except Exception as e:
        logging.exception("Application shutdown failed")
        raise HTTPException(status_code=500, detail=f"系统关闭失败：{e}") from e


@app.post("/api/app/minimize")
async def app_minimize():
    """
    最小化用户点击按钮时所在的 Windows 前台窗口。
    """
    try:
        schedule_foreground_window_minimize()
        return {"status": "success", "message": "窗口正在最小化。"}
    except Exception as e:
        logging.exception("Application window minimize failed")
        raise HTTPException(status_code=500, detail=f"窗口最小化失败：{e}") from e


@app.get("/api/control/commands")
async def get_two_level_commands():
    """
    获取协议中定义的两级指令列表（用于前端控制面板生成按钮与输入项）。
    """
    l1_list: List[Dict[str, Any]] = []
    for l1 in sorted(L1_COMMANDS.keys()):
        m1 = L1_COMMANDS[l1]
        l2_items = []
        for l2 in sorted(L2_COMMANDS.get(l1, {}).keys()):
            m2 = L2_COMMANDS[l1][l2]
            l2_items.append(
                {
                    "l2": int(l2),
                    "l2_hex": f"0x{int(l2) & 0xFF:02X}",
                    "name": m2.name,
                    "desc": m2.desc,
                    "help": str(getattr(m2, "help", "") or ""),
                    "payload_spec": str(m2.payload_spec or "none"),
                }
            )
        l1_list.append(
            {
                "l1": int(l1),
                "l1_hex": f"0x{int(l1) & 0xFF:02X}",
                "name": m1.name,
                "desc": m1.desc,
                "payload_spec": str(m1.payload_spec or "none"),
                "children": l2_items,
            }
        )
    return {"commands": l1_list}


@app.post("/api/control/send")
async def send_two_level_command(req: TwoLevelCommandRequest):
    """
    下发两级控制指令（一级 + 二级 + 附加数据）。
    """
    l1 = int(req.l1) & 0xFF
    l2 = int(req.l2) & 0xFF
    data: List[int] = []
    if req.data is not None:
        if not isinstance(req.data, list):
            raise HTTPException(status_code=400, detail="data 必须为整数列表")
        for x in req.data:
            try:
                v = int(x)
            except Exception:
                raise HTTPException(status_code=400, detail="data 必须为整数列表")
            if v < 0 or v > 255:
                raise HTTPException(status_code=400, detail="data 元素必须在 0-255 范围内")
            data.append(v & 0xFF)
    if len(data) > 64:
        raise HTTPException(status_code=400, detail="data 长度不能超过 64 字节")
    ok = state.controller.send_two_level_command(l1=l1, l2=l2, data=data)
    if not ok:
        return {"status": "error", "message": "设备未连接或采集进程未运行，无法下发指令", "device": state.controller.get_status()}
    return {
        "status": "success",
        "message": "指令已投递到采集进程（请在调试输出中查看 CMD_TX）",
        "cmd": [l1, l2, *data],
        "device": state.controller.get_status(),
    }


@app.post("/api/mode/select")
async def select_mode(req: ModeRequest):
    """
    选择模式（不自动开始）。
    """
    ok = state.controller.select_mode(req.mode)
    if not ok:
        return {"status": "error", "message": "设备未连接或模式选择失败", "device": state.controller.get_status()}
    return {"status": "success", "message": "模式已选择", "device": state.controller.get_status()}


@app.post("/api/mode/start")
async def start_mode(req: ModeRequest):
    """
    启动模式（向设备下发 start 指令）。EEG 模式会同时启动 LSL->WS 推送。
    """
    if req.mode == "eeg":
        if bool(getattr(state.streamer, "is_streaming", False)):
            return {"status": "error", "message": "EEG 正在采集中，请先停止采集", "device": state.controller.get_status()}
        if bool(getattr(state.config, "trigger", None) and state.config.trigger.enabled):
            try:
                await asyncio.to_thread(state.trigger.start_server)
            except Exception as e:
                return {"status": "error", "message": "trigger 服务端启动失败，请检查端口占用或配置。", "detail": str(e), "device": state.controller.get_status()}
        state.controller.select_mode("eeg")
        ok = state.controller.start_mode("eeg")
        if ok:
            try:
                session = state.offline.start_session()
            except Exception as e:
                state.controller.stop_mode("eeg")
                return {"status": "error", "message": f"创建离线会话失败：{e}", "device": state.controller.get_status()}
            state.streamer.start()
            state.eeg_ws_hub.start()
            return {
                "status": "success",
                "message": "EEG 已启动",
                "device": state.controller.get_status(),
                "offline": {"session": session.to_dict(), "filter_defaults": state.offline.filter_defaults},
            }
        return {"status": "error", "message": "EEG 启动失败", "device": state.controller.get_status()}
    if req.mode == "impedance":
        state.controller.select_mode("impedance")
        ok = state.controller.start_mode("impedance")
        if ok and bool(state.config.impedance.enabled):
            state.imp_streamer.start()
            state.imp_ws_hub.start()
        return {"status": "success" if ok else "error", "message": "模式已启动" if ok else "模式启动失败", "device": state.controller.get_status()}
    ok = state.controller.start_mode(req.mode)
    return {"status": "success" if ok else "error", "message": "模式已启动" if ok else "模式启动失败", "device": state.controller.get_status()}


@app.post("/api/mode/stop")
async def stop_mode(req: ModeRequest):
    """
    停止模式（向设备下发 stop 指令）。EEG 模式会同时停止 LSL->WS 推送。
    """
    if req.mode == "eeg":
        state.eeg_ws_hub.stop(clear_pending=True)
        state.stop_psd()
        state.streamer.stop()
        ok = state.controller.stop_mode("eeg")
        session = None
        try:
            session = state.offline.stop_session()
        except Exception:
            session = None
        return {
            "status": "success" if ok else "error",
            "message": "EEG 已停止" if ok else "EEG 停止失败",
            "device": state.controller.get_status(),
            "offline": {"session": session.to_dict() if session else None},
        }
    if req.mode == "impedance":
        state.imp_ws_hub.stop(clear_pending=True)
        state.imp_streamer.stop()
    ok = state.controller.stop_mode(req.mode)
    return {"status": "success" if ok else "error", "message": "模式已停止" if ok else "模式停止失败", "device": state.controller.get_status()}


@app.post("/api/offline/export")
async def offline_export(req: OfflineExportRequest):
    """
    导出离线会话数据为 CSV/EDF，并支持可选带通滤波另存。
    """
    try:
        if not str(req.session_id or "").strip():
            raise HTTPException(status_code=400, detail="session_id 不能为空")
        if not str(req.base_name_raw or "").strip():
            raise HTTPException(status_code=400, detail="base_name_raw 不能为空")

        targets = [ExportTarget(kind=x.kind, fmt=x.fmt, filename=x.filename or "") for x in (req.targets or [])]
        if not targets:
            raise HTTPException(status_code=400, detail="targets 不能为空")

        bp = None
        if req.bandpass is not None:
            order = int(req.bandpass.order) if req.bandpass.order else int(state.config.offline.filter.order)
            bp = BandpassConfig(
                enabled=bool(req.bandpass.enabled),
                lowcut_hz=float(req.bandpass.lowcut_hz),
                highcut_hz=float(req.bandpass.highcut_hz),
                order=order,
            )
        result = await asyncio.to_thread(
            state.offline.export,
            req.session_id,
            req.base_name_raw,
            targets,
            bp,
            req.base_name_filtered,
        )
        return {"status": "success", "result": result}
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"离线导出失败：{e}")


@app.get("/api/offline/session")
async def offline_session(session_id: str):
    """
    查询离线会话元信息，并附带派生指标（采集时长、数据尺寸等）。

    Args:
        session_id: 会话 ID（形如 YYYYMMDD_eeg_HHMMSS；若重名会追加 _NN）
    """
    sid = str(session_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="session_id 不能为空")
    try:
        info = state.offline.load_session(sid)
        raw_path = os.path.join(info.session_dir, "raw_float32.bin")
        raw_bytes = int(os.path.getsize(raw_path)) if os.path.isfile(raw_path) else 0
        n_ch = int(len(info.channel_names))
        total_samples = int(info.total_samples)
        sr = int(info.sampling_rate_hz) if int(info.sampling_rate_hz) > 0 else 0
        data_sec = (float(total_samples) / float(sr)) if sr > 0 else None

        wall_clock_sec = None
        try:
            if info.started_at_iso and info.stopped_at_iso:
                t0 = datetime.fromisoformat(str(info.started_at_iso))
                t1 = datetime.fromisoformat(str(info.stopped_at_iso))
                wall_clock_sec = max(0.0, float((t1 - t0).total_seconds()))
        except Exception:
            wall_clock_sec = None

        return {
            "status": "success",
            "session": info.to_dict(),
            "derived": {
                "channels": n_ch,
                "raw_bytes": raw_bytes,
                "raw_mib": float(raw_bytes) / (1024.0 * 1024.0) if raw_bytes >= 0 else 0.0,
                "data_duration_sec": data_sec,
                "wall_clock_sec": wall_clock_sec,
            },
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取会话失败：{e}")


@app.post("/api/offline/open-folder")
async def offline_open_folder(session_id: str):
    """
    打开离线会话目录，便于用户直接查看当前会话的导出文件。

    Args:
        session_id: 会话 ID（形如 `20260718_eeg_101530`）。
    """
    sid = str(session_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="session_id 不能为空")
    try:
        session_dir = resolve_offline_session_dir(sid)
        opened_dir = await asyncio.to_thread(open_directory_with_system, session_dir)
        return {"status": "success", "session_id": sid, "opened_dir": opened_dir}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"打开文件夹失败：{e}")

@app.get("/api/debug/events")
async def get_debug_events(limit: int = 200):
    """
    获取最近调试事件（用于调试界面初次加载补发）。
    """
    if not state.config.debug.ui_enabled:
        return {"enabled": False, "events": []}
    return {"enabled": True, "events": state.debug_bus.get_recent(limit=limit)}

@app.websocket("/ws/debug")
async def debug_ws(websocket: WebSocket):
    """
    调试事件 WebSocket：仅推送“调试事件”，不推送网络/蓝牙连接信息。
    """
    if not state.config.debug.ui_enabled:
        await websocket.close()
        return
    await websocket.accept()
    state.debug_bus.register_ws(websocket)
    try:
        await websocket.send_json({"type": "debug_init", "events": state.debug_bus.get_recent(limit=200)})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        state.debug_bus.unregister_ws(websocket)

@app.websocket("/ws/eeg")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket 端点，前端连接以获取实时 EEG 数据
    """
    await websocket.accept()
    state.eeg_ws_hub.register(websocket)
    logging.info("Frontend WebSocket connected.")
    try:
        while True:
            # 保持连接
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        state.eeg_ws_hub.unregister(websocket)
        logging.info("Frontend WebSocket disconnected.")


@app.websocket("/ws/psd")
async def psd_ws(websocket: WebSocket):
    """
    WebSocket 端点，前端连接以获取实时 PSD 频域数据。
    """
    await websocket.accept()
    state.start_psd()
    state.psd_ws_hub.register(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        state.psd_ws_hub.unregister(websocket)
        if not state.psd_ws_hub.has_clients():
            state.stop_psd()


@app.websocket("/ws/impedance")
async def impedance_ws(websocket: WebSocket):
    """
    WebSocket 端点，前端连接以获取实时阻抗数据。
    """
    await websocket.accept()
    state.imp_ws_hub.register(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        state.imp_ws_hub.unregister(websocket)

if __name__ == "__main__":
    import uvicorn
    host = state.config.server.host
    port = state.config.server.port
    threading.Thread(
        target=open_browser_when_server_ready,
        args=(str(host), int(port)),
        daemon=True,
    ).start()
    uvicorn.run(app, host=host, port=port)
