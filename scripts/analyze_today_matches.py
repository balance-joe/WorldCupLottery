"""
Analyze all stored matches with SP history and print a compact screening table.

Usage:
    python -m scripts.analyze_today_matches
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main():
    parser = argparse.ArgumentParser(description="Analyze stored matches for screening")
    parser.add_argument("--window", default="open_to_latest", help="筛选窗口")
    parser.add_argument("--date", help="比赛日期，格式 YYYY-MM-DD，默认今天")
    args = parser.parse_args()

    from src import db
    from src.market_structure import PRIORITY_RANK
    from src.sp_trend import WINDOWS
    from src.structure_analysis import analyze_match_windows

    if args.window not in WINDOWS:
        print(f"错误: 不支持的窗口 {args.window}")
        sys.exit(1)

    conn = db.get_connection()
    try:
        db.ensure_tables(conn)
        rows = []
        match_date = args.date or datetime.now().strftime("%Y-%m-%d")
        for match in db.fetch_matches_for_analysis(conn, match_date=match_date):
            match_id = str(match.get("match_id"))
            sp_history = db.fetch_all_sp_history(conn, [match_id])
            result = analyze_match_windows(match, sp_history, windows=(args.window,), include_debug=False)
            structure = result["market_structures"][args.window]
            rows.append({
                "match_num": match.get("match_num") or "",
                "league": match.get("league_name") or "",
                "home_team": match.get("home_team_name") or "",
                "away_team": match.get("away_team_name") or "",
                "match_time": match.get("match_time") or "",
                "final_research_priority": structure["research_priority"],
                "main_market_expression": structure["main_market_expression"],
                "had_direction": structure["had_direction"],
                "hhad_direction": structure["hhad_direction"],
                "ttg_direction": structure["ttg_direction"],
                "top_risk_flags": ",".join(risk["code"] for risk in structure["risk_flags"][:2]),
                "suggested_focus": ",".join(structure["suggested_focus"]),
            })

        rows.sort(key=lambda row: (PRIORITY_RANK.get(row["final_research_priority"], 9), row["match_time"]))
        print(f"比赛日期: {match_date}  场次: {len(rows)}")
        for row in rows:
            print(
                f"{row['match_num']} {row['league']} {row['home_team']} vs {row['away_team']} "
                f"{row['match_time']} 优先级:{row['final_research_priority']} "
                f"市场表达:{row['main_market_expression']} "
                f"胜平负:{row['had_direction']} 让球:{row['hhad_direction']} 总进球:{row['ttg_direction']} "
                f"风险:{row['top_risk_flags'] or '-'} 关注:{row['suggested_focus'] or '-'}"
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
