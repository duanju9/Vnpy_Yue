# -*- coding: utf-8 -*-
"""常用技术指标（pandas / numpy），供 chan_web 图表使用。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_ma(close: pd.Series, periods: tuple[int, ...]) -> dict[int, pd.Series]:
    """简单算术均线；``periods`` 去重后按数值排序。"""
    out: dict[int, pd.Series] = {}
    for n in sorted({p for p in periods if p > 0}):
        out[n] = close.rolling(window=n, min_periods=1).mean()
    return out


def compute_macd(
    close: pd.Series,
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD 线、信号线、柱（线 - 信号）。"""
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    line = ema_f - ema_s
    sig = line.ewm(span=signal, adjust=False).mean()
    hist = line - sig
    return line, sig, hist


def compute_kdj(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    *,
    n: int = 9,
    m1: int = 3,
    m2: int = 3,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    KDJ（国内常用平滑：K、D 初值 50，递推平滑 RSV）。
    J = 3K - 2D。
    """
    low_n = low.rolling(n, min_periods=1).min()
    high_n = high.rolling(n, min_periods=1).max()
    denom = (high_n - low_n).replace(0, np.nan)
    rsv = (close - low_n) / denom * 100.0
    rsv = rsv.replace([np.inf, -np.inf], np.nan).fillna(50.0)

    r = rsv.to_numpy(dtype=float)
    length = len(r)
    k_arr = np.zeros(length, dtype=float)
    d_arr = np.zeros(length, dtype=float)
    k_arr[0] = d_arr[0] = 50.0
    a1, a2 = (m1 - 1) / m1, 1.0 / m1
    b1, b2 = (m2 - 1) / m2, 1.0 / m2
    for i in range(1, length):
        k_arr[i] = a1 * k_arr[i - 1] + a2 * r[i]
        d_arr[i] = b1 * d_arr[i - 1] + b2 * k_arr[i]
    j_arr = 3.0 * k_arr - 2.0 * d_arr
    idx = close.index
    return pd.Series(k_arr, index=idx), pd.Series(d_arr, index=idx), pd.Series(j_arr, index=idx)
