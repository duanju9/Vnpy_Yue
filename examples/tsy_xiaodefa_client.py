# -*- coding: utf-8 -*-
"""
第三方 Tushare 兼容代理（小龙虾等）对接示例 — 限速 + 改地址

实现已迁移至 ``vnpy.feeds.tsy_pro``；本文件保留**向后兼容**的示例入口与
``fetch_daily_recent`` 便捷函数。

手册: http://tsy.xiaodefa.cn/docs
有效期查询: http://tsy.xiaodefa.cn/youxiaoqi

使用前:
  pip install tushare pandas python-dotenv

认证（勿把 key 写进代码或提交 Git）:
  1) 本目录或项目根目录的 .env 中 TSY_TOKEN=...（推荐）
  2) 环境变量 TSY_TOKEN 或 TUSHARE_TOKEN

新代码请优先使用::

    from vnpy.feeds import get_pro_throttled, fetch_daily_cached
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pandas as pd

if sys.platform == "win32" and isinstance(sys.stdout, io.TextIOWrapper):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from vnpy.feeds.tsy_pro import (  # noqa: E402
    TSY_HTTP_URL,
    TSY_SDK_EVENT_URL,
    ThrottledPro,
    get_pro_throttled,
    load_env,
)

__all__ = [
    "TSY_HTTP_URL",
    "TSY_SDK_EVENT_URL",
    "ThrottledPro",
    "get_pro_throttled",
    "load_env",
    "fetch_daily_recent",
]


def fetch_daily_recent(
    ts_code: str,
    *,
    days_calendar: int = 7,
    pro: ThrottledPro | None = None,
) -> pd.DataFrame:
    """
    拉取最近约 ``days_calendar`` 个自然日内的日线（量价），用于快速量价查看。

    注意: Tushare ``daily`` 按 ``start_date`` / ``end_date`` 过滤交易日，这里用日历日粗略回推。
    """
    pro = pro or get_pro_throttled()
    end = pd.Timestamp.now().normalize()
    start = end - pd.Timedelta(days=days_calendar + 7)
    df = pro.daily(
        ts_code=ts_code,
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
    )
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.sort_values("trade_date")
    return df.tail(max(days_calendar, 5))


def _self_test() -> None:
    """本地自检：天赐材料 002709.SZ 近期日线（需 TSY_TOKEN）。"""
    load_env()
    ts_code = "002709.SZ"
    name = "天赐材料"
    pro = get_pro_throttled()
    df = fetch_daily_recent(ts_code, days_calendar=40, pro=pro)
    print(f"{name} {ts_code} 日线（量价） 最近 {len(df)} 条")
    if df.empty:
        print("无数据：请检查代码权限、网络或是否触发限速冷却。")
        return
    cols = [c for c in ("trade_date", "open", "high", "low", "close", "vol", "amount") if c in df.columns]
    print(df[cols].to_string(index=False))


if __name__ == "__main__":
    _self_test()
