"""Fetch Sporttery football detail APIs for one match and save raw snapshots."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main():
    parser = argparse.ArgumentParser(description="Fetch football detail APIs")
    parser.add_argument("--match-id", required=True, help="比赛 match_id")
    parser.add_argument("--output", help="可选：输出 bundle JSON")
    args = parser.parse_args()

    from src import api_client, db

    conn = db.get_connection()
    try:
        db.ensure_tables(conn)
        payloads, errors = api_client.fetch_match_detail_bundle(args.match_id)
        for source_name, payload in payloads.items():
            db.save_raw_snapshot(
                conn,
                source_name,
                api_client.DETAIL_APIS[source_name],
                payload,
                str(args.match_id),
                {"matchId": str(args.match_id)},
            )
        print(f"已抓取 detail: 成功 {len(payloads)} 个, 失败 {len(errors)} 个")
        if errors:
            print(json.dumps(errors, ensure_ascii=False, indent=2))
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(payloads, f, ensure_ascii=False, indent=2)
            print(f"已输出: {args.output}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
