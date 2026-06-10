"""Database operations for Sporttery data. Supports SQLite (dev) and MySQL (prod)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from src.config import DB_CONFIG

_BACKEND = "sqlite"  # "sqlite" or "mysql"
_SQLITE_PATH = Path(__file__).resolve().parent.parent / "data" / "sporttery.db"


# ── DDL ──────────────────────────────────────────────────────────────────────

def _ddl_raw_snapshot(backend: str) -> str:
    auto = "INTEGER" if backend == "sqlite" else "BIGINT AUTO_INCREMENT"
    return f"""
    CREATE TABLE IF NOT EXISTS sporttery_raw_snapshot (
        id {auto} PRIMARY KEY,
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
    """ if backend == "sqlite" else """
    CREATE TABLE IF NOT EXISTS sporttery_raw_snapshot (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        source_name VARCHAR(100) NOT NULL,
        source_url TEXT NOT NULL,
        request_params JSON NULL,
        match_id VARCHAR(64) NULL,
        snapshot_time DATETIME NOT NULL,
        raw_content LONGTEXT NOT NULL,
        content_hash CHAR(64) NOT NULL,
        http_status INT NULL,
        parse_status TINYINT DEFAULT 0,
        error_message TEXT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uk_hash (content_hash),
        KEY idx_match_time (match_id, snapshot_time),
        KEY idx_source_time (source_name, snapshot_time)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """


def _ddl_match(backend: str) -> str:
    auto = "INTEGER" if backend == "sqlite" else "BIGINT AUTO_INCREMENT"
    return f"""
    CREATE TABLE IF NOT EXISTS sporttery_match (
        id {auto} PRIMARY KEY,
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
        home_score_90 INTEGER NULL,
        away_score_90 INTEGER NULL,
        result_90 TEXT NULL,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    );
    """ if backend == "sqlite" else """
    CREATE TABLE IF NOT EXISTS sporttery_match (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        match_id VARCHAR(64) NOT NULL,
        match_num VARCHAR(64) NULL,
        league_id VARCHAR(64) NULL,
        league_name VARCHAR(100) NULL,
        home_team_id VARCHAR(64) NULL,
        away_team_id VARCHAR(64) NULL,
        home_team_name VARCHAR(100) NULL,
        away_team_name VARCHAR(100) NULL,
        match_time DATETIME NULL,
        match_status VARCHAR(32) NULL,
        home_score_90 INT NULL,
        away_score_90 INT NULL,
        result_90 ENUM('H','D','A') NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_match_id (match_id),
        KEY idx_match_time (match_time),
        KEY idx_league (league_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """


def _ddl_signal(backend: str) -> str:
    auto = "INTEGER" if backend == "sqlite" else "BIGINT AUTO_INCREMENT"
    return f"""
    CREATE TABLE IF NOT EXISTS sporttery_signal (
        id {auto} PRIMARY KEY,
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
    """ if backend == "sqlite" else """
    CREATE TABLE IF NOT EXISTS sporttery_signal (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        match_id VARCHAR(64) NOT NULL,
        snapshot_time DATETIME NOT NULL,
        signal_type VARCHAR(64) NOT NULL,
        signal_level VARCHAR(16) NOT NULL,
        play_type VARCHAR(32) NULL,
        option_code VARCHAR(32) NULL,
        description TEXT NOT NULL,
        evidence_json JSON NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        KEY idx_match_time (match_id, snapshot_time),
        KEY idx_signal_type (signal_type)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """


def _ddl_sp_snapshot(backend: str) -> str:
    auto = "INTEGER" if backend == "sqlite" else "BIGINT AUTO_INCREMENT"
    return f"""
    CREATE TABLE IF NOT EXISTS sporttery_sp_snapshot (
        id {auto} PRIMARY KEY,
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
    """ if backend == "sqlite" else """
    CREATE TABLE IF NOT EXISTS sporttery_sp_snapshot (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        match_id VARCHAR(64) NOT NULL,
        snapshot_time DATETIME NOT NULL,
        play_type VARCHAR(32) NOT NULL COMMENT 'had/hhad/ttg/crs/hafu',
        option_code VARCHAR(32) NOT NULL COMMENT 'H/D/A or 0-7 etc.',
        option_name VARCHAR(64) NULL,
        sp_value DECIMAL(10,4) NOT NULL,
        goal_line VARCHAR(16) NULL,
        is_single TINYINT DEFAULT 0,
        implied_prob_raw DECIMAL(12,8) NULL,
        implied_prob_norm DECIMAL(12,8) NULL,
        prob_sum DECIMAL(12,8) NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uk_snapshot_option (match_id, snapshot_time, play_type, option_code),
        KEY idx_match_play_time (match_id, play_type, snapshot_time),
        KEY idx_play_option (play_type, option_code)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """


# ── Placeholder ──────────────────────────────────────────────────────────────

def _ph(sql: str, backend: str) -> str:
    """Convert %s placeholders to ? for SQLite."""
    if backend == "sqlite":
        return sql.replace("%s", "?").replace("%(", "?")
    return sql


# ── Connection ───────────────────────────────────────────────────────────────

class Connection:
    """Unified connection wrapper for SQLite and MySQL."""

    def __init__(self, backend: str):
        self.backend = backend
        if backend == "sqlite":
            _SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(_SQLITE_PATH))
            self._conn.row_factory = sqlite3.Row
        else:
            import pymysql
            self._conn = pymysql.connect(**DB_CONFIG)

    def cursor(self):
        return self._conn.cursor()

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    def execute(self, sql: str, params=None):
        """Execute with auto placeholder conversion."""
        sql = _ph(sql, self.backend)
        cur = self._conn.cursor()
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        return cur

    def executemany(self, sql: str, params_list):
        """Execute many with auto placeholder conversion."""
        sql = _ph(sql, self.backend)
        cur = self._conn.cursor()
        cur.executemany(sql, params_list)
        return cur


def get_connection(backend: str | None = None) -> Connection:
    """Return a new database connection."""
    return Connection(backend or _BACKEND)


def set_backend(backend: str):
    """Switch backend: 'sqlite' or 'mysql'."""
    global _BACKEND
    _BACKEND = backend


def ensure_tables(conn: Connection | None = None) -> None:
    """Create tables if they don't exist."""
    close = False
    if conn is None:
        conn = get_connection()
        close = True
    try:
        b = conn.backend
        conn.execute(_ddl_raw_snapshot(b))
        conn.execute(_ddl_match(b))
        conn.execute(_ddl_sp_snapshot(b))
        conn.execute(_ddl_signal(b))
        conn.commit()
    finally:
        if close:
            conn.close()


# ── Raw snapshot ─────────────────────────────────────────────────────────────

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

    try:
        if conn.backend == "sqlite":
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
        else:
            cur = conn.execute(
                """
                INSERT IGNORE INTO sporttery_raw_snapshot
                    (source_name, source_url, request_params, match_id,
                     snapshot_time, raw_content, content_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    source_name, source_url,
                    json.dumps(request_params, ensure_ascii=False) if request_params else None,
                    match_id, now, raw_str, content_hash,
                ),
            )
        conn.commit()
        return cur.rowcount > 0
    except Exception:
        return False


# ── Match ────────────────────────────────────────────────────────────────────

def save_match(conn: Connection, match: dict) -> None:
    """UPSERT a match record."""
    # Normalize match_time to string for both backends
    m = dict(match)
    if m.get("match_time") and hasattr(m["match_time"], "strftime"):
        m["match_time"] = m["match_time"].strftime("%Y-%m-%d %H:%M:%S")

    if conn.backend == "sqlite":
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
    else:
        conn.execute(
            """
            INSERT INTO sporttery_match
                (match_id, match_num, league_id, league_name,
                 home_team_id, away_team_id, home_team_name, away_team_name,
                 match_time, match_status)
            VALUES (%(match_id)s, %(match_num)s, %(league_id)s, %(league_name)s,
                    %(home_team_id)s, %(away_team_id)s, %(home_team_name)s, %(away_team_name)s,
                    %(match_time)s, %(match_status)s)
            ON DUPLICATE KEY UPDATE
                match_num = VALUES(match_num), league_id = VALUES(league_id),
                league_name = VALUES(league_name), home_team_id = VALUES(home_team_id),
                away_team_id = VALUES(away_team_id), home_team_name = VALUES(home_team_name),
                away_team_name = VALUES(away_team_name), match_time = VALUES(match_time),
                match_status = VALUES(match_status)
            """,
            m,
        )
    conn.commit()


def save_matches(conn: Connection, matches: list[dict]) -> int:
    """UPSERT multiple match records. Returns count."""
    for m in matches:
        save_match(conn, m)
    return len(matches)


# ── SP snapshot ──────────────────────────────────────────────────────────────

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

    if conn.backend == "sqlite":
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
    else:
        conn.executemany(
            """
            INSERT INTO sporttery_sp_snapshot
                (match_id, snapshot_time, play_type, option_code, option_name,
                 sp_value, goal_line, is_single,
                 implied_prob_raw, implied_prob_norm, prob_sum)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                sp_value = VALUES(sp_value), goal_line = VALUES(goal_line),
                is_single = VALUES(is_single), implied_prob_raw = VALUES(implied_prob_raw),
                implied_prob_norm = VALUES(implied_prob_norm), prob_sum = VALUES(prob_sum)
            """,
            rows,
        )
    conn.commit()
    return len(rows)
