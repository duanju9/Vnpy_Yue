# -*- coding: utf-8 -*-
"""
从研究库 ``sector_member`` 中解析指定**概念板块**（默认「机器人概念」），
结合 ``bars`` 日线做简单**选股打分**与**压力/支撑买卖参考**，导出 CSV。

**默认输出目录**：``examples/miniqmt_research/daily_picks/``（每日评分独立文件夹），
文件名带运行日期；可用 ``--out`` 覆盖路径，``--out-dir`` 只改目录。

用法（在 ``Vnpy_Yue`` 根目录）::

    python examples/miniqmt_research/concept_sector_screen_csv.py
    python examples/miniqmt_research/concept_sector_screen_csv.py --sector 人形机器人概念
    python examples/miniqmt_research/concept_sector_screen_csv.py --out-dir examples/miniqmt_research/daily_picks

说明：客户端「T概念」里常显示为「机器人概念」，但 ``xtdata.get_sector_list`` 落库名多为 ``TGN机器人概念``，属**命名差异**，一般不是同步失败。
``sector_member`` 一行一板块一股票，同一 ``code`` 可有多行（多概念）。若要把**所有名称含某关键字**的板块成分**去重合并**并列出每只股票所属板块，用::

    python examples/miniqmt_research/concept_sector_screen_csv.py --union-substring 机器人

不含「概念」字样的板块（如 ``GN工业机器人``、``机器人50``）在落库脚本里会被标为 ``kind=other``；若仅用
``download_sector_members_to_db.py --include concept,industry`` 则**不会**拉取这些板块，需加 ``other`` 或 ``all``。

打分说明（0–100，研究用，非投资建议）：
- 趋势：收盘相对 MA20 位置、MA5>MA20
- 量能：量比（相对近 5 日均量，不含当日）
- 动量：近 5 日涨幅（防过热）
- 结构：与 pro_live 一致的近高/近低 + MA20 压力/支撑带

买卖参考：由现价与支撑/压力/均线的相对位置生成中文短语（规则见代码内 ``_buy_sell_notes``）。

**买入优先级**：在综合分 ``score_0_100`` 基础上，对买点文案加分、对卖点风控文案扣分，
再加量比微调得到 ``priority_score``；全表按 ``priority_score`` 降序后生成 ``buy_priority``（1 最高）。

**中文简称**：先读库表 ``stock_cn_name``；对仍缺名称的标的，默认再调 ``xtdata.get_instrument_detail``
补全（需 miniQMT / xtdata，建议设 ``MINIQMT_USERDATA``），并写回 ``stock_cn_name`` 供下次使用。
可用 ``--skip-xt-name-fill`` 关闭（离线仅代码）。
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_MR = Path(__file__).resolve().parent
_EX = _MR.parent
_LIVE = _EX / "miniqmt_live"
for p in (_EX, _LIVE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from pro_live_quant.config import ProLiveConfig  # noqa: E402
from pro_live_quant.utils import compute_support_resistance, is_st_name  # noqa: E402


def _default_sqlite() -> Path:
    return Path(os.environ.get("MINIQMT_SQLITE_PATH") or str(_MR / "data" / "miniqmt.sqlite")).resolve()


def _daily_picks_dir() -> Path:
    return (_MR / "daily_picks").resolve()


def _write_df_csv_safe(df: pd.DataFrame, out: Path) -> Path:
    """先写临时文件再 ``os.replace``；若目标被占用（如 Excel 打开）则改写到带时间戳的备用路径。"""
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.parent / f".{out.name}.{os.getpid()}.writing.csv"
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    try:
        os.replace(str(tmp), str(out))
        return out
    except OSError as e:
        alt = out.with_name(f"{out.stem}_{int(time.time())}{out.suffix}")
        try:
            shutil.copy2(tmp, alt)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        print(
            f"[warn] 无法覆盖 {out}（常被 Excel 占用）: {e}；已写入: {alt}",
            file=sys.stderr,
            flush=True,
        )
        return alt


def _install_csv_snapshot(src: Path, dst: Path) -> Path:
    """将已生成的 ``src`` 安装为 ``dst``：先复制到同目录临时文件再 ``os.replace``，避免 WinError32 直写被占用文件。"""
    src = src.resolve()
    dst = dst.resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.parent / f".{dst.name}.{os.getpid()}.staging.csv"
    shutil.copy2(src, tmp)
    try:
        os.replace(str(tmp), str(dst))
        return dst
    except OSError as e:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        alt = dst.with_name(f"{dst.stem}_{int(time.time())}{dst.suffix}")
        shutil.copy2(src, alt)
        print(
            f"[warn] 无法覆盖 {dst}（常被 Excel/预览占用）: {e}；已写最新副本: {alt}",
            file=sys.stderr,
            flush=True,
        )
        return alt


def _default_screen_csv_path(out_dir: Path, *, union_sub: str | None, sector_hint: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    day = date.today().strftime("%Y%m%d")
    if union_sub:
        stub = "union_" + union_sub.strip().replace("/", "_").replace("\\", "_")
        stub = stub[:48]
    else:
        stub = (
            "sector_"
            + "".join(
                ch if ch.isalnum() or ("\u4e00" <= ch <= "\u9fff") else "_"
                for ch in (sector_hint or "").strip()
            ).strip("_")[:40]
        )
        if stub == "sector_":
            stub = "sector_default"
    return out_dir / f"screen_{stub}_{day}.csv"


def _priority_score_parts(
    score: float, buy_hint: str, sell_hint: str, vol_ratio: float | None
) -> tuple[float, float, float, float]:
    """返回 (priority_score, buy_bonus, sell_penalty, vol_adj)。"""
    bh = buy_hint or ""
    sh = sell_hint or ""
    buy_b = 0.0
    if "放量站均线" in bh:
        buy_b += 15.0
    if "贴近支撑位" in bh or "低吸" in bh:
        buy_b += 12.0
    if "支撑上方运行" in bh:
        buy_b += 6.0
    if "信号一般" in bh or "观望" in bh:
        buy_b -= 22.0
    sell_p = 0.0
    if "接近压力位" in sh:
        sell_p += 8.0
    if "接近预设止盈" in sh:
        sell_p += 5.0
    if "失守MA20" in sh:
        sell_p += 18.0
    vr_adj = 0.0
    if vol_ratio is not None and vol_ratio == vol_ratio and vol_ratio >= 0:
        vr_adj = min(float(vol_ratio), 3.5) * 0.35
    ps = float(score) + buy_b - sell_p + vr_adj
    return ps, buy_b, sell_p, vr_adj


def _resolve_sector_name(conn: sqlite3.Connection, hint: str) -> str:
    hint = (hint or "").strip()
    if not hint:
        raise ValueError("sector hint empty")
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sector_member' LIMIT 1"
    ).fetchone()
    if row is None:
        raise RuntimeError("缺少 sector_member 表，请先落板块")
    r = conn.execute(
        "SELECT COUNT(*) FROM sector_member WHERE sector_name = ?",
        (hint,),
    ).fetchone()
    if r and int(r[0] or 0) > 0:
        return hint

    def _pick(sql: str, params: tuple) -> list[tuple[str, int]]:
        return conn.execute(sql, params).fetchall()

    candidates: list[tuple[str, int]] = []
    # 优先：全名等于 hint；其次：以 hint 结尾（如「机器人概念」优于「TGN机器人概念」）；再其次：包含 hint
    candidates = _pick(
        """
        SELECT sector_name, COUNT(*) AS n
        FROM sector_member
        WHERE sector_name LIKE ?
        GROUP BY sector_name
        ORDER BY (CASE WHEN sector_name = ? THEN 0 ELSE 1 END),
                 LENGTH(sector_name) ASC,
                 n DESC
        LIMIT 20
        """,
        (f"%{hint}", hint),
    )
    if not candidates:
        candidates = _pick(
            """
            SELECT sector_name, COUNT(*) AS n
            FROM sector_member
            WHERE sector_name LIKE ?
            GROUP BY sector_name
            ORDER BY n DESC
            LIMIT 20
            """,
            (f"%{hint}%",),
        )
    if not candidates:
        raise RuntimeError(f"未找到与「{hint}」匹配的板块，请用 --sector 指定准确板块名")
    best = str(candidates[0][0])
    if best != hint:
        alts = ", ".join(str(x[0]) for x in candidates[:5])
        print(f"[warn] 未命中精确「{hint}」，改用「{best}」。候选: {alts}", file=sys.stderr)
    return best


def _codes_in_sector(conn: sqlite3.Connection, sector_name: str) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT code FROM sector_member WHERE sector_name = ? ORDER BY code",
        (sector_name,),
    ).fetchall()
    return [str(r[0]).strip() for r in rows if r and r[0]]


def _union_codes_by_substring(
    conn: sqlite3.Connection, sub: str
) -> tuple[str, list[str], dict[str, str], list[tuple[str, int]]]:
    """按 ``sector_name LIKE %sub%`` 合并成分股；返回 (池标签, codes, code->板块名列表, 命中板块及成分数)。"""
    sub = (sub or "").strip()
    if not sub:
        raise ValueError("union substring empty")
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sector_member' LIMIT 1"
    ).fetchone()
    if row is None:
        raise RuntimeError("缺少 sector_member 表，请先落板块")
    pat = f"%{sub}%"
    sectors = conn.execute(
        """
        SELECT sector_name, COUNT(DISTINCT code) AS n
        FROM sector_member
        WHERE sector_name LIKE ?
        GROUP BY sector_name
        ORDER BY n DESC
        """,
        (pat,),
    ).fetchall()
    if not sectors:
        raise RuntimeError(f"未找到 sector_name LIKE {pat!r} 的板块")
    tag_rows = conn.execute(
        """
        SELECT code, GROUP_CONCAT(sector_name, ';') AS tags
        FROM (
            SELECT DISTINCT code, sector_name
            FROM sector_member
            WHERE sector_name LIKE ?
        )
        GROUP BY code
        """,
        (pat,),
    ).fetchall()
    tags: dict[str, str] = {}
    for c, t in tag_rows:
        cc = str(c).strip()
        if cc:
            tags[cc] = str(t or "").strip()
    codes = sorted(tags.keys())
    pool = f"union_like:{sub}"
    sec_stats = [(str(a), int(b or 0)) for a, b in sectors]
    return pool, codes, tags, sec_stats


def _load_cn_map(conn: sqlite3.Connection, codes: list[str]) -> dict[str, str]:
    if not codes or not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='stock_cn_name' LIMIT 1"
    ).fetchone():
        return {}
    out: dict[str, str] = {}
    for i in range(0, len(codes), 400):
        part = codes[i : i + 400]
        ph = ",".join("?" * len(part))
        for c, n in conn.execute(f"SELECT code, name FROM stock_cn_name WHERE code IN ({ph})", part):
            nn = str(n).strip() if n else ""
            if nn:
                out[str(c).strip()] = nn
    return out


def _import_xtdata() -> Any:
    try:
        from xtquant import xtdata  # type: ignore
    except ImportError:
        import xtquant.xtdata as xtdata  # type: ignore
    return xtdata


def _configure_xt(xt: Any, userdata: str | None) -> None:
    if hasattr(xt, "enable_hello"):
        xt.enable_hello = False
    if userdata:
        setattr(xt, "data_dir", userdata)
    if hasattr(xt, "connect") and callable(xt.connect):
        xt.connect()


def _xt_instrument_display_name(d: Any) -> str:
    if not isinstance(d, dict):
        return ""
    return str(
        d.get("InstrumentName")
        or d.get("instrumentName")
        or d.get("Name")
        or d.get("name")
        or ""
    ).strip()


def _fill_missing_cn_from_xtdata(
    conn: sqlite3.Connection,
    codes: list[str],
    cn: dict[str, str],
    *,
    sleep: float,
) -> None:
    """对 ``cn`` 中无简称的 code 调 xtdata 补全，并写回 ``stock_cn_name``（表存在时）。"""
    missing = [str(c).strip() for c in codes if c and not str(cn.get(str(c).strip(), "")).strip()]
    if not missing:
        return
    try:
        xt = _import_xtdata()
    except Exception as e:
        print(f"[warn] 无法加载 xtdata，跳过中文名补全: {e}", file=sys.stderr)
        return
    userdata = (os.environ.get("MINIQMT_USERDATA") or "").strip() or None
    try:
        _configure_xt(xt, userdata)
    except Exception as e:
        print(f"[warn] xtdata 连接/配置失败，跳过中文名补全: {e}", file=sys.stderr)
        return
    has_tbl = bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='stock_cn_name' LIMIT 1"
        ).fetchone()
    )
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    batch: list[tuple[str, str, str]] = []
    ok = 0
    for i, code in enumerate(missing):
        if i and i % 300 == 0:
            print(f"[names] xtdata {i}/{len(missing)} filled={ok}", flush=True)
        try:
            d = xt.get_instrument_detail(code, iscomplete=False)
        except Exception:
            d = None
        nm = _xt_instrument_display_name(d)
        if nm:
            cn[code] = nm
            ok += 1
            if has_tbl:
                batch.append((code, nm, now))
        time.sleep(max(0.0, float(sleep)))
    if has_tbl and batch:
        conn.executemany(
            "INSERT OR REPLACE INTO stock_cn_name (code, name, updated_at) VALUES (?,?,?)",
            batch,
        )
        conn.commit()
    print(f"[names] xtdata 中文简称补全 {ok}/{len(missing)}（已用于本次 CSV；库表已同步）", flush=True)


def _load_daily_panel(conn: sqlite3.Connection, codes: list[str], ts_end: str, min_rows: int) -> pd.DataFrame:
    if not codes:
        return pd.DataFrame()
    ph = ",".join("?" * len(codes))
    q = f"""
        SELECT code, ts, open, high, low, close, volume, amount
        FROM bars
        WHERE period='1d' AND code IN ({ph}) AND ts <= ?
        ORDER BY code, ts
    """
    df = pd.read_sql_query(q, conn, params=[*codes, ts_end])
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
    for c in ("open", "high", "low", "close", "volume", "amount"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    g = df.groupby("code", sort=False)
    df["ma5"] = g["close"].transform(lambda s: s.rolling(5, min_periods=5).mean())
    df["ma20"] = g["close"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["vol_ma5"] = g["volume"].transform(lambda s: s.shift(1).rolling(5, min_periods=5).mean())
    df["vol_ratio"] = np.where(df["vol_ma5"] > 0, df["volume"] / df["vol_ma5"], np.nan)
    df["ret5"] = g["close"].transform(lambda s: s.pct_change(5))
    cnt = g["close"].transform("count")
    return df.loc[cnt >= min_rows].copy()


def _score_row(last: pd.Series, *, sup: float | None, res: float | None) -> tuple[float, str]:
    """返回 (0-100 分, 简短理由)。"""
    c = float(last["close"])
    m20 = float(last["ma20"]) if pd.notna(last["ma20"]) else np.nan
    m5 = float(last["ma5"]) if pd.notna(last["ma5"]) else np.nan
    vr = float(last["vol_ratio"]) if pd.notna(last["vol_ratio"]) else np.nan
    r5 = float(last["ret5"]) if pd.notna(last["ret5"]) else np.nan
    parts: list[str] = []
    s = 0.0
    if np.isfinite(m20) and m20 > 0:
        if c > m20:
            s += 28.0
            parts.append("上MA20")
        bias = (c - m20) / m20
        s += float(np.clip(bias * 120.0, -8.0, 18.0))
    if np.isfinite(m5) and np.isfinite(m20) and m5 > m20:
        s += 12.0
        parts.append("MA5>MA20")
    if np.isfinite(vr):
        s += float(np.clip((vr - 1.0) * 15.0, -5.0, 22.0))
        parts.append(f"量比{vr:.2f}")
    if np.isfinite(r5):
        if -0.02 <= r5 <= 0.12:
            s += 18.0
            parts.append("5日涨幅温和")
        elif r5 > 0.15:
            s -= 12.0
            parts.append("5日涨幅偏热")
    if sup and res and sup > 0 and res > 0 and res > sup:
        mid = (sup + res) / 2.0
        pos = (c - sup) / max(res - sup, 1e-9)
        s += float(np.clip(pos * 22.0, 0.0, 20.0))
        if c <= sup * 1.02:
            parts.append("贴近支撑")
        if c >= res * 0.98:
            parts.append("贴近压力")
        parts.append(f"SR比{(c-mid)/(res-sup):.2f}")
    s = float(np.clip(s, 0.0, 100.0))
    return s, "+".join(parts[:6])


def _apply_buy_priority_columns(df: pd.DataFrame) -> pd.DataFrame:
    """按 priority_score 降序写入 buy_priority（1=最高）与 priority_score。"""
    if df.empty or "score_0_100" not in df.columns:
        return df
    df = df.copy()
    scores = pd.to_numeric(df["score_0_100"], errors="coerce")
    if "vol_ratio" in df.columns:
        vols = pd.to_numeric(df["vol_ratio"], errors="coerce")
    else:
        vols = pd.Series(np.nan, index=df.index)
    ps_vals: list[float] = []
    for i in range(len(df)):
        sc = scores.iloc[i]
        if pd.isna(sc):
            ps_vals.append(float("nan"))
            continue
        bh = str(df["buy_hint"].iloc[i]) if "buy_hint" in df.columns else ""
        sh = str(df["sell_hint"].iloc[i]) if "sell_hint" in df.columns else ""
        vr = vols.iloc[i]
        vr_f = float(vr) if pd.notna(vr) else None
        ps, _, _, _ = _priority_score_parts(float(sc), bh, sh, vr_f)
        ps_vals.append(ps)
    df["priority_score"] = ps_vals
    df["_ps_sort"] = df["priority_score"]
    df = df.sort_values("_ps_sort", ascending=False, na_position="last")
    buy_pri: list[object] = []
    rnk = 0
    for v in df["_ps_sort"]:
        if pd.isna(v):
            buy_pri.append("")
        else:
            rnk += 1
            buy_pri.append(rnk)
    df["buy_priority"] = buy_pri
    df["priority_score"] = df["priority_score"].round(4)
    df = df.drop(columns=["_ps_sort"], errors="ignore")
    front = [
        "buy_priority",
        "priority_score",
        "sector_name",
        "matched_sectors",
        "code",
        "name_cn",
        "score_0_100",
        "score_note",
    ]
    rest = [c for c in df.columns if c not in front]
    return df[front + rest]


def _buy_sell_notes(
    last: pd.Series,
    *,
    sup: float | None,
    res: float | None,
    stop_preview: float | None,
    tp_preview: float | None,
) -> tuple[str, str]:
    c = float(last["close"])
    m20 = float(last["ma20"]) if pd.notna(last["ma20"]) else np.nan
    vr = float(last["vol_ratio"]) if pd.notna(last["vol_ratio"]) else np.nan
    buy = []
    if np.isfinite(m20) and c > m20 and np.isfinite(vr) and vr >= 1.15:
        buy.append("放量站均线，可等回踩或突破加仓")
    if sup and sup > 0 and c <= sup * 1.025 and c >= sup * 0.98:
        buy.append("贴近支撑位，关注低吸/止损设于支撑下沿")
    if sup and c > sup * 1.02 and np.isfinite(m20) and c > m20:
        buy.append("支撑上方运行，顺势持有观察")
    if not buy:
        buy.append("信号一般，观望或等待明确回踩/突破")
    sell = []
    if res and res > 0 and c >= res * 0.985:
        sell.append("接近压力位，考虑分批止盈")
    if np.isfinite(m20) and c < m20 * 1.002:
        sell.append("失守MA20，防守减仓")
    if tp_preview and tp_preview > 0 and c >= tp_preview * 0.99:
        sell.append("接近预设止盈区")
    if stop_preview and c <= stop_preview * 1.01:
        sell.append("临近预设止损参考价")
    if not sell:
        sell.append("未到主要止盈/止损触发区，按规则持仓")
    return "；".join(buy[:3]), "；".join(sell[:3])


def main() -> int:
    ap = argparse.ArgumentParser(description="概念板块成分股 CSV + 打分 + 买卖参考")
    ap.add_argument("--sector", default="机器人概念", help="板块名关键字或全名（与 --union-substring 二选一）")
    ap.add_argument(
        "--union-substring",
        default="",
        help="若指定：合并所有 sector_name 含该子串的板块成分（去重），CSV 列 matched_sectors 列出所属板块",
    )
    ap.add_argument("--sqlite", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None, help="输出 CSV 完整路径（未指定则写入 daily_picks 并带日期）")
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="每日评分目录，默认 examples/miniqmt_research/daily_picks",
    )
    ap.add_argument("--min-daily-rows", type=int, default=60, help="少于该根日线的标的跳过打分")
    ap.add_argument(
        "--skip-xt-name-fill",
        action="store_true",
        help="不调用 xtdata 补全中文简称（仅依赖库内 stock_cn_name）",
    )
    ap.add_argument(
        "--name-fill-sleep",
        type=float,
        default=0.02,
        help="xtdata 按代码补全简称时的间隔秒（限频）",
    )
    args = ap.parse_args()

    # 未跑评分前也应存在该目录，便于在资源管理器 / Git 中直接看到 daily_picks/
    _daily_picks_dir().mkdir(parents=True, exist_ok=True)
    print(f"[daily_picks] {_daily_picks_dir()}", flush=True)

    db = (args.sqlite or _default_sqlite()).resolve()
    if not db.is_file():
        print(f"找不到数据库: {db}", file=sys.stderr)
        return 1

    out_dir = (args.out_dir or _daily_picks_dir()).resolve()
    if args.out is not None:
        out = Path(args.out).resolve()
    else:
        union_sub = (args.union_substring or "").strip()
        out = _default_screen_csv_path(
            out_dir,
            union_sub=union_sub if union_sub else None,
            sector_hint=str(args.sector or ""),
        )
    out.parent.mkdir(parents=True, exist_ok=True)

    cfg = ProLiveConfig.load()
    conn = sqlite3.connect(str(db))
    code_tags: dict[str, str] = {}
    try:
        union_sub = (args.union_substring or "").strip()
        if union_sub:
            sector_used, codes, code_tags, sec_stats = _union_codes_by_substring(conn, union_sub)
            for sn, nn in sec_stats[:30]:
                print(f"[union] {sn}\t{nn}", file=sys.stderr, flush=True)
            if len(sec_stats) > 30:
                print(f"[union] ... 共 {len(sec_stats)} 个命中板块", file=sys.stderr, flush=True)
        else:
            sector_used = _resolve_sector_name(conn, args.sector)
            codes = _codes_in_sector(conn, sector_used)
            code_tags = {c: sector_used for c in codes}
        cn = _load_cn_map(conn, codes)
        ts_hi = conn.execute(
            "SELECT MAX(ts) FROM bars WHERE period='1d'"
        ).fetchone()[0]
        ts_end = str(ts_hi or "")[:10] + " 23:59:59"
        panel = _load_daily_panel(conn, codes, ts_end, int(args.min_daily_rows))
        need_names = codes if panel.empty else sorted(str(x) for x in panel["code"].unique().tolist())
        if not args.skip_xt_name_fill:
            _fill_missing_cn_from_xtdata(
                conn, need_names, cn, sleep=float(args.name_fill_sleep)
            )
    finally:
        conn.close()

    rows_out: list[dict[str, object]] = []
    if panel.empty:
        print(f"[warn] 无日线数据可打分，仅导出成分列表 sector={sector_used} n_codes={len(codes)}")
        for code in codes:
            rows_out.append(
                {
                    "buy_priority": "",
                    "priority_score": "",
                    "sector_name": sector_used,
                    "matched_sectors": code_tags.get(code, ""),
                    "code": code,
                    "name_cn": cn.get(code, ""),
                    "score_0_100": "",
                    "score_note": "NO_DAILY_BARS",
                    "last_close": "",
                    "ma20": "",
                    "vol_ratio": "",
                    "ret5d": "",
                    "support": "",
                    "resistance": "",
                    "stop_loss_preview": "",
                    "take_profit_preview": "",
                    "buy_hint": "",
                    "sell_hint": "",
                    "sqlite": str(db),
                }
            )
        written = _write_df_csv_safe(pd.DataFrame(rows_out), out)
        print(str(written))
        return 0

    for code, sub in panel.groupby("code", sort=False):
        sub = sub.sort_values("ts")
        last = sub.iloc[-1]
        nm = cn.get(code, "")
        if nm and is_st_name(nm):
            continue
        sup, res, meta = compute_support_resistance(
            sub,
            recent_high_days=cfg.sr_recent_high_days,
            recent_low_days=cfg.sr_recent_low_days,
            use_ma20_for_support=cfg.support_ma20_weight,
        )
        sl_prev = tp_prev = None
        if sup and res and sup > 0 and res > 0:
            sl_prev = float(sup) * (1.0 - cfg.stop_loss_below_support_pct)
            tp_prev = float(res) * (1.0 - cfg.take_profit_below_resistance_pct)
        sc, note = _score_row(last, sup=sup, res=res)
        bh, sh = _buy_sell_notes(
            last,
            sup=sup,
            res=res,
            stop_preview=sl_prev,
            tp_preview=tp_prev,
        )
        rows_out.append(
            {
                "sector_name": sector_used,
                "matched_sectors": code_tags.get(code, ""),
                "code": code,
                "name_cn": nm,
                "score_0_100": round(sc, 2),
                "score_note": note,
                "last_close": round(float(last["close"]), 4),
                "ma20": round(float(last["ma20"]), 4) if pd.notna(last["ma20"]) else "",
                "vol_ratio": round(float(last["vol_ratio"]), 4) if pd.notna(last["vol_ratio"]) else "",
                "ret5d": round(float(last["ret5"]), 6) if pd.notna(last["ret5"]) else "",
                "support": round(float(sup), 4) if sup else "",
                "resistance": round(float(res), 4) if res else "",
                "stop_loss_preview": round(float(sl_prev), 4) if sl_prev else "",
                "take_profit_preview": round(float(tp_prev), 4) if tp_prev else "",
                "buy_hint": bh,
                "sell_hint": sh,
                "sqlite": str(db),
            }
        )

    df_out = pd.DataFrame(rows_out)
    if not df_out.empty and "score_0_100" in df_out.columns:
        df_out = _apply_buy_priority_columns(df_out)
    written = _write_df_csv_safe(df_out, out)
    print(str(written))
    print(f"rows={len(df_out)} sector={sector_used}", flush=True)
    if written.parent.resolve() == _daily_picks_dir().resolve():
        latest = _daily_picks_dir() / "latest_screen.csv"
        installed = _install_csv_snapshot(written, latest)
        print(f"latest: {installed}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
