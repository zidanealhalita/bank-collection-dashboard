import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src import config as C
from src import filters as F
from src import metrics as M
from src import ui
from src.data import load_data, month_labels

D = load_data()
snap = D["snapshots"]
months = sorted(snap["snapshot_month"].unique())
lab = month_labels(months)

ui.header("Aging Bucket & Tren Delinquency",
          "Komposisi portofolio per bucket DPD (akhir bulan) dan bagaimana pergerakannya dari waktu ke waktu.")

# ------------------------------------------------------------------ filter
start, end = F.month_range(months, "aging")
basis = st.sidebar.radio("Basis perhitungan", ["Outstanding (Rp)", "Jumlah pinjaman"], key="aging_basis")
seg = F.segment_filters(snap, "aging")
bkey = "outstanding" if basis.startswith("Out") else "count"

s = F.apply_segments(snap, seg)
s = s[(s["snapshot_month"] >= start) & (s["snapshot_month"] <= end)]
F.stop_if_empty(s[s["is_active"]])

tbl = M.aging_by_month(s, bkey)
share = tbl.div(tbl.sum(axis=1), axis=0) * 100
end_m = tbl.index[-1]

# ------------------------------------------------------------------ KPI
k = M.portfolio_kpis(F.apply_segments(snap, seg), end_m)
cur, prev = k["cur"], k["prev"]


def delta_pp(key):
    return None if not prev else f"{(cur[key] - prev[key]) * 100:+.2f} pp"


c1, c2, c3, c4 = st.columns(4)
c1.metric(f"Outstanding ({lab[end_m]})", ui.idr(cur["outstanding"]),
          None if not prev else f"{(cur['outstanding'] / prev['outstanding'] - 1) * 100:+.1f}% MoM")
c2.metric("DPD 1+ (non-current)", ui.pct(cur["dpd1"], 2), delta_pp("dpd1"), delta_color="inverse")
c3.metric("DPD 30+", ui.pct(cur["dpd30"], 2), delta_pp("dpd30"), delta_color="inverse")
c4.metric("NPL (90+)", ui.pct(cur["npl90"], 2), delta_pp("npl90"), delta_color="inverse")

# ------------------------------------------------------------------ tren komposisi
tab1, tab2, tab3 = st.tabs(["Tren komposisi", "Rasio delinquency", "Posisi bulan terpilih"])

with tab1:
    view = st.radio("Tampilan", ["Persentase (100%)", "Nominal"], horizontal=True, key="aging_view")
    data = share if view.startswith("Pers") else tbl / (1e9 if bkey == "outstanding" else 1)
    long = data.reset_index().melt(id_vars="snapshot_month", var_name="Bucket", value_name="v")
    long["Bulan"] = long["snapshot_month"].map(lab)
    fig = px.bar(long, x="Bulan", y="v", color="Bucket", color_discrete_map=C.BUCKET_COLORS,
                 category_orders={"Bucket": C.BUCKETS, "Bulan": [lab[m] for m in data.index]})
    ytitle = "% portofolio" if view.startswith("Pers") else ("Rp miliar" if bkey == "outstanding" else "Jumlah pinjaman")
    fig.update_layout(barmode="stack", yaxis_title=ytitle, xaxis_title=None)
    fig.update_traces(hovertemplate="%{x}<br>%{fullData.name}: %{y:,.1f}<extra></extra>")
    ui.show(ui.style(fig, 420), "aging_stack")

with tab2:
    r = pd.DataFrame({
        "DPD 1+": 100 - share["Current"],
        "DPD 30+": share[["31-60", "61-90", "90+"]].sum(axis=1),
        "NPL 90+": share["90+"],
    })
    r.index = [lab[m] for m in r.index]
    fig = go.Figure()
    colors = {"DPD 1+": "#E3B341", "DPD 30+": "#F08A3C", "NPL 90+": "#8E1B3A"}
    for col in r.columns:
        fig.add_scatter(x=r.index, y=r[col], mode="lines+markers", name=col, line=dict(color=colors[col], width=2.5))
    fig.update_layout(yaxis_title="% dari portofolio", xaxis_title=None)
    ui.show(ui.style(fig, 400), "aging_ratio")
    ui.note("DPD 30+ = bucket 31-60, 61-90, dan 90+. NPL memakai definisi 90+ DPD (>90 hari). "
            "Lonjakan Apr-Mei 2026 mensimulasikan efek musiman pasca-Lebaran; vintage Jul-Okt 2025 berkualitas rendah.")

with tab3:
    m_sel = st.select_slider("Bulan", options=list(tbl.index), value=end_m, format_func=lambda m: lab[m], key="aging_month")
    one = F.apply_segments(snap, seg)
    one = one[(one["snapshot_month"] == m_sel) & one["is_active"]]
    g = one.groupby("bucket").agg(
        Pinjaman=("loan_id", "count"), Outstanding=("outstanding", "sum"),
        Tunggakan=("overdue_amount", "sum"), Rata_DPD=("dpd", "mean"),
    ).reindex(C.BUCKETS).fillna(0)
    g["% Outstanding"] = g["Outstanding"] / g["Outstanding"].sum() * 100
    left, right = st.columns([1, 1])
    with left:
        fig = px.pie(g.reset_index(), names="bucket", values="Outstanding", hole=0.55,
                     color="bucket", color_discrete_map=C.BUCKET_COLORS, category_orders={"bucket": C.BUCKETS})
        fig.update_traces(sort=False, textinfo="percent", hovertemplate="%{label}: %{percent}<extra></extra>")
        ui.show(ui.style(fig, 330, showlegend=True), "aging_pie")
    with right:
        show = g.reset_index().rename(columns={"bucket": "Bucket", "Rata_DPD": "Rata-rata DPD"})
        st.dataframe(
            show, hide_index=True, width="stretch",
            column_config={
                "Pinjaman": st.column_config.NumberColumn(format="%d"),
                "Outstanding": st.column_config.NumberColumn("Outstanding (Rp)", format="localized"),
                "Tunggakan": st.column_config.NumberColumn("Tunggakan (Rp)", format="localized"),
                "Rata-rata DPD": st.column_config.NumberColumn(format="%.0f"),
                "% Outstanding": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
            },
        )
    st.markdown("**20 akun dengan tunggakan terbesar**")
    top = one[one["dpd"] > 0].nlargest(20, "overdue_amount")[
        ["loan_id", "product", "risk_band", "bucket", "dpd", "due_date", "installments_overdue", "overdue_amount", "outstanding"]
    ].rename(columns={
        "loan_id": "Loan ID", "product": "Produk", "risk_band": "Risk band", "bucket": "Bucket", "dpd": "DPD",
        "due_date": "Jatuh tempo (tertua)", "installments_overdue": "Cicilan nunggak",
        "overdue_amount": "Tunggakan (Rp)", "outstanding": "Outstanding (Rp)"})
    top["Jatuh tempo (tertua)"] = pd.to_datetime(top["Jatuh tempo (tertua)"]).dt.date
    st.dataframe(top, hide_index=True, width="stretch",
                 column_config={"Tunggakan (Rp)": st.column_config.NumberColumn(format="localized"),
                                "Outstanding (Rp)": st.column_config.NumberColumn(format="localized")})

with st.expander("Tabel agregat per bulan"):
    out = tbl.copy()
    out.index = [lab[m] for m in out.index]
    st.dataframe(out, width="stretch")
    st.download_button("Unduh CSV", out.to_csv().encode("utf-8"), "aging_bulanan.csv", "text/csv", key="aging_dl")
