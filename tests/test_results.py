import unittest

from src.parsers import parse_result_list


class ResultParserTest(unittest.TestCase):
    def test_parse_result_list_full_time_result(self):
        raw = {
            "success": True,
            "value": {
                "matchInfoList": [{
                    "subMatchList": [{
                        "matchId": 2040133,
                        "matchNumStr": "周六210",
                        "leagueId": "39",
                        "leagueAbbName": "国际赛",
                        "homeTeamId": "523",
                        "awayTeamId": "377",
                        "homeTeamAbbName": "美国",
                        "awayTeamAbbName": "德国",
                        "matchDate": "2026-06-07",
                        "matchTime": "02:30",
                        "matchStatus": "11",
                        "matchStatusName": "已完成",
                        "sectionsNo1": "1:1",
                        "sectionsNo999": "1:2",
                    }]
                }]
            },
        }

        result = parse_result_list(raw)[0]

        self.assertEqual(result["match_id"], "2040133")
        self.assertEqual(result["home_score_90"], 1)
        self.assertEqual(result["away_score_90"], 2)
        self.assertEqual(result["result_90"], "A")
        self.assertEqual(result["half_score"], "1:1")
        self.assertEqual(result["full_score_90"], "1:2")

    def test_parse_result_list_invalid_score_has_no_result(self):
        raw = {
            "value": {
                "matchInfoList": [{
                    "subMatchList": [{
                        "matchId": 1,
                        "sectionsNo999": "无效场次",
                    }]
                }]
            },
        }

        result = parse_result_list(raw)[0]

        self.assertIsNone(result["home_score_90"])
        self.assertIsNone(result["away_score_90"])
        self.assertIsNone(result["result_90"])


if __name__ == "__main__":
    unittest.main()
