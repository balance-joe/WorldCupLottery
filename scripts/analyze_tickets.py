"""
逐票信号分析：回溯每张票下单时的 SP 信号和市场结构。

Usage:
    python -m scripts.analyze_tickets
    python -m scripts.analyze_tickets --detail
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src import db
from src.sp_trend import analyze_play_trend
from src.market_structure import analyze_market_structure
from src.recommendation import filter_sp_records_as_of


def analyze_all_tickets(conn, *, detail: bool = False) -> list[dict]:
    """分析所有已投注的票，回溯信号状态。"""
    tickets = db.fetch_betting_tickets(conn)
    if not tickets:
        print("没有投注记录")
        return []

    # 预加载所有涉及比赛的 SP 历史
    match_ids = set()
    for ticket in tickets:
        rows = conn.execute(
            "SELECT match_id FROM betting_ticket_selection WHERE ticket_id = ?",
            (ticket["id"],),
        ).fetchall()
        for row in rows:
            match_ids.add(str(row[0]))

    all_sp = db.fetch_all_sp_history(conn, list(match_ids))

    results = []
    for ticket in tickets:
        ticket_id = ticket["id"]
        legs = conn.execute(
            "SELECT * FROM betting_ticket_selection WHERE ticket_id = ? ORDER BY leg_index",
            (ticket_id,),
        ).fetchall()

        leg_analyses = []
        for leg in legs:
            leg_dict = dict(leg)
            leg_dict["placed_at"] = ticket.get("placed_at")
            mid = str(leg_dict["match_id"])
            play_type = leg_dict["play_type"]
            option_code = leg_dict["option_code"]

            match_sp = [r for r in all_sp if str(r.get("match_id")) == mid]

            match_info = db.fetch_match(conn, mid) or {}
            analysis = _analyze_leg(mid, play_type, option_code, leg_dict, match_info, match_sp)
            leg_analyses.append(analysis)

        results.append({
            "ticket": ticket,
            "legs": leg_analyses,
        })

    return results


def _analyze_leg(
    match_id: str,
    play_type: str,
    option_code: str,
    leg: dict,
    match: dict,
    sp_history: list[dict],
) -> dict:
    """分析一条 leg 的信号状态。"""
    result = {
        "match_id": match_id,
        "play_type": play_type,
        "option_code": option_code,
        "option_name": leg.get("option_name"),
        "selected_sp": leg.get("selected_sp"),
        "result_status": leg.get("result_status"),
        "actual_result": leg.get("actual_result"),
        "match_info": f"{match.get('home_team_name', '?')} vs {match.get('away_team_name', '?')}",
        "score": match.get("full_score_90", "?"),
        "had_signal": None,
        "had_confidence": None,
        "hhad_signal": None,
        "ttg_signal": None,
        "market_expression": None,
        "research_priority": None,
        "direction_match": None,
    }

    cutoff_time = leg.get("sp_snapshot_time") or leg.get("placed_at")
    as_of_history = filter_sp_records_as_of(sp_history, cutoff_time)
    result["analysis_cutoff_time"] = cutoff_time

    if not as_of_history:
        result["note"] = "no SP history"
        return result

    # HAD 趋势
    had_trend = analyze_play_trend(match_id, "had", "open_to_latest", as_of_history)
    if had_trend.available:
        result["had_signal"] = had_trend.main_direction
        result["had_confidence"] = had_trend.direction_confidence

    # HHAD 趋势
    hhad_trend = analyze_play_trend(match_id, "hhad", "open_to_latest", as_of_history)
    if hhad_trend.available:
        result["hhad_signal"] = hhad_trend.main_direction

    # TTG 趋势
    ttg_trend = analyze_play_trend(match_id, "ttg", "open_to_latest", as_of_history)
    if ttg_trend.available:
        result["ttg_signal"] = ttg_trend.main_direction

    # 市场结构
    if had_trend.available or hhad_trend.available or ttg_trend.available:
        structure = analyze_market_structure(
            match_id, "open_to_latest", had_trend, hhad_trend, ttg_trend,
        )
        result["market_expression"] = structure.main_market_expression
        result["research_priority"] = structure.research_priority
        result["consistency"] = structure.consistency_level
        result["conflicts"] = [c.message for c in structure.conflicts]
        result["risk_flags"] = [r.message for r in structure.risk_flags]

    # 判断信号是否支持买入方向
    result["direction_match"] = _check_direction_match(
        play_type, option_code, had_trend, hhad_trend, ttg_trend,
    )

    return result


def _check_direction_match(
    play_type: str,
    option_code: str,
    had_trend,
    hhad_trend,
    ttg_trend,
) -> bool | None:
    """检查信号方向是否与买入方向一致。"""
    if play_type == "had" and had_trend and had_trend.available:
        d = had_trend.main_direction
        if option_code == "H" and "home_win" in d:
            return True
        if option_code == "A" and "away_win" in d:
            return True
        if option_code == "D" and "draw" in d:
            return True
        return False

    if play_type == "hhad" and hhad_trend and hhad_trend.available:
        d = hhad_trend.main_direction
        if option_code == "H" and "home" in d:
            return True
        if option_code == "A" and "away" in d:
            return True
        if option_code == "D" and "draw" in d:
            return True
        return False

    if play_type == "ttg" and ttg_trend and ttg_trend.available:
        d = ttg_trend.main_direction
        total = _option_to_total_goals(option_code)
        if total is not None:
            if total <= 2 and "low_goal" in d:
                return True
            if total == 3 and "mid_goal" in d:
                return True
            if total >= 4 and "high_goal" in d:
                return True
        return False

    return None  # CRS/HAFU 无法用趋势判断


def _option_to_total_goals(option_code: str) -> int | None:
    """TTG option_code -> 总进球数。"""
    try:
        v = int(option_code)
        return v if 0 <= v <= 7 else None
    except ValueError:
        return None


def print_analysis(results: list[dict], *, detail: bool = False) -> None:
    """打印分析结果。"""
    total_stake = 0
    total_payout = 0
    signal_hit = 0
    signal_miss = 0
    no_signal = 0

    for r in results:
        ticket = r["ticket"]
        legs = r["legs"]
        status = ticket["ticket_status"]
        mark = "[WON]" if status == "won" else "[LOST]" if status == "lost" else "[PENDING]"
        pl = ticket.get("profit_loss") or 0
        pl_str = f"{pl:+.2f}" if pl else ""
        source_type = ticket.get("source_type", "UNKNOWN")

        print(
            f"\n{mark} #{ticket['id']} {ticket['ticket_label']}  "
            f"{ticket['stake_amount']:.0f}元  {pl_str}  source={source_type}"
        )
        total_stake += ticket["stake_amount"]
        total_payout += ticket.get("actual_payout") or 0

        for leg in legs:
            _print_leg(leg, detail=detail)

            dm = leg.get("direction_match")
            if dm is True:
                signal_hit += 1
            elif dm is False:
                signal_miss += 1
            else:
                no_signal += 1

    print(f"\n{'=' * 60}")
    print(f"信号统计: 方向命中 {signal_hit} / 方向未中 {signal_miss} / 无信号 {no_signal}")
    if signal_hit + signal_miss > 0:
        print(f"信号准确率: {signal_hit / (signal_hit + signal_miss):.1%}")
    print(f"总投入: {total_stake:.0f}  总奖金: {total_payout:.2f}  净盈亏: {total_payout - total_stake:+.2f}")


def _print_leg(leg: dict, *, detail: bool = False) -> None:
    """打印单条 leg 分析。"""
    pt = leg["play_type"]
    code = leg["option_code"]
    name = leg.get("option_name", code)
    sp = leg.get("selected_sp", "?")
    status = leg.get("result_status", "?")
    actual = leg.get("actual_result", "?")
    mark = "HIT" if status == "hit" else "MISS" if status == "miss" else "?"

    sig_parts = []
    if leg.get("had_signal"):
        sig_parts.append(f"HAD:{leg['had_signal']}({leg.get('had_confidence', '?')})")
    if leg.get("hhad_signal"):
        sig_parts.append(f"HHAD:{leg['hhad_signal']}")
    if leg.get("ttg_signal"):
        sig_parts.append(f"TTG:{leg['ttg_signal']}")
    sig_str = " | ".join(sig_parts) if sig_parts else "无趋势信号"

    expr = leg.get("market_expression", "")
    pri = leg.get("research_priority", "")
    expr_str = f" → {expr} [{pri}]" if expr else ""

    dm = leg.get("direction_match")
    dm_str = ""
    if dm is True:
        dm_str = " [信号支持]"
    elif dm is False:
        dm_str = " [信号不支持]"

    print(f"    {pt} {code}({name}) sp={sp} -> {mark} actual={actual}")
    print(f"      信号: {sig_str}{expr_str}{dm_str}")

    if detail:
        if leg.get("analysis_cutoff_time"):
            print(f"      截止快照: {leg['analysis_cutoff_time']}")
        if leg.get("conflicts"):
            print(f"      冲突: {', '.join(leg['conflicts'])}")
        if leg.get("risk_flags"):
            print(f"      风险: {', '.join(leg['risk_flags'])}")


def main():
    parser = argparse.ArgumentParser(description="逐票信号分析")
    parser.add_argument("--detail", action="store_true", help="显示冲突和风险详情")
    args = parser.parse_args()

    conn = db.get_connection()
    try:
        results = analyze_all_tickets(conn, detail=args.detail)
        print_analysis(results, detail=args.detail)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
