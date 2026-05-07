# -*- coding: utf-8 -*-
"""
与批量回测相同的「操作区间」：5m 数据截取最近 N 个有 K 的交易日（trim_last_n_trading_sessions），
计算区间内 **整体涨跌**：(末根收盘价 − 首根开盘价) / 首根开盘价 × 100%%。

用于回答：这批股票在回测窗口内是偏涨还是偏跌；与策略复利无直接因果，仅作环境对照。

用法（在仓库 Vnpy_Yue 根目录）::

    python examples/quick_tests/study_batch_ths_hot_top100_20260424_20260507/分析_操作区间整体涨跌.py
    python .../分析_操作区间整体涨跌.py --top 20 --no-download
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Vnpy_Yue 根目录：本文件在 .../examples/quick_tests/study_batch_.../
_ROOT = Path(__file__).resolve().parents[3]
_QT = Path(__file__).resolve().parents[1]
for p in (_ROOT, _QT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def em_sc_to_ts_code(sc: str) -> str:
    sc = str(sc).strip().upper()
    if sc.startswith("SH") and len(sc) > 2:
        return f"{sc[2:]}.SH"
    if sc.startswith("SZ") and len(sc) > 2:
        return f"{sc[2:]}.SZ"
    if sc.startswith("BJ") and len(sc) > 2:
        return f"{sc[2:]}.BJ"
    return sc


def _df_to_markdown(df: pd.DataFrame) -> str:
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in df.iterrows():
        cells = [str(row[c]).replace("|", "\\|") for c in df.columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _load_qm():
    path = _QT / "qmt_5m_vol_pullback_macd_backtest.py"
    spec = importlib.util.spec_from_file_location("qmt_5m_bt", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 qmt_5m_vol_pullback_macd_backtest.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_rank_csv(path: Path, col: str) -> pd.DataFrame:
    raw = pd.read_csv(path, encoding="utf-8-sig")
    if col not in raw.columns:
        raise ValueError(f"CSV 无列 {col!r}")
    name_col = next(
        (c for c in ("cn_name", "股票名称", "证券名称", "name", "证券简称") if c in raw.columns),
        None,
    )
    rows: list[dict] = []
    for _, row in raw.iterrows():
        x = str(row[col]).strip()
        if ".SH" in x or ".SZ" in x or ".BJ" in x:
            ts_code = x
        else:
            ts_code = em_sc_to_ts_code(x)
        rec = {"ts_code": ts_code}
        if name_col:
            rec["cn_name"] = str(row.get(name_col, "") or "").strip()
        rows.append(rec)
    out = pd.DataFrame(rows)
    if name_col is None:
        out["cn_name"] = ""
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="THS 池：与回测同窗口的区间涨跌幅统计")
    ap.add_argument(
        "--csv",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "data" / "ths_hot_top100_20260424_20260507.csv",
    )
    ap.add_argument("--rank-col", default="ts_code")
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--last-n-sessions", type=int, default=10, dest="last_n_sessions")
    ap.add_argument("--count", type=int, default=1500, help="每标的拉取 5m 根数（与批量脚本一致）")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--userdata", default=None)
    ap.add_argument(
        "--out-md",
        type=Path,
        default=Path(__file__).resolve().parent / "区间整体涨跌分析.md",
    )
    args = ap.parse_args()

    qm = _load_qm()
    xtdata = qm._import_xtdata()
    if hasattr(xtdata, "enable_hello"):
        xtdata.enable_hello = False
    if hasattr(xtdata, "connect") and callable(xtdata.connect):
        xtdata.connect()

    rank_df = _load_rank_csv(Path(args.csv), args.rank_col)
    rank_df = rank_df.drop_duplicates(subset=["ts_code"], keep="first").reset_index(drop=True)
    rank_df = rank_df.head(int(args.top)).reset_index(drop=True)

    rows: list[dict] = []
    errors = 0
    for _, r in rank_df.iterrows():
        code = str(r["ts_code"])
        cn = str(r.get("cn_name", "") or "").strip()
        try:
            df = qm.xtdata_fetch_5m(
                xtdata, code, int(args.count), download=bool(args.download), userdata=args.userdata
            )
        except Exception as e:
            errors += 1
            rows.append(
                {
                    "ts_code": code,
                    "cn_name": cn,
                    "ok": False,
                    "error": str(e)[:200],
                    "区间涨跌pct": np.nan,
                    "首交易日": "",
                    "末交易日": "",
                    "5m根数": 0,
                }
            )
            continue
        if df is None or df.empty:
            errors += 1
            rows.append(
                {
                    "ts_code": code,
                    "cn_name": cn,
                    "ok": False,
                    "error": "empty_df",
                    "区间涨跌pct": np.nan,
                    "首交易日": "",
                    "末交易日": "",
                    "5m根数": 0,
                }
            )
            continue
        if args.last_n_sessions > 0:
            df = qm.trim_last_n_trading_sessions(df, int(args.last_n_sessions))
        if df.empty:
            errors += 1
            rows.append(
                {
                    "ts_code": code,
                    "cn_name": cn,
                    "ok": False,
                    "error": "empty_after_trim",
                    "区间涨跌pct": np.nan,
                    "首交易日": "",
                    "末交易日": "",
                    "5m根数": 0,
                }
            )
            continue
        ds = sorted({qm.session_date(ts) for ts in df.index})
        o0 = float(df["open"].iloc[0])
        c1 = float(df["close"].iloc[-1])
        if not np.isfinite(o0) or o0 <= 0 or not np.isfinite(c1):
            ret = np.nan
        else:
            ret = (c1 / o0 - 1.0) * 100.0
        if not cn:
            cn = (qm.resolve_stock_name(code, None) or qm.xtdata_stock_name(xtdata, code) or "").strip()
        rows.append(
            {
                "ts_code": code,
                "cn_name": cn,
                "ok": True,
                "error": "",
                "区间涨跌pct": round(ret, 4) if np.isfinite(ret) else np.nan,
                "首交易日": str(ds[0]) if ds else "",
                "末交易日": str(ds[-1]) if ds else "",
                "5m根数": int(len(df)),
            }
        )

    out_df = pd.DataFrame(rows)
    ok_df = out_df[out_df["ok"]].copy()
    rets = ok_df["区间涨跌pct"].dropna()

    n_ok = int(ok_df.shape[0])
    n_up = int((rets > 0).sum()) if len(rets) else 0
    n_dn = int((rets < 0).sum()) if len(rets) else 0
    n_flat = int((rets == 0).sum()) if len(rets) else 0
    mean_ret = float(rets.mean()) if len(rets) else float("nan")
    med_ret = float(rets.median()) if len(rets) else float("nan")

    # 等权「伪指数」：各标的区间收益率算术平均（非组合再平衡，仅描述横截面）
    lines: list[str] = []
    lines.append("# 操作区间整体涨跌（与批量回测同一 5m 窗口）\n")
    lines.append("## 定义\n")
    lines.append(
        "- **操作区间**：与 `run_single_symbol_backtest` 一致，对 5m K 线执行 `trim_last_n_trading_sessions`，"
        f"保留最近 **{args.last_n_sessions}** 个**有数据的交易日**。\n"
    )
    lines.append(
        "- **区间整体涨跌%**：该窗口内 **第一根 5m 的开盘价** → **最后一根 5m 的收盘价**，"
        "公式：(末收盘 − 首开) / 首开 × 100%。"
        "这是「一路持有不动」的粗略标尺，**不是**策略逐笔复利。\n"
    )
    lines.append(f"- **股票池**：`{args.csv.name}`，前 **{args.top}** 只（按 CSV 顺序去重后截取）。\n")
    lines.append("\n## 汇总\n\n")
    lines.append(f"| 项目 | 值 |\n|------|-----|\n")
    lines.append(f"| 有效样本（拉数+截取成功） | {n_ok} |\n")
    lines.append(f"| 失败/无数据 | {errors} |\n")
    lines.append(f"| 区间上涨家数（%>0） | {n_up} |\n")
    lines.append(f"| 区间下跌家数（%<0） | {n_dn} |\n")
    lines.append(f"| 持平（%=0） | {n_flat} |\n")
    lines.append(f"| 区间涨跌%% 横截面均值 | {mean_ret:.4f} |\n")
    lines.append(f"| 区间涨跌%% 横截面中位数 | {med_ret:.4f} |\n")
    if n_ok > 0 and not ok_df.empty:
        d_first = ok_df["首交易日"].astype(str).min()
        d_last = ok_df["末交易日"].astype(str).max()
        lines.append(f"| 各标的「首交易日」最早 | {d_first} |\n")
        lines.append(f"| 各标的「末交易日」最晚 | {d_last} |\n")
    lines.append("\n**结论一句话**：")
    if n_ok == 0:
        lines.append("无有效样本，请检查 miniQMT / 本地缓存与 CSV。\n")
    elif mean_ret > 0.5:
        lines.append(
            f"该窗口内多数标的的「首开末收」横截面均值为正（约 **{mean_ret:.2f}%**），"
            "整体偏 **上涨环境**（不等同于指数涨跌）。\n"
        )
    elif mean_ret < -0.5:
        lines.append(
            f"该窗口内横截面均值为负（约 **{mean_ret:.2f}%**），整体偏 **下跌/震荡偏弱** 环境。\n"
        )
    else:
        lines.append(
            f"该窗口内横截面均值接近零（**{mean_ret:.2f}%**），整体更接近 **震荡**；"
            "请结合上涨/下跌家数判断结构。\n"
        )

    lines.append("\n## 中国长城 000066.SZ（示例）\n\n")
    row066 = out_df[out_df["ts_code"].str.contains("000066", na=False)]
    if row066.empty:
        lines.append("本 CSV 截取范围内未找到 000066。\n")
    else:
        r0 = row066.iloc[0]
        lines.append(
            f"- 名称：{r0.get('cn_name', '')}  \n"
            f"- 区间涨跌%：{r0.get('区间涨跌pct', '')}  \n"
            f"- 首/末交易日：{r0.get('首交易日', '')} ~ {r0.get('末交易日', '')}  \n"
            f"- 5m 根数：{r0.get('5m根数', '')}  \n"
        )

    lines.append("\n## 全表（按区间涨跌%降序）\n\n")
    show = ok_df.sort_values("区间涨跌pct", ascending=False, na_position="last")[
        ["ts_code", "cn_name", "区间涨跌pct", "首交易日", "末交易日", "5m根数"]
    ]
    lines.append(_df_to_markdown(show))
    lines.append("\n\n## 失败行\n\n")
    bad = out_df[~out_df["ok"]][["ts_code", "cn_name", "error"]]
    if bad.empty:
        lines.append("无。\n")
    else:
        lines.append(_df_to_markdown(bad))
        lines.append("\n")

    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text("".join(lines), encoding="utf-8")
    print(f"已写入: {args.out_md.resolve()}")
    print(f"有效={n_ok} 涨={n_up} 跌={n_dn} 均值%={mean_ret:.4f} 中位%={med_ret:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
