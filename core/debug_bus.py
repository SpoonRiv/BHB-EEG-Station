#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 {Company}. All rights reserved.

文件功能: 调试事件总线（仅用于上位机调试界面展示）

修改日志:
- 2026-05-01: 1.0.0 创建文件
- 2026-07-03: 1.0.1 修复调试事件从非事件循环线程（如 trigger TCP 线程）发布时偶发丢失的问题，并增强 WS 断线清理
- 2026-07-03: 1.0.2 将多进程调试队列转发改为可停止轮询，避免蓝牙断联重连后仍卡在旧队列

作者: Spoon
版本: 1.0.2
"""

import asyncio
import queue
import time
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class DebugEvent:
    """
    调试事件结构（用于上位机调试界面）。
    """

    ts: float
    tag: str
    message: str
    data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {"ts": self.ts, "tag": self.tag, "message": self.message, "data": self.data}


class DebugEventBus:
    """
    调试事件总线：
    - publish：发布事件并缓存
    - connect/disconnect：维护 WebSocket 连接列表（由上层调用）
    - forward_from_mp_queue：从 multiprocessing.Queue 转发事件到总线（异步后台任务）
    """

    def __init__(self, max_events: int = 500):
        self.max_events = max(1, int(max_events))
        self._events: List[DebugEvent] = []
        self._websockets: List[Any] = []
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._forward_task: Optional[asyncio.Task] = None
        self._stop_forward = False

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """
        绑定事件循环，用于从非事件循环线程安全地调度 publish（例如 trigger TCP 服务线程）。
        """

        if loop is not None:
            self._loop = loop

    def publish(self, tag: str, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        payload_data = data or {}
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            bound = self._loop
            if bound is not None:
                bound.call_soon_threadsafe(self._publish_on_loop, tag, message, payload_data)
                return
            with self._lock:
                event = DebugEvent(ts=time.time(), tag=tag, message=message, data=payload_data)
                self._events.append(event)
                if len(self._events) > self.max_events:
                    self._events = self._events[-self.max_events :]
            return
        if self._loop is None:
            self._loop = loop
        self._publish_on_loop(tag, message, payload_data)

    def _publish_on_loop(self, tag: str, message: str, data: Dict[str, Any]) -> None:
        event = DebugEvent(ts=time.time(), tag=tag, message=message, data=data)
        payload = {"type": "debug_event", "event": event.to_dict()}
        with self._lock:
            self._events.append(event)
            if len(self._events) > self.max_events:
                self._events = self._events[-self.max_events :]
            websockets = list(self._websockets)
        for ws in websockets:
            asyncio.create_task(self._safe_send(ws, payload))

    async def _safe_send(self, websocket: Any, payload: Dict[str, Any]) -> None:
        try:
            await websocket.send_json(payload)
        except Exception:
            self.unregister_ws(websocket)

    def get_recent(self, limit: int = 200) -> List[Dict[str, Any]]:
        n = max(1, int(limit))
        with self._lock:
            return [e.to_dict() for e in self._events[-n:]]

    def register_ws(self, websocket: Any) -> None:
        try:
            loop = asyncio.get_running_loop()
            if self._loop is None:
                self._loop = loop
        except RuntimeError:
            pass
        with self._lock:
            if websocket not in self._websockets:
                self._websockets.append(websocket)

    def unregister_ws(self, websocket: Any) -> None:
        with self._lock:
            try:
                self._websockets.remove(websocket)
            except ValueError:
                pass

    def start_forward_from_mp_queue(self, mp_queue: Any) -> None:
        """
        启动后台转发任务：从 multiprocessing.Queue 读取调试事件并 publish。
        """
        if self._forward_task and not self._forward_task.done():
            return
        try:
            if self._loop is None:
                self._loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        self._stop_forward = False
        self._forward_task = asyncio.create_task(self._forward_loop(mp_queue))

    async def stop_forward(self) -> None:
        self._stop_forward = True
        if self._forward_task and not self._forward_task.done():
            try:
                await self._forward_task
            except asyncio.CancelledError:
                pass
        self._forward_task = None

    async def _forward_loop(self, mp_queue: Any) -> None:
        while not self._stop_forward:
            try:
                item = await asyncio.to_thread(mp_queue.get, True, 0.2)
                if not isinstance(item, dict):
                    continue
                tag = str(item.get("tag", "DEBUG"))
                message = str(item.get("message", ""))
                data = item.get("data", {})
                if not isinstance(data, dict):
                    data = {"value": data}
                self.publish(tag=tag, message=message, data=data)
            except queue.Empty:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.1)
