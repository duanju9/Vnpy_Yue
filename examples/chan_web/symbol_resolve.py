# -*- coding: utf-8 -*-
"""
将用户输入解析为 QMT 合约代码 ``000001.SZ`` / ``600519.SH``。

支持：标准代码、六位数字、中文简称/前缀、常用拼音缩写（可扩展 ``_PINYIN_ABBREV``）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_QT = Path(__file__).resolve().parents[1] / "quick_tests"
if str(_QT) not in sys.path:
    sys.path.insert(0, str(_QT))

from qmt_5m_vol_pullback_macd_backtest import _KNOWN_STOCK_NAMES as _CODE_TO_NAME  # noqa: E402

# 拼音/键盘缩写 → QMT 代码（小写无空格匹配）
_PINYIN_ABBREV: dict[str, str] = {
    "tccl": "002709.SZ",
    "tianxi": "002709.SZ",
    "tianxicailiao": "002709.SZ",
    "tc": "002709.SZ",
    "gzmt": "600519.SH",
    "mt": "600519.SH",
    "maotai": "600519.SH",
    "gflh": "002460.SZ",
    "ganfeng": "002460.SZ",
    "zskj": "603601.SH",
    "zaisheng": "603601.SH",
    "payh": "000001.SZ",
    "pingan": "000001.SZ",
    "lfdl": "000537.SZ",
    "lvfa": "000537.SZ",
    "zgzg": "601989.SH",
    "zhongguozhonggong": "601989.SH",
}


def _six_digits_to_qmt(d: str) -> str:
    if len(d) != 6 or not d.isdigit():
        raise ValueError(f"不是 6 位数字代码: {d!r}")
    if d.startswith(("00", "30")):
        return f"{d}.SZ"
    return f"{d}.SH"


def resolve_contract(raw: str) -> tuple[str, str | None]:
    """
    :return: ``(qmt_code, 中文名或 None)``
    :raises ValueError: 无法识别或歧义
    """
    s = (raw or "").strip()
    if not s:
        raise ValueError("请输入合约代码、六位数字、中文简称或拼音缩写")

    u = s.upper().replace(" ", "")
    m = re.fullmatch(r"(\d{6})\.(SH|SZ)", u)
    if m:
        code = f"{m.group(1)}.{m.group(2)}"
        return code, _CODE_TO_NAME.get(code)

    t6 = re.sub(r"\s+", "", s)
    if re.fullmatch(r"\d{6}", t6) and "." not in s:
        code = _six_digits_to_qmt(t6)
        return code, _CODE_TO_NAME.get(code)

    # 纯字母数字缩写（tccl、gzmt）
    key = "".join(c for c in s.lower() if c.isascii() and c.isalnum())
    if key in _PINYIN_ABBREV:
        code = _PINYIN_ABBREV[key]
        return code, _CODE_TO_NAME.get(code)

    # 中文：完全匹配 → 前缀匹配（至少 2 字）
    s0 = s.strip()
    if len(s0) >= 1:
        exact: list[tuple[str, str]] = []
        prefix: list[tuple[str, str]] = []
        for code, name in _CODE_TO_NAME.items():
            if s0 == name:
                exact.append((code, name))
            elif len(s0) >= 2 and name.startswith(s0):
                prefix.append((code, name))
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            raise ValueError(f"中文完全匹配歧义: {exact!r}")
        if prefix:
            if len(prefix) == 1:
                return prefix[0]
            names = [n for _, n in prefix]
            raise ValueError(f"「{s0}」匹配多只标的: {', '.join(names)}，请输入更全的简称或六位代码")

    raise ValueError(f"无法识别: {raw!r}。示例: 600519.SH、002709、天赐、tccl")
