# -*- coding: utf-8 -*-
"""
基于 miniQMT（xtdata）5 分钟 K 的简化规则回测。

规则（用户描述落地）
--------------------
**买入（同为 5 分钟 K 判定）**
  连续两段、中间无空隙：
  1) **放量涨**：``n_bull`` 根内累计涨幅 >= ``bull_ret_min``，且段均量 >= ``vol_hi`` × 段开始前 ``vol_ma``；
     且段内至少 **半数 K 为阳线**（``close > open``），弱化横盘凑涨幅。
  2) **缩量跌**：紧随其后的 ``n_bear`` 根累计跌幅 <= ``bear_ret_max``（负值），且段均量 <= ``vol_lo`` × 放量涨段均量；
     且段内至少 **半数 K 为阴线**（``close < open``），弱化横盘凑跌幅。

  **买入时机**（``--buy-mode``）：

  - ``yang_after_bear``（默认）：缩量跌段结束后，自下一根起在 ``yang_max_wait`` 根内找**第一根阳线**（``close > open``），
    于该根**收盘价**买入；窗口内无阳线则放弃该信号。
  - ``bear_last_close``：在缩量跌段**最后一根**收盘价买入（旧版）。

**卖出（5 分钟 K + MACD）**
  **入场日的下一交易日**（按 K 线日期，跳过无数据的自然日）：
  从该日 **第一根 5 分钟 K** 起，在标准 MACD(12,26,9) 上寻找 **DIF 下穿 DEA（死叉）**；
  若当日收盘前未出现死叉，则在 **该日最后一根 5 分钟 K** 收盘价平仓（避免无限持仓）。
  可选 ``--macd-exit-skip-first-bars N``：跳过**次日**当日时间序下前 ``N`` 根 5m 的死叉判定（减轻开盘噪音），
  强平仍可用该日最后一根 K。

**可选顺势过滤（默认关）**
  ``--entry-macd-bull``：仅当买入根上 ``DIF > DEA`` 时保留该买点。

**阶段1 日线环境（可选 ``--daily-phase1``）**
  拉取日线。``--daily-phase1-mode soft``（默认）：买点日前最后一根完整日线 **收盘 > MA20**。
  ``strict``：在上述基础上再要求近 ``daily_attack_lookback`` 日内 **至少一日放量阳线**
  （量 >= ``daily_vol_hi`` × 前一日量均线）。strict 更严，样本上易削弱收益，请按需选用。

**交易日频次限制**
  - 每个**自然交易日**最多触发 **1 次买入**（同日仅保留最早出现的信号）。
  - **卖出当日不再开仓**：上一笔平仓日之后，下一笔买入须晚于该日（避免同日多次买卖）。

数据
----
默认与此前探测一致：``002709.SZ`` 天赐材料，``--download`` 先补本地 5m 缓存。

用法::

   python examples/quick_tests/qmt_5m_vol_pullback_macd_backtest.py
   python examples/quick_tests/qmt_5m_vol_pullback_macd_backtest.py --code 002709.SZ --count 800 --download
   python examples/quick_tests/qmt_5m_vol_pullback_macd_backtest.py --code 603601.SH --count 1200 --download --last-n-sessions 10

图表输出
--------
默认生成 **Plotly 离线 HTML**（内嵌 ``plotly.js``）：上图为 5m K 线 + 买卖标注，下图为平仓后阶梯更新的**复利净值曲线**。
可用 ``--chart-html 路径.html`` 指定文件；``--no-chart`` 关闭写文件。

成交明细表（类 QMT 导出）
------------------------
有成交时默认写出 **CSV** 与 **Markdown**（宽表一行一笔委托 + 下方每笔完整买卖文字明细）。
金额按 ``--lot`` 股数与 ``--commission-bps``（单边费率，按成交金额计）估算手续费与盈亏元。

Excel
-----
``--xlsx`` 单独出现则自动生成 ``output/qmt_5m_{code}_{时间}.xlsx``；也可 ``--xlsx D:\\path\\file.xlsx``。
工作簿含：**5m_K线**（OHLCV）、**策略成交**（有则写明细表）、**回测摘要**。

用法补充::

   python examples/quick_tests/qmt_5m_vol_pullback_macd_backtest.py --code 603601.SH --name 再升科技 --lot 100 --capital 100000 ...
   python examples/quick_tests/qmt_5m_vol_pullback_macd_backtest.py --code 000537.SZ --last-n-sessions 3 --download --xlsx
"""

from __future__ import annotations

import argparse
import io
import math
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# 策略逻辑版本（批量 JSONL、Excel 说明中记录，改规则时递增）
STRATEGY_LOGIC_VERSION = "2026-05-09_dailyPhase1_softDefault"

# 常见标的简称（未传 --name 时使用）
_KNOWN_STOCK_NAMES: dict[str, str] = {
    "603601.SH": "再升科技",
    "002709.SZ": "天赐材料",
    "002460.SZ": "赣锋锂业",
    "600519.SH": "贵州茅台",
    "000001.SZ": "平安银行",
    "000537.SZ": "绿发电力",
    "601989.SH": "中国重工",
}


def _configure_stdio() -> None:
    if sys.platform == "win32" and isinstance(sys.stdout, io.TextIOWrapper):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _import_xtdata() -> Any:
    try:
        from xtquant import xtdata  # type: ignore
    except ImportError:
        import xtquant.xtdata as xtdata  # type: ignore
    return xtdata


def xtdata_fetch_5m(
    xtdata: Any,
    code: str,
    count: int,
    *,
    download: bool,
    userdata: str | None,
) -> pd.DataFrame:
    if hasattr(xtdata, "enable_hello"):
        xtdata.enable_hello = False
    if userdata:
        setattr(xtdata, "data_dir", userdata)
    if hasattr(xtdata, "connect") and callable(xtdata.connect):
        xtdata.connect()
    if download and hasattr(xtdata, "download_history_data"):
        try:
            xtdata.download_history_data(code, period="5m", incrementally=True)
        except TypeError:
            xtdata.download_history_data(code, period="5m")
    raw = xtdata.get_market_data(
        field_list=["open", "high", "low", "close", "volume"],
        stock_list=[code],
        period="5m",
        count=count,
        dividend_type="none",
        fill_data=True,
    )
    if not raw or "close" not in raw:
        raise RuntimeError("get_market_data 返回空")
    row = raw["close"].iloc[0]
    cols = row.index.tolist()
    ts = pd.to_datetime([str(c) for c in cols], format="%Y%m%d%H%M%S", errors="coerce")
    df = pd.DataFrame(
        {
            "open": raw["open"].iloc[0].values,
            "high": raw["high"].iloc[0].values,
            "low": raw["low"].iloc[0].values,
            "close": raw["close"].iloc[0].values,
            "volume": raw["volume"].iloc[0].values,
        },
        index=ts,
    )
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


def xtdata_fetch_1d(
    xtdata: Any,
    code: str,
    count: int,
    *,
    download: bool,
    userdata: str | None,
) -> pd.DataFrame:
    """拉取日线 OHLCV（与 5m 共用 connect / download / userdata）。"""
    if hasattr(xtdata, "enable_hello"):
        xtdata.enable_hello = False
    if userdata:
        setattr(xtdata, "data_dir", userdata)
    if hasattr(xtdata, "connect") and callable(xtdata.connect):
        xtdata.connect()
    if download and hasattr(xtdata, "download_history_data"):
        try:
            xtdata.download_history_data(code, period="1d", incrementally=True)
        except TypeError:
            try:
                xtdata.download_history_data(code, period="1d")
            except Exception:
                pass
    raw = xtdata.get_market_data(
        field_list=["open", "high", "low", "close", "volume"],
        stock_list=[code],
        period="1d",
        count=count,
        dividend_type="none",
        fill_data=True,
    )
    if not raw or "close" not in raw:
        return pd.DataFrame()
    row = raw["close"].iloc[0]
    cols = row.index.tolist()
    ts = pd.to_datetime([str(c) for c in cols], format="%Y%m%d", errors="coerce")
    df = pd.DataFrame(
        {
            "open": raw["open"].iloc[0].values,
            "high": raw["high"].iloc[0].values,
            "low": raw["low"].iloc[0].values,
            "close": raw["close"].iloc[0].values,
            "volume": raw["volume"].iloc[0].values,
        },
        index=ts,
    )
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


def daily_phase1_entry_ok(
    df_daily: pd.DataFrame,
    entry_session_date: Any,
    *,
    mode: str = "soft",
    vol_ma_win: int = 20,
    vol_hi: float = 1.15,
    attack_lookback: int = 5,
    ma20: int = 20,
) -> bool:
    """
    阶段1 日线环境（截至 ``entry_session_date`` 开盘前、仅用已完成日线）：

    - ``soft``（默认）：最后一根已完成日线 **收盘 > MA20**（过滤最弱横盘，少砍信号）。
    - ``strict``：在 soft 条件上，再要求最近 ``attack_lookback`` 日内至少一日 **放量阳线**
      （量 >= ``vol_hi`` × 前一日量均线）；更严，易砍收益但可能减噪。
    """
    if df_daily is None or df_daily.empty:
        return True
    d0 = pd.Timestamp(entry_session_date).normalize()
    hist = df_daily[df_daily.index.normalize() < d0].sort_index()
    m = (mode or "soft").strip().lower()
    if m not in ("soft", "strict"):
        m = "soft"

    need_soft = ma20 + 2
    if len(hist) < need_soft:
        return True
    ma20s = hist["close"].rolling(ma20, min_periods=max(10, ma20 // 2)).mean()
    last = hist.iloc[-1]
    last_ma = float(ma20s.iloc[-1])
    if not np.isfinite(last_ma) or float(last["close"]) <= last_ma:
        return False
    if m == "soft":
        return True

    need = max(vol_ma_win, ma20) + attack_lookback + 2
    if len(hist) < need:
        return True
    vol_ma = hist["volume"].rolling(vol_ma_win, min_periods=max(10, vol_ma_win // 2)).mean()
    tail = hist.tail(attack_lookback)
    pos = hist.index.get_indexer(tail.index)
    for k in range(len(tail)):
        loc = int(pos[k])
        if loc <= 0:
            continue
        row = hist.iloc[loc]
        base = float(vol_ma.iloc[loc - 1])
        if not np.isfinite(base) or base <= 0:
            continue
        if float(row["close"]) <= float(row["open"]):
            continue
        if float(row["volume"]) < vol_hi * base:
            return True
    return False


def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def macd_dif_dea(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series]:
    dif = ema(close, fast) - ema(close, slow)
    dea = ema(dif, signal)
    return dif, dea


def session_date(ts: pd.Timestamp) -> Any:
    return ts.date()


def trim_last_n_trading_sessions(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """只保留时间序列中最后 ``n`` 个有数据的交易日（按 K 线日期去重后取末段）。"""
    if n <= 0 or df.empty:
        return df
    dates = sorted({session_date(ts) for ts in df.index})
    if len(dates) <= n:
        return df
    keep = set(dates[-n:])
    mask = np.array([session_date(ts) in keep for ts in df.index], dtype=bool)
    return df.loc[mask].copy()


def interval_buy_hold_open_to_close_pct(df: pd.DataFrame) -> Any:
    """
    与技术面回测 **同一根 5m 序列**（截取后不变）：**第一根开盘价 → 最后一根收盘价** 的涨跌幅%%。

    不含选股含义，仅作「本操作区间价格若一路持有」的对照标尺，便于与策略复利比较。
    """
    if df is None or df.empty:
        return ""
    o0 = float(df["open"].iloc[0])
    c1 = float(df["close"].iloc[-1])
    if not (np.isfinite(o0) and o0 > 0 and np.isfinite(c1)):
        return ""
    return round((c1 / o0 - 1.0) * 100.0, 4)


def strategy_compound_minus_interval_pct(compound_pct: float, interval_pct: Any) -> Any:
    """策略复利累计收益率%% − 区间首开末收涨跌%%（百分点差；非年化）。"""
    if interval_pct == "" or interval_pct is None:
        return ""
    try:
        return round(float(compound_pct) - float(interval_pct), 4)
    except (TypeError, ValueError):
        return ""


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    pnl_pct: float
    exit_reason: str


def find_pattern_buy_indices(
    df: pd.DataFrame,
    *,
    n_bull: int,
    n_bear: int,
    vol_ma_win: int,
    vol_hi: float,
    vol_lo: float,
    bull_ret_min: float,
    bear_ret_max: float,
    buy_mode: str = "yang_after_bear",
    yang_max_wait: int = 48,
) -> list[int]:
    """返回满足「放量涨→缩量跌」后、按 ``buy_mode`` 确定的**买入**在 df 上的 iloc 下标。"""
    if len(df) < vol_ma_win + n_bull + n_bear + 2:
        return []
    vol_ma = df["volume"].rolling(vol_ma_win, min_periods=max(5, vol_ma_win // 2)).mean()
    closes = df["close"].to_numpy()
    opens = df["open"].to_numpy()
    vols = df["volume"].to_numpy()
    vma = vol_ma.to_numpy()
    out: list[int] = []
    for i in range(vol_ma_win, len(df) - n_bull - n_bear):
        b0, b1 = i, i + n_bull - 1
        s0, s1 = i + n_bull, i + n_bull + n_bear - 1
        base = vma[b0 - 1]
        if not np.isfinite(base) or base <= 0:
            continue
        if closes[b0] <= 0 or closes[s0] <= 0:
            continue
        bull_ret = closes[b1] / closes[b0] - 1.0
        bear_ret = closes[s1] / closes[s0] - 1.0
        v_bull = float(vols[b0 : b1 + 1].mean())
        v_bear = float(vols[s0 : s1 + 1].mean())
        if bull_ret < bull_ret_min:
            continue
        if v_bull < vol_hi * float(base):
            continue
        if bear_ret > bear_ret_max:
            continue
        if v_bear > vol_lo * v_bull:
            continue
        bull_green = int(np.sum(closes[b0 : b1 + 1] > opens[b0 : b1 + 1]))
        if bull_green < max(1, (n_bull + 1) // 2):
            continue
        bear_red = int(np.sum(closes[s0 : s1 + 1] < opens[s0 : s1 + 1]))
        if bear_red < max(1, (n_bear + 1) // 2):
            continue
        if buy_mode == "bear_last_close":
            out.append(s1)
            continue
        # 缩量跌之后：第一根阳线（含 s1+1 起的若干根 5m）
        j_end = min(s1 + 1 + max(1, yang_max_wait), len(df))
        buy_idx: int | None = None
        for j in range(s1 + 1, j_end):
            if closes[j] > opens[j]:
                buy_idx = j
                break
        if buy_idx is not None:
            out.append(buy_idx)
    return out


def filter_one_buy_per_trading_day(buy_indices: list[int], df: pd.DataFrame) -> list[int]:
    """同一日历日只保留最早的一个买入下标。"""
    best: dict[Any, int] = {}
    for bi in sorted(buy_indices):
        d = session_date(df.index[bi])
        if d not in best or bi < best[d]:
            best[d] = bi
    return sorted(best.values())


def next_trading_date(dates_sorted: list, after: Any) -> Any | None:
    for d in dates_sorted:
        if d > after:
            return d
    return None


def backtest(
    df: pd.DataFrame,
    buy_indices: list[int],
    *,
    dif: pd.Series,
    dea: pd.Series,
    exit_skip_first_bars: int = 0,
) -> list[Trade]:
    all_dates = sorted({session_date(ts) for ts in df.index})
    trades: list[Trade] = []
    next_buy_cursor = 0
    last_exit_day: Any | None = None

    for bi in buy_indices:
        if bi < next_buy_cursor:
            continue
        entry_price = float(df["close"].iloc[bi])
        entry_day = session_date(df.index[bi])
        if last_exit_day is not None and entry_day <= last_exit_day:
            continue
        nd = next_trading_date(all_dates, entry_day)
        if nd is None:
            break
        day_mask = np.array([session_date(ts) == nd for ts in df.index], dtype=bool)
        day_pos = np.flatnonzero(day_mask)
        if day_pos.size == 0:
            continue
        exit_pos: int | None = None
        reason = "次日收盘强平"
        skip0 = max(0, int(exit_skip_first_bars))
        for idx_k, j in enumerate(day_pos):
            if j == 0:
                continue
            if skip0 > 0 and idx_k < skip0:
                continue
            if not (np.isfinite(dif.iloc[j]) and np.isfinite(dea.iloc[j])):
                continue
            if not (np.isfinite(dif.iloc[j - 1]) and np.isfinite(dea.iloc[j - 1])):
                continue
            # 死叉：上一根 DIF >= DEA，本根 DIF < DEA
            if float(dif.iloc[j - 1]) >= float(dea.iloc[j - 1]) and float(dif.iloc[j]) < float(dea.iloc[j]):
                exit_pos = j
                reason = "次日MACD死叉(5m)"
                break
        if exit_pos is None:
            exit_pos = int(day_pos[-1])
        exit_price = float(df["close"].iloc[exit_pos])
        pnl = (exit_price / entry_price - 1.0) * 100.0
        trades.append(
            Trade(
                entry_time=df.index[bi],
                exit_time=df.index[exit_pos],
                entry_price=entry_price,
                exit_price=exit_price,
                pnl_pct=pnl,
                exit_reason=reason,
            )
        )
        next_buy_cursor = exit_pos + 1
        last_exit_day = session_date(df.index[exit_pos])

    return trades


def run_backtest_on_df(
    df: pd.DataFrame,
    args: argparse.Namespace,
    df_daily: pd.DataFrame | None = None,
) -> list[Trade]:
    dif, dea = macd_dif_dea(df["close"], fast=args.macd_fast, slow=args.macd_slow, signal=args.macd_signal)
    buys = find_pattern_buy_indices(
        df,
        n_bull=args.n_bull,
        n_bear=args.n_bear,
        vol_ma_win=args.vol_ma_win,
        vol_hi=args.vol_hi,
        vol_lo=args.vol_lo,
        bull_ret_min=args.bull_ret_min,
        bear_ret_max=args.bear_ret_max,
        buy_mode=args.buy_mode,
        yang_max_wait=args.yang_max_wait,
    )
    # 去重：相邻信号若重叠段相同只保留第一个
    filtered: list[int] = []
    last = -10**9
    min_gap = args.n_bull + args.n_bear
    for b in buys:
        if b - last < min_gap:
            continue
        filtered.append(b)
        last = b
    filtered = filter_one_buy_per_trading_day(filtered, df)
    if getattr(args, "entry_macd_bull", False):
        filtered = [
            bi
            for bi in filtered
            if 0 <= bi < len(dif)
            and np.isfinite(dif.iloc[bi])
            and np.isfinite(dea.iloc[bi])
            and float(dif.iloc[bi]) > float(dea.iloc[bi])
        ]
    if (
        df_daily is not None
        and not df_daily.empty
        and getattr(args, "daily_phase1", False)
    ):
        dvw = int(getattr(args, "daily_vol_ma_win", 20))
        dvh = float(getattr(args, "daily_vol_hi", 1.15))
        dalb = int(getattr(args, "daily_attack_lookback", 5))
        dma = int(getattr(args, "daily_ma20", 20))
        dmode = str(getattr(args, "daily_phase1_mode", "soft") or "soft").strip().lower()
        filtered = [
            bi
            for bi in filtered
            if daily_phase1_entry_ok(
                df_daily,
                session_date(df.index[bi]),
                mode=dmode,
                vol_ma_win=dvw,
                vol_hi=dvh,
                attack_lookback=dalb,
                ma20=dma,
            )
        ]
    skip_exit = int(getattr(args, "macd_exit_skip_first_bars", 0) or 0)
    return backtest(df, filtered, dif=dif, dea=dea, exit_skip_first_bars=skip_exit)


def _hold_bars_5m(df: pd.DataFrame, t: Trade) -> int:
    idx = df.index
    pi = int(idx.get_indexer([pd.Timestamp(t.entry_time)], method="nearest")[0])
    pj = int(idx.get_indexer([pd.Timestamp(t.exit_time)], method="nearest")[0])
    if pj < pi:
        return 0
    return pj - pi + 1


def batch_detail_rows(
    trades: list[Trade],
    df: pd.DataFrame,
    *,
    lot: int,
    commission_bps: float,
) -> list[dict[str, Any]]:
    """批量 Excel「逐笔」sheet。

    口径说明：
    - **价上收益率**：仅 (卖-买)/买×100%，**不含**手续费，与回测引擎 ``Trade.pnl_pct`` 一致。
    - **本笔毛盈亏元**：(卖价-买价)×手数，未扣费。
    - **本笔手续费元**：买卖各按成交金额×单边 bps。
    - **扣费后收益率**：净盈亏 ÷ 买入金额×100%，与 **本笔净盈亏元** 同一口径，可与净额交叉核对。
    """
    rate = commission_bps / 10000.0
    rows: list[dict[str, Any]] = []
    for i, t in enumerate(trades, start=1):
        buy_amt = t.entry_price * lot
        sell_amt = t.exit_price * lot
        fee = (buy_amt + sell_amt) * rate
        gross_y = (t.exit_price - t.entry_price) * lot
        net_y = gross_y - fee
        denom = float(buy_amt) if buy_amt > 0 else 0.0
        pct_after = round(100.0 * net_y / denom, 4) if denom > 0 else ""
        rows.append(
            {
                "轮次": i,
                "买入时间": t.entry_time.strftime("%Y-%m-%d %H:%M:%S"),
                "卖出时间": t.exit_time.strftime("%Y-%m-%d %H:%M:%S"),
                "买入价": round(float(t.entry_price), 4),
                "卖出价": round(float(t.exit_price), 4),
                "价上收益率": round(float(t.pnl_pct), 4),
                "本笔毛盈亏元": round(gross_y, 2),
                "本笔手续费元": round(fee, 2),
                "扣费后收益率": pct_after,
                "本笔净盈亏元": round(net_y, 2),
                "平仓原因": t.exit_reason,
                "持仓5m根数": _hold_bars_5m(df, t),
            }
        )
    return rows


def batch_summary_cn(
    trades: list[Trade],
    df: pd.DataFrame,
    *,
    compound_pct: float,
    capital: float,
    lot: int,
    commission_bps: float,
) -> dict[str, Any]:
    """批量汇总表用：中文口径比率、10 万本金复利权益、时间线等。"""
    rets = [x.pnl_pct for x in trades]
    n = len(rets)
    rate = commission_bps / 10000.0
    sum_net_y = 0.0
    for t in trades:
        buy_amt = t.entry_price * lot
        sell_amt = t.exit_price * lot
        sum_net_y += (t.exit_price - t.entry_price) * lot - (buy_amt + sell_amt) * rate

    days_n = max(1, int((pd.Timestamp(df.index[-1]) - pd.Timestamp(df.index[0])).days) + 1)
    ibh = interval_buy_hold_open_to_close_pct(df)
    excess = strategy_compound_minus_interval_pct(compound_pct, ibh)
    base: dict[str, Any] = {
        "K线根数": len(df),
        "区间起始": str(df.index[0]),
        "区间结束": str(df.index[-1]),
        "区间首开末收涨跌": ibh,
        "策略复利减区间涨跌": excess,
        "成交笔数": n,
        "展示用本金元": round(capital, 2),
        "假设每笔股数": lot,
        "单边佣金bps": commission_bps,
    }
    if n == 0:
        base.update(
            {
                "算术平均单笔收益率": "",
                "算术累加收益率": "",
                "复利累计收益率": round(compound_pct, 4),
                "胜率": "",
                "盈利笔数": 0,
                "亏损笔数": 0,
                "持平笔数": 0,
                "最大单笔盈利": "",
                "最大单笔亏损": "",
                "单笔收益率标准差": "",
                "盈亏比": "",
                "平均盈利单笔": "",
                "平均亏损单笔": "",
                "笔均持仓5m根数": "",
                "区间自然日数": days_n,
                "年化估算收益率": "",
                "过程最大回撤": "",
                "按复利测算期末权益元": round(capital, 2),
                "较期初盈亏额元": 0.0,
                "固定手数双边佣金后净盈亏合计元": round(sum_net_y, 2),
                "买卖时间线": "",
            }
        )
        return base

    wins = sum(1 for r in rets if r > 0)
    losses = sum(1 for r in rets if r < 0)
    flats = n - wins - losses
    sum_pos = sum(r for r in rets if r > 0)
    sum_neg = sum(r for r in rets if r < 0)
    if sum_neg < 0:
        pl_ratio: Any = round(sum_pos / abs(sum_neg), 4)
    elif sum_pos > 0:
        pl_ratio = "∞"
    else:
        pl_ratio = ""

    std = round(float(np.std(rets, ddof=0)), 4)
    avg_win = round(float(np.mean([r for r in rets if r > 0])), 4) if wins else ""
    avg_loss = round(float(np.mean([r for r in rets if r < 0])), 4) if losses else ""
    holds = [_hold_bars_5m(df, t) for t in trades]
    avg_hold = round(float(np.mean(holds)), 2) if holds else ""

    nav_s = equity_nav_series(df, trades)
    peak = np.maximum.accumulate(nav_s.values)
    with np.errstate(divide="ignore", invalid="ignore"):
        r_dd = (nav_s.values / peak - 1.0) * 100.0
    max_dd = round(float(np.nanmin(r_dd)), 4)

    mult = float(np.prod([1.0 + r / 100.0 for r in rets]))
    ann: str | float = ""
    if mult > 0 and days_n > 0:
        try:
            raw_ann = (mult ** (365.0 / days_n) - 1.0) * 100.0
            ann = round(float(raw_ann), 4) if math.isfinite(raw_ann) else ""
        except OverflowError:
            ann = ""

    ending = round(capital * mult, 2)
    pnl_from_start = round(ending - capital, 2)
    timeline = " | ".join(
        f"第{i}笔 买{t.entry_time.strftime('%Y-%m-%d %H:%M')}→卖{t.exit_time.strftime('%Y-%m-%d %H:%M')} 收益{t.pnl_pct:+.2f}%"
        for i, t in enumerate(trades, 1)
    )

    base.update(
        {
            "算术平均单笔收益率": round(float(np.mean(rets)), 4),
            "算术累加收益率": round(float(np.sum(rets)), 4),
            "复利累计收益率": round(compound_pct, 4),
            "胜率": round(100.0 * wins / n, 4),
            "盈利笔数": wins,
            "亏损笔数": losses,
            "持平笔数": flats,
            "最大单笔盈利": round(float(max(rets)), 4),
            "最大单笔亏损": round(float(min(rets)), 4),
            "单笔收益率标准差": std,
            "盈亏比": pl_ratio,
            "平均盈利单笔": avg_win,
            "平均亏损单笔": avg_loss,
            "笔均持仓5m根数": avg_hold,
            "区间自然日数": days_n,
            "年化估算收益率": ann,
            "过程最大回撤": max_dd,
            "按复利测算期末权益元": ending,
            "较期初盈亏额元": pnl_from_start,
            "固定手数双边佣金后净盈亏合计元": round(sum_net_y, 2),
            "买卖时间线": timeline,
        }
    )
    return base


def run_single_symbol_backtest(xtdata: Any, code: str, args: argparse.Namespace) -> dict[str, Any]:
    """
    供批量脚本复用：拉取 5m → 按 ``args.last_n_sessions`` 截取 → 回测。

    返回 dict：``ok``、``ts_code``、``n_bars``、``n_trades``、``compound_pct`` 等；失败时 ``ok=False`` 且含 ``error``。
    """
    out: dict[str, Any] = {"ts_code": code, "ok": False}
    try:
        df = xtdata_fetch_5m(
            xtdata,
            code,
            args.count,
            download=args.download,
            userdata=args.userdata,
        )
    except Exception as e:
        out["error"] = f"fetch:{e!s}"
        return out
    if df.empty:
        out["error"] = "empty_df"
        return out
    if getattr(args, "last_n_sessions", 0) and args.last_n_sessions > 0:
        df = trim_last_n_trading_sessions(df, args.last_n_sessions)
    if df.empty:
        out["error"] = "empty_after_trim"
        return out
    df_daily: pd.DataFrame | None = None
    if getattr(args, "daily_phase1", False):
        try:
            n1d = int(getattr(args, "daily_lookback_bars", 160))
            df_daily = xtdata_fetch_1d(
                xtdata,
                code,
                n1d,
                download=args.download,
                userdata=args.userdata,
            )
            if df_daily is None or df_daily.empty:
                df_daily = None
        except Exception:
            df_daily = None
    trades = run_backtest_on_df(df, args, df_daily=df_daily)
    rets = [t.pnl_pct for t in trades]
    compound = float(np.prod([1.0 + r / 100.0 for r in rets]) - 1.0) * 100.0 if rets else 0.0
    sn = (resolve_stock_name(code, None) or xtdata_stock_name(xtdata, code) or "").strip()
    capital = float(getattr(args, "capital", 100_000.0))
    lot = int(getattr(args, "lot", 100))
    commission_bps = float(getattr(args, "commission_bps", 2.5))
    out.update(
        {
            "ok": True,
            "stock_name": sn,
            "n_bars": len(df),
            "t_start": str(df.index[0]),
            "t_end": str(df.index[-1]),
            "n_trades": len(trades),
            "mean_trade_pct": float(np.mean(rets)) if rets else None,
            "sum_trade_pct": float(np.sum(rets)) if rets else None,
            "compound_pct": compound,
        }
    )
    out["summary_cn"] = batch_summary_cn(
        trades,
        df,
        compound_pct=compound,
        capital=capital,
        lot=lot,
        commission_bps=commission_bps,
    )
    out["trades_detail_cn"] = batch_detail_rows(trades, df, lot=lot, commission_bps=commission_bps)
    return out


def equity_nav_series(df: pd.DataFrame, trades: list[Trade]) -> pd.Series:
    """每根 K 对应净值：已发生的平仓按单笔收益率复利连乘，持仓中未到平仓则净值不变。"""
    acc = 1.0
    j = 0
    vals: list[float] = []
    for ts in df.index:
        while j < len(trades) and trades[j].exit_time <= ts:
            acc *= 1.0 + trades[j].pnl_pct / 100.0
            j += 1
        vals.append(acc)
    return pd.Series(vals, index=df.index, name="nav")


def write_chart_html(
    df: pd.DataFrame,
    trades: list[Trade],
    *,
    code: str,
    compound_pct: float,
    out_path: Path,
    title: str,
    stock_name: str = "",
) -> None:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    nav = equity_nav_series(df, trades)
    cum_pct = (nav - 1.0) * 100.0

    disp = (stock_name.strip() if stock_name else "") or code
    head = f"{disp}（{code}）— {title}" if stock_name.strip() else f"{code} — {title}"
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.68, 0.32],
        subplot_titles=(f"{head} — 5m K 与买卖点", "复利累计收益 %（按平仓阶梯更新）"),
    )
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="5m",
            increasing_line_color="#d62728",
            decreasing_line_color="#2ca02c",
        ),
        row=1,
        col=1,
    )
    if trades:
        fig.add_trace(
            go.Scatter(
                x=[t.entry_time for t in trades],
                y=[t.entry_price for t in trades],
                mode="markers+text",
                marker=dict(symbol="triangle-up", size=14, color="#2ca02c", line=dict(width=1, color="white")),
                text=[f"买{i + 1}" for i in range(len(trades))],
                textposition="top center",
                name="买入",
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=[t.exit_time for t in trades],
                y=[t.exit_price for t in trades],
                mode="markers+text",
                marker=dict(symbol="triangle-down", size=14, color="#d62728", line=dict(width=1, color="white")),
                text=[f"卖{i + 1}" for i in range(len(trades))],
                textposition="bottom center",
                name="卖出",
            ),
            row=1,
            col=1,
        )

    fig.add_trace(
        go.Scatter(x=df.index, y=cum_pct, mode="lines", line=dict(color="#1f77b4", width=2), name="累计收益%"),
        row=2,
        col=1,
    )
    fig.add_hline(y=0, line_dash="dot", line_color="gray", row=2, col=1)

    ann_label = f"{disp}（{code}）" if stock_name.strip() else code
    ann = (
        f"标的 {ann_label} ｜ 笔数 {len(trades)} ｜ 连乘合计 {compound_pct:+.2f}% "
        f"｜ 区间 {df.index[0]} ~ {df.index[-1]}"
    )
    fig.update_layout(
        title=ann,
        height=900,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=48, r=24, t=80, b=48),
        xaxis_rangeslider_visible=False,
        template="plotly_white",
    )
    fig.update_yaxes(title_text="价格", row=1, col=1)
    fig.update_yaxes(title_text="%", row=2, col=1)
    fig.update_xaxes(title_text="时间", row=2, col=1)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(out_path), include_plotlyjs=True, full_html=True)


def xtdata_stock_name(xtdata: Any, ts_code: str) -> str:
    """从 miniQMT 合约详情取中文简称（失败返回空串）。"""
    try:
        d = xtdata.get_instrument_detail(str(ts_code).strip())
        if isinstance(d, dict):
            nm = d.get("InstrumentName")
            if nm is not None and str(nm).strip():
                return str(nm).strip()
    except Exception:
        pass
    return ""


def safe_filename_part(s: str, max_len: int = 48) -> str:
    """Windows 文件名安全片段（去非法字符、控长）。"""
    if not s:
        return "na"
    illegal = '<>:"/\\|?*\r\n\t'
    t = str(s).strip()
    for ch in illegal:
        t = t.replace(ch, "_")
    t = "".join(ch if ord(ch) >= 32 else "_" for ch in t)
    t = t.rstrip(" .")
    if not t:
        t = "na"
    if len(t) > max_len:
        t = t[:max_len].rstrip(" .")
    return t or "na"


def strategy_filename_tag_cn(buy_mode: str) -> str:
    """用于导出文件名中的中文策略短标签。"""
    bm = (buy_mode or "").strip()
    if not bm:
        return ""
    if bm == "yang_after_bear":
        return "5m放量涨缩量跌_阳线买_次日MACD死叉"
    if bm == "bear_last_close":
        return "5m放量涨缩量跌_末阴收盘买_次日MACD死叉"
    return safe_filename_part(bm, 32)


def resolve_stock_name(ts_code: str, override: str | None) -> str:
    o = (override or "").strip()
    if o:
        return o
    return _KNOWN_STOCK_NAMES.get(ts_code, "")


def build_execution_table(
    trades: list[Trade],
    *,
    ts_code: str,
    stock_name: str,
    lot: int,
    commission_bps: float,
    capital: float,
) -> pd.DataFrame:
    """
    类 QMT 成交宽表：每笔「买」「卖」各占一行，便于粘贴到 Excel。

    手续费：单边 ``commission_bps``（万分之一为 1.0），买卖各计一次。
    """
    rate = commission_bps / 10000.0
    rows: list[dict[str, Any]] = []
    seq = 0
    cum_pnl_yuan = 0.0
    nav = 1.0
    for round_i, t in enumerate(trades, start=1):
        buy_amt = t.entry_price * lot
        sell_amt = t.exit_price * lot
        fee_buy = buy_amt * rate
        fee_sell = sell_amt * rate
        gross = (t.exit_price - t.entry_price) * lot
        net = gross - fee_buy - fee_sell
        cum_pnl_yuan += net
        nav *= 1.0 + t.pnl_pct / 100.0
        cum_pct_vs_cap = (cum_pnl_yuan / capital * 100.0) if capital > 0 else float("nan")

        seq += 1
        rows.append(
            {
                "序号": seq,
                "分笔": f"{round_i}-买",
                "证券代码": ts_code,
                "证券名称": stock_name,
                "成交时间": t.entry_time.strftime("%Y-%m-%d %H:%M:%S"),
                "买卖": "买入",
                "成交价格": round(t.entry_price, 4),
                "成交数量": lot,
                "成交金额": round(buy_amt, 2),
                "手续费": round(fee_buy, 2),
                "本笔净额": round(-buy_amt - fee_buy, 2),
                "本轮盈亏额": "",
                "本轮盈亏%": "",
                "累计盈亏额": "",
                "累计收益率%": "",
                "备注": t.exit_reason,
            }
        )
        seq += 1
        rows.append(
            {
                "序号": seq,
                "分笔": f"{round_i}-卖",
                "证券代码": ts_code,
                "证券名称": stock_name,
                "成交时间": t.exit_time.strftime("%Y-%m-%d %H:%M:%S"),
                "买卖": "卖出",
                "成交价格": round(t.exit_price, 4),
                "成交数量": lot,
                "成交金额": round(sell_amt, 2),
                "手续费": round(fee_sell, 2),
                "本笔净额": round(sell_amt - fee_sell, 2),
                "本轮盈亏额": round(net, 2),
                "本轮盈亏%": round(t.pnl_pct, 4),
                "累计盈亏额": round(cum_pnl_yuan, 2),
                "累计收益率%": round(cum_pct_vs_cap, 4) if capital > 0 else "",
                "备注": t.exit_reason,
            }
        )

    return pd.DataFrame(rows)


def _df_to_simple_markdown(df: pd.DataFrame) -> str:
    """不依赖 ``tabulate``，避免 ``to_markdown`` 额外依赖。"""
    cols = [str(c) for c in df.columns]
    esc = [df[c].astype(str).str.replace("|", "\\|", regex=False) for c in df.columns]
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = []
    for i in range(len(df)):
        row = "| " + " | ".join(str(esc[j].iloc[i]) for j in range(len(cols))) + " |"
        body.append(row)
    return "\n".join([header, sep, *body])


def write_trade_report(
    trades: list[Trade],
    tbl: pd.DataFrame,
    *,
    ts_code: str,
    stock_name: str,
    lot: int,
    capital: float,
    commission_bps: float,
    csv_path: Path,
    md_path: Path,
) -> None:
    tbl.to_csv(csv_path, index=False, encoding="utf-8-sig")

    lines: list[str] = []
    title_name = stock_name or ts_code
    lines.append(f"# {title_name}（{ts_code}）5m 策略回测 — 成交与盈亏")
    lines.append("")
    lines.append(f"- 回测股数每边：`{lot}` 股；单边手续费率：`{commission_bps}`（万分之一为 1，万2.5 填 2.5）")
    lines.append(f"- 用于累计收益率%的分母资金：`{capital:,.2f}` 元（仅展示用，可 `--capital` 修改）")
    lines.append("")
    lines.append("## 一、成交汇总表（类 QMT 宽表）")
    lines.append("")
    lines.append(_df_to_simple_markdown(tbl))
    lines.append("")
    lines.append("## 二、每笔完整买卖明细（含盈亏）")
    lines.append("")
    rate = commission_bps / 10000.0
    cum = 0.0
    for i, t in enumerate(trades, start=1):
        buy_amt = t.entry_price * lot
        sell_amt = t.exit_price * lot
        fee_buy = buy_amt * rate
        fee_sell = sell_amt * rate
        gross = (t.exit_price - t.entry_price) * lot
        net = gross - fee_buy - fee_sell
        cum += net
        lines.append(f"### 第 {i} 笔")
        lines.append("")
        lines.append(f"- **买入**：{t.entry_time}  价格 **{t.entry_price:.4f}**  数量 **{lot}**  金额 **{buy_amt:,.2f}** 元  手续费 **{fee_buy:,.2f}** 元")
        lines.append(f"- **卖出**：{t.exit_time}  价格 **{t.exit_price:.4f}**  数量 **{lot}**  金额 **{sell_amt:,.2f}** 元  手续费 **{fee_sell:,.2f}** 元")
        lines.append(
            f"- **本轮毛盈亏**：{gross:+,.2f} 元；**扣费后净盈亏**：**{net:+,.2f}** 元；"
            f"**收益率（价）**：{t.pnl_pct:+.4f}% ；平仓原因：{t.exit_reason}"
        )
        lines.append(f"- **截至本笔累计净盈亏**：{cum:+,.2f} 元")
        if capital > 0:
            lines.append(f"- **截至本笔累计收益率（对本金 {capital:,.2f}）**：{cum / capital * 100:+.4f}%")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")


def print_execution_table(tbl: pd.DataFrame) -> None:
    """控制台宽表（列多时可能换行，以 CSV 为准）。"""
    with pd.option_context("display.max_columns", None, "display.width", 200, "display.max_colwidth", 20):
        print(tbl.to_string(index=False))


def write_excel_pack(
    df: pd.DataFrame,
    trades: list[Trade],
    tbl: pd.DataFrame | None,
    xlsx_path: Path,
    *,
    ts_code: str,
    stock_name: str,
    compound_pct: float,
    mean_ret: float | None,
    sum_ret: float | None,
    lot: int,
    capital: float,
    commission_bps: float,
    buy_mode: str = "",
    yang_max_wait: int = 0,
) -> None:
    """写出 xlsx：K 线、成交表、摘要。需 ``openpyxl``。"""
    try:
        import openpyxl  # noqa: F401
    except ImportError as e:
        raise ImportError("导出 Excel 需要安装: pip install openpyxl") from e

    kline = df.reset_index()
    kline.rename(columns={kline.columns[0]: "时间"}, inplace=True)

    _ibh = interval_buy_hold_open_to_close_pct(df)
    _ex = strategy_compound_minus_interval_pct(compound_pct, _ibh)
    summary_rows = [
        ("证券代码", ts_code),
        ("证券名称", stock_name or ""),
        ("策略标签", strategy_filename_tag_cn(buy_mode) if buy_mode else ""),
        ("买入模式", buy_mode or ""),
        ("阳线最长等待根数", yang_max_wait if buy_mode == "yang_after_bear" else ""),
        ("K线周期", "5分钟"),
        ("K线根数", len(df)),
        ("时间范围起", str(df.index[0])),
        ("时间范围止", str(df.index[-1])),
        ("区间首开末收涨跌%", _ibh if _ibh != "" else ""),
        ("策略复利减区间涨跌pt", _ex if _ex != "" else ""),
        ("回测成交笔数", len(trades)),
        ("复利累计收益率%", round(compound_pct, 4) if trades else ""),
        ("算术平均单笔%", round(mean_ret, 4) if mean_ret is not None else ""),
        ("算术累加%", round(sum_ret, 4) if sum_ret is not None else ""),
        ("假设每笔股数", lot),
        ("展示用本金", capital),
        ("单边佣金bps", commission_bps),
    ]
    summary_df = pd.DataFrame(summary_rows, columns=["项目", "值"])

    xlsx_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        kline.to_excel(writer, sheet_name="5m_K线", index=False)
        if tbl is not None and not tbl.empty:
            tbl.to_excel(writer, sheet_name="策略成交", index=False)
        else:
            pd.DataFrame([{"说明": "本区间未产生完整买卖回合（无信号或缺少次日K线）"}]).to_excel(
                writer, sheet_name="策略成交", index=False
            )
        summary_df.to_excel(writer, sheet_name="回测摘要", index=False)


def main() -> int:
    _configure_stdio()
    p = argparse.ArgumentParser(description="QMT 5m 放量涨→缩量跌 + 次日MACD死叉 回测")
    p.add_argument("--code", default="002709.SZ")
    p.add_argument("--count", type=int, default=800, help="拉取最近 N 根 5m K")
    p.add_argument(
        "--last-n-sessions",
        type=int,
        default=0,
        dest="last_n_sessions",
        help=">0 时：截取数据中最后 N 个交易日再回测（需先把 --count 拉大以覆盖足够历史）",
    )
    p.add_argument("--download", action="store_true")
    p.add_argument("--userdata", default=None)
    p.add_argument("--n-bull", type=int, default=4, dest="n_bull")
    p.add_argument("--n-bear", type=int, default=4, dest="n_bear")
    p.add_argument("--vol-ma-win", type=int, default=20, dest="vol_ma_win")
    p.add_argument("--vol-hi", type=float, default=1.2, dest="vol_hi", help="放量：段均量 >= 该倍数×前一日vol_ma")
    p.add_argument("--vol-lo", type=float, default=0.88, dest="vol_lo", help="缩量：段均量 <= 该倍数×放量段均量")
    p.add_argument("--bull-ret-min", type=float, default=0.0025, dest="bull_ret_min")
    p.add_argument("--bear-ret-max", type=float, default=-0.0015, dest="bear_ret_max")
    p.add_argument("--macd-fast", type=int, default=12, dest="macd_fast")
    p.add_argument("--macd-slow", type=int, default=26, dest="macd_slow")
    p.add_argument("--macd-signal", type=int, default=9, dest="macd_signal")
    p.add_argument(
        "--entry-macd-bull",
        action="store_true",
        dest="entry_macd_bull",
        help="仅在买入根上 5m DIF>DEA 时保留信号（顺势过滤，默认关闭）",
    )
    p.add_argument(
        "--macd-exit-skip-first-bars",
        type=int,
        default=0,
        dest="macd_exit_skip_first_bars",
        help="次日前 N 根 5m 不参与死叉判定（减轻开盘假死叉；0=关闭；收盘强平仍用当日最后一根）",
    )
    p.add_argument(
        "--daily-phase1",
        action="store_true",
        dest="daily_phase1",
        help="启用阶段1日线过滤（需能拉到日线）；模式见 --daily-phase1-mode",
    )
    p.add_argument(
        "--daily-phase1-mode",
        choices=("soft", "strict"),
        default="soft",
        dest="daily_phase1_mode",
        help="soft=仅昨收>MA20（默认）；strict=再加近几日放量阳线",
    )
    p.add_argument(
        "--daily-lookback-bars",
        type=int,
        default=160,
        dest="daily_lookback_bars",
        help="日线拉取根数（仅 --daily-phase1 时）",
    )
    p.add_argument("--daily-vol-ma-win", type=int, default=20, dest="daily_vol_ma_win")
    p.add_argument(
        "--daily-vol-hi",
        type=float,
        default=1.15,
        dest="daily_vol_hi",
        help="日放量：当日量 >= 该倍数×前一日日量均线",
    )
    p.add_argument("--daily-attack-lookback", type=int, default=5, dest="daily_attack_lookback")
    p.add_argument("--daily-ma20", type=int, default=20, dest="daily_ma20")
    p.add_argument(
        "--buy-mode",
        choices=("yang_after_bear", "bear_last_close"),
        default="yang_after_bear",
        dest="buy_mode",
        help="买入：缩量跌后首根阳线(yang_after_bear，默认) 或 缩量跌末根收盘(bear_last_close)",
    )
    p.add_argument(
        "--yang-max-wait",
        type=int,
        default=48,
        dest="yang_max_wait",
        help="yang_after_bear：缩量跌结束后最多向后看几根5m等阳线",
    )
    p.add_argument(
        "--chart-html",
        default=None,
        help="Plotly HTML 输出路径；默认写入 examples/quick_tests/output/ 下带时间戳文件名",
    )
    p.add_argument("--no-chart", action="store_true", help="不生成 HTML 图表")
    p.add_argument("--name", default="", help="证券简称，用于导出表；不设则尝试内置映射")
    p.add_argument("--lot", type=int, default=100, help="每笔成交股数（买卖同量，用于金额与盈亏元）")
    p.add_argument(
        "--capital",
        type=float,
        default=100_000.0,
        help="展示「累计收益率%%」时的分母本金（元），仅报表用",
    )
    p.add_argument(
        "--commission-bps",
        type=float,
        default=2.5,
        dest="commission_bps",
        help="单边佣金：万分之一为 1.0，万2.5 填 2.5",
    )
    p.add_argument(
        "--trade-prefix",
        default=None,
        help="成交表文件名前缀；默认与图表同目录 qmt_5m_{code}_{timestamp}",
    )
    p.add_argument("--no-trade-export", action="store_true", help="不写 CSV/Markdown 成交表")
    p.add_argument(
        "--xlsx",
        nargs="?",
        const="__AUTO__",
        default=None,
        help="导出 Excel：单独写 --xlsx 则自动生成 output 下文件名；或 --xlsx D:\\path\\a.xlsx",
    )
    args = p.parse_args()

    xtdata = _import_xtdata()
    df = xtdata_fetch_5m(
        xtdata,
        args.code,
        args.count,
        download=args.download,
        userdata=args.userdata,
    )
    if df.empty:
        print("无 5m 数据", file=sys.stderr)
        return 1
    print(f"标的 {args.code} 拉取后 5m 条数={len(df)} 时间范围 {df.index[0]} ~ {df.index[-1]}")
    if args.last_n_sessions > 0:
        df = trim_last_n_trading_sessions(df, args.last_n_sessions)
        if df.empty:
            print("--last-n-sessions 截取后无数据", file=sys.stderr)
            return 1
        ds = sorted({session_date(ts) for ts in df.index})
        print(
            f"截取最近 {args.last_n_sessions} 个交易日回测: 共 {len(df)} 根 5m，"
            f"日期 {ds[0]} ~ {ds[-1]} （共 {len(ds)} 个交易日）"
        )

    bm_note = (
        f"{args.buy_mode}（缩量跌后 {args.yang_max_wait} 根内首根阳线买）"
        if args.buy_mode == "yang_after_bear"
        else f"{args.buy_mode}（缩量跌末根收盘买，旧版）"
    )
    print(f"买入模式: {bm_note}")

    stock_name = (resolve_stock_name(args.code, args.name or None) or "").strip()
    if not stock_name:
        stock_name = (xtdata_stock_name(xtdata, args.code) or "").strip()
    if stock_name:
        print(f"证券简称: {stock_name}")

    df_daily: pd.DataFrame | None = None
    if getattr(args, "daily_phase1", False):
        try:
            n1d = int(getattr(args, "daily_lookback_bars", 160))
            df_daily = xtdata_fetch_1d(
                xtdata,
                args.code,
                n1d,
                download=args.download,
                userdata=args.userdata,
            )
            if df_daily is not None and not df_daily.empty:
                print(
                    f"日线阶段1: 已拉取 {len(df_daily)} 根日K "
                    f"({df_daily.index[0].date()} ~ {df_daily.index[-1].date()})"
                )
            else:
                df_daily = None
                print("日线为空，阶段1过滤跳过", file=sys.stderr)
        except Exception as e:
            df_daily = None
            print(f"日线拉取失败，阶段1过滤跳过: {e}", file=sys.stderr)

    trades = run_backtest_on_df(df, args, df_daily=df_daily)
    if not trades:
        print(
            "未产生完整交易（无信号或缺少「次日」K 线）。仍导出 K 线 Excel/图表（若有）；"
            "可调：--vol-hi / --vol-lo / --bull-ret-min / --bear-ret-max / --count"
        )

    rets = [t.pnl_pct for t in trades]
    compound = float(np.prod([1.0 + r / 100.0 for r in rets]) - 1.0) * 100.0 if rets else 0.0
    mean_ret = float(np.mean(rets)) if rets else None
    sum_ret = float(np.sum(rets)) if rets else None

    slug = args.code.replace(".", "_")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_dir = _REPO / "examples" / "quick_tests" / "output"
    default_dir.mkdir(parents=True, exist_ok=True)
    strat_tag = strategy_filename_tag_cn(args.buy_mode)
    name_fn = safe_filename_part(stock_name or "未命名", 28)
    code_fn = safe_filename_part(slug, 24)
    tag_fn = safe_filename_part(strat_tag, 72)
    file_stem = safe_filename_part(f"{name_fn}_{code_fn}_{tag_fn}_{stamp}", 160)
    prefix = args.trade_prefix or str(default_dir / file_stem)
    prefix_path = Path(prefix)
    csv_path = prefix_path.parent / f"{prefix_path.name}_trades.csv"
    md_path = prefix_path.parent / f"{prefix_path.name}_trades.md"

    tbl: pd.DataFrame | None = None
    if trades and not args.no_trade_export:
        tbl = build_execution_table(
            trades,
            ts_code=args.code,
            stock_name=stock_name,
            lot=args.lot,
            commission_bps=args.commission_bps,
            capital=args.capital,
        )
        print("\n=== 成交汇总表（类 QMT）===")
        print_execution_table(tbl)
        write_trade_report(
            trades,
            tbl,
            ts_code=args.code,
            stock_name=stock_name,
            lot=args.lot,
            capital=args.capital,
            commission_bps=args.commission_bps,
            csv_path=csv_path,
            md_path=md_path,
        )
        print(f"\n成交 CSV: {csv_path.resolve()}")
        print(f"成交 Markdown（含每笔文字明细）: {md_path.resolve()}")

    if trades:
        print("\n=== 轮次摘要（与图表一致）===")
        for i, t in enumerate(trades, 1):
            print(
                f"{i}. 买 {t.entry_time} @ {t.entry_price:.3f}  "
                f"卖 {t.exit_time} @ {t.exit_price:.3f}  "
                f"收益 {t.pnl_pct:+.2f}%  ({t.exit_reason})"
            )
        print(f"\n笔数={len(trades)} 平均单笔={mean_ret:+.2f}% 算术累加={sum_ret:+.2f}%")
        print(f"全仓复利净值（连乘）={compound:+.2f}%  （假设每笔平仓后全额滚入下一笔）")

    if args.xlsx is not None:
        xlsx_arg = args.xlsx
        xlsx_path = (
            default_dir / f"{file_stem}.xlsx"
            if xlsx_arg == "__AUTO__"
            else Path(xlsx_arg)
        )
        try:
            write_excel_pack(
                df,
                trades,
                tbl,
                xlsx_path,
                ts_code=args.code,
                stock_name=stock_name,
                compound_pct=compound,
                mean_ret=mean_ret,
                sum_ret=sum_ret,
                lot=args.lot,
                capital=args.capital,
                commission_bps=args.commission_bps,
                buy_mode=args.buy_mode,
                yang_max_wait=args.yang_max_wait,
            )
            print(f"\nExcel 已写入: {xlsx_path.resolve()}")
        except ImportError as e:
            print(f"\n{e}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"\n写 Excel 失败: {e}", file=sys.stderr)
            return 1

    if not args.no_chart:
        chart_path = Path(args.chart_html) if args.chart_html else default_dir / f"{file_stem}.html"
        try:
            write_chart_html(
                df,
                trades,
                code=args.code,
                compound_pct=compound,
                out_path=chart_path,
                title="5m 放量涨→缩量跌 / 次日MACD死叉",
                stock_name=stock_name,
            )
            print(f"\n图表已写入: {chart_path.resolve()}")
        except ImportError:
            print("\n未安装 plotly，跳过图表。请执行: pip install plotly>=6", file=sys.stderr)
        except Exception as e:
            print(f"\n写图表失败: {e}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
