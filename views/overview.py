import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st

from src import config as C
from src import markov as MK
from src import metrics as M
from src import ui
from src.data import load_data, month_labels

D = load_data()
snap, asg, loans, pairs = D["snapshots"], D["assignments"], D["loans"], D["pairs"]
months = sorted(snap["snapshot_month"].unique())
lab = month_labels(months)

ui.header("Ringkasan Eksekutif", "Kesehatan portofolio pinjaman digital dan efektivitas penagihan — data dummy untuk portofolio demo.")

m_sel = st.sidebar.selectbox("Posisi akhir bulan", months[::-1], index=0, format_func=lambda m: lab[m], key="ov_month")
k = M.portfolio_kpis(snap, m_sel)
cur, prev = k["cur"], k["prev"]


def dpp(key):
    return None if not prev else f"{(cur[key] - prev[key]) * 100:+.2f} pp"


c = st.columns(5)
c[0].metric("Outstanding", ui.idr(cur["outstanding"]),
            None if not prev else f"{(cur['outstanding'] / prev['outstanding'] - 1) * 100:+.1f}% MoM")
c[1].metric("Pinjaman aktif", ui.num(cur["loans"]))
c[2].metric("DPD 30+", ui.pct(cur["dpd30"], 2), dpp("dpd30"), delta_color="inverse")
c[3].metric("NPL 90+", ui.pct(cur["npl90"], 2), dpp("npl90"), delta_color="inverse")
c[4].metric("Write-off bulan ini", ui.idr(cur["writeoff"]),
            None if not prev or not prev["writeoff"] else f"{(cur['writeoff'] / prev['writeoff'] - 1) * 100:+.0f}% MoM",
            delta_color="inverse")

left, right = st.columns(2)

# ---- aging 12 bulan terakhir
with left:
    tbl = M.aging_by_month(snap, "outstanding")
    tbl = tbl.loc[:m_sel].tail(12)
    sh = (tbl.div(tbl.sum(axis=1), axis=0) * 100).reset_index().melt(id_vars="snapshot_month", var_name="Bucket", value_name="%")
    sh["Bulan"] = sh["snapshot_month"].map(lab)
    fig = px.bar(sh, x="Bulan", y="%", color="Bucket", color_discrete_map=C.BUCKET_COLORS,
                 category_orders={"Bucket": C.BUCKETS, "Bulan": [lab[m] for m in tbl.index]})
    fig.update_layout(barmode="stack", xaxis_title=None, yaxis_title="% outstanding")
    ui.show(ui.style(fig, 360, title="Komposisi aging (12 bulan)"), "ov_aging")

# ---- cure rate per tim
with right:
    a = asg[asg["month"] <= m_sel]
    g = a.groupby(["month", "team"])["cured"].mean().reset_index()
    g = g[g["month"].isin(months[max(0, months.index(m_sel) - 11): months.index(m_sel) + 1])]
    g["Bulan"] = g["month"].map(lab)
    fig = px.line(g, x="Bulan", y="cured", color="team", markers=True, color_discrete_sequence=C.PALETTE_SEQ,
                  category_orders={"Bulan": [lab[m] for m in sorted(g["month"].unique())]})
    fig.update_layout(yaxis_tickformat=".0%", yaxis_title="Cure rate", xaxis_title=None)
    ui.show(ui.style(fig, 360, title="Cure rate per tim"), "ov_cure")

# ---- sorotan otomatis
st.subheader("Sorotan")
bul = []
if prev:
    d30 = (cur["dpd30"] - prev["dpd30"]) * 100
    bul.append(f"DPD 30+ {'naik' if d30 > 0 else 'turun'} **{abs(d30):.2f} pp** dibanding {lab[months[months.index(m_sel) - 1]]} "
               f"menjadi **{ui.pct(cur['dpd30'], 2)}**.")
pm = pairs[pairs["from_month"] == months[max(0, months.index(m_sel) - 1)]]
if len(pm):
    pr, _ = MK.roll_matrix(pm, "count")
    bul.append(f"Roll rate 1-30 → 31-60 bulan lalu: **{ui.pct(pr.loc['1-30', '31-60'])}**; "
               f"61-90 → 90+: **{ui.pct(pr.loc['61-90', '90+'])}**.")
v90 = M.vintage_curves(snap, loans, "Ever 90+ DPD")
if 6 in v90.columns and v90[6].notna().any():
    w = v90[6].idxmax()
    b = v90[6].idxmin()
    bul.append(f"Vintage dengan Ever 90+ @MOB6 tertinggi: **{w}** ({v90.loc[w, 6]:.1f}%); terendah: **{b}** ({v90.loc[b, 6]:.1f}%).")
am = asg[asg["month"] == m_sel]
if len(am):
    best = am.groupby("team")["cured"].mean()
    bul.append(f"Pada {lab[m_sel]}, cure rate: " + ", ".join(f"{t} **{ui.pct(v)}**" for t, v in best.items()) + ".")
for t in bul:
    st.markdown("- " + t)

st.divider()
st.markdown(
    "**Navigasi:** *Aging* — komposisi bucket & tren · *Roll Rate* — matriks Markov, proyeksi, backtest · "
    "*Vintage* — kualitas kohort · *Collector Scorecard* — kinerja penagihan · *Segmen Risiko* · *Data & Metodologi*."
)
