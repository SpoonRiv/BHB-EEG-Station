#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 基于 Windows 蓝牙 SPP 串口的 EEG 采集链路，负责串口扫描、控制指令发送、16通道帧解析与 LSL 推流

作者: Spoon
"""

import multiprocessing
import queue
import time
from typing import Any, Dict, List, Optional

from configs.config_loader import BluetoothConfig, load_config
from core.ble.commands import interpret_two_level_cmd
from core.ble.frame_parser import FrameSpec, parse_frame_to_samples
from core.ble.lsl_outlet import LslOutletConfig, LslOutletWriter
from core.ble.module_naming import BleModuleNameInfo, parse_ble_module_name

try:
    import serial
    from serial.tools import list_ports
except Exception:
    serial = None
    list_ports = None


def _build_module_payload(info: Optional[BleModuleNameInfo]) -> Optional[Dict[str, int]]:
    """
    将设备型号解析结果转换为前后端共用的模块能力结构。
    """

    if info is None:
        return None
    return {"eeg_channels": int(info.eeg_channels), "stim_channels": int(info.stim_channels)}


def list_spp_devices(cfg: BluetoothConfig) -> List[Dict[str, Any]]:
    """
    返回当前配置下可用于 SPP 串口采集的候选设备列表。

    设计说明:
        - 若配置了固定 `port_name`，优先返回该串口，避免没有 pyserial 时前端无法继续；
        - 若未配置固定串口且本机可枚举串口，则按“蓝牙/SPP/目标设备关键字”过滤候选；
        - 返回结构与 BLE 扫描接口兼容，复用现有前端设备选择页。
    """

    configured_port = str(cfg.spp.port_name or "").strip()
    configured_name = str(cfg.target_device or "").strip()
    module_info = parse_ble_module_name(configured_name, str(cfg.module_name_regex or ""))
    module_payload = _build_module_payload(module_info)
    capabilities = {"tdcs": bool(module_payload and int(module_payload.get("stim_channels", 0)) > 0)} if module_payload else None

    out: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def append_device(port_name: str, display_name: str) -> None:
        normalized_port = str(port_name or "").strip()
        if not normalized_port:
            return
        upper_port = normalized_port.upper()
        if upper_port in seen:
            return
        seen.add(upper_port)
        out.append(
            {
                "name": str(display_name or configured_name or normalized_port).strip() or normalized_port,
                "address": normalized_port,
                "rssi": None,
                "module": module_payload,
                "capabilities": capabilities,
            }
        )

    if configured_port:
        append_device(configured_port, configured_name or configured_port)

    if list_ports is None:
        return out

    if configured_port:
        for port in list_ports.comports():
            if str(getattr(port, "device", "") or "").strip().upper() == configured_port.upper():
                display_name = configured_name or str(getattr(port, "description", "") or "").strip() or configured_port
                append_device(configured_port, display_name)
                return out
        return out

    keywords = [str(cfg.target_device or "").strip().lower()]
    for prefix in cfg.device_names or []:
        p = str(prefix or "").strip().lower()
        if p:
            keywords.append(p)
    keywords.extend(["bluetooth", "spp", "standard serial over bluetooth link"])

    for port in list_ports.comports():
        text = " ".join(
            [
                str(getattr(port, "device", "") or ""),
                str(getattr(port, "description", "") or ""),
                str(getattr(port, "manufacturer", "") or ""),
                str(getattr(port, "name", "") or ""),
            ]
        ).lower()
        if not any(keyword and keyword in text for keyword in keywords):
            continue
        display_name = configured_name or str(getattr(port, "description", "") or "").strip() or str(getattr(port, "device", "") or "").strip()
        append_device(str(getattr(port, "device", "") or "").strip(), display_name)

    return out


def run_spp_acquisition_process(
    config_path: str,
    stop_event: multiprocessing.Event,
    status_queue: multiprocessing.Queue,
    command_queue: multiprocessing.Queue,
    debug_queue: Optional[multiprocessing.Queue] = None,
    connect_address: Optional[str] = None,
    connect_name: Optional[str] = None,
    channel_mode_override: Optional[int] = None,
) -> None:
    """
    SPP 串口采集进程入口。

    参数:
        config_path: 主配置文件路径。
        stop_event: 进程停止事件。
        status_queue: 向主进程上报状态/电量/IMU 的队列。
        command_queue: 主进程下发控制指令的队列。
        debug_queue: 结构化调试事件队列。
        connect_address: 前端选择的串口名（如 `COM5`）。
        connect_name: 前端选择的显示名称。
    """

    if serial is None:
        status_queue.put({"type": "error", "message": "当前环境缺少 pyserial，请先安装并同步环境依赖"})
        return

    cfg = load_config(config_path)
    eeg_n_channels = int(channel_mode_override) if channel_mode_override is not None else int(cfg.eeg.n_channels)
    eeg_proto = cfg.eeg.protocol.ch8 if eeg_n_channels == 8 else cfg.eeg.protocol.ch16
    if eeg_proto is None:
        status_queue.put({"type": "error", "message": "eeg.n_channels=16 时必须配置 eeg.protocol.ch16.frame"})
        return

    port_name = str(connect_address or "").strip() or str(cfg.bluetooth.spp.port_name or "").strip()
    if not port_name:
        status_queue.put({"type": "error", "message": "SPP 串口未配置，请在 bluetooth.spp.port_name 中填写 COM 口"})
        return

    resolved_name = str(connect_name or "").strip() or str(cfg.bluetooth.target_device or "").strip() or port_name
    module_info = parse_ble_module_name(resolved_name, str(cfg.bluetooth.module_name_regex or ""))
    if module_info is None:
        module_info = parse_ble_module_name(str(cfg.bluetooth.target_device or ""), str(cfg.bluetooth.module_name_regex or ""))
    if module_info is not None and int(module_info.eeg_channels) != eeg_n_channels:
        status_queue.put(
            {
                "type": "error",
                "message": f"设备型号解析为 {int(module_info.eeg_channels)} 通道，但当前配置为 {eeg_n_channels} 通道",
                "address": port_name,
                "name": resolved_name,
                "module": _build_module_payload(module_info),
            }
        )
        return

    channel_count = eeg_n_channels + (1 if cfg.eeg.lsl.include_trigger_channel else 0)
    spec = FrameSpec(
        channels=eeg_n_channels,
        header_len_bytes=eeg_proto.frame.header_len_bytes,
        bytes_per_sample_per_channel=eeg_proto.frame.bytes_per_sample_per_channel,
        samples_per_frame=eeg_proto.frame.samples_per_frame,
        trigger_len_bytes=eeg_proto.frame.trigger_len_bytes,
        trigger_decode_mode=eeg_proto.frame.trigger_decode_mode,
        imu_len_bytes=eeg_proto.frame.imu_len_bytes,
        battery_len_bytes=eeg_proto.frame.battery_len_bytes,
        tail_len_bytes=eeg_proto.frame.tail_len_bytes,
    )
    outlet = LslOutletWriter(
        LslOutletConfig(
            stream_name=cfg.eeg.lsl.stream_name,
            stream_type=cfg.eeg.lsl.stream_type,
            channel_count=channel_count,
            sampling_rate_hz=cfg.eeg.sampling_rate_hz,
            source_id=f"bhb-eeg-spp-{port_name}",
        )
    )

    status_payload: Dict[str, Any] = {"type": "connecting", "address": port_name, "name": resolved_name}
    module_payload = _build_module_payload(module_info)
    if module_payload is not None:
        status_payload["module"] = module_payload
    status_queue.put(status_payload)

    serial_port: Optional[Any] = None
    try:
        serial_port = serial.Serial(
            port=port_name,
            baudrate=int(cfg.bluetooth.spp.baudrate),
            timeout=float(cfg.bluetooth.spp.timeout_sec),
            write_timeout=float(cfg.bluetooth.spp.timeout_sec),
        )
        # #region debug-point D:serial-open-ok
        try:
            import json, os, urllib.request
            _p = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".dbg", "spp-connect-fail.env")
            _u, _s = "http://127.0.0.1:7777/event", "spp-connect-fail"
            exec("try:\n with open(_p, encoding='utf-8') as f: c=f.read(); _u=next((l.split('=',1)[1] for l in c.split('\\n') if l.startswith('DEBUG_SERVER_URL=')), _u); _s=next((l.split('=',1)[1] for l in c.split('\\n') if l.startswith('DEBUG_SESSION_ID=')), _s)\nexcept: pass")
            urllib.request.urlopen(urllib.request.Request(_u, data=json.dumps({"sessionId": _s, "runId": "pre-fix", "hypothesisId": "D", "location": "spp_transport.py:199", "msg": "[DEBUG] SPP 串口打开成功", "data": {"port_name": str(port_name), "baudrate": int(cfg.bluetooth.spp.baudrate), "timeout_sec": float(cfg.bluetooth.spp.timeout_sec), "resolved_name": str(resolved_name)}, "ts": int(time.time() * 1000)}).encode(), headers={"Content-Type": "application/json"}), timeout=0.3).read()
        except Exception:
            pass
        # #endregion
        status_payload = {"type": "connected", "address": port_name, "name": resolved_name}
        if module_payload is not None:
            status_payload["module"] = module_payload
        status_queue.put(status_payload)

        status_payload = {"type": "ready", "address": port_name, "name": resolved_name}
        if module_payload is not None:
            status_payload["module"] = module_payload
        status_queue.put(status_payload)

        eeg_streaming_enabled = False
        current_mode = "idle"
        frame_counter = 0
        read_counter = 0
        start_retry_count = 0
        last_start_cmd_ts = 0.0
        last_rx_ts = time.time()
        no_data_reported = False
        buf = bytearray()

        def _emit_debug(tag: str, message: str, data: Optional[Dict[str, Any]] = None) -> None:
            if debug_queue is None:
                return
            try:
                debug_queue.put({"tag": tag, "message": message, "data": data or {}})
            except Exception:
                pass

        def _send_cmd(cmd: List[int], action: str) -> None:
            if serial_port is None:
                raise RuntimeError("SPP 串口未连接")
            payload = bytearray(int(x) & 0xFF for x in (cmd or []))
            if len(payload) < 2:
                raise ValueError("控制指令长度不足 2 字节")
            serial_port.write(payload)
            serial_port.flush()
            cmd_hex = " ".join(f"0x{int(x) & 0xFF:02X}" for x in payload)
            cmd_info = interpret_two_level_cmd(list(payload))
            _emit_debug(
                "CMD_TX",
                f"发送串口控制指令: {action}",
                {"cmd_hex": cmd_hex, "port_name": port_name, **cmd_info},
            )

        def _get_trigger_source_command() -> List[int]:
            source_mode = str(getattr(cfg.trigger, "source_mode", "ble") or "ble").strip().lower()
            if source_mode == "ttl_uart":
                return list(cfg.bluetooth.commands.trigger_source_ttl_uart)
            if source_mode == "ttl_level":
                return list(cfg.bluetooth.commands.trigger_source_ttl_level)
            return list(cfg.bluetooth.commands.trigger_source_ble)

        def _push_one_frame(one_frame: bytes) -> None:
            nonlocal frame_counter

            samples, battery, imu = parse_frame_to_samples(one_frame, spec)
            frame_counter += 1
            if cfg.eeg.lsl.include_trigger_channel:
                samples_to_push = [s[:eeg_n_channels + 1] for s in samples]
            else:
                samples_to_push = [s[:eeg_n_channels] for s in samples]
            outlet.push_samples(samples_to_push)
            if spec.battery_len_bytes > 0 and (frame_counter == 1 or frame_counter % 50 == 0):
                status_queue.put({"type": "battery", "value": int(battery)})
            if imu and frame_counter % 50 == 0:
                status_queue.put({"type": "imu", "value": imu})

        def _process_eeg_bytes(data: bytes) -> None:
            nonlocal read_counter, last_rx_ts, no_data_reported

            if not data:
                return
            read_counter += 1
            last_rx_ts = time.time()
            no_data_reported = False
            if read_counter % 10 == 0:
                _emit_debug("EEG_RX", "收到SPP EEG串口数据", {"len": int(len(data)), "port_name": port_name})

            expected = int(spec.frame_len_bytes)
            if len(data) == expected:
                if len(buf) > 0:
                    buf.clear()
                one = bytes(data)
                if spec.validate_checksum(one):
                    _push_one_frame(one)
                    return

            buf.extend(data)
            header_bytes = bytes([0xAA, 0xBB])
            for _ in range(200):
                if len(buf) < 2:
                    break
                pos = buf.find(header_bytes)
                if pos < 0:
                    if len(buf) > 1:
                        del buf[:-1]
                    break
                if pos > 0:
                    del buf[:pos]
                if len(buf) < expected:
                    break
                candidate = bytes(buf[:expected])
                if not spec.validate_checksum(candidate):
                    del buf[:1]
                    continue
                del buf[:expected]
                _push_one_frame(candidate)

        while not stop_event.is_set():
            try:
                cmd_msg: Dict[str, Any] = command_queue.get_nowait()
                msg_type = str(cmd_msg.get("type", ""))
                if msg_type == "select_mode":
                    current_mode = str(cmd_msg.get("mode", "idle"))
                    status_queue.put({"type": "mode", "mode": current_mode})
                elif msg_type == "start_mode":
                    mode = str(cmd_msg.get("mode", ""))
                    if mode != "eeg":
                        status_queue.put({"type": "error", "message": f"SPP 传输当前仅支持 EEG 模式，暂不支持 {mode}"})
                        continue
                    current_mode = "eeg"
                    eeg_streaming_enabled = False
                    buf.clear()
                    frame_counter = 0
                    read_counter = 0
                    start_retry_count = 0
                    if bool(getattr(cfg, "trigger", None) and cfg.trigger.enabled):
                        _send_cmd(_get_trigger_source_command(), action=f"select_trigger_source_{str(cfg.trigger.source_mode)}")
                    _send_cmd(list(cfg.bluetooth.commands.start_eeg), action="start_eeg")
                    last_start_cmd_ts = time.time()
                    last_rx_ts = time.time()
                    no_data_reported = False
                    eeg_streaming_enabled = True
                    status_queue.put({"type": "mode_started", "mode": "eeg"})
                elif msg_type == "stop_mode":
                    mode = str(cmd_msg.get("mode", ""))
                    if mode == "eeg":
                        eeg_streaming_enabled = False
                        buf.clear()
                        _send_cmd(list(cfg.bluetooth.commands.stop_eeg), action="stop_eeg")
                        status_queue.put({"type": "mode_stopped", "mode": "eeg"})
                    current_mode = "idle"
                    status_queue.put({"type": "mode", "mode": current_mode})
                elif msg_type == "send_cmd":
                    raw = cmd_msg.get("cmd", [])
                    cmd: List[int] = []
                    if isinstance(raw, list):
                        for value in raw:
                            try:
                                cmd.append(int(value) & 0xFF)
                            except Exception:
                                continue
                    if len(cmd) < 2:
                        _emit_debug("CMD_TX", "忽略非法串口控制指令：长度不足 2 字节", {"raw": raw})
                        continue
                    _send_cmd(cmd, action="panel_send_cmd")
            except queue.Empty:
                pass
            except Exception as exc:
                status_queue.put({"type": "error", "message": str(exc), "address": port_name, "name": resolved_name})

            if not eeg_streaming_enabled:
                time.sleep(0.05)
                continue

            try:
                waiting = int(getattr(serial_port, "in_waiting", 0) or 0)
                read_size = max(int(spec.frame_len_bytes), waiting) if waiting > 0 else int(spec.frame_len_bytes)
                data = serial_port.read(read_size)
            except Exception as exc:
                status_queue.put(
                    {
                        "type": "disconnected",
                        "message": f"SPP 串口读取失败：{str(exc)}",
                        "address": port_name,
                        "name": resolved_name,
                    }
                )
                return

            if data:
                _process_eeg_bytes(bytes(data))
            else:
                now_ts = time.time()
                if not no_data_reported and (now_ts - last_rx_ts) > 3.0:
                    no_data_reported = True
                    _emit_debug("EEG_NODATA", "3秒未收到 SPP EEG 串口数据", {"port_name": port_name})
                if read_counter == 0 and start_retry_count < 2 and (now_ts - last_start_cmd_ts) > 1.0:
                    start_retry_count += 1
                    last_start_cmd_ts = now_ts
                    try:
                        _send_cmd(list(cfg.bluetooth.commands.start_eeg), action=f"start_eeg_retry_{int(start_retry_count)}")
                    except Exception as exc:
                        _emit_debug("CMD_TX", "重发 start_eeg 串口指令失败", {"retry": int(start_retry_count), "error": str(exc)})
                time.sleep(0.01)

        if eeg_streaming_enabled:
            try:
                _send_cmd(list(cfg.bluetooth.commands.stop_eeg), action="stop_eeg")
            except Exception:
                pass
    except Exception as exc:
        # #region debug-point D:serial-open-fail
        try:
            import json, os, urllib.request
            _p = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".dbg", "spp-connect-fail.env")
            _u, _s = "http://127.0.0.1:7777/event", "spp-connect-fail"
            exec("try:\n with open(_p, encoding='utf-8') as f: c=f.read(); _u=next((l.split('=',1)[1] for l in c.split('\\n') if l.startswith('DEBUG_SERVER_URL=')), _u); _s=next((l.split('=',1)[1] for l in c.split('\\n') if l.startswith('DEBUG_SESSION_ID=')), _s)\nexcept: pass")
            urllib.request.urlopen(urllib.request.Request(_u, data=json.dumps({"sessionId": _s, "runId": "pre-fix", "hypothesisId": "D", "location": "spp_transport.py:198", "msg": "[DEBUG] SPP 串口打开失败", "data": {"port_name": str(port_name), "resolved_name": str(resolved_name), "error": str(exc)}, "ts": int(time.time() * 1000)}).encode(), headers={"Content-Type": "application/json"}), timeout=0.3).read()
        except Exception:
            pass
        # #endregion
        status_queue.put({"type": "error", "message": str(exc), "address": port_name, "name": resolved_name})
    finally:
        if serial_port is not None:
            try:
                serial_port.close()
            except Exception:
                pass
        time.sleep(0.1)
