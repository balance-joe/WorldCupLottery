import unittest

from src.sp_movement import calculate_sp_movements, latest_records


class SpMovementTest(unittest.TestCase):
    def test_calculates_first_and_previous_movement(self):
        movements = calculate_sp_movements([
            {"match_id": "1001", "play_type": "had", "option_code": "H", "sp_value": 2.0, "snapshot_time": "2026-06-11 10:00:00"},
            {"match_id": "1001", "play_type": "had", "option_code": "H", "sp_value": 1.9, "snapshot_time": "2026-06-11 10:05:00"},
            {"match_id": "1001", "play_type": "had", "option_code": "H", "sp_value": 1.8, "snapshot_time": "2026-06-11 10:10:00"},
        ])

        movement = movements[0]
        self.assertEqual(movement.change_from_first, -0.2)
        self.assertEqual(movement.change_pct_from_first, -0.1)
        self.assertEqual(movement.change_from_previous, -0.1)
        self.assertEqual(movement.direction_from_first, "down")
        self.assertEqual(movement.direction_from_previous, "down")

    def test_latest_records_keeps_latest_per_option(self):
        records = latest_records([
            {"match_id": "1001", "play_type": "had", "option_code": "H", "sp_value": 2.0, "snapshot_time": "2026-06-11 10:00:00"},
            {"match_id": "1001", "play_type": "had", "option_code": "H", "sp_value": 1.8, "snapshot_time": "2026-06-11 10:10:00"},
            {"match_id": "1001", "play_type": "had", "option_code": "D", "sp_value": 3.2, "snapshot_time": "2026-06-11 10:05:00"},
        ])

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["sp_value"], 3.2)
        self.assertEqual(records[1]["sp_value"], 1.8)


if __name__ == "__main__":
    unittest.main()
