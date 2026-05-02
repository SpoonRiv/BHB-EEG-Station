#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: LSL 数据流接收与缓冲打包（从 pylsl 拉取 EEG 数据并通过回调向上层提供 chunk）

修改日志:
- 2026-04-30: 1.0.0 创建文件
- 2026-05-02: 1.0.1 修复 LSL 解析不稳定：按 stream_name 解析并支持超时重试，避免“已启动但无波形”
- 2026-05-02: 1.0.2 解析后显式 open_stream，提升 pull_chunk 获取数据的稳定性

作者: Spoon
版本: 1.0.2
"""

import asyncio
import inspect
import logging
from typing import Any, Callable, Dict, List, Optional
from pylsl import resolve_byprop, StreamInlet

class LSLStreamer:
    """
    LSL 数据流接收与转发器。
    用于异步读取 pylsl 数据流，节流打包后供 WebSocket 广播使用。
    """

    def __init__(
        self,
        stream_name: str,
        stream_type: str,
        buffer_size: int = 10,
        resolve_timeout_sec: float = 1.0,
        resolve_retry_interval_sec: float = 0.5,
    ):
        """
        初始化 LSLStreamer。

        Args:
            stream_name: LSL 流名（优先按 name 精确解析，避免误连到其它 EEG 流）。
            stream_type: LSL 流类型（用于二次校验/排错提示）。
            buffer_size: 每次回调打包的采样点数（>0）。
            resolve_timeout_sec: 单次解析等待时长（秒），建议较小以便可取消与快速重试。
            resolve_retry_interval_sec: 解析失败后的重试间隔（秒）。
        """
        self.stream_name = stream_name
        self.stream_type = stream_type
        self.buffer_size = max(1, int(buffer_size))
        self.resolve_timeout_sec = max(0.05, float(resolve_timeout_sec))
        self.resolve_retry_interval_sec = max(0.05, float(resolve_retry_interval_sec))
        
        self.inlet: Optional[StreamInlet] = None
        self.is_streaming = False
        self.task: Optional[asyncio.Task] = None

        self._state: str = "stopped"  # stopped|resolving|streaming|error
        self._last_error: str = ""
        
        self._buffer: List[List[float]] = []
        self._callbacks: List[Callable[[List[List[float]]], None]] = []

    def add_callback(self, callback: Callable[[List[List[float]]], None]):
        """
        注册数据接收回调。当缓存满时触发。
        """
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[List[List[float]]], None]):
        """
        移除回调。
        """
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def get_status(self) -> Dict[str, Any]:
        """
        获取 LSLStreamer 状态（供 /api/status 与前端自检使用）。

        Returns:
            Dict[str, Any]: {state, stream_name, stream_type, buffer_size, last_error}
        """
        return {
            "state": self._state,
            "stream_name": self.stream_name,
            "stream_type": self.stream_type,
            "buffer_size": self.buffer_size,
            "last_error": self._last_error,
        }

    async def _resolve_stream(self) -> bool:
        """
        解析 LSL 流并建立 inlet。

        设计要点：
        - 仅按 type 解析会出现“先匹配到其它 EEG 流，目标 name 尚未出现”的情况，导致误判失败并退出；
        - resolve_byprop 默认超时极长，任务难以取消且排查困难；
        - 因此这里按 stream_name 精确解析，并使用短超时循环重试。
        """
        self._state = "resolving"
        self._last_error = ""
        logging.info(f"Looking for an LSL stream name='{self.stream_name}', type='{self.stream_type}' ...")

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

                target_stream = streams[0]
                try:
                    resolved_type = str(target_stream.type() or "")
                    if self.stream_type and resolved_type and resolved_type != self.stream_type:
                        self._last_error = f"LSL 流类型不匹配：期望 {self.stream_type}，实际 {resolved_type}"
                except Exception:
                    pass

                self.inlet = StreamInlet(target_stream)
                try:
                    await asyncio.to_thread(self.inlet.open_stream, float(self.resolve_timeout_sec))
                except Exception as e:
                    try:
                        self.inlet.close_stream()
                    except Exception:
                        pass
                    self.inlet = None
                    self._state = "error"
                    self._last_error = f"打开 LSL inlet 失败：{e}"
                    logging.error(self._last_error)
                    await asyncio.sleep(self.resolve_retry_interval_sec)
                    continue
                self._state = "streaming"
                self._last_error = ""
                logging.info(f"LSL stream resolved: name='{self.stream_name}'.")
                return True
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._state = "error"
                self._last_error = f"解析 LSL 失败：{e}"
                logging.error(self._last_error)
                await asyncio.sleep(self.resolve_retry_interval_sec)

        return False

    async def _stream_loop(self):
        """
        异步循环：不断从 inlet 拉取数据，存入 buffer，
        达到 buffer_size 时触发回调，清理 buffer。
        """
        if not await self._resolve_stream():
            self.is_streaming = False
            self._state = "stopped"
            return

        self._buffer.clear()
        
        logging.info("LSL Streamer started listening for data...")
        
        while self.is_streaming:
            try:
                # 使用 timeout=0 非阻塞获取一组数据 (chunk)
                samples, timestamps = self.inlet.pull_chunk(timeout=0.0, max_samples=self.buffer_size)
                if samples:
                    self._buffer.extend(samples)
                    
                    while len(self._buffer) >= self.buffer_size:
                        # 截取 buffer_size 大小的数据，剩余的留在 _buffer 中
                        chunk_to_send = self._buffer[:self.buffer_size]
                        self._buffer = self._buffer[self.buffer_size:]
                        
                        # 触发所有回调
                        for callback in self._callbacks:
                            try:
                                result: Any = callback(chunk_to_send)
                                if inspect.isawaitable(result):
                                    asyncio.create_task(result)
                            except Exception as e:
                                logging.error(f"Callback error: {e}")
                    
                    # 避免在连续大量数据到达时阻塞主事件循环，造成 WebSocket 饿死
                    await asyncio.sleep(0.001)
                else:
                    # 避免空转占用 100% CPU，适当休眠
                    await asyncio.sleep(0.005)
            except Exception as e:
                logging.error(f"Error during LSL pull_chunk: {e}")
                try:
                    if self.inlet:
                        self.inlet.close_stream()
                except Exception:
                    pass
                self.inlet = None
                self._state = "resolving"
                await asyncio.sleep(0.1)
                await self._resolve_stream()

    def start(self):
        """
        启动 LSL 数据拉取循环
        """
        if self.is_streaming:
            return
        self.is_streaming = True
        self._state = "resolving"
        self.task = asyncio.create_task(self._stream_loop())

    def stop(self):
        """
        停止 LSL 数据拉取循环
        """
        self.is_streaming = False
        self._state = "stopped"
        if self.task:
            self.task.cancel()
            self.task = None
        if self.inlet:
            self.inlet.close_stream()
            self.inlet = None
        logging.info("LSL Streamer stopped.")
