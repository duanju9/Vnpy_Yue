# -*- coding: utf-8 -*-
"""
miniQMT 拉到的 K 线落库备份：表 ``chan_web_ohlcv_cache``。
QMT 成功时写入；QMT 无数据或异常时按 symbol+period 读最近 N 根作为回退。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

_TABLE = "chan_web_ohlcv_cache"


def _connect() -> Any:
    import instrument_pg as _ip

    return _ip._connect()


def _ensure_table(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_TABLE} (
                symbol TEXT NOT NULL,
                period TEXT NOT NULL,
                bar_ts TIMESTAMPTZ NOT NULL,
                open DOUBLE PRECISION NOT NULL,
                high DOUBLE PRECISION NOT NULL,
                low DOUBLE PRECISION NOT NULL,
                close DOUBLE PRECISION NOT NULL,
                volume DOUBLE PRECISION NOT NULL DEFAULT 0,
                PRIMARY KEY (symbol, period, bar_ts)
            );
            """
        )
    conn.commit()


def save_ohlcv_cache(symbol: str, period: str, df: pd.DataFrame) -> int:
    """以 QMT 结果为真：先删该合约该周期旧缓存，再插入当前 DataFrame。未配置 PG 时返回 0。"""
    from instrument_pg import is_pg_configured

    if not is_pg_configured():
        return 0
    if df is None or df.empty:
        return 0
    sym = (symbol or "").strip()
    per = (period or "").strip()
    if not sym or per not in ("5m", "1d"):
        return 0

    d = df.copy()
    if not isinstance(d.index, pd.DatetimeIndex):
        d.index = pd.to_datetime(d.index)
    d = d[~d.index.isna()]
    if d.empty:
        return 0
    for col in ("open", "high", "low", "close", "volume"):
        if col not in d.columns:
            return 0

    rows: list[tuple] = []
    for ts, row in d.iterrows():
        ts_pd = pd.Timestamp(ts)
        if ts_pd is pd.NaT:
            continue
        if ts_pd.tzinfo is not None:
            ts_pd = ts_pd.tz_convert("UTC").tz_localize(None)
        rows.append(
            (
                sym,
                per,
                ts_pd.to_pydatetime(),
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                float(row.get("volume", 0) or 0),
            )
        )
    if not rows:
        return 0

    conn = None
    try:
        conn = _connect()
        _ensure_table(conn)
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {_TABLE} WHERE symbol = %s AND period = %s", (sym, per))
            cur.executemany(
                f"""
                INSERT INTO {_TABLE} (symbol, period, bar_ts, open, high, low, close, volume)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                rows,
            )
        conn.commit()
        return len(rows)
    finally:
        if conn is not None:
            conn.close()


def load_ohlcv_cache(symbol: str, period: str, limit: int) -> pd.DataFrame | None:
    """读最近 ``limit`` 根（按时间升序返回）。未配置 PG 或失败返回 None。"""
    from instrument_pg import is_pg_configured

    if not is_pg_configured():
        return None
    sym = (symbol or "").strip()
    per = (period or "").strip()
    if not sym or per not in ("5m", "1d"):
        return None
    lim = max(1, min(int(limit), 50_000))

    conn = None
    try:
        conn = _connect()
        _ensure_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT bar_ts, open, high, low, close, volume
                FROM {_TABLE}
                WHERE symbol = %s AND period = %s
                ORDER BY bar_ts DESC
                LIMIT %s
                """,
                (sym, per, lim),
            )
            raw = cur.fetchall()
    except Exception:
        return None
    finally:
        if conn is not None:
            conn.close()

    if not raw:
        return None
    df = pd.DataFrame(raw, columns=["bar_ts", "open", "high", "low", "close", "volume"])
    df["bar_ts"] = pd.to_datetime(df["bar_ts"])
    df = df.set_index("bar_ts").sort_index()
    return df
