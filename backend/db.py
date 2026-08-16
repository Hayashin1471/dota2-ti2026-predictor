"""SQLite storage: schema, connection helper and small query utilities."""
from __future__ import annotations

import json
import math
import sqlite3
import threading
from typing import Any, Iterable

from . import config

_local = threading.local()

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- HTTP response cache so repeated refreshes stay polite and fast
CREATE TABLE IF NOT EXISTS http_cache (
    url        TEXT PRIMARY KEY,
    fetched_at REAL NOT NULL,
    status     INTEGER NOT NULL,
    body       TEXT NOT NULL
);

-- Every team we know about (TI participants + their historical opponents)
CREATE TABLE IF NOT EXISTS teams (
    team_id       INTEGER PRIMARY KEY,   -- OpenDota team id
    name          TEXT NOT NULL,
    tag           TEXT,
    logo_url      TEXT,
    od_rating     REAL,
    od_wins       INTEGER,
    od_losses     INTEGER,
    last_match_at INTEGER
);

-- The 16 teams at TI 2026, as listed by Liquipedia
CREATE TABLE IF NOT EXISTS ti_teams (
    slug          TEXT PRIMARY KEY,      -- normalised key used by the frontend
    name          TEXT NOT NULL,         -- Liquipedia display name
    team_id       INTEGER,               -- resolved OpenDota id (nullable)
    qualification TEXT,
    region        TEXT,
    logo_url      TEXT,
    source        TEXT
);

CREATE TABLE IF NOT EXISTS ti_players (
    slug TEXT NOT NULL,
    role TEXT,
    name TEXT NOT NULL,
    PRIMARY KEY (slug, name)
);

CREATE TABLE IF NOT EXISTS heroes (
    hero_id       INTEGER PRIMARY KEY,
    name          TEXT,
    localized_name TEXT NOT NULL,
    primary_attr  TEXT,
    attack_type   TEXT,
    roles         TEXT,
    img           TEXT,
    icon          TEXT,
    pub_picks     INTEGER DEFAULT 0,     -- high-bracket public games
    pub_wins      INTEGER DEFAULT 0,
    pro_picks     INTEGER DEFAULT 0,
    pro_wins      INTEGER DEFAULT 0,
    pro_bans      INTEGER DEFAULT 0
);

-- Team-level match history (from OpenDota /teams/{id}/matches)
CREATE TABLE IF NOT EXISTS matches (
    match_id    INTEGER PRIMARY KEY,
    start_time  INTEGER,
    duration    INTEGER,
    radiant_id  INTEGER,
    dire_id     INTEGER,
    radiant_win INTEGER,
    league_id   INTEGER,
    league_name TEXT
);
CREATE INDEX IF NOT EXISTS idx_matches_time ON matches(start_time);

-- Draft detail for a sample of pro matches (from OpenDota /matches/{id})
CREATE TABLE IF NOT EXISTS match_drafts (
    match_id INTEGER NOT NULL,
    hero_id  INTEGER NOT NULL,
    side     INTEGER NOT NULL,   -- 0 = radiant, 1 = dire
    is_pick  INTEGER NOT NULL,
    PRIMARY KEY (match_id, hero_id, is_pick)
);
CREATE INDEX IF NOT EXISTS idx_drafts_hero ON match_drafts(hero_id);

-- Which match ids we already tried to pull drafts for (so we don't retry forever)
CREATE TABLE IF NOT EXISTS draft_seen (
    match_id INTEGER PRIMARY KEY,
    ok       INTEGER NOT NULL
);

-- Hero vs hero lane/game advantage (from OpenDota /heroes/{id}/matchups)
CREATE TABLE IF NOT EXISTS hero_matchups (
    hero_id    INTEGER NOT NULL,
    vs_hero_id INTEGER NOT NULL,
    games      INTEGER NOT NULL,
    wins       INTEGER NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (hero_id, vs_hero_id)
);

-- TI 2026 schedule / results scraped from GosuGamers
CREATE TABLE IF NOT EXISTS ti_schedule (
    match_key TEXT PRIMARY KEY,
    team_a    TEXT,
    team_b    TEXT,
    score_a   INTEGER,
    score_b   INTEGER,
    status    TEXT,
    stage     TEXT,
    url       TEXT,
    raw       TEXT
);

-- Finished series archive scraped from hawk.live (date-indexed, all tournaments)
CREATE TABLE IF NOT EXISTS series_results (
    key        TEXT PRIMARY KEY,
    source     TEXT NOT NULL,
    played_on  TEXT,                  -- YYYY-MM-DD, null on the rolling page
    tournament TEXT,
    team_a     TEXT NOT NULL,
    team_b     TEXT NOT NULL,
    score_a    INTEGER,
    score_b    INTEGER,
    url        TEXT,
    is_ti      INTEGER DEFAULT 0,
    fetched_at REAL
);
CREATE INDEX IF NOT EXISTS idx_series_day ON series_results(played_on DESC);
CREATE INDEX IF NOT EXISTS idx_series_ti  ON series_results(is_ti);

-- Pro players, keyed by their Steam account id (from OpenDota /teams/{id}/players)
CREATE TABLE IF NOT EXISTS players (
    account_id  INTEGER PRIMARY KEY,
    name        TEXT,
    team_id     INTEGER,               -- team they are listed under
    slug        TEXT,                  -- ti_teams slug, when the team is at TI
    team_games  INTEGER DEFAULT 0,     -- games played for that team
    team_wins   INTEGER DEFAULT 0,
    is_current  INTEGER DEFAULT 1,
    -- totals over the per-hero table below; this is the player's own baseline
    hero_games  INTEGER DEFAULT 0,
    hero_wins   INTEGER DEFAULT 0,
    heroes_updated REAL
);
CREATE INDEX IF NOT EXISTS idx_players_team ON players(team_id);

-- How a player performs on each hero (from OpenDota /players/{id}/heroes)
CREATE TABLE IF NOT EXISTS player_heroes (
    account_id  INTEGER NOT NULL,
    hero_id     INTEGER NOT NULL,
    games       INTEGER NOT NULL,
    wins        INTEGER NOT NULL,
    last_played INTEGER,
    PRIMARY KEY (account_id, hero_id)
);

-- Manual corrections to `players.is_current`.
--
-- OpenDota's "current team member" flag is derived from who has actually been
-- fielded, so it lags a roster move by days - exactly the days that matter
-- during a tournament.  A refresh rewrites `players` wholesale, so a hand fix
-- there would be undone by the next one; these rows are re-applied after every
-- roster refresh instead.  Managed with `python -m backend roster`.
CREATE TABLE IF NOT EXISTS roster_overrides (
    slug       TEXT NOT NULL,        -- ti_teams slug
    account_id INTEGER NOT NULL,
    is_current INTEGER NOT NULL,     -- 1 = force into the lineup, 0 = force out
    note       TEXT,
    created_at REAL,
    PRIMARY KEY (slug, account_id)
);

-- Computed Elo ratings
CREATE TABLE IF NOT EXISTS elo (
    team_id  INTEGER PRIMARY KEY,
    rating   REAL NOT NULL,
    games    INTEGER NOT NULL,
    wins     INTEGER NOT NULL,
    avg_duration REAL,
    last_played INTEGER
);
"""


# Columns added after the first release.  `CREATE TABLE IF NOT EXISTS` will not
# add them to a database that already exists, so they are applied explicitly.
MIGRATIONS = {
    "matches": {
        # Elo of each side *before* the match was played.  Recorded during the
        # rating run so backtests can score the model without looking ahead.
        "pre_elo_radiant": "REAL",
        "pre_elo_dire": "REAL",
        # 'group' or 'playoff' for TI matches, NULL elsewhere.  Filled in by
        # `ingest.label_match_stages` from the GosuGamers bracket.
        "stage": "TEXT",
    },
    "ti_schedule": {
        # ti_teams slugs, resolved when the fixture is stored.  The sources
        # spell teams their own way ("BoomBoys" for BetBoom), and the backend
        # already owns that mapping, so the frontend should not re-guess it.
        "slug_a": "TEXT",
        "slug_b": "TEXT",
    },
    "ti_players": {
        # OpenDota account id, filled in once the Liquipedia roster name is
        # matched against the team's OpenDota player list.
        "account_id": "INTEGER",
    },
}


def _migrate(conn: sqlite3.Connection) -> None:
    for table, columns in MIGRATIONS.items():
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    conn.commit()


def connect() -> sqlite3.Connection:
    """One connection per thread; FastAPI hands requests to a thread pool."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(config.DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        # SQLite's own LOG() is base-10 and is not compiled in everywhere, so we
        # register a natural log under an unambiguous name.
        conn.create_function("LN", 1, lambda x: math.log(x) if x and x > 0 else None)
        conn.executescript(SCHEMA)
        _migrate(conn)
        _local.conn = conn
    return conn


def init() -> None:
    connect()


def get_meta(key: str, default: Any = None) -> Any:
    row = connect().execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except (json.JSONDecodeError, TypeError):
        return row["value"]


def set_meta(key: str, value: Any) -> None:
    conn = connect()
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )
    conn.commit()


def query(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return connect().execute(sql, tuple(params)).fetchall()


def one(sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    return connect().execute(sql, tuple(params)).fetchone()


def execute(sql: str, params: Iterable[Any] = ()) -> None:
    conn = connect()
    conn.execute(sql, tuple(params))
    conn.commit()


def executemany(sql: str, rows: Iterable[Iterable[Any]]) -> None:
    conn = connect()
    conn.executemany(sql, [tuple(r) for r in rows])
    conn.commit()
