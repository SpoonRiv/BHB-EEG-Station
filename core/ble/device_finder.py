#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: BLE 设备扫描与发现（按名称匹配目标设备并返回地址信息）

修改日志:
- 2026-04-30: 1.0.0 创建文件
- 2026-05-24: 1.1.0 支持按模块命名规则优先匹配期望通道数与电刺激能力（MSM***S**）

作者: Spoon
版本: 1.1.0
"""

import asyncio
from dataclasses import dataclass
from typing import Optional

from bleak import BleakScanner

from core.ble.module_naming import parse_ble_module_name


@dataclass(frozen=True)
class BleTarget:
    """
    BLE 目标设备信息。
    """
    name: str
    address: str


async def find_device_by_spec(
    *,
    target_name: str,
    max_retries: int,
    retry_interval_sec: float,
    module_name_regex: str,
    desired_eeg_channels: Optional[int],
    require_stim_module: bool,
) -> Optional[BleTarget]:
    """
    扫描 BLE 设备并按规则匹配目标设备。

    匹配优先级：
    1) 命名规则匹配成功（module_name_regex）且满足 desired_eeg_channels/require_stim_module 的设备；
    2) 回退到“名称包含 target_name”的旧逻辑。

    Args:
        target_name: 旧版目标名称（用于回退匹配）。
        max_retries: 最大重试次数。
        retry_interval_sec: 重试间隔（秒）。
        module_name_regex: 模块命名规则正则（需包含 eeg_channels、stim_channels）。
        desired_eeg_channels: 期望采集通道数；为 None 时不做限制。
        require_stim_module: 是否要求存在电刺激模块（stim_channels > 0）。

    Returns:
        Optional[BleTarget]: 匹配到的设备信息；未找到返回 None。
    """

    fallback: Optional[BleTarget] = None
    for _ in range(max_retries):
        devices = await BleakScanner.discover()
        best: Optional[BleTarget] = None
        best_rssi: int = -10_000
        for dev in devices:
            name = str(getattr(dev, "name", "") or "")
            address = str(getattr(dev, "address", "") or "")
            if not address:
                continue
            info = parse_ble_module_name(name, module_name_regex)
            if info is not None:
                if desired_eeg_channels is not None and int(info.eeg_channels) != int(desired_eeg_channels):
                    continue
                if require_stim_module and int(info.stim_channels) <= 0:
                    continue
                rssi_val = getattr(dev, "rssi", None)
                rssi = int(rssi_val) if isinstance(rssi_val, (int, float)) else -10_000
                if best is None or rssi > best_rssi:
                    best = BleTarget(name=name, address=address)
                    best_rssi = rssi
                continue
            if fallback is None and name and str(target_name or "") in name:
                fallback = BleTarget(name=name, address=address)
        if best is not None:
            return best
        if fallback is not None:
            return fallback
        await asyncio.sleep(retry_interval_sec)
    return None


async def find_device_by_name(
    target_name: str,
    max_retries: int,
    retry_interval_sec: float,
) -> Optional[BleTarget]:
    """
    按设备名扫描 BLE 设备，找到第一个名称包含 target_name 的设备。
    """
    for _ in range(max_retries):
        devices = await BleakScanner.discover()
        for dev in devices:
            if dev.name and target_name in str(dev.name):
                return BleTarget(name=str(dev.name), address=str(dev.address))
        await asyncio.sleep(retry_interval_sec)
    return None
