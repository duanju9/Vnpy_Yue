# -*- coding: utf-8 -*-
"""
将「全市场合约索引」写入 PostgreSQL，换机后只需恢复库或连同一库，无需反复从 QMT 构建。

环境变量（二选一）::

    # 推荐：一条 URI
    CHAN_WEB_PG_URI=postgresql://quantuser:密码@127.0.0.1:5433/quantdb

    # 或标准 libpq 变量（需同时有 PGDATABASE + PGUSER；端口未设时默认 5432，本机若为 5433 请设 PGPORT）
    PGHOST=127.0.0.1 PGPORT=5433 PGUSER=quantuser PGPASSWORD=... PGDATABASE=quantdb

表名固定为 ``chan_web_instruments``；K 线备份见 ``ohlcv_cache_pg`` 中的 ``chan_web_ohlcv_cache``（可同在 ``quantdb``）。
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote_plus

_TABLE = "chan_web_instruments"


def pg_uri() -> str | None:
    direct = (os.environ.get("CHAN_WEB_PG_URI") or "").strip()
    if direct:
        return direct
    db = (os.environ.get("PGDATABASE") or os.environ.get("PGDB") or "").strip()
    user = (os.environ.get("PGUSER") or "").strip()
    if not db or not user:
        return None
    host = (os.environ.get("PGHOST") or "127.0.0.1").strip()
    port = (os.environ.get("PGPORT") or "5432").strip()
    password = os.environ.get("PGPASSWORD") or ""
    return (
        f"postgresql://{quote_plus(user)}:{quote_plus(password)}"
        f"@{quote_plus(host)}:{port}/{quote_plus(db)}"
    )


def is_pg_configured() -> bool:
    return pg_uri() is not None


def _connect() -> Any:
    try:
        import psycopg
    except ImportError as e:
        raise RuntimeError("请安装: pip install 'psycopg[binary]>=3.1'") from e

    uri = pg_uri()
    if not uri:
        raise RuntimeError("未配置 PostgreSQL（CHAN_WEB_PG_URI 或 PGDATABASE+PGUSER）")
    return psycopg.connect(uri, connect_timeout=30)


def ensure_table(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_TABLE} (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
    conn.commit()


def load_instrument_index_from_pg() -> list[tuple[str, str]] | None:
    """从 PG 读全表；未配置、无表、空表、失败时返回 None（由调用方回退 JSON）。"""
    if not is_pg_configured():
        return None
    conn = None
    try:
        conn = _connect()
        ensure_table(conn)
        with conn.cursor() as cur:
            cur.execute(f"SELECT code, name FROM {_TABLE} ORDER BY code")
            raw = cur.fetchall()
        if not raw:
            return None
        return [(str(a), str(b or "")) for a, b in raw]
    except (ImportError, OSError, RuntimeError):
        return None
    except Exception:
        return None
    finally:
        if conn is not None:
            conn.close()


def count_instruments_in_pg() -> int | None:
    """``chan_web_instruments`` 行数；未配置或失败返回 None。"""
    if not is_pg_configured():
        return None
    conn = None
    try:
        conn = _connect()
        ensure_table(conn)
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {_TABLE}")
            row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return None
    finally:
        if conn is not None:
            conn.close()


def replace_instrument_index_in_pg(rows: list[tuple[str, str]]) -> int:
    """
    清空并写入索引（与 QMT 构建结果一致）。
    :return: 写入条数
    """
    if not rows:
        raise ValueError("rows 为空")
    conn = None
    try:
        conn = _connect()
        ensure_table(conn)
        with conn.cursor() as cur:
            cur.execute(f"TRUNCATE {_TABLE}")
            cur.executemany(
                f"INSERT INTO {_TABLE} (code, name) VALUES (%s, %s)",
                [(c, n or "") for c, n in rows],
            )
        conn.commit()
        return len(rows)
    finally:
        if conn is not None:
            conn.close()
