"""Entrypoint Streamlit: navigasi multi-halaman."""
import streamlit as st

from src import config as C

st.set_page_config(page_title=C.APP_TITLE, page_icon=C.APP_ICON, layout="wide", initial_sidebar_state="expanded")

pages = [
    st.Page("views/overview.py", title="Ringkasan", icon=":material/dashboard:", default=True),
    st.Page("views/aging.py", title="Aging & Tren", icon=":material/stacked_bar_chart:"),
    st.Page("views/roll_rate.py", title="Roll Rate & Markov", icon=":material/swap_horiz:"),
    st.Page("views/vintage.py", title="Vintage", icon=":material/grid_on:"),
    st.Page("views/collector.py", title="Collector Scorecard", icon=":material/support_agent:"),
    st.Page("views/segments.py", title="Segmen Risiko", icon=":material/donut_small:"),
    st.Page("views/data_info.py", title="Data & Metodologi", icon=":material/info:"),
]
nav = st.navigation(pages)
st.sidebar.caption("Data dummy · bukan data nasabah nyata")
nav.run()
