"""回测模块单元测试。"""

from __future__ import annotations

import unittest

from src.backtest.settle import evaluate_bet, settle_bet, get_sp_for_option
from src.backtest.strategies import STRATEGY_DEFS, match_conditions, pick_option
from src.backtest.types import BetResult, StrategyResult, BacktestReport


class TestEvaluateBet(unittest.TestCase):
    """结算判定测试。"""

    def test_had_home_win(self):
        match = {"home_score_90": 2, "away_score_90": 1}
        hit, actual = evaluate_bet("had", "H", match)
        self.assertTrue(hit)
        self.assertEqual(actual, "H")

    def test_had_draw(self):
        match = {"home_score_90": 1, "away_score_90": 1}
        hit, actual = evaluate_bet("had", "D", match)
        self.assertTrue(hit)
        self.assertEqual(actual, "D")

    def test_had_away_win(self):
        match = {"home_score_90": 0, "away_score_90": 3}
        hit, actual = evaluate_bet("had", "H", match)
        self.assertFalse(hit)
        self.assertEqual(actual, "A")

    def test_hhad_with_goal_line(self):
        match = {"home_score_90": 2, "away_score_90": 1, "goal_line": "-1"}
        # 2 + (-1) = 1, away=1, 平局
        hit, actual = evaluate_bet("hhad", "D", match)
        self.assertTrue(hit)
        self.assertEqual(actual, "D")

    def test_hhad_no_goal_line(self):
        match = {"home_score_90": 2, "away_score_90": 1}
        hit, actual = evaluate_bet("hhad", "H", match)
        self.assertIsNone(hit)
        self.assertEqual(actual, "no_goal_line")

    def test_ttg(self):
        match = {"home_score_90": 2, "away_score_92": 1, "away_score_90": 1}
        hit, actual = evaluate_bet("ttg", "3", match)
        self.assertTrue(hit)
        self.assertEqual(actual, "3")

    def test_ttg_high(self):
        match = {"home_score_90": 4, "away_score_90": 3}
        hit, actual = evaluate_bet("ttg", "7", match)
        self.assertTrue(hit)
        self.assertEqual(actual, "7")

    def test_crs_hit(self):
        match = {"home_score_90": 2, "away_score_90": 1}
        hit, actual = evaluate_bet("crs", "s02s01", match)
        self.assertTrue(hit)
        self.assertEqual(actual, "s02s01")

    def test_crs_miss(self):
        match = {"home_score_90": 3, "away_score_90": 0}
        hit, actual = evaluate_bet("crs", "s02s01", match)
        self.assertFalse(hit)
        self.assertEqual(actual, "s03s00")

    def test_hafu_hit(self):
        match = {"home_score_90": 2, "away_score_90": 1, "half_score": "1:0"}
        hit, actual = evaluate_bet("hafu", "hh", match)
        self.assertTrue(hit)
        self.assertEqual(actual, "hh")

    def test_hafu_miss(self):
        match = {"home_score_90": 2, "away_score_92": 1, "away_score_90": 1, "half_score": "0:1"}
        hit, actual = evaluate_bet("hafu", "hh", match)
        self.assertFalse(hit)
        self.assertEqual(actual, "ah")

    def test_no_result(self):
        match = {"home_score_90": None, "away_score_90": None}
        hit, actual = evaluate_bet("had", "H", match)
        self.assertIsNone(hit)
        self.assertEqual(actual, "no_result")


class TestSettleBet(unittest.TestCase):
    """settle_bet 测试。"""

    def test_hit_with_sp(self):
        match = {
            "match_id": "100",
            "home_team_name": "A", "away_team_name": "B",
            "home_score_90": 2, "away_score_90": 1,
        }
        result = settle_bet("had", "H", match, sp_value=1.85, stake=10)
        self.assertTrue(result.hit)
        self.assertEqual(result.payout, 18.5)
        self.assertEqual(result.stake, 10)

    def test_miss(self):
        match = {
            "match_id": "100",
            "home_team_name": "A", "away_team_name": "B",
            "home_score_90": 0, "away_score_90": 1,
        }
        result = settle_bet("had", "H", match, sp_value=1.85, stake=10)
        self.assertFalse(result.hit)
        self.assertEqual(result.payout, 0.0)


class TestMatchConditions(unittest.TestCase):
    """策略条件匹配测试。"""

    def _signals(self, **overrides):
        base = {
            "had_bet": "H",
            "had_bet_sp": 1.50,
            "had_confidence": "medium",
            "hhad_confirms_had": True,
            "ttg_bet": "3",
            "ttg_confidence": "high",
            "crs_top1": "s02s01",
            "hafu_top1": "hh",
            "expression": "home_big_win_supported",
            "priority": "A",
            "consistency": "strong",
            "gate_allowed": True,
            "allowed_plays": ("had", "hhad", "ttg", "crs"),
            "gate_reasons": (),
        }
        base.update(overrides)
        return base

    def test_a_had_passes(self):
        sig = self._signals()
        self.assertTrue(match_conditions(STRATEGY_DEFS["A-HAD"], sig))

    def test_a_had_blocked_by_priority(self):
        sig = self._signals(priority="C")
        self.assertFalse(match_conditions(STRATEGY_DEFS["A-HAD"], sig))

    def test_ab_had_passes_b(self):
        sig = self._signals(priority="B")
        self.assertTrue(match_conditions(STRATEGY_DEFS["AB-HAD"], sig))

    def test_triple_confirm_passes(self):
        sig = self._signals(expression="home_big_win_supported")
        self.assertTrue(match_conditions(STRATEGY_DEFS["triple-confirm"], sig))

    def test_triple_confirm_blocked_by_expression(self):
        sig = self._signals(expression="mixed_or_noisy")
        self.assertFalse(match_conditions(STRATEGY_DEFS["triple-confirm"], sig))

    def test_low_sp_high_conf_passes(self):
        sig = self._signals(had_bet_sp=1.45, had_confidence="high")
        self.assertTrue(match_conditions(STRATEGY_DEFS["low-sp-high-conf"], sig))

    def test_low_sp_high_conf_blocked_by_high_sp(self):
        sig = self._signals(had_bet_sp=1.80, had_confidence="high")
        self.assertFalse(match_conditions(STRATEGY_DEFS["low-sp-high-conf"], sig))

    def test_mid_sp_confirm_passes(self):
        sig = self._signals(had_bet_sp=2.0, hhad_confirms_had=True)
        self.assertTrue(match_conditions(STRATEGY_DEFS["mid-sp-confirm"], sig))

    def test_mid_sp_confirm_blocked_no_hhad(self):
        sig = self._signals(had_bet_sp=2.0, hhad_confirms_had=False)
        self.assertFalse(match_conditions(STRATEGY_DEFS["mid-sp-confirm"], sig))

    def test_crs_top1_passes(self):
        sig = self._signals(crs_top1="s02s01")
        self.assertTrue(match_conditions(STRATEGY_DEFS["CRS-top1"], sig))

    def test_crs_top1_blocked_null(self):
        sig = self._signals(crs_top1=None)
        self.assertFalse(match_conditions(STRATEGY_DEFS["CRS-top1"], sig))

    def test_gate_blocked(self):
        sig = self._signals(gate_allowed=False)
        self.assertFalse(match_conditions(STRATEGY_DEFS["A-HAD"], sig))

    def test_play_not_in_allowed(self):
        sig = self._signals(allowed_plays=("ttg", "crs"))
        self.assertFalse(match_conditions(STRATEGY_DEFS["A-HAD"], sig))


class TestPickOption(unittest.TestCase):
    """pick_option 测试。"""

    def test_had_first(self):
        sig = {"had_bet": "H"}
        self.assertEqual(pick_option({"pick": "had_first"}, sig), "H")

    def test_ttg_first(self):
        sig = {"ttg_bet": "3"}
        self.assertEqual(pick_option({"pick": "ttg_first"}, sig), "3")

    def test_crs_top1(self):
        sig = {"crs_top1": "s02s01"}
        self.assertEqual(pick_option({"pick": "crs_top1"}, sig), "s02s01")

    def test_hafu_top1(self):
        sig = {"hafu_top1": "hh"}
        self.assertEqual(pick_option({"pick": "hafu_top1"}, sig), "hh")

    def test_unknown_rule(self):
        sig = {"had_bet": "H"}
        self.assertIsNone(pick_option({"pick": "unknown"}, sig))


class TestTypes(unittest.TestCase):
    """数据类型测试。"""

    def test_bet_result_to_dict(self):
        r = BetResult(
            match_id="1", match_info="A vs B", score="2:1",
            play_type="had", bet_option="H", sp_value=1.85,
            hit=True, actual_result="H", stake=10, payout=18.5,
        )
        d = r.to_dict()
        self.assertEqual(d["match_id"], "1")
        self.assertTrue(d["hit"])
        self.assertEqual(d["payout"], 18.5)

    def test_strategy_result_to_dict(self):
        r = StrategyResult(
            strategy_name="test", strategy_desc="desc", play_type="had",
            total_bets=5, wins=3, losses=2, hit_rate=0.6,
            total_stake=50, total_payout=60, profit_loss=10, roi=0.2,
            bets=(),
        )
        d = r.to_dict()
        self.assertEqual(d["strategy_name"], "test")
        self.assertEqual(d["bets"], [])

    def test_backtest_report_to_dict(self):
        r = BacktestReport(match_count=10, strategies=(), computed_at="2025-01-01")
        d = r.to_dict()
        self.assertEqual(d["match_count"], 10)


class TestGetSpForOption(unittest.TestCase):
    """get_sp_for_option 测试。"""

    def test_found(self):
        sp_history = [
            {"match_id": "1", "play_type": "had", "option_code": "H", "sp_value": 1.85, "snapshot_time": "2025-01-01 10:00:00"},
            {"match_id": "1", "play_type": "had", "option_code": "D", "sp_value": 3.20, "snapshot_time": "2025-01-01 10:00:00"},
        ]
        sp = get_sp_for_option("had", "H", sp_history, "1")
        self.assertEqual(sp, 1.85)

    def test_not_found(self):
        sp_history = [
            {"match_id": "1", "play_type": "had", "option_code": "H", "sp_value": 1.85, "snapshot_time": "2025-01-01 10:00:00"},
        ]
        sp = get_sp_for_option("had", "A", sp_history, "1")
        self.assertIsNone(sp)

    def test_empty_history(self):
        sp = get_sp_for_option("had", "H", [], "1")
        self.assertIsNone(sp)


if __name__ == "__main__":
    unittest.main()
