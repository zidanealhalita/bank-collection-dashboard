"""Helper tampilan: format angka Indonesia, tema plotly, CSS, dan komponen kecil."""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from . import config as C

# ------------------------------------------------------------------ format


def idr(x: float, digits: int = 2) -> str:
    """1.234.567.890 -> 'Rp 1,23 M' (M = miliar, T = triliun, jt = juta)."""
    if x is None or x != x:
        return "-"
    ax = abs(x)
    if ax >= 1e12:
        v, u = x / 1e12, "T"
    elif ax >= 1e9:
        v, u = x / 1e9, "M"
    elif ax >= 1e6:
        v, u = x / 1e6, "jt"
    else:
        return "Rp " + f"{x:,.0f}".replace(",", ".")
    return f"Rp {v:,.{digits}f} {u}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(x: float, digits: int = 1) -> str:
    if x is None or x != x:
        return "-"
    return f"{x * 100:.{digits}f}%".replace(".", ",")


def num(x: float) -> str:
    if x is None or x != x:
        return "-"
    return f"{x:,.0f}".replace(",", ".")


# ------------------------------------------------------------------ plotly

_FONT = "Inter, -apple-system, Segoe UI, Roboto, sans-serif"

_template = go.layout.Template(
    layout=go.Layout(
        font=dict(family=_FONT, size=13, color="#26323F"),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        colorway=C.PALETTE_SEQ,
        margin=dict(l=10, r=10, t=50, b=10),
        title=dict(font=dict(size=15), x=0.0, xanchor="left"),
        xaxis=dict(showgrid=False, linecolor="#C9D1D9", ticks="outside", tickcolor="#C9D1D9"),
        yaxis=dict(gridcolor="#E6EAEE", zeroline=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, title_text=""),
        hoverlabel=dict(font_family=_FONT),
    )
)
pio.templates["bank"] = _template
pio.templates.default = "bank"


def style(fig: go.Figure, height: int = 380, **layout) -> go.Figure:
    if "title" in layout and "margin" not in layout:
        layout["margin"] = dict(l=10, r=10, t=95, b=10)  # ruang untuk judul di atas legenda
    fig.update_layout(height=height, legend_title_text="", **layout)
    return fig


def show(fig: go.Figure, key: str | None = None) -> None:
    st.plotly_chart(fig, width="stretch", key=key, config={"displayModeBar": False})


# ------------------------------------------------------------------ komponen

_CSS = """
<style>
div[data-testid="stMetric"] {background:#F6F8FA;border:1px solid #E3E8ED;border-radius:10px;padding:12px 16px;}
div[data-testid="stMetricLabel"] p {font-size:.82rem;color:#5B6B7A;}
div[data-testid="stMetricValue"] {font-size:1.55rem;}
div[data-testid="stMetricValue"] > div {overflow:visible;text-overflow:clip;white-space:normal;}
.block-container {padding-top:2.2rem;}
.small-note {font-size:.82rem;color:#5B6B7A;}
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def header(title: str, subtitle: str = "") -> None:
    inject_css()
    st.title(title)
    if subtitle:
        st.caption(subtitle)


def note(text: str) -> None:
    st.caption(text)


def bucket_colors(names: list[str]) -> dict[str, str]:
    return {n: C.BUCKET_COLORS.get(n, "#888") for n in names}
