import unittest

from src.market_structure import analyze_market_structure
from src.sp_trend import PlayTrend, TrendOption


def trend(play_type, direction, confidence="medium", available=True, options=()):
    return PlayTrend(
        match_id="1",
        play_type=play_type,
        window="open_to_latest",
        available=available,
        reason=None if available else "not_enough_snapshots",
        options=tuple(options),
        main_direction=direction,
        direction_confidence=confidence,
        direction_gap=0.03 if confidence == "medium" else 0.05,
        handicap_line="-1" if play_type == "hhad" and available else None,
    )


def home_option(sp_end=1.8):
    return TrendOption(
        option_code="H",
        option_name="主胜",
        sp_start=2.0,
        sp_end=sp_end,
        sp_delta=-0.2,
        sp_delta_pct=-0.1,
        raw_implied_weight_start=0.5,
        raw_implied_weight_end=0.55,
        normalized_implied_weight_start=0.45,
        normalized_implied_weight_end=0.50,
        normalized_weight_delta=0.05,
        sp_trend="strong_down",
        weight_trend="strengthening",
    )


class MarketStructureTest(unittest.TestCase):
    def test_hhad_missing_does_not_force_home_small_win(self):
        # Case 1: both hhad and ttg unavailable — single play type, must not be A
        structure = analyze_market_structure(
            "1",
            "open_to_latest",
            trend("had", "home_win_strengthening"),
            trend("hhad", "no_clear_direction", available=False),
            trend("ttg", "no_clear_goal_direction", available=False),
        )

        self.assertNotEqual(structure.main_market_expression, "home_small_win_supported")
        self.assertNotEqual(structure.research_priority, "A")

        # Case 2: hhad unavailable but ttg has direction — still must not be A
        structure2 = analyze_market_structure(
            "1",
            "open_to_latest",
            trend("had", "home_win_strengthening"),
            trend("hhad", "no_clear_direction", available=False),
            trend("ttg", "low_goal_strengthening", "medium"),
        )

        self.assertNotEqual(structure2.research_priority, "A")

    def test_home_win_with_hhad_counter_signal(self):
        structure = analyze_market_structure(
            "1",
            "open_to_latest",
            trend("had", "home_win_strengthening"),
            trend("hhad", "handicap_away_strengthening", "medium"),
            trend("ttg", "low_goal_strengthening", "medium"),
        )

        self.assertEqual(structure.main_market_expression, "home_small_win_supported")
        self.assertIn("hhad_counter_signal", [risk.code for risk in structure.risk_flags])

    def test_home_big_win_structure(self):
        structure = analyze_market_structure(
            "1",
            "open_to_latest",
            trend("had", "home_win_strengthening"),
            trend("hhad", "handicap_home_strengthening", "medium"),
            trend("ttg", "mid_goal_strengthening", "medium"),
        )

        self.assertEqual(structure.main_market_expression, "home_big_win_supported")
        self.assertIn(structure.research_priority, {"A", "B"})

    def test_goal_clear_result_unclear(self):
        structure = analyze_market_structure(
            "1",
            "open_to_latest",
            trend("had", "no_clear_direction", "none"),
            trend("hhad", "no_clear_direction", "none"),
            trend("ttg", "high_goal_strengthening", "medium"),
        )

        self.assertEqual(structure.main_market_expression, "goal_market_clear_but_result_unclear")
        self.assertIn("ttg_4_plus_goals", structure.suggested_focus)

    def test_all_missing_graceful_degradation(self):
        structure = analyze_market_structure(
            "1",
            "open_to_latest",
            trend("had", "no_clear_direction", available=False),
            trend("hhad", "no_clear_direction", available=False),
            trend("ttg", "no_clear_goal_direction", available=False),
        )

        self.assertFalse(structure.available)
        self.assertEqual(structure.research_priority, "D")

    def test_popular_home_overheated_risk(self):
        structure = analyze_market_structure(
            "1",
            "open_to_latest",
            trend("had", "home_win_strengthening", options=(home_option(sp_end=1.40),)),
            trend("hhad", "no_clear_direction", "none"),
            trend("ttg", "mid_goal_strengthening", "medium"),
        )

        self.assertIn("popular_home_win_overheated", [risk.code for risk in structure.risk_flags])

    def test_away_not_lose_or_small_win(self):
        structure = analyze_market_structure(
            "1",
            "open_to_latest",
            trend("had", "away_win_strengthening"),
            trend("hhad", "handicap_away_strengthening", "medium"),
            trend("ttg", "low_goal_strengthening", "medium"),
        )

        self.assertEqual(structure.main_market_expression, "away_not_lose_or_small_win_supported")

    def test_mixed_or_noisy_low_confidence(self):
        structure = analyze_market_structure(
            "1",
            "open_to_latest",
            trend("had", "no_clear_direction", "none"),
            trend("hhad", "no_clear_direction", "none"),
            trend("ttg", "no_clear_goal_direction", "none"),
        )

        self.assertEqual(structure.main_market_expression, "mixed_or_noisy")
        self.assertEqual(structure.research_priority, "D")

    def test_single_play_type_gets_priority_c(self):
        """Only 1 available play type should be C, not A or B."""
        structure = analyze_market_structure(
            "1",
            "open_to_latest",
            trend("had", "home_win_strengthening", "high"),
            trend("hhad", "no_clear_direction", available=False),
            trend("ttg", "no_clear_goal_direction", available=False),
        )

        self.assertIn(structure.research_priority, {"C", "D"})

    def test_hhad_no_confirmation_risk(self):
        """hhad no_clear with low confidence is a medium-low risk."""
        structure = analyze_market_structure(
            "1",
            "open_to_latest",
            trend("had", "home_win_strengthening"),
            trend("hhad", "no_clear_direction", "low"),
            trend("ttg", "mid_goal_strengthening", "medium"),
        )

        risk_codes = [risk.code for risk in structure.risk_flags]
        self.assertIn("hhad_no_confirmation", risk_codes)

    def test_away_unbeaten_strengthening(self):
        structure = analyze_market_structure(
            "1",
            "open_to_latest",
            trend("had", "away_unbeaten_strengthening"),
            trend("hhad", "handicap_away_strengthening", "medium"),
            trend("ttg", "low_goal_strengthening", "medium"),
        )

        self.assertEqual(structure.main_market_expression, "away_not_lose_or_small_win_supported")


if __name__ == "__main__":
    unittest.main()
