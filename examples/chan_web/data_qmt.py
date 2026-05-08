# -*- coding: utf-8 -*-
"""从 miniQMT xtdata 拉 OHLCV，复用 quick_tests 内已验证的转换逻辑。"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

_REPO = Path(__file__).resolve().parents[2]
_QT = _REPO / "examples" / "quick_tests"
if str(_QT) not in sys.path:
    sys.path.insert(0, str(_QT))

from qmt_5m_vol_pullback_macd_backtest import (  # noqa: E402
    _import_xtdata,
    xtdata_fetch_1d,
    xtdata_fetch_5m,
)


def fetch_ohlcv(
    code: str,
    period: str,
    count: int,
    *,
    download: bool,
) -> pd.DataFrame:
    """
    :param period: ``5m`` 或 ``1d``
    """
    xt: Any = _import_xtdata()
    userdata = (os.environ.get("MINIQMT_USERDATA") or "").strip() or None
    if period == "5m":
        return xtdata_fetch_5m(xt, code, count, download=download, userdata=userdata)
    if period == "1d":
        return xtdata_fetch_1d(xt, code, count, download=download, userdata=userdata)
    raise ValueError(f"本页暂只支持 period=5m 或 1d，收到: {period!r}")


def fetch_ohlcv_with_pg_cache(
    code: str,
    period: str,
    count: int,
    *,
    download: bool,
    use_pg_backup: bool = True,
) -> tuple[pd.DataFrame, str]:
    """
    **始终以 miniQMT 为准**：先 ``fetch_ohlcv``；有数据则写入 PG 备份；
    无数据或抛错时，若已配置 PG 则读表 ``chan_web_ohlcv_cache`` 作回退。

    :return: ``(df, source)``，``source`` 为 ``"miniQMT"`` | ``"pg_cache"`` | ``"empty"``。
    """
    from instrument_pg import is_pg_configured

    qmt_err: BaseException | None = None
    try:
        df = fetch_ohlcv(code, period, count, download=download)
    except BaseException as e:
        qmt_err = e
        df = pd.DataFrame()

    if df is not None and not df.empty:
        if use_pg_backup and is_pg_configured():
            try:
                from ohlcv_cache_pg import save_ohlcv_cache

                save_ohlcv_cache(code, period, df)
            except Exception:
                pass
        return df, "miniQMT"

    if use_pg_backup and is_pg_configured():
        try:
            from ohlcv_cache_pg import load_ohlcv_cache

            cached = load_ohlcv_cache(code, period, count)
            if cached is not None and not cached.empty:
                return cached, "pg_cache"
        except Exception:
            pass

    if qmt_err is not None:
        raise qmt_err
    return pd.DataFrame(), "empty"


def load_csv(uploaded) -> pd.DataFrame:
    """Streamlit 上传文件 -> DataFrame。需含 datetime 列或索引为第一列时间。"""
    df = pd.read_csv(uploaded)
    if "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime")
    elif "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"])
        df = df.set_index("time")
    else:
        df.iloc[:, 0] = pd.to_datetime(df.iloc[:, 0])
        df = df.set_index(df.columns[0])
    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns:
            raise ValueError(f"CSV 缺少列: {col}")
    return df.sort_index()
