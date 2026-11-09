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
asg, act, col = D["assignments"], D["actions"], D["collectors"]

ui.header("Collector Scorecard",
          "Cure rate, recovery rate, dan promise-to-pay (PTP) kept rate per collector, tim, dan channel penagihan.")

# ------------------------------------------------------------------ filter
dmin, dmax = asg["assigned_date"].min().date(), asg["assigned_date"].max().date()
default_start = max(dmin, (pd.Timestamp(dmax) - pd.Timedelta(days=89)).date())
rng = st.sidebar.date_input("Rentang tanggal penugasan", value=(default_start, dmax), min_value=dmin, max_value=dmax,
                            key="col_dates", help="Tanggal akun pertama kali ditangani collector pada bulan tersebut.")
if not (isinstance(rng, (list, tuple)) and len(rng) == 2):
    st.info("Pilih tanggal akhir pada kalender untuk melengkapi rentang.")
    st.stop()
d0, d1 = pd.Timestamp(rng[0]), pd.Timestamp(rng[1])
teams = st.sidebar.multiselect("Tim", C.TEAMS, default=C.TEAMS, key="col_teams")
channels = st.sidebar.multiselect("Channel utama", C.CHANNELS, default=C.CHANNELS, key="col_ch",
                                  help="Channel yang dipakai pada kontak pertama (channel utama) akun tersebut.")
min_acc = st.sidebar.number_input("Minimum akun per collector", 0, 500, 30, 10, key="col_min")

A = asg[(asg["assigned_date"] >= d0) & (asg["assigned_date"] <= d1 + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))]
A = A[A["team"].isin(teams) & A["primary_channel"].isin(channels)]
F.stop_if_empty(A)
X = act[act["assignment_id"].isin(set(A["assignment_id"]))]

# ------------------------------------------------------------------ KPI
tot = M._assignment_metrics(A)
am = M._action_metrics(X)
cost_per = am["Biaya (Rp jt)"] / tot["Tertagih (Rp jt)"] if tot["Tertagih (Rp jt)"] else np.nan
k = st.columns(5)
k[0].metric("Akun ditagih", ui.num(tot["Akun"]))
k[1].metric("Cure rate", ui.pct(tot["Cure rate"]))
k[2].metric("Recovery rate", ui.pct(tot["Recovery rate"]))
k[3].metric("PTP kept rate", ui.pct(am["PTP kept rate"]))
k[4].metric("Biaya per Rp1 jt tertagih", f"Rp {cost_per * 1e6:,.0f}".replace(",", "."))
ui.note("**Cure** = akun delinquent awal bulan yang kembali Current/lunas di akhir bulan. **Recovery** = tertagih ÷ tagihan "
        "(tunggakan + cicilan berjalan). **PTP kept** = janji bayar yang ditepati ÷ janji bayar yang dibuat.")

tab_lb, tab_ch, tab_tr, tab_dt = st.tabs(["Leaderboard", "Channel", "Tren", "Detail collector"])

# ================================================================== leaderboard
with tab_lb:
    sc = M.scorecard(A, X, ["collector_id", "collector_name", "team"])
    sc = sc[sc["Akun"] >= min_acc]
    if sc.empty:
        st.info("Tidak ada collector yang memenuhi minimum akun. Turunkan batas minimum di sidebar.")
    else:
        sc = M.add_composite(sc, "team")
        sc["Rating"] = sc["Skor"].map(M.rating)
        sc = sc.sort_values(["team", "Peringkat di tim"])
        show = sc[["collector_id", "collector_name", "team", "Akun", "Cure rate", "Recovery rate", "PTP kept rate",
                   "Contact rate", "Biaya per Rp1 jt tertagih", "Skor", "Peringkat di tim", "Rating"]].rename(
            columns={"collector_id": "ID", "collector_name": "Collector", "team": "Tim"})
        st.dataframe(show, hide_index=True, width="stretch", column_config={
            "Akun": st.column_config.NumberColumn(format="%d"),
            "Cure rate": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
            "Recovery rate": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
            "PTP kept rate": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
            "Contact rate": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
            "Biaya per Rp1 jt tertagih": st.column_config.NumberColumn("Biaya / Rp1 jt", format="Rp %.0f"),
            "Skor": st.column_config.ProgressColumn(format="%.0f", min_value=0, max_value=100),
        })
        ui.note("Skor = 40% cure + 35% recovery + 25% PTP kept, masing-masing sebagai peringkat persentil DI DALAM tim "
                "(tim Late menangani bucket sulit sehingga angka mentahnya tidak bisa dibandingkan langsung dengan tim Early).")
        st.download_button("Unduh leaderboard CSV", show.to_csv(index=False).encode("utf-8"), "collector_scorecard.csv",
                           "text/csv", key="col_dl")

        fig = px.scatter(sc, x="Cure rate", y="Recovery rate", size="Akun", color="team", hover_name="collector_name",
                         color_discrete_sequence=C.PALETTE_SEQ, size_max=28)
        fig.update_layout(xaxis_tickformat=".0%", yaxis_tickformat=".0%", legend_title_text="")
        ui.show(ui.style(fig, 380, title="Cure rate vs recovery rate (ukuran = jumlah akun)"), "col_scatter")

# ================================================================== channel
with tab_ch:
    left, right = st.columns(2)
    chs = M.scorecard(A, X, ["team", "primary_channel"])
    with left:
        hm = chs.pivot(index="team", columns="primary_channel", values="Cure rate").reindex(index=C.TEAMS, columns=C.CHANNELS) * 100
        txt = [[("" if np.isnan(v) else f"{v:.1f}%") for v in r] for r in hm.to_numpy()]
        fig = go.Figure(go.Heatmap(z=hm.to_numpy(), x=hm.columns, y=hm.index, text=txt, texttemplate="%{text}",
                                   colorscale="Greens", colorbar=dict(title="%"),
                                   hovertemplate="%{y} · %{x}: %{z:.1f}%<extra></extra>"))
        fig.update_yaxes(autorange="reversed")
        ui.show(ui.style(fig, 300, title="Cure rate: tim × channel utama"), "ch_heat")
    with right:
        ach = X.groupby("channel").apply(M._action_metrics, include_groups=False).reindex(C.CHANNELS).dropna(how="all").reset_index()
        fig = go.Figure()
        fig.add_bar(x=ach["channel"], y=ach["Contact rate"] * 100, name="Contact rate", marker_color="#3B6EA5")
        fig.add_bar(x=ach["channel"], y=ach["PTP kept rate"] * 100, name="PTP kept rate", marker_color="#2E7D5B")
        fig.update_layout(barmode="group", yaxis_title="%")
        ui.show(ui.style(fig, 300, title="Kualitas kontak per channel (level aksi)"), "ch_bar")
    show = chs.rename(columns={"team": "Tim", "primary_channel": "Channel utama"})
    st.dataframe(show, hide_index=True, width="stretch", column_config={
        "Akun": st.column_config.NumberColumn(format="%d"),
        "Cure rate": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
        "Recovery rate": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
        "PTP kept rate": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
        "Contact rate": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
        "Roll-worse rate": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
        "Biaya per Rp1 jt tertagih": st.column_config.NumberColumn("Biaya / Rp1 jt", format="Rp %.0f"),
    })
    ui.note("Bandingkan channel DI DALAM tim yang sama: Field Visit hanya dipakai untuk bucket dalam sehingga cure rate "
            "agregatnya terlihat rendah karena mix akun, bukan karena channelnya buruk.")

# ================================================================== tren
with tab_tr:
    A2 = A.copy()
    A2["Bulan"] = A2["month"]
    g = A2.groupby(["Bulan", "team"]).agg(cure=("cured", "mean"), n=("cured", "size"),
                                         due=("amount_due", "sum"), got=("collected_amount", "sum")).reset_index()
    g["recovery"] = g["got"] / g["due"]
    metric = st.radio("Metrik", ["Cure rate", "Recovery rate"], horizontal=True, key="col_tr_metric")
    yv = "cure" if metric.startswith("Cure") else "recovery"
    fig = px.line(g, x="Bulan", y=yv, color="team", markers=True, color_discrete_sequence=C.PALETTE_SEQ)
    fig.update_layout(yaxis_tickformat=".0%", yaxis_title=metric, xaxis_title=None)
    ui.show(ui.style(fig, 380), "col_trend")
    ui.note("Bulan pertama/terakhir pada rentang tanggal bisa parsial sehingga jumlah akunnya lebih kecil.")

# ================================================================== detail
with tab_dt:
    names = col.sort_values(["team", "collector_id"])
    opts = {f"{r.collector_id} · {r.collector_name} ({r.team})": r.collector_id for r in names.itertuples()
            if r.team in teams}
    if not opts:
        st.info("Pilih minimal satu tim.")
    else:
        pick = st.selectbox("Collector", list(opts.keys()), key="col_pick")
        cid = opts[pick]
        Ac = A[A["collector_id"] == cid]
        if Ac.empty:
            st.info("Collector ini tidak punya penugasan pada filter yang dipilih.")
        else:
            team = Ac["team"].iloc[0]
            At = A[A["team"] == team]
            m_c, m_t = M._assignment_metrics(Ac), M._assignment_metrics(At)
            a_c = M._action_metrics(X[X["collector_id"] == cid])
            a_t = M._action_metrics(X[X["team"] == team])
            c = st.columns(4)
            c[0].metric("Akun", ui.num(m_c["Akun"]))
            c[1].metric("Cure rate", ui.pct(m_c["Cure rate"]), f"{(m_c['Cure rate'] - m_t['Cure rate']) * 100:+.1f} pp vs tim")
            c[2].metric("Recovery rate", ui.pct(m_c["Recovery rate"]), f"{(m_c['Recovery rate'] - m_t['Recovery rate']) * 100:+.1f} pp vs tim")
            c[3].metric("PTP kept rate", ui.pct(a_c["PTP kept rate"]),
                        None if np.isnan(a_c["PTP kept rate"]) or np.isnan(a_t["PTP kept rate"])
                        else f"{(a_c['PTP kept rate'] - a_t['PTP kept rate']) * 100:+.1f} pp vs tim")
            by_ch = M.scorecard(Ac, X[X["collector_id"] == cid], ["primary_channel"])
            fig = px.bar(by_ch, x="primary_channel", y="Cure rate", text=by_ch["Cure rate"].map(lambda v: f"{v:.0%}"),
                         color="primary_channel", color_discrete_map=C.CHANNEL_COLORS)
            fig.update_layout(showlegend=False, yaxis_tickformat=".0%", xaxis_title=None, yaxis_title="Cure rate")
            ui.show(ui.style(fig, 320, title="Cure rate per channel utama"), "det_bar")
            mo = Ac.groupby("month").agg(Akun=("cured", "size"), Cure=("cured", "mean")).reset_index()
            st.dataframe(mo.rename(columns={"month": "Bulan", "Cure": "Cure rate"}), hide_index=True, width="stretch",
                         column_config={"Cure rate": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1)})
