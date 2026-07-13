#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 两级控制指令元数据（一级/二级）与解释函数，供采集进程与上层控制面板复用
作者: Spoon
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


L1_ADC_CONTROL = 0x02
L1_IMPEDANCE_CONTROL = 0x03
L1_IMU_CONTROL = 0x04
L1_BATTERY_CONTROL = 0x05
L1_TRIGGER_SOURCE = 0x06
L1_TRIGGER_CONTROL = 0xFF
L1_TDCS_CONTROL = 0x07


@dataclass(frozen=True)
class ControlCommandMeta:
    """
    控制指令元信息。

    Attributes:
        name: 指令英文名（用于开发者定位）
        desc: 指令中文说明（用于 UI 展示）
        help: 面向使用者的操作说明（用于 UI 展示）
        payload_spec: 附加数据格式约定（供 UI 渲染输入框与编码）。
            - "none": 无附加数据
            - "u16be": 2 字节无符号整数（高字节在前）
            - "hex": 用户自定义十六进制字节串（例如 "01 02 0A"）
    """

    name: str
    desc: str
    help: str = ""
    payload_spec: str = "none"


L1_COMMANDS: Dict[int, ControlCommandMeta] = {
    0x00: ControlCommandMeta(name="Get Information", desc="获取信息"),
    0x01: ControlCommandMeta(name="Get Configuration", desc="获取配置"),
    0x02: ControlCommandMeta(name="ADC Control", desc="脑电数据传输控制"),
    0x03: ControlCommandMeta(name="Impedance Control", desc="阻抗检测控制"),
    0x04: ControlCommandMeta(name="IMU Control", desc="IMU 数据控制"),
    0x05: ControlCommandMeta(name="Battery Control", desc="电量监测控制"),
    0x06: ControlCommandMeta(name="Trigger Source", desc="触发源选择"),
    0xFF: ControlCommandMeta(name="Trigger Control", desc="触发控制（蓝牙程控）"),
    0x07: ControlCommandMeta(name="tDCS Control", desc="tDCS 控制"),
}


L2_COMMANDS: Dict[int, Dict[int, ControlCommandMeta]] = {
    0x02: {
        0x00: ControlCommandMeta(name="Get Information", desc="获取信息"),
        0x01: ControlCommandMeta(name="Start Transfer", desc="开始传输脑电数据"),
        0x02: ControlCommandMeta(name="Stop Transfer", desc="停止传输脑电数据"),
        0x03: ControlCommandMeta(name="Get Configuration Specific", desc="读取指定配置", payload_spec="hex"),
        0x04: ControlCommandMeta(name="Get Configuration All", desc="读取全部配置"),
        0x05: ControlCommandMeta(name="Set Configuration Specific", desc="写入指定配置", payload_spec="hex"),
        0x06: ControlCommandMeta(name="Set Configuration All", desc="写入全部配置", payload_spec="hex"),
    },
    0x03: {
        0x00: ControlCommandMeta(name="Get Information", desc="获取信息"),
        0x01: ControlCommandMeta(name="Start Impedance", desc="开始传输阻抗数据"),
        0x02: ControlCommandMeta(name="Stop Impedance", desc="停止传输阻抗数据"),
        0x03: ControlCommandMeta(name="Get Configuration Specific", desc="读取指定配置", payload_spec="hex"),
        0x04: ControlCommandMeta(name="Set Configuration Specific", desc="写入指定配置", payload_spec="hex"),
    },
    0x04: {
        0x00: ControlCommandMeta(name="Get Information", desc="获取信息"),
        0x01: ControlCommandMeta(name="Start IMU", desc="开始传输 IMU 数据"),
        0x02: ControlCommandMeta(name="Stop IMU", desc="停止传输 IMU 数据"),
        0x03: ControlCommandMeta(name="Get Configuration Specific", desc="读取指定配置", payload_spec="hex"),
        0x04: ControlCommandMeta(name="Set Configuration Specific", desc="写入指定配置", payload_spec="hex"),
    },
    0x05: {
        0x00: ControlCommandMeta(name="Get Information", desc="获取信息"),
        0x01: ControlCommandMeta(name="Start Battery Monitor", desc="开始电量监测"),
        0x02: ControlCommandMeta(name="Stop Battery Monitor", desc="停止电量监测"),
        0x03: ControlCommandMeta(name="Get Configuration Specific", desc="读取指定配置", payload_spec="hex"),
        0x04: ControlCommandMeta(name="Set Configuration Specific", desc="写入指定配置", payload_spec="hex"),
    },
    0x06: {
        0x01: ControlCommandMeta(name="BLE Trigger", desc="蓝牙程控触发"),
        0x02: ControlCommandMeta(name="External TTL UART Trigger", desc="外部 TTL（UART 控制）触发"),
        0x03: ControlCommandMeta(name="External TTL Level Trigger", desc="外部 TTL（电平控制）触发"),
    },
    0xFF: {
        0x01: ControlCommandMeta(name="Set Trigger", desc="设置 Trigger"),
        0x02: ControlCommandMeta(name="Clear Trigger", desc="清除 Trigger"),
    },
    0x07: {
        0x01: ControlCommandMeta(name="Start tDCS", desc="启动 tDCS 工作", help="启动电刺激输出。通常需要先“使能高压电路”并预热后再启动。"),
        0x02: ControlCommandMeta(name="Stop tDCS", desc="停止 tDCS 工作", help="停止电刺激输出。停止后可进一步“禁止高压电路”以降低功耗。"),
        0x15: ControlCommandMeta(name="Enable HV", desc="使能高压电路工作", help="开启高压电路并进入预热状态；建议预热约 2s 后再启动 tDCS。"),
        0x16: ControlCommandMeta(name="Disable HV", desc="禁止高压电路工作", help="关闭高压电路，节省功耗；通常在停止 tDCS 后执行。"),
        0x10: ControlCommandMeta(name="Set Current", desc="设置 tDCS 输出电流值", help="设置目标输出电流（单位 mA，对应 2 字节数字量）。建议先设置电流与时间参数，再启动 tDCS。", payload_spec="u16be"),
        0x20: ControlCommandMeta(name="Set Ramp Up", desc="设置输出电流缓升时间", help="设置电流从 0 上升到目标值的时间（单位 100ms，对应 2 字节数字量）。", payload_spec="u16be"),
        0x21: ControlCommandMeta(name="Set Hold", desc="设置输出电流稳定工作时间", help="设置电流在目标值保持的稳定时间（单位 1s，对应 2 字节数字量）。", payload_spec="u16be"),
        0x22: ControlCommandMeta(name="Set Ramp Down", desc="设置输出电流缓降时间", help="设置电流从目标值下降到 0 的时间（单位 100ms，对应 2 字节数字量）。", payload_spec="u16be"),
        0x23: ControlCommandMeta(name="Set Alarm Threshold", desc="设置输出电流报警阈值", help="设置过流报警阈值；超过阈值模块会自动断电（单位按文档换算为 2 字节数字量）。", payload_spec="u16be"),
    },
}


def interpret_two_level_cmd(cmd: List[int]) -> Dict[str, str]:
    """
    解析两级控制指令（一级指令 + 二级指令），用于日志展示与 UI 显示。

    Args:
        cmd: 指令字节列表，通常至少包含 2 个字节：[L1, L2, ...]

    Returns:
        Dict[str, str]: 结构化解释字段（适合直接塞入调试事件 data）。
    """

    l1: Optional[int] = (int(cmd[0]) & 0xFF) if len(cmd) >= 1 else None
    l2: Optional[int] = (int(cmd[1]) & 0xFF) if len(cmd) >= 2 else None

    out: Dict[str, str] = {}
    if l1 is None:
        return out

    out["cmd_l1_hex"] = f"0x{l1:02X}"
    m1 = L1_COMMANDS.get(l1)
    if m1 is not None:
        out["cmd_l1_name"] = m1.name
        out["cmd_l1_desc"] = m1.desc
    else:
        out["cmd_l1_name"] = "Unknown"
        out["cmd_l1_desc"] = "未知一级指令"

    if l2 is None:
        return out

    out["cmd_l2_hex"] = f"0x{l2:02X}"
    m2 = L2_COMMANDS.get(l1, {}).get(l2)
    if m2 is not None:
        out["cmd_l2_name"] = m2.name
        out["cmd_l2_desc"] = m2.desc
    else:
        out["cmd_l2_name"] = "Unknown"
        out["cmd_l2_desc"] = "未知二级指令"

    return out
