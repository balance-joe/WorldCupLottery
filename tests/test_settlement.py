import tempfile
import unittest
from pathlib import Path

from src import db as db_mod
from src.settlement import evaluate_leg, settle_pending_tickets


class SettlementRulesTest(unittest.TestCase):
    def test_had_result(self):
        status, actual = evaluate_leg(
            {"play_type": "had", "option_code": "H"},
            {"home_score_90": 2, "away_score_90": 1},
        )
        self.assertEqual((status, actual), ("hit", "H"))

    def test_hhad_result_uses_home_goal_line(self):
        status, actual = evaluate_leg(
            {"play_type": "hhad", "option_code": "D", "goal_line": "-1"},
            {"home_score_90": 2, "away_score_90": 1},
        )
        self.assertEqual((status, actual), ("hit", "D"))

    def test_ttg_result_uses_seven_plus_bucket(self):
        status, actual = evaluate_leg(
            {"play_type": "ttg", "option_code": "7"},
            {"home_score_90": 4, "away_score_90": 3},
        )
        self.assertEqual((status, actual), ("hit", "7"))

    def test_pending_without_result(self):
        status, actual = evaluate_leg(
            {"play_type": "ttg", "option_code": "3"},
            {"home_score_90": None, "away_score_90": None},
        )
        self.assertEqual((status, actual), ("pending", ""))

    def test_crs_hit(self):
        status, actual = evaluate_leg(
            {"play_type": "crs", "option_code": "s02s01"},
            {"home_score_90": 2, "away_score_90": 1},
        )
        self.assertEqual((status, actual), ("hit", "s02s01"))

    def test_crs_miss(self):
        status, actual = evaluate_leg(
            {"play_type": "crs", "option_code": "s01s00"},
            {"home_score_90": 2, "away_score_90": 1},
        )
        self.assertEqual(status, "miss")
        self.assertEqual(actual, "s02s01")

    def test_hafu_hit(self):
        status, actual = evaluate_leg(
            {"play_type": "hafu", "option_code": "hh"},
            {"home_score_90": 2, "away_score_90": 1, "half_score": "1:0"},
        )
        self.assertEqual((status, actual), ("hit", "hh"))

    def test_hafu_miss(self):
        status, actual = evaluate_leg(
            {"play_type": "hafu", "option_code": "dh"},
            {"home_score_90": 2, "away_score_90": 1, "half_score": "1:0"},
        )
        self.assertEqual(status, "miss")
        self.assertEqual(actual, "hh")

    def test_hafu_unsupported_without_half_score(self):
        status, actual = evaluate_leg(
            {"play_type": "hafu", "option_code": "hh"},
            {"home_score_90": 2, "away_score_90": 1, "half_score": None},
        )
        self.assertEqual((status, actual), ("unsupported", "missing_half_score"))


class _DBTestBase(unittest.TestCase):
    def setUp(self):
        self._orig_path = db_mod._SQLITE_PATH
        self._tmpdir = tempfile.mkdtemp()
        db_mod._SQLITE_PATH = Path(self._tmpdir) / "test.db"
        self.conn = db_mod.get_connection()
        db_mod.ensure_tables(self.conn)

    def tearDown(self):
        self.conn.close()
        db_mod._SQLITE_PATH = self._orig_path


class SettlementIntegrationTest(_DBTestBase):
    def test_settles_winning_single_ticket(self):
        db_mod.save_match_result(self.conn, {
            "match_id": "2040163",
            "home_team_name": "韩国",
            "away_team_name": "捷克",
            "home_score_90": 2,
            "away_score_90": 1,
            "result_90": "H",
        })
        ticket_id = db_mod.save_betting_ticket(self.conn, {
            "bet_group": "plan-1",
            "ticket_label": "总进球3球",
            "pass_type": "single",
            "stake_amount": 10,
            "unit_stake": 2,
            "multiplier": 5,
            "selections": [{
                "match_id": "2040163",
                "play_type": "ttg",
                "option_code": "3",
                "option_name": "3球",
                "selected_sp": 3.75,
            }],
        })

        settlements = settle_pending_tickets(self.conn, bet_group="plan-1")

        self.assertEqual(len(settlements), 1)
        self.assertEqual(settlements[0].ticket_id, ticket_id)
        self.assertEqual(settlements[0].status, "won")
        self.assertEqual(settlements[0].actual_payout, 37.5)
        self.assertEqual(settlements[0].profit_loss, 27.5)
        row = self.conn.execute(
            "SELECT ticket_status, actual_payout, profit_loss FROM betting_ticket WHERE id = ?",
            (ticket_id,),
        ).fetchone()
        self.assertEqual(row["ticket_status"], "won")
        self.assertEqual(row["actual_payout"], 37.5)

    def test_settles_losing_parlay_when_one_leg_misses(self):
        db_mod.save_match_result(self.conn, {
            "match_id": "1",
            "home_score_90": 1,
            "away_score_90": 0,
            "result_90": "H",
        })
        db_mod.save_match_result(self.conn, {
            "match_id": "2",
            "home_score_90": 0,
            "away_score_90": 0,
            "result_90": "D",
        })
        ticket_id = db_mod.save_betting_ticket(self.conn, {
            "bet_group": "plan-2",
            "ticket_label": "主胜串关",
            "pass_type": "2x1",
            "stake_amount": 20,
            "unit_stake": 2,
            "multiplier": 10,
            "selections": [
                {"match_id": "1", "play_type": "had", "option_code": "H", "selected_sp": 1.5},
                {"match_id": "2", "play_type": "had", "option_code": "H", "selected_sp": 2.0},
            ],
        })

        settlements = settle_pending_tickets(self.conn, bet_group="plan-2")

        self.assertEqual(len(settlements), 1)
        self.assertEqual(settlements[0].ticket_id, ticket_id)
        self.assertEqual(settlements[0].status, "lost")
        self.assertEqual(settlements[0].actual_payout, 0.0)
        self.assertEqual(settlements[0].profit_loss, -20.0)

    def test_does_not_settle_until_all_legs_have_results(self):
        db_mod.save_match_result(self.conn, {
            "match_id": "1",
            "home_score_90": 1,
            "away_score_90": 0,
            "result_90": "H",
        })
        db_mod.save_betting_ticket(self.conn, {
            "bet_group": "plan-3",
            "ticket_label": "等待另一场",
            "pass_type": "2x1",
            "stake_amount": 20,
            "unit_stake": 2,
            "multiplier": 10,
            "selections": [
                {"match_id": "1", "play_type": "had", "option_code": "H", "selected_sp": 1.5},
                {"match_id": "2", "play_type": "had", "option_code": "H", "selected_sp": 2.0},
            ],
        })

        settlements = settle_pending_tickets(self.conn, bet_group="plan-3")

        self.assertEqual(settlements, [])


if __name__ == "__main__":
    unittest.main()
