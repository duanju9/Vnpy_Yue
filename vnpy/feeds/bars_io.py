# -*- coding: utf-8 -*-
"""Tushare 日线 DataFrame ↔ ``BarData`` / VeighNa ``vt_symbol`` 约定（SSE/SZSE）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from vnpy.trader.object import BarData


def tushare_ts_code_to_vt_symbol(ts_code: str) -> str:
    """
    Tushare 代码 ``600519.SH`` / ``000001.SZ`` → VeighNa ``vt_symbol``（``SSE``/``SZSE``）。
    """
    parts = ts_code.strip().split(".")
    if len(parts) != 2:
        raise ValueError(f"无效 ts_code: {ts_code!r}，期望如 002460.SZ")
    sym, suf = parts[0], parts[1].upper()
    if suf == "SH":
        return f"{sym}.SSE"
    if suf == "SZ":
        return f"{sym}.SZSE"
    if suf == "BJ":
        return f"{sym}.BSE"
    raise ValueError(f"不支持的交易所后缀: {ts_code}")


def daily_tushare_ohlc_df_to_bars(
    df: pd.DataFrame,
    ts_code: str,
    *,
    gateway_name: str = "DB",
) -> list["BarData"]:
    """
    将 Tushare ``daily`` 风格 DataFrame 转为 ``BarData`` 列表（日线）。

    要求列：``open, high, low, close``；``trade_date`` 为 datetime 或可解析日期；
    成交量列 ``vol`` 或 ``volume``；成交额 ``amount`` 可选。
    """
    from vnpy.trader.constant import Interval
    from vnpy.trader.object import BarData
    from vnpy.trader.utility import extract_vt_symbol

    vt_symbol = tushare_ts_code_to_vt_symbol(ts_code)
    symbol, exchange = extract_vt_symbol(vt_symbol)
    bars: list[BarData] = []
    for _, row in df.iterrows():
        dt = row["trade_date"]
        if isinstance(dt, pd.Timestamp):
            dt = dt.to_pydatetime()
        elif not hasattr(dt, "hour"):
            dt = pd.Timestamp(dt).to_pydatetime()
        vol = float(row["vol"]) if "vol" in df.columns else float(row.get("volume", 0))
        amt = float(row["amount"]) if "amount" in df.columns and pd.notna(row.get("amount")) else 0.0
        bars.append(
            BarData(
                symbol=symbol,
                exchange=exchange,
                datetime=dt,
                interval=Interval.DAILY,
                open_price=float(row["open"]),
                high_price=float(row["high"]),
                low_price=float(row["low"]),
                close_price=float(row["close"]),
                volume=float(vol),
                turnover=float(amt),
                gateway_name=gateway_name,
            )
        )
    return bars
