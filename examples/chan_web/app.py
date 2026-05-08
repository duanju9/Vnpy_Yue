# -*- coding: utf-8 -*-
"""
K 线 + 简易分形压力/支撑（Plotly），数据源可选 miniQMT 或 CSV。

运行::

   cd Vnpy_Yue
   pip install -r examples/chan_web/requirements-chan-web.txt
   streamlit run examples/chan_web/app.py

局域网给友人访问::

   streamlit run examples/chan_web/app.py --server.address 0.0.0.0 --server.port 8501

浏览器打开: http://本机IP:8501 （同一 WiFi 下手机也可访问）

说明: 完整缠论（笔/线段/中枢）请自行克隆 Vespa314/chan.py（Python>=3.11），
本页不内置其依赖；分形层为研究用近似，不等同于 chan.py 买卖点。
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

try:
    import streamlit as st
except ImportError:
    print("请先安装: pip install -r examples/chan_web/requirements-chan-web.txt", file=sys.stderr)
    raise

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT / "examples" / "chan_web"))

from fractal_levels import fractal_high_low  # noqa: E402


def _fig_candle(df: pd.DataFrame, title: str, *, show_fractal: bool, fractal_n: int) -> go.Figure:
    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    df = df.sort_index()

    has_vol = "volume" in df.columns
    if has_vol:
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.72, 0.28])
    else:
        fig = go.Figure()

    candle = go.Candlestick(
        x=df.index,
        open=df["open"],
        high=df["high"],
        low=df["low"],
        close=df["close"],
        name="OHLC",
    )
    if has_vol:
        fig.add_trace(candle, row=1, col=1)
    else:
        fig.add_trace(candle)

    if show_fractal:
        hi, lo = fractal_high_low(df, last_n_peaks=fractal_n)
        if not hi.empty:
            sc_h = go.Scatter(
                x=hi["time"],
                y=hi["price"],
                mode="markers",
                name="分形高(压力)",
                marker=dict(symbol="triangle-down", size=10, color="#e74c3c"),
            )
            (fig.add_trace(sc_h, row=1, col=1) if has_vol else fig.add_trace(sc_h))
            for y in hi["price"].tail(5).tolist():
                if has_vol:
                    fig.add_hline(y=y, line_dash="dot", line_color="rgba(231,76,60,0.45)", row=1, col=1)
                else:
                    fig.add_hline(y=y, line_dash="dot", line_color="rgba(231,76,60,0.45)")
        if not lo.empty:
            sc_l = go.Scatter(
                x=lo["time"],
                y=lo["price"],
                mode="markers",
                name="分形低(支撑)",
                marker=dict(symbol="triangle-up", size=10, color="#27ae60"),
            )
            (fig.add_trace(sc_l, row=1, col=1) if has_vol else fig.add_trace(sc_l))
            for y in lo["price"].tail(5).tolist():
                if has_vol:
                    fig.add_hline(y=y, line_dash="dot", line_color="rgba(39,174,96,0.45)", row=1, col=1)
                else:
                    fig.add_hline(y=y, line_dash="dot", line_color="rgba(39,174,96,0.45)")

    if has_vol:
        fig.add_trace(
            go.Bar(x=df.index, y=df["volume"], name="成交量", marker_color="#7f8c8d"),
            row=2,
            col=1,
        )
        fig.update_layout(
            title=title,
            xaxis_rangeslider_visible=False,
            height=720,
            legend_orientation="h",
            margin=dict(l=48, r=24, t=56, b=40),
        )
        fig.update_yaxes(title_text="价", row=1, col=1)
        fig.update_yaxes(title_text="量", row=2, col=1)
    else:
        fig.update_layout(
            title=title,
            xaxis_rangeslider_visible=False,
            height=560,
            margin=dict(l=48, r=24, t=56, b=40),
        )
    return fig


def main() -> None:
    st.set_page_config(page_title="K线 / 压力支撑研究", layout="wide")
    st.title("K 线 + 分形压力/支撑（研究用）")
    st.caption(
        "优先：chan.py + QMT 见仓库 `examples/chan_web/integrate_chan_py/`。"
        "本页为轻量 K 线与分形（[chan.py](https://github.com/Vespa314/chan.py) 建议 Python 3.11+）。"
    )

    with st.sidebar:
        st.header("数据")
        src = st.radio("来源", ("miniQMT (xtdata)", "上传 CSV"), index=0)
        code = st.text_input("合约代码", value="600519.SH", help="QMT 格式，如 600519.SH")
        period = st.selectbox("周期", ("5m", "1d"), index=0)
        count = st.number_input("K 线根数 (QMT)", min_value=50, max_value=50000, value=2000, step=100)
        download = st.checkbox("download_history_data 增量", value=True)
        show_frac = st.checkbox("显示分形高/低 + 水平参考线", value=True)
        frac_n = st.slider("分形点数量（每侧）", 4, 30, 12)
        up = None
        if not src.startswith("miniQMT"):
            up = st.file_uploader("CSV 文件", type=["csv"])

    df: pd.DataFrame | None = None
    err: str | None = None

    if src.startswith("miniQMT"):
        try:
            from data_qmt import fetch_ohlcv

            with st.spinner("连接 QMT 并拉取行情…"):
                df = fetch_ohlcv(code, period, int(count), download=download)
        except Exception as e:
            err = str(e)
    elif up is not None:
        try:
            from data_qmt import load_csv

            df = load_csv(up)
        except Exception as e:
            err = str(e)

    tab_chart, tab_raw, tab_help = st.tabs(["图表", "数据表", "说明与部署"])

    with tab_help:
        st.markdown(
            """
### 你要的两件事

1. **AI / 缠论式看图与回测**  
   - 本页 **分形高/低** 只是几何近似，帮助肉眼扫压力/支撑，**不是** chan.py 的笔、中枢与买卖点。  
   - 正式缠论结构：克隆 `chan.py` 后，按其文档实现 `DataAPI` 自定义类接 QMT（或 CSV），再用 `CChan` 出图/导出 JSON，把结果接到本仓库回测脚本（时间戳对齐即可）。

2. **网页给自已和朋友看**  
   - 本机: `streamlit run examples/chan_web/app.py`  
   - 同一局域网: 加 `--server.address 0.0.0.0 --server.port 8501`，浏览器访问 `http://你的电脑IP:8501`  
   - **无登录**，勿公网裸奔；外网可自建密码或 VPN，或用云主机 + Nginx 鉴权。

### QMT

请先打开 **miniQMT / QMT**；可选环境变量 `MINIQMT_USERDATA` 指向 `userdata_mini`。
            """
        )

    with tab_chart:
        if err:
            st.error(err)
        elif df is None or df.empty:
            st.info("请选择 CSV，或使用 miniQMT 并确认客户端已登录、合约代码正确。")
        else:
            title = f"{code} {period} 共 {len(df)} 根"
            fig = _fig_candle(df, title, show_fractal=show_frac, fractal_n=int(frac_n))
            st.plotly_chart(fig, use_container_width=True)

    with tab_raw:
        if err or df is None or df.empty:
            st.caption("有有效数据后在此显示表格与导出。")
        else:
            st.dataframe(df.tail(500), use_container_width=True)
            buf = io.StringIO()
            df.to_csv(buf)
            st.download_button("下载当前表 CSV", buf.getvalue(), file_name="ohlcv_export.csv", mime="text/csv")


if __name__ == "__main__":
    main()
