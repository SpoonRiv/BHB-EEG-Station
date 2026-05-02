#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 {Company}. All rights reserved.

文件功能: EEG 采集控制编排（启动/停止 BLE 采集进程），并向上层提供统一的设备生命周期管理接口

修改日志:
- 2026-04-30: 1.0.0 创建文件

作者: Spoon
版本: 1.0.0
"""

import multiprocessing
import os
import logging
import time
from typing import Any, Dict, Optional

from configs.config_loader import load_config
from core.ble.acquisition_process import run_ble_acquisition_process


class EEGController:
    """
    蓝牙 EEG 采集控制器。

    - 采集逻辑运行在独立的 multiprocessing.Process 中（避免阻塞主事件循环）
    - 进程通过 LSL 推流，FastAPI 再从 LSL 异步读取并通过 WebSocket 广播给前端
    - 预留 8/16 通道模式：由 configs/config.yaml 的 eeg.mode_channels 控制
    """

    def __init__(self, config_path: Optional[str] = None):
        self.process: Optional[multiprocessing.Process] = None
        self.stop_event: Optional[multiprocessing.Event] = None
        self.status_queue: Optional[multiprocessing.Queue] = None
        self.debug_queue: Optional[multiprocessing.Queue] = None
        self.last_status: Optional[Dict[str, Any]] = None
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
        - last: 最近一次来自采集进程的状态消息（connected/connecting/error/battery/imu/stopped/idle 等）
        - configured_name: 配置中期望匹配的设备名（用于用户核对）
        """
        configured_name = self.config.bluetooth.target_device
        last = self.last_status or {"type": "idle", "message": "未启动", "name": configured_name}
        if "name" not in last:
            last = {**last, "name": configured_name}
        return {"running": self.is_running(), "last": last, "configured_name": configured_name}

    def start_device(self) -> bool:
        """
        启动蓝牙采集进程（BLE -> LSL）。

        Returns:
            bool: 启动是否成功
        """
        if self.process and self.process.is_alive():
            logging.warning("EEG device process is already running.")
            return True

        try:
            self.stop_event = multiprocessing.Event()
            self.status_queue = multiprocessing.Queue()
            self.debug_queue = multiprocessing.Queue()
            self.process = multiprocessing.Process(
                target=run_ble_acquisition_process,
                args=(self.config_path, self.stop_event, self.status_queue, self.debug_queue),
            )
            self.process.start()

            deadline = time.time() + 30.0
            while time.time() < deadline:
                remaining = max(0.1, deadline - time.time())
                msg: Dict[str, Any] = self.status_queue.get(timeout=remaining)
                self.last_status = msg

                if msg.get("type") == "connected":
                    logging.info("Bluetooth EEG device connected successfully.")
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
            self.debug_queue = None
            self.last_status = {"type": "stopped", "message": "采集已停止", "name": self.config.bluetooth.target_device}
            return True
        except Exception as e:
            logging.error(f"Failed to stop EEG device: {e}")
            self.last_status = {"type": "error", "message": str(e), "name": self.config.bluetooth.target_device}
            return False
