import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from src import config as C
from src import ui
from src.data import load_data

D = load_data()
ui.header("Data & Metodologi", "Kamus data, definisi metrik, dan cara data dummy dibangkitkan.")

tab_d, tab_m, tab_g = st.tabs(["Data explorer", "Definisi metrik", "Cara data dibangkitkan"])

with tab_d:
    names = {"Pinjaman (loans)": "loans", "Snapshot bulanan": "snapshots", "Pembayaran": "payments",
             "Penugasan collector": "assignments", "Aksi penagihan": "actions", "Collector": "collectors"}
    pick = st.selectbox("Tabel", list(names.keys()), key="di_table")
    df = D[names[pick]]
    st.caption(f"{len(df):,} baris × {df.shape[1]} kolom".replace(",", "."))
    n = st.slider("Baris ditampilkan", 10, 1000, 100, 10, key="di_rows")
    st.dataframe(df.head(n), hide_index=True, width="stretch")
    sample = df.head(50_000)
    st.download_button("Unduh 50.000 baris pertama (CSV)", sample.to_csv(index=False).encode("utf-8"),
                       f"{names[pick]}.csv", "text/csv", key="di_dl")

with tab_m:
    st.markdown("""
| Metrik | Definisi |
|---|---|
| **Bucket** | Current (DPD 0), 1-30, 31-60, 61-90, 90+ — diukur pada akhir bulan |
| **DPD 30+** | Outstanding bucket 31-60, 61-90, 90+ ÷ total outstanding aktif |
| **NPL** | Outstanding bucket 90+ ÷ total outstanding aktif |
| **Roll rate** | % akun di bucket *i* pada akhir bulan *t* yang berada di bucket *j* pada akhir bulan *t+1* |
| **Cure rate** | % akun delinquent awal bulan yang kembali Current atau lunas di akhir bulan |
| **Recovery rate** | Jumlah tertagih ÷ tagihan (tunggakan + cicilan berjalan) dari akun yang ditangani |
| **PTP kept rate** | Janji bayar yang ditepati ÷ janji bayar yang dibuat |
| **Contact rate** | Aksi dengan kontak berhasil ÷ seluruh aksi |
| **Ever 30+/60+/90+ @MOB k** | % pinjaman kohort yang pernah mencapai kondisi itu sampai umur k bulan (penyebut = seluruh kohort) |
| **Tim collector** | Early (bucket 1-30), Mid (31-60), Late (61-90 dan 90+) |
""")
    st.markdown("**Matriks Markov.** Keadaan = 5 bucket aktif + 2 keadaan absorbing (*Lunas*, *Write-off*). "
                "Matriks $P$ diestimasi dari frekuensi transisi bulanan. Proyeksi: $v_{t}=v_0P^{t}$. "
                "Probabilitas akhir lunas/write-off: $B=(I-Q)^{-1}R$ dengan $Q$ blok transien dan $R$ blok absorbing.")

with tab_g:
    st.markdown(f"""
**Semua data pada dashboard ini sintetis** (seed `{C.SEED}`), dibangkitkan oleh `generate_data.py`.

1. **Pinjaman**: {C.N_LOANS:,} pinjaman dicairkan {C.FIRST_VINTAGE} s.d. {C.LAST_VINTAGE} pada 3 produk, 3 risk band, 10 wilayah. Vintage Jul-Okt 2025 sengaja dibuat longgar (lebih banyak risk C) dan vintage 2026 lebih ketat.
2. **Lintasan bucket**: tiap pinjaman bergerak antar bucket tiap bulan mengikuti rantai Markov dengan matriks dasar yang disesuaikan (tilt eksponensial) oleh risk band, produk, vintage, umur pinjaman, dan guncangan makro (efek pasca-Lebaran Apr-Mei 2026).
3. **Ledger konsisten**: cicilan tunggakan, cicilan terbayar, outstanding, pelunasan, dan write-off diturunkan dari lintasan bucket.
4. **Penagihan**: akun delinquent awal bulan ditugaskan ke collector sesuai tim; tiap akun mendapat 2-6 aksi (SMS/WhatsApp/Call/Field Visit) yang dikondisikan pada hasil bulan itu (cure, perbaikan, atau roll worse). Kualitas collector dan efektivitas channel memengaruhi peluang transisi.
5. **Keterbatasan**: tidak ada data nyata nasabah; pola seperti Lebaran dan kualitas vintage adalah skenario buatan untuk demonstrasi.
""".replace(",", "."))
