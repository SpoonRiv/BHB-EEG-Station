#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: LSL 输出写入（创建 StreamOutlet 并将采样点按时间戳推送到 pylsl）

修改日志:
- 2026-04-30: 1.0.0 创建文件
- 2026-05-21: 1.0.1 pylsl 延迟导入以降低采集进程启动开销

作者: Spoon
版本: 1.0.1
"""

import time
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class LslOutletConfig:
    """
    LSL 输出配置。
    """
    stream_name: str
    stream_type: str
    channel_count: int
    sampling_rate_hz: int
    source_id: str


class LslOutletWriter:
    """
    LSL Outlet 写入器：将采样点推送到 pylsl。
    """

    def __init__(self, cfg: LslOutletConfig):
        from pylsl import StreamInfo, StreamOutlet

        self.cfg = cfg
        info = StreamInfo(
            name=cfg.stream_name,
            type=cfg.stream_type,
            channel_count=cfg.channel_count,
            nominal_srate=float(cfg.sampling_rate_hz),
            channel_format="float32",
            source_id=cfg.source_id,
        )
        self.outlet: Optional[StreamOutlet] = StreamOutlet(info)

    def push_samples(self, samples: List[List[float]]):
        """
        推送多个采样点到 LSL，timestamp 使用本地时间。
        """
        if not self.outlet:
            return
        now = time.time()
        for s in samples:
            self.outlet.push_sample(s, timestamp=now)
