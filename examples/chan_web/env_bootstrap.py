# -*- coding: utf-8 -*-
"""启动时加载 ``examples/.env``、项目根 ``.env``，使 Streamlit / CLI 无需先手动 export。"""

from __future__ import annotations

from pathlib import Path


def load_chan_web_env(repo_root: Path | None = None) -> None:
    """
    依次加载 ``{repo}/examples/.env``、``{repo}/.env``（后者不覆盖已有键）。
    未安装 ``python-dotenv`` 时静默跳过。
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[2]
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for p in (repo_root / "examples" / ".env", repo_root / ".env"):
        if p.is_file():
            load_dotenv(p, override=False)
