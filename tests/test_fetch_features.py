"""Tests for fetch_sporttery enhanced features:
- Schema validation
- SP snapshot content-hash dedup
- Raw snapshot response_version tracking
- API error logging
"""

import tempfile
import unittest
import os
from pathlib import Path

from src import db as db_mod
from src.parsers import validate_fixed_bonus_schema, validate_match_list_schema


# ── Schema validation ─────────────────────────────────────────────────────────

class MatchListSchemaValidationTest(unittest.TestCase):
    def test_valid_response_returns_no_warnings(self):
        raw = {
            "success": True,
            "value": {
                "matchInfoList": [{
                    "subMatchList": [{
                        "matchId": 2040162,
                        "matchDate": "2026-06-10",
                        "matchTime": "20:00",
                        "homeTeamAbbName": "主队",
                        "awayTeamAbbName": "客队",
                    }]
                }]
            },
        }
        warnings = validate_match_list_schema(raw)
        self.assertEqual(warnings, [])

    def test_missing_value_key_returns_warning(self):
        raw = {"success": True}
        warnings = validate_match_list_schema(raw)
        self.assertTrue(any("value" in w for w in warnings))

    def test_missing_matchInfoList_returns_warning(self):
        raw = {"value": {}}
        warnings = validate_match_list_schema(raw)
        self.assertTrue(any("matchInfoList" in w for w in warnings))

    def test_missing_match_fields_returns_warning(self):
        raw = {
            "value": {
                "matchInfoList": [{
                    "subMatchList": [{"matchId": 1}]  # missing other fields
                }]
            },
        }
        warnings = validate_match_list_schema(raw)
        self.assertTrue(len(warnings) > 0)


class FixedBonusSchemaValidationTest(unittest.TestCase):
    def test_valid_response_returns_no_warnings(self):
        raw = {
            "success": True,
            "value": {
                "oddsHistory": {
                    "hadList": [],
                    "hhadList": [],
                    "ttgList": [],
                }
            },
        }
        warnings = validate_fixed_bonus_schema(raw, "2040162")
        self.assertEqual(warnings, [])

    def test_missing_value_key_returns_warning(self):
        raw = {"success": True}
        warnings = validate_fixed_bonus_schema(raw, "2040162")
        self.assertTrue(any("value" in w for w in warnings))

    def test_missing_oddsHistory_returns_warning(self):
        raw = {"value": {}}
        warnings = validate_fixed_bonus_schema(raw, "2040162")
        self.assertTrue(any("oddsHistory" in w for w in warnings))


# ── DB: in-memory integration tests ──────────────────────────────────────────

class _DBTestBase(unittest.TestCase):
    """Use a temp-file SQLite for isolation."""

    def setUp(self):
        self._orig_path = db_mod._SQLITE_PATH
        self._orig_backend = os.environ.get("SPORTTERY_DB_BACKEND")
        self._tmpdir = tempfile.mkdtemp()
        os.environ["SPORTTERY_DB_BACKEND"] = "sqlite"
        db_mod._SQLITE_PATH = Path(self._tmpdir) / "test.db"
        self.conn = db_mod.get_connection()
        db_mod.ensure_tables(self.conn)

    def tearDown(self):
        self.conn.close()
        db_mod._SQLITE_PATH = self._orig_path
        if self._orig_backend is None:
            os.environ.pop("SPORTTERY_DB_BACKEND", None)
        else:
            os.environ["SPORTTERY_DB_BACKEND"] = self._orig_backend


class RawSnapshotVersionTest(_DBTestBase):
    def test_first_insert_has_version_1(self):
        ok = db_mod.save_raw_snapshot(self.conn, "test", "http://x", {"a": 1})
        self.assertTrue(ok)
        row = self.conn.execute(
            "SELECT response_version FROM sporttery_raw_snapshot"
        ).fetchone()
        self.assertEqual(row["response_version"], 1)

    def test_different_content_increments_version(self):
        db_mod.save_raw_snapshot(self.conn, "test", "http://x", {"v": 1}, match_id="100")
        db_mod.save_raw_snapshot(self.conn, "test", "http://x", {"v": 2}, match_id="100")
        rows = self.conn.execute(
            "SELECT response_version FROM sporttery_raw_snapshot ORDER BY response_version"
        ).fetchall()
        self.assertEqual([r["response_version"] for r in rows], [1, 2])

    def test_duplicate_content_returns_false_and_keeps_version(self):
        db_mod.save_raw_snapshot(self.conn, "test", "http://x", {"same": True})
        ok2 = db_mod.save_raw_snapshot(self.conn, "test", "http://x", {"same": True})
        self.assertFalse(ok2)
        count = self.conn.execute("SELECT COUNT(*) FROM sporttery_raw_snapshot").fetchone()[0]
        self.assertEqual(count, 1)

    def test_different_sources_track_versions_independently(self):
        db_mod.save_raw_snapshot(self.conn, "srcA", "http://a", {"x": 1}, match_id="M1")
        db_mod.save_raw_snapshot(self.conn, "srcB", "http://b", {"y": 1}, match_id="M1")
        rows = self.conn.execute(
            "SELECT source_name, response_version FROM sporttery_raw_snapshot ORDER BY source_name"
        ).fetchall()
        self.assertEqual(rows[0]["response_version"], 1)
        self.assertEqual(rows[1]["response_version"], 1)


class SpSnapshotDedupTest(_DBTestBase):
    def _record(self, sp=1.8, goal_line=None, snapshot_time="2026-06-10 12:00:00"):
        return {
            "match_id": "2040162",
            "snapshot_time": snapshot_time,
            "play_type": "had",
            "option_code": "H",
            "option_name": "主胜",
            "sp_value": sp,
            "goal_line": goal_line,
            "is_single": 0,
        }

    def test_first_insert_counted(self):
        n = db_mod.save_sp_snapshots(self.conn, [self._record()])
        self.assertEqual(n, 1)

    def test_same_data_skipped(self):
        db_mod.save_sp_snapshots(self.conn, [self._record()])
        n = db_mod.save_sp_snapshots(self.conn, [self._record()])
        self.assertEqual(n, 0)

    def test_different_sp_value_inserted(self):
        db_mod.save_sp_snapshots(self.conn, [self._record(sp=1.8)])
        n = db_mod.save_sp_snapshots(self.conn, [self._record(sp=1.7)])
        self.assertEqual(n, 1)

    def test_different_snapshot_time_inserted(self):
        db_mod.save_sp_snapshots(self.conn, [self._record(snapshot_time="T1")])
        n = db_mod.save_sp_snapshots(self.conn, [self._record(snapshot_time="T2")])
        self.assertEqual(n, 1)

    def test_mixed_records_partial_dedup(self):
        records = [
            self._record(sp=1.8, snapshot_time="T1"),
            self._record(sp=1.8, snapshot_time="T2"),
        ]
        n1 = db_mod.save_sp_snapshots(self.conn, records)
        self.assertEqual(n1, 2)

        # Same first (dup), different second (new)
        records2 = [
            self._record(sp=1.8, snapshot_time="T1"),  # dup
            self._record(sp=1.85, snapshot_time="T2"),  # changed sp
        ]
        n2 = db_mod.save_sp_snapshots(self.conn, records2)
        self.assertEqual(n2, 1)


class ApiErrorLogTest(_DBTestBase):
    def test_save_and_query_error(self):
        db_mod.save_api_error(
            self.conn, "fixedBonus", "timeout",
            match_id="2040162", retry_count=3,
        )
        row = self.conn.execute("SELECT * FROM sporttery_api_error").fetchone()
        self.assertEqual(row["endpoint"], "fixedBonus")
        self.assertEqual(row["error_message"], "timeout")
        self.assertEqual(row["match_id"], "2040162")
        self.assertEqual(row["retry_count"], 3)

    def test_error_without_optional_fields(self):
        db_mod.save_api_error(self.conn, "matchList", "connection refused")
        row = self.conn.execute("SELECT * FROM sporttery_api_error").fetchone()
        self.assertIsNone(row["match_id"])
        self.assertIsNone(row["http_status"])
        self.assertEqual(row["retry_count"], 0)


class BettingLedgerTest(_DBTestBase):
    def test_save_manual_betting_ticket_with_selections(self):
        db_mod.save_sp_snapshots(self.conn, [{
            "match_id": "2040162",
            "snapshot_time": "2026-06-11 12:25:32",
            "play_type": "had",
            "option_code": "H",
            "option_name": "主胜",
            "sp_value": 1.26,
            "is_single": 1,
        }])
        sp_row = self.conn.execute(
            "SELECT id FROM sporttery_sp_snapshot WHERE match_id = ?",
            ("2040162",),
        ).fetchone()

        ticket_id = db_mod.save_betting_ticket(self.conn, {
            "bet_group": "plan-1",
            "source_type": "SYSTEM",
            "ticket_label": "墨西哥胜 × 美国胜",
            "pass_type": "2x1",
            "stake_amount": 20,
            "unit_stake": 2,
            "multiplier": 10,
            "expected_min_payout": 45.36,
            "expected_max_payout": 45.36,
            "placed_at": "2026-06-11 15:00:00",
            "selections": [
                {
                    "match_id": "2040162",
                    "match_num": "周四001",
                    "play_type": "had",
                    "option_code": "H",
                    "option_name": "主胜",
                    "selected_sp": 1.26,
                    "sp_snapshot_time": "2026-06-11 12:25:32",
                },
                {
                    "match_id": "2040165",
                    "match_num": "周五004",
                    "play_type": "had",
                    "option_code": "H",
                    "option_name": "主胜",
                    "selected_sp": 1.8,
                    "sp_snapshot_time": "2026-06-11 10:26:17",
                },
            ],
        })

        self.assertGreater(ticket_id, 0)
        tickets = db_mod.fetch_betting_tickets(self.conn, "plan-1")
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0]["ticket_status"], "pending")
        self.assertEqual(tickets[0]["expected_max_payout"], 45.36)
        self.assertEqual(tickets[0]["source_type"], "SYSTEM")

        selection_count = self.conn.execute(
            "SELECT COUNT(*) FROM betting_ticket_selection WHERE ticket_id = ?",
            (ticket_id,),
        ).fetchone()[0]
        self.assertEqual(selection_count, 2)

        linked_selection = self.conn.execute(
            """
            SELECT sp_snapshot_id
            FROM betting_ticket_selection
            WHERE ticket_id = ? AND match_id = ? AND option_code = ?
            """,
            (ticket_id, "2040162", "H"),
        ).fetchone()
        self.assertEqual(linked_selection["sp_snapshot_id"], sp_row["id"])

    def test_existing_rows_default_source_type_to_unknown(self):
        self.conn.execute(
            """
            INSERT INTO betting_ticket
                (bet_group, ticket_label, pass_type, stake_amount, placed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("legacy", "老票", "single", 2, "2026-06-11 15:00:00"),
        )
        self.conn.commit()

        tickets = db_mod.fetch_betting_tickets(self.conn, "legacy")
        self.assertEqual(tickets[0]["source_type"], "UNKNOWN")

    def test_save_ticket_rejects_unknown_source_type(self):
        with self.assertRaises(ValueError):
            db_mod.save_betting_ticket(self.conn, {
                "bet_group": "plan-1",
                "source_type": "mystery",
                "ticket_label": "非法来源",
                "pass_type": "single",
                "stake_amount": 2,
                "selections": [{
                    "match_id": "1",
                    "play_type": "had",
                    "option_code": "H",
                    "selected_sp": 1.5,
                }],
            })


if __name__ == "__main__":
    unittest.main()
