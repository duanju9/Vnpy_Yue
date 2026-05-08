# -*- coding: utf-8 -*-
"""
从本地 ``vendor/chan`` 跑 CChan，提取笔 / 中枢区间供 Plotly 叠加。

默认通过 ``DataAPI.XtQuant.chan_web_set_kline_feed`` 把当前页的 ``df`` 注入，
避免 CChan 再调 xtdata；环境变量 ``CHAN_WEB_CHAN_OVERLAY_USE_QMT_REFETCH=1`` 时改回拉线。
失败时返回 None，不抛到 Streamlit 主流程。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

_VENDOR_CHAN = Path(__file__).resolve().parent / "vendor" / "chan"


@dataclass
class ChanOverlay:
    bi_segments: list[tuple[pd.Timestamp, float, pd.Timestamp, float]]
    zs_boxes: list[tuple[pd.Timestamp, pd.Timestamp, float, float]]
    seg_segments: list[tuple[pd.Timestamp, float, pd.Timestamp, float]] = field(default_factory=list)


def is_chan_vendor_ready() -> bool:
    return _VENDOR_CHAN.is_dir() and (_VENDOR_CHAN / "Chan.py").is_file()


def _ensure_sys_path() -> bool:
    p = str(_VENDOR_CHAN.resolve())
    if not is_chan_vendor_ready():
        return False
    if p not in sys.path:
        sys.path.insert(0, p)
    return True


def _ctime_to_ts(ct: Any) -> pd.Timestamp:
    return pd.Timestamp(datetime.fromtimestamp(float(ct.ts)))


def _overlay_use_qmt_refetch() -> bool:
    """为 True 时 CChan 仍走 xtdata 拉线（调试用）；默认 False 用当前页 ``df`` 注入，避免重复请求。"""
    return (os.environ.get("CHAN_WEB_CHAN_OVERLAY_USE_QMT_REFETCH") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def is_chan_overlay_qmt_refetch_enabled() -> bool:
    """与 ``compute_chan_overlay`` 内是否注入页内 df 一致；供缓存键等使用。"""
    return _overlay_use_qmt_refetch()


def _normalize_ohlcv_df(df: pd.DataFrame) -> pd.DataFrame | None:
    """排序、时间索引、去掉 OHLC 含 NaN 的行；缺列则返回 None。"""
    if df is None or df.empty:
        return None
    need = ("open", "high", "low", "close")
    if not all(c in df.columns for c in need):
        return None
    out = df.copy(deep=False)
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index)
    out = out.sort_index()
    out = out.dropna(subset=list(need), how="any")
    if out.empty:
        return None
    return out


def _df_to_chan_range(df: pd.DataFrame, period: str) -> tuple[str, str]:
    lo = pd.Timestamp(df.index.min()).to_pydatetime()
    hi = pd.Timestamp(df.index.max()).to_pydatetime()
    if period == "5m":
        return (
            lo.strftime("%Y%m%d%H%M%S"),
            hi.strftime("%Y%m%d%H%M%S"),
        )
    return (
        lo.strftime("%Y%m%d") + "000000",
        hi.strftime("%Y%m%d") + "235959",
    )


def compute_chan_overlay(code: str, period: str, df: pd.DataFrame) -> ChanOverlay | None:
    """
    :param code: QMT 代码如 ``600519.SH``
    :param period: ``5m`` 或 ``1d``
    """
    if df is None or df.empty or period not in ("5m", "1d"):
        return None
    if not _ensure_sys_path():
        return None
    work = _normalize_ohlcv_df(df)
    if work is None:
        return None
    try:
        from Chan import CChan
        from Common.CEnum import AUTYPE, KL_TYPE
    except Exception:
        return None

    kl = KL_TYPE.K_5M if period == "5m" else KL_TYPE.K_DAY
    begin_t, end_t = _df_to_chan_range(work, period)

    _clear_feed = None
    if not _overlay_use_qmt_refetch():
        try:
            from DataAPI.XtQuant import chan_web_clear_kline_feed, chan_web_set_kline_feed

            chan_web_set_kline_feed(code, kl, begin_t, end_t, work.copy(deep=False))
            _clear_feed = chan_web_clear_kline_feed
        except Exception:
            _clear_feed = None

    try:
        chan = CChan(
            code,
            begin_time=begin_t,
            end_time=end_t,
            lv_list=[kl],
            data_src="custom:XtQuant.CXtQuantStock",
            autype=AUTYPE.QFQ,
        )
    except Exception:
        return None
    finally:
        if _clear_feed is not None:
            try:
                _clear_feed()
            except Exception:
                pass

    kline = chan.kl_datas.get(kl)
    if kline is None:
        return None

    bi_segments: list[tuple[pd.Timestamp, float, pd.Timestamp, float]] = []
    for bi in kline.bi_list:
        try:
            t0 = _ctime_to_ts(bi.get_begin_klu().time)
            t1 = _ctime_to_ts(bi.get_end_klu().time)
            p0 = float(bi.get_begin_val())
            p1 = float(bi.get_end_val())
            bi_segments.append((t0, p0, t1, p1))
        except Exception:
            continue

    zs_boxes: list[tuple[pd.Timestamp, pd.Timestamp, float, float]] = []
    for zs in kline.zs_list.zs_lst:
        try:
            if zs.begin is None or zs.end is None:
                continue
            t0 = _ctime_to_ts(zs.begin)
            t1 = _ctime_to_ts(zs.end)
            zs_boxes.append((t0, t1, float(zs.low), float(zs.high)))
        except Exception:
            continue

    seg_segments: list[tuple[pd.Timestamp, float, pd.Timestamp, float]] = []
    for seg in kline.seg_list:
        try:
            t0 = _ctime_to_ts(seg.get_begin_klu().time)
            t1 = _ctime_to_ts(seg.get_end_klu().time)
            p0 = float(seg.get_begin_val())
            p1 = float(seg.get_end_val())
            seg_segments.append((t0, p0, t1, p1))
        except Exception:
            continue

    if not bi_segments and not zs_boxes and not seg_segments:
        return None
    return ChanOverlay(bi_segments=bi_segments, zs_boxes=zs_boxes, seg_segments=seg_segments)
