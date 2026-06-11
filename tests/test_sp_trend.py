import unittest

from src.sp_trend import analyze_play_trend


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


class SpTrendTest(unittest.TestCase):
    def test_normalized_weights_sum_to_one(self):
        records = [
            row("1", "had", "H", 2.0, "2026-06-11 10:00:00"),
            row("1", "had", "D", 3.0, "2026-06-11 10:00:00"),
            row("1", "had", "A", 4.0, "2026-06-11 10:00:00"),
            row("1", "had", "H", 2.0, "2026-06-11 11:00:00"),
            row("1", "had", "D", 3.0, "2026-06-11 11:00:00"),
            row("1", "had", "A", 4.0, "2026-06-11 11:00:00"),
        ]

        trend = analyze_play_trend("1", "had", "open_to_latest", records)
        total = sum(option.normalized_implied_weight_start for option in trend.options)

        self.assertAlmostEqual(total, 1.0, places=5)
        self.assertAlmostEqual(next(o for o in trend.options if o.option_code == "H").raw_implied_weight_start, 0.5, places=6)

    def test_had_home_win_strengthening(self):
        records = [
            row("1", "had", "H", 2.10, "2026-06-11 10:00:00"),
            row("1", "had", "D", 3.20, "2026-06-11 10:00:00"),
            row("1", "had", "A", 3.10, "2026-06-11 10:00:00"),
            row("1", "had", "H", 1.85, "2026-06-11 20:00:00"),
            row("1", "had", "D", 3.30, "2026-06-11 20:00:00"),
            row("1", "had", "A", 3.80, "2026-06-11 20:00:00"),
        ]

        trend = analyze_play_trend("1", "had", "open_to_latest", records)

        self.assertEqual(trend.main_direction, "home_win_strengthening")
        self.assertEqual(trend.direction_confidence, "high")

    def test_had_home_unbeaten_strengthening(self):
        records = [
            row("1", "had", "H", 2.10, "2026-06-11 10:00:00"),
            row("1", "had", "D", 3.20, "2026-06-11 10:00:00"),
            row("1", "had", "A", 3.10, "2026-06-11 10:00:00"),
            row("1", "had", "H", 1.90, "2026-06-11 20:00:00"),
            row("1", "had", "D", 2.90, "2026-06-11 20:00:00"),
            row("1", "had", "A", 4.20, "2026-06-11 20:00:00"),
        ]

        trend = analyze_play_trend("1", "had", "open_to_latest", records)

        self.assertEqual(trend.main_direction, "home_unbeaten_strengthening")

    def test_no_clear_direction(self):
        records = [
            row("1", "had", "H", 2.00, "2026-06-11 10:00:00"),
            row("1", "had", "D", 3.00, "2026-06-11 10:00:00"),
            row("1", "had", "A", 4.00, "2026-06-11 10:00:00"),
            row("1", "had", "H", 2.01, "2026-06-11 20:00:00"),
            row("1", "had", "D", 3.00, "2026-06-11 20:00:00"),
            row("1", "had", "A", 3.99, "2026-06-11 20:00:00"),
        ]

        trend = analyze_play_trend("1", "had", "open_to_latest", records)

        self.assertEqual(trend.main_direction, "no_clear_direction")
        self.assertEqual(trend.direction_confidence, "none")

    def test_mixed_direction(self):
        records = [
            row("1", "had", "H", 2.10, "2026-06-11 10:00:00"),
            row("1", "had", "D", 3.20, "2026-06-11 10:00:00"),
            row("1", "had", "A", 3.10, "2026-06-11 10:00:00"),
            row("1", "had", "H", 2.00, "2026-06-11 20:00:00"),
            row("1", "had", "D", 3.80, "2026-06-11 20:00:00"),
            row("1", "had", "A", 2.80, "2026-06-11 20:00:00"),
        ]

        trend = analyze_play_trend("1", "had", "open_to_latest", records)

        self.assertEqual(trend.main_direction, "mixed_direction")

    def test_not_enough_snapshots(self):
        trend = analyze_play_trend("1", "had", "open_to_latest", [
            row("1", "had", "H", 2.0, "2026-06-11 10:00:00"),
        ])

        self.assertFalse(trend.available)
        self.assertEqual(trend.reason, "not_enough_snapshots")

    def test_had_away_win_strengthening(self):
        records = [
            row("1", "had", "H", 2.10, "2026-06-11 10:00:00"),
            row("1", "had", "D", 3.20, "2026-06-11 10:00:00"),
            row("1", "had", "A", 3.10, "2026-06-11 10:00:00"),
            row("1", "had", "H", 2.80, "2026-06-11 20:00:00"),
            row("1", "had", "D", 3.50, "2026-06-11 20:00:00"),
            row("1", "had", "A", 2.00, "2026-06-11 20:00:00"),
        ]

        trend = analyze_play_trend("1", "had", "open_to_latest", records)

        self.assertEqual(trend.main_direction, "away_win_strengthening")

    def test_had_draw_strengthening(self):
        records = [
            row("1", "had", "H", 2.10, "2026-06-11 10:00:00"),
            row("1", "had", "D", 3.20, "2026-06-11 10:00:00"),
            row("1", "had", "A", 3.10, "2026-06-11 10:00:00"),
            row("1", "had", "H", 2.50, "2026-06-11 20:00:00"),
            row("1", "had", "D", 2.40, "2026-06-11 20:00:00"),
            row("1", "had", "A", 3.60, "2026-06-11 20:00:00"),
        ]

        trend = analyze_play_trend("1", "had", "open_to_latest", records)

        self.assertEqual(trend.main_direction, "draw_strengthening")

    def test_hhad_handicap_home_strengthening(self):
        records = [
            row("1", "hhad", "H", 2.10, "2026-06-11 10:00:00"),
            row("1", "hhad", "D", 3.20, "2026-06-11 10:00:00"),
            row("1", "hhad", "A", 3.10, "2026-06-11 10:00:00"),
            row("1", "hhad", "H", 1.70, "2026-06-11 20:00:00"),
            row("1", "hhad", "D", 3.50, "2026-06-11 20:00:00"),
            row("1", "hhad", "A", 4.00, "2026-06-11 20:00:00"),
        ]

        trend = analyze_play_trend("1", "hhad", "open_to_latest", records)

        self.assertEqual(trend.main_direction, "handicap_home_strengthening")

    def test_ttg_high_goal_strengthening(self):
        records = [
            row("1", "ttg", "0", 15.0, "2026-06-11 10:00:00"),
            row("1", "ttg", "1", 6.0, "2026-06-11 10:00:00"),
            row("1", "ttg", "2", 3.5, "2026-06-11 10:00:00"),
            row("1", "ttg", "3", 3.8, "2026-06-11 10:00:00"),
            row("1", "ttg", "4", 5.0, "2026-06-11 10:00:00"),
            row("1", "ttg", "5", 8.0, "2026-06-11 10:00:00"),
            row("1", "ttg", "6", 15.0, "2026-06-11 10:00:00"),
            row("1", "ttg", "7", 25.0, "2026-06-11 10:00:00"),
            row("1", "ttg", "0", 18.0, "2026-06-11 20:00:00"),
            row("1", "ttg", "1", 7.0, "2026-06-11 20:00:00"),
            row("1", "ttg", "2", 4.0, "2026-06-11 20:00:00"),
            row("1", "ttg", "3", 3.8, "2026-06-11 20:00:00"),
            row("1", "ttg", "4", 3.5, "2026-06-11 20:00:00"),
            row("1", "ttg", "5", 5.0, "2026-06-11 20:00:00"),
            row("1", "ttg", "6", 10.0, "2026-06-11 20:00:00"),
            row("1", "ttg", "7", 18.0, "2026-06-11 20:00:00"),
        ]

        trend = analyze_play_trend("1", "ttg", "open_to_latest", records)

        self.assertEqual(trend.main_direction, "high_goal_strengthening")
        self.assertIsNotNone(trend.goal_group_deltas)

    def test_ttg_low_goal_strengthening(self):
        records = [
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

        trend = analyze_play_trend("1", "ttg", "open_to_latest", records)

        self.assertEqual(trend.main_direction, "low_goal_strengthening")

    def test_sp_trend_labels(self):
        """Verify sp_trend tag mapping via end-to-end analysis."""
        # Strong down: sp_delta_pct <= -0.08
        records = [
            row("1", "had", "H", 2.00, "2026-06-11 10:00:00"),
            row("1", "had", "D", 3.00, "2026-06-11 10:00:00"),
            row("1", "had", "A", 4.00, "2026-06-11 10:00:00"),
            row("1", "had", "H", 1.80, "2026-06-11 20:00:00"),
            row("1", "had", "D", 3.10, "2026-06-11 20:00:00"),
            row("1", "had", "A", 4.20, "2026-06-11 20:00:00"),
        ]
        trend = analyze_play_trend("1", "had", "open_to_latest", records)
        h = next(o for o in trend.options if o.option_code == "H")
        self.assertEqual(h.sp_trend, "strong_down")

        # Stable: -0.03 < sp_delta_pct < 0.03
        records_stable = [
            row("2", "had", "H", 2.00, "2026-06-11 10:00:00"),
            row("2", "had", "D", 3.00, "2026-06-11 10:00:00"),
            row("2", "had", "A", 4.00, "2026-06-11 10:00:00"),
            row("2", "had", "H", 2.02, "2026-06-11 20:00:00"),
            row("2", "had", "D", 3.00, "2026-06-11 20:00:00"),
            row("2", "had", "A", 3.98, "2026-06-11 20:00:00"),
        ]
        trend2 = analyze_play_trend("2", "had", "open_to_latest", records_stable)
        h2 = next(o for o in trend2.options if o.option_code == "H")
        self.assertEqual(h2.sp_trend, "stable")

    def test_window_last_24h(self):
        """last_24h window uses snapshots within 24h of the latest."""
        records = [
            row("1", "had", "H", 2.10, "2026-06-10 10:00:00"),
            row("1", "had", "D", 3.20, "2026-06-10 10:00:00"),
            row("1", "had", "A", 3.10, "2026-06-10 10:00:00"),
            row("1", "had", "H", 1.90, "2026-06-11 08:00:00"),
            row("1", "had", "D", 3.30, "2026-06-11 08:00:00"),
            row("1", "had", "A", 3.50, "2026-06-11 08:00:00"),
            row("1", "had", "H", 1.85, "2026-06-11 20:00:00"),
            row("1", "had", "D", 3.40, "2026-06-11 20:00:00"),
            row("1", "had", "A", 3.60, "2026-06-11 20:00:00"),
        ]

        trend = analyze_play_trend("1", "had", "last_24h", records)

        self.assertTrue(trend.available)
        self.assertEqual(trend.snapshot_start_time[:19], "2026-06-11T08:00:00")

    def test_window_not_enough_in_window(self):
        """Window with only 1 snapshot returns unavailable."""
        records = [
            row("1", "had", "H", 2.10, "2026-06-10 10:00:00"),
            row("1", "had", "D", 3.20, "2026-06-10 10:00:00"),
            row("1", "had", "A", 3.10, "2026-06-10 10:00:00"),
            row("1", "had", "H", 1.85, "2026-06-11 20:00:00"),
            row("1", "had", "D", 3.40, "2026-06-11 20:00:00"),
            row("1", "had", "A", 3.60, "2026-06-11 20:00:00"),
        ]

        trend = analyze_play_trend("1", "had", "last_1h", records)

        self.assertFalse(trend.available)
        self.assertEqual(trend.reason, "not_enough_snapshots")

    def test_window_uses_boundary_snapshot_when_only_latest_inside(self):
        records = [
            row("1", "had", "H", 2.10, "2026-06-11 18:30:00"),
            row("1", "had", "D", 3.20, "2026-06-11 18:30:00"),
            row("1", "had", "A", 3.10, "2026-06-11 18:30:00"),
            row("1", "had", "H", 1.85, "2026-06-11 20:00:00"),
            row("1", "had", "D", 3.40, "2026-06-11 20:00:00"),
            row("1", "had", "A", 3.60, "2026-06-11 20:00:00"),
        ]

        trend = analyze_play_trend("1", "had", "last_1h", records)

        self.assertTrue(trend.available)
        self.assertEqual(trend.snapshot_start_time[:19], "2026-06-11T18:30:00")


if __name__ == "__main__":
    unittest.main()
