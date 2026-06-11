"""SQLite database operations for Sporttery data."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from src.sp_movement import latest_records

_SQLITE_PATH = Path(__file__).resolve().parent.parent / "data" / "sporttery.db"


# DDL

DDL_RAW_SNAPSHOT = """
CREATE TABLE IF NOT EXISTS sporttery_raw_snapshot (
    id INTEGER PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    request_params TEXT NULL,
    match_id TEXT NULL,
    snapshot_time TEXT NOT NULL,
    raw_content TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    http_status INTEGER NULL,
    parse_status INTEGER DEFAULT 0,
    error_message TEXT NULL,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
"""


DDL_MATCH = """
CREATE TABLE IF NOT EXISTS sporttery_match (
    id INTEGER PRIMARY KEY,
    match_id TEXT NOT NULL UNIQUE,
    match_num TEXT NULL,
    league_id TEXT NULL,
    league_name TEXT NULL,
    home_team_id TEXT NULL,
    away_team_id TEXT NULL,
    home_team_name TEXT NULL,
    away_team_name TEXT NULL,
    match_time TEXT NULL,
    match_status TEXT NULL,
    match_status_name TEXT NULL,
    home_score_90 INTEGER NULL,
    away_score_90 INTEGER NULL,
    result_90 TEXT NULL,
    half_score TEXT NULL,
    full_score_90 TEXT NULL,
    result_source TEXT NULL,
    result_updated_at TEXT NULL,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
"""


DDL_SP_SNAPSHOT = """
CREATE TABLE IF NOT EXISTS sporttery_sp_snapshot (
    id INTEGER PRIMARY KEY,
    match_id TEXT NOT NULL,
    snapshot_time TEXT NOT NULL,
    play_type TEXT NOT NULL,
    option_code TEXT NOT NULL,
    option_name TEXT NULL,
    sp_value REAL NOT NULL,
    goal_line TEXT NULL,
    is_single INTEGER DEFAULT 0,
    implied_prob_raw REAL NULL,
    implied_prob_norm REAL NULL,
    prob_sum REAL NULL,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE (match_id, snapshot_time, play_type, option_code)
);
"""


DDL_SIGNAL = """
CREATE TABLE IF NOT EXISTS sporttery_signal (
    id INTEGER PRIMARY KEY,
    match_id TEXT NOT NULL,
    snapshot_time TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    signal_level TEXT NOT NULL,
    play_type TEXT NULL,
    option_code TEXT NULL,
    description TEXT NOT NULL,
    evidence_json TEXT NULL,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
"""


# Connection

class Connection:
    """Small SQLite connection wrapper used by the project."""

    def __init__(self):
        _SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(_SQLITE_PATH))
        self._conn.row_factory = sqlite3.Row

    def cursor(self):
        return self._conn.cursor()

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    def execute(self, sql: str, params=None):
        cur = self._conn.cursor()
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        return cur

    def executemany(self, sql: str, params_list):
        cur = self._conn.cursor()
        cur.executemany(sql, params_list)
        return cur


def get_connection() -> Connection:
    """Return a new SQLite database connection."""
    return Connection()


def ensure_tables(conn: Connection | None = None) -> None:
    """Create tables if they don't exist."""
    close = False
    if conn is None:
        conn = get_connection()
        close = True
    try:
        conn.execute(DDL_RAW_SNAPSHOT)
        conn.execute(DDL_MATCH)
        conn.execute(DDL_SP_SNAPSHOT)
        conn.execute(DDL_SIGNAL)
        _ensure_match_result_columns(conn)
        conn.commit()
    finally:
        if close:
            conn.close()


# Raw snapshot

def save_raw_snapshot(
    conn: Connection,
    source_name: str,
    source_url: str,
    raw_json: dict,
    match_id: str | None = None,
    request_params: dict | None = None,
) -> bool:
    """Save raw API response. Returns True if inserted, False if duplicate."""
    raw_str = json.dumps(raw_json, ensure_ascii=False, separators=(",", ":"))
    content_hash = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur = conn.execute(
        """
        INSERT OR IGNORE INTO sporttery_raw_snapshot
            (source_name, source_url, request_params, match_id,
             snapshot_time, raw_content, content_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_name, source_url,
            json.dumps(request_params, ensure_ascii=False) if request_params else None,
            match_id, now, raw_str, content_hash,
        ),
    )
    conn.commit()
    return cur.rowcount > 0


# Match

def save_match(conn: Connection, match: dict) -> None:
    """UPSERT a match record."""
    m = dict(match)
    if m.get("match_time") and hasattr(m["match_time"], "strftime"):
        m["match_time"] = m["match_time"].strftime("%Y-%m-%d %H:%M:%S")

    conn.execute(
        """
        INSERT INTO sporttery_match
            (match_id, match_num, league_id, league_name,
             home_team_id, away_team_id, home_team_name, away_team_name,
             match_time, match_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(match_id) DO UPDATE SET
            match_num=excluded.match_num, league_id=excluded.league_id,
            league_name=excluded.league_name, home_team_id=excluded.home_team_id,
            away_team_id=excluded.away_team_id, home_team_name=excluded.home_team_name,
            away_team_name=excluded.away_team_name, match_time=excluded.match_time,
            match_status=excluded.match_status
        """,
        (
            m["match_id"], m.get("match_num"), m.get("league_id"),
            m.get("league_name"), m.get("home_team_id"), m.get("away_team_id"),
            m.get("home_team_name"), m.get("away_team_name"),
            m.get("match_time"), m.get("match_status"),
        ),
    )
    conn.commit()


def save_matches(conn: Connection, matches: list[dict]) -> int:
    """UPSERT multiple match records. Returns count."""
    for m in matches:
        save_match(conn, m)
    return len(matches)


def save_match_result(conn: Connection, result: dict) -> None:
    """UPSERT one match result from Sporttery football data."""
    r = dict(result)
    if r.get("match_time") and hasattr(r["match_time"], "strftime"):
        r["match_time"] = r["match_time"].strftime("%Y-%m-%d %H:%M:%S")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn.execute(
        """
        INSERT INTO sporttery_match
            (match_id, match_num, league_id, league_name,
             home_team_id, away_team_id, home_team_name, away_team_name,
             match_time, match_status, match_status_name,
             home_score_90, away_score_90, result_90,
             half_score, full_score_90, result_source, result_updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(match_id) DO UPDATE SET
            match_num=excluded.match_num,
            league_id=excluded.league_id,
            league_name=excluded.league_name,
            home_team_id=excluded.home_team_id,
            away_team_id=excluded.away_team_id,
            home_team_name=excluded.home_team_name,
            away_team_name=excluded.away_team_name,
            match_time=excluded.match_time,
            match_status=excluded.match_status,
            match_status_name=excluded.match_status_name,
            home_score_90=excluded.home_score_90,
            away_score_90=excluded.away_score_90,
            result_90=excluded.result_90,
            half_score=excluded.half_score,
            full_score_90=excluded.full_score_90,
            result_source=excluded.result_source,
            result_updated_at=excluded.result_updated_at,
            updated_at=datetime('now','localtime')
        """,
        (
            r["match_id"], r.get("match_num"), r.get("league_id"),
            r.get("league_name"), r.get("home_team_id"), r.get("away_team_id"),
            r.get("home_team_name"), r.get("away_team_name"),
            r.get("match_time"), r.get("match_status"), r.get("match_status_name"),
            r.get("home_score_90"), r.get("away_score_90"), r.get("result_90"),
            r.get("half_score"), r.get("full_score_90"),
            r.get("result_source", "sporttery_zqsj"), now,
        ),
    )
    conn.commit()


def save_match_results(conn: Connection, results: list[dict]) -> int:
    """UPSERT multiple match results. Returns count."""
    for result in results:
        save_match_result(conn, result)
    return len(results)


# SP snapshot

def save_sp_snapshots(conn: Connection, records: list[dict]) -> int:
    """Bulk insert SP snapshot records. Each record carries its own snapshot_time."""
    if not records:
        return 0

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for r in records:
        rows.append((
            r["match_id"],
            r.get("snapshot_time", now),
            r["play_type"], r["option_code"],
            r.get("option_name"), r["sp_value"], r.get("goal_line"),
            r.get("is_single", 0), r.get("implied_prob_raw"),
            r.get("implied_prob_norm"), r.get("prob_sum"),
        ))

    conn.executemany(
        """
        INSERT OR REPLACE INTO sporttery_sp_snapshot
            (match_id, snapshot_time, play_type, option_code, option_name,
             sp_value, goal_line, is_single,
             implied_prob_raw, implied_prob_norm, prob_sum)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def fetch_sp_history(
    conn: Connection,
    match_ids: list[str] | tuple[str, ...],
    *,
    play_type: str = "had",
) -> list[dict]:
    """Fetch SP history rows for matches and one play type."""
    if not match_ids:
        return []

    ids = [str(match_id) for match_id in match_ids]
    placeholders = ", ".join(["?"] * len(ids))
    cur = conn.execute(
        f"""
        SELECT *
        FROM sporttery_sp_snapshot
        WHERE play_type = ?
          AND match_id IN ({placeholders})
        ORDER BY match_id, option_code, snapshot_time
        """,
        (play_type, *ids),
    )
    return _fetch_dicts(cur)


def fetch_latest_sp_snapshots(
    conn: Connection,
    match_ids: list[str] | tuple[str, ...],
    *,
    play_type: str = "had",
) -> list[dict]:
    """Fetch latest SP row per match/play/option from stored history."""
    return latest_records(fetch_sp_history(conn, match_ids, play_type=play_type))


def _fetch_dicts(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _ensure_match_result_columns(conn: Connection) -> None:
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(sporttery_match)").fetchall()
    }
    columns = {
        "match_status_name": "TEXT NULL",
        "half_score": "TEXT NULL",
        "full_score_90": "TEXT NULL",
        "result_source": "TEXT NULL",
        "result_updated_at": "TEXT NULL",
    }
    for name, ddl in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE sporttery_match ADD COLUMN {name} {ddl}")
