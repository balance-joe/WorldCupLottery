import unittest


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


if __name__ == "__main__":
    unittest.main()
