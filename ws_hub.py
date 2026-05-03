#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: EEG WebSocket 广播枢纽（用有界队列+最新覆盖策略消除停采集时的发送积压）

修改日志:
- 2026-05-03: 1.0.0 创建文件

作者: Spoon
版本: 1.0.0
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from fastapi import WebSocket


@dataclass(frozen=True)
class EegWsHubConfig:
    """
    EEG WebSocket 广播枢纽配置。

    Attributes:
        max_pending_chunks: 允许排队的最大 chunk 数。满时丢弃旧数据保留最新，避免 stop 后“尾巴很长”。
        send_timeout_sec: 单个 WebSocket 发送超时（秒）。避免某个慢连接拖垮整体。
    """

    max_pending_chunks: int
    send_timeout_sec: float


class EegWsHub:
    """
    EEG WebSocket 广播枢纽。

    设计目标：
    - 解决“高频数据 + 每 chunk 创建 task”导致的发送积压；
    - stop 时立即清空队列并停止发送，让前端波形立刻停止；
    - 对慢连接设置发送超时并自动剔除，避免拖累主链路。
    """

    def __init__(self, cfg: EegWsHubConfig):
        self._cfg = cfg
        self._clients: List[WebSocket] = []
        self._queue: Optional["asyncio.Queue[Optional[List[List[float]]]]"] = None
        self._task: Optional[asyncio.Task] = None
        self._transform: Optional[Callable[[List[List[float]]], List[List[float]]]] = None

    def set_transform(self, fn: Optional[Callable[[List[List[float]]], List[List[float]]]]) -> None:
        """
        设置发送前的变换函数（如陷波/缩放）。在发送任务线程内执行。
        """

        self._transform = fn

    def register(self, ws: WebSocket) -> None:
        """
        注册一个 WebSocket 客户端。
        """

        if ws not in self._clients:
            self._clients.append(ws)

    def unregister(self, ws: WebSocket) -> None:
        """
        取消注册一个 WebSocket 客户端。
        """

        try:
            self._clients.remove(ws)
        except ValueError:
            return

    def start(self) -> None:
        """
        启动后台发送任务（幂等）。
        """

        if self._task and not self._task.done():
            return
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=max(1, int(self._cfg.max_pending_chunks)))
        self._task = asyncio.create_task(self._send_loop())

    def stop(self, clear_pending: bool = True) -> None:
        """
        停止后台发送任务，并可选清空排队数据（用于 stop 立即止波形）。
        """

        if clear_pending and self._queue is not None:
            try:
                while True:
                    self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        if self._task:
            self._task.cancel()
            self._task = None

    def enqueue(self, chunk: List[List[float]]) -> None:
        """
        入队一个待发送的 EEG chunk。

        说明：
        - 使用“最新覆盖”：队列满时先丢弃旧数据再放入新数据，避免积压。
        - 该方法必须在事件循环线程中调用（由 LSLStreamer 回调触发）。
        """

        if self._queue is None or self._task is None or (self._task.done() if self._task else False):
            self.start()
        if self._queue is None:
            return
        try:
            self._queue.put_nowait(chunk)
        except asyncio.QueueFull:
            try:
                _ = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self._queue.put_nowait(chunk)
            except asyncio.QueueFull:
                pass

    async def _send_loop(self) -> None:
        while True:
            try:
                if self._queue is None:
                    await asyncio.sleep(0.05)
                    continue
                item = await self._queue.get()
                if item is None:
                    return
                latest = item
                try:
                    while True:
                        nxt = self._queue.get_nowait()
                        if nxt is None:
                            return
                        latest = nxt
                except asyncio.QueueEmpty:
                    pass

                send_chunk = latest
                if self._transform is not None:
                    try:
                        send_chunk = self._transform(latest)
                    except Exception:
                        send_chunk = latest

                if not self._clients:
                    continue

                payload: Any = {"type": "eeg_data", "data": send_chunk}
                disconnected: List[WebSocket] = []
                for ws in list(self._clients):
                    try:
                        await asyncio.wait_for(ws.send_json(payload), timeout=float(self._cfg.send_timeout_sec))
                    except Exception as e:
                        logging.error(f"WebSocket send error: {e}")
                        disconnected.append(ws)
                for ws in disconnected:
                    self.unregister(ws)
            except asyncio.CancelledError:
                return
            except Exception:
                await asyncio.sleep(0.02)
