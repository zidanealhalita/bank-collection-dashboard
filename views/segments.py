import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
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

ui.header("Segmen Risiko", "Di mana delinquency terkonsentrasi? Bandingkan produk, risk band, wilayah, dan segmen pendapatan.")

m_sel = st.sidebar.selectbox("Posisi akhir bulan", months[::-1], index=0, format_func=lambda m: lab[m], key="seg_month")
dims = {"Produk": "product", "Risk band": "risk_band", "Wilayah": "region", "Pendapatan": "income_band", "Vintage": "vintage"}
dim_name = st.sidebar.selectbox("Dimensi", list(dims.keys()), key="seg_dim")
metric = st.sidebar.selectbox("Metrik", ["DPD 30+ (%)", "NPL 90+ (%)", "DPD 1+ (%)"], index=0, key="seg_metric")
dim = dims[dim_name]

one = snap[snap["snapshot_month"] == m_sel]
F.stop_if_empty(one[one["is_active"]])
t = M.delinquency_by(one, dim).sort_values(metric, ascending=False)

left, right = st.columns([3, 2])
with left:
    fig = px.bar(t, x=metric, y=dim, orientation="h", color=metric, color_continuous_scale="YlOrRd",
                 text=t[metric].map(lambda v: f"{v:.1f}%"))
    fig.update_layout(coloraxis_showscale=False, yaxis=dict(autorange="reversed", title=None), xaxis_title=metric)
    ui.show(ui.style(fig, max(300, 34 * len(t) + 90), title=f"{metric} per {dim_name.lower()} ({lab[m_sel]})"), "seg_bar")
with right:
    st.dataframe(t.rename(columns={dim: dim_name}).round(2), hide_index=True, width="stretch",
                 column_config={"Outstanding (Rp M)": st.column_config.NumberColumn(format="%.2f")})

st.subheader("Produk × risk band")
a = one[one["is_active"]]
rows = []
for (p, b), g in a.groupby(["product", "risk_band"]):
    tot = g["outstanding"].sum()
    rows.append({"product": p, "risk_band": b, "v": g.loc[g["bucket"].isin(["31-60", "61-90", "90+"]), "outstanding"].sum() / tot * 100})
hm = pd.DataFrame(rows).pivot(index="product", columns="risk_band", values="v").reindex(index=C.PRODUCTS, columns=C.RISK_BANDS)
txt = [[("" if np.isnan(v) else f"{v:.1f}%") for v in r] for r in hm.to_numpy()]
fig = go.Figure(go.Heatmap(z=hm.to_numpy(), x=hm.columns, y=hm.index, text=txt, texttemplate="%{text}", colorscale="YlOrRd",
                           colorbar=dict(title="%"), hovertemplate="%{y} · %{x}: %{z:.1f}%<extra></extra>"))
fig.update_yaxes(autorange="reversed")
ui.show(ui.style(fig, 280, title="DPD 30+ (% outstanding)"), "seg_heat")

st.subheader("Tren NPL 90+ per risk band")
act = snap[snap["is_active"]]
g = act.groupby(["snapshot_month", "risk_band"]).apply(
    lambda d: d.loc[d["bucket"] == "90+", "outstanding"].sum() / d["outstanding"].sum() * 100, include_groups=False
).reset_index(name="NPL")
g = g[g["snapshot_month"] <= m_sel]
g["Bulan"] = g["snapshot_month"].map(lab)
fig = px.line(g, x="Bulan", y="NPL", color="risk_band", markers=True,
              color_discrete_sequence=["#2E7D5B", "#E3B341", "#8E1B3A"],
              category_orders={"Bulan": [lab[m] for m in months if m <= m_sel], "risk_band": C.RISK_BANDS})
fig.update_layout(yaxis_title="NPL 90+ (%)", xaxis_title=None)
ui.show(ui.style(fig, 360), "seg_trend")
