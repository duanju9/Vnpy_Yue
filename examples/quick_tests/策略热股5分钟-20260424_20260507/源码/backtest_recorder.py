# -*- coding: utf-8 -*-
"""将批量/单次回测摘要追加写入 JSONL，便于对比参数与策略版本。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def append_backtest_jsonl(repo_root: Path, record: dict[str, Any]) -> Path:
    out_dir = repo_root / "examples" / "quick_tests" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "backtest_runs.jsonl"
    row = {
        **record,
        "logged_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path
