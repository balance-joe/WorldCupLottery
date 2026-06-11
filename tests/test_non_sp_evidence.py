import unittest

from src.non_sp_evidence import build_non_sp_evidence


class NonSpEvidenceTest(unittest.TestCase):
    def test_builds_compact_evidence(self):
        detail = {
            "matchResult": {
                "value": {
                    "home": {
                        "statistics": {
                            "teamShortName": "法国",
                            "winGoalMatchCnt": 3,
                            "drawMatchCnt": 1,
                            "lossGoalMatchCnt": 1,
                            "winProbability": "60%",
                            "lossProbability": "20%",
                            "goalCnt": 9,
                            "lossGoalCnt": 4,
                            "netGoal": 5,
                        },
                        "matchList": [
                            {
                                "matchDate": "2026-06-01",
                                "homeTeamShortName": "法国",
                                "awayTeamShortName": "德国",
                                "homeTeamFullCourtGoalCnt": "2",
                                "awayTeamFullCourtGoalCnt": "1",
                                "teamMatchResult": "W",
                                "tournamentShortName": "国际赛",
                            }
                        ],
                    },
                    "away": {
                        "statistics": {
                            "teamShortName": "丹麦",
                            "winGoalMatchCnt": 1,
                            "drawMatchCnt": 1,
                            "lossGoalMatchCnt": 3,
                            "winProbability": "20%",
                            "lossProbability": "60%",
                            "goalCnt": 4,
                            "lossGoalCnt": 8,
                            "netGoal": -4,
                        },
                        "matchList": [],
                    },
                }
            },
            "matchFeature": {
                "value": {
                    "eachHomeAway": {
                        "homeWinGoalMatchCnt": 6,
                        "homeDrawMatchCnt": 2,
                        "homeLossGoalMatchCnt": 2,
                        "awayWinGoalMatchCnt": 2,
                        "awayDrawMatchCnt": 3,
                        "awayLossGoalMatchCnt": 5,
                    },
                    "goalAvg": {"homeGoalAvgCnt": "1.8", "awayGoalAvgCnt": "0.9"},
                    "lossGoalAvg": {"homeLossGoalAvgCnt": "0.6", "awayLossGoalAvgCnt": "1.4"},
                }
            },
            "resultHistory": {
                "value": {
                    "statistics": {
                        "totalLegCnt": 4,
                        "winProbability": "50%",
                        "drawProbability": "25%",
                        "lossProbability": "25%",
                    },
                    "matchList": [
                        {
                            "matchDate": "2024-01-01",
                            "tournamentShortName": "友谊赛",
                            "homeTeamShortName": "法国",
                            "awayTeamShortName": "丹麦",
                            "fullCourtGoal": "2:0",
                            "winningTeam": "home",
                        }
                    ],
                }
            },
            "sameOdds": {"value": {"totalLegCnt": 7, "winProbability": "57%"}},
            "matchTables": {
                "value": {
                    "homeTable": [{"teamShortName": "法国", "rank": "1", "integral": "9"}],
                    "awayTable": [{"teamShortName": "丹麦", "rank": "3", "integral": "4"}],
                }
            },
            "injurySuspension": {
                "value": {
                    "homeList": [{"playerName": "主队前锋", "reason": "injury", "position": "FW"}],
                    "awayList": [{"playerName": "客队后卫", "reason": "suspension", "position": "DF"}],
                }
            },
            "futureMatches": {
                "value": {
                    "homeMatches": [{"matchDate": "2026-06-20", "againstTeamName": "西班牙", "tournamentShortName": "世界杯"}],
                    "awayMatches": [{"matchDate": "2026-06-21", "againstTeamName": "英格兰", "tournamentShortName": "世界杯"}],
                }
            },
        }

        evidence = build_non_sp_evidence(detail)

        self.assertEqual(evidence["team_form"]["home"]["team"], "法国")
        self.assertEqual(evidence["historical"]["h2h_count"], 4)
        self.assertEqual(evidence["tables"]["home_rank"]["rank"], 1)
        self.assertEqual(evidence["injuries"]["home_count"], 1)
        self.assertEqual(evidence["future_matches"]["away_next"][0]["opponent"], "英格兰")
        self.assertTrue(evidence["key_signals"])


if __name__ == "__main__":
    unittest.main()
