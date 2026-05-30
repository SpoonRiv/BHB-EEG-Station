#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: BLE 采集进程实现（连接设备、接收通知数据、按协议组帧解析并推送到 LSL）

修改日志:
- 2026-04-30: 1.0.0 创建文件
- 2026-05-02: 1.1.0 支持连接常驻与命令队列模式切换
- 2026-05-02: 1.1.1 调整调试输出：仅在EEG启动后提示无数据，减少默认噪声
- 2026-05-03: 1.1.2 移除 EEG_FRAME 调试输出，减少调试面板噪声
- 2026-05-03: 1.1.3 修复电量状态上报条件，避免电量为 0 时不显示
- 2026-05-03: 1.1.4 提前上报首帧电量，避免页面长期显示“--”
- 2026-05-03: 1.1.5 EEG 停止后不再输出 EEG_RX 调试事件，避免“停采集仍在滚”
- 2026-05-03: 1.1.6 停止模式指令失败不再上报“连接失败”，断联时改为上报“连接已断开”
- 2026-05-03: 1.1.7 stop_mode 无论指令是否成功都上报 mode_stopped，用于 UI 解除运行态锁定
- 2026-05-04: 1.1.8 增加阻抗帧解析与阻抗 LSL 推流（供 WebSocket 可视化）
- 2026-05-04: 1.1.9 统一三模式命名并显式区分 8/16 通道配置字段（n_channels/protocol.ch8/ch16）
- 2026-05-04: 1.1.10 限制 tDCS 仅在 8 通道模式可用（16 通道规划不包含电刺激）
- 2026-05-04: 1.1.11 EEG 启动不再发送 pre_stop_eeg（0x02 0x02）
- 2026-05-09: 1.1.12 增加 tDCS 通知帧解析与调试事件（TDCS_RX/TDCS_FRAME/TDCS_NODATA）
- 2026-05-12: 1.1.13 支持下发任意两级控制指令（控制面板），并抽取指令元数据模块复用
- 2026-05-21: 1.1.14 延迟创建 LSL Outlet（pylsl），降低“仅连接蓝牙”阶段启动耗时
- 2026-05-21: 1.1.15 LSL 初始化失败时返回结构化错误，避免采集进程崩溃
- 2026-05-24: 1.1.16 按模块命名规则识别电刺激能力（无刺激模块时禁用 tDCS 与 tDCS 阻抗通道）
- 2026-05-24: 1.1.17 广播名仅为 MSM 时按“无电刺激模块”处理（禁用 tDCS 与 tDCS 阻抗通道）
- 2026-05-30: 1.1.18 连接异常上报包含设备名，避免前端回退展示为配置名

作者: Spoon
版本: 1.1.18
"""

import asyncio
import multiprocessing
import queue
import time
from typing import Any, Dict, List, Optional

from bleak import BleakClient, BleakScanner

from configs.config_loader import load_config
from core.ble.commands import interpret_two_level_cmd
from core.ble.device_finder import find_device_by_spec
from core.ble.frame_parser import FrameSpec, parse_frame_to_samples
from core.ble.impedance_parser import ImpedanceFrameSpec, build_impedance_vector, parse_impedance_frame
from core.ble.lsl_outlet import LslOutletConfig, LslOutletWriter
from core.ble.module_naming import BleModuleNameInfo, parse_ble_module_name


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

    eeg_n_channels = int(cfg.eeg.n_channels)
    eeg_proto = cfg.eeg.protocol.ch8 if eeg_n_channels == 8 else cfg.eeg.protocol.ch16
    if eeg_proto is None:
        raise ValueError("eeg.n_channels=16 时必须配置 eeg.protocol.ch16.frame")

    channel_count = eeg_n_channels + (1 if cfg.eeg.lsl.include_trigger_channel else 0)
    spec: Optional[FrameSpec] = None
    outlet: Optional[LslOutletWriter] = None

    imp_n_channels = int(cfg.impedance.n_channels)
    imp_tail_channels = 0
    imp_spec: Optional[ImpedanceFrameSpec] = None
    imp_outlet: Optional[LslOutletWriter] = None

    address: Optional[str] = (connect_address or "").strip() or cfg.bluetooth.mac_address.strip() or None
    resolved_name = (connect_name or "").strip() or cfg.bluetooth.target_device
    if address and not (connect_name or "").strip():
        try:
            timeout_sec = float(cfg.bluetooth.scan.retry_interval_sec)
            if timeout_sec <= 0:
                timeout_sec = 1.0
            devices = await BleakScanner.discover(timeout=timeout_sec)
            for dev in devices:
                if str(getattr(dev, "address", "") or "") == str(address):
                    n = str(getattr(dev, "name", "") or "").strip()
                    if n:
                        resolved_name = n
                        break
        except Exception:
            pass

    if not address:
        target = await find_device_by_spec(
            target_name=str(cfg.bluetooth.target_device or ""),
            max_retries=int(cfg.bluetooth.scan.max_retries),
            retry_interval_sec=float(cfg.bluetooth.scan.retry_interval_sec),
            module_name_regex=str(cfg.bluetooth.module_name_regex or ""),
            desired_eeg_channels=int(cfg.eeg.n_channels),
            require_stim_module=bool(getattr(cfg, "tdcs", None) and cfg.tdcs.enabled),
        )
        if not target and bool(getattr(cfg, "tdcs", None) and cfg.tdcs.enabled):
            target = await find_device_by_spec(
                target_name=str(cfg.bluetooth.target_device or ""),
                max_retries=int(cfg.bluetooth.scan.max_retries),
                retry_interval_sec=float(cfg.bluetooth.scan.retry_interval_sec),
                module_name_regex=str(cfg.bluetooth.module_name_regex or ""),
                desired_eeg_channels=int(cfg.eeg.n_channels),
                require_stim_module=False,
            )
        if not target:
            status_queue.put({"type": "error", "message": "未扫描到目标 BLE 设备", "name": cfg.bluetooth.target_device})
            return
        address = target.address
        resolved_name = target.name

    module_info: Optional[BleModuleNameInfo] = parse_ble_module_name(resolved_name, str(cfg.bluetooth.module_name_regex or ""))
    if module_info is not None and int(module_info.eeg_channels) != int(cfg.eeg.n_channels):
        status_queue.put(
            {
                "type": "error",
                "message": f"设备型号解析为 {int(module_info.eeg_channels)} 通道，但当前配置为 {int(cfg.eeg.n_channels)} 通道，请检查 config.yaml 的 eeg.n_channels",
                "name": resolved_name,
                "module": {"eeg_channels": int(module_info.eeg_channels), "stim_channels": int(module_info.stim_channels)},
            }
        )
        return

    device_has_stim = module_info is not None and int(module_info.stim_channels) > 0
    imp_include_tdcs = bool(cfg.impedance.frame.include_tdcs_if_ch8) and imp_n_channels == 8 and bool(device_has_stim)
    imp_tail_channels = (1 if bool(cfg.impedance.frame.include_bias) else 0) + (1 if imp_include_tdcs else 0)

    notify_handle = cfg.bluetooth.gatt.notify_char_handle
    write_handle = cfg.bluetooth.gatt.write_char_handle

    def ensure_eeg_lsl_ready() -> None:
        nonlocal spec, outlet
        if spec is None:
            spec = FrameSpec(
                channels=eeg_n_channels,
                header_len_bytes=eeg_proto.frame.header_len_bytes,
                bytes_per_sample_per_channel=eeg_proto.frame.bytes_per_sample_per_channel,
                samples_per_frame=eeg_proto.frame.samples_per_frame,
                trigger_len_bytes=eeg_proto.frame.trigger_len_bytes,
                imu_len_bytes=eeg_proto.frame.imu_len_bytes,
                battery_len_bytes=eeg_proto.frame.battery_len_bytes,
                tail_len_bytes=eeg_proto.frame.tail_len_bytes,
            )
        if outlet is None:
            outlet = LslOutletWriter(
                LslOutletConfig(
                    stream_name=cfg.eeg.lsl.stream_name,
                    stream_type=cfg.eeg.lsl.stream_type,
                    channel_count=channel_count,
                    sampling_rate_hz=cfg.eeg.sampling_rate_hz,
                    source_id=f"bhb-eeg-{cfg.bluetooth.target_device}",
                )
            )

    def ensure_impedance_lsl_ready() -> None:
        nonlocal imp_spec, imp_outlet
        if imp_spec is None:
            imp_spec = ImpedanceFrameSpec(
                header=(int(cfg.impedance.frame.header[0]) & 0xFF, int(cfg.impedance.frame.header[1]) & 0xFF),
                n_channels=imp_n_channels,
                frame_len_bytes=int(cfg.impedance.frame.frame_len_bytes_ch8 if imp_n_channels == 8 else cfg.impedance.frame.frame_len_bytes_ch16),
                include_bias=bool(cfg.impedance.frame.include_bias),
                include_tdcs=imp_include_tdcs,
                gain_scale=float(cfg.impedance.frame.gain_scale),
            )
        if imp_outlet is None:
            imp_outlet = LslOutletWriter(
                LslOutletConfig(
                    stream_name=cfg.impedance.lsl.stream_name,
                    stream_type=cfg.impedance.lsl.stream_type,
                    channel_count=imp_n_channels + imp_tail_channels,
                    sampling_rate_hz=int(cfg.impedance.lsl.sampling_rate_hz),
                    source_id=f"bhb-imp-{cfg.bluetooth.target_device}",
                )
            )

    buf = bytearray()
    frame_counter = 0
    notify_counter = 0
    last_notify_ts: float = 0.0
    no_data_reported = False
    start_retry_count = 0
    last_start_cmd_ts: float = 0.0
    current_mode: str = "idle"
    eeg_streaming_enabled = False

    imp_buf = bytearray()
    imp_frame_counter = 0
    imp_notify_counter = 0
    imp_last_notify_ts: float = 0.0
    imp_no_data_reported = False
    impedance_streaming_enabled = False

    tdcs_buf = bytearray()
    tdcs_notify_counter = 0
    tdcs_last_notify_ts: float = 0.0
    tdcs_no_data_reported = False
    tdcs_streaming_enabled = False

    def on_notify(_: int, data: bytearray) -> None:
        nonlocal frame_counter, notify_counter, last_notify_ts, no_data_reported, eeg_streaming_enabled
        nonlocal imp_frame_counter, imp_notify_counter, imp_last_notify_ts, imp_no_data_reported, impedance_streaming_enabled
        nonlocal tdcs_buf, tdcs_notify_counter, tdcs_last_notify_ts, tdcs_no_data_reported, tdcs_streaming_enabled

        if impedance_streaming_enabled:
            if imp_spec is None or imp_outlet is None:
                return
            imp_notify_counter += 1
            imp_last_notify_ts = time.time()
            imp_no_data_reported = False
            if debug_queue is not None:
                try:
                    if imp_notify_counter % 5 == 0:
                        debug_queue.put(
                            {
                                "tag": "IMP_RX",
                                "message": "收到阻抗通知数据",
                                "data": {"len": int(len(data))},
                            }
                        )
                except Exception:
                    pass

            expected = int(imp_spec.frame_len_bytes)
            hdr0, hdr1 = int(imp_spec.header[0]) & 0xFF, int(imp_spec.header[1]) & 0xFF
            if len(data) == expected and len(data) >= 2 and data[0] == hdr0 and data[1] == hdr1:
                imp_buf.clear()
                frames = [bytes(data)]
            else:
                imp_buf.extend(data)
                header_bytes = bytes([hdr0, hdr1])
                frames = []
                for _ in range(20):
                    pos = imp_buf.find(header_bytes)
                    if pos < 0:
                        if len(imp_buf) > 1:
                            del imp_buf[:-1]
                        break
                    if pos > 0:
                        del imp_buf[:pos]
                    if len(imp_buf) < expected:
                        break
                    frames.append(bytes(imp_buf[:expected]))
                    del imp_buf[:expected]

            for fr in frames:
                try:
                    ch_ohm, gain_coeff, bias_ohm, tdcs_ohm = parse_impedance_frame(fr, imp_spec)
                    vec = build_impedance_vector(ch_ohm, bias_ohm, tdcs_ohm)
                    imp_outlet.push_samples([vec])
                    imp_frame_counter += 1
                    if debug_queue is not None and imp_frame_counter % 10 == 0:
                        try:
                            vmin = float(min(ch_ohm)) if ch_ohm else 0.0
                            vmax = float(max(ch_ohm)) if ch_ohm else 0.0
                            debug_queue.put(
                                {
                                    "tag": "IMP_FRAME",
                                    "message": "阻抗帧解析并推送",
                                    "data": {
                                        "channels": int(len(ch_ohm)),
                                        "min_ohm": vmin,
                                        "max_ohm": vmax,
                                        "bias_ohm": float(bias_ohm) if bias_ohm is not None else None,
                                        "tdcs_ohm": float(tdcs_ohm) if tdcs_ohm is not None else None,
                                        "gain_coeff": float(gain_coeff),
                                    },
                                }
                            )
                        except Exception:
                            pass
                except Exception as e:
                    if debug_queue is not None:
                        try:
                            debug_queue.put({"tag": "IMP_PARSE", "message": "阻抗帧解析失败", "data": {"error": str(e), "len": int(len(fr))}})
                        except Exception:
                            pass
            return

        if tdcs_streaming_enabled:
            tdcs_notify_counter += 1
            tdcs_last_notify_ts = time.time()
            tdcs_no_data_reported = False
            
            if debug_queue is not None:
                try:
                    if tdcs_notify_counter % 5 == 0:
                        debug_queue.put(
                            {
                                "tag": "TDCS_RX",
                                "message": "收到tDCS通知数据",
                                "data": {"len": int(len(data))},
                            }
                        )
                except Exception:
                    pass
                    
            expected = 10
            hdr0, hdr1 = 0xEB, 0x90
            
            if len(data) == expected and len(data) >= 2 and data[0] == hdr0 and data[1] == hdr1:
                tdcs_buf.clear()
                frames = [bytes(data)]
            else:
                tdcs_buf.extend(data)
                header_bytes = bytes([hdr0, hdr1])
                frames = []
                for _ in range(20):
                    pos = tdcs_buf.find(header_bytes)
                    if pos < 0:
                        if len(tdcs_buf) > 1:
                            del tdcs_buf[:-1]
                        break
                    if pos > 0:
                        del tdcs_buf[:pos]
                    if len(tdcs_buf) < expected:
                        break
                    frames.append(bytes(tdcs_buf[:expected]))
                    del tdcs_buf[:expected]
                    
            for fr in frames:
                try:
                    out_curr_raw = int.from_bytes(fr[2:5], byteorder="big", signed=False)
                    out_curr_uA = out_curr_raw * 0.3125 / 40.0 - 444.0
                    
                    hv_raw = int.from_bytes(fr[5:8], byteorder="big", signed=False)
                    hv_uV = hv_raw * 195.3125
                    
                    status_byte = int(fr[8])
                    is_working = bool(status_byte & 0x04)
                    open_circuit = bool(status_byte & 0x02)
                    over_current = bool(status_byte & 0x01)
                    
                    battery = int(fr[9])
                    if battery >= 0 and battery <= 100:
                        status_queue.put({"type": "battery", "value": battery})
                        
                    if debug_queue is not None:
                        try:
                            debug_queue.put(
                                {
                                    "tag": "TDCS_FRAME",
                                    "message": "tDCS 监测数据解析",
                                    "data": {
                                        "out_curr_raw": out_curr_raw,
                                        "out_curr_uA": out_curr_uA,
                                        "hv_raw": hv_raw,
                                        "hv_uV": hv_uV,
                                        "is_working": is_working,
                                        "open_circuit": open_circuit,
                                        "over_current": over_current,
                                        "battery": battery,
                                    },
                                }
                            )
                        except Exception:
                            pass
                except Exception as e:
                    if debug_queue is not None:
                        try:
                            debug_queue.put({"tag": "TDCS_PARSE", "message": "tDCS 帧解析失败", "data": {"error": str(e), "len": int(len(fr))}})
                        except Exception:
                            pass
            return

        notify_counter += 1
        last_notify_ts = time.time()
        no_data_reported = False
        if not eeg_streaming_enabled:
            return
        if spec is None or outlet is None:
            return
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
            if not cfg.eeg.lsl.include_trigger_channel:
                samples = [s[:eeg_n_channels] for s in samples]
            outlet.push_samples(samples)
            if spec.battery_len_bytes > 0 and (frame_counter == 1 or frame_counter % 50 == 0):
                status_queue.put({"type": "battery", "value": int(battery)})
            if imu and frame_counter % 50 == 0:
                status_queue.put({"type": "imu", "value": imu})

    status_payload: Dict[str, Any] = {"type": "connecting", "address": address, "name": resolved_name}
    if module_info is not None:
        status_payload["module"] = {"eeg_channels": int(module_info.eeg_channels), "stim_channels": int(module_info.stim_channels)}
    status_queue.put(status_payload)

    while not stop_event.is_set():
        try:
            async with BleakClient(address) as client:
                status_payload = {"type": "connected", "address": address, "name": resolved_name}
                if module_info is not None:
                    status_payload["module"] = {"eeg_channels": int(module_info.eeg_channels), "stim_channels": int(module_info.stim_channels)}
                status_queue.put(status_payload)
                await client.start_notify(notify_handle, on_notify)
                notify_counter = 0
                last_notify_ts = time.time()
                no_data_reported = False
                start_retry_count = 0
                last_start_cmd_ts = 0.0
                current_mode = "idle"
                eeg_streaming_enabled = False
                impedance_streaming_enabled = False
                imp_buf.clear()
                imp_frame_counter = 0
                imp_notify_counter = 0
                imp_last_notify_ts = 0.0
                imp_no_data_reported = False
                tdcs_streaming_enabled = False
                tdcs_buf.clear()
                tdcs_notify_counter = 0
                tdcs_last_notify_ts = 0.0
                tdcs_no_data_reported = False

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

                status_payload = {"type": "ready", "address": address, "name": resolved_name}
                if module_info is not None:
                    status_payload["module"] = {"eeg_channels": int(module_info.eeg_channels), "stim_channels": int(module_info.stim_channels)}
                status_queue.put(status_payload)
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
                                impedance_streaming_enabled = False
                                imp_buf.clear()
                                buf.clear()
                                notify_counter = 0
                                last_notify_ts = time.time()
                                no_data_reported = False
                                start_retry_count = 0
                                try:
                                    ensure_eeg_lsl_ready()
                                except Exception as e:
                                    status_queue.put({"type": "error", "message": f"创建 EEG LSL Outlet 失败：{str(e)}"})
                                    continue
                                await _send_cmd(cfg.bluetooth.commands.start_eeg, action="start_eeg")
                                last_start_cmd_ts = time.time()
                                eeg_streaming_enabled = True
                                status_queue.put({"type": "mode_started", "mode": "eeg"})
                            elif mode == "impedance":
                                current_mode = "impedance"
                                eeg_streaming_enabled = False
                                impedance_streaming_enabled = False
                                buf.clear()
                                imp_buf.clear()
                                imp_notify_counter = 0
                                imp_last_notify_ts = time.time()
                                imp_no_data_reported = False
                                try:
                                    ensure_impedance_lsl_ready()
                                except Exception as e:
                                    status_queue.put({"type": "error", "message": f"创建阻抗 LSL Outlet 失败：{str(e)}"})
                                    continue
                                await _send_cmd(cfg.bluetooth.commands.start_impedance, action="start_impedance")
                                impedance_streaming_enabled = True
                                status_queue.put({"type": "mode_started", "mode": "impedance"})
                            elif mode == "tdcs":
                                if int(cfg.eeg.n_channels) != 8:
                                    status_queue.put({"type": "error", "message": f"{int(cfg.eeg.n_channels)}通道模式不支持电刺激（tDCS）"})
                                    continue
                                if module_info is None or int(module_info.stim_channels) <= 0:
                                    status_queue.put({"type": "error", "message": "当前设备不带电刺激模块，电刺激（tDCS）已禁用"})
                                    continue
                                current_mode = "tdcs"
                                eeg_streaming_enabled = False
                                impedance_streaming_enabled = False
                                tdcs_streaming_enabled = False
                                imp_buf.clear()
                                buf.clear()
                                tdcs_buf.clear()
                                tdcs_notify_counter = 0
                                tdcs_last_notify_ts = time.time()
                                tdcs_no_data_reported = False
                                await _send_cmd(cfg.bluetooth.commands.start_tdcs, action="start_tdcs")
                                tdcs_streaming_enabled = True
                                status_queue.put({"type": "mode_started", "mode": "tdcs"})
                        elif msg_type == "send_cmd":
                            raw = cmd_msg.get("cmd", [])
                            cmd: List[int] = []
                            if isinstance(raw, list):
                                for x in raw:
                                    try:
                                        v = int(x) & 0xFF
                                    except Exception:
                                        continue
                                    cmd.append(v)
                            if len(cmd) < 2:
                                if debug_queue is not None:
                                    try:
                                        debug_queue.put(
                                            {
                                                "tag": "CMD_TX",
                                                "message": "忽略非法控制指令：长度不足 2 字节",
                                                "data": {"raw": raw},
                                            }
                                        )
                                    except Exception:
                                        pass
                                continue
                            await _send_cmd(cmd, action="panel_send_cmd")
                        elif msg_type == "stop_mode":
                            mode = str(cmd_msg.get("mode", ""))
                            if mode == "eeg":
                                eeg_streaming_enabled = False
                                buf.clear()
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
                                    if not bool(getattr(client, "is_connected", True)):
                                        status_queue.put({"type": "disconnected", "message": "蓝牙连接已断开", "address": address, "name": resolved_name})
                                status_queue.put({"type": "mode_stopped", "mode": "eeg"})
                            elif mode == "impedance":
                                eeg_streaming_enabled = False
                                buf.clear()
                                impedance_streaming_enabled = False
                                imp_buf.clear()
                                try:
                                    await _send_cmd(cfg.bluetooth.commands.stop_impedance, action="stop_impedance")
                                except Exception as e:
                                    if debug_queue is not None:
                                        try:
                                            debug_queue.put(
                                                {
                                                    "tag": "CMD_TX",
                                                    "message": "发送 stop_impedance 指令失败",
                                                    "data": {"error": str(e), "write_handle": int(write_handle)},
                                                }
                                            )
                                        except Exception:
                                            pass
                                    if not bool(getattr(client, "is_connected", True)):
                                        status_queue.put({"type": "disconnected", "message": "蓝牙连接已断开", "address": address, "name": resolved_name})
                                status_queue.put({"type": "mode_stopped", "mode": "impedance"})
                            elif mode == "tdcs":
                                eeg_streaming_enabled = False
                                buf.clear()
                                impedance_streaming_enabled = False
                                imp_buf.clear()
                                tdcs_streaming_enabled = False
                                tdcs_buf.clear()
                                try:
                                    await _send_cmd(cfg.bluetooth.commands.stop_tdcs, action="stop_tdcs")
                                except Exception as e:
                                    if debug_queue is not None:
                                        try:
                                            debug_queue.put(
                                                {
                                                    "tag": "CMD_TX",
                                                    "message": "发送 stop_tdcs 指令失败",
                                                    "data": {"error": str(e), "write_handle": int(write_handle)},
                                                }
                                            )
                                        except Exception:
                                            pass
                                    if not bool(getattr(client, "is_connected", True)):
                                        status_queue.put({"type": "disconnected", "message": "蓝牙连接已断开", "address": address, "name": resolved_name})
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

                    if impedance_streaming_enabled and debug_queue is not None and not imp_no_data_reported:
                        if imp_last_notify_ts > 0 and imp_notify_counter == 0 and (time.time() - imp_last_notify_ts) > 3.0:
                            imp_no_data_reported = True
                            try:
                                debug_queue.put(
                                    {
                                        "tag": "IMP_NODATA",
                                        "message": "3秒未收到阻抗通知数据（可能 notify_handle/write_handle 不匹配，或设备未开始传输）",
                                        "data": {"notify_handle": int(notify_handle), "write_handle": int(write_handle)},
                                    }
                                )
                            except Exception:
                                pass

                    if tdcs_streaming_enabled and debug_queue is not None and not tdcs_no_data_reported:
                        if tdcs_last_notify_ts > 0 and tdcs_notify_counter == 0 and (time.time() - tdcs_last_notify_ts) > 3.0:
                            tdcs_no_data_reported = True
                            try:
                                debug_queue.put(
                                    {
                                        "tag": "TDCS_NODATA",
                                        "message": "3秒未收到tDCS通知数据（可能 notify_handle/write_handle 不匹配，或设备未开始传输）",
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
            status_queue.put({"type": "error", "message": str(e), "address": address, "name": resolved_name})
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
