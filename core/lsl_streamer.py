#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 在独立摄取线程中接收 LSL 数据并向事件循环安全转发数据块
作者: Spoon
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from pylsl import StreamInlet, resolve_byprop


class LSLStreamer:
    """异步解析 LSL 流，并使用独立线程连续摄取和打包样本。"""

    def __init__(
        self,
        stream_name: str,
        stream_type: str,
        buffer_size: int = 10,
        resolve_timeout_sec: float = 1.0,
        resolve_retry_interval_sec: float = 0.5,
    ) -> None:
        """初始化 LSL 流标识、打包参数和线程生命周期状态。"""
        self.stream_name = stream_name
        self.stream_type = stream_type
        self.buffer_size = max(1, int(buffer_size))
        self.resolve_timeout_sec = max(0.05, float(resolve_timeout_sec))
        self.resolve_retry_interval_sec = max(0.05, float(resolve_retry_interval_sec))
        self.inlet: Optional[StreamInlet] = None
        self.is_streaming = False
        self.task: Optional[asyncio.Task[None]] = None
        self._state = "stopped"
        self._last_error = ""
        self._callbacks: List[Callable[[List[List[float]]], Any]] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ingest_thread: Optional[threading.Thread] = None
        self._ingest_stop = threading.Event()
        self._inlet_lock = threading.Lock()

    def add_callback(self, callback: Callable[[List[List[float]]], Any]) -> None:
        """注册在事件循环线程执行的数据块回调。"""
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[List[List[float]]], Any]) -> None:
        """移除已注册的数据块回调。"""
        try:
            self._callbacks.remove(callback)
        except ValueError:
            return

    def get_status(self) -> Dict[str, Any]:
        """返回流解析、独立摄取线程和最近错误状态。"""
        return {
            "state": self._state,
            "stream_name": self.stream_name,
            "stream_type": self.stream_type,
            "buffer_size": self.buffer_size,
            "ingest_thread_alive": bool(
                self._ingest_thread is not None and self._ingest_thread.is_alive()
            ),
            "last_error": self._last_error,
        }

    async def _run(self) -> None:
        """持续解析目标流，并在摄取线程异常退出后自动重新连接。"""
        while self.is_streaming:
            resolved = await self._resolve_stream()
            if not resolved or not self.is_streaming:
                break
            self._start_ingest_thread()
            while self.is_streaming and self._ingest_thread is not None:
                if not self._ingest_thread.is_alive():
                    break
                await asyncio.sleep(0.1)
            if self.is_streaming:
                self._close_inlet()
                self._state = "resolving"
                await asyncio.sleep(self.resolve_retry_interval_sec)
        self._state = "stopped"

    async def _resolve_stream(self) -> bool:
        """在线程池执行阻塞解析和打开操作，直至成功或收到停止请求。"""
        self._state = "resolving"
        self._last_error = ""
        logging.info(
            "Looking for an LSL stream name='%s', type='%s' ...",
            self.stream_name,
            self.stream_type,
        )
        while self.is_streaming:
            try:
                streams = await asyncio.to_thread(
                    resolve_byprop,
                    "name",
                    self.stream_name,
                    1,
                    float(self.resolve_timeout_sec),
                )
                if not streams:
                    self._last_error = "等待 LSL 流出现"
                    await asyncio.sleep(self.resolve_retry_interval_sec)
                    continue
                stream_info = streams[0]
                resolved_type = str(stream_info.type() or "")
                if self.stream_type and resolved_type and resolved_type != self.stream_type:
                    self._last_error = (
                        f"LSL 流类型不匹配：期望 {self.stream_type}，实际 {resolved_type}"
                    )
                    await asyncio.sleep(self.resolve_retry_interval_sec)
                    continue
                inlet = StreamInlet(stream_info)
                await asyncio.to_thread(
                    inlet.open_stream,
                    float(self.resolve_timeout_sec),
                )
                with self._inlet_lock:
                    self.inlet = inlet
                self._state = "streaming"
                self._last_error = ""
                logging.info("LSL stream resolved: name='%s'.", self.stream_name)
                return True
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._state = "error"
                self._last_error = f"解析或打开 LSL 失败：{exc}"
                logging.exception(self._last_error)
                await asyncio.sleep(self.resolve_retry_interval_sec)
        return False

    def _start_ingest_thread(self) -> None:
        """启动唯一的独立摄取线程，避免 pylsl 拉流占用 FastAPI 事件循环。"""
        if self._ingest_thread is not None and self._ingest_thread.is_alive():
            return
        self._ingest_stop.clear()
        self._ingest_thread = threading.Thread(
            target=self._ingest_loop,
            name=f"lsl-ingest-{self.stream_name}",
            daemon=True,
        )
        self._ingest_thread.start()

    def _ingest_loop(self) -> None:
        """阻塞拉取 LSL 样本、按配置打包，并线程安全地投递回调。"""
        buffer: List[List[float]] = []
        try:
            while self.is_streaming and not self._ingest_stop.is_set():
                with self._inlet_lock:
                    inlet = self.inlet
                if inlet is None:
                    return
                samples, _timestamps = inlet.pull_chunk(
                    timeout=0.1,
                    max_samples=self.buffer_size,
                )
                if not samples:
                    continue
                buffer.extend(samples)
                while len(buffer) >= self.buffer_size:
                    chunk = buffer[: self.buffer_size]
                    del buffer[: self.buffer_size]
                    self._dispatch_chunk(chunk)
        except Exception as exc:
            if self.is_streaming and not self._ingest_stop.is_set():
                self._state = "error"
                self._last_error = f"LSL 摄取线程异常：{exc}"
                logging.exception(self._last_error)

    def _dispatch_chunk(self, chunk: List[List[float]]) -> None:
        """将摄取线程产生的数据块投递到创建流转发器的事件循环。"""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._invoke_callbacks, chunk)

    def _invoke_callbacks(self, chunk: List[List[float]]) -> None:
        """在事件循环线程调用所有回调，并调度可能返回的协程。"""
        for callback in list(self._callbacks):
            try:
                result = callback(chunk)
                if inspect.isawaitable(result):
                    asyncio.create_task(result)
            except Exception:
                logging.exception("LSL 数据回调异常")

    def start(self) -> None:
        """绑定当前事件循环并启动解析与独立摄取流程。"""
        if self.is_streaming:
            return
        self._loop = asyncio.get_running_loop()
        self.is_streaming = True
        self._state = "resolving"
        self._ingest_stop.clear()
        self.task = asyncio.create_task(self._run())

    def stop(self) -> None:
        """停止解析任务与摄取线程，并关闭 LSL inlet。"""
        self.is_streaming = False
        self._state = "stopped"
        self._ingest_stop.set()
        if self.task is not None:
            self.task.cancel()
            self.task = None
        self._close_inlet()
        if self._ingest_thread is not None and not self._ingest_thread.is_alive():
            self._ingest_thread = None
        logging.info("LSL Streamer stopped.")

    def _close_inlet(self) -> None:
        """并发安全地摘除并关闭当前 inlet。"""
        with self._inlet_lock:
            inlet = self.inlet
            self.inlet = None
        if inlet is not None:
            try:
                inlet.close_stream()
            except Exception:
                logging.exception("关闭 LSL inlet 失败")
