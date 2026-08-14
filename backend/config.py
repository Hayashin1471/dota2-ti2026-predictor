"""Central configuration for the TI 2026 prediction app."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
FRONTEND_DIR = ROOT / "frontend"
DB_PATH = DATA_DIR / "dota_ti.sqlite"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# --- Identification -------------------------------------------------------
# Liquipedia's API terms of use require a descriptive User-Agent with contact
# info and gzip encoding.  Override the contact via the DOTA_APP_CONTACT env var.
CONTACT = os.environ.get("DOTA_APP_CONTACT", "local-user@example.com")
LIQUIPEDIA_UA = f"DotaTI2026Predictor/1.0 ({CONTACT})"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# --- Endpoints ------------------------------------------------------------
LIQUIPEDIA_API = "https://liquipedia.net/dota2/api.php"
LIQUIPEDIA_PAGE = "The_International/2026"
GOSU_BASE = "https://www.gosugamers.net"
GOSU_TI_SLUG_HINT = "the-international-2026"
OPENDOTA_API = "https://api.opendota.com/api"
STEAM_CDN = "https://cdn.cloudflare.steamstatic.com"

# --- Politeness -----------------------------------------------------------
# seconds between consecutive requests to the same host
RATE_LIMITS = {
    "liquipedia.net": 2.0,      # Liquipedia asks for >= 2s between parse calls
    "www.gosugamers.net": 1.0,
    "hawk.live": 1.0,
    "api.opendota.com": 1.05,   # free tier: 60 calls/min
}

# HTTP cache TTLs (seconds)
TTL_SHORT = 15 * 60          # live-ish pages (schedule, results)
TTL_MEDIUM = 6 * 60 * 60     # team ratings, hero stats
TTL_LONG = 7 * 24 * 60 * 60  # immutable-ish (finished match details, matchups)

# --- Model knobs ----------------------------------------------------------
OVER_UNDER_LINE_MIN = 41.0   # the over/under line the app is asked to price

# Match length drifts with patches, so the duration baseline uses the narrowest
# recent window that still has enough games; team pace is measured inside its
# own window so era drift is not counted twice.
DURATION_WINDOWS = [120, 180, 365, 640, None]
PACE_WINDOW_DAYS = 400

ELO_START = 1500.0
ELO_K = 28.0
ELO_HISTORY_DAYS = 640       # how far back match history feeds the ratings
ELO_HALF_LIFE_DAYS = 300     # older results count less

# how much the draft is allowed to move the needle relative to team strength.
# Hero win rates are deliberately damped: a hero's pro win rate is partly a
# proxy for which teams pick it, and team strength is already its own term.
W_TEAM = 1.00
W_HERO_WINRATE = 0.30
W_MATCHUP = 0.45

# How much a player's own record on the hero he is assigned counts.  The term
# is measured *relative to that player's overall win rate*, so a strong player
# does not get credit twice (his team's Elo already carries that); what is left
# is hero proficiency, which is a genuinely separate signal.
W_PLAYER_HERO = 0.35
PLAYER_HERO_PRIOR_GAMES = 45   # games needed before a player-hero record counts halfway
PLAYER_EDGE_CAP = 0.30         # per player, log-odds
PLAYER_LOGIT_CAP = 0.60        # for the five players of a side, net of the other side
PLAYER_MIN_GAMES = 3           # below this a record is treated as no information
# A roster refresh costs one request per player, so re-pull a player's hero
# table at most this often.
PLAYER_REFRESH_TTL = 3 * 24 * 60 * 60

# shrinkage pseudo-counts, keeps thin samples from producing silly numbers
HERO_WR_PRIOR_GAMES = 400
PRO_WR_SHRINK = 120          # pro-sample games needed to move a hero halfway
MATCHUP_PRIOR_GAMES = 300
# A hero's mean game length is measured against a residual spread of ~0.27 in
# log space, so a few dozen games is almost pure noise.  This prior keeps a
# hero's duration effect near zero until it has a real sample behind it.
DURATION_PRIOR_GAMES = 120

DEFAULT_DRAFT_SAMPLE = 600   # pro matches to pull picks/duration for by default

# How many calendar days of finished series to pull from hawk.live per refresh.
# Dated pages never change, so they cache for a week and re-runs are cheap.
RESULTS_DAYS = 14
