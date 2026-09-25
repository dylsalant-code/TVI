# TVI — Total Value Index (auto-updating)

Every morning, GitHub runs `tvi.py`, which pulls fresh stats from Basketball-Reference,
recalculates TVI for every qualified NBA player, and publishes:

- `data/tvi_latest.csv` — today's rankings
- `data/history/` — a snapshot for every day (great for charts later)
- `docs/index.html` — a public rankings page (search + sort)

## One-time setup (~10 min)
1. Create a free GitHub account and a new **public** repo called `tvi`.
2. Upload everything in this folder (keep the `.github` folder — it's the scheduler).
3. Repo **Settings → Pages** → Source: "Deploy from a branch" → `main` / `/docs` → Save.
4. **Actions** tab → enable workflows → "Update TVI" → **Run workflow** to test it now.
5. Your page lives at `https://YOUR-USERNAME.github.io/tvi/`

Want it in Google Sheets? Put this in cell A1 and it stays synced:
`=IMPORTDATA("https://raw.githubusercontent.com/YOUR-USERNAME/tvi/main/data/tvi_latest.csv")`

## How the season handles itself
- **Season switch:** flips to the new season automatically in October (2026-27 → 2027-28 next fall).
- **Early season:** blends last season's pillar scores until a player has 25 games (`BLEND_GAMES`).
- **Playoff Impact:** uses last year's playoffs until enough players qualify in this year's.
- **Contracts:** pulled daily from Basketball-Reference's contracts page.
- **Off-Court Market Value:** the only manual part — edit `data/market_value.csv` (0-100)
  whenever you want. New players get added automatically at 50.

## Tweaking the formula
All weights and stat choices live in `config.py`. Change a number, commit, done.

## Testing without internet
`python tests/test_offline.py` runs the whole pipeline on fake data.
