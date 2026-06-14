"""
回填已有 raw_snapshot 中的 crs/hafu 数据到 sp_snapshot 表。

Usage:
    python -m scripts.backfill_crs_hafu
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src import db, parsers, probability


def main():
    conn = db.get_connection()

    try:
        cur = conn.execute(
            "SELECT id, match_id, raw_content FROM sporttery_raw_snapshot "
            "WHERE source_name = 'fixedBonus'"
        )
        rows = cur.fetchall()
        print(f"找到 {len(rows)} 条 fixedBonus 原始快照")

        total_records = 0
        matches_processed = set()

        for row in rows:
            snapshot_id, match_id, raw_content = row

            if not match_id:
                continue

            try:
                raw = json.loads(raw_content)
            except json.JSONDecodeError:
                print(f"  ⚠ 快照 {snapshot_id} JSON 解析失败，跳过")
                continue

            records = []
            odds = raw.get("value", {}).get("oddsHistory", {})

            single_map = {}
            for s in odds.get("singleList", []):
                pool = s.get("poolCode", "").lower()
                single_map[pool] = s.get("single", 0)

            for item in odds.get("crsList", []):
                records.extend(parsers.parse_crs(item, match_id, single_map))

            for item in odds.get("hafuList", []):
                records.extend(parsers.parse_hafu(item, match_id, single_map))

            if not records:
                continue

            records = probability.calc_implied_prob(records)
            inserted = db.save_sp_snapshots(conn, records)
            total_records += inserted
            matches_processed.add(match_id)

        print(f"\n回填完成:")
        print(f"  处理比赛数: {len(matches_processed)}")
        print(f"  插入记录数: {total_records}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
