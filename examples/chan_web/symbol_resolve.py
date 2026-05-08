# -*- coding: utf-8 -*-
"""
将用户输入解析为 QMT 合约代码（同花顺式：代码 / 东财 SH600519 / 六位 / 中文 / 拼音缩写 / 品种.交易所）。

全市场中文/简称与代码前缀检索依赖本地索引（``qmt_symbol_index.rebuild_index``）；未建索引时仍支持 A 股六位、SH/SZ/BJ、内置别名，以及原样 ``IF2506.CFFEX`` 等 QMT 代码。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_QT = Path(__file__).resolve().parents[1] / "quick_tests"
if str(_QT) not in sys.path:
    sys.path.insert(0, str(_QT))

from qmt_5m_vol_pullback_macd_backtest import _KNOWN_STOCK_NAMES as _CODE_TO_NAME  # noqa: E402

# 拼音/键盘缩写 → QMT（无索引时也可用）
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


def _from_ths_em_style(s: str) -> str | None:
    """东财/同花顺 ``SH600519`` ``SZ000001`` ``BJ920000`` → ``600519.SH``。"""
    t = s.strip().upper().replace(" ", "")
    if len(t) < 8:
        return None
    pre = t[:2]
    if pre not in ("SH", "SZ", "BJ"):
        return None
    suf = t[2:]
    if len(suf) < 6 or not suf[:6].isdigit():
        return None
    return f"{suf[:6]}.{pre}"


def _stem_from_code(code: str) -> str:
    s = (code or "").strip().upper()
    if "." in s:
        return s.rsplit(".", 1)[0]
    return s


def _ascii_code_query(q: str) -> str | None:
    """仅字母数字点横线时视为「代码检索」前缀，避免中文走代码枝。"""
    t = (q or "").strip().upper().replace(" ", "")
    if not t or not re.match(r"^[A-Z0-9._-]+$", t):
        return None
    return t.split(".", 1)[0] if "." in t else t


def _six_digits_to_qmt(d: str) -> str:
    if len(d) != 6 or not d.isdigit():
        raise ValueError(f"不是 6 位数字代码: {d!r}")
    if d.startswith(("00", "30")):
        return f"{d}.SZ"
    if d.startswith(("43", "83", "87", "88", "92")):
        return f"{d}.BJ"
    if d.startswith(("60", "68")):
        return f"{d}.SH"
    return f"{d}.SH"


def _search_index(query: str, index: list[tuple[str, str]]) -> list[tuple[str, str]]:
    q = (query or "").strip()
    if not q or not index:
        return []
    qu = q.upper()
    exact_code: list[tuple[str, str]] = []
    exact_name: list[tuple[str, str]] = []
    prefix_name: list[tuple[str, str]] = []
    substr_name: list[tuple[str, str]] = []

    stem_exact: list[tuple[str, str]] = []
    stem_prefix: list[tuple[str, str]] = []
    ac = _ascii_code_query(q)

    for code, name in index:
        cU = code.upper()
        if qu == cU or qu.replace(".", "") == cU.replace(".", ""):
            exact_code.append((code, name))
            continue
        if ac and len(ac) >= 2:
            stem = _stem_from_code(code)
            if stem == ac:
                stem_exact.append((code, name))
                continue
            digit_only = ac.isdigit()
            min_len = 4 if digit_only else 2
            if len(ac) >= min_len and stem.startswith(ac):
                stem_prefix.append((code, name))
                continue
        if not name:
            continue
        if q == name:
            exact_name.append((code, name))
        elif name.startswith(q):
            prefix_name.append((code, name))
        elif len(q) >= 2 and q in name:
            substr_name.append((code, name))

    if exact_code:
        return exact_code[:25]
    if stem_exact:
        return stem_exact[:25]
    if stem_prefix:
        stem_prefix.sort(key=lambda x: (len(x[0]), x[0]))
        return stem_prefix[:40]
    if exact_name:
        return exact_name[:25]
    if prefix_name:
        prefix_name.sort(key=lambda x: len(x[1]))
        return prefix_name[:40]
    if substr_name:
        substr_name.sort(key=lambda x: (len(x[1]), x[0]))
        return substr_name[:40]
    return []


def resolve_instruments(raw: str, index: list[tuple[str, str]] | None = None) -> list[tuple[str, str]]:
    """
    返回所有可能匹配 ``(code, name)``，按优先级去重（保序）。
    """
    s = (raw or "").strip()
    if not s:
        return []

    merged: dict[str, str] = {}

    def add(code: str, name: str | None) -> None:
        c = (code or "").strip()
        if not c or c in merged:
            return
        merged[c] = (name or "").strip()

    # 1) 同花顺/东财风格
    em = _from_ths_em_style(s)
    if em:
        add(em, _CODE_TO_NAME.get(em))

    # 2) 标准 600519.SH
    u = s.upper().replace(" ", "")
    m = re.fullmatch(r"(\d{6})\.(SH|SZ|BJ)", u)
    if m:
        code = f"{m.group(1)}.{m.group(2)}"
        add(code, _CODE_TO_NAME.get(code))

    # 2b) QMT 原样：期货/港股等 ``IF2506.CFFEX``、``rb2510.SHFE``（排除六位+A 股所 SH/SZ/BJ）
    m_gen = re.fullmatch(r"([\w-]+)\.([A-Z][A-Z0-9]{1,15})", u)
    if m_gen:
        sym, ex = m_gen.group(1), m_gen.group(2)
        is_a_share = ex in ("SH", "SZ", "BJ") and len(sym) == 6 and sym.isdigit()
        if not is_a_share:
            qc = f"{sym}.{ex}"
            add(qc, _CODE_TO_NAME.get(qc))

    # 3) 纯六位
    t6 = re.sub(r"\s+", "", s)
    if re.fullmatch(r"\d{6}", t6) and "." not in s:
        try:
            code = _six_digits_to_qmt(t6)
            add(code, _CODE_TO_NAME.get(code))
        except ValueError:
            pass

    # 4) 小表拼音
    key = "".join(c for c in s.lower() if c.isascii() and c.isalnum())
    if key in _PINYIN_ABBREV:
        c = _PINYIN_ABBREV[key]
        add(c, _CODE_TO_NAME.get(c))

    # 5) 内置中文（无索引时）
    s0 = s.strip()
    if s0:
        for code, name in _CODE_TO_NAME.items():
            if s0 == name:
                add(code, name)
            elif len(s0) >= 2 and (name.startswith(s0) or s0 in name):
                add(code, name)

    # 6) 全市场索引
    if index:
        for code, name in _search_index(s0 or s, index):
            add(code, name)

    return [(c, merged[c]) for c in merged]


def resolve_contract(raw: str, index: list[tuple[str, str]] | None = None) -> tuple[str, str | None]:
    """
    :return: 唯一匹配 ``(code, name)``；0 或多于 1 则 ``ValueError``。
    """
    ms = resolve_instruments(raw, index)
    if len(ms) == 1:
        return ms[0][0], (ms[0][1] or None) or None
    if len(ms) == 0:
        raise ValueError(
            f"无法识别: {raw!r}。可尝试标准代码、SH600519、六位、品种.交易所、中文关键字；"
            "全市场匹配请先在本页侧边栏「构建合约索引」。"
        )
    lines = "\n".join([f"  {c}  {n}" for c, n in ms[:18]])
    raise ValueError(f"匹配到 {len(ms)} 只合约，请在下拉框选择或输入更精确：\n{lines}")
