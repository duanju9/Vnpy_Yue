# -*- coding: utf-8 -*-
"""
K 线 + 简易分形压力/支撑（Plotly），行情以 **miniQMT** 为准；已配置 PG 时，**打开页面自动**对齐合约索引入库，QMT 拉线成功后自动写 K 线缓存。启动时加载 ``examples/.env``。

运行::

   cd Vnpy_Yue
   pip install -r examples/chan_web/requirements-chan-web.txt
   streamlit run examples/chan_web/app.py --server.headless true

局域网给友人访问::

   streamlit run examples/chan_web/app.py --server.headless true --server.address 0.0.0.0 --server.port 8501

浏览器手动打开 http://localhost:8501 或 http://本机IP:8501 （headless 不自动弹窗；同一 WiFi 下手机也可访问）

说明: 默认 **浅色 + 红涨绿跌**（整体配色同前）；画法参考 Zen：**紫中枢、橙线段、灰蓝笔、量柱随涨跌着色、底部范围滑块**；可选「终端深色」主题。叠 chan **笔 / 线段 / 中枢**。分形与 chan 可并存。
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pandas as pd

try:
    import streamlit as st
except ImportError:
    print("请先安装: pip install -r examples/chan_web/requirements-chan-web.txt", file=sys.stderr)
    raise

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT / "examples" / "chan_web"))

from env_bootstrap import load_chan_web_env  # noqa: E402

load_chan_web_env(_ROOT)

from chan_plotly_overlay import (  # noqa: E402
    ChanOverlay,
    compute_chan_overlay,
    is_chan_overlay_qmt_refetch_enabled,
    is_chan_vendor_ready,
)
from chan_web_chart import build_figure  # noqa: E402
from instrument_pg import is_pg_configured, replace_instrument_index_in_pg  # noqa: E402
from qmt_symbol_index import load_index, rebuild_index  # noqa: E402
from symbol_resolve import resolve_instruments  # noqa: E402

# 侧边栏显示：用于确认已拉取到含「合约别名」的最新脚本（改代码后请结束旧 Streamlit 再启）
CHAN_WEB_BUILD = "light-zen-draw-style-v6"


def main() -> None:
    st.set_page_config(page_title="K线 / 压力支撑研究", layout="wide")

    if "_chan_startup_pg_once" not in st.session_state:
        st.session_state["_chan_startup_pg_once"] = True
        try:
            from startup_pg_sync import auto_sync_instrument_index_if_needed

            _m = auto_sync_instrument_index_if_needed()
            if _m:
                st.session_state.pop("instrument_index", None)
                if hasattr(st, "toast"):
                    st.toast(_m, icon="💾")
                else:
                    st.session_state["_chan_instrument_sync_toast"] = _m
        except Exception:
            pass

    st.title("K 线 + 分形压力/支撑（研究用）")
    st.caption(
        "优先：chan.py + QMT 见仓库 `examples/chan_web/integrate_chan_py/`。"
        "本页为轻量 K 线与分形（[chan.py](https://github.com/Vespa314/chan.py) 建议 Python 3.11+）。"
    )

    resolve_code = ""
    resolve_err: str | None = None
    show_chan = False

    with st.sidebar:
        st.caption(f"chan_web 构建 `{CHAN_WEB_BUILD}` · 更新后若别名无效，请先关掉旧 Streamlit 进程再启动")
        _toast = st.session_state.pop("_chan_instrument_sync_toast", None)
        if _toast:
            st.success(_toast)
        st.header("数据")
        src = st.radio(
            "来源",
            ("miniQMT (xtdata)", "上传 CSV"),
            index=0,
            help="K 线优先 miniQMT；已配置 PG 时成功拉取后自动写库，失败/空表时读 chan_web_ohlcv_cache。",
        )
        if st.button("构建/更新全市场合约索引（较慢）", help="从 QMT 板块汇总代码并拉名称；中文/简称搜索依赖此索引"):
            try:
                prog = st.progress(0.0)
                stat = st.empty()

                def _cb(msg: str, frac: float) -> None:
                    stat.text(msg)
                    prog.progress(min(1.0, max(0.0, frac)))

                rows = rebuild_index(progress=_cb)
                prog.progress(1.0)
                st.session_state["instrument_index"] = rows
                hint = f"已写入 {len(rows)} 条到本地 JSON 缓存。"
                if is_pg_configured():
                    try:
                        replace_instrument_index_in_pg(rows)
                        hint += " 已同步写入 PostgreSQL（表 chan_web_instruments）。"
                    except Exception as e_pg:
                        hint += f" PostgreSQL 写入失败：{e_pg}"
                st.success(hint)
                st.rerun()
            except Exception as e:
                st.error(f"索引失败: {e}")
        if is_pg_configured():
            st.caption(
                "已配置 PG：打开页面时会自动把 **本地 JSON 索引** 与库对齐；"
                "K 线在 QMT 成功后自动写入 **chan_web_ohlcv_cache**。关闭：`CHAN_WEB_DISABLE_AUTO_SYNC_INDEX` / `CHAN_WEB_DISABLE_PG_OHLCACHE`。"
            )
        idx_hint = st.session_state.get("instrument_index")
        if idx_hint is None:
            idx_hint = load_index()
            if idx_hint is not None:
                st.session_state["instrument_index"] = idx_hint
        if st.session_state.get("instrument_index"):
            st.caption(f"已加载合约索引 **{len(st.session_state['instrument_index'])}** 条（优先 PostgreSQL，否则本地 JSON）")
        else:
            st.caption("尚未构建索引：仍可用 **代码/SH600519/六位/拼音缩写**；**中文全市场**请先点上方按钮。")

        code_raw = st.text_input(
            "合约（同花顺式：代码 / SH600519 / 六位 / 中文 / 拼音）",
            value="600519.SH",
            help="全市场中文需先构建索引；支持 A 股/京/港股通等；也可直接粘贴 QMT 代码如 IF2506.CFFEX。",
        )
        use_qmt = src.startswith("miniQMT")

        if use_qmt:
            idx = st.session_state.get("instrument_index")
            if idx is None:
                idx = load_index()
            try:
                matches = resolve_instruments(code_raw, idx)
                if len(matches) == 0:
                    raise ValueError(
                        "无匹配。可试：600519.SH、SH600519、六位、品种.交易所、中文关键字；"
                        "中文全市场请先「构建合约索引」（有 PG 时会自动入库）。"
                    )
                if len(matches) == 1:
                    resolve_code, cname = matches[0][0], matches[0][1]
                    label = f"{resolve_code}（{cname}）" if cname else resolve_code
                    st.success(f"已识别：{label}")
                else:
                    labels = [f"{c} | {n or '?'}" for c, n in matches]
                    chosen = st.selectbox("多条匹配，请选一条", labels, key="chan_web_sym_pick")
                    resolve_code, sep, rest = chosen.partition("|")
                    resolve_code = resolve_code.strip()
                    cname = rest.strip() if sep else ""
                    st.info(f"已选用：**{resolve_code}**" + (f"（{cname}）" if cname else ""))
            except ValueError as e:
                resolve_err = str(e)
            except Exception as e:
                resolve_err = f"合约解析异常: {e}"

        use_pg_ohlcv_backup = False
        if use_qmt:
            use_pg_ohlcv_backup = is_pg_configured() and (
                (os.environ.get("CHAN_WEB_DISABLE_PG_OHLCACHE") or "").strip().lower()
                not in ("1", "true", "yes", "on")
            )
            period = st.selectbox("周期", ("5m", "1d"), index=0)
            count = st.number_input("K 线根数 (QMT)", min_value=50, max_value=50000, value=2000, step=100)
            download = st.checkbox("download_history_data 增量", value=True)
        else:
            period = "1d"
            count = 2000
            download = False
            use_pg_ohlcv_backup = False
        show_frac = st.checkbox("显示分形高/低 + 水平参考线", value=True)
        frac_n = st.slider("分形点数量（每侧）", 4, 30, 12)
        st.subheader("指标与外观")
        chart_theme = st.selectbox(
            "图表主题",
            options=("light", "terminal"),
            index=0,
            format_func=lambda x: (
                "浅色（默认，红涨·绿跌）" if x == "light" else "终端深色（红涨·青跌）"
            ),
            help="浅色：沿用原先页面配色；缠论画法参考 Zen（紫中枢、橙线段等）。终端：整图深色 + 青跌 K 线。",
        )
        show_ma = st.checkbox("均线 MA", value=True)
        ma_periods = tuple(
            st.multiselect(
                "MA 周期",
                options=[5, 10, 20, 30, 60, 120],
                default=[5, 10, 20],
                disabled=not show_ma,
                help="叠加在 K 线上的算术均线；关闭「均线 MA」时不绘制。",
            )
        )
        show_macd = st.checkbox("MACD 子图", value=False)
        show_kdj = st.checkbox("KDJ 子图", value=False)
        with st.expander("MACD / KDJ 参数", expanded=False):
            c1, c2 = st.columns(2)
            with c1:
                macd_fast = st.number_input("MACD 快线", min_value=2, max_value=60, value=12, step=1, key="macd_f")
                macd_slow = st.number_input("MACD 慢线", min_value=3, max_value=120, value=26, step=1, key="macd_s")
            with c2:
                macd_signal = st.number_input("MACD 信号", min_value=2, max_value=60, value=9, step=1, key="macd_sig")
                kdj_n = st.number_input("KDJ 周期 n", min_value=3, max_value=60, value=9, step=1, key="kdj_n")
            c3, c4 = st.columns(2)
            with c3:
                kdj_m1 = st.number_input("K 平滑 m1", min_value=2, max_value=30, value=3, step=1, key="kdj_m1")
            with c4:
                kdj_m2 = st.number_input("D 平滑 m2", min_value=2, max_value=30, value=3, step=1, key="kdj_m2")
        _chan_ov_disabled = (os.environ.get("CHAN_WEB_DISABLE_CHAN_OVERLAY") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if use_qmt and not _chan_ov_disabled and is_chan_vendor_ready():
            show_chan = st.checkbox(
                "叠 chan 笔/中枢（同图，再跑 CChan；默认用当前表内 K 线、不重复拉 xtdata）",
                value=False,
                help="需 `examples/chan_web/vendor/chan` 与 chan 依赖；默认把本页已加载的 OHLCV 喂给 CChan。调试可设 `CHAN_WEB_CHAN_OVERLAY_USE_QMT_REFETCH=1` 强制走 xtdata。与分形层可同时开启。",
            )
        elif use_qmt and _chan_ov_disabled:
            st.caption("chan 叠加已关闭：`CHAN_WEB_DISABLE_CHAN_OVERLAY=1`。")
        elif use_qmt and not is_chan_vendor_ready():
            st.caption("可选：将 chan.py 置于 `vendor/chan/` 后，可勾选「叠 chan 笔/中枢」。")
        up = None
        if not use_qmt:
            up = st.file_uploader("CSV 文件", type=["csv"])

    df: pd.DataFrame | None = None
    err: str | None = None
    kline_src = ""
    code = (code_raw or "").strip()
    use_qmt = src.startswith("miniQMT")

    if use_qmt:
        err = resolve_err
        code = resolve_code.strip() if resolve_code else ""
        if not err and code:
            try:
                from data_qmt import fetch_ohlcv_with_pg_cache

                with st.spinner("miniQMT 拉取行情（必要时读库缓存）…"):
                    df, kline_src = fetch_ohlcv_with_pg_cache(
                        code,
                        period,
                        int(count),
                        download=download,
                        use_pg_backup=use_pg_ohlcv_backup,
                    )
                if (df is None or df.empty) and kline_src == "empty":
                    err = "未取到 K 线：miniQMT 无数据且库中无缓存（可开启上方「写入 PG」并先成功拉过一次）。"
            except Exception as e:
                err = str(e)
    elif up is not None:
        try:
            from data_qmt import load_csv

            df = load_csv(up)
            code = up.name or "CSV"
        except Exception as e:
            err = str(e)

    tab_chart, tab_raw, tab_help = st.tabs(["图表", "数据表", "说明与部署"])

    with tab_help:
        st.markdown(
            """
### 你要的两件事

1. **AI / 缠论式看图与回测**  
   - 本页 **分形高/低** 只是几何近似，帮助肉眼扫压力/支撑，**不是** chan.py 的买卖点。  
   - **指标 / 外观**：**MA**、**MACD / KDJ**；默认浅色；缠论层画法参考 Zen（紫中枢、橙线段、量柱随涨跌）；**终端深色**为可选整图主题。  
   - **可选**：勾选「叠 chan 笔/中枢」时用本地 `vendor/chan` 跑 `CChan`；默认用当前页 K 线喂入、不重复拉 xtdata；与分形层可并存。  
   - 亦可克隆 `chan.py` 后自行导出结构 JSON，接到本仓库回测脚本（时间戳对齐即可）。

2. **网页给自已和朋友看**  
   - 本机: `streamlit run examples/chan_web/app.py`  
   - 同一局域网: 加 `--server.address 0.0.0.0 --server.port 8501`，浏览器访问 `http://你的电脑IP:8501`  
   - **无登录**，勿公网裸奔；外网可自建密码或 VPN，或用云主机 + Nginx 鉴权。

### QMT

请先打开 **miniQMT / QMT**；可选环境变量 `MINIQMT_USERDATA` 指向 `userdata_mini`。

**全市场中文/简称**：侧边栏点「构建/更新全市场合约索引」，从 QMT 全板块 + 常见补充板块拉成分与名称；构建过程会显示进度条。也可直接输入 **品种.交易所**（如期货 `IF2506.CFFEX`），不依赖中文索引。

**PostgreSQL**：在 `examples/.env` 配置 `CHAN_WEB_PG_URI` 等（本机端口常为 **5433**）。  
- **合约索引**：表 `chan_web_instruments`；每次打开页面若与本地 JSON 条数不一致会 **自动全量同步**（重建索引后也会自动写入）。  
- **K 线**：表 `chan_web_ohlcv_cache`；QMT **成功即自动写入**；QMT 失败或空表时 **自动读库**。关闭自动：`CHAN_WEB_DISABLE_AUTO_SYNC_INDEX=1`（仅索引）、`CHAN_WEB_DISABLE_PG_OHLCACHE=1`（仅 K 线缓存）。
- **chan 叠加**：`CHAN_WEB_DISABLE_CHAN_OVERLAY=1` 可关闭侧边栏「叠 chan 笔/中枢」。默认用当前页 K 线喂 CChan、不重复拉 xtdata；调试可设 `CHAN_WEB_CHAN_OVERLAY_USE_QMT_REFETCH=1` 强制走 xtdata。CChan 侧会 **剔除 OHLC 任一为 NaN 的 K 线**（蜡烛图仍用原始表）。
            """
        )

    chan_ov: ChanOverlay | None = None
    if use_qmt and show_chan and df is not None and not df.empty and code and not err:
        ckey = (
            "chan_overlay_v4",
            code,
            period,
            len(df),
            str(df.index[-1]),
            str(df.index[0]),
            str(round(float(df["close"].iloc[-1]), 8)) if "close" in df.columns else "",
            kline_src or "",
            int(count),
            bool(download),
            str(is_chan_overlay_qmt_refetch_enabled()),
        )
        if st.session_state.get("_chan_ov_key") != ckey:
            with st.spinner("chan.py 计算笔/中枢（默认使用当前表内 K 线）…"):
                st.session_state["_chan_ov_key"] = ckey
                st.session_state["_chan_ov_val"] = compute_chan_overlay(code, period, df)
        chan_ov = st.session_state.get("_chan_ov_val")

    with tab_chart:
        if err:
            st.error(err)
        elif df is None or df.empty:
            if use_qmt and code and not err:
                st.warning(
                    f"合约 **{code}** 已解析，但未取到 K 线（空表）。"
                    "请确认 miniQMT 已登录、已勾选「增量下载」，或减小时间范围/根数后再试。"
                )
            else:
                st.info("请选择 miniQMT 或上传 CSV；miniQMT 需客户端已登录。")
        else:
            title = f"{code} {period} 共 {len(df)} 根"
            if kline_src == "pg_cache":
                title += "（PostgreSQL 缓存·miniQMT 当时无数据）"
                st.info("当前 K 线来自 **PostgreSQL 缓存**；有新数据时请以 miniQMT 为准重新拉取。")
            _co = chan_ov if (use_qmt and show_chan) else None
            if use_qmt and show_chan:
                if _co is not None:
                    _n_seg = len(getattr(_co, "seg_segments", ()) or ())
                    st.caption(f"chan：笔 {len(_co.bi_segments)} · 线段 {_n_seg} · 中枢 {len(_co.zs_boxes)}")
                else:
                    st.caption("chan 叠加：未得到笔/中枢或 CChan/xtquant 不可用；仍显示 K 线与分形。")
            _ma_key = tuple(sorted(ma_periods)) if (show_ma and ma_periods) else ()
            fig = build_figure(
                df,
                title,
                show_fractal=show_frac,
                fractal_n=int(frac_n),
                chan_overlay=_co,
                uirevision=(
                    f"{code}|{period}|th{chart_theme}|ma{int(show_ma)}{_ma_key}|macd{int(show_macd)}"
                    f"{int(macd_fast)}{int(macd_slow)}{int(macd_signal)}|kdj{int(show_kdj)}"
                    f"{int(kdj_n)}{int(kdj_m1)}{int(kdj_m2)}"
                ),
                chart_theme=chart_theme,
                show_ma=show_ma,
                ma_periods=_ma_key,
                show_macd=show_macd,
                show_kdj=show_kdj,
                macd_fast=int(macd_fast),
                macd_slow=int(macd_slow),
                macd_signal=int(macd_signal),
                kdj_n=int(kdj_n),
                kdj_m1=int(kdj_m1),
                kdj_m2=int(kdj_m2),
            )
            st.plotly_chart(fig, width="stretch")

    with tab_raw:
        if err or df is None or df.empty:
            st.caption("有有效数据后在此显示表格与导出。")
        else:
            st.dataframe(df.tail(500), width="stretch")
            buf = io.StringIO()
            df.to_csv(buf)
            st.download_button("下载当前表 CSV", buf.getvalue(), file_name="ohlcv_export.csv", mime="text/csv")


if __name__ == "__main__":
    main()
