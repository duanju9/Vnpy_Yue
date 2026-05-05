# -*- coding: utf-8 -*-
"""
双均线 CTA 回测：复用 ``vnpy_ctastrategy`` 的 ``BacktestingEngine``，不重复造轮子。

策略类：``vnpy_ctastrategy.strategies.close_signal_next_open_strategy.CloseSignalNextOpenStrategy``
（收盘快慢线比较 → 金叉/死叉；委托价配合回测引擎，**下一根 K 线开盘价**成交，见该文件头注释）。

数据流：小龙虾日线 ``vnpy.feeds.fetch_daily_cached`` → 转 ``BarData`` → 写入**独立** SQLite
（默认 ``examples/quick_tests/cta_bt_workspace/cta_bt.sqlite``），再 ``engine.load_data()``。

与「Station 里 CTA 回测界面」差在哪里：
    - **CtaBacktester 图形界面**（``vnpy_ctabacktester``）：委托/成交/每日盈亏表格 + **K 线图上**
      开平仓箭头、盈亏虚线、手数文字（``CandleChartDialog``），信息最全。
    - **本脚本默认**：终端统计 + JSON；``engine.show_chart()`` 只有资金/回撤/日盈亏（**没有** K 线叠加成交）。
    - **``dual_ma_smoketest.py`` 的 Plotly**：投研烟雾图，买卖点与 CTA **撮合价/滑点**不一致，仅便于扫一眼。

增强：加 ``--qt-chart`` 直接弹出与界面同源的 ``CandleChartDialog``；默认另存 ``*_trades.csv`` 成交明细。

安装：
    pip install -i https://pypi.tuna.tsinghua.edu.cn/simple vnpy_ctastrategy vnpy_ctabacktester vnpy_sqlite

用法：
    cd d:\\Vnpy\\Vnpy_Yue
    python examples/quick_tests/run_dual_ma_cta_backtest.py --ts_code 002460.SZ --use-cache \\
        --fast 10 --slow 30 --start_date 20240101 --rate 0.0003 --slippage 0.01
    python examples/quick_tests/run_dual_ma_cta_backtest.py --ts_code 002709.SZ --use-cache \\
        --fast 10 --slow 30 --start_date 20240101 --qt-chart
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

if sys.platform == "win32" and isinstance(sys.stdout, io.TextIOWrapper):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vnpy.feeds import (  # noqa: E402
    daily_tushare_ohlc_df_to_bars,
    fetch_daily_cached,
    get_pro_throttled,
    tushare_ts_code_to_vt_symbol,
)
from vnpy.trader.constant import Interval  # noqa: E402
from vnpy.trader.database import get_database  # noqa: E402
from vnpy.trader.object import TradeData  # noqa: E402
from vnpy.trader.utility import extract_vt_symbol  # noqa: E402

try:
    from vnpy_ctastrategy.backtesting import BacktestingEngine, load_bar_data
except ImportError as e:
    raise SystemExit(
        "请先安装: pip install -i https://pypi.tuna.tsinghua.edu.cn/simple "
        "vnpy_ctastrategy vnpy_ctabacktester vnpy_sqlite\n"
        f"原始错误: {e}"
    ) from e


def sanitize_filename(name: str, *, max_len: int = 32) -> str:
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name.strip())
    return (s.strip(" .") or "未命名")[:max_len]


def fetch_stock_basic_name(ts_code: str, pro: object) -> str:
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
    fast: int,
    slow: int,
    stamp: str,
) -> str:
    return (
        f"{sanitize_filename(stock_name or '未命名')}_"
        f"{ts_code.replace('.', '_')}_{sanitize_filename(strategy_name, max_len=12)}_"
        f"CTA_MA{fast}-{slow}_{stamp}"
    )


def configure_isolated_sqlite(db_path: Path) -> None:
    """将 VeighNa 全局库指向独立文件，避免污染用户主 ``database.db``。"""
    from vnpy.trader import setting
    import vnpy.trader.database as vndb

    db_path.parent.mkdir(parents=True, exist_ok=True)
    setting.SETTINGS["database.name"] = "sqlite"
    setting.SETTINGS["database.database"] = str(db_path.resolve())
    vndb.database = None


def fetch_daily_for_script(
    ts_code: str,
    start_date: str,
    end_date: str,
    *,
    use_cache: bool,
) -> pd.DataFrame:
    if use_cache:
        df = fetch_daily_cached(ts_code, start_date, end_date)
    else:
        pro = get_pro_throttled()
        raw = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
        if raw is None or raw.empty:
            raise RuntimeError(f"未取到 {ts_code} 日线")
        df = raw.sort_values("trade_date").reset_index(drop=True)
    out = df.copy()
    td = out["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]
    out["trade_date"] = pd.to_datetime(td, format="%Y%m%d")
    return out


def export_trades_csv(trades: dict[str, TradeData], path: Path) -> None:
    """逐笔成交导出（与 CTA 回测界面「成交记录」列同源）。"""
    if not trades:
        path.write_text("", encoding="utf-8-sig")
        return
    rows: list[dict[str, object]] = []
    for t in sorted(trades.values(), key=lambda x: x.datetime or datetime.min):
        rows.append(
            {
                "datetime": t.datetime,
                "vt_tradeid": t.vt_tradeid,
                "vt_symbol": t.vt_symbol,
                "direction": t.direction.value if t.direction else "",
                "offset": t.offset.value,
                "price": t.price,
                "volume": t.volume,
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def launch_cta_candle_chart(engine: BacktestingEngine) -> None:
    """复用 ``vnpy_ctabacktester`` 的 ``CandleChartDialog``（与 Station「K线图表」同源逻辑）。"""
    from vnpy.trader.ui import create_qapp
    from vnpy_ctabacktester.ui.widget import CandleChartDialog

    app = create_qapp()
    dlg = CandleChartDialog()
    history = list(engine.history_data)
    trade_list = list(engine.trades.values())
    dlg.clear_data()
    dlg.update_history(history)
    dlg.update_trades(trade_list)
    dlg.showMaximized()
    app.exec()


def main() -> None:
    ap = argparse.ArgumentParser(description="双均线 CTA 回测（vnpy_ctastrategy 引擎 + CloseSignalNextOpenStrategy）")
    ap.add_argument("--ts_code", default="002460.SZ")
    ap.add_argument("--start_date", default="20240101", help="回测区间起点 YYYYMMDD")
    ap.add_argument("--end_date", default="", help="回测区间终点，默认今天")
    ap.add_argument("--fast", type=int, default=10, dest="fast_window")
    ap.add_argument("--slow", type=int, default=30, dest="slow_window")
    ap.add_argument("--volume", type=int, default=100, help="每次交易股数（一手=100）")
    ap.add_argument("--capital", type=int, default=1_000_000)
    ap.add_argument("--rate", type=float, default=0.0003, help="手续费率（按成交额）")
    ap.add_argument("--slippage", type=float, default=0.01, help="滑点（回测引擎定义：见 vnpy_ctastrategy.backtesting）")
    ap.add_argument("--size", type=float, default=1.0, help="合约乘数，股票按股数一般为 1")
    ap.add_argument("--pricetick", type=float, default=0.01)
    ap.add_argument("--use-cache", action="store_true")
    ap.add_argument("--no-stock-name", action="store_true")
    ap.add_argument("--strategy-name", default="双均线")
    ap.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="独立 Sqlite 路径，默认 examples/quick_tests/cta_bt_workspace/cta_bt.sqlite",
    )
    ap.add_argument("--save-chart-html", type=Path, default=None, help="可选：保存 CTA 引擎自带 Plotly 图表 HTML")
    ap.add_argument(
        "--qt-chart",
        action="store_true",
        help="回测结束后弹出与 CtaBacktester 一致的 K 线+成交标注窗口（需图形界面）",
    )
    ap.add_argument(
        "--no-trades-csv",
        action="store_true",
        help="不写出成交明细 CSV（默认与 JSON 同目录同前缀 _trades.csv）",
    )
    ap.add_argument("--margin-calendar-days", type=int, default=400, help="起点前多取自然日，供策略 load_bar 预热")
    args = ap.parse_args()

    end_s = args.end_date.strip() or datetime.now().strftime("%Y%m%d")
    user_start = datetime.strptime(args.start_date, "%Y%m%d")
    user_end = datetime.strptime(end_s, "%Y%m%d").replace(hour=23, minute=59, second=59)

    fetch_start = (pd.Timestamp(user_start) - pd.Timedelta(days=args.margin_calendar_days)).strftime("%Y%m%d")

    ws = Path(__file__).resolve().parent / "cta_bt_workspace"
    db_path = args.db_path if args.db_path is not None else ws / "cta_bt.sqlite"
    configure_isolated_sqlite(db_path)

    pro = get_pro_throttled()
    stock_name = ""
    if not args.no_stock_name:
        print("[1/5] stock_basic 查询简称...")
        stock_name = fetch_stock_basic_name(args.ts_code, pro)
        print(f"      → {stock_name or '（空）'}")
    else:
        print("[1/5] 已跳过简称（--no-stock-name）")

    print(f"[2/5] 拉取日线 {fetch_start} ~ {end_s}（含预热）...")
    raw = fetch_daily_for_script(args.ts_code, fetch_start, end_s, use_cache=args.use_cache)
    print(f"      共 {len(raw)} 根")

    vt_symbol = tushare_ts_code_to_vt_symbol(args.ts_code)
    symbol, exchange = extract_vt_symbol(vt_symbol)
    bars = daily_tushare_ohlc_df_to_bars(raw, args.ts_code, gateway_name="DB")

    print("[3/5] 写入独立 SQLite K 线（日线）...")
    db = get_database()
    db.delete_bar_data(symbol, exchange, Interval.DAILY)
    db.save_bar_data(bars, stream=False)

    load_bar_data.cache_clear()

    from vnpy_ctastrategy.strategies.close_signal_next_open_strategy import (
        CloseSignalNextOpenStrategy,
    )

    setting_dict = {
        "fast_window": args.fast_window,
        "slow_window": args.slow_window,
        "fixed_volume": args.volume,
    }

    print("[4/5] CTA BacktestingEngine 回放...")
    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbol=vt_symbol,
        interval=Interval.DAILY,
        start=user_start,
        end=user_end,
        rate=args.rate,
        slippage=args.slippage,
        size=args.size,
        pricetick=args.pricetick,
        capital=args.capital,
    )
    engine.add_strategy(CloseSignalNextOpenStrategy, setting_dict)
    engine.load_data()
    engine.run_backtesting()
    engine.calculate_result()
    stats = engine.calculate_statistics(output=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = make_export_basename(
        stock_name, args.ts_code, args.strategy_name, args.fast_window, args.slow_window, stamp
    )
    out_dir = Path(__file__).resolve().parent / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{base}.json"
    meta = {
        "engine": "vnpy_ctastrategy.backtesting.BacktestingEngine",
        "strategy": "CloseSignalNextOpenStrategy",
        "vt_symbol": vt_symbol,
        "ts_code": args.ts_code,
        "stock_name": stock_name,
        "sqlite": str(db_path),
        "statistics": stats,
    }
    json_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n[5/5] 摘要 JSON → {json_path}")

    if not args.no_trades_csv:
        trades_path = out_dir / f"{base}_trades.csv"
        export_trades_csv(engine.trades, trades_path)
        print(f"成交明细 CSV → {trades_path}")

    if args.save_chart_html:
        fig = engine.show_chart()
        if fig is not None:
            fig.write_html(args.save_chart_html, include_plotlyjs=True)
            print(f"Plotly 资金/回撤图 → {args.save_chart_html}")

    if args.qt_chart:
        print("打开 K 线+成交标注窗口（与 CtaBacktester「K线图表」同源，关闭后结束）...")
        launch_cta_candle_chart(engine)


if __name__ == "__main__":
    main()
