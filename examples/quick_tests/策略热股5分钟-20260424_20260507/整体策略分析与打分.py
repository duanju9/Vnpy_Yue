# -*- coding: utf-8 -*-
"""
热股批次的「整体展示」：① 全池与回测同窗口的区间首开末收涨跌（波动环境）；
② 若提供批量汇总 Excel，则从「批量回测结果」sheet 聚合策略截面，并给出 **策略打分（0–100）**。

打分逻辑面向：选热股 = 要波动；希望规则能在波动里 **相对稳定地兑现收益**（≠ 必然跑赢全程持有）。

用法（在仓库 Vnpy_Yue 根目录）::

    # 推荐：基于已跑好的批量 Excel（从表内「区间首开末收涨跌」汇总全池，无需再拉 5m）+ 策略打分
    python examples/quick_tests/策略热股5分钟-20260424_20260507/整体策略分析与打分.py ^
      --batch-xlsx examples/quick_tests/output/批量人气_最近10交易日_....xlsx

    # 仅扫全池区间（需 miniQMT；无 xlsx 时用）
    python examples/quick_tests/策略热股5分钟-20260424_20260507/整体策略分析与打分.py --interval-only
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_PKG = Path(__file__).resolve().parent
_QT = Path(__file__).resolve().parents[1]
_ROOT = Path(__file__).resolve().parents[3]
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
    rows: list[dict[str, Any]] = []
    for _, row in raw.iterrows():
        x = str(row[col]).strip()
        if ".SH" in x or ".SZ" in x or ".BJ" in x:
            ts_code = x
        else:
            ts_code = em_sc_to_ts_code(x)
        rec: dict[str, Any] = {"ts_code": ts_code}
        if name_col:
            rec["cn_name"] = str(row.get(name_col, "") or "").strip()
        rows.append(rec)
    out = pd.DataFrame(rows)
    if name_col is None:
        out["cn_name"] = ""
    return out


def _df_to_markdown(df: pd.DataFrame) -> str:
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in df.iterrows():
        cells = [str(row[c]).replace("|", "\\|") for c in df.columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def run_interval_scan(
    *,
    csv_path: Path,
    top: int,
    last_n_sessions: int,
    count: int,
    download: bool,
    userdata: str | None,
) -> tuple[pd.DataFrame, str]:
    qm = _load_qm()
    xtdata = qm._import_xtdata()
    if hasattr(xtdata, "enable_hello"):
        xtdata.enable_hello = False
    if hasattr(xtdata, "connect") and callable(xtdata.connect):
        xtdata.connect()
    rank_df = _load_rank_csv(csv_path, "ts_code")
    rank_df = rank_df.drop_duplicates(subset=["ts_code"], keep="first").reset_index(drop=True).head(top)
    rows: list[dict[str, Any]] = []
    for _, r in rank_df.iterrows():
        code = str(r["ts_code"])
        cn = str(r.get("cn_name", "") or "").strip()
        try:
            df = qm.xtdata_fetch_5m(xtdata, code, count, download=download, userdata=userdata)
        except Exception as e:
            rows.append(
                {
                    "ts_code": code,
                    "cn_name": cn,
                    "ok": False,
                    "error": str(e)[:120],
                    "区间涨跌pct": np.nan,
                }
            )
            continue
        if df is None or df.empty:
            rows.append(
                {"ts_code": code, "cn_name": cn, "ok": False, "error": "empty", "区间涨跌pct": np.nan}
            )
            continue
        if last_n_sessions > 0:
            df = qm.trim_last_n_trading_sessions(df, last_n_sessions)
        if df.empty:
            rows.append(
                {"ts_code": code, "cn_name": cn, "ok": False, "error": "trim_empty", "区间涨跌pct": np.nan}
            )
            continue
        o0, c1 = float(df["open"].iloc[0]), float(df["close"].iloc[-1])
        if not (np.isfinite(o0) and o0 > 0 and np.isfinite(c1)):
            ret = np.nan
        else:
            ret = round((c1 / o0 - 1.0) * 100.0, 4)
        if not cn:
            cn = (qm.resolve_stock_name(code, None) or qm.xtdata_stock_name(xtdata, code) or "").strip()
        rows.append({"ts_code": code, "cn_name": cn, "ok": True, "error": "", "区间涨跌pct": ret})
    out_df = pd.DataFrame(rows)
    ok = out_df[out_df["ok"]]
    rets = pd.to_numeric(ok["区间涨跌pct"], errors="coerce").dropna()
    n_ok, n_up, n_dn = len(rets), int((rets > 0).sum()), int((rets < 0).sum())
    mean_r, med_r = (float(rets.mean()), float(rets.median())) if len(rets) else (float("nan"), float("nan"))
    abs_mean = float(rets.abs().mean()) if len(rets) else float("nan")
    summary = (
        f"- 有效样本：**{n_ok}** ；区间上涨：**{n_up}** ；下跌：**{n_dn}**\n"
        f"- 区间涨跌%% **横截面均值**：**{mean_r:.4f}** ；**中位数**：**{med_r:.4f}**\n"
        f"- 全池 |区间涨跌| **均值**（波动幅度粗指标）：**{abs_mean:.4f}**%%\n"
    )
    return out_df, summary


def _read_batch_sheet(xlsx: Path) -> pd.DataFrame:
    df = pd.read_excel(xlsx, sheet_name="批量回测结果")
    return df


def compute_scores(df_traded: pd.DataFrame) -> dict[str, Any]:
    """
    仅对「成交笔数>0」子集打分。满分 100，四块与「热股 + 稳定套利」叙事对齐。
    """
    comp = pd.to_numeric(df_traded["复利累计收益率"], errors="coerce").dropna()
    exc = pd.to_numeric(df_traded["策略复利减区间涨跌"], errors="coerce").dropna()
    wr = pd.to_numeric(df_traded["胜率"], errors="coerce").dropna()
    iv = pd.to_numeric(df_traded["区间首开末收涨跌"], errors="coerce").dropna()
    dd_col = "过程最大回撤" if "过程最大回撤" in df_traded.columns else None
    dd = pd.to_numeric(df_traded[dd_col], errors="coerce").dropna() if dd_col else pd.Series(dtype=float)

    m_comp = float(comp.mean()) if len(comp) else 0.0
    m_exc = float(exc.mean()) if len(exc) else 0.0
    med_wr = float(wr.median()) if len(wr) else 50.0
    m_abs_iv = float(iv.abs().mean()) if len(iv) else 0.0
    m_dd = float(dd.mean()) if len(dd) else 0.0

    # ① 收益力 0–26：复利截面均值（热股里能否赚到钱）
    s_ret = min(26.0, max(0.0, (m_comp + 2.5) * 3.5))

    # ② 波动里的「套利感」0–30：相对全程持有的超额（不要求跑赢大牛市；略设下限避免「有收益但超额很负」时整项归零）
    s_exc = min(30.0, max(2.0, 14.0 + m_exc * 0.65))

    # ③ 稳定性 0–24：胜率中位数（笔级是否稳）
    s_wr = min(24.0, max(0.0, (med_wr - 46.0) * 0.62))

    # ④ 过程回撤纪律 0–20：平均最大回撤（越接近 0 越好，一般为负）
    s_dd = min(20.0, max(0.0, 20.0 + m_dd * 0.45))

    total = round(s_ret + s_exc + s_wr + s_dd, 2)
    if total >= 72:
        grade, note = "A", "综合较好：收益与纪律相对均衡，可作为继续迭代的基础。"
    elif total >= 56:
        grade, note = "B", "中等：有利润或胜率支撑，但在超额或回撤上仍有明显改进空间。"
    elif total >= 40:
        grade, note = "C", "偏弱：对照区间持有或回撤，规则与热股波动匹配度一般。"
    else:
        grade, note = "D", "审慎：截面整体偏弱或相对区间回撤/超额较差，不宜直接外推实盘。"

    return {
        "m_comp": m_comp,
        "m_exc": m_exc,
        "med_wr": med_wr,
        "m_abs_iv": m_abs_iv,
        "m_dd": m_dd,
        "s_ret": round(s_ret, 2),
        "s_exc": round(s_exc, 2),
        "s_wr": round(s_wr, 2),
        "s_dd": round(s_dd, 2),
        "total": total,
        "grade": grade,
        "note": note,
        "n_traded": int(len(df_traded)),
    }


def interval_block_from_xlsx(succ: pd.DataFrame) -> tuple[str, str]:
    """用批量结果中的「区间首开末收涨跌」列生成全池区间统计与降序表。"""
    if succ.empty or "区间首开末收涨跌" not in succ.columns:
        return "", ""
    iv = pd.to_numeric(succ["区间首开末收涨跌"], errors="coerce")
    sub = succ.loc[iv.notna()].copy()
    sub["区间涨跌pct"] = iv.loc[iv.notna()]
    rets = sub["区间涨跌pct"]
    n_ok = len(rets)
    n_up, n_dn = int((rets > 0).sum()), int((rets < 0).sum())
    mean_r, med_r = float(rets.mean()), float(rets.median())
    abs_mean = float(rets.abs().mean())
    summary = (
        f"- 有效样本：**{n_ok}** ；区间上涨：**{n_up}** ；下跌：**{n_dn}**\n"
        f"- 区间涨跌%% **横截面均值**：**{mean_r:.4f}** ；**中位数**：**{med_r:.4f}**\n"
        f"- 全池 |区间涨跌| **均值**（波动幅度粗指标）：**{abs_mean:.4f}**%%\n"
        f"- 本段 **直接来自本 Excel**「批量回测结果」列，与当次回测逐标的区间一致（无需再拉 5m）。\n"
    )
    comp_col = "复利累计收益率"
    if comp_col in sub.columns:
        strat_s = pd.to_numeric(sub[comp_col], errors="coerce")
        iv_s = sub["区间涨跌pct"]
        valid = strat_s.notna() & iv_s.notna()
        eps = 1e-6
        if int(valid.sum()) > 0:
            d = strat_s[valid] - iv_s[valid]
            n_be = int((d > eps).sum())
            n_lt = int((d < -eps).sum())
            n_eq = int((d.abs() <= eps).sum())
            summary += (
                f"- **是否跑赢区间**（策略复利累计收益率 vs 区间首开末收涨跌，同口径 %%）："
                f"**跑赢 {n_be}** ；**跑输 {n_lt}** ；**持平 {n_eq}**（两列均有效时统计）。\n"
            )
    code_col = "证券代码" if "证券代码" in sub.columns else "ts_code"
    name_col = "股票名称" if "股票名称" in sub.columns else None
    show = sub.sort_values("区间涨跌pct", ascending=False, na_position="last")
    out_show = show[[code_col, "区间涨跌pct"]].rename(columns={code_col: "证券代码", "区间涨跌pct": "区间首开末收涨跌"})
    if name_col:
        out_show.insert(1, "股票名称", show[name_col].values)
    # 与 Excel「批量回测结果」一致：展示同期策略复利累计收益率（无成交一般为 0）；并标注是否跑赢区间
    if comp_col in show.columns:
        ser = pd.to_numeric(show[comp_col], errors="coerce")
        iv_row = show["区间涨跌pct"]

        def _fmt_comp(x: Any) -> Any:
            if x is None or pd.isna(x):
                return ""
            try:
                v = float(x)
            except (TypeError, ValueError):
                return ""
            if not np.isfinite(v):
                return ""
            return round(v, 4)

        out_show["策略复利累计收益率"] = ser.map(_fmt_comp)

        def _beat_label(sv: Any, iv: Any) -> str:
            if pd.isna(sv) or pd.isna(iv):
                return ""
            try:
                fs, fi = float(sv), float(iv)
            except (TypeError, ValueError):
                return ""
            if not (np.isfinite(fs) and np.isfinite(fi)):
                return ""
            eps = 1e-6
            if abs(fs - fi) <= eps:
                return "持平"
            return "跑赢" if fs > fi else "跑输"

        out_show["是否跑赢区间"] = [_beat_label(s, i) for s, i in zip(ser.values, iv_row.values)]
    else:
        out_show["策略复利累计收益率"] = ""
        out_show["是否跑赢区间"] = ""
    table = _df_to_markdown(out_show)
    return summary, table


def main() -> int:
    ap = argparse.ArgumentParser(description="热股批次：区间环境 + 批量 Excel 策略展示与打分")
    ap.add_argument(
        "--csv",
        type=Path,
        default=_PKG / "测试成分股" / "ths_hot_THS20260424-0707_交付重跑_20260508.csv",
        help="股票池 CSV（仅 --interval-only 拉 5m 时用）",
    )
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--last-n-sessions", type=int, default=10, dest="last_n_sessions")
    ap.add_argument("--count", type=int, default=1500)
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--userdata", default=None)
    ap.add_argument("--batch-xlsx", type=Path, default=None, dest="batch_xlsx", help="批量汇总 xlsx（含「批量回测结果」sheet）")
    ap.add_argument("--interval-only", action="store_true", help="仅拉 5m 扫区间；需 miniQMT，不写打分")
    ap.add_argument(
        "--out-md",
        type=Path,
        default=_PKG / "整体策略展示与打分.md",
    )
    args = ap.parse_args()

    lines: list[str] = []
    lines.append("# 整体策略展示与打分（热股 5m 批次）\n\n")
    lines.append("> 本文档由 `整体策略分析与打分.py` 自动生成；可纳入 zip 交付。\n\n")
    lines.append("## 1. 选股逻辑说明（本批）\n\n")
    lines.append(
        "- **未做 alpha 选股**：股票池为 **同花顺人气 Top 快照**，动机是 **波动大、换手高**，便于技术规则有发挥空间。\n"
        "- **「稳定套利」在本报告中的含义**：不保证跑赢「一路持有」，而指 **笔级胜率与过程回撤** 相对可控、"
        "且在 **高波动区间** 下仍能 **稳定兑现一部分价差收益**（由打分中的收益力、超额、稳定性、回撤四块近似刻画）。\n\n"
    )

    lines.append("## 2. 全池区间环境（与回测同一 5m 截取窗口）\n\n")
    lines.append("口径：**第一根 5m 开盘价 → 最后一根 5m 收盘价**，涨跌幅%%；与引擎 `区间首开末收涨跌` 一致。\n\n")

    if args.interval_only:
        lines.append("*本节由 xtdata 现场拉取 5m 计算。*\n\n")
        try:
            interval_df, interval_summary = run_interval_scan(
                csv_path=Path(args.csv),
                top=int(args.top),
                last_n_sessions=int(args.last_n_sessions),
                count=int(args.count),
                download=bool(args.download),
                userdata=args.userdata,
            )
            lines.append(interval_summary)
            lines.append("\n")
            if interval_df is not None and not interval_df.empty:
                show = interval_df.sort_values("区间涨跌pct", ascending=False, na_position="last")
                lines.append("### 全表（按区间涨跌%%降序）\n\n")
                lines.append(_df_to_markdown(show[["ts_code", "cn_name", "ok", "区间涨跌pct", "error"]]))
                lines.append("\n")
        except Exception as e:
            lines.append(f"区间扫描失败：`{e}`\n\n")
        lines.append(
            "\n---\n\n已有批量 Excel 时推荐：`python .../整体策略分析与打分.py --batch-xlsx 路径.xlsx`（从表内列还原区间，无需再拉数）。\n"
        )
        args.out_md.write_text("".join(lines), encoding="utf-8")
        print(f"已写入: {args.out_md.resolve()}")
        return 0

    if args.batch_xlsx is None:
        lines.append(
            "*请任选其一：* `--interval-only`（拉 5m 扫区间），或 `--batch-xlsx 某次批量汇总.xlsx`（推荐：含区间列 + 策略打分）。\n"
        )
        args.out_md.write_text("".join(lines), encoding="utf-8")
        print(f"已写入占位说明: {args.out_md.resolve()}")
        return 0

    xlsx = Path(args.batch_xlsx)
    if not xlsx.is_file():
        print(f"找不到文件: {xlsx}", file=sys.stderr)
        return 1

    try:
        raw = _read_batch_sheet(xlsx)
    except Exception as e:
        lines.append(f"读取 Excel 失败：`{e}`\n")
        args.out_md.write_text("".join(lines), encoding="utf-8")
        print(f"已写入: {args.out_md.resolve()}")
        return 1

    succ = raw[raw.get("回测成功", "") == "是"].copy() if "回测成功" in raw.columns else raw.copy()
    summ2, tab2 = interval_block_from_xlsx(succ)
    if summ2:
        lines.append("*本节由本 Excel「批量回测结果」中的区间列汇总；与下文第 3 节区间统计同源。*\n\n")
        lines.append(summ2)
        lines.append("\n")
        if tab2:
            lines.append(
                "### 全池逐标的：区间首开末收涨跌 vs 策略复利累计（降序按区间涨跌）\n\n"
                "列 **策略复利累计收益率** 与 Excel「批量回测结果」中 **复利累计收益率** 一致（本区间多笔连乘%%；无成交为 0）。"
                "列 **是否跑赢区间**：策略复利累计收益率 **>** 区间首开末收涨跌 为 **跑赢**；**<** 为 **跑输**；相等（容差内）为 **持平**。\n\n"
            )
            lines.append(tab2)
            lines.append("\n")

    lines.append("---\n\n")
    lines.append(f"## 3. 批量回测结果聚合（来源：`{xlsx.name}`）\n\n")

    n_bt = pd.to_numeric(succ.get("成交笔数", 0), errors="coerce").fillna(0)
    traded = succ.loc[n_bt > 0].copy()

    def _col_mean(s: pd.Series) -> float:
        x = pd.to_numeric(s, errors="coerce").dropna()
        return float(x.mean()) if len(x) else float("nan")

    def _col_med(s: pd.Series) -> float:
        x = pd.to_numeric(s, errors="coerce").dropna()
        return float(x.median()) if len(x) else float("nan")

    iv_all = pd.to_numeric(succ.get("区间首开末收涨跌"), errors="coerce").dropna()
    lines.append("### 3.1 全体回测成功标的（含 0 成交）\n\n")
    lines.append(f"- 家数：**{len(succ)}**\n")
    if len(iv_all):
        lines.append(
            f"- **区间首开末收涨跌%%** 均值 **{_col_mean(succ['区间首开末收涨跌']):.4f}** ；"
            f"中位数 **{_col_med(succ['区间首开末收涨跌']):.4f}**\n"
        )
        lines.append(
            f"- |区间首开末收涨跌| 均值（波动粗指标）：**{float(iv_all.abs().mean()):.4f}**%%\n\n"
        )

    lines.append("### 3.2 有成交标的（用于策略截面与打分）\n\n")
    lines.append(f"- 家数：**{len(traded)}**\n")
    if traded.empty:
        lines.append("- 无成交，无法计算策略打分。\n")
    else:
        for label, col in [
            ("复利累计收益率%%", "复利累计收益率"),
            ("胜率%%", "胜率"),
            ("区间首开末收涨跌%%", "区间首开末收涨跌"),
            ("策略复利减区间涨跌（百分点）", "策略复利减区间涨跌"),
            ("过程最大回撤%%", "过程最大回撤"),
        ]:
            if col in traded.columns:
                lines.append(
                    f"- **{label}** 均值 **{_col_mean(traded[col]):.4f}** ；中位数 **{_col_med(traded[col]):.4f}**\n"
                )
        lines.append("\n")

        sc = compute_scores(traded)
        lines.append("## 4. 策略打分（0–100）\n\n")
        lines.append("### 4.1 维度与公式（透明、可改权重）\n\n")
        lines.append("| 维度 | 满分 | 含义 | 本批计算方式（代码一致） |\n")
        lines.append("|------|------|------|---------------------------|\n")
        lines.append(
            "| 收益力 | 26 | 热股池里策略能否 **稳定赚到钱** | `min(26, max(0, (复利均值%+2.5)×3.5))` |\n"
        )
        lines.append(
            "| 波动里套利感 | 30 | 相对 **全程持有** 是否过差（大牛市常显著为负） | `min(30, max(2, 14 + 超额均值×0.65))`，超额=策略复利减区间涨跌 |\n"
        )
        lines.append(
            "| 稳定性 | 24 | **笔级胜率** 中位 | `min(24, max(0, (胜率中位数−46)×0.62))` |\n"
        )
        lines.append(
            "| 回撤纪律 | 20 | **过程最大回撤** 横截面均值（越接近 0 越好） | `min(20, max(0, 20 + 回撤均值×0.45))` |\n"
        )
        lines.append(
            "\n**等级**：总分 ≥72 **A**；≥56 **B**；≥40 **C**；否则 **D**。"
            " 此为 **研究用标尺**，非投资建议。\n\n"
        )
        lines.append("### 4.2 本 Excel 得分\n\n")
        lines.append(f"- **有成交家数**：{sc['n_traded']}\n")
        lines.append(
            f"- **复利均值%%** {sc['m_comp']:.4f} ；**超额均值（百分点）** {sc['m_exc']:.4f} ；"
            f"**胜率中位数%%** {sc['med_wr']:.4f} ；**|区间|均值%%** {sc['m_abs_iv']:.4f} ；**回撤均值%%** {sc['m_dd']:.4f}\n"
        )
        lines.append(
            f"- **分项**：收益力 **{sc['s_ret']}** ；套利感 **{sc['s_exc']}** ；稳定性 **{sc['s_wr']}** ；回撤 **{sc['s_dd']}**\n"
        )
        lines.append(f"- **总分**：**{sc['total']}** / 100 　**等级：{sc['grade']}**\n")
        lines.append(f"- **评语**：{sc['note']}\n\n")

        lines.append("### 4.3 与「热股 + 稳定套利」期望的对照\n\n")
        lines.append(
            "- 若 **|区间| 均值很高** 而 **超额均值很负**：说明池子波动大，但本规则 **早下车**，"
            "更像 **波段提款**，不宜用「跑赢全程持有」苛求。\n"
            "- 若 **稳定性、回撤** 两项长期偏低：即使收益尚可，也 **谈不上稳定**，应优先改出场/仓位假设而非继续加信号。\n\n"
        )

    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text("".join(lines), encoding="utf-8")
    print(f"已写入: {args.out_md.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
