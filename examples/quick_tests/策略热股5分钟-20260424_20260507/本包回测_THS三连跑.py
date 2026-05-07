# -*- coding: utf-8 -*-
"""
交付包内一键三连跑（无日线 / 日线 soft / 日线 strict），Excel 写入本目录 **产物/**，
文件名带 **策略热股5m交付_THS20260424-0707_** 前缀，便于与仓库默认 output 区分。

实际执行的是仓库内正式脚本（保证 _REPO 路径与 import 正确），本文件仅做路径拼装与 subprocess 转发。

用法（在仓库 Vnpy_Yue 根目录）::

    python examples/quick_tests/策略热股5分钟-20260424_20260507/本包回测_THS三连跑.py
    python .../本包回测_THS三连跑.py --top 20 --last-n-sessions 10
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

_PKG = Path(__file__).resolve().parent


def _find_repo_root() -> Path:
    for p in [_PKG, *_PKG.parents]:
        if (p / "pyproject.toml").is_file() and (
            p / "examples" / "quick_tests" / "qmt_batch_hot_rank_backtest.py"
        ).is_file():
            return p
    raise RuntimeError("未找到 Vnpy_Yue 仓库根（需存在 pyproject.toml 与 examples/quick_tests/qmt_batch_hot_rank_backtest.py）")


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="交付包：三连跑批量回测，产物写入本包 产物/")
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--last-n-sessions", type=int, default=10, dest="last_n_sessions")
    ap.add_argument("--count", type=int, default=1500)
    ap.add_argument("--download", action="store_true")
    ap.add_argument(
        "--csv",
        type=Path,
        default=_PKG / "测试成分股" / "ths_hot_THS20260424-0707_交付重跑_20260508.csv",
        help="股票池 CSV（默认本包「新快照文件名」；内容可与旧快照一致）",
    )
    args = ap.parse_args()

    repo = _find_repo_root()
    batch_py = repo / "examples" / "quick_tests" / "qmt_batch_hot_rank_backtest.py"
    out_dir = _PKG / "产物"
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = "策略热股5m交付_THS20260424-0707"
    csv_abs = Path(args.csv).resolve()

    runs: list[tuple[str, list[str]]] = [
        (f"{tag}_无日线_Top{args.top}_{stamp}", []),
        (f"{tag}_日线阶段1soft_Top{args.top}_{stamp}", ["--daily-phase1"]),
        (f"{tag}_日线阶段1strict_Top{args.top}_{stamp}", ["--daily-phase1", "--daily-phase1-mode", "strict"]),
    ]

    if not csv_abs.is_file():
        print(f"找不到 CSV: {csv_abs}", file=sys.stderr)
        return 1

    for stem, extra in runs:
        xlsx = out_dir / f"{stem}.xlsx"
        cmd = [
            sys.executable,
            str(batch_py),
            "--rank-csv",
            str(csv_abs),
            "--rank-col",
            "ts_code",
            "--last-n-sessions",
            str(int(args.last_n_sessions)),
            "--top",
            str(int(args.top)),
            "--count",
            str(int(args.count)),
            "--output-xlsx",
            str(xlsx),
        ]
        if args.download:
            cmd.append("--download")
        cmd.extend(extra)
        print(">>>", " ".join(cmd), flush=True)
        r = subprocess.run(cmd, cwd=str(repo))
        if r.returncode != 0:
            print(f"失败: returncode={r.returncode} stem={stem}", file=sys.stderr)
            return int(r.returncode)

    print("\n全部完成。产物目录:", out_dir.resolve())
    for stem, _ in runs:
        print(" ", (out_dir / f"{stem}.xlsx").resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
