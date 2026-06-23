"""Unit tests for src.probability — implied probability calculation."""

from __future__ import annotations

import unittest

from src.probability import calc_implied_prob


class CalcImpliedProbTest(unittest.TestCase):
    """Tests for calc_implied_prob."""

    def test_single_group_normalizes_to_one(self):
        records = [
            {"match_id": "m1", "play_type": "had", "snapshot_time": "t1", "option_code": "H", "sp_value": 2.0},
            {"match_id": "m1", "play_type": "had", "snapshot_time": "t1", "option_code": "D", "sp_value": 3.0},
            {"match_id": "m1", "play_type": "had", "snapshot_time": "t1", "option_code": "A", "sp_value": 5.0},
        ]
        result = calc_implied_prob(records)
        norm_sum = sum(r["implied_prob_norm"] for r in result)
        self.assertAlmostEqual(norm_sum, 1.0, places=10)
        # H has highest SP weight (lowest SP)
        self.assertGreater(result[0]["implied_prob_norm"], result[1]["implied_prob_norm"])
        self.assertGreater(result[1]["implied_prob_norm"], result[2]["implied_prob_norm"])

    def test_multi_group_independent_normalization(self):
        records = [
            {"match_id": "m1", "play_type": "had", "snapshot_time": "t1", "option_code": "H", "sp_value": 2.0},
            {"match_id": "m1", "play_type": "had", "snapshot_time": "t1", "option_code": "D", "sp_value": 3.0},
            {"match_id": "m1", "play_type": "had", "snapshot_time": "t2", "option_code": "H", "sp_value": 1.5},
            {"match_id": "m1", "play_type": "had", "snapshot_time": "t2", "option_code": "D", "sp_value": 4.0},
        ]
        result = calc_implied_prob(records)
        # Group 1 (t1)
        t1 = [r for r in result if r["snapshot_time"] == "t1"]
        self.assertAlmostEqual(sum(r["implied_prob_norm"] for r in t1), 1.0, places=10)
        # Group 2 (t2)
        t2 = [r for r in result if r["snapshot_time"] == "t2"]
        self.assertAlmostEqual(sum(r["implied_prob_norm"] for r in t2), 1.0, places=10)

    def test_zero_sp_value_gets_zero_prob(self):
        records = [
            {"match_id": "m1", "play_type": "had", "snapshot_time": "t1", "option_code": "H", "sp_value": 2.0},
            {"match_id": "m1", "play_type": "had", "snapshot_time": "t1", "option_code": "D", "sp_value": 0},
        ]
        result = calc_implied_prob(records)
        h = [r for r in result if r["option_code"] == "H"][0]
        d = [r for r in result if r["option_code"] == "D"][0]
        self.assertAlmostEqual(h["implied_prob_norm"], 1.0, places=10)
        self.assertEqual(d["implied_prob_raw"], 0.0)
        self.assertEqual(d["implied_prob_norm"], 0.0)

    def test_negative_sp_value_gets_zero_prob(self):
        records = [
            {"match_id": "m1", "play_type": "had", "snapshot_time": "t1", "option_code": "H", "sp_value": -1.0},
            {"match_id": "m1", "play_type": "had", "snapshot_time": "t1", "option_code": "D", "sp_value": 3.0},
        ]
        result = calc_implied_prob(records)
        h = [r for r in result if r["option_code"] == "H"][0]
        self.assertEqual(h["implied_prob_raw"], 0.0)

    def test_all_zero_sp_values(self):
        records = [
            {"match_id": "m1", "play_type": "had", "snapshot_time": "t1", "option_code": "H", "sp_value": 0},
            {"match_id": "m1", "play_type": "had", "snapshot_time": "t1", "option_code": "D", "sp_value": 0},
        ]
        result = calc_implied_prob(records)
        for r in result:
            self.assertEqual(r["implied_prob_raw"], 0.0)
            self.assertEqual(r["implied_prob_norm"], 0.0)
            self.assertEqual(r["prob_sum"], 0.0)

    def test_empty_list_returns_empty(self):
        result = calc_implied_prob([])
        self.assertEqual(result, [])

    def test_single_record(self):
        records = [
            {"match_id": "m1", "play_type": "had", "snapshot_time": "t1", "option_code": "H", "sp_value": 2.5},
        ]
        result = calc_implied_prob(records)
        self.assertAlmostEqual(result[0]["implied_prob_raw"], 0.4, places=10)
        self.assertAlmostEqual(result[0]["implied_prob_norm"], 1.0, places=10)
        self.assertAlmostEqual(result[0]["prob_sum"], 0.4, places=10)

    def test_modifies_in_place(self):
        records = [
            {"match_id": "m1", "play_type": "had", "snapshot_time": "t1", "option_code": "H", "sp_value": 2.0},
        ]
        result = calc_implied_prob(records)
        self.assertIs(result, records)
        self.assertIn("implied_prob_raw", records[0])
        self.assertIn("implied_prob_norm", records[0])
        self.assertIn("prob_sum", records[0])

    def test_none_sp_value_gets_zero_prob(self):
        records = [
            {"match_id": "m1", "play_type": "had", "snapshot_time": "t1", "option_code": "H", "sp_value": None},
            {"match_id": "m1", "play_type": "had", "snapshot_time": "t1", "option_code": "D", "sp_value": 3.0},
        ]
        result = calc_implied_prob(records)
        h = [r for r in result if r["option_code"] == "H"][0]
        self.assertEqual(h["implied_prob_raw"], 0.0)

    def test_different_play_types_are_separate_groups(self):
        records = [
            {"match_id": "m1", "play_type": "had", "snapshot_time": "t1", "option_code": "H", "sp_value": 2.0},
            {"match_id": "m1", "play_type": "had", "snapshot_time": "t1", "option_code": "D", "sp_value": 3.0},
            {"match_id": "m1", "play_type": "hhad", "snapshot_time": "t1", "option_code": "H", "sp_value": 1.8},
            {"match_id": "m1", "play_type": "hhad", "snapshot_time": "t1", "option_code": "D", "sp_value": 3.5},
        ]
        result = calc_implied_prob(records)
        had = [r for r in result if r["play_type"] == "had"]
        hhad = [r for r in result if r["play_type"] == "hhad"]
        self.assertAlmostEqual(sum(r["implied_prob_norm"] for r in had), 1.0, places=10)
        self.assertAlmostEqual(sum(r["implied_prob_norm"] for r in hhad), 1.0, places=10)


if __name__ == "__main__":
    unittest.main()
