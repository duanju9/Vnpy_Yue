# -*- coding: utf-8 -*-
"""
小龙虾（Tushare 兼容代理）客户端：改地址 + 全局限速。

手册: http://tsy.xiaodefa.cn/docs
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from threading import Lock
from typing import Any

TSY_HTTP_URL = "http://tsy.xiaodefa.cn"
TSY_SDK_EVENT_URL = "http://tsy.xiaodefa.cn/dataapi/sdk-event"

# 120 次/分钟 => 理论最小间隔 0.5s；略加大以降低边界误判
_DEFAULT_MIN_INTERVAL = 0.55


def load_env() -> None:
    """从 ``examples/.env``、项目根 ``.env`` 加载 ``TSY_TOKEN``（若已安装 python-dotenv）。"""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    here = Path(__file__).resolve().parents[2] / "examples"
    root = Path(__file__).resolve().parents[2]
    for path in (here / ".env", root / ".env"):
        if path.is_file():
            load_dotenv(path)
            return
    load_dotenv()


class ThrottledPro:
    """包装 tushare ``pro_api``，对所有可调用属性在调用前后做全局限速。"""

    def __init__(self, pro: Any, min_interval_sec: float) -> None:
        self._pro = pro
        self._min_interval = min_interval_sec
        self._lock = Lock()
        self._last = 0.0

    def _wait_turn(self) -> None:
        with self._lock:
            now = time.monotonic()
            gap = now - self._last
            need = self._min_interval - gap
            if need > 0:
                time.sleep(need)
            self._last = time.monotonic()

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._pro, name)
        if not callable(attr):
            return attr

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            self._wait_turn()
            return attr(*args, **kwargs)

        return wrapper


def get_pro_throttled(
    *,
    min_interval_sec: float | None = None,
    configure_realtime_sdk_event: bool = False,
) -> ThrottledPro:
    """
    构造已改地址的 tushare pro 实例，并套限速包装。

    :param min_interval_sec: 两次请求最小间隔（秒）。None 时用默认 0.55（适配约 120 次/分钟）。
    :param configure_realtime_sdk_event: 若要用 realtime_quote / realtime_tick / realtime_list，
        按手册需设置 ``tushare.stock.cons.verify_token_url``，传 True。
    """
    import tushare as ts

    load_env()
    token = (os.environ.get("TSY_TOKEN") or os.environ.get("TUSHARE_TOKEN") or "").strip()
    if len(token) < 50:
        raise ValueError(
            "未找到 TSY_TOKEN：请在 examples/.env 或项目根 .env 中设置，"
            "或设置环境变量 TSY_TOKEN（56 位 key）。勿硬编码进仓库。"
            " 说明见 http://tsy.xiaodefa.cn/docs"
        )

    ts.set_token(token)
    pro = ts.pro_api()
    pro._DataApi__http_url = TSY_HTTP_URL

    if configure_realtime_sdk_event:
        from tushare.stock import cons as ct

        ct.verify_token_url = TSY_SDK_EVENT_URL

    interval = min_interval_sec if min_interval_sec is not None else _DEFAULT_MIN_INTERVAL
    return ThrottledPro(pro, interval)
