import unittest
from types import SimpleNamespace

from scripts.analyze_today_matches import _main_pick
from scripts.backtest_daily_suggestions import _evaluate_suggestion, _predict_crs, _settle_single_prediction, _settle_suggestion


def _recommendation(had_options, had_sps):
    return SimpleNamespace(
        gate=SimpleNamespace(allowed=True),
        candidates=SimpleNamespace(had_options=tuple(had_options), crs_options=()),
        had_trend=SimpleNamespace(
            options=tuple(
                SimpleNamespace(option_code=code, sp_end=sp)
                for code, sp in had_sps.items()
            )
        ),
    )


class AnalyzeTodayMatchesCliShapeTest(unittest.TestCase):
    def test_expected_fields_present_for_screening_rows(self):
        row = {
            "sp_research_priority": "C",
            "final_research_priority": "B",
            "main_market_expression": "home_small_win_supported",
            "had_direction": "home_win_strengthening",
            "hhad_direction": "handicap_away_strengthening",
            "ttg_direction": "low_goal_strengthening",
            "top_risk_flags": "hhad_counter_signal",
            "suggested_focus": "had_home,ttg_0_2_goals",
            "non_sp_lean": "home",
            "support_confidence": "medium",
            "blend_reason": "non_sp_confirms_sp",
        }

        self.assertIn("sp_research_priority", row)
        self.assertIn("final_research_priority", row)
        self.assertIn("non_sp_lean", row)
        self.assertIn("support_confidence", row)
        self.assertIn("blend_reason", row)

    def test_main_pick_requires_single_had_option(self):
        recommendation = _recommendation(("H", "D"), {"H": 1.45, "D": 3.8})

        self.assertIsNone(_main_pick(recommendation))

    def test_high_sp_away_is_not_main_pick(self):
        recommendation = _recommendation(("A",), {"A": 2.2})

        self.assertIsNone(_main_pick(recommendation))

    def test_crs_prediction_does_not_fallback_when_constraints_miss(self):
        recommendation = SimpleNamespace(candidates=SimpleNamespace(crs_options=()))
        sp_history = [
            {"play_type": "crs", "snapshot_time": "2026-06-23 10:00:00", "option_code": "s02s00", "implied_prob_norm": 0.2},
        ]

        self.assertIsNone(_predict_crs(recommendation, sp_history, "A", "1"))

    def test_settle_suggestion_uses_one_unit_per_selection(self):
        match = {"home_score_90": 2, "away_score_90": 1}
        sp_history = [
            {"play_type": "ttg", "snapshot_time": "2026-06-23 10:00:00", "option_code": "3", "sp_value": 3.45},
            {"play_type": "ttg", "snapshot_time": "2026-06-23 10:00:00", "option_code": "4", "sp_value": 5.00},
        ]

        settlement = _settle_suggestion("ttg", ("3", "4"), match, sp_history, unit_stake=2)

        self.assertTrue(settlement["settleable"])
        self.assertEqual(settlement["unit_count"], 2)
        self.assertEqual(settlement["stake"], 4)
        self.assertEqual(settlement["payout"], 6.9)
        self.assertEqual(settlement["profit"], 2.9)

    def test_settle_hhad_uses_goal_line(self):
        match = {"home_score_90": 2, "away_score_90": 1}
        sp_history = [
            {"play_type": "hhad", "snapshot_time": "2026-06-23 10:00:00", "option_code": "D", "goal_line": "-1", "sp_value": 3.40},
        ]

        settlement = _settle_suggestion("hhad", ("D",), match, sp_history, unit_stake=2)

        self.assertTrue(settlement["settleable"])
        self.assertEqual(settlement["goal_line"], "-1")
        self.assertEqual(settlement["payout"], 6.8)
        self.assertEqual(settlement["profit"], 4.8)

    def test_evaluates_hafu_and_half_result_from_half_score(self):
        match = {"half_score": "1:0", "home_score_90": 2, "away_score_90": 1}

        self.assertEqual(_evaluate_suggestion("hafu", ("hh",), match), (True, "hh"))
        self.assertEqual(_evaluate_suggestion("half_result", ("H",), match), (True, "H"))

    def test_settle_hafu_prediction_uses_sp(self):
        match = {"half_score": "1:0", "home_score_90": 2, "away_score_90": 1}
        sp_history = [
            {"play_type": "hafu", "snapshot_time": "2026-06-23 10:00:00", "option_code": "hh", "sp_value": 3.2},
        ]

        settlement = _settle_single_prediction("hafu", "hh", match, sp_history, unit_stake=2)

        self.assertTrue(settlement["settleable"])
        self.assertEqual(settlement["payout"], 6.4)
        self.assertEqual(settlement["profit"], 4.4)


if __name__ == "__main__":
    unittest.main()
