"""竞彩数据的数据库操作。

MySQL是运行时后端。SQLite支持仅保留用于独立的单元测试和旧版迁移工具。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from decimal import Decimal
from datetime import datetime
from pathlib import Path
from typing import Iterable


_SQLITE_PATH = Path(__file__).resolve().parent.parent / "data" / "sporttery.db"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_LOADED = False
SOURCE_TYPES = frozenset({
    "AI_RECOMMENDATION",
    "BACKTEST_SIMULATED",
    "SYSTEM",
    "UNKNOWN",
    "USER_ACTUAL",
    "USER_MODIFIED",
    "USER_ODDS_ONLY",
})


def _db_backend() -> str:
    _load_env_file()
    return os.environ.get("SPORTTERY_DB_BACKEND", "mysql").strip().lower() or "mysql"



def _load_env_file() -> None:
    """从项目.env文件加载简单的KEY=VALUE键值对，不覆盖已有的环境变量。"""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    env_path = _PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


# 数据定义语句

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
    source_type TEXT NOT NULL DEFAULT 'UNKNOWN',
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


DDL_DAILY_RECOMMENDATION = """
CREATE TABLE IF NOT EXISTS daily_recommendation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recommendation_date TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    match_id TEXT NOT NULL,
    match_num TEXT NULL,
    league_name TEXT NULL,
    home_team_name TEXT NULL,
    away_team_name TEXT NULL,
    match_time TEXT NULL,
    recommendation_level TEXT NOT NULL,
    main_play_type TEXT NULL,
    main_option_code TEXT NULL,
    main_option_name TEXT NULL,
    main_sp REAL NULL,
    score_option_code TEXT NULL,
    score_option_name TEXT NULL,
    score_sp REAL NULL,
    aux_json TEXT NULL,
    gates_json TEXT NULL,
    model_version TEXT NOT NULL DEFAULT 'sp_structure_v1',
    sp_snapshot_time TEXT NULL,
    notes TEXT NULL,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(recommendation_date, generated_at, match_id)
);
"""


MYSQL_DDL_RAW_SNAPSHOT = """
CREATE TABLE IF NOT EXISTS sporttery_raw_snapshot (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    source_name VARCHAR(64) NOT NULL,
    source_url TEXT NOT NULL,
    request_params JSON NULL,
    match_id VARCHAR(32) NULL,
    snapshot_time DATETIME NOT NULL,
    raw_content LONGTEXT NOT NULL,
    content_hash CHAR(64) NOT NULL,
    http_status INT NULL,
    parse_status INT DEFAULT 0,
    error_message TEXT NULL,
    response_version INT DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_raw_content_hash (content_hash),
    KEY idx_raw_source_match_time (source_name, match_id, snapshot_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


MYSQL_DDL_MATCH = """
CREATE TABLE IF NOT EXISTS sporttery_match (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    sport_code VARCHAR(16) NOT NULL DEFAULT 'football',
    match_id VARCHAR(32) NOT NULL,
    match_num VARCHAR(32) NULL,
    league_id VARCHAR(32) NULL,
    league_name VARCHAR(128) NULL,
    home_team_id VARCHAR(32) NULL,
    away_team_id VARCHAR(32) NULL,
    home_team_name VARCHAR(128) NULL,
    away_team_name VARCHAR(128) NULL,
    match_time DATETIME NULL,
    match_status VARCHAR(16) NULL,
    match_status_name VARCHAR(64) NULL,
    home_score_90 INT NULL,
    away_score_90 INT NULL,
    result_90 VARCHAR(4) NULL,
    half_score VARCHAR(16) NULL,
    full_score_90 VARCHAR(16) NULL,
    result_source VARCHAR(64) NULL,
    result_updated_at DATETIME NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_match_id (match_id),
    KEY idx_match_league_time (league_name, match_time),
    KEY idx_match_status_time (match_status, match_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


MYSQL_DDL_SP_SNAPSHOT = """
CREATE TABLE IF NOT EXISTS sporttery_sp_snapshot (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    sport_code VARCHAR(16) NOT NULL DEFAULT 'football',
    match_id VARCHAR(32) NOT NULL,
    snapshot_time DATETIME NOT NULL,
    play_type VARCHAR(16) NOT NULL,
    option_code VARCHAR(32) NOT NULL,
    option_name VARCHAR(128) NULL,
    sp_value DECIMAL(10, 4) NOT NULL,
    goal_line VARCHAR(16) NULL,
    is_single TINYINT DEFAULT 0,
    implied_prob_raw DECIMAL(18, 10) NULL,
    implied_prob_norm DECIMAL(18, 10) NULL,
    prob_sum DECIMAL(18, 10) NULL,
    content_hash CHAR(16) NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_sp_snapshot (match_id, snapshot_time, play_type, option_code),
    KEY idx_sp_match_play_time (match_id, play_type, snapshot_time),
    KEY idx_sp_play_time (play_type, snapshot_time),
    KEY idx_sp_content (match_id, snapshot_time, play_type, option_code, content_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


MYSQL_DDL_SIGNAL = """
CREATE TABLE IF NOT EXISTS sporttery_signal (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    match_id VARCHAR(32) NOT NULL,
    snapshot_time DATETIME NOT NULL,
    signal_type VARCHAR(64) NOT NULL,
    signal_level VARCHAR(32) NOT NULL,
    play_type VARCHAR(16) NULL,
    option_code VARCHAR(32) NULL,
    description TEXT NOT NULL,
    evidence_json JSON NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    KEY idx_signal_match_time (match_id, snapshot_time),
    KEY idx_signal_type_level (signal_type, signal_level)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


MYSQL_DDL_API_ERROR = """
CREATE TABLE IF NOT EXISTS sporttery_api_error (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    endpoint VARCHAR(64) NOT NULL,
    request_params JSON NULL,
    match_id VARCHAR(32) NULL,
    http_status INT NULL,
    error_message TEXT NOT NULL,
    retry_count INT DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    KEY idx_api_error_endpoint_time (endpoint, created_at),
    KEY idx_api_error_match (match_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


MYSQL_DDL_MARKET_ANALYSIS = """
CREATE TABLE IF NOT EXISTS sporttery_market_analysis (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    match_id VARCHAR(32) NOT NULL,
    analysis_time DATETIME NOT NULL,
    window VARCHAR(32) NOT NULL,
    had_direction VARCHAR(32) NULL,
    hhad_direction VARCHAR(32) NULL,
    ttg_direction VARCHAR(32) NULL,
    consistency_level VARCHAR(32) NULL,
    main_market_expression VARCHAR(128) NULL,
    research_priority VARCHAR(8) NULL,
    risk_flags_json JSON NULL,
    suggested_focus_json JSON NULL,
    avoid_focus_json JSON NULL,
    raw_analysis_json JSON NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_market_analysis (match_id, analysis_time, window),
    KEY idx_market_match_window_time (match_id, window, analysis_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


MYSQL_DDL_DAILY_RECOMMENDATION = """
CREATE TABLE IF NOT EXISTS daily_recommendation (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    recommendation_date DATE NOT NULL,
    generated_at DATETIME NOT NULL,
    match_id VARCHAR(32) NOT NULL,
    match_num VARCHAR(32) NULL,
    league_name VARCHAR(128) NULL,
    home_team_name VARCHAR(128) NULL,
    away_team_name VARCHAR(128) NULL,
    match_time DATETIME NULL,
    recommendation_level VARCHAR(16) NOT NULL,
    main_play_type VARCHAR(16) NULL,
    main_option_code VARCHAR(32) NULL,
    main_option_name VARCHAR(128) NULL,
    main_sp DECIMAL(10, 4) NULL,
    score_option_code VARCHAR(32) NULL,
    score_option_name VARCHAR(128) NULL,
    score_sp DECIMAL(10, 4) NULL,
    aux_json JSON NULL,
    gates_json JSON NULL,
    model_version VARCHAR(64) NOT NULL DEFAULT 'sp_structure_v1',
    sp_snapshot_time DATETIME NULL,
    notes TEXT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_daily_recommendation (recommendation_date, generated_at, match_id),
    KEY idx_daily_match (match_id),
    KEY idx_daily_level_date (recommendation_level, recommendation_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


MYSQL_DDL_BETTING_TICKET = """
CREATE TABLE IF NOT EXISTS betting_ticket (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    bet_group VARCHAR(128) NULL,
    source_type VARCHAR(32) NOT NULL DEFAULT 'UNKNOWN',
    ticket_label VARCHAR(255) NOT NULL,
    pass_type VARCHAR(32) NOT NULL,
    stake_amount DECIMAL(12, 2) NOT NULL,
    unit_stake DECIMAL(12, 2) DEFAULT 2,
    multiplier INT DEFAULT 1,
    ticket_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    expected_min_payout DECIMAL(12, 2) NULL,
    expected_max_payout DECIMAL(12, 2) NULL,
    actual_payout DECIMAL(12, 2) NULL,
    profit_loss DECIMAL(12, 2) NULL,
    placed_at DATETIME NOT NULL,
    settled_at DATETIME NULL,
    notes TEXT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_ticket_source_status_time (source_type, ticket_status, placed_at),
    KEY idx_ticket_group (bet_group)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


MYSQL_DDL_BETTING_TICKET_SELECTION = """
CREATE TABLE IF NOT EXISTS betting_ticket_selection (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    ticket_id BIGINT NOT NULL,
    leg_index INT NOT NULL,
    match_id VARCHAR(32) NOT NULL,
    match_num VARCHAR(32) NULL,
    play_type VARCHAR(16) NOT NULL,
    option_code VARCHAR(32) NOT NULL,
    option_name VARCHAR(128) NULL,
    goal_line VARCHAR(16) NULL,
    selected_sp DECIMAL(10, 4) NOT NULL,
    sp_snapshot_id BIGINT NULL,
    sp_snapshot_time DATETIME NULL,
    result_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    actual_result VARCHAR(32) NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_ticket_selection (ticket_id, leg_index, match_id, play_type, option_code),
    KEY idx_selection_match_play (match_id, play_type),
    KEY idx_selection_snapshot (sp_snapshot_id),
    CONSTRAINT fk_ticket_selection_ticket FOREIGN KEY(ticket_id) REFERENCES betting_ticket(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


MYSQL_DDLS = (
    MYSQL_DDL_RAW_SNAPSHOT,
    MYSQL_DDL_MATCH,
    MYSQL_DDL_SP_SNAPSHOT,
    MYSQL_DDL_SIGNAL,
    MYSQL_DDL_API_ERROR,
    MYSQL_DDL_MARKET_ANALYSIS,
    MYSQL_DDL_DAILY_RECOMMENDATION,
    MYSQL_DDL_BETTING_TICKET,
    MYSQL_DDL_BETTING_TICKET_SELECTION,
)


SQLITE_DDLS = (
    DDL_RAW_SNAPSHOT,
    DDL_MATCH,
    DDL_SP_SNAPSHOT,
    DDL_SIGNAL,
    DDL_API_ERROR,
    DDL_MARKET_ANALYSIS,
    DDL_DAILY_RECOMMENDATION,
    DDL_BETTING_TICKET,
    DDL_BETTING_TICKET_SELECTION,
)


# 数据库连接

class Row(dict):
    """字典行，同时支持像sqlite3.Row那样的位置索引。"""

    def __init__(self, values: Iterable, columns: list[str]):
        converted = tuple(_db_value(value) for value in values)
        super().__init__(zip(columns, converted))
        self._values = converted

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


class CursorAdapter:
    """将sqlite3和PyMySQL游标规范化，以适配现有项目代码。"""

    def __init__(self, cursor):
        self._cursor = cursor

    @property
    def description(self):
        return self._cursor.description

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    def fetchone(self):
        row = self._cursor.fetchone()
        return self._wrap(row)

    def fetchall(self):
        return [self._wrap(row) for row in self._cursor.fetchall()]

    def _wrap(self, row):
        if row is None:
            return None
        if isinstance(row, sqlite3.Row):
            return row
        if isinstance(row, dict):
            values = list(row.values())
            columns = list(row.keys())
            return Row(values, columns)
        columns = [d[0] for d in self._cursor.description]
        return Row(row, columns)


class Connection:
    """项目使用的小型数据库连接封装器。"""

    def __init__(self):
        self.backend = _db_backend()
        if self.backend == "mysql":
            import pymysql

            self._conn = pymysql.connect(
                host=os.environ["SPORTTERY_MYSQL_HOST"],
                port=int(os.environ.get("SPORTTERY_MYSQL_PORT", "3306")),
                user=os.environ["SPORTTERY_MYSQL_USER"],
                password=os.environ["SPORTTERY_MYSQL_PASSWORD"],
                database=os.environ["SPORTTERY_MYSQL_DATABASE"],
                charset=os.environ.get("SPORTTERY_MYSQL_CHARSET", "utf8mb4"),
                autocommit=False,
                connect_timeout=int(os.environ.get("SPORTTERY_MYSQL_CONNECT_TIMEOUT", "10")),
                read_timeout=int(os.environ.get("SPORTTERY_MYSQL_READ_TIMEOUT", "30")),
                write_timeout=int(os.environ.get("SPORTTERY_MYSQL_WRITE_TIMEOUT", "30")),
            )
        elif self.backend == "sqlite":
            _SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(_SQLITE_PATH))
            self._conn.row_factory = sqlite3.Row
        else:
            raise ValueError(f"unsupported SPORTTERY_DB_BACKEND={self.backend!r}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def cursor(self):
        return CursorAdapter(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    def execute(self, sql: str, params=None):
        cur = self._conn.cursor()
        if self.backend == "mysql":
            sql = _mysqlize_sql(sql)
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        return CursorAdapter(cur)

    def executemany(self, sql: str, params_list):
        cur = self._conn.cursor()
        if self.backend == "mysql":
            sql = _mysqlize_sql(sql)
        cur.executemany(sql, params_list)
        return CursorAdapter(cur)


def _mysqlize_sql(sql: str) -> str:
    """将项目的SQLite风格占位符转换为PyMySQL兼容格式。"""
    return sql.replace("?", "%s")


def _db_value(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def get_connection() -> Connection:
    """返回一个新的已配置数据库连接。"""
    return Connection()


def ensure_tables(conn: Connection | None = None) -> None:
    """如果表不存在则创建。"""
    close = False
    if conn is None:
        conn = get_connection()
        close = True
    try:
        for ddl in MYSQL_DDLS if conn.backend == "mysql" else SQLITE_DDLS:
            conn.execute(ddl)
        if conn.backend == "sqlite":
            _ensure_match_result_columns(conn)
            _ensure_raw_snapshot_version_column(conn)
            _ensure_betting_ticket_columns(conn)
            _ensure_betting_selection_columns(conn)
            _ensure_daily_recommendation_table(conn)
            conn.commit()
        else:
            conn.commit()
    finally:
        if close:
            conn.close()


# 原始快照

def save_raw_snapshot(
    conn: Connection,
    source_name: str,
    source_url: str,
    raw_json: dict,
    match_id: str | None = None,
    request_params: dict | None = None,
) -> bool:
    """保存原始API响应。插入成功返回True，重复返回False。

    同时跟踪 *response_version*：按(source_name, match_id)递增，
    以便查看已捕获了多少不同的快照。
    """
    raw_str = json.dumps(raw_json, ensure_ascii=False, separators=(",", ":"))
    content_hash = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 首先检查重复的内容哈希
    existing = conn.execute(
        "SELECT id FROM sporttery_raw_snapshot WHERE content_hash = ?",
        (content_hash,),
    ).fetchone()
    if existing:
        return False

    # 计算此(source_name, match_id)的下一个版本号
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
    """保存API错误以供后续分析。"""
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


# 比赛

def save_match(conn: Connection, match: dict) -> None:
    """UPSERT一条比赛记录（不提交事务——调用方负责提交）。"""
    m = dict(match)
    if m.get("match_time") and hasattr(m["match_time"], "strftime"):
        m["match_time"] = m["match_time"].strftime("%Y-%m-%d %H:%M:%S")

    params = (
        m["match_id"], m.get("match_num"), m.get("league_id"),
        m.get("league_name"), m.get("home_team_id"), m.get("away_team_id"),
        m.get("home_team_name"), m.get("away_team_name"),
        m.get("match_time"), m.get("match_status"),
    )
    if conn.backend == "mysql":
        conn.execute(
            """
            INSERT INTO sporttery_match
                (match_id, match_num, league_id, league_name,
                 home_team_id, away_team_id, home_team_name, away_team_name,
                 match_time, match_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON DUPLICATE KEY UPDATE
                match_num=VALUES(match_num), league_id=VALUES(league_id),
                league_name=VALUES(league_name), home_team_id=VALUES(home_team_id),
                away_team_id=VALUES(away_team_id), home_team_name=VALUES(home_team_name),
                away_team_name=VALUES(away_team_name), match_time=VALUES(match_time),
                match_status=VALUES(match_status)
            """,
            params,
        )
    else:
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
            params,
        )


def save_matches(conn: Connection, matches: list[dict]) -> int:
    """UPSERT多条比赛记录并统一提交。返回记录数。"""
    for m in matches:
        save_match(conn, m)
    conn.commit()
    return len(matches)


def save_match_result(conn: Connection, result: dict) -> None:
    """UPSERT一条比赛结果（不提交事务——调用方负责提交）。"""
    r = dict(result)
    if r.get("match_time") and hasattr(r["match_time"], "strftime"):
        r["match_time"] = r["match_time"].strftime("%Y-%m-%d %H:%M:%S")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    params = (
        r["match_id"], r.get("match_num"), r.get("league_id"),
        r.get("league_name"), r.get("home_team_id"), r.get("away_team_id"),
        r.get("home_team_name"), r.get("away_team_name"),
        r.get("match_time"), r.get("match_status"), r.get("match_status_name"),
        r.get("home_score_90"), r.get("away_score_90"), r.get("result_90"),
        r.get("half_score"), r.get("full_score_90"),
        r.get("result_source", "sporttery_zqsj"), now,
    )
    if conn.backend == "mysql":
        conn.execute(
            """
            INSERT INTO sporttery_match
                (match_id, match_num, league_id, league_name,
                 home_team_id, away_team_id, home_team_name, away_team_name,
                 match_time, match_status, match_status_name,
                 home_score_90, away_score_90, result_90,
                 half_score, full_score_90, result_source, result_updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON DUPLICATE KEY UPDATE
                match_num=VALUES(match_num),
                league_id=VALUES(league_id),
                league_name=VALUES(league_name),
                home_team_id=VALUES(home_team_id),
                away_team_id=VALUES(away_team_id),
                home_team_name=VALUES(home_team_name),
                away_team_name=VALUES(away_team_name),
                match_time=VALUES(match_time),
                match_status=VALUES(match_status),
                match_status_name=VALUES(match_status_name),
                home_score_90=VALUES(home_score_90),
                away_score_90=VALUES(away_score_90),
                result_90=VALUES(result_90),
                half_score=VALUES(half_score),
                full_score_90=VALUES(full_score_90),
                result_source=VALUES(result_source),
                result_updated_at=VALUES(result_updated_at)
            """,
            params,
        )
    else:
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
            params,
        )


def save_match_results(conn: Connection, results: list[dict]) -> int:
    """UPSERT多条比赛结果并统一提交。返回记录数。"""
    for result in results:
        save_match_result(conn, result)
    conn.commit()
    return len(results)


# SP快照

def save_sp_snapshots(conn: Connection, records: list[dict]) -> int:
    """批量插入SP快照记录，使用内容哈希去重。

    如果某条记录的(match_id, play_type, option_code, sp_value, goal_line,
    is_single)组合在同一snapshot_time下已存在，则跳过该行而非替换。
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
        # 如果此snapshot_time已存储相同内容则跳过
        existing = conn.execute(
            "SELECT id FROM sporttery_sp_snapshot WHERE match_id=? AND snapshot_time=? "
            "AND play_type=? AND option_code=? AND content_hash=?",
            (r["match_id"], st, r["play_type"], r["option_code"], h),
        ).fetchone()
        if existing:
            continue

        inserted += 1
        params = (
            r["match_id"], st, r["play_type"], r["option_code"],
            r.get("option_name"), r["sp_value"], r.get("goal_line"),
            r.get("is_single", 0), r.get("implied_prob_raw"),
            r.get("implied_prob_norm"), r.get("prob_sum"), h,
        )
        if conn.backend == "mysql":
            conn.execute(
                """
                INSERT IGNORE INTO sporttery_sp_snapshot
                    (match_id, snapshot_time, play_type, option_code, option_name,
                     sp_value, goal_line, is_single,
                     implied_prob_raw, implied_prob_norm, prob_sum, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params,
            )
        else:
            conn.execute(
                """
                INSERT OR IGNORE INTO sporttery_sp_snapshot
                    (match_id, snapshot_time, play_type, option_code, option_name,
                     sp_value, goal_line, is_single,
                     implied_prob_raw, implied_prob_norm, prob_sum, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params,
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
    """SP关键字段的确定性哈希。"""
    raw = f"{match_id}|{play_type}|{option_code}|{sp_value}|{goal_line}|{is_single}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def fetch_sp_history(
    conn: Connection,
    match_ids: list[str] | tuple[str, ...],
    *,
    play_type: str = "had",
) -> list[dict]:
    """获取指定比赛和玩法类型的SP历史记录。"""
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
    """一次性获取所有支持玩法类型的SP历史记录。"""
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


def fetch_match(conn: Connection, match_id: str) -> dict | None:
    """根据match_id获取一条比赛记录。"""
    cur = conn.execute("SELECT * FROM sporttery_match WHERE match_id = ?", (str(match_id),))
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def fetch_matches_for_analysis(conn: Connection, match_date: str | None = None) -> list[dict]:
    """获取有SP历史的比赛，可选按本地比赛日期过滤。"""
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
    """保存一条市场结构分析快照。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    params = (
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
    )
    if conn.backend == "mysql":
        conn.execute(
            """
            INSERT INTO sporttery_market_analysis
                (match_id, analysis_time, window, had_direction, hhad_direction,
                 ttg_direction, consistency_level, main_market_expression,
                 research_priority, risk_flags_json, suggested_focus_json,
                 avoid_focus_json, raw_analysis_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON DUPLICATE KEY UPDATE
                had_direction=VALUES(had_direction),
                hhad_direction=VALUES(hhad_direction),
                ttg_direction=VALUES(ttg_direction),
                consistency_level=VALUES(consistency_level),
                main_market_expression=VALUES(main_market_expression),
                research_priority=VALUES(research_priority),
                risk_flags_json=VALUES(risk_flags_json),
                suggested_focus_json=VALUES(suggested_focus_json),
                avoid_focus_json=VALUES(avoid_focus_json),
                raw_analysis_json=VALUES(raw_analysis_json)
            """,
            params,
        )
    else:
        conn.execute(
            """
            INSERT OR REPLACE INTO sporttery_market_analysis
                (match_id, analysis_time, window, had_direction, hhad_direction,
                 ttg_direction, consistency_level, main_market_expression,
                 research_priority, risk_flags_json, suggested_focus_json,
                 avoid_focus_json, raw_analysis_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            params,
        )
    conn.commit()


def save_daily_recommendations(conn: Connection, recommendations: list[dict]) -> int:
    """保存赛前固定推荐记录，供后续审计/回测使用。"""
    if not recommendations:
        return 0
    inserted = 0
    for rec in recommendations:
        params = (
            rec["recommendation_date"],
            rec.get("generated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            str(rec["match_id"]),
            rec.get("match_num"),
            rec.get("league_name"),
            rec.get("home_team_name"),
            rec.get("away_team_name"),
            rec.get("match_time"),
            rec["recommendation_level"],
            rec.get("main_play_type"),
            rec.get("main_option_code"),
            rec.get("main_option_name"),
            rec.get("main_sp"),
            rec.get("score_option_code"),
            rec.get("score_option_name"),
            rec.get("score_sp"),
            json.dumps(rec.get("aux", rec.get("aux_json", {})), ensure_ascii=False),
            json.dumps(rec.get("gates", rec.get("gates_json", [])), ensure_ascii=False),
            rec.get("model_version", "sp_structure_v1"),
            rec.get("sp_snapshot_time"),
            rec.get("notes"),
        )
        if conn.backend == "mysql":
            cur = conn.execute(
                """
                INSERT INTO daily_recommendation
                    (recommendation_date, generated_at, match_id, match_num,
                     league_name, home_team_name, away_team_name, match_time,
                     recommendation_level, main_play_type, main_option_code,
                     main_option_name, main_sp, score_option_code, score_option_name,
                     score_sp, aux_json, gates_json, model_version,
                     sp_snapshot_time, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON DUPLICATE KEY UPDATE
                    match_num=VALUES(match_num),
                    league_name=VALUES(league_name),
                    home_team_name=VALUES(home_team_name),
                    away_team_name=VALUES(away_team_name),
                    match_time=VALUES(match_time),
                    recommendation_level=VALUES(recommendation_level),
                    main_play_type=VALUES(main_play_type),
                    main_option_code=VALUES(main_option_code),
                    main_option_name=VALUES(main_option_name),
                    main_sp=VALUES(main_sp),
                    score_option_code=VALUES(score_option_code),
                    score_option_name=VALUES(score_option_name),
                    score_sp=VALUES(score_sp),
                    aux_json=VALUES(aux_json),
                    gates_json=VALUES(gates_json),
                    model_version=VALUES(model_version),
                    sp_snapshot_time=VALUES(sp_snapshot_time),
                    notes=VALUES(notes)
                """,
                params,
            )
        else:
            cur = conn.execute(
                """
                INSERT OR REPLACE INTO daily_recommendation
                    (recommendation_date, generated_at, match_id, match_num,
                     league_name, home_team_name, away_team_name, match_time,
                     recommendation_level, main_play_type, main_option_code,
                     main_option_name, main_sp, score_option_code, score_option_name,
                     score_sp, aux_json, gates_json, model_version,
                     sp_snapshot_time, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params,
            )
        inserted += max(cur.rowcount, 0)
    conn.commit()
    return inserted


def save_betting_ticket(conn: Connection, ticket: dict) -> int:
    """保存一张手动投注票及其选项。

    这是手动决策的财务账本，不是竞彩原始数据表。
    原始SP快照保存在sporttery_sp_snapshot中。
    """
    selections = ticket.get("selections") or []
    if not selections:
        raise ValueError("ticket selections are required")

    placed_at = ticket.get("placed_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    source_type = _normalize_source_type(ticket.get("source_type"))
    cur = conn.execute(
        """
        INSERT INTO betting_ticket
            (bet_group, source_type, ticket_label, pass_type, stake_amount, unit_stake,
             multiplier, ticket_status, expected_min_payout, expected_max_payout,
             actual_payout, profit_loss, placed_at, settled_at, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ticket.get("bet_group"),
            source_type,
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
    """查找与投注选项匹配的已存储SP快照行。"""
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
    """获取已保存的手动投注票，可选按组过滤。"""
    sql = "SELECT * FROM betting_ticket"
    params: tuple[str, ...] = ()
    if bet_group is not None:
        sql += " WHERE bet_group = ?"
        params = (bet_group,)
    sql += " ORDER BY placed_at, id"
    return _fetch_dicts(conn.execute(sql, params))


def _fetch_dicts(cur) -> list[dict]:
    rows = cur.fetchall()
    if not rows:
        return []
    if isinstance(rows[0], dict):
        return [dict(row) for row in rows]
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in rows]


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
    """如果缺少response_version列则添加到sporttery_raw_snapshot表。"""
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


def _ensure_daily_recommendation_table(conn: Connection) -> None:
    conn.execute(DDL_DAILY_RECOMMENDATION)


def _ensure_betting_ticket_columns(conn: Connection) -> None:
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(betting_ticket)").fetchall()
    }
    if "source_type" not in existing:
        conn.execute("ALTER TABLE betting_ticket ADD COLUMN source_type TEXT NULL")
    conn.execute(
        "UPDATE betting_ticket SET source_type = COALESCE(source_type, 'UNKNOWN') "
        "WHERE source_type IS NULL OR source_type = ''"
    )
    for raw_value in conn.execute("SELECT DISTINCT source_type FROM betting_ticket").fetchall():
        value = raw_value[0]
        normalized = _normalize_source_type(value)
        if value != normalized:
            conn.execute(
                "UPDATE betting_ticket SET source_type = ? WHERE source_type = ?",
                (normalized, value),
            )


_sp_hash_column_checked = False


def _ensure_sp_snapshot_hash_column(conn: Connection) -> None:
    """如果缺少content_hash列则添加到sporttery_sp_snapshot表（仅检查一次）。"""
    global _sp_hash_column_checked
    if conn.backend == "mysql":
        return
    if _sp_hash_column_checked:
        return
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(sporttery_sp_snapshot)").fetchall()
    }
    if "content_hash" not in existing:
        conn.execute("ALTER TABLE sporttery_sp_snapshot ADD COLUMN content_hash TEXT NULL")
    _sp_hash_column_checked = True


def _normalize_source_type(value: str | None) -> str:
    if value is None:
        return "SYSTEM"
    normalized = str(value).strip().upper()
    if not normalized:
        return "UNKNOWN"
    if normalized not in SOURCE_TYPES:
        raise ValueError(
            f"unsupported source_type={value!r}; allowed={sorted(SOURCE_TYPES)}"
        )
    return normalized
