# -*- coding: utf-8 -*-
"""带 Parquet 缓存的日线拉取（缓存命中则零网络请求）。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .daily_store import DailyBarStore
from .paths import default_data_root
from .registry import FeedRegistry
from .tsy_pro import get_pro_throttled


def normalize_yyyymmdd(d: str | datetime) -> str:
    """输入 ``YYYYMMDD`` 或 ``YYYY-MM-DD`` 或 ``datetime``，输出 ``YYYYMMDD``。"""
    if isinstance(d, datetime):
        return d.strftime("%Y%m%d")
    s = str(d).strip().replace("-", "")
    if len(s) < 8:
        raise ValueError(f"无法解析日期: {d!r}")
    return s[:8]


def _covers(df: pd.DataFrame, start: str, end: str) -> bool:
    if df.empty or "trade_date" not in df.columns:
        return False
    td = df["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]
    return bool(td.min() <= start and td.max() >= end)


def _filter_range(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    if df.empty:
        return df
    td = df["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]
    m = (td >= start) & (td <= end)
    return df.loc[m].sort_values("trade_date").reset_index(drop=True)


def fetch_daily_cached(
    ts_code: str,
    start_date: str | datetime,
    end_date: str | datetime,
    *,
    data_root: Path | None = None,
    pro: Any | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    拉取 ``[start_date, end_date]`` 区间日线：先读本地 Parquet，覆盖完整则不打接口；
    否则调用 ``pro.daily`` 拉整段后合并写回。

    :param ts_code: 如 ``000001.SZ``、``600519.SH``
    :param force_refresh: True 时仍合并写回缓存，但忽略「是否已覆盖」判断，强制打一次接口
    """
    root = data_root if data_root is not None else default_data_root()
    start = normalize_yyyymmdd(start_date)
    end = normalize_yyyymmdd(end_date)
    if start > end:
        raise ValueError(f"start_date {start} > end_date {end}")

    store = DailyBarStore(root)
    reg = FeedRegistry(root)
    cached = store.read_daily(ts_code)

    need_network = force_refresh or (not _covers(cached, start, end))
    if not need_network:
        return _filter_range(cached, start, end)

    api = pro or get_pro_throttled()
    raw = api.daily(ts_code=ts_code, start_date=start, end_date=end)
    if raw is None:
        raw = pd.DataFrame()
    rows_fetched = int(len(raw))
    reg.log_sync_run(ts_code, start, end, rows_fetched, source="tsy")

    merged = store.merge_and_write(ts_code, raw)
    if not merged.empty:
        td = merged["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]
        reg.upsert_symbol_daily(
            ts_code,
            min_trade_date=str(td.min()),
            max_trade_date=str(td.max()),
            row_count=int(len(merged)),
        )

    out = _filter_range(merged, start, end)
    if out.empty and rows_fetched == 0:
        raise RuntimeError(
            f"未取到 {ts_code} 在 [{start},{end}] 的日线：请检查权限、代码、网络或限速冷却"
        )
    return out
