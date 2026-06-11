"""
Analyze one match's Sporttery SP market structure.

Usage:
    python -m scripts.analyze_match_structure --match-id 123456
    python -m scripts.analyze_match_structure --match-id 123456 --window last_24h --debug
    python -m scripts.analyze_match_structure --match-id 123456 --save
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
    parser = argparse.ArgumentParser(description="Analyze one match market structure")
    parser.add_argument("--match-id", required=True, help="比赛 match_id")
    parser.add_argument("--window", action="append", help="分析窗口，可重复传入")
    parser.add_argument("--debug", action="store_true", help="输出完整趋势明细")
    parser.add_argument("--save", action="store_true", help="保存 market_structure 到数据库")
    args = parser.parse_args()

    from src import db
    from src.sp_trend import WINDOWS
    from src.structure_analysis import analyze_match_windows

    windows = tuple(args.window) if args.window else WINDOWS
    invalid = [window for window in windows if window not in WINDOWS]
    if invalid:
        print(f"错误: 不支持的窗口 {', '.join(invalid)}")
        sys.exit(1)

    conn = db.get_connection()
    try:
        db.ensure_tables(conn)
        match = db.fetch_match(conn, args.match_id)
        if not match:
            print(f"错误: match_id={args.match_id} 不存在")
            sys.exit(1)
        sp_history = db.fetch_all_sp_history(conn, [args.match_id])
        result = analyze_match_windows(match, sp_history, windows=windows, include_debug=args.debug)

        print(f"{match.get('match_num')} {match.get('home_team_name')} vs {match.get('away_team_name')} ({match.get('league_name')})")
        print(f"最终研究优先级: {result['final_research_priority']}")
        for window, structure in result["market_structures"].items():
            print(
                f"[{window}] 优先级={structure['research_priority']} "
                f"市场表达={structure['main_market_expression']} "
                f"had={structure['had_direction']} "
                f"hhad={structure['hhad_direction']} "
                f"ttg={structure['ttg_direction']}"
            )
        print(f"节奏: {result['cross_window_summary']['tempo_reading']}")

        if args.save:
            analysis_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for structure in result["market_structures"].values():
                payload = dict(structure)
                payload["analysis_time"] = analysis_time
                db.save_market_analysis(conn, payload)
            print("已保存 market_structure 分析记录")

        if args.debug:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(result["llm_input"], ensure_ascii=False, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
