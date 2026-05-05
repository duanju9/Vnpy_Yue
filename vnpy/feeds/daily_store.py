# -*- coding: utf-8 -*-
"""日线 OHLCV 的 Parquet 落盘与合并（按标的单文件）。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .paths import default_data_root


def _require_pyarrow() -> None:
    try:
        import pyarrow  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "写入/读取 Parquet 缓存需要安装 pyarrow，例如: pip install pyarrow>=15"
        ) from e


def _normalize_trade_date_series(s: pd.Series) -> pd.Series:
    """统一为 8 位字符串 YYYYMMDD。"""
    out = s.astype(str).str.replace("-", "", regex=False).str[:8]
    return out


class DailyBarStore:
    """
    日线缓存：``<root>/daily/{ts_code}.parquet``（文件名中 ``.`` 替换为 ``_``）。

    合并策略：按 ``trade_date`` 去重，保留最新一行（便于修正历史）。
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root: Path = root if root is not None else default_data_root()
        self.daily_dir: Path = self.root / "daily"
        self.daily_dir.mkdir(parents=True, exist_ok=True)

    def parquet_path(self, ts_code: str) -> Path:
        safe = ts_code.replace(".", "_")
        return self.daily_dir / f"{safe}.parquet"

    def read_daily(self, ts_code: str) -> pd.DataFrame:
        path = self.parquet_path(ts_code)
        if not path.exists():
            return pd.DataFrame()
        _require_pyarrow()
        df = pd.read_parquet(path)
        if df.empty or "trade_date" not in df.columns:
            return df
        df = df.copy()
        df["trade_date"] = _normalize_trade_date_series(df["trade_date"])
        return df.sort_values("trade_date").reset_index(drop=True)

    def write_daily(self, ts_code: str, df: pd.DataFrame) -> None:
        """整表覆盖写入（慎用；一般用 ``merge_and_write``）。"""
        if df.empty:
            return
        _require_pyarrow()
        out = df.copy()
        out["trade_date"] = _normalize_trade_date_series(out["trade_date"])
        out = out.sort_values("trade_date").drop_duplicates(subset=["trade_date"], keep="last")
        path = self.parquet_path(ts_code)
        path.parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(path, index=False)

    def merge_and_write(self, ts_code: str, new_rows: pd.DataFrame) -> pd.DataFrame:
        """与已有缓存合并后写回，返回合并后的全量表。"""
        if new_rows.empty:
            return self.read_daily(ts_code)
        old = self.read_daily(ts_code)
        fresh = new_rows.copy()
        fresh["trade_date"] = _normalize_trade_date_series(fresh["trade_date"])
        if old.empty:
            merged = fresh
        else:
            merged = pd.concat([old, fresh], ignore_index=True)
        merged = merged.drop_duplicates(subset=["trade_date"], keep="last")
        merged = merged.sort_values("trade_date").reset_index(drop=True)
        self.write_daily(ts_code, merged)
        return merged
