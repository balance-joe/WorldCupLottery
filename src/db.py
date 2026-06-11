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
    content_hash TEXT NULL,
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

DDL_API_ERROR = """
CREATE TABLE IF NOT EXISTS sporttery_api_error (
    id INTEGER PRIMARY KEY,
    endpoint TEXT NOT NULL,
    request_params TEXT NULL,
    match_id TEXT NULL,
    http_status INTEGER NULL,
    error_message TEXT NOT NULL,
    retry_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
"""

DDL_MARKET_ANALYSIS = """
CREATE TABLE IF NOT EXISTS sporttery_market_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT NOT NULL,
    analysis_time TEXT NOT NULL,
    window TEXT NOT NULL,
    had_direction TEXT,
    hhad_direction TEXT,
    ttg_direction TEXT,
    consistency_level TEXT,
    main_market_expression TEXT,
    research_priority TEXT,
    risk_flags_json TEXT,
    suggested_focus_json TEXT,
    avoid_focus_json TEXT,
    raw_analysis_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(match_id, analysis_time, window)
);
"""


DDL_BETTING_TICKET = """
CREATE TABLE IF NOT EXISTS betting_ticket (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bet_group TEXT NULL,
    ticket_label TEXT NOT NULL,
    pass_type TEXT NOT NULL,
    stake_amount REAL NOT NULL,
    unit_stake REAL DEFAULT 2,
    multiplier INTEGER DEFAULT 1,
    ticket_status TEXT NOT NULL DEFAULT 'pending',
    expected_min_payout REAL NULL,
    expected_max_payout REAL NULL,
    actual_payout REAL NULL,
    profit_loss REAL NULL,
    placed_at TEXT NOT NULL,
    settled_at TEXT NULL,
    notes TEXT NULL,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
"""


DDL_BETTING_TICKET_SELECTION = """
CREATE TABLE IF NOT EXISTS betting_ticket_selection (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL,
    leg_index INTEGER NOT NULL,
    match_id TEXT NOT NULL,
    match_num TEXT NULL,
    play_type TEXT NOT NULL,
    option_code TEXT NOT NULL,
    option_name TEXT NULL,
    goal_line TEXT NULL,
    selected_sp REAL NOT NULL,
    sp_snapshot_id INTEGER NULL,
    sp_snapshot_time TEXT NULL,
    result_status TEXT NOT NULL DEFAULT 'pending',
    actual_result TEXT NULL,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY(ticket_id) REFERENCES betting_ticket(id),
    FOREIGN KEY(sp_snapshot_id) REFERENCES sporttery_sp_snapshot(id),
    UNIQUE(ticket_id, leg_index, match_id, play_type, option_code)
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
        conn.execute(DDL_API_ERROR)
        conn.execute(DDL_MARKET_ANALYSIS)
        conn.execute(DDL_BETTING_TICKET)
        conn.execute(DDL_BETTING_TICKET_SELECTION)
        _ensure_match_result_columns(conn)
        _ensure_raw_snapshot_version_column(conn)
        _ensure_betting_selection_columns(conn)
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
    """Save raw API response. Returns True if inserted, False if duplicate.

    Also tracks *response_version*: increments per (source_name, match_id)
    so you can see how many distinct snapshots have been captured.
    """
    raw_str = json.dumps(raw_json, ensure_ascii=False, separators=(",", ":"))
    content_hash = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Check for duplicate content hash first
    existing = conn.execute(
        "SELECT id FROM sporttery_raw_snapshot WHERE content_hash = ?",
        (content_hash,),
    ).fetchone()
    if existing:
        return False

    # Compute next version for this (source_name, match_id)
    row = conn.execute(
        """
        SELECT COALESCE(MAX(response_version), 0) FROM sporttery_raw_snapshot
        WHERE source_name = ? AND (match_id = ? OR (match_id IS NULL AND ? IS NULL))
        """,
        (source_name, match_id, match_id),
    ).fetchone()
    version = (row[0] or 0) + 1

    cur = conn.execute(
        """
        INSERT INTO sporttery_raw_snapshot
            (source_name, source_url, request_params, match_id,
             snapshot_time, raw_content, content_hash, response_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_name, source_url,
            json.dumps(request_params, ensure_ascii=False) if request_params else None,
            match_id, now, raw_str, content_hash, version,
        ),
    )
    conn.commit()
    return cur.rowcount > 0


def save_api_error(
    conn: Connection,
    endpoint: str,
    error_message: str,
    *,
    match_id: str | None = None,
    request_params: dict | None = None,
    http_status: int | None = None,
    retry_count: int = 0,
) -> None:
    """Persist an API error for later analysis."""
    conn.execute(
        """
        INSERT INTO sporttery_api_error
            (endpoint, request_params, match_id, http_status,
             error_message, retry_count)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            endpoint,
            json.dumps(request_params, ensure_ascii=False) if request_params else None,
            match_id, http_status, error_message, retry_count,
        ),
    )
    conn.commit()


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
    """Bulk insert SP snapshot records with content-hash dedup.

    If a record's (match_id, play_type, option_code, sp_value, goal_line,
    is_single) combination already exists for the same snapshot_time, the
    row is skipped instead of replaced.
    """
    if not records:
        return 0

    _ensure_sp_snapshot_hash_column(conn)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inserted = 0
    for r in records:
        st = r.get("snapshot_time", now)
        h = _sp_content_hash(r["match_id"], r["play_type"], r["option_code"],
                             r["sp_value"], r.get("goal_line"), r.get("is_single", 0))
        # Skip if same content already stored for this snapshot_time
        existing = conn.execute(
            "SELECT id FROM sporttery_sp_snapshot WHERE match_id=? AND snapshot_time=? "
            "AND play_type=? AND option_code=? AND content_hash=?",
            (r["match_id"], st, r["play_type"], r["option_code"], h),
        ).fetchone()
        if existing:
            continue

        inserted += 1
        conn.execute(
            """
            INSERT OR REPLACE INTO sporttery_sp_snapshot
                (match_id, snapshot_time, play_type, option_code, option_name,
                 sp_value, goal_line, is_single,
                 implied_prob_raw, implied_prob_norm, prob_sum, content_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                r["match_id"], st, r["play_type"], r["option_code"],
                r.get("option_name"), r["sp_value"], r.get("goal_line"),
                r.get("is_single", 0), r.get("implied_prob_raw"),
                r.get("implied_prob_norm"), r.get("prob_sum"), h,
            ),
        )
    conn.commit()
    return inserted


def _sp_content_hash(
    match_id: str,
    play_type: str,
    option_code: str,
    sp_value: float,
    goal_line: str | None,
    is_single: int,
) -> str:
    """Deterministic hash of SP-critical fields."""
    raw = f"{match_id}|{play_type}|{option_code}|{sp_value}|{goal_line}|{is_single}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


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


def fetch_all_sp_history(
    conn: Connection,
    match_ids: list[str] | tuple[str, ...],
) -> list[dict]:
    """Fetch SP history rows for all supported play types at once."""
    if not match_ids:
        return []

    ids = [str(match_id) for match_id in match_ids]
    placeholders = ", ".join(["?"] * len(ids))
    cur = conn.execute(
        f"""
        SELECT *
        FROM sporttery_sp_snapshot
        WHERE match_id IN ({placeholders})
        ORDER BY match_id, play_type, option_code, snapshot_time
        """,
        tuple(ids),
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


def fetch_match(conn: Connection, match_id: str) -> dict | None:
    """Fetch one match by match_id."""
    cur = conn.execute("SELECT * FROM sporttery_match WHERE match_id = ?", (str(match_id),))
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def fetch_matches_for_analysis(conn: Connection, match_date: str | None = None) -> list[dict]:
    """Fetch matches that have SP history, optionally filtered by local match date."""
    sql = """
        SELECT DISTINCT m.*
        FROM sporttery_match m
        JOIN sporttery_sp_snapshot s ON s.match_id = m.match_id
    """
    params: tuple[str, ...] = ()
    if match_date:
        sql += "\n        WHERE date(m.match_time) = ?"
        params = (match_date,)
    sql += "\n        ORDER BY m.match_time"
    cur = conn.execute(sql, params)
    return _fetch_dicts(cur)


def save_market_analysis(conn: Connection, analysis: dict) -> None:
    """Save one market structure analysis snapshot."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        INSERT OR REPLACE INTO sporttery_market_analysis
            (match_id, analysis_time, window, had_direction, hhad_direction,
             ttg_direction, consistency_level, main_market_expression,
             research_priority, risk_flags_json, suggested_focus_json,
             avoid_focus_json, raw_analysis_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(analysis["match_id"]),
            analysis.get("analysis_time") or now,
            analysis["window"],
            analysis.get("had_direction"),
            analysis.get("hhad_direction"),
            analysis.get("ttg_direction"),
            analysis.get("consistency_level"),
            analysis.get("main_market_expression"),
            analysis.get("research_priority"),
            json.dumps(analysis.get("risk_flags", []), ensure_ascii=False),
            json.dumps(analysis.get("suggested_focus", []), ensure_ascii=False),
            json.dumps(analysis.get("avoid_focus", []), ensure_ascii=False),
            json.dumps(analysis, ensure_ascii=False),
        ),
    )
    conn.commit()


def save_betting_ticket(conn: Connection, ticket: dict) -> int:
    """Save one manual betting ticket and its selections.

    This is a financial ledger for manual decisions, not a Sporttery raw-data
    table. Keep original SP snapshots in sporttery_sp_snapshot.
    """
    selections = ticket.get("selections") or []
    if not selections:
        raise ValueError("ticket selections are required")

    placed_at = ticket.get("placed_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        """
        INSERT INTO betting_ticket
            (bet_group, ticket_label, pass_type, stake_amount, unit_stake,
             multiplier, ticket_status, expected_min_payout, expected_max_payout,
             actual_payout, profit_loss, placed_at, settled_at, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ticket.get("bet_group"),
            ticket["ticket_label"],
            ticket["pass_type"],
            ticket["stake_amount"],
            ticket.get("unit_stake", 2),
            ticket.get("multiplier", 1),
            ticket.get("ticket_status", "pending"),
            ticket.get("expected_min_payout"),
            ticket.get("expected_max_payout"),
            ticket.get("actual_payout"),
            ticket.get("profit_loss"),
            placed_at,
            ticket.get("settled_at"),
            ticket.get("notes"),
        ),
    )
    ticket_id = int(cur.lastrowid)

    for index, selection in enumerate(selections, start=1):
        sp_snapshot_id = selection.get("sp_snapshot_id")
        if sp_snapshot_id is None:
            sp_snapshot_id = find_sp_snapshot_id(conn, selection)
        conn.execute(
            """
            INSERT INTO betting_ticket_selection
                (ticket_id, leg_index, match_id, match_num, play_type,
                 option_code, option_name, goal_line, selected_sp,
                 sp_snapshot_id, sp_snapshot_time, result_status, actual_result)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticket_id,
                selection.get("leg_index", index),
                str(selection["match_id"]),
                selection.get("match_num"),
                selection["play_type"],
                selection["option_code"],
                selection.get("option_name"),
                selection.get("goal_line"),
                selection["selected_sp"],
                sp_snapshot_id,
                selection.get("sp_snapshot_time"),
                selection.get("result_status", "pending"),
                selection.get("actual_result"),
            ),
        )
    conn.commit()
    return ticket_id


def find_sp_snapshot_id(conn: Connection, selection: dict) -> int | None:
    """Find the stored SP snapshot row matching a betting selection."""
    params = [
        str(selection["match_id"]),
        selection["play_type"],
        selection["option_code"],
    ]
    sql = """
        SELECT id
        FROM sporttery_sp_snapshot
        WHERE match_id = ?
          AND play_type = ?
          AND option_code = ?
    """
    if selection.get("sp_snapshot_time"):
        sql += " AND snapshot_time = ?"
        params.append(selection["sp_snapshot_time"])
    if selection.get("goal_line") is not None:
        sql += " AND goal_line = ?"
        params.append(selection["goal_line"])
    sql += " ORDER BY snapshot_time DESC, id DESC LIMIT 1"
    row = conn.execute(sql, tuple(params)).fetchone()
    return int(row["id"]) if row else None


def fetch_betting_tickets(conn: Connection, bet_group: str | None = None) -> list[dict]:
    """Fetch saved manual betting tickets, optionally for one group."""
    sql = "SELECT * FROM betting_ticket"
    params: tuple[str, ...] = ()
    if bet_group is not None:
        sql += " WHERE bet_group = ?"
        params = (bet_group,)
    sql += " ORDER BY placed_at, id"
    return _fetch_dicts(conn.execute(sql, params))


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


def _ensure_raw_snapshot_version_column(conn: Connection) -> None:
    """Add response_version column to sporttery_raw_snapshot if missing."""
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(sporttery_raw_snapshot)").fetchall()
    }
    if "response_version" not in existing:
        conn.execute("ALTER TABLE sporttery_raw_snapshot ADD COLUMN response_version INTEGER DEFAULT 1")


def _ensure_betting_selection_columns(conn: Connection) -> None:
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(betting_ticket_selection)").fetchall()
    }
    if "sp_snapshot_id" not in existing:
        conn.execute("ALTER TABLE betting_ticket_selection ADD COLUMN sp_snapshot_id INTEGER NULL")


_sp_hash_column_checked = False


def _ensure_sp_snapshot_hash_column(conn: Connection) -> None:
    """Add content_hash column to sporttery_sp_snapshot if missing (once)."""
    global _sp_hash_column_checked
    if _sp_hash_column_checked:
        return
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(sporttery_sp_snapshot)").fetchall()
    }
    if "content_hash" not in existing:
        conn.execute("ALTER TABLE sporttery_sp_snapshot ADD COLUMN content_hash TEXT NULL")
    _sp_hash_column_checked = True
