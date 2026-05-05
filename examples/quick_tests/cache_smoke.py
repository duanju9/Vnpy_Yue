# -*- coding: utf-8 -*-
"""vnpy.feeds 缓存层烟雾测试：两次拉同区间，第二次应命中本地 Parquet。"""

from __future__ import annotations

import io
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if sys.platform == "win32" and isinstance(sys.stdout, io.TextIOWrapper):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from vnpy.feeds import (  # noqa: E402
    FeedRegistry,
    default_data_root,
    fetch_daily_cached,
)


def main() -> None:
    ts_code = "002709.SZ"
    start, end = "20260401", "20260430"
    root = default_data_root()
    print(f"数据根目录: {root}")

    t0 = time.perf_counter()
    df1 = fetch_daily_cached(ts_code, start, end)
    t1 = time.perf_counter()
    df2 = fetch_daily_cached(ts_code, start, end)
    t2 = time.perf_counter()

    print(f"第一次 rows={len(df1)} 耗时 {t1 - t0:.2f}s（含网络或冷启动）")
    print(f"第二次 rows={len(df2)} 耗时 {t2 - t1:.3f}s（应明显更短：命中缓存）")
    if not df2.empty:
        print(df2[["trade_date", "close"]].head(3).to_string(index=False))

    reg = FeedRegistry(root)
    meta = reg.get_symbol_daily_meta(ts_code)
    print("symbol_daily_meta:", meta)


if __name__ == "__main__":
    main()
