"""
miniQMT / XtQuant 连通性探测脚本（不依赖 vnpy 核心）。

前置条件
----------
1. 已安装并启动 **miniQMT** 客户端（保持登录、行情服务正常）。
2. Python 能 import **xtquant**（库通常随 QMT/miniQMT 安装目录提供，见官方说明）。
3. 若自动发现数据目录失败，设置环境变量 ``MINIQMT_USERDATA`` 为 **userdata_mini** 的绝对路径
   （例如 ``D:/国金QMT交易端/userdata_mini``，以本机实际为准）。

文档与示例
----------
- https://www.miniqmt.com/pages/examples/index.html
- XtData 行情模块说明见 miniQMT 官方 API 文档

用法
----------
.. code-block:: text

   set MINIQMT_USERDATA=D:\\path\\to\\userdata_mini
   python examples/miniqmt_try.py
   python examples/miniqmt_try.py --code 600519.SH --count 5
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any


def _import_xtdata() -> Any:
    try:
        from xtquant import xtdata  # type: ignore
    except ImportError:
        try:
            import xtquant.xtdata as xtdata  # type: ignore
        except ImportError as e:  # pragma: no cover
            print(
                "无法导入 xtquant：请确认已安装 miniQMT，且当前 Python 与 xtquant 支持的版本一致。\n"
                "常见做法：使用 QMT 安装目录自带的 python.exe，或将 xtquant 所在目录加入 PYTHONPATH。",
                file=sys.stderr,
            )
            raise e
    return xtdata


def main() -> int:
    parser = argparse.ArgumentParser(description="miniQMT / xtdata 连通性与行情拉取探测")
    parser.add_argument(
        "--userdata",
        default=os.environ.get("MINIQMT_USERDATA", "").strip() or None,
        help="userdata_mini 绝对路径；不设则读环境变量 MINIQMT_USERDATA，仍不设则交给 xtdata 自动发现",
    )
    parser.add_argument("--code", default="000001.SZ", help="合约代码，如 000001.SZ、600519.SH")
    parser.add_argument("--period", default="1d", help="K 线周期，如 1d、5m、1m")
    parser.add_argument("--count", type=int, default=5, help="取最近 N 根（>=0）")
    parser.add_argument(
        "--download",
        action="store_true",
        help="调用 download_history_data 增量下载该标的日线后再取数（首次无缓存时可试）",
    )
    args = parser.parse_args()

    xtdata = _import_xtdata()
    if hasattr(xtdata, "enable_hello"):
        xtdata.enable_hello = False  # 关闭 xtdata 连接成功时的横幅打印

    if args.userdata:
        # 文档：可改 xtdata.data_dir 指向 userdata_mini，便于本地文件直连
        setattr(xtdata, "data_dir", args.userdata)
        print(f"[配置] xtdata.data_dir = {args.userdata}")

    if hasattr(xtdata, "connect"):
        fn = getattr(xtdata, "connect")
        if callable(fn):
            try:
                ret = fn()
                print(f"[xtdata.connect] 返回: {ret!r}")
            except Exception as e:  # pragma: no cover
                print(f"[xtdata.connect] 调用异常（部分版本可不调用）: {e}")

    field_list = ["open", "high", "low", "close", "volume"]
    stock_list = [args.code]

    if args.download and hasattr(xtdata, "download_history_data"):
        print(f"[下载] download_history_data({args.code!r}, period={args.period!r}, ...)")
        try:
            xtdata.download_history_data(args.code, period=args.period, incrementally=True)
        except TypeError:
            # 部分版本签名不同，退回最简调用
            xtdata.download_history_data(args.code, period=args.period)
        except Exception as e:
            print(f"[下载] 调用异常（可改在 miniQMT 客户端内手动下载行情）: {e}")

    print(f"[请求] get_market_data period={args.period!r} count={args.count} stock_list={stock_list}")
    try:
        data = xtdata.get_market_data(
            field_list=field_list,
            stock_list=stock_list,
            period=args.period,
            count=args.count,
            dividend_type="none",
            fill_data=True,
        )
    except Exception as e:
        print(f"[失败] get_market_data 异常: {e}", file=sys.stderr)
        print(
            "排查：1) miniQMT 是否已启动；2) 合约代码格式是否为 000001.SZ；"
            "3) 是否需先下载历史数据（客户端或 download_history_data）；4) MINIQMT_USERDATA 是否正确。",
            file=sys.stderr,
        )
        return 1

    if not data:
        print("[结果] 返回空 dict，可能本地无缓存或未订阅，请在客户端确认行情/下载后再试。")
        return 2

    print("[结果] 字段键:", list(data.keys()))
    empty = True
    for field, table in data.items():
        print(f"--- {field} ---")
        print(table)
        if hasattr(table, "columns") and len(table.columns) > 0:
            empty = False
    if empty:
        print(
            "[提示] 行情表无时间列：多为本地尚未缓存该周期数据。"
            "可在 miniQMT 里补充/下载行情后重试，或执行: python examples/miniqmt_try.py --download"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
