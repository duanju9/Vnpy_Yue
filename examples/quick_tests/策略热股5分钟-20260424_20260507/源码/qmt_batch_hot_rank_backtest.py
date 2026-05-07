# -*- coding: utf-8 -*-
"""
批量：热度榜 Top N × 最近若干交易日 5m 策略回测（复用 ``qmt_5m_vol_pullback_macd_backtest`` 逻辑）。

热度股票来源（重要）
--------------------
**同花顺 App 官方热榜**无稳定、免积分的公开 HTTP 接口；本脚本默认使用 **东方财富「个股人气榜」**
（与 AKShare ``stock_hot_rank_em`` 同源接口）作为 **A 股人气 Top100 的 proxy**，便于批量跑通。

若你已有 **Tushare ``ths_hot``** 等高积分接口，可自行导出 CSV（列含 ``ts_code`` 或 ``SH600000`` 风格代码），再用::

    python examples/quick_tests/qmt_batch_hot_rank_backtest.py --rank-csv path/to.csv --rank-col ts_code

依赖：miniQMT + xtquant、``requests``、``pandas``、``openpyxl``（写汇总 Excel）。

用法::

    python examples/quick_tests/qmt_batch_hot_rank_backtest.py --last-n-sessions 5 --download --top 100
    python examples/quick_tests/qmt_batch_hot_rank_backtest.py --last-n-sessions 5 --top 20 --no-download

THS 人气 CSV 批次的说明、回测结果与结论见::
    examples/quick_tests/study_batch_ths_hot_top100_20260424_20260507/说明与结论.md
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import ssl
import sys
import urllib.error
import urllib.request
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
_QT_DIR = Path(__file__).resolve().parent
if str(_QT_DIR) not in sys.path:
    sys.path.insert(0, str(_QT_DIR))
from backtest_recorder import append_backtest_jsonl


def _configure_stdio() -> None:
    if sys.platform == "win32" and isinstance(sys.stdout, io.TextIOWrapper):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _load_qm_module():
    path = _REPO / "examples" / "quick_tests" / "qmt_5m_vol_pullback_macd_backtest.py"
    spec = importlib.util.spec_from_file_location("qmt_5m_bt", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 qmt_5m_vol_pullback_macd_backtest.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def em_sc_to_ts_code(sc: str) -> str:
    """东财 ``sc`` 如 ``SH600519`` / ``SZ000537`` → ``600519.SH`` / ``000537.SZ``。"""
    sc = str(sc).strip().upper()
    if sc.startswith("SH") and len(sc) > 2:
        return f"{sc[2:]}.SH"
    if sc.startswith("SZ") and len(sc) > 2:
        return f"{sc[2:]}.SZ"
    if sc.startswith("BJ") and len(sc) > 2:
        return f"{sc[2:]}.BJ"
    return sc


def _fetch_em_hot_json(url: str, payload: dict, headers: dict) -> dict:
    """先 ``requests``，失败再用 ``urllib`` + 跳过证书校验（部分网络/代理环境 SSL 握手异常）。"""
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=45, verify=True)
        r.raise_for_status()
        return r.json()
    except (requests.exceptions.SSLError, requests.exceptions.RequestException):
        pass
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=45, verify=False)
        r.raise_for_status()
        return r.json()
    except (requests.exceptions.SSLError, requests.exceptions.RequestException):
        pass
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(f"东财人气榜 HTTP 失败: {e}") from e


def fetch_em_hot_rank_top(*, page_size: int = 100) -> pd.DataFrame:
    """
    东方财富个股人气榜当前列表（仅排名与代码，与 AKShare ``stock_hot_rank_em`` 第一步同源）。
    """
    url = "https://emappdata.eastmoney.com/stockrank/getAllCurrentList"
    payload = {
        "appId": "appId01",
        "globalId": "786e4c21-70dc-435a-93bb-38",
        "marketType": "",
        "pageNo": 1,
        "pageSize": int(page_size),
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/json",
    }
    js = _fetch_em_hot_json(url, payload, headers)
    rows = js.get("data") or []
    if not rows:
        raise RuntimeError("人气榜接口返回空 data")
    df = pd.DataFrame(rows)
    if "sc" not in df.columns or "rk" not in df.columns:
        raise RuntimeError(f"人气榜字段异常: {df.columns.tolist()}")
    out = pd.DataFrame(
        {
            "rank": pd.to_numeric(df["rk"], errors="coerce"),
            "sc": df["sc"].astype(str),
        }
    )
    out["ts_code"] = out["sc"].map(em_sc_to_ts_code)
    out["cn_name"] = ""
    for cand in ("nm", "name", "stockName", "secName", "SECURITY_NAME"):
        if cand in df.columns:
            out["cn_name"] = df[cand].astype(str).str.strip().values
            break
    return out.sort_values("rank").reset_index(drop=True)


def load_rank_from_csv(path: Path, col: str) -> pd.DataFrame:
    raw = pd.read_csv(path, encoding="utf-8-sig")
    if col not in raw.columns:
        raise ValueError(f"CSV 无列 {col!r}，现有: {raw.columns.tolist()}")
    name_col = next(
        (c for c in ("cn_name", "股票名称", "证券名称", "name", "证券简称") if c in raw.columns),
        None,
    )
    use_csv_rank = "rank" in raw.columns
    rows_out: list[dict[str, Any]] = []
    for _, row in raw.iterrows():
        x = str(row[col]).strip()
        if ".SH" in x or ".SZ" in x or ".BJ" in x:
            ts_code = x
        else:
            ts_code = em_sc_to_ts_code(x)
        rec: dict[str, Any] = {"ts_code": ts_code}
        if use_csv_rank:
            rec["rank"] = row["rank"]
        if name_col:
            rec["cn_name"] = str(row.get(name_col, "") or "").strip()
        for extra in ("热度区间", "核心题材"):
            if extra in raw.columns:
                rec[extra] = str(row.get(extra, "") or "").strip()
        rows_out.append(rec)
    out = pd.DataFrame(rows_out)
    if "rank" not in out.columns:
        out["rank"] = range(1, len(out) + 1)
    else:
        out["rank"] = pd.to_numeric(out["rank"], errors="coerce")
    if name_col is None:
        out["cn_name"] = ""
    return out


def build_bt_namespace(p: argparse.Namespace) -> Namespace:
    """与单标的脚本一致的策略参数子集。"""
    return Namespace(
        n_bull=p.n_bull,
        n_bear=p.n_bear,
        vol_ma_win=p.vol_ma_win,
        vol_hi=p.vol_hi,
        vol_lo=p.vol_lo,
        bull_ret_min=p.bull_ret_min,
        bear_ret_max=p.bear_ret_max,
        macd_fast=p.macd_fast,
        macd_slow=p.macd_slow,
        macd_signal=p.macd_signal,
        buy_mode=p.buy_mode,
        yang_max_wait=p.yang_max_wait,
        last_n_sessions=p.last_n_sessions,
        count=p.count,
        download=p.download,
        userdata=p.userdata,
        capital=float(getattr(p, "capital", 100_000.0)),
        lot=int(getattr(p, "lot", 100)),
        commission_bps=float(getattr(p, "commission_bps", 2.5)),
        entry_macd_bull=bool(getattr(p, "entry_macd_bull", False)),
        macd_exit_skip_first_bars=int(getattr(p, "macd_exit_skip_first_bars", 0) or 0),
        daily_phase1=bool(getattr(p, "daily_phase1", False)),
        daily_lookback_bars=int(getattr(p, "daily_lookback_bars", 160)),
        daily_vol_ma_win=int(getattr(p, "daily_vol_ma_win", 20)),
        daily_vol_hi=float(getattr(p, "daily_vol_hi", 1.15)),
        daily_attack_lookback=int(getattr(p, "daily_attack_lookback", 5)),
        daily_ma20=int(getattr(p, "daily_ma20", 20)),
        daily_phase1_mode=str(getattr(p, "daily_phase1_mode", "soft") or "soft"),
    )


def main() -> int:
    _configure_stdio()
    ap = argparse.ArgumentParser(description="人气榜 TopN × 5m 策略批量回测")
    ap.add_argument("--last-n-sessions", type=int, default=5, dest="last_n_sessions")
    ap.add_argument("--top", type=int, default=100, help="只跑前 N 只（按人气排名）")
    ap.add_argument("--count", type=int, default=1500, help="每标的拉取最近 N 根 5m")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--userdata", default=None)
    ap.add_argument("--rank-csv", default=None, help="从 CSV 读代码列（替代东财接口）")
    ap.add_argument("--rank-col", default="ts_code", help="CSV 中代码列名")
    ap.add_argument(
        "--output-xlsx",
        default=None,
        help="汇总 Excel 路径；默认 output/qmt_batch_hot_{timestamp}.xlsx",
    )
    ap.add_argument("--n-bull", type=int, default=4)
    ap.add_argument("--n-bear", type=int, default=4)
    ap.add_argument("--vol-ma-win", type=int, default=20, dest="vol_ma_win")
    ap.add_argument("--vol-hi", type=float, default=1.2, dest="vol_hi")
    ap.add_argument("--vol-lo", type=float, default=0.88, dest="vol_lo")
    ap.add_argument("--bull-ret-min", type=float, default=0.0025, dest="bull_ret_min")
    ap.add_argument("--bear-ret-max", type=float, default=-0.0015, dest="bear_ret_max")
    ap.add_argument("--macd-fast", type=int, default=12, dest="macd_fast")
    ap.add_argument("--macd-slow", type=int, default=26, dest="macd_slow")
    ap.add_argument("--macd-signal", type=int, default=9, dest="macd_signal")
    ap.add_argument(
        "--buy-mode",
        choices=("yang_after_bear", "bear_last_close"),
        default="yang_after_bear",
    )
    ap.add_argument("--yang-max-wait", type=int, default=48, dest="yang_max_wait")
    ap.add_argument(
        "--capital",
        type=float,
        default=100_000.0,
        help="展示用初始本金（元），用于复利测算期末权益与盈亏额",
    )
    ap.add_argument("--lot", type=int, default=100, help="假设每笔买卖股数（用于逐笔净盈亏元）")
    ap.add_argument(
        "--commission-bps",
        type=float,
        default=2.5,
        dest="commission_bps",
        help="单边佣金 bps（万分之一为 1）",
    )
    ap.add_argument(
        "--entry-macd-bull",
        action="store_true",
        dest="entry_macd_bull",
        help="与单标的脚本一致：买入根要求 DIF>DEA（默认关闭）",
    )
    ap.add_argument(
        "--macd-exit-skip-first-bars",
        type=int,
        default=0,
        dest="macd_exit_skip_first_bars",
        help="次日前 N 根 5m 不参与死叉判定（默认 0）",
    )
    ap.add_argument(
        "--daily-phase1",
        action="store_true",
        dest="daily_phase1",
        help="阶段1：日线环境过滤 5m 买点（默认 soft，见 --daily-phase1-mode）",
    )
    ap.add_argument(
        "--daily-phase1-mode",
        choices=("soft", "strict"),
        default="soft",
        dest="daily_phase1_mode",
        help="soft=仅昨收>MA20；strict=再加近几日放量阳线（更严）",
    )
    ap.add_argument("--daily-lookback-bars", type=int, default=160, dest="daily_lookback_bars")
    ap.add_argument("--daily-vol-ma-win", type=int, default=20, dest="daily_vol_ma_win")
    ap.add_argument("--daily-vol-hi", type=float, default=1.15, dest="daily_vol_hi")
    ap.add_argument("--daily-attack-lookback", type=int, default=5, dest="daily_attack_lookback")
    ap.add_argument("--daily-ma20", type=int, default=20, dest="daily_ma20")
    args = ap.parse_args()

    if args.rank_csv:
        rank_df = load_rank_from_csv(Path(args.rank_csv), args.rank_col)
        rank_source = f"csv:{args.rank_csv}"
    else:
        try:
            rank_df = fetch_em_hot_rank_top(page_size=max(100, args.top))
            rank_source = "em_hot_rank_top100"
        except Exception as e:
            fb = Path(__file__).resolve().parent / "data" / "hot_rank_fallback.csv"
            print(
                f"东财人气榜接口不可用（{e!s}）。改用仓库内备用表（**非**同花顺实时热度，仅保证离线可跑）：{fb}",
                file=sys.stderr,
            )
            rank_df = load_rank_from_csv(fb, "ts_code")
            rank_source = f"fallback:{fb.name}"

    rank_df = rank_df.drop_duplicates(subset=["ts_code"], keep="first").reset_index(drop=True)
    rank_df["rank"] = list(range(1, len(rank_df) + 1))
    if len(rank_df) < args.top:
        print(f"提示: 去重后共 {len(rank_df)} 只，少于 --top {args.top}，按实际只数回测。", file=sys.stderr)
    rank_df = rank_df.head(args.top).reset_index(drop=True)
    if "cn_name" not in rank_df.columns:
        rank_df["cn_name"] = ""

    qm = _load_qm_module()
    xtdata = qm._import_xtdata()
    if hasattr(xtdata, "enable_hello"):
        xtdata.enable_hello = False
    if hasattr(xtdata, "connect") and callable(xtdata.connect):
        xtdata.connect()
    bt_args = build_bt_namespace(args)

    for idx in rank_df.index:
        code = str(rank_df.loc[idx, "ts_code"])
        cur = str(rank_df.loc[idx, "cn_name"] or "").strip()
        if not cur:
            rank_df.loc[idx, "cn_name"] = (
                qm.xtdata_stock_name(xtdata, code) or qm.resolve_stock_name(code, None) or ""
            ).strip()

    strat_tag = qm.strategy_filename_tag_cn(args.buy_mode)
    rows: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []
    for _, r in rank_df.iterrows():
        code = str(r["ts_code"])
        rk = int(r["rank"]) if pd.notna(r["rank"]) else 0
        cn = str(r.get("cn_name", "") or "").strip()
        res = qm.run_single_symbol_backtest(xtdata, code, bt_args)
        if not cn:
            cn = str(res.get("stock_name", "") or "").strip()
        summ = res.get("summary_cn") if isinstance(res.get("summary_cn"), dict) else {}
        row: dict[str, Any] = {
            "人气排名": rk,
            "股票名称": cn,
            "证券代码": code,
            "榜单来源": rank_source,
            "热度区间": str(r.get("热度区间", "") or "") if "热度区间" in rank_df.columns else "",
            "核心题材": str(r.get("核心题材", "") or "") if "核心题材" in rank_df.columns else "",
            "回测成功": "是" if res.get("ok") else "否",
            "错误信息": res.get("error", "") or "",
            **summ,
        }
        rows.append(row)
        for tr in res.get("trades_detail_cn") or []:
            if isinstance(tr, dict):
                detail_rows.append(
                    {
                        "人气排名": rk,
                        "股票名称": cn,
                        "证券代码": code,
                        **tr,
                    }
                )
        disp = cn or code
        cp = res.get("compound_pct", "")
        print(
            f"[{rk:>3}/{args.top}] {disp} {code} ok={res.get('ok')} "
            f"笔数={res.get('n_trades')} 复利%={cp}"
        )

    out_df = pd.DataFrame(rows)
    summary_col_order = [
        "人气排名",
        "股票名称",
        "证券代码",
        "榜单来源",
        "热度区间",
        "核心题材",
        "回测成功",
        "错误信息",
        "K线根数",
        "区间起始",
        "区间结束",
        "区间首开末收涨跌",
        "策略复利减区间涨跌",
        "成交笔数",
        "展示用本金元",
        "假设每笔股数",
        "单边佣金bps",
        "算术平均单笔收益率",
        "算术累加收益率",
        "复利累计收益率",
        "胜率",
        "盈利笔数",
        "亏损笔数",
        "持平笔数",
        "最大单笔盈利",
        "最大单笔亏损",
        "单笔收益率标准差",
        "盈亏比",
        "平均盈利单笔",
        "平均亏损单笔",
        "笔均持仓5m根数",
        "区间自然日数",
        "年化估算收益率",
        "过程最大回撤",
        "按复利测算期末权益元",
        "较期初盈亏额元",
        "固定手数双边佣金后净盈亏合计元",
        "买卖时间线",
    ]
    out_df = out_df.reindex(columns=summary_col_order)

    detail_df = pd.DataFrame(detail_rows)
    detail_col_order = [
        "人气排名",
        "股票名称",
        "证券代码",
        "轮次",
        "买入时间",
        "卖出时间",
        "买入价",
        "卖出价",
        "价上收益率",
        "本笔毛盈亏元",
        "本笔手续费元",
        "扣费后收益率",
        "本笔净盈亏元",
        "平仓原因",
        "持仓5m根数",
    ]
    if not detail_df.empty:
        detail_df = detail_df.reindex(columns=detail_col_order)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = _REPO / "examples" / "quick_tests" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = qm.safe_filename_part(
        f"批量人气_最近{args.last_n_sessions}交易日_{strat_tag}_Top{args.top}_{stamp}",
        160,
    )
    out_path = Path(args.output_xlsx) if args.output_xlsx else out_dir / f"{stem}.xlsx"

    strat_ver = getattr(qm, "STRATEGY_LOGIC_VERSION", "")

    meta = pd.DataFrame(
        [
            (
                "说明",
                "优先东财个股人气榜Top100（与 AKShare stock_hot_rank_em 同源）；"
                "网络失败时用仓库 data/hot_rank_fallback.csv（蓝筹/成长混合，**非同花顺实时热度**）。"
                "严格同花顺热榜请导出 CSV 用 --rank-csv 或接 Tushare ths_hot。",
            ),
            ("策略逻辑版本", strat_ver),
            ("rank_source", rank_source),
            ("last_n_sessions", args.last_n_sessions),
            ("top", args.top),
            ("buy_mode", args.buy_mode),
            ("策略文件名标签", strat_tag),
            ("count_5m", args.count),
            ("展示用本金元", args.capital),
            ("假设每笔股数", args.lot),
            ("单边佣金bps", args.commission_bps),
            ("entry_macd_bull", args.entry_macd_bull),
            ("macd_exit_skip_first_bars", args.macd_exit_skip_first_bars),
            ("daily_phase1", args.daily_phase1),
            ("daily_phase1_mode", args.daily_phase1_mode),
            ("daily_lookback_bars", args.daily_lookback_bars),
            ("daily_vol_ma_win", args.daily_vol_ma_win),
            ("daily_vol_hi", args.daily_vol_hi),
            ("daily_attack_lookback", args.daily_attack_lookback),
            ("daily_ma20", args.daily_ma20),
        ],
        columns=["项", "值"],
    )

    traded = out_df[pd.to_numeric(out_df["成交笔数"], errors="coerce").fillna(0) > 0]
    cp = pd.to_numeric(traded["复利累计收益率"], errors="coerce")
    wr = pd.to_numeric(traded["胜率"], errors="coerce")
    succ = out_df[out_df["回测成功"] == "是"] if "回测成功" in out_df.columns else out_df
    ibh_ok = pd.to_numeric(succ["区间首开末收涨跌"], errors="coerce").dropna()
    ibh_tr = pd.to_numeric(traded["区间首开末收涨跌"], errors="coerce").dropna()
    ex_tr = pd.to_numeric(traded["策略复利减区间涨跌"], errors="coerce").dropna()
    stats = pd.DataFrame(
        [
            ("标的数", len(out_df)),
            ("有成交家数", int(len(traded))),
            ("复利累计收益率_均值_仅成交大于0笔", round(float(cp.mean()), 4) if len(cp) else ""),
            ("复利累计收益率_中位数_仅成交大于0笔", round(float(cp.median()), 4) if len(cp) else ""),
            ("胜率_均值_仅成交大于0笔", round(float(wr.mean()), 4) if len(wr) else ""),
            ("胜率_中位数_仅成交大于0笔", round(float(wr.median()), 4) if len(wr) else ""),
            (
                "区间首开末收涨跌_均值_全体回测成功",
                round(float(ibh_ok.mean()), 4) if len(ibh_ok) else "",
            ),
            (
                "区间首开末收涨跌_中位数_全体回测成功",
                round(float(ibh_ok.median()), 4) if len(ibh_ok) else "",
            ),
            ("区间首开末收涨跌_均值_仅成交大于0笔", round(float(ibh_tr.mean()), 4) if len(ibh_tr) else ""),
            ("区间首开末收涨跌_中位数_仅成交大于0笔", round(float(ibh_tr.median()), 4) if len(ibh_tr) else ""),
            ("策略复利减区间涨跌_均值_仅成交大于0笔", round(float(ex_tr.mean()), 4) if len(ex_tr) else ""),
            ("策略复利减区间涨跌_中位数_仅成交大于0笔", round(float(ex_tr.median()), 4) if len(ex_tr) else ""),
        ],
        columns=["项", "值"],
    )

    try:
        import openpyxl  # noqa: F401
    except ImportError:
        print("请安装: pip install openpyxl", file=sys.stderr)
        return 1
    with pd.ExcelWriter(out_path, engine="openpyxl") as w:
        meta.to_excel(w, sheet_name="说明", index=False)
        stats.to_excel(w, sheet_name="截面统计", index=False)
        out_df.to_excel(w, sheet_name="批量回测结果", index=False)
        if detail_df.empty:
            pd.DataFrame([{"说明": "本批无逐笔成交（全体成交笔数为 0 或拉数失败）"}]).to_excel(
                w, sheet_name="逐笔成交明细", index=False
            )
        else:
            detail_df.to_excel(w, sheet_name="逐笔成交明细", index=False)
    print(f"\n汇总 Excel: {out_path.resolve()}")
    okn = int((out_df["回测成功"] == "是").sum()) if "回测成功" in out_df.columns else 0
    print(f"成功 {okn}/{len(out_df)}，失败 {len(out_df) - okn}")
    if len(cp):
        msg = (
            f"截面：有成交 {len(traded)} 家，复利累计收益率% 均值={float(cp.mean()):.4f} "
            f"中位数={float(cp.median()):.4f}"
        )
        if len(wr):
            msg += f"；胜率% 均值={float(wr.mean()):.4f} 中位数={float(wr.median()):.4f}"
        msg += "（见 Excel「截面统计」）"
        print(msg)

    total_trades = int(pd.to_numeric(out_df["成交笔数"], errors="coerce").fillna(0).sum()) if "成交笔数" in out_df.columns else 0
    log_path = append_backtest_jsonl(
        _REPO,
        {
            "run_type": "batch_hot_rank",
            "strategy_logic_version": strat_ver,
            "excel_path": str(out_path.resolve()),
            "rank_source": rank_source,
            "last_n_sessions": args.last_n_sessions,
            "top": args.top,
            "count_5m": args.count,
            "buy_mode": args.buy_mode,
            "capital": args.capital,
            "lot": args.lot,
            "commission_bps": args.commission_bps,
            "entry_macd_bull": args.entry_macd_bull,
            "macd_exit_skip_first_bars": args.macd_exit_skip_first_bars,
            "daily_phase1": args.daily_phase1,
            "daily_phase1_mode": args.daily_phase1_mode,
            "daily_lookback_bars": args.daily_lookback_bars,
            "daily_vol_hi": args.daily_vol_hi,
            "symbols": len(out_df),
            "ok_symbols": okn,
            "symbols_with_trades": int(len(traded)),
            "total_trade_rounds": total_trades,
            "compound_pct_mean": round(float(cp.mean()), 6) if len(cp) else None,
            "compound_pct_median": round(float(cp.median()), 6) if len(cp) else None,
            "winrate_pct_mean": round(float(wr.mean()), 6) if len(wr) else None,
            "winrate_pct_median": round(float(wr.median()), 6) if len(wr) else None,
            "interval_bh_pct_mean_all_ok": round(float(ibh_ok.mean()), 6) if len(ibh_ok) else None,
            "interval_bh_pct_median_all_ok": round(float(ibh_ok.median()), 6) if len(ibh_ok) else None,
            "interval_bh_pct_mean_traded": round(float(ibh_tr.mean()), 6) if len(ibh_tr) else None,
            "excess_compound_minus_interval_mean_traded": round(float(ex_tr.mean()), 6)
            if len(ex_tr)
            else None,
        },
    )
    print(f"回测记录已追加: {log_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
