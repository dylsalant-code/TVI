"""
TVI (Total Value Index) auto-updater.
Scrapes Basketball-Reference, calculates TVI for every qualified player,
and writes data/tvi_latest.csv + docs/index.html (the public rankings page).
"""
import datetime as dt
import io
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import requests

import config as C

ROOT = Path(__file__).parent
DATA = ROOT / "data"
CACHE = DATA / "cache"
HIST = DATA / "history"
DOCS = ROOT / "docs"
BASE = "https://www.basketball-reference.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (TVI student research project)"}
PILLARS = ["production", "efficiency", "availability", "playoffs", "market"]


# ---------------------------------------------------------------- helpers
def today():
    return dt.date.today()


def season_end_year(d=None):
    """2026-27 season -> 2027. Flips to the new season in October."""
    d = d or today()
    return d.year + 1 if d.month >= 10 else d.year


def season_label(year):
    return f"{year - 1}-{str(year)[2:]}"


def norm(name):
    """Normalize names so 'Nikola Jokić' and 'Nikola Jokic' match."""
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z ]", "", s.lower())
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return " ".join(s.split())


def pct(s):
    """Percentile rank 0-100 within the group."""
    return s.rank(pct=True) * 100


def composite(df, cols):
    """Average of each stat's percentile, re-ranked so it spreads 0-100."""
    parts = [pct(pd.to_numeric(df[c], errors="coerce")) for c in cols if c in df.columns]
    return pct(pd.concat(parts, axis=1).mean(axis=1)).fillna(0)


def num(df, cols):
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")


# ---------------------------------------------------------------- scraping
_last_request = [0.0]


def fetch_html(url):
    wait = C.SECONDS_BETWEEN_REQUESTS - (time.time() - _last_request[0])
    if wait > 0:
        time.sleep(wait)
    status = None
    for attempt in range(3):
        r = requests.get(url, headers=HEADERS, timeout=30)
        _last_request[0] = time.time()
        status = r.status_code
        if status == 200:
            r.encoding = "utf-8"  # keeps names like Jokić from getting garbled
            # bbref hides some tables inside HTML comments
            return r.text.replace("<!--", "").replace("-->", "")
        if status == 404:
            return None
        time.sleep(60 * (attempt + 1) if status == 429 else 10)
    raise RuntimeError(f"Couldn't load {url} (status {status})")


def flatten(t):
    if isinstance(t.columns, pd.MultiIndex):
        t.columns = [c[-1] for c in t.columns]
    return t


def pick_table(html, must_have):
    try:
        tables = pd.read_html(io.StringIO(html))
    except Exception:  # no tables on the page
        return None
    best = None
    for t in tables:
        t = flatten(t)
        if all(c in t.columns for c in must_have) and (best is None or len(t) > len(best)):
            best = t
    return best


def clean(df):
    df = df.rename(columns={"Tm": "Team"})
    df = df.loc[:, ~df.columns.duplicated()]
    df = df[df["Player"].notna()]
    df = df[~df["Player"].isin(["Player", "League Average"])].copy()
    df["Player"] = df["Player"].astype(str).str.replace("*", "", regex=False).str.strip()
    df["key"] = df["Player"].map(norm)
    # traded players: bbref lists the combined row (2TM/3TM/TOT) first
    return df.drop_duplicates("key", keep="first")


def get_page(url, cache_name, use_cache, must_have):
    path = CACHE / f"{cache_name}.csv"
    if use_cache and path.exists():
        return pd.read_csv(path)
    html = fetch_html(url)
    if html is None:
        return None
    t = pick_table(html, must_have)
    if t is None:
        return None
    t = clean(t)
    if use_cache and len(t):
        CACHE.mkdir(parents=True, exist_ok=True)
        t.to_csv(path, index=False)
    return t


# ---------------------------------------------------------------- pillars
def load_regular(year, use_cache):
    per = get_page(f"{BASE}/leagues/NBA_{year}_per_game.html", f"per_game_{year}",
                   use_cache, ["Player", "G", "MP", "PTS", "TRB", "AST"])
    adv = get_page(f"{BASE}/leagues/NBA_{year}_advanced.html", f"advanced_{year}",
                   use_cache, ["Player", "TS%", "BPM", "VORP", "WS/48"])
    if per is None or adv is None or per.empty:
        return None

    adv = adv[["key", "MP", "TS%", "WS", "WS/48", "BPM", "VORP"]].rename(columns={"MP": "MP_total"})
    df = per.merge(adv, on="key", how="inner")
    num(df, ["Age", "G", "MP", "MP_total", "WS"] + C.PRODUCTION_STATS + C.EFFICIENCY_STATS)
    df = df[df["G"] > 0]
    if df.empty:
        return None

    max_g = df["G"].max()  # ~ games played so far this season
    df = df[df["MP_total"] >= C.MIN_MINUTES_PER_TEAM_GAME * max_g].set_index("key")

    df["production"] = composite(df, C.PRODUCTION_STATS)
    df["efficiency"] = composite(df, C.EFFICIENCY_STATS)
    avail = pd.DataFrame({"games_share": (df["G"] / max_g).clip(upper=1), "mpg": df["MP"]})
    df["availability"] = composite(avail, ["games_share", "mpg"])
    return df


def load_playoffs(year, use_cache):
    t = get_page(f"{BASE}/playoffs/NBA_{year}_advanced.html", f"playoffs_{year}",
                 use_cache, ["Player", "MP", "BPM", "WS"])
    if t is None or t.empty:
        return None
    num(t, ["MP"] + C.PLAYOFF_STATS)
    t = t[t["MP"] >= C.MIN_PLAYOFF_MINUTES].set_index("key")
    return composite(t, C.PLAYOFF_STATS) if len(t) else None


def load_market(df):
    """Manual 0-100 scores in data/market_value.csv. New players get the default."""
    path = DATA / "market_value.csv"
    if path.exists():
        m = pd.read_csv(path)
    else:
        m = pd.DataFrame(columns=["Player", "Score"])
    m["key"] = m["Player"].map(norm)
    m = m.drop_duplicates("key")
    new = df.loc[~df.index.isin(m["key"]), ["Player"]].reset_index()
    new["Score"] = C.DEFAULT_MARKET_SCORE
    m = pd.concat([m, new], ignore_index=True)
    DATA.mkdir(parents=True, exist_ok=True)
    m.sort_values("Player")[["Player", "Score"]].to_csv(path, index=False)
    scores = pd.to_numeric(m.set_index("key")["Score"], errors="coerce")
    return scores.reindex(df.index).fillna(C.DEFAULT_MARKET_SCORE).clip(0, 100)


def load_salaries(year):
    html = fetch_html(f"{BASE}/contracts/players.html")
    if html is None:
        return pd.Series(dtype=float)
    t = pick_table(html, ["Player"])
    sal_cols = [c for c in t.columns if re.fullmatch(r"\d{4}-\d{2}", str(c))]
    if not sal_cols:
        return pd.Series(dtype=float)
    col = season_label(year) if season_label(year) in sal_cols else sal_cols[0]
    t = clean(t)
    sal = pd.to_numeric(t[col].astype(str).str.replace(r"[$,]", "", regex=True), errors="coerce")
    return pd.Series(sal.values, index=t["key"]).dropna()


# ---------------------------------------------------------------- main
def main():
    bad = set(C.WEIGHTS) - set(PILLARS)
    if bad:
        sys.exit(f"Unknown pillar(s) in config.WEIGHTS: {bad}")

    year = C.SEASON_OVERRIDE or season_end_year()
    cur = load_regular(year, use_cache=False)
    if cur is None:
        print(f"No {season_label(year)} data yet — using {season_label(year - 1)}.")
        year -= 1
        cur = load_regular(year, use_cache=False)
        if cur is None:
            sys.exit("Couldn't load any season data.")

    # Early season: blend with last season until players hit BLEND_GAMES
    prev = load_regular(year - 1, use_cache=True)
    if prev is not None:
        w = (cur["G"] / C.BLEND_GAMES).clip(upper=1)
        has_prev = cur.index.isin(prev.index)
        for p in ["production", "efficiency", "availability"]:
            old = prev[p].reindex(cur.index)
            cur[p] = np.where(has_prev, w * cur[p] + (1 - w) * old, cur[p])

    # Playoffs: this year's once enough players qualify, otherwise last year's
    po, po_year = None, year
    if today() >= dt.date(year, 4, 10):
        po = load_playoffs(year, use_cache=today() > dt.date(year, 7, 1))
        if po is not None and len(po) < C.MIN_PLAYOFF_PLAYERS:
            po = None
    if po is None:
        po, po_year = load_playoffs(year - 1, use_cache=True), year - 1
    cur["playoffs"] = (po.reindex(cur.index) if po is not None
                       else pd.Series(np.nan, index=cur.index)).fillna(C.NO_PLAYOFFS_SCORE)

    cur["market"] = load_market(cur)

    total_w = sum(C.WEIGHTS.values())
    cur["base"] = sum(cur[p] * wt for p, wt in C.WEIGHTS.items()) / total_w

    # Contract Efficiency Multiplier: value percentile vs salary percentile
    try:
        sal = load_salaries(year)
    except Exception as e:  # never let contracts kill the whole update
        print(f"Warning: salaries failed ({e}); multiplier set to 1.0")
        sal = pd.Series(dtype=float)
    cur["salary"] = sal.reindex(cur.index)
    has_sal = cur["salary"].fillna(0) > 0
    mult = pd.Series(1.0, index=cur.index)
    if has_sal.sum() > 10:
        gap = pct(cur.loc[has_sal, "base"]) - pct(cur.loc[has_sal, "salary"])
        mult[has_sal] = 1 + C.CONTRACT_MAX_ADJUST * gap / 100
    cur["contract_mult"] = mult
    cur["TVI"] = (cur["base"] * mult).clip(0, 100)

    # Output
    cols = ["Player", "Team", "Pos", "Age", "G"] + PILLARS + ["base", "contract_mult", "salary", "TVI"]
    out = cur.reset_index()[[c for c in cols if c in cur.reset_index().columns]]
    out = out.sort_values("TVI", ascending=False).reset_index(drop=True)
    out.insert(0, "Rank", out.index + 1)
    for c in PILLARS + ["base", "TVI"]:
        out[c] = out[c].astype(float).round(1)
    out["contract_mult"] = out["contract_mult"].round(3)

    HIST.mkdir(parents=True, exist_ok=True)
    out.to_csv(DATA / "tvi_latest.csv", index=False)
    out.to_csv(HIST / f"tvi_{today().isoformat()}.csv", index=False)
    write_html(out, year, po_year)
    print(f"TVI updated: {len(out)} players, {season_label(year)} season. "
          f"#1: {out.iloc[0]['Player']} ({out.iloc[0]['TVI']})")


def write_html(out, year, po_year):
    DOCS.mkdir(parents=True, exist_ok=True)
    rows = json.loads(out.drop(columns=["salary"]).to_json(orient="records"))
    meta = {"season": season_label(year), "updated": today().strftime("%b %d, %Y"),
            "playoffs": season_label(po_year)}
    html = TEMPLATE.replace("__ROWS__", json.dumps(rows)).replace("__META__", json.dumps(meta))
    (DOCS / "index.html").write_text(html, encoding="utf-8")


TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TVI Rankings</title>
<style>
:root{--bg:#fafaf7;--fg:#16181d;--mute:#6b6f78;--line:#e3e3dd;--acc:#1d5bd8;--row:#f1f1ec}
@media (prefers-color-scheme:dark){:root{--bg:#121316;--fg:#ececea;--mute:#9a9ea8;--line:#2a2c31;--acc:#7aa7ff;--row:#1a1c20}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.4 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:28px 16px}
h1{margin:0;font-size:34px;letter-spacing:-.02em}.sub{color:var(--mute);margin:4px 0 18px}
input{width:100%;max-width:320px;padding:9px 12px;border:1px solid var(--line);border-radius:8px;
background:var(--bg);color:var(--fg);font:inherit;margin-bottom:14px}
.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;min-width:820px}
th,td{padding:8px 10px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}
th{cursor:pointer;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--mute);user-select:none}
th:nth-child(2),td:nth-child(2),th:nth-child(3),td:nth-child(3){text-align:left}
tbody tr:hover{background:var(--row)}td.tvi{font-weight:700;color:var(--acc)}
.foot{color:var(--mute);font-size:13px;margin-top:16px}
</style></head><body><main>
<h1>Total Value Index</h1>
<div class="sub" id="sub"></div>
<input id="q" placeholder="Search player or team">
<div class="wrap"><table><thead><tr id="hd"></tr></thead><tbody id="bd"></tbody></table></div>
<div class="foot">Auto-updated daily from Basketball-Reference. Click a column to sort.</div>
</main><script>
const ROWS=__ROWS__, META=__META__;
const COLS=[["Rank","#"],["Player","Player"],["Team","Team"],["G","G"],["production","Prod"],
["efficiency","Eff"],["availability","Avail"],["playoffs","Playoff"],["market","Market"],
["contract_mult","Contract"],["TVI","TVI"]];
document.getElementById("sub").textContent=META.season+" season · updated "+META.updated+" · playoff pillar uses "+META.playoffs+" playoffs";
let key="TVI",dir=-1;
const hd=document.getElementById("hd");
COLS.forEach(([k,l])=>{const th=document.createElement("th");th.textContent=l;
th.onclick=()=>{dir=key===k?-dir:(k==="Player"||k==="Team"||k==="Rank"?1:-1);key=k;draw()};hd.appendChild(th)});
function draw(){const q=document.getElementById("q").value.toLowerCase();
const r=ROWS.filter(x=>(x.Player+" "+x.Team).toLowerCase().includes(q))
.sort((a,b)=>(a[key]>b[key]?1:a[key]<b[key]?-1:0)*dir);
document.getElementById("bd").innerHTML=r.map(x=>"<tr>"+COLS.map(([k])=>{let v=x[k];
if(k==="contract_mult")v=(v>=1?"+":"")+((v-1)*100).toFixed(1)+"%";
return "<td"+(k==="TVI"?' class="tvi"':"")+">"+(v??"")+"</td>"}).join("")+"</tr>").join("")}
document.getElementById("q").oninput=draw;draw();
</script></body></html>"""


if __name__ == "__main__":
    main()
