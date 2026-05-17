#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 加载并校验 10-20 电极二维布局（电极名 -> 归一化坐标），供后端下发给前端绘制地形图。

修改日志:
- 2026-05-17: 1.0.0 创建文件

作者: Spoon
版本: 1.0.0
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ElectrodePosition:
    x: float
    y: float


@dataclass(frozen=True)
class ElectrodeLayoutConfig:
    name: str
    coord_system: str
    positions: Dict[str, ElectrodePosition]
    aliases: Dict[str, str]


def resolve_project_relative_path(config_path: str, project_relative_path: str) -> str:
    """
    将配置中的“项目相对路径”解析为绝对路径。

    Args:
        config_path: configs/config.yaml 的实际路径。
        project_relative_path: 以项目根目录为基准的相对路径（例如 configs/electrodes/xxx.json）。

    Returns:
        绝对路径。
    """
    p = str(project_relative_path or "").strip()
    if not p:
        return ""
    if os.path.isabs(p):
        return p
    root_dir = os.path.abspath(os.path.join(os.path.dirname(config_path), os.pardir))
    return os.path.abspath(os.path.join(root_dir, p))


def load_electrode_layout(config_path: str, layout_path: str, required: bool = False) -> Optional[ElectrodeLayoutConfig]:
    """
    从 JSON 文件加载电极布局。

    Args:
        config_path: configs/config.yaml 的实际路径（用于解析相对路径）。
        layout_path: JSON 文件路径（建议使用项目相对路径）。
        required: 是否强制要求布局文件存在且合法。

    Returns:
        ElectrodeLayoutConfig；当 required=False 且 layout_path 为空/文件不存在/解析失败时返回 None。

    Raises:
        ValueError: required=True 时遇到任何解析/校验错误。
    """
    abs_path = resolve_project_relative_path(config_path=config_path, project_relative_path=layout_path)
    if not abs_path:
        if required:
            raise ValueError("eeg.montage_1020_layout_path 不能为空")
        return None
    if not os.path.exists(abs_path):
        if required:
            raise ValueError(f"电极布局文件不存在: {abs_path}")
        return None
    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            raw: Dict[str, Any] = json.load(f) or {}
    except Exception as e:
        if required:
            raise ValueError(f"电极布局文件读取失败: {abs_path}: {e}")
        return None

    try:
        name = str(raw.get("name", "") or "").strip() or "layout"
        coord = str(raw.get("coord_system", "") or "").strip() or "svg_100x100"
        pos_raw = raw.get("positions", {}) or {}
        if not isinstance(pos_raw, dict) or not pos_raw:
            raise ValueError("positions 必须为非空对象")
        positions: Dict[str, ElectrodePosition] = {}
        for k, v in pos_raw.items():
            key = str(k or "").strip()
            if not key:
                continue
            if not isinstance(v, dict):
                continue
            x = float(v.get("x"))
            y = float(v.get("y"))
            if not (x == x and y == y):
                continue
            positions[key] = ElectrodePosition(x=x, y=y)

        if not positions:
            raise ValueError("positions 解析后为空")

        aliases_raw = raw.get("aliases", {}) or {}
        aliases: Dict[str, str] = {}
        if isinstance(aliases_raw, dict):
            for ak, av in aliases_raw.items():
                a = str(ak or "").strip()
                b = str(av or "").strip()
                if not a or not b:
                    continue
                aliases[a] = b

        return ElectrodeLayoutConfig(name=name, coord_system=coord, positions=positions, aliases=aliases)
    except Exception as e:
        if required:
            raise ValueError(f"电极布局文件格式错误: {abs_path}: {e}")
        return None
