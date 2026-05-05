# -*- coding: utf-8 -*-
"""
Vnpy_Yue 数据接入与本地缓存（feeds）。

与官方 ``vnpy`` 的 ``Datafeed`` / 录制模块互补：本包面向「投研批跑 + 小龙虾代理」，
在本地落 Parquet + SQLite 元数据，为后续指数对比、形态筛选、板块相似度分析铺路。
"""

from .bars_io import daily_tushare_ohlc_df_to_bars, tushare_ts_code_to_vt_symbol
from .cached_daily import fetch_daily_cached, normalize_yyyymmdd
from .daily_store import DailyBarStore
from .paths import default_data_root, repo_root
from .registry import FeedRegistry
from .tsy_pro import (
    TSY_HTTP_URL,
    TSY_SDK_EVENT_URL,
    ThrottledPro,
    get_pro_throttled,
    load_env,
)

__all__ = [
    "TSY_HTTP_URL",
    "TSY_SDK_EVENT_URL",
    "ThrottledPro",
    "DailyBarStore",
    "FeedRegistry",
    "fetch_daily_cached",
    "normalize_yyyymmdd",
    "get_pro_throttled",
    "load_env",
    "default_data_root",
    "repo_root",
    "tushare_ts_code_to_vt_symbol",
    "daily_tushare_ohlc_df_to_bars",
]
