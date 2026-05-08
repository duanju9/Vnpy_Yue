# -*- coding: utf-8 -*-
"""
启动时 / 重建索引后：若已配置 PostgreSQL，将本地 ``qmt_instruments.json`` 与库表
``chan_web_instruments`` 对齐（条数不一致则全量覆盖），无需再手点「同步」。

禁用：环境变量 ``CHAN_WEB_DISABLE_AUTO_SYNC_INDEX=1``。
"""

from __future__ import annotations

import os


def _disabled() -> bool:
    v = (os.environ.get("CHAN_WEB_DISABLE_AUTO_SYNC_INDEX") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def auto_sync_instrument_index_if_needed() -> str | None:
    """
    若本地 JSON 有数据且 PG 中条数与 JSON 不一致，则 ``replace_instrument_index_in_pg``。
    :return: 成功时简短说明文案，未执行或跳过返回 None。
    """
    if _disabled():
        return None
    from instrument_pg import count_instruments_in_pg, is_pg_configured, replace_instrument_index_in_pg
    from qmt_symbol_index import load_index_json_only

    if not is_pg_configured():
        return None
    rows = load_index_json_only()
    if not rows:
        return None
    n_json = len(rows)
    n_pg = count_instruments_in_pg()
    if n_pg is not None and n_pg == n_json:
        return None
    replace_instrument_index_in_pg(rows)
    return f"合约索引已自动同步至 PostgreSQL（{n_json} 条）。"
