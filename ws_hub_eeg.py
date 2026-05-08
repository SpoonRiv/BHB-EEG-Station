#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: EEG WebSocket 广播枢纽（用有界队列+合并策略控制积压，保证不丢数据）

修改日志:
- 2026-05-03: 1.0.0 创建文件
- 2026-05-03: 1.0.1 广播改为顺序发送全部 chunk；队列满时合并旧 chunk，避免丢包
- 2026-05-04: 1.0.2 文件更名为 ws_hub_eeg，命名与 impedance/tdcs 保持一致
- 2026-05-07: 1.0.3 发送前变换（如陷波）移至线程执行，降低事件循环阻塞与长时间卡顿

作者: Spoon
版本: 1.0.3
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
        max_pending_chunks: 允许排队的最大 chunk 数。满时合并旧 chunk（扩大单 chunk 样本数），避免丢包且控制积压。
        send_timeout_sec: 单个 WebSocket 发送超时（秒）。避免某个慢连接拖垮整体。
    """

    max_pending_chunks: int
    send_timeout_sec: float


class EegWsHub:
    """
    EEG WebSocket 广播枢纽。

    设计目标：
    - 在不丢包的前提下，控制 WebSocket 发送积压并避免事件循环被大量小任务打爆；
    - 队列满时通过合并 chunk（扩大单次 payload）削峰填谷；
    - 对慢连接设置发送超时并自动剔除，避免拖累主链路。
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
        self._stopping = False
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=max(1, int(self._cfg.max_pending_chunks)))
        self._task = asyncio.create_task(self._send_loop())

    def stop(self, clear_pending: bool = True) -> None:
        """
        请求停止后台发送任务，并可选清空排队数据。

        说明：
            - clear_pending=True：用于“立即止波形”，会丢弃尚未发送的待发 chunk。
            - clear_pending=False：发送线程会把已入队数据顺序发送完后退出，保证不丢包。
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
        入队一个待发送的 EEG chunk。

        说明：
        - 队列满时通过合并旧 chunk（扩大单 chunk 样本数）保证不丢包，并控制队列长度。
        - 该方法必须在事件循环线程中调用（由 LSLStreamer 回调触发）。
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
