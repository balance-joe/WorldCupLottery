"""sp_movement 模块单元测试。"""

import unittest

from src.sp_movement import latest_records


class LatestRecordsTest(unittest.TestCase):
    def test_keeps_latest_per_option(self):
        records = latest_records([
            {"match_id": "1001", "play_type": "had", "option_code": "H", "sp_value": 2.0, "snapshot_time": "2026-06-11 10:00:00"},
            {"match_id": "1001", "play_type": "had", "option_code": "H", "sp_value": 1.8, "snapshot_time": "2026-06-11 10:10:00"},
            {"match_id": "1001", "play_type": "had", "option_code": "D", "sp_value": 3.2, "snapshot_time": "2026-06-11 10:05:00"},
        ])

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["sp_value"], 3.2)
        self.assertEqual(records[1]["sp_value"], 1.8)

    def test_single_record(self):
        records = latest_records([
            {"match_id": "1001", "play_type": "had", "option_code": "H", "sp_value": 2.0, "snapshot_time": "2026-06-11 10:00:00"},
        ])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["sp_value"], 2.0)

    def test_empty_list(self):
        self.assertEqual(latest_records([]), [])


if __name__ == "__main__":
    unittest.main()
