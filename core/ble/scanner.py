#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: BLE 扫描能力封装（向上层提供“扫描到的设备列表”，用于前端下拉选择）

修改日志:
- 2026-05-02: 1.0.0 新增 BLE 扫描封装

作者: Spoon
版本: 1.0.0
"""

from dataclasses import dataclass
from typing import List, Optional

from bleak import BleakScanner


@dataclass(frozen=True)
class BleScanResult:
    """
    单次 BLE 扫描结果。
    """

    name: str
    address: str
    rssi: Optional[int]


async def scan_devices(timeout_sec: float) -> List[BleScanResult]:
    """
    扫描周边 BLE 设备并返回结果列表。

    Args:
        timeout_sec: 扫描超时时间（秒）。

    Returns:
        List[BleScanResult]: 扫描到的设备列表（仅包含可展示字段）。
    """

    devices = await BleakScanner.discover(timeout=float(timeout_sec))
    out: List[BleScanResult] = []
    for dev in devices:
        name = str(dev.name or "")
        address = str(dev.address or "")
        if not address:
            continue
        rssi_val = getattr(dev, "rssi", None)
        rssi = int(rssi_val) if isinstance(rssi_val, (int, float)) else None
        out.append(BleScanResult(name=name, address=address, rssi=rssi))
    return out
