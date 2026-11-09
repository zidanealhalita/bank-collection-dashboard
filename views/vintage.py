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
from src.data import load_data

D = load_data()
loans, snap = D["loans"], D["snapshots"]

ui.header("Vintage Analysis",
          "Kualitas kohort pinjaman berdasarkan bulan pencairan, diamati menurut umur pinjaman (Months on Book / MOB).")

# ------------------------------------------------------------------ filter
metric = st.sidebar.selectbox("Metrik", list(M.EVER_SETS.keys()), index=2, key="vin_metric",
                              help="Persentase pinjaman kohort yang PERNAH mencapai kondisi tersebut sampai MOB tertentu.")
basis = st.sidebar.radio("Basis", ["Jumlah pinjaman", "Plafon pencairan (Rp)"], key="vin_basis")
bkey = "count" if basis.startswith("Jumlah") else "principal"
with st.sidebar.expander("Segmen pinjaman", expanded=False):
    prod = st.multiselect("Produk", C.PRODUCTS, default=C.PRODUCTS, key="vin_prod")
    band = st.multiselect("Risk band", C.RISK_BANDS, default=C.RISK_BANDS, key="vin_band")

L = loans[loans["product"].isin(prod) & loans["risk_band"].isin(band)]
F.stop_if_empty(L)
S = snap[snap["loan_id"].isin(set(L["loan_id"]))]

curves = M.vintage_curves(S, L, metric, bkey)
vints = list(curves.index)

# ------------------------------------------------------------------ heatmap
st.subheader(f"{metric} — kohort × MOB")
z = curves.to_numpy()
zmax = float(np.nanmax(z)) if np.isfinite(z).any() else 1.0
text = [[("" if np.isnan(v) else f"{v:.1f}") for v in row] for row in z]
fig = go.Figure(go.Heatmap(
    z=z, x=[f"{c}" for c in curves.columns], y=vints, text=text, texttemplate="%{text}",
    colorscale="YlOrRd", zmin=0, zmax=max(zmax, 1), colorbar=dict(title="%"), xgap=1, ygap=1,
    hovertemplate="Vintage %{y} · MOB %{x}: %{z:.2f}%<extra></extra>",
))
fig.update_yaxes(autorange="reversed", title="Bulan pencairan", type="category", dtick=1)
fig.update_xaxes(title="MOB (bulan sejak pencairan)", side="top")
ui.show(ui.style(fig, 140 + 24 * len(vints), margin=dict(l=10, r=10, t=70, b=10)), "vin_heat")
ui.note("Sel kosong = belum teramati (kohort belum mencapai MOB tersebut). Penyebut = seluruh pinjaman kohort, "
        "sehingga pinjaman yang sudah lunas tetap dihitung dan kurva tidak bias.")

# ------------------------------------------------------------------ kurva & perbandingan
t1, t2, t3 = st.tabs(["Kurva per vintage", "Perbandingan pada MOB tertentu", "Ringkasan kohort"])

with t1:
    default_sel = vints[::3] if len(vints) > 6 else vints
    sel = st.multiselect("Vintage yang ditampilkan", vints, default=default_sel, key="vin_sel")
    if sel:
        long = curves.loc[sel].reset_index(names="Vintage").melt(id_vars="Vintage", var_name="MOB", value_name="%").dropna()
        fig = px.line(long, x="MOB", y="%", color="Vintage", markers=True,
                      color_discrete_sequence=px.colors.sequential.Turbo)
        fig.update_layout(yaxis_title=f"% kumulatif ({metric})", xaxis=dict(dtick=1, title="MOB"))
        ui.show(ui.style(fig, 420), "vin_lines")
    else:
        st.info("Pilih minimal satu vintage.")

with t2:
    avail = [int(c) for c in curves.columns if curves[c].notna().sum() >= 3]
    mob = st.select_slider("MOB", options=avail, value=min(6, max(avail)), key="vin_mob")
    cmp_df = curves[mob].dropna().reset_index()
    cmp_df.columns = ["Vintage", "%"]
    avg = cmp_df["%"].mean()
    fig = px.bar(cmp_df, x="Vintage", y="%", color="%", color_continuous_scale="YlOrRd")
    fig.add_hline(y=avg, line_dash="dash", line_color="#4B4B4B", annotation_text=f"rata-rata {avg:.1f}%")
    fig.update_layout(yaxis_title=f"{metric} @MOB {mob} (%)", coloraxis_showscale=False, xaxis_title=None)
    ui.show(ui.style(fig, 380), "vin_bar")
    worst = cmp_df.loc[cmp_df["%"].idxmax()]
    best = cmp_df.loc[cmp_df["%"].idxmin()]
    st.markdown(f"Pada MOB {mob}, vintage terburuk adalah **{worst['Vintage']}** ({worst['%']:.1f}%) dan terbaik "
                f"**{best['Vintage']}** ({best['%']:.1f}%) — selisih {worst['%'] / max(best['%'], 0.01):.1f}x.")

with t3:
    summ = M.vintage_summary(S, L).round(2).reset_index().rename(columns={"vintage": "Vintage"})
    st.dataframe(summ, hide_index=True, width="stretch", column_config={
        "Pinjaman": st.column_config.NumberColumn(format="%d"),
        "% Risk C": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
    })
    st.download_button("Unduh CSV", summ.to_csv(index=False).encode("utf-8"), "vintage_summary.csv", "text/csv", key="vin_dl")
