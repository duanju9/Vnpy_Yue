# -*- coding: utf-8 -*-
"""
双均线策略烟雾测试（基于小龙虾 Tushare 代理日线）

目的：
    打通「数据接入 → 信号 → 回测 → 出图」整条链路，作为后续接入
    缠论 / 多因子 / Alpha 模块时的基线模板。

用法：
    cd d:\\Vnpy\\Vnpy_Yue
    python examples/quick_tests/dual_ma_smoketest.py
    python examples/quick_tests/dual_ma_smoketest.py --ts_code 002460.SZ --short 10 --long 30 --use-cache
    python examples/quick_tests/dual_ma_smoketest.py --ts_code 002460.SZ --use-cache \\
        --price-add 0.0005 --open-commission 0.00025 --close-commission 0.00025
    python examples/quick_tests/dual_ma_smoketest.py --ts_code 002460.SZ --use-cache --qt-chart

约束：
    - Token 走 examples/.env 中的 TSY_TOKEN，**不在代码里硬编码**
    - 全局限速由 ``vnpy.feeds.get_pro_throttled()`` 处理；加 ``--use-cache`` 时走
      ``vnpy.feeds.fetch_daily_cached``（Parquet + SQLite 元数据，见 docs/dev_log）
    - 仓位由前一日均线信号决定（无未来函数）；收益按收盘价涨跌近似（非 CTA 引擎撮合）
    - 费用参数与 ``vnpy.alpha.strategy.template.AlphaStrategy.execute_trading`` 中
      ``price_add``（报单价相对收盘价偏移比例）及 ``EquityDemoStrategy`` 的开/平佣金思路一致，
      按换仓日扣减（烟雾级近似）。**正式 CTA 撮合/统计**请用
      ``examples/quick_tests/run_dual_ma_cta_backtest.py``（``vnpy_ctastrategy.BacktestingEngine``）。
    - 输出 HTML/JSON 文件名含**股票中文名 + 策略名 + MA 参数**，便于辨认。
    - 可选 ``--qt-chart``：弹出 ``vnpy.chart.ChartWidget`` 原生 K 线（PySide6 + pyqtgraph）。
    - HTML 默认内嵌 plotly.js（可离线打开）；若需小文件可加 ``--plotly-cdn``（依赖外网 CDN）
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Windows 终端默认 GBK，强制 UTF-8 避免中文打印乱码
if sys.platform == "win32" and isinstance(sys.stdout, io.TextIOWrapper):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[2]                # d:\Vnpy\Vnpy_Yue
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vnpy.feeds import (  # noqa: E402
    daily_tushare_ohlc_df_to_bars,
    fetch_daily_cached,
    get_pro_throttled,
)


def sanitize_filename(name: str, *, max_len: int = 32) -> str:
    """去掉 Windows 非法字符，缩短文件名。"""
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name.strip())
    s = s.strip(" .") or "未命名"
    return s[:max_len]


def fetch_stock_basic_name(ts_code: str, pro: Any) -> str:
    """``stock_basic`` 查中文简称（一次限速请求）。"""
    try:
        df = pro.stock_basic(ts_code=ts_code, fields="ts_code,name")
    except Exception:
        return ""
    if df is None or df.empty or "name" not in df.columns:
        return ""
    return str(df.iloc[0]["name"]).strip()


def make_export_basename(
    stock_name: str,
    ts_code: str,
    strategy_name: str,
    short: int,
    long_: int,
    stamp: str,
) -> str:
    """例如：赣锋锂业_002460_SZ_双均线_MA10-30_20260505_231024"""
    part_name = sanitize_filename(stock_name or "未命名")
    part_ts = ts_code.replace(".", "_")
    part_strat = sanitize_filename(strategy_name.replace(" ", ""), max_len=16)
    return f"{part_name}_{part_ts}_{part_strat}_MA{short}-{long_}_{stamp}"


def launch_qt_candle_chart(df: pd.DataFrame, ts_code: str, window_title: str) -> None:
    """使用 vnpy 原生 ``ChartWidget``（与 ``examples/candle_chart/run.py`` 同源）。"""
    from vnpy.chart import CandleItem, ChartWidget, VolumeItem
    from vnpy.trader.ui import create_qapp

    app = create_qapp()
    widget = ChartWidget()
    widget.setWindowTitle(window_title)
    widget.add_plot("candle", hide_x_axis=True)
    widget.add_plot("volume", maximum_height=200)
    widget.add_item(CandleItem, "candle", "candle")
    widget.add_item(VolumeItem, "volume", "volume")
    widget.add_cursor()
    history = daily_tushare_ohlc_df_to_bars(df, ts_code, gateway_name="BACKTEST")
    widget.update_history(history)
    widget.showMaximized()
    app.exec()


@dataclass
class BacktestResult:
    """单次回测结果"""
    ts_code: str
    short_window: int
    long_window: int
    start_date: str
    end_date: str
    bars: int
    trades: int
    win_rate: float
    total_return: float                # 策略累计收益（%）
    annual_return: float               # 年化收益（%）
    max_drawdown: float                # 最大回撤（%）
    sharpe: float
    buy_and_hold_return: float         # 买入持有累计收益（%）
    excess_return: float               # 超额（策略 - 买入持有）
    stock_name: str = ""
    strategy_name: str = "双均线"
    price_add: float = 0.0             # 与 Alpha 模板一致：换仓日额外扣减（买+卖各计一次）
    open_commission: float = 0.0       # 开多当日扣减比例
    close_commission: float = 0.0    # 平多当日扣减比例


def fetch_daily(
    ts_code: str,
    start_date: str,
    end_date: str,
    *,
    use_cache: bool,
) -> pd.DataFrame:
    """通过小龙虾代理拉日线（已限速）；``use_cache`` 时写入 ``data/vnpy_yue`` Parquet。"""
    if use_cache:
        df = fetch_daily_cached(ts_code, start_date, end_date)
    else:
        pro = get_pro_throttled()
        raw = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
        if raw is None or raw.empty:
            raise RuntimeError(f"未取到 {ts_code} 的日线，请检查代码 / 权限 / 限速冷却")
        df = raw.sort_values("trade_date").reset_index(drop=True)
    df = df.copy()
    td = df["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]
    df["trade_date"] = pd.to_datetime(td, format="%Y%m%d")
    return df


def run_dual_ma(
    df: pd.DataFrame,
    short: int,
    long_: int,
    *,
    ts_code: str = "",
    stock_name: str = "",
    strategy_name: str = "双均线",
    price_add: float = 0.0,
    open_commission: float = 0.0,
    close_commission: float = 0.0,
) -> tuple[pd.DataFrame, BacktestResult]:
    """
    双均线：短均 > 长均则满仓，否则空仓；仓位 = 昨日信号。

    费用：换仓日扣减 —— 与 ``AlphaStrategy.execute_trading`` 中 ``price_add`` 及
    ``EquityDemoStrategy`` 开/平费率同语义（按**全仓名义**比例一次扣减，烟雾近似）。
    """
    df = df.copy()
    df["ma_s"] = df["close"].rolling(short).mean()
    df["ma_l"] = df["close"].rolling(long_).mean()

    # 1 表示当日收盘后判定的「目标持仓」（短均上穿长均=持有），下一日开盘按此调整
    df["signal"] = (df["ma_s"] > df["ma_l"]).astype(int)
    # 实际仓位是上一日信号决定的（避免未来函数）
    df["position"] = df["signal"].shift(1).fillna(0).astype(int)

    df["close_ret"] = df["close"].pct_change().fillna(0)
    pos = df["position"].astype(float)
    chg = pos.diff().fillna(0.0)
    n = len(df)
    fee = np.zeros(n, dtype=float)
    fee = np.where(chg > 0, open_commission + price_add, fee)
    fee = np.where(chg < 0, close_commission + price_add, fee)
    df["fee_drag"] = fee
    df["strategy_ret"] = pos * df["close_ret"] - df["fee_drag"]

    df["nav_strategy"] = (1 + df["strategy_ret"]).cumprod()
    df["nav_buy_hold"] = (1 + df["close_ret"]).cumprod()

    # 交易笔数（持仓状态变化数 / 2 取整向上，进+出算两次状态变化）
    state_change = df["position"].diff().abs().fillna(0)
    trades = int(state_change.sum())                                  # 单边换仓次数（开+平=2）
    round_trips = trades // 2

    # 胜率：以每次完整开仓→平仓为单位
    wins = 0
    completed = 0
    entry_price: float | None = None
    for _, row in df.iterrows():
        if row["position"] == 1 and entry_price is None:
            entry_price = row["close"]
        elif row["position"] == 0 and entry_price is not None:
            completed += 1
            if row["close"] > entry_price:
                wins += 1
            entry_price = None
    win_rate = (wins / completed) if completed else 0.0

    total_return = float(df["nav_strategy"].iloc[-1] - 1)
    bh_return = float(df["nav_buy_hold"].iloc[-1] - 1)
    days = (df["trade_date"].iloc[-1] - df["trade_date"].iloc[0]).days or 1
    years = days / 365.25
    annual_return = float((1 + total_return) ** (1 / years) - 1) if years > 0 else 0.0

    # 最大回撤
    nav = df["nav_strategy"].values
    peak = np.maximum.accumulate(nav)
    dd = (nav - peak) / peak
    max_dd = float(dd.min())

    # 夏普（年化，假设无风险利率为 0，使用日频年化系数 252）
    daily = df["strategy_ret"].values
    if daily.std() > 0:
        sharpe = float((daily.mean() / daily.std()) * np.sqrt(252))
    else:
        sharpe = 0.0

    code = ts_code or (str(df["ts_code"].iloc[0]) if "ts_code" in df.columns else "")
    result = BacktestResult(
        ts_code=code,
        short_window=short,
        long_window=long_,
        start_date=df["trade_date"].iloc[0].strftime("%Y-%m-%d"),
        end_date=df["trade_date"].iloc[-1].strftime("%Y-%m-%d"),
        bars=int(len(df)),
        trades=round_trips,
        win_rate=round(win_rate * 100, 2),
        total_return=round(total_return * 100, 2),
        annual_return=round(annual_return * 100, 2),
        max_drawdown=round(max_dd * 100, 2),
        sharpe=round(sharpe, 3),
        buy_and_hold_return=round(bh_return * 100, 2),
        excess_return=round((total_return - bh_return) * 100, 2),
        stock_name=stock_name,
        strategy_name=strategy_name,
        price_add=price_add,
        open_commission=open_commission,
        close_commission=close_commission,
    )
    return df, result


def render_html(
    df: pd.DataFrame,
    result: BacktestResult,
    out_path: Path,
    *,
    plotly_cdn: bool = False,
) -> None:
    """生成 K线 + 双均线 + 买卖点 + 净值曲线 的 Plotly HTML"""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.65, 0.35], vertical_spacing=0.04,
        subplot_titles=("K线 + 双均线 + 买卖点", "净值曲线（策略 vs 买入持有）"),
    )

    fig.add_trace(
        go.Candlestick(
            x=df["trade_date"], open=df["open"], high=df["high"],
            low=df["low"], close=df["close"], name="K线",
            increasing_line_color="#d83a3a", decreasing_line_color="#2eb872",
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(x=df["trade_date"], y=df["ma_s"], name=f"MA{result.short_window}",
                   line=dict(color="#f0b400", width=1.4)),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(x=df["trade_date"], y=df["ma_l"], name=f"MA{result.long_window}",
                   line=dict(color="#3a7bd5", width=1.4)),
        row=1, col=1,
    )

    pos_diff = df["position"].diff().fillna(0)
    buys = df[pos_diff == 1]
    sells = df[pos_diff == -1]
    fig.add_trace(
        go.Scatter(x=buys["trade_date"], y=buys["open"], mode="markers", name="买入",
                   marker=dict(symbol="triangle-up", size=11, color="#d83a3a")),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(x=sells["trade_date"], y=sells["open"], mode="markers", name="卖出",
                   marker=dict(symbol="triangle-down", size=11, color="#2eb872")),
        row=1, col=1,
    )

    fig.add_trace(
        go.Scatter(x=df["trade_date"], y=df["nav_strategy"], name="策略净值",
                   line=dict(color="#d83a3a", width=1.6)),
        row=2, col=1,
    )
    fig.add_trace(
        go.Scatter(x=df["trade_date"], y=df["nav_buy_hold"], name="买入持有净值",
                   line=dict(color="#888888", width=1.4, dash="dot")),
        row=2, col=1,
    )

    fee_hint = ""
    if result.price_add or result.open_commission or result.close_commission:
        fee_hint = (
            f" | 费用近似: price_add={result.price_add:g} "
            f"open={result.open_commission:g} close={result.close_commission:g}"
        )
    name_part = f"{result.stock_name} " if result.stock_name else ""
    fig.update_layout(
        title=(
            f"{result.strategy_name} | {name_part}{result.ts_code} | "
            f"{result.start_date} ~ {result.end_date} | "
            f"MA{result.short_window}/{result.long_window} | "
            f"策略 {result.total_return:+.2f}% (B&H {result.buy_and_hold_return:+.2f}%) | "
            f"年化 {result.annual_return:+.2f}% | MDD {result.max_drawdown:.2f}% | "
            f"Sharpe {result.sharpe} | 交易 {result.trades} 次 | 胜率 {result.win_rate}%"
            f"{fee_hint}"
        ),
        xaxis_rangeslider_visible=False,
        template="plotly_white",
        height=820,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=20, t=80, b=40),
    )
    # 默认内嵌 plotly.js，避免依赖 cdn.plot.ly（国内常打不开或长时间空白）
    js_mode: bool | str = "cdn" if plotly_cdn else True
    fig.write_html(out_path, include_plotlyjs=js_mode)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ts_code", default="002709.SZ", help="Tushare 代码，如 002709.SZ / 600519.SH")
    parser.add_argument("--start_date", default="20240101")
    parser.add_argument("--end_date", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--short", type=int, default=5)
    parser.add_argument("--long", type=int, default=20, dest="long_")
    parser.add_argument("--strategy-name", default="双均线", help="导出文件名与图表标题中的策略名")
    parser.add_argument(
        "--no-stock-name",
        action="store_true",
        help="不调用 stock_basic（省一次请求）；文件名用「未命名」",
    )
    parser.add_argument(
        "--price-add",
        type=float,
        default=0.0,
        help="报单价偏移比例，与 Alpha execute_trading 的 price_add 同语义；换仓日扣减",
    )
    parser.add_argument(
        "--open-commission",
        type=float,
        default=0.0,
        help="开多当日按全仓名义扣减的比例（如万2.5 填 0.00025）",
    )
    parser.add_argument(
        "--close-commission",
        type=float,
        default=0.0,
        help="平多当日按全仓名义扣减的比例",
    )
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="使用 vnpy.feeds 本地 Parquet + manifest.sqlite 缓存（二次同区间请求可零网络）",
    )
    parser.add_argument(
        "--plotly-cdn",
        action="store_true",
        help="HTML 使用 plotly CDN（文件小；国内/离线环境易空白，默认关闭）",
    )
    parser.add_argument(
        "--qt-chart",
        action="store_true",
        help="回测结束后弹出 vnpy 原生 ChartWidget（K线+成交量），需图形界面",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    pro = get_pro_throttled()
    stock_name = ""
    if not args.no_stock_name:
        print("[1/4] 查询证券简称（stock_basic，一次限速请求）...")
        stock_name = fetch_stock_basic_name(args.ts_code, pro)
        if stock_name:
            print(f"      → {stock_name}")
        else:
            print("      → 未取到简称，文件名中用「未命名」")
    else:
        print("[1/4] 已跳过简称查询（--no-stock-name）")

    mode = "缓存优先" if args.use_cache else "直连"
    print(f"[2/4] 拉取日线 ({mode}) {args.ts_code} {args.start_date}~{args.end_date} ...")
    raw = fetch_daily(args.ts_code, args.start_date, args.end_date, use_cache=args.use_cache)
    print(f"      共 {len(raw)} 根日线，最近收盘 {raw['close'].iloc[-1]} ({raw['trade_date'].iloc[-1].date()})")

    print(f"[3/4] 跑 {args.strategy_name} MA{args.short}/MA{args.long_} ...")
    df, result = run_dual_ma(
        raw,
        args.short,
        args.long_,
        ts_code=args.ts_code,
        stock_name=stock_name,
        strategy_name=args.strategy_name,
        price_add=args.price_add,
        open_commission=args.open_commission,
        close_commission=args.close_commission,
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = make_export_basename(
        stock_name or "未命名",
        args.ts_code,
        args.strategy_name,
        args.short,
        args.long_,
        stamp,
    )
    html_path = OUTPUT_DIR / f"{base}.html"
    json_path = OUTPUT_DIR / f"{base}.json"

    print(f"[4/4] 生成报表 {html_path.name} ...")
    render_html(df, result, html_path, plotly_cdn=args.plotly_cdn)
    json_path.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== 回测摘要 ===")
    for k, v in asdict(result).items():
        print(f"{k:>22}: {v}")
    print(f"\nHTML 报告 → {html_path}")
    print(f"JSON 摘要 → {json_path}")

    if args.qt_chart:
        print("启动 vnpy 原生 K 线窗口（关闭窗口后程序结束）...")
        title = f"{stock_name or args.ts_code} {args.strategy_name} MA{args.short}-{args.long_}"
        launch_qt_candle_chart(raw, args.ts_code, title)


if __name__ == "__main__":
    main()
