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
from src import markov as MK
from src import ui
from src.data import load_data, month_labels

D = load_data()
snap, pairs = D["snapshots"], D["pairs"]
months = sorted(snap["snapshot_month"].unique())
lab = month_labels(months)
from_months = sorted(pairs["from_month"].unique())

ui.header("Roll Rate & Matriks Transisi Markov",
          "Roll rate = peluang akun berpindah bucket dalam sebulan. Matriks ini adalah matriks transisi Markov "
          "yang bisa diestimasi, diproyeksikan ke depan, dan di-stress test.")

# ------------------------------------------------------------------ filter
start, end = F.month_range(from_months, "roll", "Periode transisi (bulan asal)")
basis = st.sidebar.radio("Pembobotan", ["Jumlah akun", "Outstanding (Rp)"], key="roll_basis")
wkey = "count" if basis.startswith("Jumlah") else "outstanding"
seg = F.segment_filters(pairs, "roll")

p = F.apply_segments(pairs, seg)
p = p[(p["from_month"] >= start) & (p["from_month"] <= end)]
F.stop_if_empty(p)

prob, raw = MK.roll_matrix(p, wkey)
P = MK.full_matrix(prob)
ncols = [MK.STATE_LABEL[s] for s in MK.STATES]
_cnt = MK.roll_matrix(p, "count")[1]
_thin = MK.thin_rows(_cnt)
if _thin:
    st.warning("Observasi sangat sedikit (< 30 akun) untuk bucket: " + ", ".join(_thin) +
               ". Estimasi baris tersebut tidak andal — perlebar periode atau segmen.")

tab_m, tab_t, tab_p, tab_b = st.tabs(["Matriks roll rate", "Tren roll rate", "Proyeksi Markov", "Backtest"])

# ================================================================== 1. matriks
with tab_m:
    z = prob.to_numpy() * 100
    text = [[f"{v:.1f}%" if v >= 0.05 else "" for v in row] for row in z]
    fig = go.Figure(go.Heatmap(
        z=z, x=ncols, y=C.BUCKETS, text=text, texttemplate="%{text}", colorscale="YlOrRd",
        zmin=0, zmax=100, colorbar=dict(title="%"), hovertemplate="Dari %{y} → %{x}: %{z:.2f}%<extra></extra>",
    ))
    fig.update_yaxes(autorange="reversed", title="Bucket bulan t")
    fig.update_xaxes(title="Status bulan t+1", side="top")
    ui.show(ui.style(fig, 360, margin=dict(l=10, r=10, t=70, b=10)), "roll_heat")

    fwd = {"Current → 1-30": prob.loc["Current", "1-30"], "1-30 → 31-60": prob.loc["1-30", "31-60"],
           "31-60 → 61-90": prob.loc["31-60", "61-90"], "61-90 → 90+": prob.loc["61-90", "90+"]}
    cols = st.columns(4)
    for c, (k, v) in zip(cols, fwd.items()):
        c.metric(f"Roll rate {k}", ui.pct(v))
    cure = {"1-30": prob.loc["1-30", ["Current", "Closed"]].sum(), "31-60": prob.loc["31-60", ["Current", "Closed"]].sum(),
            "61-90": prob.loc["61-90", ["Current", "Closed"]].sum(), "90+": prob.loc["90+", ["Current", "Closed"]].sum()}
    st.markdown("**Cure rate bulanan** (kembali Current atau lunas): " +
                " · ".join(f"{k}: **{ui.pct(v)}**" for k, v in cure.items()))
    ui.note("Baris dibaca: dari bucket di baris, sekian % berada di kolom bucket pada akhir bulan berikutnya. "
            "'Lunas' dan 'Write-off' adalah keadaan absorbing (tidak keluar lagi). Persentase < 0,05% disembunyikan di sel.")

    with st.expander("Jumlah mentah (observasi transisi)"):
        rawt = raw.copy()
        rawt.columns = ncols
        st.dataframe(rawt.round(0), width="stretch")

# ================================================================== 2. tren
with tab_t:
    pp = F.apply_segments(pairs, seg)
    rows = []
    for m, g in pp.groupby("from_month"):
        pr, _ = MK.roll_matrix(g, wkey)
        if len(g) < 200:
            continue
        rows.append({
            "Bulan": m,
            "Current → 1-30": pr.loc["Current", "1-30"], "1-30 → 31-60": pr.loc["1-30", "31-60"],
            "31-60 → 61-90": pr.loc["31-60", "61-90"], "61-90 → 90+": pr.loc["61-90", "90+"],
        })
    tr = pd.DataFrame(rows)
    tr = tr[(tr["Bulan"] >= start) & (tr["Bulan"] <= end)]
    F.stop_if_empty(tr, "Data tren tidak cukup pada filter ini.")
    tr["Bulan"] = tr["Bulan"].map(lab)
    long = tr.melt(id_vars="Bulan", var_name="Transisi", value_name="Roll rate")
    long["Roll rate"] *= 100
    fig = px.line(long, x="Bulan", y="Roll rate", color="Transisi", markers=True,
                  category_orders={"Bulan": list(tr["Bulan"])},
                  color_discrete_sequence=["#E3B341", "#F08A3C", "#D9534F", "#8E1B3A"])
    fig.update_layout(yaxis_title="% akun yang roll ke bucket berikutnya", xaxis_title=None)
    ui.show(ui.style(fig, 420), "roll_trend")
    ui.note("Roll rate Current → 1-30 naik pada vintage longgar (Jul-Okt 2025); transisi 31-60 → 61-90 melonjak "
            "setelah efek musiman Lebaran 2026.")

# ================================================================== 3. proyeksi
with tab_p:
    c1, c2, c3 = st.columns(3)
    horizon = c1.slider("Horizon proyeksi (bulan)", 1, 12, 6, key="roll_h")
    stress = c2.slider("Stress: pengali peluang memburuk", 0.5, 2.0, 1.0, 0.1, key="roll_stress",
                       help="1.0 = matriks hasil estimasi. 1.5 = semua peluang roll-forward & write-off x1,5 (lalu dinormalisasi).")
    origin = c3.selectbox("Posisi awal", months[::-1], index=0, format_func=lambda m: lab[m], key="roll_origin")

    start_snap = F.apply_segments(snap, seg)
    start_snap = start_snap[start_snap["snapshot_month"] == origin]
    v0 = MK.state_vector(start_snap, wkey)
    F.stop_if_empty(pd.DataFrame({"x": [1]}) if v0.sum() > 0 else pd.DataFrame(), "Tidak ada akun aktif pada posisi awal ini.")

    Ps = MK.stress_matrix(P, stress)
    path = MK.project(Ps, v0, horizon)
    share = path / path.sum(axis=1, keepdims=True) * 100

    dfp = pd.DataFrame(share, columns=ncols)
    dfp["Bulan ke"] = range(horizon + 1)
    long = dfp.melt(id_vars="Bulan ke", var_name="Status", value_name="%")
    cmap = {**C.BUCKET_COLORS, "Lunas": "#7FB3D5"}
    fig = px.area(long, x="Bulan ke", y="%", color="Status", color_discrete_map=cmap,
                  category_orders={"Status": ncols})
    fig.update_layout(yaxis_title="% dari portofolio awal", xaxis=dict(dtick=1))
    ui.show(ui.style(fig, 400), "roll_proj")

    wo_h = share[-1, -1]
    act_now = share[0, :MK.NA]
    act_end = share[-1, :MK.NA]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("NPL 90+ sekarang", f"{act_now[4]:.2f}%")
    k2.metric(f"NPL 90+ dalam {horizon} bln", f"{act_end[4]:.2f}%", f"{act_end[4] - act_now[4]:+.2f} pp", delta_color="inverse")
    k3.metric(f"Kumulatif write-off {horizon} bln", f"{wo_h:.2f}%")
    base_wo = MK.project(P, v0, horizon)
    base_wo_pct = base_wo[-1, -1] / base_wo[-1].sum() * 100
    k4.metric("vs. skenario dasar", f"{wo_h - base_wo_pct:+.2f} pp", help="Selisih kumulatif write-off terhadap stress = 1,0")

    st.markdown("**Probabilitas akhir & lama sampai selesai** (matriks fundamental $N=(I-Q)^{-1}$)")
    ab = MK.absorption(Ps)
    if ab is None:
        st.info("Tabel absorpsi tidak dapat dihitung: ada bucket tanpa observasi transisi pada filter ini "
                "(biasanya karena rentang periode/segmen terlalu sempit). Perlebar periode atau segmen di sidebar.")
    else:
        st.dataframe(
            ab.reset_index().rename(columns={"index": "Bucket saat ini"}), hide_index=True, width="stretch",
            column_config={
                "P(akhirnya lunas)": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
                "P(akhirnya write-off)": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
                "Ekspektasi bulan sampai selesai": st.column_config.NumberColumn(format="%.1f bln"),
            },
        )
    ui.note("Proyeksi hanya untuk portofolio yang ada pada posisi awal (run-off, tanpa pencairan baru). "
            "Asumsi Markov: matriks tetap (homogen waktu) dan peluang hanya bergantung pada bucket saat ini. "
            "Untuk pelunasan, asumsi ini kasar karena waktu lunas bergantung pada tenor — lihat tab Backtest.")

# ================================================================== 4. backtest
with tab_b:
    st.markdown("Uji seberapa baik matriks Markov yang **hanya dilatih dari masa lalu** memprediksi kohort yang sama.")
    b1, b2 = st.columns(2)
    candidates = [m for m in months if months.index(m) >= 6 and months.index(m) <= len(months) - 2]
    origin_b = b1.selectbox("Titik asal prediksi", candidates[::-1], index=min(3, len(candidates) - 1),
                            format_func=lambda m: lab[m], key="bt_origin")
    max_h = len(months) - 1 - months.index(origin_b)
    h_b = b2.slider("Horizon (bulan)", 1, max(1, min(6, max_h)), min(3, max_h), key="bt_h") if max_h > 1 else 1
    res = MK.backtest(pairs, snap, origin_b, h_b, wkey)
    if res is None:
        st.info("Data tidak cukup untuk backtest pada kombinasi ini.")
    else:
        cmp_tbl, path_b = res
        fig = go.Figure()
        fig.add_bar(x=cmp_tbl.index, y=cmp_tbl["Proyeksi"], name="Proyeksi Markov", marker_color="#3B6EA5")
        fig.add_bar(x=cmp_tbl.index, y=cmp_tbl["Realisasi"], name="Realisasi", marker_color="#2E7D5B")
        fig.update_layout(barmode="group", yaxis_title="% kohort", title=f"Distribusi status {h_b} bulan setelah {lab[origin_b]}")
        ui.show(ui.style(fig, 380), "bt_bar")
        st.dataframe(cmp_tbl.round(2).reset_index().rename(columns={"index": "Status"}), hide_index=True, width="stretch")
        mae_act = cmp_tbl.loc[[MK.STATE_LABEL[s] for s in C.BUCKETS], "Selisih (pp)"].abs().mean()
        st.metric("MAE bucket aktif (pp)", f"{mae_act:.2f}")
        ui.note("Selisih pada 'Lunas' umumnya terbesar karena pelunasan terjadi di akhir tenor (tidak homogen waktu), "
                "sedangkan selisih di bucket delinquent mencerminkan perubahan kualitas kohort (underwriting yang diperketat) "
                "relatif terhadap rata-rata historis yang dipakai melatih matriks.")
