#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 {Company}. All rights reserved.

文件功能: 调试事件总线（仅用于上位机调试界面展示）

修改日志:
- 2026-05-01: 1.0.0 创建文件

作者: Spoon
版本: 1.0.0
"""

import asyncio
import time
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
        self._forward_task: Optional[asyncio.Task] = None
        self._stop_forward = False

    def publish(self, tag: str, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        event = DebugEvent(ts=time.time(), tag=tag, message=message, data=data or {})
        self._events.append(event)
        if len(self._events) > self.max_events:
            self._events = self._events[-self.max_events :]

        payload = {"type": "debug_event", "event": event.to_dict()}
        for ws in list(self._websockets):
            try:
                asyncio.create_task(ws.send_json(payload))
            except Exception:
                try:
                    self._websockets.remove(ws)
                except ValueError:
                    pass

    def get_recent(self, limit: int = 200) -> List[Dict[str, Any]]:
        n = max(1, int(limit))
        return [e.to_dict() for e in self._events[-n:]]

    def register_ws(self, websocket: Any) -> None:
        if websocket not in self._websockets:
            self._websockets.append(websocket)

    def unregister_ws(self, websocket: Any) -> None:
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
        self._stop_forward = False
        self._forward_task = asyncio.create_task(self._forward_loop(mp_queue))

    async def stop_forward(self) -> None:
        self._stop_forward = True
        if self._forward_task and not self._forward_task.done():
            self._forward_task.cancel()
        self._forward_task = None

    async def _forward_loop(self, mp_queue: Any) -> None:
        while not self._stop_forward:
            try:
                item = await asyncio.to_thread(mp_queue.get)
                if not isinstance(item, dict):
                    continue
                tag = str(item.get("tag", "DEBUG"))
                message = str(item.get("message", ""))
                data = item.get("data", {})
                if not isinstance(data, dict):
                    data = {"value": data}
                self.publish(tag=tag, message=message, data=data)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.1)

