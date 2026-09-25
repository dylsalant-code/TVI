# ============================================================
#  TVI SETTINGS — edit these. Everything else runs itself.
# ============================================================

# Pillar weights. They currently add to 85, so the script scales
# them to 100 automatically. If TVI has a 6th pillar, add it here
# (and a matching calculation in tvi.py).
WEIGHTS = {
    "production": 20,    # Raw Production
    "efficiency": 30,    # Efficiency & Winning Impact
    "availability": 10,  # Availability & Consistency
    "playoffs": 15,      # Playoff Impact
    "market": 10,        # Off-Court Market Value
}

# Contract Efficiency Multiplier: max boost/penalty (0.15 = ±15%)
CONTRACT_MAX_ADJUST = 0.15

# Which Basketball-Reference stats feed each pillar.
# Each stat is turned into a percentile, then averaged.
PRODUCTION_STATS = ["PTS", "TRB", "AST", "STL", "BLK"]   # per game
EFFICIENCY_STATS = ["TS%", "BPM", "WS/48", "VORP"]
PLAYOFF_STATS = ["WS", "BPM", "VORP"]

# Who counts: minimum total minutes = this × games played so far.
# 5 → about 410 minutes by the end of the season.
MIN_MINUTES_PER_TEAM_GAME = 5

# Playoffs
MIN_PLAYOFF_MINUTES = 40     # below this, playoff stats are noise
MIN_PLAYOFF_PLAYERS = 100    # wait until this many qualify before using this year's playoffs
NO_PLAYOFFS_SCORE = 0        # Playoff Impact score for players who didn't play in them

# Off-Court Market Value: edit data/market_value.csv (0-100).
# New players get this default automatically.
DEFAULT_MARKET_SCORE = 50

# Early-season blending: a player is 100% this-season data
# once he's played this many games. Before that, last season fills in.
BLEND_GAMES = 25

# Be polite to Basketball-Reference (they ban fast scrapers)
SECONDS_BETWEEN_REQUESTS = 4

# Leave as None to auto-pick the season by date (switches in October).
# Set to e.g. 2027 to force the 2026-27 season.
SEASON_OVERRIDE = None
