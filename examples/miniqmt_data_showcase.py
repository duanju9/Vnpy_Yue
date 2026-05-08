# -*- coding: utf-8 -*-
"""
miniQMT / xtdata：周期、字段与部分非 K 线接口的探测与 Markdown 报告。

前置：已启动 QMT 极简版或投研版；可选环境变量 MINIQMT_USERDATA。

用法::

   python examples/miniqmt_data_showcase.py
   python examples/miniqmt_data_showcase.py --code 600519.SH --out examples/quick_tests/output/miniqmt_showcase.md
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def _configure_stdio() -> None:
    if sys.platform == "win32" and isinstance(sys.stdout, io.TextIOWrapper):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _import_xtdata() -> Any:
    try:
        from xtquant import xtdata  # type: ignore
    except ImportError:
        import xtquant.xtdata as xtdata  # type: ignore
    return xtdata


def _df_brief(df: Any, max_rows: int = 4) -> str:
    try:
        s = df.head(max_rows).to_string()
        return s if s.strip() else "(空表)"
    except Exception as e:
        return f"(无法展示 DataFrame: {e})"


def _safe_download(xtdata: Any, code: str, period: str) -> str | None:
    if not hasattr(xtdata, "download_history_data"):
        return "无 download_history_data"
    try:
        xtdata.download_history_data(code, period=period, incrementally=True)
    except TypeError:
        try:
            xtdata.download_history_data(code, period=period)
        except Exception as e:
            return str(e)
    except Exception as e:
        return str(e)
    return None


def _probe_kline(
    xtdata: Any,
    code: str,
    period: str,
    count: int,
    fields: list[str],
) -> tuple[str, str]:
    err = _safe_download(xtdata, code, period)
    if err:
        return "download_fail", err
    try:
        data = xtdata.get_market_data(
            field_list=fields,
            stock_list=[code],
            period=period,
            count=count,
            dividend_type="none",
            fill_data=True,
        )
    except Exception as e:
        return "get_fail", str(e)
    if not data:
        return "empty", "返回空 dict"
    lines: list[str] = []
    for k, v in data.items():
        lines.append(f"- **{k}** shape={getattr(v, 'shape', '?')}")
        if hasattr(v, "shape") and v.size and v.shape[1] > 0:
            lines.append("```")
            lines.append(_df_brief(v, 3))
            lines.append("```")
    return "ok", "\n".join(lines)


def _strategy_section() -> str:
    return """## 可挖掘的策略规划（思路）

以下与具体标的无关，按「数据可得 → 假设可检验」组织。

### 1. 多周期联动（1m / 5m / 15m / 30m / 60m / 1d）

- **日内结构**：开盘区间突破、前 30/60 分钟区间、午盘后再择时；用 5m/15m 定义信号、1m 做执行近似。
- **跨日过滤**：日线趋势或均线位置（多头只做回踩、空头只做反弹），分钟线只做入场触发，降低噪声。
- **波动率 regime**：同一标的在不同交易日 5m 实现波动分层，高波动日缩小仓位或放宽止损。

### 2. OHLCV + 成交额（amount）

- **量价背离**：上涨缩量、下跌放量等经典形态；注意除权口径（`dividend_type`）与复权一致性。
- **流动性过滤**：低成交额时段不做突破，避免滑点假设失真（与交付文档里「滑点声明」一致）。

### 3. 合约元数据（`get_instrument_detail`）

- **涨跌停附近行为**：结合 `UpStopPrice` / `DownStopPrice` 与分钟收盘距离，研究「封板质量」或「磁吸效应」样本。
- **停牌 / 可交易标志**：回测前剔除不可交易时段，避免未来函数。

### 4. 财务与股本（`get_financial_data`）

- **慢变量过滤**：ROE、每股指标、股东户数变化等仅作 **日频或更低频** 因子，与分钟策略组合时用「最近已披露报表日」对齐，避免用未披露数据。
- **事件驱动**：财报披露日前后波动率变化（需严格事件时间轴）。

### 5. 盘口 Tick（`get_full_tick`）

- **微观结构**：买卖价差、五档失衡；更适合 **短周期预测或执行成本研究**，回测需显式假设挂单成交比例。
- **与 K 线一致性**：Tick 聚合到 5m 与 `get_market_data` 直接 5m 对比，可做数据质量校验。

### 6. Level2 / 扩展周期（若 `get_period_list` 中出现且本机有权限）

- **订单流**：委托队列、大单统计；策略容量与幸存者偏差风险更高，建议单独「研究分支」而非与 L1 混用同一套假设。

### 7. 研究流程建议

- 为每个子假设固定：**标的池、时间窗、复权口径、手续费/滑点声明、是否允许集合竞价**。
- 先 **样本外** 与 **简单基线**（随机入场、买入持有）对比，再谈参数优化。
"""


def main() -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="xtdata 周期与数据展示")
    parser.add_argument("--code", default="600519.SH", help="测试合约")
    parser.add_argument(
        "--out",
        default="",
        help="Markdown 输出路径；默认 examples/quick_tests/output/miniqmt_showcase_<时间>.md",
    )
    parser.add_argument("--count", type=int, default=3, help="K 线探测每个周期取最近 N 根")
    args = parser.parse_args()

    xtdata = _import_xtdata()
    if hasattr(xtdata, "enable_hello"):
        xtdata.enable_hello = False

    userdata = (os.environ.get("MINIQMT_USERDATA") or "").strip() or None
    if userdata:
        setattr(xtdata, "data_dir", userdata)

    try:
        if hasattr(xtdata, "connect") and callable(xtdata.connect):
            xtdata.connect()
    except Exception as e:
        print(f"[失败] 无法连接 xtquant: {e}", file=sys.stderr)
        return 1

    code = args.code
    repo = Path(__file__).resolve().parents[1]
    out_arg = (args.out or "").strip()
    if out_arg:
        out_path = Path(out_arg)
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = repo / "examples" / "quick_tests" / "output" / f"miniqmt_showcase_{ts}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    md: list[str] = []
    md.append(f"# miniQMT / xtdata 数据探测报告\n")
    md.append(f"- 生成时间: {datetime.now().isoformat(timespec='seconds')}")
    md.append(f"- 测试合约: `{code}`")
    md.append(f"- data_dir: `{getattr(xtdata, 'data_dir', None) or '(默认)'}`\n")

    # --- 服务端周期列表 ---
    md.append("## 1. `get_period_list()`（服务端声明的扩展周期）\n")
    try:
        plist = xtdata.get_period_list()
        md.append(f"共 **{len(plist)}** 条（节选前 60 条 JSON）：\n")
        md.append("```json")
        md.append(json.dumps(plist[:60], ensure_ascii=False, indent=2))
        if len(plist) > 60:
            md.append(f"... 其余 {len(plist) - 60} 条略")
        md.append("```\n")
    except Exception as e:
        md.append(f"调用失败: `{e}`\n")
        md.append(
            "> 部分极简版客户端未实现 `get_period_list`。以下 **K 线周期** 来自 xtquant `get_market_data` "
            "源码中「可走本地缓存」的集合，实际以你安装的 `xtdata.py` 为准：\n"
            "> `tick`, `1m`, `5m`, `15m`, `30m`, `60m`, `1h`, `1d`, `1w`, `1mon`, `1q`, `1hy`, `1y`。\n"
            "> 文档中还列有 Level2、期货仓单等 **扩展 period 字符串**（需权限与客户端支持），此处不逐项探测。\n"
        )

    # --- 标准 K 线周期探测（与 xtdata.get_market_data_ori 中 enable_read_from_local 集合对齐并略扩） ---
    k_periods = [
        "tick",
        "1m",
        "5m",
        "15m",
        "30m",
        "60m",
        "1h",
        "1d",
        "1w",
        "1mon",
        "1q",
        "1hy",
        "1y",
    ]
    k_fields = ["open", "high", "low", "close", "volume", "amount"]
    md.append("## 2. K 线类周期探测（`download_history_data` + `get_market_data`）\n")
    md.append(f"字段: `{k_fields}`，count=`{args.count}`\n")
    probe_results: dict[str, tuple[str, str]] = {}
    for p in k_periods:
        probe_results[p] = _probe_kline(xtdata, code, p, args.count, k_fields)
    md.append("| period | 结果 | 说明 |")
    md.append("|--------|------|------|")
    for p in k_periods:
        status, detail = probe_results[p]
        brief = detail.replace("\n", "<br>")[:500]
        if len(detail) > 500:
            brief += "…"
        md.append(f"| `{p}` | {status} | {brief} |")
    md.append("")
    md.append("各周期详细样例（仅展示 `ok` 的周期）：\n")
    for p in k_periods:
        status, detail = probe_results[p]
        if status == "ok":
            md.append(f"### `{p}`\n")
            md.append(detail + "\n")

    # --- field_list 为空：文档称 [] 为全部字段 ---
    md.append("## 3. `get_market_data(field_list=[])` 全字段（日线 count=2）\n")
    err = _safe_download(xtdata, code, "1d")
    if err:
        md.append(f"下载提示: `{err}`\n")
    try:
        full = xtdata.get_market_data(
            field_list=[],
            stock_list=[code],
            period="1d",
            count=2,
            dividend_type="none",
            fill_data=True,
        )
        md.append(f"返回字段键: `{list(full.keys())}`\n")
        for k, v in full.items():
            md.append(f"### 字段 `{k}`\n```\n{_df_brief(v, 5)}\n```\n")
    except Exception as e:
        md.append(f"失败: `{e}`\n")

    # --- 合约信息 ---
    md.append("## 4. `get_instrument_detail`（`iscomplete=True`）\n")
    try:
        inst = xtdata.get_instrument_detail(code, iscomplete=True)
        if inst is None:
            md.append("返回 None\n")
        else:
            md.append("```json")
            md.append(json.dumps(inst, ensure_ascii=False, indent=2, default=str)[:12000])
            md.append("```\n")
    except Exception as e:
        md.append(f"失败: `{e}`\n")

    # --- 财务：仅拉一张小表 ---
    md.append("## 5. `get_financial_data`（示例：`PershareIndex`，最近 8 年）\n")
    y = datetime.now().year
    start_t = f"{y - 8}0101"
    end_t = f"{y}1231"
    try:
        fin = xtdata.get_financial_data(
            stock_list=[code],
            table_list=["PershareIndex"],
            start_time=start_t,
            end_time=end_t,
            report_type="report_time",
        )
        if not fin or code not in fin:
            md.append("返回空或无该合约\n")
        else:
            for tname, tdf in fin[code].items():
                md.append(f"### 表 `{tname}`\n")
                md.append(f"行数: {len(tdf)} 列: `{list(tdf.columns)[:40]}` …\n")
                md.append("```\n")
                md.append(_df_brief(tdf, 5))
                md.append("\n```\n")
    except Exception as e:
        md.append(f"失败: `{e}`\n")

    # --- 全档 tick ---
    md.append("## 6. `get_full_tick`（当前时刻盘口快照）\n")
    try:
        tick = xtdata.get_full_tick([code])
        md.append("```json")
        md.append(json.dumps(tick, ensure_ascii=False, indent=2, default=str)[:8000])
        md.append("```\n")
    except Exception as e:
        md.append(f"失败: `{e}`\n")

    md.append(_strategy_section())

    text = "\n".join(md)
    out_path.write_text(text, encoding="utf-8")
    print(f"已写入: {out_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
