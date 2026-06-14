"""Tests for crs/hafu parsers."""

import pytest
from src.parsers import parse_crs, parse_hafu, parse_fixed_bonus


def test_parse_crs_basic():
    """Test basic crs parsing with valid data."""
    item = {
        "s00s00": "9.50",
        "s01s00": "5.10",
        "s02s01": "6.90",
        "s-1sh": "50.00",
        "s-1sd": "600.0",
        "s-1sa": "500.0",
        "s00s00f": "0",
        "s01s00f": "0",
        "updateDate": "2026-06-08",
        "updateTime": "10:02:19",
    }
    match_id = "2040162"
    single_map = {"crs": 1}

    records = parse_crs(item, match_id, single_map)

    assert len(records) == 6
    r0 = records[0]
    assert r0["match_id"] == "2040162"
    assert r0["play_type"] == "crs"
    assert r0["option_code"] == "s00s00"
    assert r0["option_name"] == "0:0"
    assert r0["sp_value"] == 9.50
    assert r0["goal_line"] is None
    assert r0["is_single"] == 1
    assert r0["snapshot_time"] == "2026-06-08 10:02:19"


def test_parse_crs_special_codes():
    """Test crs parsing for special codes."""
    item = {
        "s-1sh": "50.00",
        "s-1sd": "600.0",
        "s-1sa": "500.0",
        "updateDate": "2026-06-08",
        "updateTime": "10:02:19",
    }
    match_id = "2040162"
    single_map = {"crs": 1}

    records = parse_crs(item, match_id, single_map)
    assert len(records) == 3
    codes = {r["option_code"]: r["option_name"] for r in records}
    assert codes["s-1sh"] == "主胜其他"
    assert codes["s-1sd"] == "平其他"
    assert codes["s-1sa"] == "客胜其他"


def test_parse_crs_skip_f_suffix():
    """Test that f suffix options are skipped."""
    item = {
        "s00s00": "9.50",
        "s00s00f": "0",
        "s01s00": "5.10",
        "s01s00f": "0",
        "updateDate": "2026-06-08",
        "updateTime": "10:02:19",
    }
    match_id = "2040162"
    single_map = {"crs": 1}

    records = parse_crs(item, match_id, single_map)
    assert len(records) == 2
    assert all(not r["option_code"].endswith("f") for r in records)


def test_parse_crs_skip_zero_values():
    """Test that zero value options are skipped."""
    item = {
        "s00s00": "9.50",
        "s01s00": "0",
        "s02s01": "6.90",
        "updateDate": "2026-06-08",
        "updateTime": "10:02:19",
    }
    match_id = "2040162"
    single_map = {"crs": 1}

    records = parse_crs(item, match_id, single_map)
    assert len(records) == 2
    assert records[0]["option_code"] == "s00s00"
    assert records[1]["option_code"] == "s02s01"


def test_parse_hafu_basic():
    """Test basic hafu parsing with valid data."""
    item = {
        "hh": "1.91",
        "hd": "21.00",
        "ha": "65.00",
        "dh": "3.65",
        "dd": "5.45",
        "da": "16.00",
        "ah": "30.00",
        "ad": "21.00",
        "aa": "15.00",
        "hhf": "0",
        "updateDate": "2026-06-08",
        "updateTime": "10:02:19",
    }
    match_id = "2040162"
    single_map = {"hafu": 1}

    records = parse_hafu(item, match_id, single_map)

    assert len(records) == 9
    r0 = records[0]
    assert r0["match_id"] == "2040162"
    assert r0["play_type"] == "hafu"
    assert r0["option_code"] == "hh"
    assert r0["option_name"] == "主/主"
    assert r0["sp_value"] == 1.91
    assert r0["goal_line"] is None
    assert r0["is_single"] == 1
    assert r0["snapshot_time"] == "2026-06-08 10:02:19"


def test_parse_hafu_option_names():
    """Test hafu option name mapping."""
    item = {
        "hh": "1.91", "hd": "21.00", "ha": "65.00",
        "dh": "3.65", "dd": "5.45", "da": "16.00",
        "ah": "30.00", "ad": "21.00", "aa": "15.00",
        "updateDate": "2026-06-08", "updateTime": "10:02:19",
    }
    match_id = "2040162"
    single_map = {"hafu": 1}

    records = parse_hafu(item, match_id, single_map)
    names = {r["option_code"]: r["option_name"] for r in records}
    assert names["hh"] == "主/主"
    assert names["hd"] == "主/平"
    assert names["ha"] == "主/客"
    assert names["dh"] == "平/主"
    assert names["dd"] == "平/平"
    assert names["da"] == "平/客"
    assert names["ah"] == "客/主"
    assert names["ad"] == "客/平"
    assert names["aa"] == "客/客"


def test_parse_hafu_skip_f_suffix():
    """Test that f suffix options are skipped."""
    item = {
        "hh": "1.91", "hhf": "0",
        "hd": "21.00", "hdf": "0",
        "updateDate": "2026-06-08", "updateTime": "10:02:19",
    }
    match_id = "2040162"
    single_map = {"hafu": 1}

    records = parse_hafu(item, match_id, single_map)
    assert len(records) == 2
    assert all(not r["option_code"].endswith("f") for r in records)


def test_parse_hafu_skip_zero_values():
    """Test that zero value options are skipped."""
    item = {
        "hh": "1.91", "hd": "0", "ha": "65.00",
        "updateDate": "2026-06-08", "updateTime": "10:02:19",
    }
    match_id = "2040162"
    single_map = {"hafu": 1}

    records = parse_hafu(item, match_id, single_map)
    assert len(records) == 2
    assert records[0]["option_code"] == "hh"
    assert records[1]["option_code"] == "ha"


def test_parse_fixed_bonus_includes_crs_hafu():
    """Test that parse_fixed_bonus now includes crs and hafu records."""
    raw = {
        "value": {
            "oddsHistory": {
                "hadList": [
                    {
                        "h": "1.85", "d": "3.50", "a": "4.20",
                        "goalLine": "",
                        "updateDate": "2026-06-08", "updateTime": "10:02:19",
                    }
                ],
                "hhadList": [],
                "ttgList": [],
                "crsList": [
                    {
                        "s00s00": "9.50", "s01s00": "5.10", "s00s00f": "0",
                        "updateDate": "2026-06-08", "updateTime": "10:02:19",
                    }
                ],
                "hafuList": [
                    {
                        "hh": "1.91", "hd": "21.00", "hhf": "0",
                        "updateDate": "2026-06-08", "updateTime": "10:02:19",
                    }
                ],
                "singleList": [
                    {"poolCode": "HAD", "single": 1},
                    {"poolCode": "CRS", "single": 1},
                    {"poolCode": "HAFU", "single": 1},
                ],
            }
        }
    }
    match_id = "2040162"

    records = parse_fixed_bonus(raw, match_id)

    by_play = {}
    for r in records:
        by_play.setdefault(r["play_type"], []).append(r)

    assert "had" in by_play
    assert "crs" in by_play
    assert "hafu" in by_play

    crs_records = by_play["crs"]
    assert len(crs_records) == 2
    assert crs_records[0]["option_code"] == "s00s00"
    assert crs_records[1]["option_code"] == "s01s00"

    hafu_records = by_play["hafu"]
    assert len(hafu_records) == 2
    assert hafu_records[0]["option_code"] == "hh"
    assert hafu_records[1]["option_code"] == "hd"
