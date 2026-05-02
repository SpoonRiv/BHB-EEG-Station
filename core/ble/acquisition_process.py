#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: BLE 采集进程实现（连接设备、接收通知数据、按协议组帧解析并推送到 LSL）

修改日志:
- 2026-04-30: 1.0.0 创建文件
- 2026-05-02: 1.1.0 支持连接常驻与命令队列模式切换
- 2026-05-02: 1.1.1 调整调试输出：仅在EEG启动后提示无数据，减少默认噪声

作者: Spoon
版本: 1.1.1
"""

import asyncio
import multiprocessing
import queue
import time
from typing import Any, Dict, List, Optional

from bleak import BleakClient

from configs.config_loader import load_config
from core.ble.device_finder import find_device_by_name
from core.ble.frame_parser import FrameSpec, parse_frame_to_samples
from core.ble.lsl_outlet import LslOutletConfig, LslOutletWriter


_L1_CMD_META: Dict[int, Dict[str, str]] = {
    0x00: {"name": "Get Information", "desc": "获取信息"},
    0x01: {"name": "Get Configuration", "desc": "获取配置"},
    0x02: {"name": "ADC Control", "desc": "脑电数据传输控制"},
    0x03: {"name": "Impedance Control", "desc": "阻抗检测控制"},
    0x04: {"name": "IMU Control", "desc": "IMU 数据控制"},
    0x05: {"name": "Battery Control", "desc": "电量监测控制"},
    0x06: {"name": "Trigger Source", "desc": "触发源选择"},
    0xFF: {"name": "Trigger Control", "desc": "触发控制（蓝牙程控）"},
    0x07: {"name": "tDCS Control", "desc": "tDCS 控制"},
}

_L2_CMD_META: Dict[int, Dict[int, Dict[str, str]]] = {
    0x02: {
        0x00: {"name": "Get Information", "desc": "获取信息"},
        0x01: {"name": "Start Transfer", "desc": "开始传输脑电数据"},
        0x02: {"name": "Stop Transfer", "desc": "停止传输脑电数据"},
        0x03: {"name": "Get Configuration Specific", "desc": "读取指定配置"},
        0x04: {"name": "Get Configuration All", "desc": "读取全部配置"},
        0x05: {"name": "Set Configuration Specific", "desc": "写入指定配置"},
        0x06: {"name": "Set Configuration All", "desc": "写入全部配置"},
    },
    0x03: {
        0x00: {"name": "Get Information", "desc": "获取信息"},
        0x01: {"name": "Start Impedance", "desc": "开始传输阻抗数据"},
        0x02: {"name": "Stop Impedance", "desc": "停止传输阻抗数据"},
        0x03: {"name": "Get Configuration Specific", "desc": "读取指定配置"},
        0x04: {"name": "Set Configuration Specific", "desc": "写入指定配置"},
    },
    0x04: {
        0x00: {"name": "Get Information", "desc": "获取信息"},
        0x01: {"name": "Start IMU", "desc": "开始传输 IMU 数据"},
        0x02: {"name": "Stop IMU", "desc": "停止传输 IMU 数据"},
        0x03: {"name": "Get Configuration Specific", "desc": "读取指定配置"},
        0x04: {"name": "Set Configuration Specific", "desc": "写入指定配置"},
    },
    0x05: {
        0x00: {"name": "Get Information", "desc": "获取信息"},
        0x01: {"name": "Start Battery Monitor", "desc": "开始电量监测"},
        0x02: {"name": "Stop Battery Monitor", "desc": "停止电量监测"},
        0x03: {"name": "Get Configuration Specific", "desc": "读取指定配置"},
        0x04: {"name": "Set Configuration Specific", "desc": "写入指定配置"},
    },
    0x06: {
        0x01: {"name": "BLE Trigger", "desc": "蓝牙程控触发"},
        0x02: {"name": "External TTL UART Trigger", "desc": "外部 TTL（UART 控制）触发"},
        0x03: {"name": "External TTL Level Trigger", "desc": "外部 TTL（电平控制）触发"},
    },
    0xFF: {
        0x01: {"name": "Set Trigger", "desc": "设置 Trigger"},
        0x02: {"name": "Clear Trigger", "desc": "清除 Trigger"},
    },
    0x07: {
        0x01: {"name": "Start tDCS", "desc": "启动 tDCS 工作"},
        0x02: {"name": "Stop tDCS", "desc": "停止 tDCS 工作"},
        0x10: {"name": "Set Current", "desc": "设置 tDCS 输出电流值（数字量）"},
        0x15: {"name": "Enable HV", "desc": "使能高压电路工作"},
        0x16: {"name": "Disable HV", "desc": "禁止高压电路工作"},
        0x20: {"name": "Set Ramp Up", "desc": "设置输出电流缓升时间（数字量）"},
        0x21: {"name": "Set Hold", "desc": "设置输出电流稳定工作时间（数字量）"},
        0x22: {"name": "Set Ramp Down", "desc": "设置输出电流缓降时间（数字量）"},
        0x23: {"name": "Set Alarm Threshold", "desc": "设置输出电流报警阈值（数字量）"},
    },
}


def interpret_two_level_cmd(cmd: List[int]) -> Dict[str, str]:
    """
    解析两级控制指令（一级指令 + 二级指令），用于日志展示。

    Args:
        cmd: 指令字节列表，通常至少包含 2 个字节：[L1, L2, ...]

    Returns:
        Dict[str, str]: 结构化解释字段（用于调试日志 data）。
    """
    l1 = int(cmd[0]) & 0xFF if len(cmd) >= 1 else None
    l2 = int(cmd[1]) & 0xFF if len(cmd) >= 2 else None

    out: Dict[str, str] = {}
    if l1 is None:
        return out

    out["cmd_l1_hex"] = f"0x{l1:02X}"
    l1_meta = _L1_CMD_META.get(l1)
    if l1_meta:
        out["cmd_l1_name"] = l1_meta["name"]
        out["cmd_l1_desc"] = l1_meta["desc"]
    else:
        out["cmd_l1_name"] = "Unknown"
        out["cmd_l1_desc"] = "未知一级指令"

    if l2 is None:
        return out

    out["cmd_l2_hex"] = f"0x{l2:02X}"
    l2_meta = _L2_CMD_META.get(l1, {}).get(l2)
    if l2_meta:
        out["cmd_l2_name"] = l2_meta["name"]
        out["cmd_l2_desc"] = l2_meta["desc"]
    else:
        out["cmd_l2_name"] = "Unknown"
        out["cmd_l2_desc"] = "未知二级指令"

    return out


async def _connect_and_stream(
    config_path: str,
    stop_event: multiprocessing.Event,
    status_queue: multiprocessing.Queue,
    command_queue: multiprocessing.Queue,
    debug_queue: Optional[multiprocessing.Queue],
    connect_address: Optional[str],
    connect_name: Optional[str],
) -> None:
    """
    BLE 连接与数据接收主协程：读取配置，连接 BLE，接收通知数据，并根据主进程命令队列执行模式切换/启停。
    """
    cfg = load_config(config_path)

    spec = FrameSpec(
        channels=cfg.eeg.mode_channels,
        header_len_bytes=cfg.protocol.frame.header_len_bytes,
        bytes_per_sample_per_channel=cfg.protocol.frame.bytes_per_sample_per_channel,
        samples_per_frame=cfg.protocol.frame.samples_per_frame,
        trigger_len_bytes=cfg.protocol.frame.trigger_len_bytes,
        imu_len_bytes=cfg.protocol.frame.imu_len_bytes,
        battery_len_bytes=cfg.protocol.frame.battery_len_bytes,
        tail_len_bytes=cfg.protocol.frame.tail_len_bytes,
    )

    channel_count = cfg.eeg.mode_channels + (1 if cfg.eeg.lsl.include_trigger_channel else 0)
    outlet = LslOutletWriter(
        LslOutletConfig(
            stream_name=cfg.eeg.lsl.stream_name,
            stream_type=cfg.eeg.lsl.stream_type,
            channel_count=channel_count,
            sampling_rate_hz=cfg.eeg.sampling_rate_hz,
            source_id=f"bhb-eeg-{cfg.bluetooth.target_device}",
        )
    )

    address: Optional[str] = (connect_address or "").strip() or cfg.bluetooth.mac_address.strip() or None
    resolved_name = (connect_name or "").strip() or cfg.bluetooth.target_device
    if not address:
        target = await find_device_by_name(
            target_name=cfg.bluetooth.target_device,
            max_retries=cfg.bluetooth.scan.max_retries,
            retry_interval_sec=cfg.bluetooth.scan.retry_interval_sec,
        )
        if not target:
            status_queue.put({"type": "error", "message": "未扫描到目标 BLE 设备", "name": cfg.bluetooth.target_device})
            return
        address = target.address
        resolved_name = target.name

    notify_handle = cfg.bluetooth.gatt.notify_char_handle
    write_handle = cfg.bluetooth.gatt.write_char_handle

    buf = bytearray()
    frame_counter = 0
    notify_counter = 0
    last_notify_ts: float = 0.0
    no_data_reported = False
    start_retry_count = 0
    last_start_cmd_ts: float = 0.0
    current_mode: str = "idle"
    eeg_streaming_enabled = False

    def on_notify(_: int, data: bytearray) -> None:
        nonlocal frame_counter, notify_counter, last_notify_ts, no_data_reported, eeg_streaming_enabled
        notify_counter += 1
        last_notify_ts = time.time()
        no_data_reported = False
        if debug_queue is not None:
            try:
                if notify_counter % 10 == 0:
                    debug_queue.put(
                        {
                            "tag": "EEG_RX",
                            "message": "收到EEG通知数据",
                            "data": {"len": int(len(data))},
                        }
                    )
            except Exception:
                pass
        if not eeg_streaming_enabled:
            return
        # 参考旧版已验证逻辑：若收到长度刚好为一帧（140字节）的数据包，则清空缓存，避免错位累积
        if len(data) == spec.frame_len_bytes:
            if debug_queue is not None:
                try:
                    debug_queue.put(
                        {
                            "tag": "EEG_ALIGN",
                            "message": "收到完整帧长度数据包，清空缓存以重新对齐",
                            "data": {"frame_len": int(spec.frame_len_bytes)},
                        }
                    )
                except Exception:
                    pass
            buf.clear()
        buf.extend(data)
        while len(buf) >= spec.frame_len_bytes:
            frame = bytes(buf[: spec.frame_len_bytes])
            del buf[: spec.frame_len_bytes]
            samples, battery, imu = parse_frame_to_samples(frame, spec)
            frame_counter += 1
            if debug_queue is not None and frame_counter % 50 == 0:
                try:
                    debug_queue.put(
                        {
                            "tag": "EEG_FRAME",
                            "message": "已解析EEG帧",
                            "data": {"frame_len": int(spec.frame_len_bytes), "count": int(frame_counter)},
                        }
                    )
                except Exception:
                    pass
            if not cfg.eeg.lsl.include_trigger_channel:
                samples = [s[: cfg.eeg.mode_channels] for s in samples]
            outlet.push_samples(samples)
            if battery and frame_counter % 50 == 0:
                status_queue.put({"type": "battery", "value": battery})
            if imu and frame_counter % 50 == 0:
                status_queue.put({"type": "imu", "value": imu})

    status_queue.put({"type": "connecting", "address": address, "name": resolved_name})

    while not stop_event.is_set():
        try:
            async with BleakClient(address) as client:
                status_queue.put({"type": "connected", "address": address, "name": resolved_name})
                await client.start_notify(notify_handle, on_notify)
                notify_counter = 0
                last_notify_ts = time.time()
                no_data_reported = False
                start_retry_count = 0
                last_start_cmd_ts = 0.0
                current_mode = "idle"
                eeg_streaming_enabled = False

                async def _send_cmd(cmd: List[int], action: str) -> None:
                    payload = bytearray(cmd)
                    await client.write_gatt_char(write_handle, payload, response=False)
                    if debug_queue is not None:
                        try:
                            cmd_hex = " ".join(f"0x{int(x) & 0xFF:02X}" for x in cmd)
                            cmd_info = interpret_two_level_cmd(cmd)
                            debug_queue.put(
                                {
                                    "tag": "CMD_TX",
                                    "message": f"发送控制指令: {action}",
                                    "data": {"cmd_hex": cmd_hex, "write_handle": int(write_handle), **cmd_info},
                                }
                            )
                        except Exception:
                            pass

                try:
                    for one in cfg.bluetooth.commands.init_commands:
                        if one:
                            await _send_cmd(one, action="init")
                            await asyncio.sleep(0.05)
                except Exception as e:
                    if debug_queue is not None:
                        try:
                            debug_queue.put(
                                {
                                    "tag": "CMD_TX",
                                    "message": "发送 init 指令失败",
                                    "data": {"error": str(e), "write_handle": int(write_handle)},
                                }
                            )
                        except Exception:
                            pass

                status_queue.put({"type": "ready", "address": address, "name": resolved_name})
                while not stop_event.is_set():
                    try:
                        cmd_msg: Dict[str, Any] = command_queue.get_nowait()
                        msg_type = str(cmd_msg.get("type", ""))
                        if msg_type == "select_mode":
                            next_mode = str(cmd_msg.get("mode", "idle"))
                            current_mode = next_mode
                            status_queue.put({"type": "mode", "mode": current_mode})
                        elif msg_type == "start_mode":
                            mode = str(cmd_msg.get("mode", ""))
                            if mode == "eeg":
                                current_mode = "eeg"
                                eeg_streaming_enabled = False
                                buf.clear()
                                notify_counter = 0
                                last_notify_ts = time.time()
                                no_data_reported = False
                                start_retry_count = 0
                                try:
                                    await _send_cmd(cfg.bluetooth.commands.stop_eeg, action="pre_stop_eeg")
                                    await asyncio.sleep(0.05)
                                except Exception:
                                    pass
                                await _send_cmd(cfg.bluetooth.commands.start_eeg, action="start_eeg")
                                last_start_cmd_ts = time.time()
                                eeg_streaming_enabled = True
                                status_queue.put({"type": "mode_started", "mode": "eeg"})
                            elif mode == "impedance":
                                current_mode = "impedance"
                                eeg_streaming_enabled = False
                                buf.clear()
                                await _send_cmd(cfg.bluetooth.commands.start_impedance, action="start_impedance")
                                status_queue.put({"type": "mode_started", "mode": "impedance"})
                            elif mode == "tdcs":
                                current_mode = "tdcs"
                                eeg_streaming_enabled = False
                                buf.clear()
                                await _send_cmd(cfg.bluetooth.commands.start_tdcs, action="start_tdcs")
                                status_queue.put({"type": "mode_started", "mode": "tdcs"})
                        elif msg_type == "stop_mode":
                            mode = str(cmd_msg.get("mode", ""))
                            if mode == "eeg":
                                eeg_streaming_enabled = False
                                buf.clear()
                                await _send_cmd(cfg.bluetooth.commands.stop_eeg, action="stop_eeg")
                                status_queue.put({"type": "mode_stopped", "mode": "eeg"})
                            elif mode == "impedance":
                                eeg_streaming_enabled = False
                                buf.clear()
                                await _send_cmd(cfg.bluetooth.commands.stop_impedance, action="stop_impedance")
                                status_queue.put({"type": "mode_stopped", "mode": "impedance"})
                            elif mode == "tdcs":
                                eeg_streaming_enabled = False
                                buf.clear()
                                await _send_cmd(cfg.bluetooth.commands.stop_tdcs, action="stop_tdcs")
                                status_queue.put({"type": "mode_stopped", "mode": "tdcs"})
                            current_mode = "idle"
                            status_queue.put({"type": "mode", "mode": current_mode})
                    except queue.Empty:
                        pass
                    except Exception as e:
                        status_queue.put({"type": "error", "message": str(e)})

                    # 若持续未收到任何 notify，则输出一次“无数据”调试事件（便于定位：已发指令但设备未回传）
                    if eeg_streaming_enabled and debug_queue is not None and not no_data_reported:
                        if last_notify_ts > 0 and notify_counter == 0 and (time.time() - last_notify_ts) > 3.0:
                            no_data_reported = True
                            try:
                                debug_queue.put(
                                    {
                                        "tag": "EEG_NODATA",
                                        "message": "3秒未收到EEG通知数据（可能 notify_handle/write_handle 不匹配，或设备未开始传输）",
                                        "data": {"notify_handle": int(notify_handle), "write_handle": int(write_handle)},
                                    }
                                )
                            except Exception:
                                pass

                    if eeg_streaming_enabled and debug_queue is not None and notify_counter == 0 and start_retry_count < 2:
                        if last_start_cmd_ts > 0 and (time.time() - last_start_cmd_ts) > 1.0:
                            start_retry_count += 1
                            last_start_cmd_ts = time.time()
                            try:
                                await _send_cmd(cfg.bluetooth.commands.start_eeg, action=f"start_eeg_retry_{int(start_retry_count)}")
                            except Exception as e:
                                try:
                                    debug_queue.put(
                                        {
                                            "tag": "CMD_TX",
                                            "message": "重发 start_eeg 指令失败",
                                            "data": {"retry": int(start_retry_count), "error": str(e), "write_handle": int(write_handle)},
                                        }
                                    )
                                except Exception:
                                    pass
                    await asyncio.sleep(0.05)
                await client.stop_notify(notify_handle)
                if eeg_streaming_enabled:
                    try:
                        await _send_cmd(cfg.bluetooth.commands.stop_eeg, action="stop_eeg")
                    except Exception as e:
                        if debug_queue is not None:
                            try:
                                debug_queue.put(
                                    {
                                        "tag": "CMD_TX",
                                        "message": "发送 stop_eeg 指令失败",
                                        "data": {"error": str(e), "write_handle": int(write_handle)},
                                    }
                                )
                            except Exception:
                                pass
                break
        except Exception as e:
            status_queue.put({"type": "error", "message": str(e)})
            await asyncio.sleep(1.0)


def run_ble_acquisition_process(
    config_path: str,
    stop_event: multiprocessing.Event,
    status_queue: multiprocessing.Queue,
    command_queue: multiprocessing.Queue,
    debug_queue: Optional[multiprocessing.Queue] = None,
    connect_address: Optional[str] = None,
    connect_name: Optional[str] = None,
) -> None:
    """
    BLE 采集进程入口函数：运行 asyncio 事件循环并执行连接与通知处理逻辑。
    """
    try:
        asyncio.run(_connect_and_stream(config_path, stop_event, status_queue, command_queue, debug_queue, connect_address, connect_name))
    except KeyboardInterrupt:
        pass
    finally:
        time.sleep(0.1)
