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
    parser.add_argument("--with-detail", action="store_true", help="读取/抓取非SP详情证据")
    parser.add_argument("--fetch-detail", action="store_true", help="运行时实时抓取 detail APIs")
    parser.add_argument("--detail-path", type=str, help="detail bundle JSON 路径")
    args = parser.parse_args()

    from src import db
    from src import api_client
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
        detail_bundle = None
        if args.with_detail:
            if args.fetch_detail:
                detail_bundle, detail_errors = api_client.fetch_match_detail_bundle(args.match_id)
                for source_name, payload in detail_bundle.items():
                    db.save_raw_snapshot(conn, source_name, api_client.DETAIL_APIS[source_name], payload, str(args.match_id), {"matchId": str(args.match_id)})
                if detail_errors:
                    print(f"detail 抓取失败: {detail_errors}")
            elif args.detail_path:
                with open(args.detail_path, encoding="utf-8") as f:
                    detail_bundle = json.load(f)

        result = analyze_match_windows(
            match,
            sp_history,
            windows=windows,
            include_debug=args.debug,
            detail_bundle=detail_bundle,
        )

        print(f"{match.get('match_num')} {match.get('home_team_name')} vs {match.get('away_team_name')} ({match.get('league_name')})")
        if result.get("sp_research_priority") and result["sp_research_priority"] != result["final_research_priority"]:
            print(f"最终研究优先级: {result['final_research_priority']}  (SP基础={result['sp_research_priority']})")
        else:
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
        if result.get("non_sp_evidence"):
            print(f"非SP信号: {'; '.join(result['non_sp_evidence'].get('key_signals', [])[:5]) or '-'}")
        if result.get("non_sp_blend_summary"):
            blend = result["non_sp_blend_summary"]
            print(f"综合校正: SP={blend['sp_lean']} 非SP={blend['non_sp_lean']} 置信={blend['support_confidence']} 原因={blend['reason']}")

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
