#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 {Company}. All rights reserved.

文件功能: 后端入口（FastAPI 应用、静态前端挂载、HTTP API、WebSocket 实时广播 EEG 数据）

修改日志:
- 2026-04-30: 1.0.0 创建文件

作者: Spoon
版本: 1.0.0
"""

import asyncio
import os
import logging
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from configs.config_loader import load_config
from core.eeg_controller import EEGController
from core.lsl_streamer import LSLStreamer
from core.debug_bus import DebugEventBus

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class AppState:
    def __init__(self):
        self.config_path = os.path.join(os.path.dirname(__file__), "configs", "config.yaml")
        self.config = load_config(self.config_path)
        self.controller = EEGController(config_path=self.config_path)
        self.debug_bus = DebugEventBus(max_events=self.config.debug.max_events)
        self._debug_forward_started = False

        lsl_name = self.config.eeg.lsl.stream_name
        lsl_type = self.config.eeg.lsl.stream_type
        buffer_size = self.config.streaming.buffer_size

        self.streamer = LSLStreamer(stream_name=lsl_name, stream_type=lsl_type, buffer_size=buffer_size)
        self.active_websockets: List[WebSocket] = []

    async def broadcast_eeg_data(self, chunk: List[List[float]]):
        """
        回调函数：当 LSL Streamer 凑齐一个 chunk 的数据时，通过 WebSocket 广播给所有前端
        """
        if not self.active_websockets:
            return
            
        data_to_send = {
            "type": "eeg_data",
            "data": chunk
        }
        
        disconnected_ws = []
        for ws in self.active_websockets:
            try:
                await ws.send_json(data_to_send)
            except Exception as e:
                logging.error(f"WebSocket send error: {e}")
                disconnected_ws.append(ws)
                
        for ws in disconnected_ws:
            self.active_websockets.remove(ws)

state = AppState()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 生命周期管理：启动时注册数据流回调，关闭时停止设备。
    """
    logging.info("Application starting: registering callbacks...")
    state.streamer.add_callback(state.broadcast_eeg_data)
    if state.config.debug.ui_enabled and not state._debug_forward_started:
        if state.controller.debug_queue is not None:
            state.debug_bus.start_forward_from_mp_queue(state.controller.debug_queue)
            state._debug_forward_started = True
    yield
    logging.info("Application shutting down: cleaning up resources...")
    state.streamer.stop()
    await asyncio.to_thread(state.controller.stop_device)
    await state.debug_bus.stop_forward()

app = FastAPI(title="BHB-SSVEP Web API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载前端静态文件
app.mount("/web", StaticFiles(directory="web"), name="web")


@app.get("/")
async def root():
    return RedirectResponse(url="/web/index.html")


@app.get("/api/start")
async def start_eeg():
    """启动蓝牙设备与 LSL 数据流"""
    if state.config.debug.ui_enabled:
        state.debug_bus.publish(tag="UI", message="点击开始采集", data={})
    success = await asyncio.to_thread(state.controller.start_device)
    if success:
        if state.config.debug.ui_enabled and state.controller.debug_queue is not None and not state._debug_forward_started:
            state.debug_bus.start_forward_from_mp_queue(state.controller.debug_queue)
            state._debug_forward_started = True
        state.streamer.start()
        return {"status": "success", "message": "蓝牙采集已启动并连接成功。", "device": state.controller.get_status()}
    last = state.controller.last_status or {"type": "error", "message": "启动失败"}
    if state.config.debug.ui_enabled:
        state.debug_bus.publish(tag="UI", message="开始采集失败", data={"reason": last.get("message", "")})
    return {"status": "error", "message": last.get("message", "启动失败"), "detail": last, "device": state.controller.get_status()}

@app.get("/api/config")
async def get_config():
    """
    获取前端渲染所需的基础配置（通道数、通道名等）。
    """
    return {
        "mode_channels": state.config.eeg.mode_channels,
        "channel_names": state.config.eeg.channel_names,
        "sampling_rate_hz": state.config.eeg.sampling_rate_hz,
        "buffer_size": state.config.streaming.buffer_size,
        "update_fps": state.config.streaming.update_fps,
    }

@app.get("/api/status")
async def get_status():
    """
    获取采集状态（用于前端连接指示与设备名展示）。
    """
    return {
        "device": state.controller.get_status(),
        "lsl_streaming": bool(getattr(state.streamer, "is_streaming", False)),
    }

@app.get("/api/stop")
async def stop_eeg():
    """停止蓝牙设备与 LSL 数据流"""
    if state.config.debug.ui_enabled:
        state.debug_bus.publish(tag="UI", message="点击停止采集", data={})
    state.streamer.stop()
    success = await asyncio.to_thread(state.controller.stop_device)
    if success:
        return {"status": "success", "message": "采集已停止。", "device": state.controller.get_status()}
    return {"status": "error", "message": "停止采集失败。", "device": state.controller.get_status()}

@app.get("/api/debug/events")
async def get_debug_events(limit: int = 200):
    """
    获取最近调试事件（用于调试界面初次加载补发）。
    """
    if not state.config.debug.ui_enabled:
        return {"enabled": False, "events": []}
    return {"enabled": True, "events": state.debug_bus.get_recent(limit=limit)}

@app.websocket("/ws/debug")
async def debug_ws(websocket: WebSocket):
    """
    调试事件 WebSocket：仅推送“调试事件”，不推送网络/蓝牙连接信息。
    """
    if not state.config.debug.ui_enabled:
        await websocket.close()
        return
    await websocket.accept()
    state.debug_bus.register_ws(websocket)
    try:
        await websocket.send_json({"type": "debug_init", "events": state.debug_bus.get_recent(limit=200)})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        state.debug_bus.unregister_ws(websocket)

@app.websocket("/ws/eeg")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket 端点，前端连接以获取实时 EEG 数据
    """
    await websocket.accept()
    state.active_websockets.append(websocket)
    logging.info("Frontend WebSocket connected.")
    try:
        while True:
            # 保持连接，处理前端可能发来的 ping 或控制信息
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        state.active_websockets.remove(websocket)
        logging.info("Frontend WebSocket disconnected.")

if __name__ == "__main__":
    import uvicorn
    host = state.config.server.host
    port = state.config.server.port
    uvicorn.run(app, host=host, port=port)
