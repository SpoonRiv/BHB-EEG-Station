#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: EEG WebSocket 广播枢纽（用有界队列+合并策略控制积压，保证不丢数据）
作者: Spoon
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
    """

    max_pending_chunks: int
    send_timeout_sec: float


class EegWsHub:
    """
    EEG WebSocket 广播枢纽。
    """

    def __init__(self, cfg: EegWsHubConfig):
        self._cfg = cfg
        self._clients: List[WebSocket] = []
        self._queue: Optional["asyncio.Queue[Optional[List[List[float]]]]"] = None
        self._task: Optional[asyncio.Task] = None
        self._transform: Optional[Callable[[List[List[float]]], List[List[float]]]] = None
        self._stopping = False

    def set_transform(self, fn: Optional[Callable[[List[List[float]]], List[List[float]]]]) -> None:
        """
        设置发送前的变换函数。
        """

        self._transform = fn

    def register(self, ws: WebSocket) -> None:
        """
        注册 WebSocket 客户端。
        """

        if ws not in self._clients:
            self._clients.append(ws)

    def unregister(self, ws: WebSocket) -> None:
        """
        取消注册 WebSocket 客户端。
        """

        try:
            self._clients.remove(ws)
        except ValueError:
            return

    def start(self) -> None:
        """
        启动后台发送任务。
        """

        if self._task and not self._task.done():
            return
        self._stopping = False
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=max(1, int(self._cfg.max_pending_chunks)))
        self._task = asyncio.create_task(self._send_loop())

    def stop(self, clear_pending: bool = True) -> None:
        """
        请求停止后台发送任务，并可选清空待发数据。
        """

        self._stopping = True
        if clear_pending and self._queue is not None:
            try:
                while True:
                    self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass

    def enqueue(self, chunk: List[List[float]]) -> None:
        """
        入队一个待发送的 EEG 数据块。
        """

        if self._stopping:
            return
        if self._queue is None or self._task is None or (self._task.done() if self._task else False):
            self.start()
        if self._queue is None:
            return
        merged = chunk
        for _ in range(5):
            try:
                self._queue.put_nowait(merged)
                return
            except asyncio.QueueFull:
                try:
                    old = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    old = None
                if old:
                    merged = old + merged

    async def _send_loop(self) -> None:
        while True:
            try:
                if self._queue is None:
                    await asyncio.sleep(0.05)
                    continue
                try:
                    item = await asyncio.wait_for(self._queue.get(), timeout=0.2)
                except asyncio.TimeoutError:
                    if self._stopping:
                        return
                    continue
                if item is None:
                    continue

                send_chunk = item
                if self._transform is not None:
                    try:
                        send_chunk = await asyncio.to_thread(self._transform, item)
                    except Exception:
                        send_chunk = item

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
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                return
            except Exception:
                await asyncio.sleep(0.02)
