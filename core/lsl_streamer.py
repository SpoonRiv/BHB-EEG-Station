#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 {Company}. All rights reserved.

文件功能: LSL 数据流接收与缓冲打包（从 pylsl 拉取 EEG 数据并通过回调向上层提供 chunk）

修改日志:
- 2026-04-30: 1.0.0 创建文件

作者: Spoon
版本: 1.0.0
"""

import asyncio
import inspect
import logging
from typing import Any, Callable, List, Optional
from pylsl import resolve_byprop, StreamInlet

class LSLStreamer:
    """
    LSL 数据流接收与转发器。
    用于异步读取 pylsl 数据流，节流打包后供 WebSocket 广播使用。
    """
    def __init__(self, stream_name: str, stream_type: str, buffer_size: int = 10):
        self.stream_name = stream_name
        self.stream_type = stream_type
        self.buffer_size = buffer_size
        
        self.inlet: Optional[StreamInlet] = None
        self.is_streaming = False
        self.task: Optional[asyncio.Task] = None
        
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

    async def _resolve_stream(self) -> bool:
        """
        解析 LSL 流并建立 inlet。
        """
        logging.info(f"Looking for an LSL stream '{self.stream_name}' of type '{self.stream_type}'...")
        # pylsl 中 resolve_byprop 返回所有匹配属性的流列表
        streams = await asyncio.to_thread(resolve_byprop, 'type', self.stream_type)
        if not streams:
            logging.error(f"No stream found with type {self.stream_type}.")
            return False

        target_stream = None
        for stream in streams:
            if stream.name() == self.stream_name:
                target_stream = stream
                break
        
        if not target_stream:
            logging.error(f"Stream {self.stream_name} not found among available {self.stream_type} streams.")
            return False

        self.inlet = StreamInlet(target_stream)
        logging.info(f"LSL stream '{self.stream_name}' resolved successfully.")
        return True

    async def _stream_loop(self):
        """
        异步循环：不断从 inlet 拉取数据，存入 buffer，
        达到 buffer_size 时触发回调，清理 buffer。
        """
        if not await self._resolve_stream():
            self.is_streaming = False
            return

        self.is_streaming = True
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
                await asyncio.sleep(0.1)

    def start(self):
        """
        启动 LSL 数据拉取循环
        """
        if self.is_streaming:
            return
        self.task = asyncio.create_task(self._stream_loop())

    def stop(self):
        """
        停止 LSL 数据拉取循环
        """
        self.is_streaming = False
        if self.task:
            self.task.cancel()
            self.task = None
        if self.inlet:
            self.inlet.close_stream()
            self.inlet = None
        logging.info("LSL Streamer stopped.")
