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

**chan_web**：在构造 ``CChan`` 前可调用 ``chan_web_set_kline_feed`` 注入已拉好的 ``DataFrame``，
则 ``get_kl_data`` 不再请求 xtdata；结束后务必 ``chan_web_clear_kline_feed``。
若需强制仍走 xtdata（调试），设置环境变量 ``CHAN_WEB_CHAN_OVERLAY_USE_QMT_REFETCH=1``。

说明：``KL_TYPE.K_3M`` 在 xtdata 中无对应周期，本实现会直接抛错。
"""

from __future__ import annotations

import os
from typing import Any, Iterable, Iterator, Optional

import pandas as pd

from Common.CEnum import AUTYPE, DATA_FIELD, KL_TYPE
from Common.CTime import CTime
from DataAPI.CommonStockAPI import CCommonStockApi
from KLine.KLine_Unit import CKLine_Unit

# chan_web：在跑 CChan 前注入当前页已拉好的 OHLCV，避免再走 xtdata 拉线（见 chan_plotly_overlay）。
_chan_web_kline_feed: Optional[dict[str, Any]] = None


def chan_web_set_kline_feed(
    code: str,
    k_type: KL_TYPE,
    begin_date: str,
    end_date: str,
    df: pd.DataFrame,
) -> None:
    """由 examples/chan_web 在构造 ``CChan`` 前调用；必须在 ``finally`` 里配对 ``chan_web_clear_kline_feed``。"""
    global _chan_web_kline_feed
    _chan_web_kline_feed = {
        "code": code,
        "k_type": k_type,
        "begin_date": begin_date,
        "end_date": end_date,
        "df": df,
    }


def chan_web_clear_kline_feed() -> None:
    global _chan_web_kline_feed
    _chan_web_kline_feed = None


def _pd_ts_to_ctime(ts: Any) -> CTime:
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_convert("Asia/Shanghai")
    dt = t.to_pydatetime()
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)


def _ohlcv_df_to_klu_iter(df: pd.DataFrame) -> Iterator[CKLine_Unit]:
    d = df.sort_index()
    if not isinstance(d.index, pd.DatetimeIndex):
        d = d.copy()
        d.index = pd.to_datetime(d.index)
    ohlc = ("open", "high", "low", "close")
    if all(c in d.columns for c in ohlc):
        d = d.dropna(subset=list(ohlc), how="any")
    if d.empty:
        return
    has_vol = "volume" in d.columns
    has_amt = "amount" in d.columns
    idx = d.index
    for i in range(len(d)):
        ts = idx[i]
        row = d.iloc[i]
        ct = _pd_ts_to_ctime(ts)
        o = float(row["open"])
        h = float(row["high"])
        lo = float(row["low"])
        c = float(row["close"])
        vol = float(row["volume"]) if has_vol and pd.notna(row["volume"]) else 0.0
        amt = float(row["amount"]) if has_amt and pd.notna(row["amount"]) else 0.0
        item = {
            DATA_FIELD.FIELD_TIME: ct,
            DATA_FIELD.FIELD_OPEN: o,
            DATA_FIELD.FIELD_HIGH: h,
            DATA_FIELD.FIELD_LOW: lo,
            DATA_FIELD.FIELD_CLOSE: c,
            DATA_FIELD.FIELD_VOLUME: vol,
            DATA_FIELD.FIELD_TURNOVER: amt,
        }
        yield CKLine_Unit(item)


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
        feed = _chan_web_kline_feed
        if (
            feed is not None
            and feed.get("code") == self.code
            and feed.get("k_type") == self.k_type
            and _norm_xt_range(self.begin_date, self.end_date)
            == _norm_xt_range(feed.get("begin_date"), feed.get("end_date"))
        ):
            yield from _ohlcv_df_to_klu_iter(feed["df"])
            return
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
        feed = _chan_web_kline_feed
        if (
            feed is not None
            and feed.get("code") == self.code
            and feed.get("k_type") == self.k_type
            and _norm_xt_range(self.begin_date, self.end_date)
            == _norm_xt_range(feed.get("begin_date"), feed.get("end_date"))
        ):
            self.name = str(self.code)
            self.is_stock = self.code.endswith(".SH") or self.code.endswith(".SZ")
            return
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
        if _chan_web_kline_feed is not None:
            cls._xtdata = None
            return
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
