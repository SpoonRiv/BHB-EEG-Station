#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: Trigger TCP 客户端（连接本机/局域网触发服务并发送 start/end 等命令）
作者: Spoon
"""

from __future__ import annotations

import socket
from typing import Optional


class TriggerClient:
    """
    Trigger TCP 客户端。

    说明：
        该客户端用于向外部“触发服务/刺激程序”发送简单字符串命令（如 start/end）。
        协议来自旧版参考实现：建立 TCP 连接后直接发送 UTF-8 字节串，无额外包头/长度字段。

    Args:
        host: 触发服务地址。
        port: 触发服务端口。
        timeout_sec: socket 超时（秒），同时作用于 connect 与 send。

    Raises:
        ConnectionError: 连接失败或发送失败。
        ValueError: host/port 非法。
    """

    def __init__(self, host: str, port: int, timeout_sec: float = 1.0):
        host_s = str(host or "").strip()
        if not host_s:
            raise ValueError("host 不能为空")
        port_i = int(port)
        if port_i <= 0 or port_i > 65535:
            raise ValueError(f"port 非法: {port}")

        self._host = host_s
        self._port = port_i
        self._timeout_sec = float(timeout_sec)
        self._sock: Optional[socket.socket] = None

        try:
            self._sock = socket.create_connection((self._host, self._port), timeout=self._timeout_sec)
            try:
                self._sock.settimeout(self._timeout_sec)
            except Exception:
                pass
        except OSError as e:
            raise ConnectionError(f"连接 trigger 服务失败: {e}") from e

    def send_trigger(self, command: str) -> None:
        """
        发送 trigger 命令。

        Args:
            command: 命令字符串，例如 "start" / "end"。

        Raises:
            ConnectionError: 连接已关闭或发送失败。
        """

        if self._sock is None:
            raise ConnectionError("trigger socket 已关闭")

        payload = str(command or "").encode("utf-8")
        try:
            self._sock.sendall(payload)
        except OSError as e:
            raise ConnectionError(f"发送 trigger 命令失败: {e}") from e

    def close_client(self) -> None:
        """
        关闭 trigger 连接。

        注意：
            该方法幂等；多次调用不会抛异常。
        """

        sock = self._sock
        self._sock = None
        if sock is None:
            return
        try:
            sock.close()
        except Exception:
            pass
