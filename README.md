# Collection Performance & Delinquency Dashboard

Dashboard Streamlit untuk memantau kualitas portofolio pinjaman dan efektivitas penagihan di sebuah bank digital.
**Seluruh data adalah data dummy (sintetis)** — dibangkitkan oleh `generate_data.py`, tidak ada data nasabah nyata.

## Halaman

| Halaman | Isi |
|---|---|
| **Ringkasan** | KPI eksekutif (outstanding, DPD 30+, NPL 90+, write-off), tren aging, cure rate per tim, sorotan otomatis |
| **Aging & Tren** | Bucket Current / 1-30 / 31-60 / 61-90 / 90+, tren bulanan (nominal & %), rasio delinquency, 20 akun tunggakan terbesar |
| **Roll Rate & Markov** | Matriks roll rate (= matriks transisi Markov), tren roll rate, **proyeksi Markov** + stress test, peluang akhir lunas/write-off (matriks fundamental), **backtest** |
| **Vintage** | Heatmap & kurva Ever 30+/60+/90+/Write-off per kohort bulan pencairan terhadap MOB |
| **Collector Scorecard** | Cure rate, recovery rate, PTP kept rate, contact rate, biaya per Rp tertagih — per collector, tim, dan channel (SMS/WhatsApp/Call/Field Visit); filter tanggal & tim |
| **Segmen Risiko** | Delinquency per produk, risk band, wilayah, pendapatan, vintage |
| **Data & Metodologi** | Data explorer + unduh CSV, definisi metrik, cara data dibangkitkan |

## Struktur

```
app.py               entrypoint (st.navigation)
views/               satu file per halaman
src/
  config.py          konstanta (bucket, channel, tim, seed)
  gen_loans.py       generator pinjaman & collector
  gen_sim.py         simulasi Markov bulanan + penagihan
  data.py            loader ber-cache (generate otomatis bila parquet hilang)
  metrics.py         aging, vintage, scorecard (pandas murni)
  markov.py          estimasi, proyeksi, absorpsi, stress, backtest
  filters.py, ui.py  widget filter, format angka, tema plotly
data/                *.parquet (±4 MB) hasil generate_data.py
tests/               pytest: integritas data, logika, dan AppTest semua halaman
.streamlit/config.toml
```

## Menjalankan lokal

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Bangkitkan ulang data (opsional): `python generate_data.py` atau `python generate_data.py --seed 7`.
Jalankan tes: `pip install -r requirements-dev.txt && pytest`.

## Deploy ke Streamlit Community Cloud

1. Buat repository GitHub baru, lalu dari folder ini:
   ```bash
   git init && git add . && git commit -m "Collection dashboard"
   git branch -M main
   git remote add origin https://github.com/<username>/<repo>.git
   git push -u origin main
   ```
2. Buka <https://share.streamlit.io> → **Create app** → pilih repository & branch `main`.
3. **Main file path**: `app.py`. Di *Advanced settings* pilih Python 3.11, 3.12, atau 3.13.
4. **Deploy**. Dependensi dibaca dari `requirements.txt`; tidak ada secret/API key yang dibutuhkan.

Folder `data/` sudah dikomit, jadi aplikasi langsung jalan. Bila folder itu terhapus, `src/data.py` membangkitkan ulang
data otomatis (±2 detik) saat pertama kali dibuka.

## Catatan metodologi singkat

* **Roll rate** = % akun di bucket *i* pada akhir bulan *t* yang berada di bucket *j* pada *t+1*. Ruang keadaan: 5 bucket + *Lunas* + *Write-off* (absorbing).
* **Proyeksi**: v<sub>t</sub> = v<sub>0</sub>·P<sup>t</sup>. **Absorpsi**: B = (I−Q)<sup>−1</sup>R. Proyeksi adalah run-off portofolio yang ada (tanpa pencairan baru) dengan asumsi matriks tetap.
* **Backtest** melatih matriks hanya dari transisi sebelum titik asal, lalu membandingkan proyeksi dengan realisasi kohort yang sama. Error terbesar ada pada *Lunas* (waktu pelunasan bergantung tenor → tidak homogen waktu) dan pada bucket delinquent (kualitas vintage berubah).
* **Cure rate** = akun delinquent awal bulan yang kembali Current/lunas di akhir bulan; **Recovery** = tertagih ÷ (tunggakan + cicilan berjalan); **PTP kept** = janji bayar ditepati ÷ dibuat.
* **Skor collector** dihitung sebagai peringkat persentil *di dalam tim*, karena tim Late menangani bucket yang jauh lebih sulit.
* Perbandingan channel sebaiknya dilakukan di dalam tim yang sama (Field Visit hanya dipakai pada bucket dalam).
