# -*- coding: utf-8 -*-
"""从每日评分 CSV 生成文本关注池（读 buy_priority / priority_score）。"""
import csv
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: picks_report.py <csv_in> <report_out> [top_n]", file=sys.stderr)
        return 1
    csv_path = Path(sys.argv[1])
    report_path = Path(sys.argv[2])
    top_n = int(sys.argv[3]) if len(sys.argv) > 3 else 25

    def pri_key(row: dict[str, str]) -> tuple:
        try:
            bp = int(row.get("buy_priority") or 999999)
        except ValueError:
            bp = 999999
        try:
            ps = float(row.get("priority_score") or -1e9)
        except ValueError:
            ps = -1e9
        try:
            sc = float(row.get("score_0_100") or 0)
        except ValueError:
            sc = -1.0
        return (bp, -ps, -sc, row.get("code", ""))

    rows: list[dict[str, str]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("code"):
                rows.append(row)

    rows.sort(key=pri_key)

    def is_watch_buy(h: str) -> bool:
        if not h:
            return False
        if "观望或等待" in h or "信号一般" in h:
            return False
        return any(k in h for k in ("放量", "回踩", "低吸", "突破", "支撑"))

    watch = [x for x in rows if is_watch_buy(x.get("buy_hint", ""))]
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("  每日标的关注池（研究用，非投资建议）")
    lines.append("=" * 72)
    lines.append(f"CSV: {csv_path}")
    lines.append(f"标的数: {len(rows)}")
    lines.append("")
    lines.append(
        "【买入优先级说明】buy_priority=1 为最高；由 priority_score（趋势分+买点加分-卖点扣分+量比微调）排序得到。"
    )
    lines.append("-" * 72)
    for row in watch[:top_n]:
        bp = row.get("buy_priority", "")
        ps = row.get("priority_score", "")
        lines.append(
            f"P{bp} | {row.get('code', '')} | score={row.get('score_0_100', '')} | "
            f"pri_score={ps} | {row.get('name_cn', '') or '(无中文名)'}"
        )
        lines.append(f"    板块: {row.get('matched_sectors', '')}")
        lines.append(f"    买: {row.get('buy_hint', '')}")
        lines.append(f"    卖: {row.get('sell_hint', '')}")
        lines.append("")

    m = min(15, top_n)
    lines.append("【总榜前 " + str(m) + "（按 buy_priority）】")
    lines.append("-" * 72)
    for row in rows[:m]:
        lines.append(
            f"P{row.get('buy_priority','')} {row.get('code','')} score={row.get('score_0_100','')} "
            f"pri={row.get('priority_score','')} | {(row.get('buy_hint','') or '')[:80]}"
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(str(report_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
