-- Sporttery SP Radar - Database Schema
-- MySQL 5.7+ / 8.0+

CREATE DATABASE IF NOT EXISTS sporttery DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE sporttery;

-- 1. Raw API snapshots (never overwrite)
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

-- 2. Match master table
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

-- 3. SP snapshots (all play types, time series)
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

-- 4. Signals (generated from SP analysis)
CREATE TABLE IF NOT EXISTS sporttery_signal (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    match_id VARCHAR(64) NOT NULL,
    snapshot_time DATETIME NOT NULL,
    signal_type VARCHAR(64) NOT NULL COMMENT 'positive/negative/structure/uncertainty',
    signal_level VARCHAR(16) NOT NULL COMMENT 'low/medium/high',
    play_type VARCHAR(32) NULL,
    option_code VARCHAR(32) NULL,
    description TEXT NOT NULL,
    evidence_json JSON NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    KEY idx_match_time (match_id, snapshot_time),
    KEY idx_signal_type (signal_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
