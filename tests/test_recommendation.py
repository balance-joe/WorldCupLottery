import unittest

from src.recommendation import build_match_recommendation, filter_sp_records_as_of


class RecommendationTest(unittest.TestCase):
    def test_filter_sp_records_as_of_respects_cutoff(self):
        records = [
            {"snapshot_time": "2026-06-20 09:00:00", "play_type": "had"},
            {"snapshot_time": "2026-06-20 12:00:00", "play_type": "had"},
        ]
        filtered = filter_sp_records_as_of(records, "2026-06-20 10:00:00")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["snapshot_time"], "2026-06-20 09:00:00")

    def test_build_match_recommendation_blocks_noisy_market(self):
        match = {
            "match_id": "1",
            "match_time": "2026-06-23 20:00:00",
        }
        records = [
            {"match_id": "1", "snapshot_time": "2026-06-22 10:00:00", "play_type": "had", "option_code": "H", "sp_value": 1.80},
            {"match_id": "1", "snapshot_time": "2026-06-22 10:00:00", "play_type": "had", "option_code": "D", "sp_value": 3.40},
            {"match_id": "1", "snapshot_time": "2026-06-22 10:00:00", "play_type": "had", "option_code": "A", "sp_value": 4.20},
            {"match_id": "1", "snapshot_time": "2026-06-22 11:00:00", "play_type": "had", "option_code": "H", "sp_value": 1.81},
            {"match_id": "1", "snapshot_time": "2026-06-22 11:00:00", "play_type": "had", "option_code": "D", "sp_value": 3.38},
            {"match_id": "1", "snapshot_time": "2026-06-22 11:00:00", "play_type": "had", "option_code": "A", "sp_value": 4.18},
        ]
        recommendation = build_match_recommendation(match, records)
        self.assertFalse(recommendation.gate.allowed)
        self.assertIn("priority_D_blocked", recommendation.gate.reasons)
        self.assertEqual(recommendation.suggestions, ())

    def test_build_match_recommendation_generates_aligned_candidates(self):
        match = {
            "match_id": "1",
            "match_time": "2026-06-23 01:00:00",
        }
        records = [
            {"match_id": "1", "snapshot_time": "2026-06-20 09:00:00", "play_type": "had", "option_code": "H", "option_name": "主胜", "sp_value": 1.50, "implied_prob_norm": 0.58},
            {"match_id": "1", "snapshot_time": "2026-06-20 09:00:00", "play_type": "had", "option_code": "D", "option_name": "平", "sp_value": 3.60, "implied_prob_norm": 0.24},
            {"match_id": "1", "snapshot_time": "2026-06-20 09:00:00", "play_type": "had", "option_code": "A", "option_name": "客胜", "sp_value": 5.20, "implied_prob_norm": 0.18},
            {"match_id": "1", "snapshot_time": "2026-06-22 12:00:00", "play_type": "had", "option_code": "H", "option_name": "主胜", "sp_value": 1.30, "implied_prob_norm": 0.68},
            {"match_id": "1", "snapshot_time": "2026-06-22 12:00:00", "play_type": "had", "option_code": "D", "option_name": "平", "sp_value": 4.20, "implied_prob_norm": 0.20},
            {"match_id": "1", "snapshot_time": "2026-06-22 12:00:00", "play_type": "had", "option_code": "A", "option_name": "客胜", "sp_value": 7.20, "implied_prob_norm": 0.12},
            {"match_id": "1", "snapshot_time": "2026-06-20 09:00:00", "play_type": "hhad", "option_code": "H", "sp_value": 2.60, "goal_line": "-1", "implied_prob_norm": 0.34},
            {"match_id": "1", "snapshot_time": "2026-06-20 09:00:00", "play_type": "hhad", "option_code": "D", "sp_value": 3.40, "goal_line": "-1", "implied_prob_norm": 0.26},
            {"match_id": "1", "snapshot_time": "2026-06-20 09:00:00", "play_type": "hhad", "option_code": "A", "sp_value": 2.20, "goal_line": "-1", "implied_prob_norm": 0.40},
            {"match_id": "1", "snapshot_time": "2026-06-22 12:00:00", "play_type": "hhad", "option_code": "H", "sp_value": 2.02, "goal_line": "-1", "implied_prob_norm": 0.43},
            {"match_id": "1", "snapshot_time": "2026-06-22 12:00:00", "play_type": "hhad", "option_code": "D", "sp_value": 3.40, "goal_line": "-1", "implied_prob_norm": 0.26},
            {"match_id": "1", "snapshot_time": "2026-06-22 12:00:00", "play_type": "hhad", "option_code": "A", "sp_value": 2.86, "goal_line": "-1", "implied_prob_norm": 0.31},
            {"match_id": "1", "snapshot_time": "2026-06-20 09:00:00", "play_type": "ttg", "option_code": "2", "sp_value": 3.20, "implied_prob_norm": 0.25},
            {"match_id": "1", "snapshot_time": "2026-06-20 09:00:00", "play_type": "ttg", "option_code": "3", "sp_value": 3.55, "implied_prob_norm": 0.22},
            {"match_id": "1", "snapshot_time": "2026-06-20 09:00:00", "play_type": "ttg", "option_code": "4", "sp_value": 5.60, "implied_prob_norm": 0.14},
            {"match_id": "1", "snapshot_time": "2026-06-20 09:00:00", "play_type": "ttg", "option_code": "5", "sp_value": 10.00, "implied_prob_norm": 0.08},
            {"match_id": "1", "snapshot_time": "2026-06-20 09:00:00", "play_type": "ttg", "option_code": "0", "sp_value": 10.50, "implied_prob_norm": 0.07},
            {"match_id": "1", "snapshot_time": "2026-06-20 09:00:00", "play_type": "ttg", "option_code": "1", "sp_value": 4.80, "implied_prob_norm": 0.17},
            {"match_id": "1", "snapshot_time": "2026-06-20 09:00:00", "play_type": "ttg", "option_code": "6", "sp_value": 18.00, "implied_prob_norm": 0.04},
            {"match_id": "1", "snapshot_time": "2026-06-20 09:00:00", "play_type": "ttg", "option_code": "7", "sp_value": 25.00, "implied_prob_norm": 0.03},
            {"match_id": "1", "snapshot_time": "2026-06-22 12:00:00", "play_type": "ttg", "option_code": "2", "sp_value": 3.55, "implied_prob_norm": 0.22},
            {"match_id": "1", "snapshot_time": "2026-06-22 12:00:00", "play_type": "ttg", "option_code": "3", "sp_value": 3.45, "implied_prob_norm": 0.23},
            {"match_id": "1", "snapshot_time": "2026-06-22 12:00:00", "play_type": "ttg", "option_code": "4", "sp_value": 5.00, "implied_prob_norm": 0.16},
            {"match_id": "1", "snapshot_time": "2026-06-22 12:00:00", "play_type": "ttg", "option_code": "5", "sp_value": 9.20, "implied_prob_norm": 0.09},
            {"match_id": "1", "snapshot_time": "2026-06-22 12:00:00", "play_type": "ttg", "option_code": "0", "sp_value": 13.00, "implied_prob_norm": 0.06},
            {"match_id": "1", "snapshot_time": "2026-06-22 12:00:00", "play_type": "ttg", "option_code": "1", "sp_value": 4.90, "implied_prob_norm": 0.16},
            {"match_id": "1", "snapshot_time": "2026-06-22 12:00:00", "play_type": "ttg", "option_code": "6", "sp_value": 16.50, "implied_prob_norm": 0.05},
            {"match_id": "1", "snapshot_time": "2026-06-22 12:00:00", "play_type": "ttg", "option_code": "7", "sp_value": 24.00, "implied_prob_norm": 0.03},
            {"match_id": "1", "snapshot_time": "2026-06-22 12:00:00", "play_type": "crs", "option_code": "s02s00", "sp_value": 6.00, "implied_prob_norm": 0.118},
            {"match_id": "1", "snapshot_time": "2026-06-22 12:00:00", "play_type": "crs", "option_code": "s02s01", "sp_value": 6.40, "implied_prob_norm": 0.109},
            {"match_id": "1", "snapshot_time": "2026-06-22 12:00:00", "play_type": "crs", "option_code": "s03s01", "sp_value": 8.80, "implied_prob_norm": 0.081},
            {"match_id": "1", "snapshot_time": "2026-06-22 12:00:00", "play_type": "crs", "option_code": "s01s01", "sp_value": 7.50, "implied_prob_norm": 0.095},
        ]
        recommendation = build_match_recommendation(match, records)
        self.assertTrue(recommendation.gate.allowed)
        self.assertEqual(recommendation.candidates.had_options, ("H",))
        self.assertEqual(recommendation.candidates.hhad_options, ("H",))
        self.assertIn("3", recommendation.candidates.ttg_options)
        self.assertEqual(recommendation.candidates.crs_options[:2], ("s02s00", "s02s01"))
        self.assertEqual(len(recommendation.suggestions), 1)
        self.assertEqual(recommendation.suggestions[0].play_type, "hhad")
        self.assertEqual(recommendation.suggestions[0].selections, ("H",))


if __name__ == "__main__":
    unittest.main()
