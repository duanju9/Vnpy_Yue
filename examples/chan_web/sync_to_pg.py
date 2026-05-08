# -*- coding: utf-8 -*-
"""
命令行：把本地 ``.cache/qmt_instruments.json`` 全量写入 PostgreSQL（表 ``chan_web_instruments``）。

会尝试加载 ``Vnpy_Yue/examples/.env``、项目根 ``.env``（若已安装 ``python-dotenv``），
读取其中的 ``CHAN_WEB_PG_URI`` 或 ``PGHOST``+``PGDATABASE``+``PGUSER`` 等。

用法（在仓库根 ``Vnpy_Yue`` 下）::

    set CHAN_WEB_PG_URI=postgresql://quantuser:密码@127.0.0.1:5432/quantdb
    python examples/chan_web/sync_to_pg.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_CHAN = Path(__file__).resolve().parent
_ROOT = _CHAN.parents[1]

sys.path.insert(0, str(_CHAN))


def main() -> int:
    from env_bootstrap import load_chan_web_env

    load_chan_web_env(_ROOT)
    from instrument_pg import is_pg_configured, replace_instrument_index_in_pg
    from qmt_symbol_index import index_cache_path, load_index_json_only

    if not is_pg_configured():
        print(
            "未配置数据库连接。请在 shell 或 examples/.env 中设置其一：\n"
            "  CHAN_WEB_PG_URI=postgresql://用户:密码@主机:5432/quantdb\n"
            "  或 PGHOST + PGPORT + PGUSER + PGPASSWORD + PGDATABASE",
            file=sys.stderr,
        )
        return 2
    rows = load_index_json_only()
    if not rows:
        print(f"未找到本地索引文件: {index_cache_path()}", file=sys.stderr)
        return 3
    try:
        n = replace_instrument_index_in_pg(rows)
    except Exception as e:
        print(f"写入失败: {e}", file=sys.stderr)
        return 1
    print(f"已写入 PostgreSQL 表 chan_web_instruments：{n} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
