# -*- coding: utf-8 -*-
"""本地数据根目录解析（缓存 / 元数据 / 后续 DuckDB 分析库）"""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    """本仓库根目录（含 vnpy/、examples/ 的那一层）。"""
    return Path(__file__).resolve().parents[2]


def default_data_root() -> Path:
    """
    默认数据目录：``<repo>/data/vnpy_yue``。

    可通过环境变量 ``VNPY_YUE_DATA`` 覆盖（绝对路径或 ``~`` 展开）。
    """
    env = os.environ.get("VNPY_YUE_DATA")
    if env:
        return Path(env).expanduser().resolve()
    return repo_root() / "data" / "vnpy_yue"
