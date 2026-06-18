#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 后端入口（FastAPI 应用、静态前端挂载、HTTP API、WebSocket 实时广播 EEG 数据）

修改日志:
- 2026-04-30: 1.0.0 创建文件
- 2026-05-02: 1.1.0 增加设备与模式页面流，拆分脚本入口
- 2026-05-02: 1.1.1 增加 LSL 推流自检信息并传递解析重试配置
- 2026-05-03: 1.1.2 禁用静态资源缓存并限制 EEG 重复启动
- 2026-05-03: 1.1.3 EEG 停止接口幂等化，避免未推流时无法停止
- 2026-05-03: 1.1.4 EEG 停止后进入离线存储页，支持导出 CSV/EDF 与可选滤波
- 2026-05-03: 1.1.5 离线导出接口补充参数校验与错误信息回传，便于定位 HTTP 500
- 2026-05-03: 1.1.6 增加 50Hz 工频陷波预处理（波形展示与导出均生效）
- 2026-05-03: 1.1.7 EEG WebSocket 广播改为有界队列最新覆盖，停止采集立即止波形
- 2026-05-03: 1.1.8 增加离线会话查询接口，供前端展示采集时长与数据尺寸
- 2026-05-03: 1.1.9 下发 UI 波形显示配置并调整停止采集时的 WS 收尾策略
- 2026-05-03: 1.2.0 配置命名区分“后端转发频率”和“前端渲染频率”
- 2026-05-03: 1.2.1 增加 10-20 通道选择与常用组合接口（本机覆盖配置，不写入 config.yaml）
- 2026-05-03: 1.2.2 增加参考电极下拉选择（候选列表/待应用保存/应用到系统）
- 2026-05-03: 1.2.3 通道预设增加参考电极字段，套用/保存包含参考电极
- 2026-05-04: 1.3.0 增加阻抗检测数据流：LSL->WebSocket 推送与前端可视化入口
- 2026-05-04: 1.3.1 下发阻抗阈值滑条上限配置（slider_max_ohm）
- 2026-05-04: 1.3.2 下发阻抗阈值滑条步进配置（slider_step_ohm）
- 2026-05-04: 1.3.3 下发电刺激（tDCS）占位配置（enabled/ui）
- 2026-05-04: 1.3.4 统一三模式命名：eeg/impedance/tdcs，并重命名 EEG WebSocket Hub 模块
- 2026-05-07: 1.3.5 下发前端 WS 背压配置并将离线写入队列上限接入配置，降低长时间运行卡顿风险
- 2026-05-08: 1.3.6 下发动态 y 轴分档/更新频率配置并下调默认渲染频率，降低 ECharts 布局与重绘压力
- 2026-05-09: 1.3.7 (Fengye) 增加刺激模式：独立进程启动/停止刺激程序并暴露状态字段（已移除）
- 2026-05-09: 1.3.8 修复刺激模块导入路径，避免启动时报错（已移除）
- 2026-05-12: 1.3.9 延迟导入刺激模式依赖，避免子进程启动时加载重模块导致 BLE 连接超时（已移除）
- 2026-05-12: 1.3.10 增加两级指令控制面板 API（下发指令与指令列表），用于 tDCS 页面按钮化控制
- 2026-05-12: 1.3.11 控制面板指令列表补充 help 字段（用于 UI 展示按钮说明）
- 2026-05-15: 1.3.12 EEG 波形展示默认开启 0.5-80Hz 带通滤波
- 2026-05-15: 1.3.13 EEG 波形展示与离线导出统一按 /120 缩放（uv_per_count）
- 2026-05-15: 1.3.14 EEG 缩放配置改为 count_divisor，并统一按 /count_divisor 执行（不使用乘法）
- 2026-05-16: 1.3.15 离线会话 ID 命名调整：默认不再追加 _00 后缀
- 2026-05-16: 1.3.16 下发 EEG y 轴动态/固定缩放 UI 配置（开关与滑条范围）
- 2026-05-17: 1.3.17 移除视觉刺激模式相关接口与模块
- 2026-05-17: 1.3.18 BLE 扫描白名单改为前缀匹配，支持列出多个同前缀设备供用户选择
- 2026-05-17: 1.3.19 下发 10-20 电极位置布局给前端（用于地形图绘制）
- 2026-05-17: 1.3.20 参考电极允许从全部电极中选择（地形图点选），不再强制限制为候选列表
- 2026-05-21: 1.3.21 移除 EEG 波形展示带通滤波预处理与相关配置下发
- 2026-05-24: 1.4.0 按模块命名规则识别电刺激能力：无刺激模块时禁用 tDCS 并隐藏 tDCS 阻抗通道
- 2026-05-24: 1.4.1 广播名仅为 MSM 时按“无电刺激模块”处理；扫描失败返回中文错误提示
- 2026-05-29: 1.4.2 EEG 采集模式增加频域分析（PSD WebSocket 推送与前端切换）
- 2026-05-29: 1.4.3 频域分析与时域链路隔离：PSD 仅在前端订阅时启用且不占用主回调
- 2026-05-30: 1.4.4 PSD 按“视图开关”启停：仅 PSD WS 在线时启动后台线程/任务，关闭后完整释放
- 2026-05-30: 1.4.5 增加 trigger 控制 API（开始/停止）
- 2026-05-30: 1.4.6 开始采集时自动启动 trigger TCP 服务端
- 2026-05-31: 1.4.7 EEG 模式启动时自动启动 trigger 服务端，并将 trigger start/end 同步到采集进程注入触发通道
- 2026-06-17: 1.4.8 下发当前参考电极名，供阻抗页将 BIAS 显示为实际参考通道
- 2026-06-18: 1.4.9 增加应用关机接口，统一断开蓝牙并在响应后退出服务进程
- 2026-06-18: 1.5.0 直接运行 main.py 时自动使用系统默认浏览器打开上位机首页


作者: Spoon
版本: 1.5.0
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
    禁用静态资源缓存的 StaticFiles 包装。
·
    目的：
        开发阶段频繁修改 web/ 下的 HTML/CSS/JS 时，浏览器缓存会导致“看起来像没生效”的假象。
        此类统一对静态资源响应加上 Cache-Control: no-store，确保每次刷新都取最新内容。
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
        def _on_trigger_event(command: str, source: str) -> None:
            try:
                self.controller.send_trigger_command(command=str(command), source=str(source))
            except Exception:
                pass
            if not bool(self.config.debug.ui_enabled):
                return
            self.debug_bus.publish(tag="TRIGGER", message=f"收到 {command}", data={"source": str(source)})
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
        启动 PSD 后台计算与 WebSocket 推送。
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
        停止 PSD 后台计算与 WebSocket 推送，并清空缓存。
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
        PSD 后台循环：按配置节流计算 Welch PSD，并通过 WebSocket 推送最新结果。
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
        对 EEG chunk 应用实时预处理（失败则回退到原始数据）。

        Args:
            chunk: 形如 [sample][channel] 的二维数组

        Returns:
            List[List[float]]: 预处理后的数据（或原始数据）
        """
        out = chunk
        try:
            out = self.notch.apply(out)
        except Exception:
            out = chunk
        return self._scale_eeg_chunk_like_legacy(out)

    def _scale_eeg_chunk_like_legacy(self, chunk: List[List[float]]) -> List[List[float]]:
        """
        对实时波形展示数据做幅值缩放（与离线导出一致）。

        说明：
            - 旧版上位机在保存/展示前对数据做 /120；
            - 新版通过配置 offline.export.count_divisor 表达“原始计数到物理单位的缩放除数”，因此采用除法缩放：
              scaled = raw / count_divisor；
            - 触发通道（若存在）不做缩放。

        Args:
            chunk: 形如 [sample][channel] 的二维数组

        Returns:
            List[List[float]]: 缩放后的数据
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
        LSL 数据回调：记录离线数据并入队等待 WebSocket 广播。

        设计要点：
        - 该函数必须保持轻量且不 await，避免每个 chunk 创建 task 导致发送积压；
        - WebSocket 发送在后台单任务中完成，并在队列满时丢弃旧数据保留最新。
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
        阻抗 LSL 数据回调：仅保留最新一帧并入队等待 WebSocket 广播。
        """
        if not chunk:
            return
        last = chunk[-1]
        try:
            self.imp_ws_hub.enqueue_latest([float(x) for x in last])
        except Exception:
            pass

state = AppState()


def shutdown_runtime() -> None:
    """
    关闭运行中的数据流、后台服务与采集进程。

    职责边界：
        - 统一停止 WebSocket Hub、LSL 读取、PSD 任务、trigger 服务与离线会话；
        - 最后停止 BLE 采集进程，确保蓝牙连接被断开；
        - 该函数不直接退出 Python 进程，便于在 HTTP 响应返回后再执行真正的进程退出。
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
    在短延时后强制退出当前服务进程。

    Args:
        delay_sec: 延时时长（秒），用于给 HTTP 响应留出发送时间。
    """

    def _exit_later() -> None:
        """
        等待响应发出后退出进程，避免前端请求在网络层中断。
        """
        try:
            time.sleep(max(0.1, float(delay_sec)))
        finally:
            os._exit(0)

    threading.Thread(target=_exit_later, daemon=True).start()


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
    if state.config.debug.ui_enabled and not state._debug_forward_started:
        if state.controller.debug_queue is not None:
            state.debug_bus.start_forward_from_mp_queue(state.controller.debug_queue)
            state._debug_forward_started = True
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
    await state.debug_bus.stop_forward()

app = FastAPI(title="BHB-EEG Station Web API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载前端静态文件
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
        if state.config.debug.ui_enabled and state.controller.debug_queue is not None and not state._debug_forward_started:
            state.debug_bus.start_forward_from_mp_queue(state.controller.debug_queue)
            state._debug_forward_started = True
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

    if int(state.config.eeg.n_channels) == 16:
        raise HTTPException(status_code=400, detail="16通道链路尚未开发完成，请保持 8 通道模式")

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
    return {
        "device": state.controller.get_status(),
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
    success = await asyncio.to_thread(state.controller.start_device, req.address, req.name)
    if success and state.config.debug.ui_enabled and state.controller.debug_queue is not None and not state._debug_forward_started:
        state.debug_bus.start_forward_from_mp_queue(state.controller.debug_queue)
        state._debug_forward_started = True
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
                await state.debug_bus.stop_forward()
            except Exception:
                pass
        schedule_process_exit()
        return {"status": "success", "message": "系统关闭中。"}
    except Exception as e:
        logging.exception("Application shutdown failed")
        raise HTTPException(status_code=500, detail=f"系统关闭失败：{e}") from e


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
            # 保持连接，处理前端可能发来的 ping 或控制信息
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
