"""Tests for crs/hafu signal rules in LLM package."""

import pytest
from src.llm_package import _classify_signals


def test_crs_low_price_concentration():
    """Test crs low price concentration signal."""
    markets = {
        "crs": {
            "options": [
                {"code": "s01s00", "current_prob": 0.20},
                {"code": "s00s00", "current_prob": 0.15},
                {"code": "s02s01", "current_prob": 0.12},
                {"code": "s02s00", "current_prob": 0.10},
                {"code": "s00s01", "current_prob": 0.08},
            ]
        }
    }
    signals = _classify_signals(markets, {}, {}, {}, {"tradable": True})
    assert any("比分低赔集中在" in s for s in signals["structure_signals"])


def test_crs_other_score_comparison():
    """Test crs 主胜其他 vs 客胜其他 comparison."""
    markets = {
        "crs": {
            "options": [
                {"code": "s-1sh", "current_prob": 0.15},
                {"code": "s-1sa", "current_prob": 0.08},
            ]
        }
    }
    signals = _classify_signals(markets, {}, {}, {}, {"tradable": True})
    assert any("主胜其他概率高于客胜其他" in s for s in signals["positive_signals"])


def test_crs_sp_change():
    """Test crs SP change signal."""
    markets = {
        "crs": {
            "options": [
                {
                    "code": "s01s00",
                    "current_sp": 4.50,
                    "open_sp": 5.10,
                    "sp_change": -0.60,
                    "prob_change": 0.02,
                },
            ]
        }
    }
    signals = _classify_signals(markets, {}, {}, {}, {"tradable": True})
    assert any("SP 下降" in s for s in signals["positive_signals"])


def test_hafu_home_home_probability():
    """Test hafu 主/主 probability signal."""
    markets = {
        "hafu": {
            "options": [
                {"code": "hh", "current_prob": 0.30},
                {"code": "hd", "current_prob": 0.10},
            ]
        }
    }
    signals = _classify_signals(markets, {}, {}, {}, {"tradable": True})
    assert any("半全场主/主概率" in s for s in signals["positive_signals"])


def test_hafu_half_draw_structure():
    """Test hafu 半场平局 structure signal.

    Core threshold: half_draw > 0.40
    """
    markets = {
        "hafu": {
            "options": [
                {"code": "dh", "current_prob": 0.20},
                {"code": "dd", "current_prob": 0.15},
                {"code": "da", "current_prob": 0.10},
                {"code": "hh", "current_prob": 0.25},
            ]
        }
    }
    signals = _classify_signals(markets, {}, {}, {}, {"tradable": True})
    assert any("半场平局概率" in s for s in signals["structure_signals"])


def test_hafu_full_home_win_structure():
    """Test hafu 全场主胜 structure signal.

    Core threshold: full_home > 0.50
    """
    markets = {
        "hafu": {
            "options": [
                {"code": "hh", "current_prob": 0.30},
                {"code": "dh", "current_prob": 0.20},
                {"code": "ah", "current_prob": 0.10},
                {"code": "hd", "current_prob": 0.10},
            ]
        }
    }
    signals = _classify_signals(markets, {}, {}, {}, {"tradable": True})
    assert any("全场主胜概率" in s for s in signals["positive_signals"])


def test_hafu_had_consistency():
    """Test hafu and had direction consistency."""
    markets = {
        "had": {
            "options": [
                {"code": "H", "sp_change": -0.20},
            ]
        },
        "hafu": {
            "options": [
                {"code": "hh", "current_prob": 0.30},
            ]
        }
    }
    signals = _classify_signals(markets, {}, {}, {}, {"tradable": True})
    assert any("半全场与胜平负方向一致" in s for s in signals["positive_signals"])
