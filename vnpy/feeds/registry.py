# -*- coding: utf-8 -*-
"""SQLite 元数据：标的缓存覆盖区间、同步流水（为后续批跑 / 板块表留钩子）。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import default_data_root


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class FeedRegistry:
    """
    元数据库：``<root>/manifest.sqlite``。

    表：
    - ``symbol_daily_meta``：每只股票日线在本地缓存中的 min/max 与行数
    - ``sync_run``：每次网络拉取一条流水，便于审计与限速排障
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root: Path = root if root is not None else default_data_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path: Path = self.root / "manifest.sqlite"
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS symbol_daily_meta (
                    ts_code TEXT PRIMARY KEY,
                    min_trade_date TEXT,
                    max_trade_date TEXT,
                    row_count INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sync_run (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_code TEXT NOT NULL,
                    req_start TEXT NOT NULL,
                    req_end TEXT NOT NULL,
                    rows_fetched INTEGER NOT NULL,
                    source TEXT NOT NULL DEFAULT 'tsy',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_sync_run_ts_code
                    ON sync_run (ts_code, created_at DESC);
                """
            )

    def upsert_symbol_daily(
        self,
        ts_code: str,
        *,
        min_trade_date: str,
        max_trade_date: str,
        row_count: int,
    ) -> None:
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO symbol_daily_meta
                    (ts_code, min_trade_date, max_trade_date, row_count, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(ts_code) DO UPDATE SET
                    min_trade_date = excluded.min_trade_date,
                    max_trade_date = excluded.max_trade_date,
                    row_count = excluded.row_count,
                    updated_at = excluded.updated_at
                """,
                (ts_code, min_trade_date, max_trade_date, row_count, now),
            )

    def log_sync_run(
        self,
        ts_code: str,
        req_start: str,
        req_end: str,
        rows_fetched: int,
        *,
        source: str = "tsy",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sync_run
                    (ts_code, req_start, req_end, rows_fetched, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (ts_code, req_start, req_end, rows_fetched, source, _utc_now_iso()),
            )

    def get_symbol_daily_meta(self, ts_code: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM symbol_daily_meta WHERE ts_code = ?",
                (ts_code,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return dict(row)
