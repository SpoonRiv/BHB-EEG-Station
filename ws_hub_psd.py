#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: PSD WebSocket 广播枢纽（低频数据：保持“最新覆盖”，避免积压导致 UI 延迟）

修改日志:
- 2026-05-29: 1.0.0 创建文件
- 2026-05-29: 1.0.1 增加客户端在线判断接口（用于后端按需启用 PSD）

作者: Spoon
版本: 1.0.1
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from fastapi import WebSocket


@dataclass(frozen=True)
class PsdWsHubConfig:
    """
    PSD WebSocket 广播枢纽配置。

    Attributes:
        send_timeout_sec: 单个 WebSocket 发送超时（秒）。
        queue_size: 内部队列长度（默认 1，表示仅保留最新值）。
    """

    send_timeout_sec: float
    queue_size: int = 1


class PsdWsHub:
    """
    PSD WebSocket 广播枢纽。

    设计目标：
    - PSD 频率通常较低（~1-5Hz），UI 只需要最新状态；
    - 队列满时覆盖旧数据，避免积压与延迟扩散；
    - 对慢连接设置发送超时并自动剔除。
    """

    def __init__(self, cfg: PsdWsHubConfig):
        self._cfg = cfg
        self._clients: List[WebSocket] = []
        self._queue: Optional[asyncio.Queue] = None
        self._task: Optional[asyncio.Task] = None
        self._stopping = False

    def register(self, ws: WebSocket) -> None:
        if ws not in self._clients:
            self._clients.append(ws)

    def has_clients(self) -> bool:
        return len(self._clients) > 0

    def unregister(self, ws: WebSocket) -> None:
        try:
            self._clients.remove(ws)
        except ValueError:
            return

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stopping = False
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=max(1, int(self._cfg.queue_size)))
        self._task = asyncio.create_task(self._send_loop())

    def stop(self, clear_pending: bool = True) -> None:
        self._stopping = True
        if clear_pending and self._queue is not None:
            try:
                while True:
                    self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass

    def enqueue_latest(self, payload: Dict[str, object]) -> None:
        if self._stopping:
            return
        if self._queue is None or self._task is None or (self._task.done() if self._task else False):
            self.start()
        if self._queue is None:
            return
        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self._queue.put_nowait(payload)
            except Exception:
                pass

    async def _send_loop(self) -> None:
        while True:
            try:
                if self._queue is None:
                    await asyncio.sleep(0.05)
                    continue
                try:
                    item = await asyncio.wait_for(self._queue.get(), timeout=0.3)
                except asyncio.TimeoutError:
                    if self._stopping:
                        return
                    continue
                if item is None:
                    continue
                if not self._clients:
                    continue
                payload: Any = {"type": "psd_data", "data": item}
                disconnected: List[WebSocket] = []
                for ws in list(self._clients):
                    try:
                        await asyncio.wait_for(ws.send_json(payload), timeout=float(self._cfg.send_timeout_sec))
                    except Exception as e:
                        logging.error(f"WebSocket send error: {e}")
                        disconnected.append(ws)
                for ws in disconnected:
                    self.unregister(ws)
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                return
            except Exception:
                await asyncio.sleep(0.02)
