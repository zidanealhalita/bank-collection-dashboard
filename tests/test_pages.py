"""Uji end-to-end memakai Streamlit AppTest: tiap halaman dirender, lalu setiap widget diubah-ubah."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent

PAGES = [
    "views/overview.py", "views/aging.py", "views/roll_rate.py", "views/vintage.py",
    "views/collector.py", "views/segments.py", "views/data_info.py",
]
KINDS = ["selectbox", "radio", "select_slider", "multiselect", "slider", "number_input"]
TIMEOUT = 180


def _fresh(page):
    return AppTest.from_file(str(ROOT / page), default_timeout=TIMEOUT).run()


def _check(at, ctx):
    assert not at.exception, f"{ctx}: {[e.value for e in at.exception]}"
    assert not at.error, f"{ctx}: {[e.value for e in at.error]}"


def _pick(seq):
    seq = list(seq)
    if len(seq) <= 4:
        return seq
    return [seq[0], seq[len(seq) // 2], seq[-1]]


def _variants(w, kind):
    """Daftar (label, fungsi-terapan) untuk satu widget."""
    out = []
    if kind in ("selectbox", "radio"):
        opts = list(w.options)
        for i in (0, len(opts) // 2, len(opts) - 1):
            out.append((f"idx{i}", i))
    elif kind == "multiselect":
        out.append(("kosong", []))
        out.append(("satu", [w.options[0]]))
        out.append(("dua", list(w.options[:2])))
    elif kind in ("slider", "number_input"):
        out.append(("min", w.min))
        out.append(("max", w.max))
    return out


def _apply(at, kind, key, variant):
    w = next(x for x in getattr(at, kind) if x.key == key)
    if kind in ("selectbox", "radio"):
        w.select_index(variant) if kind == "selectbox" else w.set_value(w.options[variant])
    else:
        w.set_value(variant)
    return at.run()


@pytest.mark.parametrize("page", PAGES)
def test_page_renders(page):
    at = _fresh(page)
    _check(at, page)
    assert len(at.title) == 1
    # setiap halaman harus punya konten (grafik/tabel/metrik)
    assert at.metric or at.dataframe or at.markdown


@pytest.mark.parametrize("page", PAGES)
def test_widget_fuzz(page):
    base = _fresh(page)
    jobs = []
    for kind in KINDS:
        for w in getattr(base, kind):
            if kind == "select_slider":
                continue  # ditangani terpisah (butuh nilai asli, bukan label)
            for label, variant in _variants(w, kind):
                jobs.append((kind, w.key, label, variant))
    for kind, key, label, variant in jobs:
        at = _fresh(page)
        at = _apply(at, kind, key, variant)
        _check(at, f"{page} :: {kind}[{key}] = {label}")


def test_select_slider_ranges():
    """Slider rentang bulan: coba rentang sempit & penuh pada halaman yang memakainya."""
    for page, key in [("views/aging.py", "aging_period"), ("views/roll_rate.py", "roll_period")]:
        at = _fresh(page)
        w = next(x for x in at.select_slider if x.key == key)
        lo, hi = w.value
        for rng in [(hi, hi), (lo, lo), (lo, hi)]:
            at = _fresh(page)
            w = next(x for x in at.select_slider if x.key == key)
            w.set_value(rng)
            at = at.run()
            _check(at, f"{page} {key} {rng}")


def test_collector_date_filter():
    import datetime as dt

    at = _fresh("views/collector.py")
    w = at.sidebar.date_input[0] if at.sidebar.date_input else at.date_input[0]
    lo, hi = w.min, w.max
    cases = [(lo, hi), (hi - dt.timedelta(days=3), hi), (lo, lo), (dt.date(2026, 3, 1), dt.date(2026, 3, 31))]
    for a, b in cases:
        at = _fresh("views/collector.py")
        w = at.sidebar.date_input[0] if at.sidebar.date_input else at.date_input[0]
        w.set_value((a, b))
        at = at.run()
        _check(at, f"collector dates {a}..{b}")
    # filter tim: hanya satu tim, dan tidak ada tim
    for teams in (["Early (1-30)"], ["Late (61+)"], []):
        at = _fresh("views/collector.py")
        w = next(x for x in at.multiselect if x.key == "col_teams")
        w.set_value(teams)
        at = at.run()
        _check(at, f"collector teams {teams}")


def test_full_app_entrypoint():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=TIMEOUT).run()
    _check(at, "app.py")
