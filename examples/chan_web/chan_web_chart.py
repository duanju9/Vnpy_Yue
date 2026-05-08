# -*- coding: utf-8 -*-
"""Plotly K 线主图 + 成交量 + 可选 MA / MACD / KDJ；默认浅色，可选终端深色；浅色下缠论画法参考 ZenChart。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from fractal_levels import fractal_high_low
from technical_indicators import compute_kdj, compute_macd, compute_ma

if TYPE_CHECKING:
    from chan_plotly_overlay import ChanOverlay

ChartTheme = Literal["light", "terminal"]

_MA_COLORS_LIGHT = ("#ff9800", "#2196f3", "#9c27b0", "#795548", "#00897b", "#c62828")
_MA_COLORS_TERMINAL = ("#ffd54f", "#4fc3f7", "#ce93d8", "#80cbc4", "#ff8a65", "#fff59d")


def _vol_bar_colors(df: pd.DataFrame, *, up: str, down: str) -> list[str]:
    out: list[str] = []
    for i in range(len(df)):
        o = float(df["open"].iloc[i])
        c = float(df["close"].iloc[i])
        out.append(up if c >= o else down)
    return out


def build_figure(
    df: pd.DataFrame,
    title: str,
    *,
    show_fractal: bool,
    fractal_n: int,
    chan_overlay: ChanOverlay | None = None,
    uirevision: str | None = None,
    chart_theme: ChartTheme = "light",
    show_ma: bool = False,
    ma_periods: tuple[int, ...] = (),
    show_macd: bool = False,
    show_kdj: bool = False,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    kdj_n: int = 9,
    kdj_m1: int = 3,
    kdj_m2: int = 3,
) -> go.Figure:
    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    df = df.sort_index()

    terminal = chart_theme == "terminal"
    has_vol = "volume" in df.columns
    close = df["close"]

    if terminal:
        up_fill, up_line = "#f23645", "#ff6b6b"
        dn_fill, dn_line = "#00d9ff", "#26c6da"
        up_vol, dn_vol = "#f23645", "#00d9ff"
        macd_pos, macd_neg = "#f23645", "#00d9ff"
        ma_palette = _MA_COLORS_TERMINAL
        spike = "rgba(255,255,255,0.25)"
        hline_zero = "rgba(255,255,255,0.35)"
        kdj_ref = "rgba(255,255,255,0.12)"
        paper, plot_bg = "#131722", "#1b1f2a"
        font_c = "#d1d4dc"
        fract_hi, fract_lo = "#ff8a80", "#69f0ae"
        fract_hi_h, fract_lo_h = "rgba(255,138,128,0.5)", "rgba(105,240,174,0.45)"
    else:
        up_fill, up_line = "#e53935", "#b71c1c"
        dn_fill, dn_line = "#43a047", "#2e7d32"
        up_vol, dn_vol = "rgba(229,57,53,0.52)", "rgba(67,160,71,0.52)"
        macd_pos, macd_neg = "rgba(229,57,53,0.72)", "rgba(67,160,71,0.72)"
        ma_palette = _MA_COLORS_LIGHT
        spike = "rgba(0,0,0,0.25)"
        hline_zero = "rgba(0,0,0,0.35)"
        kdj_ref = "rgba(0,0,0,0.15)"
        paper, plot_bg = "#ffffff", "#fafafa"
        font_c = "#212121"
        fract_hi, fract_lo = "#e74c3c", "#27ae60"
        fract_hi_h, fract_lo_h = "rgba(231,76,60,0.45)", "rgba(39,174,96,0.45)"

    panels: list[str] = ["price"]
    if has_vol:
        panels.append("volume")
    if show_macd:
        panels.append("macd")
    if show_kdj:
        panels.append("kdj")

    n_rows = len(panels)
    multi = n_rows > 1

    if multi:
        if n_rows == 3 and panels == ["price", "volume", "macd"]:
            weights = [0.62, 0.2, 0.18]
        else:
            base_w = {"price": 0.52, "volume": 0.22, "macd": 0.13, "kdj": 0.13}
            weights = [base_w[p] for p in panels]
            s = sum(weights)
            weights = [w / s for w in weights]
        fig = make_subplots(
            rows=n_rows,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=weights,
        )
        row_of = {name: i + 1 for i, name in enumerate(panels)}
    else:
        fig = go.Figure()
        row_of = {"price": 1}

    r_price = row_of["price"]

    def add_price(trace: go.BaseTraceType) -> None:
        if multi:
            fig.add_trace(trace, row=r_price, col=1)
        else:
            fig.add_trace(trace)

    def hline_price(y: float, color: str) -> None:
        if multi:
            fig.add_hline(y=y, line_dash="dot", line_color=color, row=r_price, col=1)
        else:
            fig.add_hline(y=y, line_dash="dot", line_color=color)

    def zs_rect(t0, t1, zlo: float, zhi: float) -> None:
        if terminal:
            fill, line = "rgba(156, 39, 176, 0.32)", "rgba(186, 104, 200, 0.65)"
        else:
            fill, line = "rgba(156, 39, 176, 0.16)", "rgba(123, 31, 162, 0.5)"
        kw: dict = dict(
            x0=t0,
            x1=t1,
            y0=zlo,
            y1=zhi,
            fillcolor=fill,
            line_width=1,
            line_color=line,
            layer="below",
        )
        if multi:
            fig.add_vrect(**kw, row=r_price, col=1)
        else:
            fig.add_vrect(**kw)

    _lw = 1.15 if not terminal else 1.0
    _ww = 0.85 if not terminal else 0.8
    candle = go.Candlestick(
        x=df.index,
        open=df["open"],
        high=df["high"],
        low=df["low"],
        close=df["close"],
        name="ローソク",
        increasing=dict(line=dict(color=up_line, width=_lw), fillcolor=up_fill),
        decreasing=dict(line=dict(color=dn_line, width=_lw), fillcolor=dn_fill),
        whiskerwidth=_ww,
    )
    add_price(candle)

    last_c = float(close.iloc[-1])
    hline_price(last_c, "rgba(0,217,255,0.55)" if terminal else "rgba(33,150,243,0.45)")

    if show_ma and ma_periods:
        ma_dict = compute_ma(close, ma_periods)
        for idx, (period, series) in enumerate(sorted(ma_dict.items(), key=lambda x: x[0])):
            col = ma_palette[idx % len(ma_palette)]
            add_price(
                go.Scatter(
                    x=series.index,
                    y=series,
                    mode="lines",
                    name=f"MA{period}",
                    line=dict(width=1.2, color=col),
                    connectgaps=False,
                )
            )

    if show_fractal:
        hi, lo = fractal_high_low(df, last_n_peaks=fractal_n)
        if not hi.empty:
            add_price(
                go.Scatter(
                    x=hi["time"],
                    y=hi["price"],
                    mode="markers",
                    name="分形高(压力)",
                    marker=dict(symbol="triangle-down", size=10, color=fract_hi),
                )
            )
            for y in hi["price"].tail(5).tolist():
                hline_price(y, fract_hi_h)
        if not lo.empty:
            add_price(
                go.Scatter(
                    x=lo["time"],
                    y=lo["price"],
                    mode="markers",
                    name="分形低(支撑)",
                    marker=dict(symbol="triangle-up", size=10, color=fract_lo),
                )
            )
            for y in lo["price"].tail(5).tolist():
                hline_price(y, fract_lo_h)

    if chan_overlay is not None:
        for t0, t1, zlo, zhi in chan_overlay.zs_boxes:
            zs_rect(t0, t1, zlo, zhi)
        seg_segs = getattr(chan_overlay, "seg_segments", None) or ()
        if seg_segs:
            xs: list = []
            ys: list = []
            for t0, p0, t1, p1 in seg_segs:
                xs.extend([t0, t1, None])
                ys.extend([p0, p1, None])
            add_price(
                go.Scatter(
                    x=xs,
                    y=ys,
                    mode="lines",
                    name="线段",
                    line=dict(color="#ff9800", width=2.4),
                    connectgaps=False,
                    legendgroup="chan",
                )
            )
        if chan_overlay.bi_segments:
            xs = []
            ys = []
            for t0, p0, t1, p1 in chan_overlay.bi_segments:
                xs.extend([t0, t1, None])
                ys.extend([p0, p1, None])
            bi_color = "rgba(236,239,241,0.9)" if terminal else "#455a64"
            bi_w = 1.5 if not terminal else 1.4
            add_price(
                go.Scatter(
                    x=xs,
                    y=ys,
                    mode="lines",
                    name="笔",
                    line=dict(color=bi_color, width=bi_w),
                    connectgaps=False,
                    legendgroup="chan",
                )
            )

    if "volume" in panels:
        vcol = _vol_bar_colors(df, up=up_vol, down=dn_vol)
        fig.add_trace(
            go.Bar(
                x=df.index,
                y=df["volume"],
                name="成交量",
                marker_color=vcol,
                marker_line_width=0,
            ),
            row=row_of["volume"],
            col=1,
        )

    if "macd" in panels:
        m_line, sig, hist = compute_macd(
            close,
            fast=macd_fast,
            slow=macd_slow,
            signal=macd_signal,
        )
        hfill = hist.fillna(0.0)
        hist_colors = [macd_pos if v >= 0 else macd_neg for v in hfill]
        rm = row_of["macd"]
        fig.add_trace(
            go.Bar(
                x=df.index,
                y=hist,
                name="MACD柱",
                marker_color=hist_colors,
                marker_line_width=0,
            ),
            row=rm,
            col=1,
        )
        m_macd, m_sig = ("#42a5f5", "#ffa726") if terminal else ("#5c6bc0", "#ff7043")
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=m_line,
                name="MACD",
                line=dict(width=1.2, color=m_macd),
                connectgaps=False,
            ),
            row=rm,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=sig,
                name="Signal",
                line=dict(width=1, color=m_sig),
                connectgaps=False,
            ),
            row=rm,
            col=1,
        )
        fig.add_hline(y=0, line_dash="dot", line_color=hline_zero, row=rm, col=1)

    if "kdj" in panels:
        K, D, J = compute_kdj(
            df["high"],
            df["low"],
            close,
            n=kdj_n,
            m1=kdj_m1,
            m2=kdj_m2,
        )
        rk = row_of["kdj"]
        k_k, k_d, k_j = (
            ("#ffd54f", "#42a5f5", "#ce93d8")
            if terminal
            else ("#fbc02d", "#1976d2", "#7b1fa2")
        )
        fig.add_trace(
            go.Scatter(x=df.index, y=K, name="K", line=dict(width=1.2, color=k_k), connectgaps=False),
            row=rk,
            col=1,
        )
        fig.add_trace(
            go.Scatter(x=df.index, y=D, name="D", line=dict(width=1.2, color=k_d), connectgaps=False),
            row=rk,
            col=1,
        )
        fig.add_trace(
            go.Scatter(x=df.index, y=J, name="J", line=dict(width=1, color=k_j), connectgaps=False),
            row=rk,
            col=1,
        )
        for y in (20.0, 80.0):
            fig.add_hline(y=y, line_dash="dot", line_color=kdj_ref, row=rk, col=1)

    _uirev = uirevision if uirevision is not None else title
    height = min(1100, max(560, 380 + 260 * max(0, n_rows - 1)))
    if multi and n_rows >= 2:
        height = min(1180, height + 36)

    margin_b = 88 if terminal else (64 if multi else 40)

    legend_cfg = (
        dict(orientation="v", x=1.002, y=1, xanchor="left", yanchor="top", font=dict(size=11))
        if terminal
        else dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )

    fig.update_layout(
        title=dict(text=title, font=dict(size=16, color=font_c)),
        height=height,
        legend=legend_cfg,
        margin=dict(l=48, r=72 if terminal else 24, t=56, b=margin_b),
        bargap=0,
        hovermode="x unified",
        uirevision=_uirev,
        template="plotly_dark" if terminal else None,
        paper_bgcolor=paper,
        plot_bgcolor=plot_bg,
        font=dict(color=font_c),
    )

    if multi:
        for r in range(1, n_rows + 1):
            rs_vis = multi and (r == n_rows)
            fig.update_xaxes(
                rangeslider_visible=rs_vis,
                rangeslider_thickness=0.11 if rs_vis else 0.04,
                rangeslider_bgcolor=(
                    "rgba(30,35,50,0.95)" if (rs_vis and terminal) else ("rgba(248,249,250,0.98)" if rs_vis else None)
                ),
                showspikes=True,
                spikethickness=1,
                spikedash="solid",
                spikecolor=spike,
                spikemode="across",
                type="date",
                row=r,
                col=1,
            )
        fig.update_yaxes(
            title_text="价",
            row=r_price,
            col=1,
            autorange=True,
            fixedrange=False,
            gridcolor="rgba(255,255,255,0.06)" if terminal else "rgba(0,0,0,0.06)",
        )
        if "volume" in row_of:
            fig.update_yaxes(
                title_text="量",
                row=row_of["volume"],
                col=1,
                autorange=True,
                fixedrange=False,
                gridcolor="rgba(255,255,255,0.06)" if terminal else "rgba(0,0,0,0.06)",
            )
        if "macd" in row_of:
            fig.update_yaxes(
                title_text="MACD",
                row=row_of["macd"],
                col=1,
                autorange=True,
                fixedrange=False,
                gridcolor="rgba(255,255,255,0.06)" if terminal else "rgba(0,0,0,0.06)",
            )
        if "kdj" in row_of:
            fig.update_yaxes(
                title_text="KDJ",
                row=row_of["kdj"],
                col=1,
                autorange=True,
                fixedrange=False,
                gridcolor="rgba(255,255,255,0.06)" if terminal else "rgba(0,0,0,0.06)",
            )
    else:
        fig.update_xaxes(
            rangeslider_visible=True,
            rangeslider_thickness=0.11,
            rangeslider_bgcolor="rgba(248,249,250,0.98)" if not terminal else "rgba(30,35,50,0.95)",
            showspikes=True,
            spikethickness=1,
            spikedash="solid",
            spikecolor=spike,
            spikemode="across",
            type="date",
        )
        fig.update_yaxes(
            autorange=True,
            fixedrange=False,
            gridcolor="rgba(255,255,255,0.06)" if terminal else "rgba(0,0,0,0.06)",
        )

    return fig
