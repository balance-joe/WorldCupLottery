"""
Fetch Sporttery football results and backfill match scores.

Usage:
    python -m scripts.fetch_results
    python -m scripts.fetch_results --page-size 50
    python -m scripts.fetch_results --match-date 2026-06-10
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main():
    parser = argparse.ArgumentParser(description="Fetch Sporttery football results")
    parser.add_argument("--page-size", type=int, default=50, help="每页赛果数量")
    parser.add_argument("--page-no", type=int, default=None, help="页码，不传则使用接口默认")
    parser.add_argument("--match-date", type=str, default=None, help="比赛日期 YYYY-MM-DD")
    args = parser.parse_args()

    if args.page_size <= 0:
        print("错误: --page-size 必须大于 0")
        sys.exit(1)

    from src import api_client, db, parsers

    conn = db.get_connection()
    try:
        db.ensure_tables(conn)
        raw, err = api_client.fetch_result_list(
            page_size=args.page_size,
            page_no=args.page_no,
            match_date=args.match_date,
        )
        if err:
            print(f"赛果抓取失败: {err}")
            sys.exit(1)

        db.save_raw_snapshot(
            conn,
            "matchResultList",
            "method=result",
            raw,
            request_params={
                "method": "result",
                "pageSize": args.page_size,
                "pageNo": args.page_no,
                "matchDate": args.match_date,
            },
        )

        results = parsers.parse_result_list(raw)
        completed = [
            result for result in results
            if result.get("home_score_90") is not None
            and result.get("away_score_90") is not None
            and result.get("result_90") is not None
        ]
        saved = db.save_match_results(conn, completed)

        print(f"抓取赛果: {len(results)} 场")
        print(f"有效回填: {saved} 场")
        for result in completed[:10]:
            print(
                f"  {result['match_num']} {result['home_team_name']} "
                f"{result['full_score_90']} {result['away_team_name']} "
                f"result_90={result['result_90']}"
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
