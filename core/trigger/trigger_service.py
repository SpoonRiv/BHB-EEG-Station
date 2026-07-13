#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: Trigger 业务封装（提供开始/停止触发的幂等接口，并统一管理配置与异常）
作者: Spoon
"""

from __future__ import annotations

import socket
import socketserver
import threading
from dataclasses import dataclass
from typing import Callable, Literal, Optional


TriggerCommand = Literal["start", "end"]
TriggerSource = Literal["api", "tcp"]


@dataclass(frozen=True)
class TriggerServiceConfig:
    enabled: bool
    host: str
    port: int
    timeout_sec: float


class TriggerService:
    """
    Trigger 服务封装，统一处理 API 与 TCP 触发事件。
    """

    def __init__(
        self,
        config: TriggerServiceConfig,
        on_event: Optional[Callable[[TriggerCommand, TriggerSource], bool]] = None,
    ):
        self._config = config
        self._active: Optional[bool] = False if bool(config.enabled) else None
        self._on_event = on_event
        self._server: Optional[socketserver.ThreadingTCPServer] = None
        self._server_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self._config.enabled)

    @property
    def active(self) -> Optional[bool]:
        return self._active

    @property
    def server_running(self) -> bool:
        return self._server is not None

    def start_server(self) -> None:
        """
        启动 trigger TCP 服务端。
        """

        if not self.enabled:
            raise RuntimeError("trigger 未启用，请在配置中开启 trigger.enabled")

        with self._lock:
            if self._server is not None:
                return

            service = self

            class _Handler(socketserver.BaseRequestHandler):
                def handle(self) -> None:
                    try:
                        self.request.settimeout(float(service._config.timeout_sec))
                    except Exception:
                        pass
                    chunks = []
                    while True:
                        try:
                            data = self.request.recv(1024)
                        except socket.timeout:
                            break
                        if not data:
                            break
                        chunks.append(data)
                    if not chunks:
                        return
                    raw = b"".join(chunks)
                    try:
                        text = raw.decode("utf-8", errors="ignore").strip()
                    except Exception:
                        return
                    if not text:
                        return
                    service._handle_command_str(text, source="tcp")

            class _Server(socketserver.ThreadingTCPServer):
                allow_reuse_address = True

            server = _Server((str(self._config.host), int(self._config.port)), _Handler)
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            self._server = server
            self._server_thread = t
            if self._active is None:
                self._active = False

    def stop_server(self) -> None:
        """
        停止 trigger TCP 服务端。
        """

        with self._lock:
            server = self._server
            t = self._server_thread
            self._server = None
            self._server_thread = None

        if server is None:
            return
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass
        if t is not None:
            try:
                t.join(timeout=1.0)
            except Exception:
                pass

    def _handle_command_str(self, command: str, source: TriggerSource) -> None:
        cmd = str(command or "").strip().lower()
        if cmd.startswith("start"):
            self._handle_command("start", source=source)
            return
        if cmd.startswith("end") or cmd.startswith("stop"):
            self._handle_command("end", source=source)
            return

    def _handle_command(self, command: TriggerCommand, source: TriggerSource) -> None:
        cb = self._on_event
        if cb is not None:
            ok = bool(cb(command, source))
            if not ok:
                raise RuntimeError("EEG 设备未连接或采集进程未运行，无法下发 trigger 指令")
        if command == "start":
            self._active = True
        elif command == "end":
            self._active = False

    def start(self) -> None:
        """
        触发 start。
        """

        if not self.enabled:
            raise RuntimeError("trigger 未启用，请在配置中开启 trigger.enabled")
        self._handle_command("start", source="api")

    def stop(self) -> None:
        """
        触发 end。
        """

        if not self.enabled:
            raise RuntimeError("trigger 未启用，请在配置中开启 trigger.enabled")
        self._handle_command("end", source="api")
