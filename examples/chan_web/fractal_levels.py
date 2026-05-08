# -*- coding: utf-8 -*-
"""简易分形高/低点（默认三根 K：中间高最高 / 中间低最低），近似压力、支撑线。"""

from __future__ import annotations

import pandas as pd


def fractal_high_low(
    df: pd.DataFrame,
    *,
    last_n_peaks: int = 12,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    :param df: 索引为 datetime，列含 high / low
    :param last_n_peaks: 各取最近 N 个分形高、分形低
    :return: (fractal_highs_df, fractal_lows_df)，列 time, price
    """
    if df.empty or "high" not in df.columns or "low" not in df.columns:
        return pd.DataFrame(), pd.DataFrame()

    h = df["high"].values
    l = df["low"].values
    idx = df.index
    n = len(df)
    peaks: list[tuple[pd.Timestamp, float]] = []
    troughs: list[tuple[pd.Timestamp, float]] = []

    for i in range(1, n - 1):
        if h[i] > h[i - 1] and h[i] > h[i + 1]:
            peaks.append((idx[i], float(h[i])))
        if l[i] < l[i - 1] and l[i] < l[i + 1]:
            troughs.append((idx[i], float(l[i])))

    hi = pd.DataFrame(peaks[-last_n_peaks:], columns=["time", "price"])
    lo = pd.DataFrame(troughs[-last_n_peaks:], columns=["time", "price"])
    return hi, lo
