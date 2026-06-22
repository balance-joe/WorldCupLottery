"""
Analyze all stored matches with SP history and print a compact screening table.

Usage:
    python -m scripts.analyze_today_matches
"""

from __future__ import annotations

import argparse
import json
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
    parser.add_argument("--with-detail", action="store_true", help="读取/抓取非SP详情证据")
    parser.add_argument("--fetch-detail", action="store_true", help="运行时实时抓取 detail APIs")
    parser.add_argument("--detail-dir", type=str, help="detail bundle JSON 目录")
    args = parser.parse_args()

    from src import api_client
    from src import db
    from src.market_structure import PRIORITY_RANK
    from src.recommendation import build_match_recommendation
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
            detail_bundle = None
            detail_error_count = 0
            if args.with_detail:
                if args.fetch_detail:
                    detail_bundle, detail_errors = api_client.fetch_match_detail_bundle(match_id)
                    detail_error_count = len(detail_errors)
                    for source_name, payload in detail_bundle.items():
                        db.save_raw_snapshot(conn, source_name, api_client.DETAIL_APIS[source_name], payload, match_id, {"matchId": match_id})
                elif args.detail_dir:
                    detail_path = Path(args.detail_dir) / f"match_{match_id}_detail.json"
                    if detail_path.exists():
                        with open(detail_path, encoding="utf-8") as f:
                            detail_bundle = json.load(f)

            result = analyze_match_windows(
                match,
                sp_history,
                windows=(args.window,),
                include_debug=False,
                detail_bundle=detail_bundle,
            )
            structure = result["market_structures"][args.window]
            recommendation = build_match_recommendation(match, sp_history, window=args.window)
            rows.append({
                "match_num": match.get("match_num") or "",
                "league": match.get("league_name") or "",
                "home_team": match.get("home_team_name") or "",
                "away_team": match.get("away_team_name") or "",
                "match_time": match.get("match_time") or "",
                "sp_research_priority": result.get("sp_research_priority") or structure["research_priority"],
                "final_research_priority": result["final_research_priority"],
                "main_market_expression": structure["main_market_expression"],
                "had_direction": structure["had_direction"],
                "hhad_direction": structure["hhad_direction"],
                "ttg_direction": structure["ttg_direction"],
                "top_risk_flags": ",".join(risk["code"] for risk in structure["risk_flags"][:2]),
                "suggested_focus": ",".join(structure["suggested_focus"]),
                "non_sp_lean": (result.get("non_sp_evidence") or {}).get("non_sp_lean", "-"),
                "support_confidence": (result.get("non_sp_evidence") or {}).get("support_confidence", "-"),
                "blend_reason": (result.get("non_sp_blend_summary") or {}).get("reason", "-"),
                "detail_errors": detail_error_count,
                "gate_allowed": recommendation.gate.allowed,
                "allowed_plays": ",".join(recommendation.gate.allowed_plays) or "-",
                "gate_reasons": ",".join(recommendation.gate.reasons) or "-",
                "had_options": ",".join(recommendation.candidates.had_options) or "-",
                "ttg_options": ",".join(recommendation.candidates.ttg_options) or "-",
                "crs_options": ",".join(recommendation.candidates.crs_options) or "-",
            })

        rows.sort(key=lambda row: (PRIORITY_RANK.get(row["final_research_priority"], 9), row["match_time"]))
        print(f"比赛日期: {match_date}  场次: {len(rows)}")
        for row in rows:
            print(
                f"{row['match_num']} {row['league']} {row['home_team']} vs {row['away_team']} "
                f"{row['match_time']} 优先级:{row['final_research_priority']}"
                f"(SP:{row['sp_research_priority']}) "
                f"市场表达:{row['main_market_expression']} "
                f"胜平负:{row['had_direction']} 让球:{row['hhad_direction']} 总进球:{row['ttg_direction']} "
                f"风险:{row['top_risk_flags'] or '-'} 关注:{row['suggested_focus'] or '-'} "
                f"非SP:{row['non_sp_lean']}/{row['support_confidence']} 校正:{row['blend_reason']} "
                f"可买:{'Y' if row['gate_allowed'] else 'N'} 玩法:{row['allowed_plays']} "
                f"候选:HAD={row['had_options']} TTG={row['ttg_options']} CRS={row['crs_options']} "
                f"门禁:{row['gate_reasons']}"
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
