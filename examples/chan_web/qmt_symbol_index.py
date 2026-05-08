# -*- coding: utf-8 -*-
"""
全市场合约索引：从 QMT ``get_sector_list`` + ``get_stock_list_in_sector`` 汇总代码，
并额外尝试常见板块名（``_EXTRA_SECTORS``），再 ``get_instrument_detail`` 取名称，供「同花顺式」输入解析。

缓存文件（勿提交）：``examples/chan_web/.cache/qmt_instruments.json``

若配置 ``CHAN_WEB_PG_URI``（或 ``PGDATABASE``+``PGUSER``），``load_index()`` **优先**从表
``chan_web_instruments`` 读取；见 ``instrument_pg.py``。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable

_CACHE_DIR = Path(__file__).resolve().parent / ".cache"
_INDEX_JSON = _CACHE_DIR / "qmt_instruments.json"

# 在 get_sector_list 之外再扫一遍，尽量覆盖 A 股/京/港股通等（名称因客户端而异，失败则跳过）。
_EXTRA_SECTORS: tuple[str, ...] = (
    "沪深A股",
    "沪深京A股",
    "上证A股",
    "深证A股",
    "北证A股",
    "北交所股票",
    "沪港通",
    "深港通",
    "创业板",
    "科创板",
    "上证50",
    "沪深300",
    "中证500",
    "中证1000",
)


def index_cache_path() -> Path:
    return _INDEX_JSON


def load_index_json_only() -> list[tuple[str, str]] | None:
    """仅从本地 ``qmt_instruments.json`` 加载，不查 PostgreSQL（CLI 推送 / 避免读到旧库）。"""
    if not _INDEX_JSON.is_file():
        return None
    try:
        data = json.loads(_INDEX_JSON.read_text(encoding="utf-8"))
    except Exception:
        return None
    rows = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return None
    out: list[tuple[str, str]] = []
    for it in rows:
        if isinstance(it, (list, tuple)) and len(it) >= 2:
            out.append((str(it[0]), str(it[1])))
        elif isinstance(it, dict) and "code" in it:
            out.append((str(it["code"]), str(it.get("name") or "")))
    return out or None


def _import_xtdata() -> Any:
    try:
        from xtquant import xtdata  # type: ignore
    except ImportError:
        import xtquant.xtdata as xtdata  # type: ignore
    return xtdata


def load_index() -> list[tuple[str, str]] | None:
    """加载 ``[(code, name), ...]``：已配置 PostgreSQL 时优先读库，否则读本地 JSON；皆无则 None。"""
    try:
        from instrument_pg import is_pg_configured, load_instrument_index_from_pg

        if is_pg_configured():
            pg_rows = load_instrument_index_from_pg()
            if pg_rows:
                return pg_rows
    except Exception:
        pass

    return load_index_json_only()


def save_index(rows: list[tuple[str, str]], *, meta: dict[str, Any] | None = None) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "version": 1,
        "saved_ts": int(time.time()),
        "rows": [{"code": c, "name": n} for c, n in rows],
    }
    if meta:
        payload["meta"] = meta
    _INDEX_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=0), encoding="utf-8")


def rebuild_index(
    xtdata: Any | None = None,
    *,
    progress: Callable[[str, float], None] | None = None,
    max_instruments: int | None = None,
) -> list[tuple[str, str]]:
    """
    连接 QMT，遍历板块拉全成分，再逐只取 ``InstrumentName``。

    :param max_instruments: 上限（调试）；默认读环境变量 ``QMT_INDEX_MAX`` 或不限。
    """
    xt = xtdata or _import_xtdata()
    if hasattr(xt, "enable_hello"):
        xt.enable_hello = False
    ud = (os.environ.get("MINIQMT_USERDATA") or "").strip()
    if ud:
        setattr(xt, "data_dir", ud)
    if hasattr(xt, "connect") and callable(xt.connect):
        xt.connect()

    if hasattr(xt, "download_sector_data"):
        try:
            xt.download_sector_data()
        except Exception:
            pass

    lim = max_instruments
    if lim is None and (os.environ.get("QMT_INDEX_MAX") or "").strip().isdigit():
        lim = int(os.environ["QMT_INDEX_MAX"].strip())

    if progress:
        progress("获取板块列表…", 0.0)
    try:
        sectors = xt.get_sector_list() or []
    except Exception as e:
        raise RuntimeError(f"get_sector_list 失败: {e}") from e
    if not isinstance(sectors, list):
        sectors = list(sectors) if sectors else []

    all_codes: list[str] = []
    seen: set[str] = set()
    for i, sec in enumerate(sectors):
        if progress and i % 20 == 0:
            progress(f"扫描板块 {i + 1}/{len(sectors)}…", min(0.35, (i + 1) / max(len(sectors), 1) * 0.35))
        if not sec or not isinstance(sec, str):
            continue
        try:
            lst = xt.get_stock_list_in_sector(sec)
        except Exception:
            continue
        if not lst:
            continue
        if not isinstance(lst, (list, tuple)):
            continue
        for c in lst:
            c = str(c).strip()
            if not c or c in seen:
                continue
            seen.add(c)
            all_codes.append(c)
            if lim is not None and len(all_codes) >= lim:
                break
        if lim is not None and len(all_codes) >= lim:
            break

    for sec in _EXTRA_SECTORS:
        if lim is not None and len(all_codes) >= lim:
            break
        if not sec:
            continue
        try:
            lst = xt.get_stock_list_in_sector(sec)
        except Exception:
            continue
        if not lst or not isinstance(lst, (list, tuple)):
            continue
        for c in lst:
            c = str(c).strip()
            if not c or c in seen:
                continue
            seen.add(c)
            all_codes.append(c)
            if lim is not None and len(all_codes) >= lim:
                break

    rows: list[tuple[str, str]] = []
    total = len(all_codes)
    for j, code in enumerate(all_codes):
        if progress and j % 200 == 0:
            progress(f"拉取合约名称 {j + 1}/{total}…", 0.35 + 0.65 * (j / max(total, 1)))
        try:
            d = xt.get_instrument_detail(code, iscomplete=False)
        except Exception:
            d = None
        name = ""
        if isinstance(d, dict):
            name = str(
                d.get("InstrumentName")
                or d.get("instrumentName")
                or d.get("Name")
                or d.get("name")
                or ""
            ).strip()
        rows.append((code, name))

    rows.sort(key=lambda x: x[0])
    meta = {
        "sector_count": len(sectors),
        "extra_sector_tried": len(_EXTRA_SECTORS),
        "instrument_count": len(rows),
    }
    save_index(rows, meta=meta)
    return rows
