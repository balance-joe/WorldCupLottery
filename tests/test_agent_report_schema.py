"""Tests for agent_report_schema: LLM package builder and output validation."""

import unittest

from src.agent_report_schema import (
    build_agent_report_package,
    build_cross_window_summary,
    final_research_priority,
    validate_llm_output_json,
)
from src.market_structure import MarketMessage, MarketStructure


def _structure(window, expression, priority, available=True, had_dir="home_win_strengthening"):
    return MarketStructure(
        match_id="1",
        window=window,
        available=available,
        had_direction=had_dir,
        hhad_direction="handicap_home_strengthening",
        ttg_direction="mid_goal_strengthening",
        handicap_line="-1",
        consistency_level="strong",
        main_market_expression=expression,
        conflicts=(),
        risk_flags=(),
        suggested_focus=("had_home",),
        avoid_focus=(),
        research_priority=priority,
    )


class ValidateLlmOutputTest(unittest.TestCase):
    def test_valid_output_no_errors(self):
        data = {
            "market_reading": "主队方向增强",
            "play_consistency": "胜平负与让球一致",
            "tempo_reading": "长期与临场一致",
            "risk_explanations": [],
            "suggested_human_focus": ["主胜"],
            "avoid_or_caution": [],
            "research_priority": "A",
            "confidence_type": "structure_confidence_not_win_probability",
        }
        errors = validate_llm_output_json(data)
        self.assertEqual(errors, [])

    def test_missing_field_detected(self):
        data = {"market_reading": "test"}
        errors = validate_llm_output_json(data)
        self.assertTrue(any("missing field" in e for e in errors))

    def test_forbidden_term_detected(self):
        data = {
            "market_reading": "必胜",
            "play_consistency": "",
            "tempo_reading": "",
            "risk_explanations": [],
            "suggested_human_focus": [],
            "avoid_or_caution": [],
            "research_priority": "A",
            "confidence_type": "structure_confidence_not_win_probability",
        }
        errors = validate_llm_output_json(data)
        self.assertTrue(any("forbidden term" in e for e in errors))

    def test_wrong_confidence_type_detected(self):
        data = {
            "market_reading": "",
            "play_consistency": "",
            "tempo_reading": "",
            "risk_explanations": [],
            "suggested_human_focus": [],
            "avoid_or_caution": [],
            "research_priority": "A",
            "confidence_type": "wrong_type",
        }
        errors = validate_llm_output_json(data)
        self.assertTrue(any("confidence_type" in e for e in errors))

    def test_json_parse_error_detected(self):
        errors = validate_llm_output_json('{"market_reading": ')
        self.assertTrue(any("invalid json" in e for e in errors))

    def test_json_string_validated(self):
        data = """{
          "market_reading": "主队方向增强",
          "play_consistency": "胜平负与让球一致",
          "tempo_reading": "长期与临场一致",
          "risk_explanations": [],
          "suggested_human_focus": ["主胜"],
          "avoid_or_caution": [],
          "research_priority": "A",
          "confidence_type": "structure_confidence_not_win_probability"
        }"""
        self.assertEqual(validate_llm_output_json(data), [])


class FinalResearchPriorityTest(unittest.TestCase):
    def test_picks_best_across_windows(self):
        structures = {
            "open_to_latest": _structure("open_to_latest", "home_small_win_supported", "B"),
            "last_6h": _structure("last_6h", "home_big_win_supported", "A"),
        }
        self.assertEqual(final_research_priority(structures), "A")

    def test_all_unavailable_returns_d(self):
        structures = {
            "open_to_latest": _structure("open_to_latest", "mixed_or_noisy", "D", available=False),
        }
        self.assertEqual(final_research_priority(structures), "D")


class CrossWindowSummaryTest(unittest.TestCase):
    def test_consistent_expressions(self):
        structures = {
            "open_to_latest": _structure("open_to_latest", "home_small_win_supported", "A"),
            "last_6h": _structure("last_6h", "home_small_win_supported", "A"),
        }
        summary = build_cross_window_summary(structures)
        self.assertIn("一致", summary["tempo_reading"])

    def test_long_term_mixed_recent_clear(self):
        structures = {
            "open_to_latest": _structure("open_to_latest", "mixed_or_noisy", "C"),
            "last_6h": _structure("last_6h", "home_big_win_supported", "A"),
        }
        summary = build_cross_window_summary(structures)
        self.assertIn("临场", summary["tempo_reading"])

    def test_all_missing(self):
        structures = {}
        summary = build_cross_window_summary(structures)
        self.assertIn("数据不足", summary["long_term_direction"])


class BuildAgentReportPackageTest(unittest.TestCase):
    def test_package_has_required_keys(self):
        match_info = {
            "match_id": "123",
            "match_num": "周三001",
            "league_name": "世界杯",
            "match_time": "2026-06-11 22:00:00",
            "home_team_name": "法国",
            "away_team_name": "丹麦",
        }
        structures = {
            "open_to_latest": _structure("open_to_latest", "home_small_win_supported", "A"),
        }
        package = build_agent_report_package(match_info, structures)

        self.assertIn("match", package)
        self.assertIn("window_summaries", package)
        self.assertIn("cross_window_summary", package)
        self.assertIn("final_research_priority", package)
        self.assertIn("llm_instruction", package)
        self.assertEqual(package["match"]["home_team"], "法国")
        self.assertEqual(package["match"]["handicap_line"], "-1")


if __name__ == "__main__":
    unittest.main()
