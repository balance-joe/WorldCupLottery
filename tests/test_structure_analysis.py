import unittest

from src.structure_analysis import analyze_match_windows


def row(match_id, play_type, code, sp, t, name=None, goal_line=None):
    return {
        "match_id": match_id,
        "play_type": play_type,
        "option_code": code,
        "option_name": name or code,
        "sp_value": sp,
        "snapshot_time": t,
        "goal_line": goal_line,
    }


class StructureAnalysisBlendTest(unittest.TestCase):
    def test_default_windows_exclude_last_1h(self):
        match = {
            "match_id": "1",
            "match_num": "周三001",
            "league_name": "世界杯",
            "match_time": "2026-06-11 22:00:00",
            "home_team_name": "法国",
            "away_team_name": "丹麦",
        }
        sp_history = [
            row("1", "had", "H", 2.10, "2026-06-11 10:00:00"),
            row("1", "had", "D", 3.20, "2026-06-11 10:00:00"),
            row("1", "had", "A", 3.10, "2026-06-11 10:00:00"),
            row("1", "had", "H", 1.85, "2026-06-11 20:00:00"),
            row("1", "had", "D", 3.30, "2026-06-11 20:00:00"),
            row("1", "had", "A", 3.80, "2026-06-11 20:00:00"),
        ]

        result = analyze_match_windows(match, sp_history)

        self.assertEqual(set(result["market_structures"]), {"open_to_latest", "last_24h", "last_6h"})
        self.assertNotIn("last_1h", result["llm_input"]["window_summaries"])

    def test_non_sp_confirmation_upgrades_priority(self):
        match = {
            "match_id": "1",
            "match_num": "周三001",
            "league_name": "世界杯",
            "match_time": "2026-06-11 22:00:00",
            "home_team_name": "法国",
            "away_team_name": "丹麦",
        }
        sp_history = [
            row("1", "had", "H", 2.10, "2026-06-11 10:00:00"),
            row("1", "had", "D", 3.20, "2026-06-11 10:00:00"),
            row("1", "had", "A", 3.10, "2026-06-11 10:00:00"),
            row("1", "had", "H", 1.85, "2026-06-11 20:00:00"),
            row("1", "had", "D", 3.30, "2026-06-11 20:00:00"),
            row("1", "had", "A", 3.80, "2026-06-11 20:00:00"),
        ]
        detail = {
            "matchResult": {
                "value": {
                    "home": {"statistics": {"teamShortName": "法国", "winGoalMatchCnt": 3, "drawMatchCnt": 1, "lossGoalMatchCnt": 1, "winProbability": "60%", "lossProbability": "20%", "goalCnt": 9, "lossGoalCnt": 4, "netGoal": 5}, "matchList": []},
                    "away": {"statistics": {"teamShortName": "丹麦", "winGoalMatchCnt": 1, "drawMatchCnt": 1, "lossGoalMatchCnt": 3, "winProbability": "20%", "lossProbability": "60%", "goalCnt": 4, "lossGoalCnt": 8, "netGoal": -4}, "matchList": []},
                }
            },
            "matchFeature": {"value": {"eachHomeAway": {}, "goalAvg": {"homeGoalAvgCnt": "1.8", "awayGoalAvgCnt": "0.9"}, "lossGoalAvg": {"homeLossGoalAvgCnt": "0.6", "awayLossGoalAvgCnt": "1.4"}}},
            "matchTables": {"value": {"homeTable": [{"teamShortName": "法国", "rank": "1"}], "awayTable": [{"teamShortName": "丹麦", "rank": "4"}]}},
        }

        result = analyze_match_windows(match, sp_history, detail_bundle=detail)

        self.assertEqual(result["sp_research_priority"], "D")
        self.assertEqual(result["final_research_priority"], "C")
        self.assertEqual(result["non_sp_blend_summary"]["reason"], "non_sp_confirms_sp")

    def test_non_sp_conflict_downgrades_priority(self):
        match = {
            "match_id": "1",
            "match_num": "周三001",
            "league_name": "世界杯",
            "match_time": "2026-06-11 22:00:00",
            "home_team_name": "法国",
            "away_team_name": "丹麦",
        }
        sp_history = [
            row("1", "had", "H", 2.10, "2026-06-11 10:00:00"),
            row("1", "had", "D", 3.20, "2026-06-11 10:00:00"),
            row("1", "had", "A", 3.10, "2026-06-11 10:00:00"),
            row("1", "had", "H", 1.85, "2026-06-11 20:00:00"),
            row("1", "had", "D", 3.30, "2026-06-11 20:00:00"),
            row("1", "had", "A", 3.80, "2026-06-11 20:00:00"),
            row("1", "hhad", "H", 2.40, "2026-06-11 10:00:00", goal_line="-1"),
            row("1", "hhad", "D", 3.30, "2026-06-11 10:00:00", goal_line="-1"),
            row("1", "hhad", "A", 2.60, "2026-06-11 10:00:00", goal_line="-1"),
            row("1", "hhad", "H", 1.95, "2026-06-11 20:00:00", goal_line="-1"),
            row("1", "hhad", "D", 3.50, "2026-06-11 20:00:00", goal_line="-1"),
            row("1", "hhad", "A", 3.20, "2026-06-11 20:00:00", goal_line="-1"),
            row("1", "ttg", "0", 10.0, "2026-06-11 10:00:00"),
            row("1", "ttg", "1", 5.0, "2026-06-11 10:00:00"),
            row("1", "ttg", "2", 3.5, "2026-06-11 10:00:00"),
            row("1", "ttg", "3", 3.8, "2026-06-11 10:00:00"),
            row("1", "ttg", "4", 6.0, "2026-06-11 10:00:00"),
            row("1", "ttg", "5", 10.0, "2026-06-11 10:00:00"),
            row("1", "ttg", "6", 18.0, "2026-06-11 10:00:00"),
            row("1", "ttg", "7", 30.0, "2026-06-11 10:00:00"),
            row("1", "ttg", "0", 6.0, "2026-06-11 20:00:00"),
            row("1", "ttg", "1", 3.5, "2026-06-11 20:00:00"),
            row("1", "ttg", "2", 3.0, "2026-06-11 20:00:00"),
            row("1", "ttg", "3", 4.5, "2026-06-11 20:00:00"),
            row("1", "ttg", "4", 7.0, "2026-06-11 20:00:00"),
            row("1", "ttg", "5", 12.0, "2026-06-11 20:00:00"),
            row("1", "ttg", "6", 20.0, "2026-06-11 20:00:00"),
            row("1", "ttg", "7", 35.0, "2026-06-11 20:00:00"),
        ]
        detail = {
            "matchResult": {
                "value": {
                    "home": {"statistics": {"teamShortName": "法国", "winGoalMatchCnt": 1, "drawMatchCnt": 1, "lossGoalMatchCnt": 3, "winProbability": "20%", "lossProbability": "60%", "goalCnt": 4, "lossGoalCnt": 8, "netGoal": -4}, "matchList": []},
                    "away": {"statistics": {"teamShortName": "丹麦", "winGoalMatchCnt": 4, "drawMatchCnt": 1, "lossGoalMatchCnt": 0, "winProbability": "80%", "lossProbability": "0%", "goalCnt": 11, "lossGoalCnt": 2, "netGoal": 9}, "matchList": []},
                }
            },
            "matchFeature": {"value": {"eachHomeAway": {}, "goalAvg": {"homeGoalAvgCnt": "0.9", "awayGoalAvgCnt": "2.1"}, "lossGoalAvg": {"homeLossGoalAvgCnt": "1.5", "awayLossGoalAvgCnt": "0.5"}}},
            "matchTables": {"value": {"homeTable": [{"teamShortName": "法国", "rank": "4"}], "awayTable": [{"teamShortName": "丹麦", "rank": "1"}]}},
            "injurySuspension": {"value": {"homeList": [{"playerName": "A"}, {"playerName": "B"}, {"playerName": "C"}], "awayList": []}},
        }

        result = analyze_match_windows(match, sp_history, detail_bundle=detail)

        self.assertEqual(result["sp_research_priority"], "C")
        self.assertEqual(result["final_research_priority"], "D")
        self.assertEqual(result["non_sp_blend_summary"]["reason"], "non_sp_conflicts_with_sp")


if __name__ == "__main__":
    unittest.main()
