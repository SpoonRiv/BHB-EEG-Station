#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 方差 WebSocket 广播枢纽，仅保留最新方差与预热状态供前端展示
作者: Spoon
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from fastapi import WebSocket


@dataclass(frozen=True)
class VarianceWsHubConfig:
    """描述方差 WebSocket 的发送超时与最新值队列容量。"""

    send_timeout_sec: float
    queue_size: int = 1


class VarianceWsHub:
    """广播方差数据，慢连接只接收最新结果，不产生历史积压。"""

    def __init__(self, cfg: VarianceWsHubConfig) -> None:
        self._cfg = cfg
        self._clients: List[WebSocket] = []
        self._queue: Optional[asyncio.Queue] = None
        self._task: Optional[asyncio.Task] = None
        self._stopping = False

    def register(self, ws: WebSocket) -> None:
        if ws not in self._clients:
            self._clients.append(ws)

    def unregister(self, ws: WebSocket) -> None:
        try:
            self._clients.remove(ws)
        except ValueError:
            pass

    def has_clients(self) -> bool:
        return bool(self._clients)

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stopping = False
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=max(1, int(self._cfg.queue_size)))
        self._task = asyncio.create_task(self._send_loop())

    def stop(self, clear_pending: bool = True) -> None:
        self._stopping = True
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
        if clear_pending and self._queue is not None:
            try:
                while True:
                    self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self._queue = None

    def enqueue_latest(self, payload: Dict[str, object]) -> None:
        if self._stopping:
            return
        if self._queue is None or self._task is None or self._task.done():
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
                    item: Any = await asyncio.wait_for(self._queue.get(), timeout=0.3)
                except asyncio.TimeoutError:
                    if self._stopping:
                        return
                    continue
                if item is None or not self._clients:
                    continue
                disconnected: List[WebSocket] = []
                for ws in list(self._clients):
                    try:
                        await asyncio.wait_for(
                            ws.send_json({"type": "variance_data", "data": item}),
                            timeout=float(self._cfg.send_timeout_sec),
                        )
                    except Exception as exc:
                        logging.error("Variance WebSocket send error: %s", exc)
                        disconnected.append(ws)
                for ws in disconnected:
                    self.unregister(ws)
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                return
            except Exception:
                await asyncio.sleep(0.02)
