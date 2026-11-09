"""Widget filter sidebar yang dipakai lintas halaman."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from . import config as C
from .data import month_labels


def month_range(months: list[str], key: str, label: str = "Periode", last_n: int | None = None) -> tuple[str, str]:
    """Slider rentang bulan. Default: seluruh periode (atau `last_n` bulan terakhir)."""
    lab = month_labels(months)
    default_start = months[max(0, len(months) - last_n)] if last_n else months[0]
    start, end = st.sidebar.select_slider(
        label,
        options=months,
        value=(default_start, months[-1]),
        format_func=lambda m: lab[m],
        key=f"{key}_period",
    )
    return start, end


def segment_filters(df: pd.DataFrame, key: str) -> dict[str, list[str]]:
    """Filter produk / risk band / wilayah. Mengembalikan pilihan (kosong = tidak ada yang dipilih)."""
    with st.sidebar.expander("Segmen portofolio", expanded=False):
        prod = st.multiselect("Produk", C.PRODUCTS, default=C.PRODUCTS, key=f"{key}_prod")
        band = st.multiselect("Risk band", C.RISK_BANDS, default=C.RISK_BANDS, key=f"{key}_band")
        region = st.multiselect("Wilayah", C.REGIONS, default=C.REGIONS, key=f"{key}_region")
    return {"product": prod, "risk_band": band, "region": region}


def apply_segments(df: pd.DataFrame, sel: dict[str, list[str]]) -> pd.DataFrame:
    out = df
    for col, vals in sel.items():
        if col in out.columns:
            out = out[out[col].isin(vals)]
    return out


def stop_if_empty(df: pd.DataFrame, msg: str = "Tidak ada data untuk kombinasi filter ini. Longgarkan filter di sidebar.") -> None:
    if df is None or len(df) == 0:
        st.warning(msg)
        st.stop()
