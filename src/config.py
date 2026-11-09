"""Konstanta global untuk dashboard Collection Performance & Delinquency."""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------- path
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"

DATA_FILES = {
    "loans": DATA_DIR / "loans.parquet",
    "snapshots": DATA_DIR / "snapshots.parquet",
    "payments": DATA_DIR / "payments.parquet",
    "assignments": DATA_DIR / "assignments.parquet",
    "actions": DATA_DIR / "actions.parquet",
    "collectors": DATA_DIR / "collectors.parquet",
}

# ---------------------------------------------------------------- simulasi
SEED = 20261108
N_LOANS = 24_000
FIRST_VINTAGE = "2025-01"          # bulan pencairan pertama
LAST_VINTAGE = "2026-10"           # bulan pencairan terakhir
LAST_SNAPSHOT = "2026-10"          # posisi akhir bulan terakhir (data s.d. 31 Okt 2026)

# ---------------------------------------------------------------- bucket
# index 0..4 = bucket aktif, 5 = write-off (absorbing)
BUCKETS = ["Current", "1-30", "31-60", "61-90", "90+"]
STATES = BUCKETS + ["Write-off"]
N_ACTIVE = len(BUCKETS)
WRITEOFF_IDX = 5

BUCKET_COLORS = {
    "Current": "#2E7D5B",
    "1-30": "#E3B341",
    "31-60": "#F08A3C",
    "61-90": "#D9534F",
    "90+": "#8E1B3A",
    "Write-off": "#4B4B4B",
}

# ---------------------------------------------------------------- produk & segmen
PRODUCTS = ["Pinjaman Tunai", "PayLater", "Cicilan Gadget"]
RISK_BANDS = ["A (Low Risk)", "B (Medium Risk)", "C (High Risk)"]
REGIONS = [
    "DKI Jakarta", "Jawa Barat", "Jawa Tengah", "Jawa Timur", "Banten",
    "Sumatera Utara", "Sulawesi Selatan", "Bali", "Kalimantan Timur", "Lainnya",
]

# ---------------------------------------------------------------- penagihan
CHANNELS = ["SMS", "WhatsApp", "Call", "Field Visit"]
CHANNEL_COLORS = {
    "SMS": "#8DA0B3",
    "WhatsApp": "#2E7D5B",
    "Call": "#3B6EA5",
    "Field Visit": "#B5543B",
}

OUTCOMES = [
    "No Contact",
    "Contacted - No Commitment",
    "Refused / Dispute",
    "Promise to Pay",
    "Paid Immediately",
]

TEAMS = ["Early (1-30)", "Mid (31-60)", "Late (61+)"]
# bucket awal bulan -> tim yang menangani
TEAM_BY_BUCKET = {1: "Early (1-30)", 2: "Mid (31-60)", 3: "Late (61+)", 4: "Late (61+)"}
TEAM_SIZE = {"Early (1-30)": 10, "Mid (31-60)": 8, "Late (61+)": 6}

# channel yang tersedia per tim beserta bobot pemilihan
TEAM_CHANNEL_WEIGHTS = {
    "Early (1-30)": {"SMS": 0.35, "WhatsApp": 0.35, "Call": 0.30, "Field Visit": 0.0},
    "Mid (31-60)": {"SMS": 0.10, "WhatsApp": 0.30, "Call": 0.45, "Field Visit": 0.15},
    "Late (61+)": {"SMS": 0.0, "WhatsApp": 0.10, "Call": 0.40, "Field Visit": 0.50},
}

# efektivitas relatif channel (mengubah logit peluang cure)
CHANNEL_EFFECT = {"SMS": -0.15, "WhatsApp": 0.05, "Call": 0.25, "Field Visit": 0.45}

# ---------------------------------------------------------------- tampilan
PALETTE_SEQ = ["#3B6EA5", "#2E7D5B", "#E3B341", "#F08A3C", "#D9534F", "#8E1B3A", "#7B6D8D", "#4B4B4B"]
APP_TITLE = "Collection Performance & Delinquency"
APP_ICON = "📉"
