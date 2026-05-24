#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: BLE 模块命名规则解析（将设备广播名解析为采集通道数与刺激通道数等能力信息）

修改日志:
- 2026-05-24: 1.0.0 创建文件

作者: Spoon
版本: 1.0.0
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class BleModuleNameInfo:
    """
    BLE 模块命名解析结果。

    Attributes:
        raw_name: 原始广播名（未清洗）。
        model_name: 命名规则匹配到的“型号段”（例如 MSM008S01）。
        eeg_channels: 采集通道数（例如 8、16、128）。
        stim_channels: 电刺激通道数（例如 0、1）。
    """

    raw_name: str
    model_name: str
    eeg_channels: int
    stim_channels: int


def parse_ble_module_name(name: str, pattern: str) -> Optional[BleModuleNameInfo]:
    """
    解析 BLE 模块广播名（基于可配置正则），提取采集通道数与刺激通道数。

    说明：
    - 正则需包含两个命名分组：eeg_channels、stim_channels
    - 若广播名包含额外后缀（例如括号/空格），建议在正则中自行处理，或使用非锚定正则并配合 search 匹配

    Args:
        name: BLE 广播名（字符串）。
        pattern: 正则表达式（必须包含命名分组 eeg_channels 与 stim_channels）。

    Returns:
        Optional[BleModuleNameInfo]: 解析成功返回信息；解析失败返回 None。
    """

    raw = str(name or "")
    s = raw.strip()
    if not s:
        return None
    p = str(pattern or "").strip()
    if not p:
        return None
    try:
        m = re.search(p, s)
    except re.error:
        return None
    if not m:
        return None
    gd = m.groupdict() or {}
    if "eeg_channels" not in gd or "stim_channels" not in gd:
        return None
    try:
        eeg_channels = int(str(gd.get("eeg_channels", "")).strip())
        stim_channels = int(str(gd.get("stim_channels", "")).strip())
    except Exception:
        return None
    if eeg_channels <= 0 or stim_channels < 0:
        return None
    model_name = str(m.group(0) or "").strip() or s
    return BleModuleNameInfo(
        raw_name=raw,
        model_name=model_name,
        eeg_channels=eeg_channels,
        stim_channels=stim_channels,
    )

