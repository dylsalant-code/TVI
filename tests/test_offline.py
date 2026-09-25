"""Runs the full pipeline against fake Basketball-Reference pages (no internet).
Usage: python tests/test_offline.py"""
import datetime as dt
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
import tvi

rng = np.random.default_rng(7)
import itertools, string
NAMES = [f"{a}{b} {c}{d}son" for a, b, c, d in itertools.islice(itertools.product(string.ascii_uppercase, "aeiou", string.ascii_uppercase, "aeiou"), 300)] + ["Nikola Jokić", "Luka Dončić"]
config.SECONDS_BETWEEN_REQUESTS = 0


def fake_season(games):
    rows = []
    for n in NAMES:
        g = int(rng.integers(1, games + 1))
        rows.append(dict(Rk=1, Player=n, Age=int(rng.integers(19, 38)), Team="BOS", Pos="G", G=g,
                         MP=round(rng.uniform(5, 38), 1), PTS=round(rng.uniform(1, 32), 1),
                         TRB=round(rng.uniform(1, 13), 1), AST=round(rng.uniform(0, 10), 1),
                         STL=round(rng.uniform(0, 2), 1), BLK=round(rng.uniform(0, 2.5), 1),
                         **{"TS%": round(rng.uniform(.45, .68), 3), "WS/48": round(rng.uniform(-.05, .3), 3)},
                         WS=round(rng.uniform(-1, 15), 1), BPM=round(rng.uniform(-6, 12), 1),
                         VORP=round(rng.uniform(-1, 9), 1)))
    df = pd.DataFrame(rows)
    df["MP_total"] = (df["MP"] * df["G"]).round()
    # traded player: combined row first, then team rows; plus repeat header + league avg
    trade = df.iloc[[0]].copy(); trade["Team"] = "2TM"
    extra = df.iloc[[0]].copy(); extra["Team"] = "LAL"
    df = pd.concat([trade, df.iloc[1:], extra], ignore_index=True)
    return df


def per_game_html(df):
    t = df.drop(columns=["MP_total", "TS%", "WS/48", "WS", "BPM", "VORP"])
    hdr = pd.DataFrame([{c: c for c in t.columns}])
    t = pd.concat([t.iloc[:50], hdr, t.iloc[50:],
                   pd.DataFrame([{"Player": "League Average"}])], ignore_index=True)
    return "<!--" + t.to_html(index=False) + "-->"


def adv_html(df):
    t = df[["Rk", "Player", "Team", "G", "MP_total", "TS%", "WS", "WS/48", "BPM", "VORP"]]
    return t.rename(columns={"MP_total": "MP"}).to_html(index=False)


def contracts_html():
    t = pd.DataFrame({("Unnamed", "Player"): NAMES, ("Unnamed", "Tm"): "BOS",
                      ("Salary", "2026-27"): [f"${int(x):,}" for x in rng.uniform(1e6, 55e6, len(NAMES))],
                      ("Salary", "2027-28"): "$1"})
    return t.to_html(index=False)


SEASONS = {2026: fake_season(82), 2027: fake_season(20)}
PLAYOFF = fake_season(20)


def fake_fetch(url):
    h = _fake(url)
    return h.replace("<!--", "").replace("-->", "") if h else None


def _fake(url):
    for y, df in SEASONS.items():
        if url.endswith(f"NBA_{y}_per_game.html"):
            return per_game_html(df)
        if url.endswith(f"leagues/NBA_{y}_advanced.html"):
            return adv_html(df)
    if url.endswith("playoffs/NBA_2026_advanced.html"):
        return adv_html(PLAYOFF.iloc[:180])
    if "contracts" in url:
        return contracts_html()
    return None  # 404


tmp = Path(tempfile.mkdtemp())
tvi.DATA, tvi.CACHE, tvi.HIST, tvi.DOCS = tmp / "data", tmp / "data/cache", tmp / "data/history", tmp / "docs"
tvi.fetch_html = fake_fetch
tvi.today = lambda: dt.date(2026, 11, 20)  # early 2026-27 season

tvi.main()
out = pd.read_csv(tvi.DATA / "tvi_latest.csv")
assert len(out) > 100, len(out)
assert out["TVI"].between(0, 100).all()
assert out["contract_mult"].between(0.85, 1.15).all()
assert out["Player"].is_unique

assert (tvi.DATA / "market_value.csv").exists() and (tvi.DOCS / "index.html").exists()
print(out.head(5).to_string(index=False))

# Offseason fallback: pretend it's Oct 5 2027 with no 2028 data yet
tvi.today = lambda: dt.date(2027, 10, 5)
tvi.main()
print("ALL TESTS PASSED")
shutil.rmtree(tmp)
