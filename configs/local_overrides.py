#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 本机覆盖配置读写（config.local.yaml），用于保存不希望进入 Git 的运行时偏好（如通道选择）
作者: Spoon
"""

from __future__ import annotations

import os
from typing import Any, Dict

import yaml


def get_local_override_path(base_config_path: str) -> str:
    """
    获取与主配置同目录的本机覆盖配置路径。

    Args:
        base_config_path: 主配置文件路径（通常为 configs/config.yaml）

    Returns:
        str: 覆盖配置文件路径（configs/config.local.yaml）
    """
    base_dir = os.path.dirname(os.path.abspath(base_config_path))
    return os.path.join(base_dir, "config.local.yaml")


def deep_merge_dict(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    深度合并字典（override 覆盖 base）。

    规则：
    - 若 key 对应值均为 dict，则递归合并
    - 否则使用 override 的值替换 base 的值

    Args:
        base: 基础配置字典
        override: 覆盖配置字典

    Returns:
        Dict[str, Any]: 合并后的新字典（不修改入参）
    """
    out: Dict[str, Any] = dict(base or {})
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge_dict(out.get(k, {}), v)
        else:
            out[k] = v
    return out


def load_yaml_file(path: str) -> Dict[str, Any]:
    """
    读取 YAML 文件为 dict；文件不存在则返回空 dict。

    Args:
        path: YAML 文件路径

    Returns:
        Dict[str, Any]: 解析结果
    """
    if not path or not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def write_yaml_file_atomic(path: str, data: Dict[str, Any]) -> None:
    """
    原子写入 YAML 文件（避免写入中断导致文件损坏）。

    Args:
        path: 目标文件路径
        data: 待写入内容（dict）
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data or {}, f, allow_unicode=True, sort_keys=False)
    os.replace(tmp_path, path)
