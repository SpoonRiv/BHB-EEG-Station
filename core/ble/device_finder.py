#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: BLE 设备扫描与发现（按名称匹配目标设备并返回地址信息）

修改日志:
- 2026-04-30: 1.0.0 创建文件

作者: Spoon
版本: 1.0.0
"""

import asyncio
from dataclasses import dataclass
from typing import Optional

from bleak import BleakScanner


@dataclass(frozen=True)
class BleTarget:
    """
    BLE 目标设备信息。
    """
    name: str
    address: str


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
