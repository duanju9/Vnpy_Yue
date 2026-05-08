# -*- coding: utf-8 -*-
"""
miniQMT / xtquant → chan.py 的 K 线数据源。

使用方式：将本文件复制到 chan.py 仓库的 ``DataAPI/XtQuant.py``，
然后::

    from Chan import CChan
    from Common.CEnum import KL_TYPE, AUTYPE

    CChan(
        "600519.SH",
        begin_time="20250501093000",
        end_time="20260508150000",
        lv_list=[KL_TYPE.K_5M],
        data_src="custom:XtQuant.CXtQuantStock",
        autype=AUTYPE.QFQ,
    )

环境：已启动 QMT/miniQMT；可选环境变量 ``MINIQMT_USERDATA`` 指向 ``userdata_mini``；
当前 Python 能 ``from xtquant import xtdata``。

说明：``KL_TYPE.K_3M`` 在 xtdata 中无对应周期，本实现会直接抛错。
"""

from __future__ import annotations

import os
from typing import Any, Iterable

import pandas as pd

from Common.CEnum import AUTYPE, DATA_FIELD, KL_TYPE
from Common.CTime import CTime
from DataAPI.CommonStockAPI import CCommonStockApi
from KLine.KLine_Unit import CKLine_Unit


def _import_xtdata() -> Any:
    try:
        from xtquant import xtdata  # type: ignore
    except ImportError:
        import xtquant.xtdata as xtdata  # type: ignore
    return xtdata


def _ctime_from_xt_col(col: Any) -> CTime:
    s = str(int(col)) if isinstance(col, (int, float)) and not isinstance(col, bool) else str(col).strip()
    if len(s) == 8:
        return CTime(int(s[:4]), int(s[4:6]), int(s[6:8]), 0, 0)
    if len(s) >= 12:
        return CTime(int(s[:4]), int(s[4:6]), int(s[6:8]), int(s[8:10]), int(s[10:12]))
    raise ValueError(f"无法解析 xtdata 时间列: {s!r}")


def _norm_xt_range(begin_date: str | None, end_date: str | None) -> tuple[str, str]:
    def _strip(s: str | None) -> str:
        if s is None:
            return ""
        x = str(s).strip().replace("-", "").replace(":", "").replace(" ", "")
        return x

    a = _strip(begin_date)
    b = _strip(end_date)
    if a and len(a) == 8:
        a = a + "000000"
    if b and len(b) == 8:
        b = b + "150000"
    return a, b


def _autype_to_xt(autype: AUTYPE) -> str:
    return {AUTYPE.QFQ: "front", AUTYPE.HFQ: "back", AUTYPE.NONE: "none"}[autype]


def _kl_to_period(kl: KL_TYPE) -> str:
    m = {
        KL_TYPE.K_1M: "1m",
        KL_TYPE.K_5M: "5m",
        KL_TYPE.K_15M: "15m",
        KL_TYPE.K_30M: "30m",
        KL_TYPE.K_60M: "60m",
        KL_TYPE.K_DAY: "1d",
        KL_TYPE.K_WEEK: "1w",
        KL_TYPE.K_MON: "1mon",
        KL_TYPE.K_QUARTER: "1q",
        KL_TYPE.K_YEAR: "1y",
    }
    if kl not in m:
        raise ValueError(f"XtQuant 数据源暂不支持 K 线类型: {kl!r}（如 K_3M 请换 5m/1m）")
    return m[kl]


def _xt_to_df(xtdata: Any, code: str, period: str, start_time: str, end_time: str, dividend_type: str) -> pd.DataFrame:
    if hasattr(xtdata, "connect") and callable(xtdata.connect):
        xtdata.connect()
    if hasattr(xtdata, "download_history_data"):
        try:
            xtdata.download_history_data(
                code,
                period,
                start_time=start_time,
                end_time=end_time,
                incrementally=not bool(start_time),
            )
        except TypeError:
            xtdata.download_history_data(code, period)
    raw = xtdata.get_market_data(
        field_list=["open", "high", "low", "close", "volume", "amount"],
        stock_list=[code],
        period=period,
        start_time=start_time,
        end_time=end_time,
        count=-1,
        dividend_type=dividend_type,
        fill_data=True,
    )
    if not raw or "close" not in raw:
        return pd.DataFrame()
    row = raw["close"].iloc[0]
    cols = row.index.tolist()
    ts = [_ctime_from_xt_col(c) for c in cols]
    df = pd.DataFrame(
        {
            "_ct": ts,
            "open": raw["open"].iloc[0].values,
            "high": raw["high"].iloc[0].values,
            "low": raw["low"].iloc[0].values,
            "close": raw["close"].iloc[0].values,
            "volume": raw["volume"].iloc[0].values,
            "amount": raw["amount"].iloc[0].values,
        },
    )
    return df.drop_duplicates(subset=["_ct"], keep="last")


class CXtQuantStock(CCommonStockApi):
    _xtdata: Any | None = None

    def __init__(
        self,
        code: str,
        k_type: KL_TYPE = KL_TYPE.K_DAY,
        begin_date: str | None = None,
        end_date: str | None = None,
        autype: AUTYPE = AUTYPE.QFQ,
    ):
        super().__init__(code, k_type, begin_date, end_date, autype)

    def get_kl_data(self) -> Iterable[CKLine_Unit]:
        xt = CXtQuantStock._xtdata
        assert xt is not None
        period = _kl_to_period(self.k_type)
        st, et = _norm_xt_range(self.begin_date, self.end_date)
        div = _autype_to_xt(self.autype)
        df = _xt_to_df(xt, self.code, period, st, et, div)
        if df.empty:
            return
        for _, row in df.iterrows():
            t = row["_ct"]
            item = {
                DATA_FIELD.FIELD_TIME: t,
                DATA_FIELD.FIELD_OPEN: float(row["open"]),
                DATA_FIELD.FIELD_HIGH: float(row["high"]),
                DATA_FIELD.FIELD_LOW: float(row["low"]),
                DATA_FIELD.FIELD_CLOSE: float(row["close"]),
                DATA_FIELD.FIELD_VOLUME: float(row["volume"]),
                DATA_FIELD.FIELD_TURNOVER: float(row["amount"]),
            }
            yield CKLine_Unit(item)

    def SetBasciInfo(self):
        xt = CXtQuantStock._xtdata
        assert xt is not None
        try:
            if hasattr(xt, "connect") and callable(xt.connect):
                xt.connect()
            d = xt.get_instrument_detail(self.code, iscomplete=False)
        except Exception:
            d = None
        if isinstance(d, dict) and d.get("InstrumentName"):
            self.name = str(d["InstrumentName"])
        else:
            self.name = self.code
        self.is_stock = self.code.endswith(".SH") or self.code.endswith(".SZ")

    @classmethod
    def do_init(cls):
        xt = _import_xtdata()
        if hasattr(xt, "enable_hello"):
            xt.enable_hello = False
        ud = (os.environ.get("MINIQMT_USERDATA") or "").strip()
        if ud:
            setattr(xt, "data_dir", ud)
        if hasattr(xt, "connect") and callable(xt.connect):
            xt.connect()
        cls._xtdata = xt

    @classmethod
    def do_close(cls):
        cls._xtdata = None
