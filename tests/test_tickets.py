import unittest

from src.tickets import (
    HadSelection,
    TicketValidationError,
    build_ticket,
    make_had_selection,
    make_had_selection_from_sp_records,
    quote_ticket_with_latest_sp,
)


class HadTicketRulesTest(unittest.TestCase):
    def test_single_requires_single_flag(self):
        ticket = build_ticket(
            [make_had_selection("1001", ["H"], is_single=True)],
            "single",
        )

        self.assertEqual(ticket.unit_count, 1)
        self.assertEqual(ticket.amount, 2)

    def test_single_rejects_match_without_single_support(self):
        with self.assertRaisesRegex(TicketValidationError, "does not support single"):
            build_ticket(
                [make_had_selection("1001", ["H"], is_single=False)],
                "single",
            )

    def test_parlay_accepts_distinct_had_matches(self):
        ticket = build_ticket(
            [
                make_had_selection("1001", ["H", "D"]),
                make_had_selection("1002", ["A"]),
            ],
            "2x1",
            multiplier=3,
        )

        self.assertEqual(ticket.unit_count, 2)
        self.assertEqual(ticket.amount, 12)

    def test_parlay_rejects_duplicate_match(self):
        with self.assertRaisesRegex(TicketValidationError, "same match"):
            build_ticket(
                [
                    make_had_selection("1001", ["H"]),
                    make_had_selection("1001", ["A"]),
                ],
                "2x1",
            )

    def test_parlay_rejects_pass_type_count_mismatch(self):
        with self.assertRaisesRegex(TicketValidationError, "count must equal"):
            build_ticket(
                [
                    make_had_selection("1001", ["H"]),
                    make_had_selection("1002", ["A"]),
                ],
                "3x1",
            )

    def test_rejects_non_had_play_type(self):
        with self.assertRaisesRegex(TicketValidationError, "only had"):
            build_ticket(
                [HadSelection("1001", ("H",), is_single=True, play_type="hhad")],
                "single",
            )

    def test_rejects_non_had_option(self):
        with self.assertRaisesRegex(TicketValidationError, "invalid had option"):
            build_ticket(
                [make_had_selection("1001", ["H", "7"], is_single=True)],
                "single",
            )

    def test_rejects_not_in_sale_status(self):
        with self.assertRaisesRegex(TicketValidationError, "not currently in sale"):
            build_ticket(
                [make_had_selection("1001", ["H"], is_single=True, match_status="3")],
                "single",
            )

    def test_builds_selection_from_sp_records(self):
        selection = make_had_selection_from_sp_records(
            "1001",
            ["H", "D"],
            [
                {"match_id": "1001", "play_type": "had", "option_code": "H", "is_single": "1"},
                {"match_id": "1001", "play_type": "had", "option_code": "D", "is_single": "1"},
                {"match_id": "1001", "play_type": "hhad", "option_code": "H", "is_single": "0"},
            ],
        )

        self.assertTrue(selection.is_single)
        self.assertEqual(selection.option_codes, ("H", "D"))

    def test_build_selection_from_sp_records_requires_selected_options(self):
        with self.assertRaisesRegex(TicketValidationError, "missing had SP records"):
            make_had_selection_from_sp_records(
                "1001",
                ["H", "A"],
                [{"match_id": "1001", "play_type": "had", "option_code": "H", "is_single": "1"}],
            )

    def test_quotes_ticket_with_latest_sp(self):
        ticket = build_ticket(
            [
                make_had_selection("1001", ["H", "D"]),
                make_had_selection("1002", ["A"]),
            ],
            "2x1",
            multiplier=2,
        )

        quote = quote_ticket_with_latest_sp(ticket, [
            {"match_id": "1001", "play_type": "had", "option_code": "H", "sp_value": 2.0, "snapshot_time": "2026-06-11 10:00:00"},
            {"match_id": "1001", "play_type": "had", "option_code": "H", "sp_value": 1.8, "snapshot_time": "2026-06-11 10:10:00"},
            {"match_id": "1001", "play_type": "had", "option_code": "D", "sp_value": 3.1, "snapshot_time": "2026-06-11 10:10:00"},
            {"match_id": "1002", "play_type": "had", "option_code": "A", "sp_value": 2.2, "snapshot_time": "2026-06-11 10:10:00"},
        ])

        self.assertEqual(ticket.amount, 8)
        self.assertEqual(len(quote.combinations), 2)
        self.assertEqual(quote.min_potential_payout, 15.84)
        self.assertEqual(quote.max_potential_payout, 27.28)
        self.assertEqual(quote.option_sp[("1001", "H")], 1.8)

    def test_quote_requires_latest_sp_for_each_selected_option(self):
        ticket = build_ticket(
            [make_had_selection("1001", ["H"], is_single=True)],
            "single",
        )

        with self.assertRaisesRegex(TicketValidationError, "missing latest HAD SP"):
            quote_ticket_with_latest_sp(ticket, [])


if __name__ == "__main__":
    unittest.main()
