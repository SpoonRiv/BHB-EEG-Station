#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: EEG 采集控制编排（启动/停止 BLE 采集进程），并向上层提供统一的设备生命周期管理接口

修改日志:
- 2026-04-30: 1.0.0 创建文件
- 2026-05-02: 1.1.0 增加设备与模式页面流，拆分脚本入口
- 2026-05-03: 1.2.0 增加电量/IMU 状态缓存透传，供前端展示
- 2026-05-03: 1.2.1 增加断联状态类型（disconnected），用于前端显示“连接已断开”
- 2026-05-03: 1.2.2 增加任务运行态标记（task_running），用于运行中锁定导航入口
- 2026-05-04: 1.2.3 配置字段更名：eeg.mode_channels -> eeg.n_channels（8/16 通道预留）

作者: Spoon
版本: 1.2.3
"""

import multiprocessing
import os
import logging
import time
import queue
from typing import Any, Dict, Optional

from configs.config_loader import load_config
from core.ble.acquisition_process import run_ble_acquisition_process


class EEGController:
    """
    蓝牙 EEG 采集控制器。

    - 采集逻辑运行在独立的 multiprocessing.Process 中（避免阻塞主事件循环）
    - 进程通过 LSL 推流，FastAPI 再从 LSL 异步读取并通过 WebSocket 广播给前端
    - 预留 8/16 通道模式：由 configs/config.yaml 的 eeg.n_channels 控制
    """

    def __init__(self, config_path: Optional[str] = None):
        self.process: Optional[multiprocessing.Process] = None
        self.stop_event: Optional[multiprocessing.Event] = None
        self.status_queue: Optional[multiprocessing.Queue] = None
        self.command_queue: Optional[multiprocessing.Queue] = None
        self.debug_queue: Optional[multiprocessing.Queue] = None
        self.last_status: Optional[Dict[str, Any]] = None
        self.last_battery: Optional[Dict[str, Any]] = None
        self.last_imu: Optional[Dict[str, Any]] = None
        self.current_mode: str = "idle"
        self.task_running: bool = False
        self.task_mode: str = ""
        self.config_path = config_path or os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "configs",
            "config.yaml",
        )
        self.config = load_config(self.config_path)

    def is_running(self) -> bool:
        """
        判断采集进程是否处于运行状态。

        Returns:
            bool: 采集进程是否存活
        """
        return bool(self.process and self.process.is_alive())

    def get_status(self) -> Dict[str, Any]:
        """
        获取采集侧状态快照（用于前端状态指示）。

        返回约定：
        - running: 采集进程是否存活（仅表示进程存在，不等价于“已连接并开始推流”）
        - last: 最近一次来自采集进程的状态消息（connected/connecting/error/stopped/idle 等）
        - configured_name: 配置中期望匹配的设备名（用于用户核对）
        - battery: 最近一次电量上报（来自采集进程），结构为 {value, ts}
        - imu: 最近一次 IMU 上报（来自采集进程），结构为 {value, ts}
        """
        self._drain_status_queue()
        configured_name = self.config.bluetooth.target_device
        last = self.last_status or {"type": "idle", "message": "未启动", "name": configured_name}
        if "name" not in last:
            last = {**last, "name": configured_name}
        return {
            "running": self.is_running(),
            "last": last,
            "configured_name": configured_name,
            "mode": self.current_mode,
            "task_running": bool(self.task_running),
            "task_mode": str(self.task_mode or ""),
            "battery": self.last_battery,
            "imu": self.last_imu,
        }

    def start_device(self, address: Optional[str] = None, name: Optional[str] = None) -> bool:
        """
        启动蓝牙采集进程并建立 BLE 连接（连接常驻，不自动进入具体业务模式）。

        Returns:
            bool: 启动是否成功
        """
        if self.process and self.process.is_alive():
            logging.warning("EEG device process is already running.")
            return True

        try:
            self.stop_event = multiprocessing.Event()
            self.status_queue = multiprocessing.Queue()
            self.command_queue = multiprocessing.Queue()
            self.debug_queue = multiprocessing.Queue()
            self.process = multiprocessing.Process(
                target=run_ble_acquisition_process,
                args=(self.config_path, self.stop_event, self.status_queue, self.command_queue, self.debug_queue, address, name),
            )
            self.process.start()

            deadline = time.time() + 30.0
            while time.time() < deadline:
                remaining = max(0.1, deadline - time.time())
                msg: Dict[str, Any] = self.status_queue.get(timeout=remaining)
                msg_type = str(msg.get("type", "")) if isinstance(msg, dict) else ""
                if msg_type in {"connecting", "connected", "ready", "error", "stopped", "idle", "disconnected"}:
                    self.last_status = msg
                elif msg_type == "battery" and "value" in msg:
                    self.last_battery = {"value": int(msg.get("value", 0)), "ts": time.time()}
                elif msg_type == "imu" and "value" in msg:
                    self.last_imu = {"value": msg.get("value"), "ts": time.time()}

                if msg.get("type") == "connected":
                    logging.info("Bluetooth EEG device connected successfully.")
                    self.current_mode = "idle"
                    return True
                if msg.get("type") == "error":
                    logging.error(f"EEG device start error: {msg.get('message')}")
                    return False
                # connecting/battery/imu 等状态消息继续等待，直到 connected 或 error

            self.last_status = {"type": "error", "message": "蓝牙连接超时（30秒）"}
            logging.error("EEG device start error: 蓝牙连接超时（30秒）")
            return False
        except Exception as e:
            logging.error(f"Failed to start EEG device: {e}")
            self.last_status = {"type": "error", "message": str(e)}
            return False

    def select_mode(self, mode: str) -> bool:
        """
        选择设备业务模式（仅切换状态，不自动下发 start 指令）。

        Args:
            mode: 目标模式。当前支持：idle/eeg/impedance/tdcs

        Returns:
            bool: 命令是否成功投递到采集进程
        """
        if not self.command_queue or not self.is_running():
            return False
        self.command_queue.put({"type": "select_mode", "mode": str(mode)})
        self.current_mode = str(mode)
        return True

    def start_mode(self, mode: str) -> bool:
        """
        启动指定模式（向设备下发对应 start 指令）。

        Args:
            mode: 模式。当前支持：eeg/impedance/tdcs

        Returns:
            bool: 命令是否成功投递到采集进程
        """
        if not self.command_queue or not self.is_running():
            return False
        self.command_queue.put({"type": "start_mode", "mode": str(mode)})
        self.current_mode = str(mode)
        return True

    def stop_mode(self, mode: str) -> bool:
        """
        停止指定模式（向设备下发对应 stop 指令）。

        Args:
            mode: 模式。当前支持：eeg/impedance/tdcs

        Returns:
            bool: 命令是否成功投递到采集进程
        """
        if not self.command_queue or not self.is_running():
            return False
        self.command_queue.put({"type": "stop_mode", "mode": str(mode)})
        self.current_mode = "idle"
        return True

    def _drain_status_queue(self) -> None:
        """
        尝试无阻塞地清空状态队列，将最新状态缓存到 last_status。

        该函数用于解决“连接后持续更新状态”的需求：主进程不应为状态更新创建额外阻塞循环，
        而由 get_status() 在被调用时顺手拉取最新状态即可。
        """
        if not self.status_queue:
            return
        while True:
            try:
                msg = self.status_queue.get_nowait()
                if isinstance(msg, dict):
                    msg_type = str(msg.get("type", ""))
                    if msg_type in {"connecting", "connected", "ready", "error", "stopped", "idle", "disconnected"}:
                        self.last_status = msg
                    if msg_type == "battery" and "value" in msg:
                        self.last_battery = {"value": int(msg.get("value", 0)), "ts": time.time()}
                    if msg_type == "imu" and "value" in msg:
                        self.last_imu = {"value": msg.get("value"), "ts": time.time()}
                    if msg_type == "mode" and "mode" in msg:
                        self.current_mode = str(msg.get("mode"))
                    if msg_type in {"mode_started", "mode_stopped"} and "mode" in msg:
                        if msg_type == "mode_started":
                            self.current_mode = str(msg.get("mode"))
                            self.task_running = True
                            self.task_mode = str(msg.get("mode"))
                        else:
                            self.current_mode = "idle"
                            self.task_running = False
                            self.task_mode = ""
            except queue.Empty:
                break
            except Exception:
                break

    def stop_device(self) -> bool:
        """
        停止蓝牙采集进程。
        Returns:
            bool: 停止是否成功
        """
        if not self.process or not self.process.is_alive():
            logging.warning("EEG device process is not running.")
            self.last_status = {"type": "stopped", "message": "采集未运行", "name": self.config.bluetooth.target_device}
            return True

        try:
            if self.stop_event:
                self.stop_event.set()

            self.process.join(timeout=5)
            if self.process.is_alive():
                logging.warning("Process did not exit gracefully, terminating...")
                self.process.terminate()
                self.process.join()

            self.process = None
            self.stop_event = None
            self.status_queue = None
            self.command_queue = None
            self.debug_queue = None
            self.current_mode = "idle"
            self.last_status = {"type": "stopped", "message": "采集已停止", "name": self.config.bluetooth.target_device}
            self.last_battery = None
            self.last_imu = None
            self.task_running = False
            self.task_mode = ""
            return True
        except Exception as e:
            logging.error(f"Failed to stop EEG device: {e}")
            self.last_status = {"type": "error", "message": str(e), "name": self.config.bluetooth.target_device}
            return False
