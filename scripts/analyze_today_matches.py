"""
分析所有已存储的比赛（含 SP 历史），输出紧凑的筛选表。

用法:
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
    from src.recommendation import build_match_recommendation, latest_play_snapshot, latest_option_sp
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
            if args.with_detail:
                if args.fetch_detail:
                    detail_bundle, _ = api_client.fetch_match_detail_bundle(match_id)
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
            recommendation = build_match_recommendation(
                match,
                sp_history,
                window=args.window,
                now_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            main_play, main_pick = _main_result_pick(recommendation)
            score_pick = _score_pick(recommendation, main_pick)
            goal_range = _goal_range(recommendation)
            hafu_pick = _hafu_pick(sp_history)
            half_result_pick = _half_result_pick(sp_history)
            report_class = _report_class(main_pick, goal_range)
            main_pick_sp = _main_pick_sp(recommendation, main_play, main_pick)
            had_bucket = _had_bucket(main_play, main_pick, main_pick_sp)
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
                "gate_allowed": recommendation.gate.allowed,
                "allowed_plays": ",".join(recommendation.gate.allowed_plays) or "-",
                "gate_reasons": ",".join(recommendation.gate.reasons) or "-",
                "report_class": report_class,
                "had_bucket": had_bucket,
                "main_play": main_play or "-",
                "main_pick": main_pick or "-",
                "main_pick_sp": main_pick_sp,
            "score_pick": score_pick or "-",
                "score_sp": latest_option_sp(sp_history, "crs", score_pick) if score_pick else None,
                "goal_range": goal_range or "-",
                "hafu_pick": hafu_pick or "-",
                "half_result_pick": half_result_pick or "-",
            })

        rows.sort(key=lambda row: (
            _report_sort_rank(row["report_class"], row["had_bucket"]),
            PRIORITY_RANK.get(row["final_research_priority"], 9),
            row["main_pick_sp"] if row["main_pick_sp"] is not None else 999.0,
            row["match_time"],
        ))
        print(f"比赛日期: {match_date}  场次: {len(rows)}")
        for row in rows:
            sp_text = f"{row['main_pick_sp']:.2f}" if row["main_pick_sp"] is not None else "-"
            main_text = f"{row['main_play']}:{row['main_pick']}" if row["main_play"] != "-" and row["main_pick"] != "-" else "-"
            ticket_text = f"{main_text} @ {sp_text}" if main_text != "-" else "不买"
            score_ticket_text = (
                f"crs:{row['score_pick']} @ {row['score_sp']:.2f}"
                if row["score_pick"] != "-" and row["score_sp"] is not None
                else "不买"
            )
            assist_text = (
                f"进球:{row['goal_range']} 半场:{row['half_result_pick']} 半全场:{row['hafu_pick']}"
                if row["report_class"] != "过滤场"
                else "-"
            )
            print(
                f"{row['match_num']} {row['league']} {row['home_team']} vs {row['away_team']} "
                f"{row['match_time']} 优先级:{row['final_research_priority']}"
                f"(SP:{row['sp_research_priority']}) "
                f"分类:{row['report_class']} 分层:{row['had_bucket']} "
                f"正式主票:{ticket_text} 正式比分小票:{score_ticket_text} "
                f"市场表达:{row['main_market_expression']} 风险:{row['top_risk_flags'] or '-'} "
                f"门禁:{row['gate_reasons']}"
            )
            print(
                f"  辅助观察:{assist_text} "
                f"方向:胜平负={row['had_direction']} 让球={row['hhad_direction']} 总进球={row['ttg_direction']} "
                f"非SP:{row['non_sp_lean']}/{row['support_confidence']} 校正:{row['blend_reason']}"
            )
    finally:
        conn.close()


def _main_result_pick(recommendation) -> tuple[str | None, str | None]:
    for suggestion in getattr(recommendation, "suggestions", ()):
        if suggestion.play_type not in {"had", "hhad"} or len(suggestion.selections) != 1:
            continue
        pick = suggestion.selections[0]
        sp_value = _pick_sp(recommendation, suggestion.play_type, pick)
        if suggestion.play_type == "had" and pick == "A" and sp_value is not None and sp_value >= 1.60:
            return None, None
        return suggestion.play_type, pick

    if not recommendation.gate.allowed:
        return None, None
    if len(recommendation.candidates.had_options) != 1:
        return None, None
    pick = recommendation.candidates.had_options[0]
    sp_value = _pick_sp(recommendation, "had", pick)
    if pick == "A" and sp_value is not None and sp_value >= 1.60:
        return None, None
    return "had", pick


def _score_pick(recommendation, main_pick: str | None) -> str | None:
    if not recommendation.gate.allowed:
        return None
    if not main_pick:
        return None
    if recommendation.candidates.crs_options:
        return recommendation.candidates.crs_options[0]
    return None


def _goal_range(recommendation) -> str | None:
    if not recommendation.gate.allowed:
        return None
    if recommendation.candidates.ttg_options:
        return "/".join(recommendation.candidates.ttg_options)
    return None


def _hafu_pick(sp_history: list[dict]) -> str | None:
    latest = _latest_play_snapshot(sp_history, "hafu")
    if not latest:
        return None
    best = max(
        latest,
        key=lambda row: (
            row.get("implied_prob_norm") or 0,
            -float(row.get("sp_value") or 999),
        ),
    )
    return str(best.get("option_code")).lower()


def _half_result_pick(sp_history: list[dict]) -> str | None:
    latest = _latest_play_snapshot(sp_history, "hafu")
    if not latest:
        return None
    buckets = {"H": 0.0, "D": 0.0, "A": 0.0}
    for row in latest:
        code = str(row.get("option_code", "")).lower()
        if len(code) != 2 or code[0] not in {"h", "d", "a"}:
            continue
        half = {"h": "H", "d": "D", "a": "A"}[code[0]]
        buckets[half] += float(row.get("implied_prob_norm") or 0)
    if not any(buckets.values()):
        return None
    return max(buckets.items(), key=lambda item: item[1])[0]


def _main_pick_sp(recommendation, main_play: str | None, main_pick: str | None) -> float | None:
    if not main_play or not main_pick:
        return None
    return _pick_sp(recommendation, main_play, main_pick)


def _latest_play_snapshot(sp_history: list[dict], play_type: str) -> list[dict]:
    latest_time = max(
        (str(row.get("snapshot_time", "")) for row in sp_history if row.get("play_type") == play_type),
        default="",
    )
    if not latest_time:
        return []
    return [
        row for row in sp_history
        if row.get("play_type") == play_type and str(row.get("snapshot_time", "")) == latest_time
    ]


def _pick_sp(recommendation, play_type: str, pick: str | None) -> float | None:
    if not pick:
        return None
    trend = recommendation.hhad_trend if play_type == "hhad" else recommendation.had_trend
    for option in trend.options:
        if option.option_code == pick:
            return option.sp_end
    return None


def _had_bucket(main_play: str | None, main_pick: str | None, main_pick_sp: float | None) -> str:
    if main_play == "hhad":
        return {"H": "让胜", "D": "让平", "A": "让负"}.get(main_pick or "", "让球")
    if main_pick == "H":
        if main_pick_sp is not None and main_pick_sp < 1.60:
            return "低SP主胜"
        return "中高SP主胜"
    if main_pick == "A":
        if main_pick_sp is not None and main_pick_sp < 1.60:
            return "低SP客胜"
        return "高SP客胜"
    if main_pick == "D":
        return "平局"
    return "-"


def _report_class(main_pick: str | None, goal_range: str | None) -> str:
    if main_pick:
        return "主推场"
    if goal_range:
        return "观察场"
    return "过滤场"


def _report_sort_rank(report_class: str, had_bucket: str) -> tuple[int, int]:
    class_rank = {
        "主推场": 0,
        "观察场": 1,
        "过滤场": 2,
    }.get(report_class, 9)
    bucket_rank = {
        "低SP主胜": 0,
        "低SP客胜": 1,
        "中高SP主胜": 2,
        "高SP客胜": 3,
        "让胜": 4,
        "让负": 5,
        "让平": 6,
        "平局": 7,
        "-": 9,
    }.get(had_bucket, 9)
    return class_rank, bucket_rank


if __name__ == "__main__":
    main()
