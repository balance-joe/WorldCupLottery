"""
策略回测：在全部有 SP+赛果的比赛上模拟不同买入策略。

Usage:
    python -m scripts.backtest_strategies
    python -m scripts.backtest_strategies --detail
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src import db
from src.recommendation import build_match_recommendation


# ── 策略定义 ────────────────────────────────────────────────────────────────

STRATEGIES = [
    {
        "name": "A-HAD",
        "desc": "只买 priority A 的 HAD 方向",
        "play": "had",
        "filter": lambda sig: sig["priority"] == "A" and sig["gate_allowed"] and "had" in sig["allowed_plays"],
        "bet_option": lambda sig: sig["had_bet"],
        "stake": 10,
    },
    {
        "name": "AB-HAD",
        "desc": "买 priority A+B 的 HAD 方向",
        "play": "had",
        "filter": lambda sig: sig["priority"] in ("A", "B") and sig["gate_allowed"] and "had" in sig["allowed_plays"],
        "bet_option": lambda sig: sig["had_bet"],
        "stake": 10,
    },
    {
        "name": "triple-confirm",
        "desc": "三线一致时买 HAD (home_big_win / away_not_lose)",
        "play": "had",
        "filter": lambda sig: sig["gate_allowed"] and "had" in sig["allowed_plays"] and sig["expression"] in (
            "home_big_win_supported", "away_not_lose_or_small_win_supported",
        ),
        "bet_option": lambda sig: sig["had_bet"],
        "stake": 10,
    },
    {
        "name": "low-sp-high-conf",
        "desc": "低 SP (<1.6) + medium/high 置信的 HAD",
        "play": "had",
        "filter": lambda sig: (
            sig["gate_allowed"]
            and "had" in sig["allowed_plays"]
            and
            sig["had_bet_sp"] is not None
            and sig["had_bet_sp"] < 1.6
            and sig["had_confidence"] in ("medium", "high")
        ),
        "bet_option": lambda sig: sig["had_bet"],
        "stake": 10,
    },
    {
        "name": "mid-sp-confirm",
        "desc": "中等 SP (1.6-2.5) + hhad 确认的 HAD",
        "play": "had",
        "filter": lambda sig: (
            sig["gate_allowed"]
            and "had" in sig["allowed_plays"]
            and
            sig["had_bet_sp"] is not None
            and 1.6 <= sig["had_bet_sp"] <= 2.5
            and sig["hhad_confirms_had"]
        ),
        "bet_option": lambda sig: sig["had_bet"],
        "stake": 10,
    },
    {
        "name": "TTG-medium-conf",
        "desc": "TTG medium/high 置信时买 TTG 方向",
        "play": "ttg",
        "filter": lambda sig: (
            sig["gate_allowed"]
            and "ttg" in sig["allowed_plays"]
            and
            sig["ttg_bet"] is not None
            and sig["ttg_confidence"] in ("medium", "high")
        ),
        "bet_option": lambda sig: sig["ttg_bet"],
        "stake": 10,
    },
    {
        "name": "CRS-top1",
        "desc": "CRS 最高概率比分",
        "play": "crs",
        "filter": lambda sig: sig["gate_allowed"] and "crs" in sig["allowed_plays"] and sig["crs_top1"] is not None,
        "bet_option": lambda sig: sig["crs_top1"],
        "stake": 2,
    },
    {
        "name": "HAFU-top1",
        "desc": "HAFU 最高概率选项",
        "play": "hafu",
        "filter": lambda sig: sig["gate_allowed"] and sig["hafu_top1"] is not None,
        "bet_option": lambda sig: sig["hafu_top1"],
        "stake": 2,
    },
    {
        "name": "ABC-HAD-any",
        "desc": "只要 had 有方向就买 (对照组)",
        "play": "had",
        "filter": lambda sig: sig["had_bet"] is not None and sig["gate_allowed"] and "had" in sig["allowed_plays"],
        "bet_option": lambda sig: sig["had_bet"],
        "stake": 10,
    },
    {
        "name": "no-bet",
        "desc": "不买 (基准线)",
        "play": None,
        "filter": lambda sig: False,
        "bet_option": lambda sig: None,
        "stake": 0,
    },
]


# ── 信号提取 ────────────────────────────────────────────────────────────────

def extract_match_signals(
    match_info: dict,
    match_id: str,
    sp_history: list[dict],
) -> dict:
    """提取一场比赛的全部信号，供策略过滤。"""
    recommendation = build_match_recommendation(match_info, sp_history, window="open_to_latest")
    had_trend = recommendation.had_trend
    hhad_trend = recommendation.hhad_trend
    ttg_trend = recommendation.ttg_trend
    structure = recommendation.structure

    # HAD 买什么
    had_bet = None
    had_bet_sp = None
    had_confidence = "none"
    if had_trend.available:
        if recommendation.candidates.had_options:
            had_bet = recommendation.candidates.had_options[0]
        d = had_trend.main_direction
        had_confidence = had_trend.direction_confidence
        if had_bet and had_trend.options:
            for opt in had_trend.options:
                if opt.option_code == had_bet:
                    had_bet_sp = opt.sp_end

    # HHAD 是否确认 HAD
    hhad_confirms_had = False
    if had_bet and hhad_trend.available:
        hd = hhad_trend.main_direction
        if had_bet == "H" and "home" in hd:
            hhad_confirms_had = True
        elif had_bet == "A" and "away" in hd:
            hhad_confirms_had = True
        elif had_bet == "D" and "draw" in hd:
            hhad_confirms_had = True

    # TTG 买什么
    ttg_bet = None
    ttg_confidence = "none"
    if ttg_trend.available:
        ttg_confidence = ttg_trend.direction_confidence
        if recommendation.candidates.ttg_options:
            ttg_bet = recommendation.candidates.ttg_options[0]

    # CRS 最高概率
    crs_records = [r for r in sp_history
                   if str(r.get("match_id")) == match_id and r.get("play_type") == "crs"]
    crs_top1 = None
    if recommendation.candidates.crs_options:
        crs_top1 = recommendation.candidates.crs_options[0]
    elif crs_records:
        latest_time = max(str(r.get("snapshot_time", "")) for r in crs_records)
        latest = [r for r in crs_records if str(r.get("snapshot_time", "")) == latest_time]
        if latest:
            best = max(latest, key=lambda r: r.get("implied_prob_norm") or 0)
            crs_top1 = best["option_code"]

    # HAFU 最高概率
    hafu_records = [r for r in sp_history
                    if str(r.get("match_id")) == match_id and r.get("play_type") == "hafu"]
    hafu_top1 = None
    if hafu_records:
        latest_time = max(str(r.get("snapshot_time", "")) for r in hafu_records)
        latest = [r for r in hafu_records if str(r.get("snapshot_time", "")) == latest_time]
        if latest:
            best = max(latest, key=lambda r: r.get("implied_prob_norm") or 0)
            hafu_top1 = best["option_code"]

    return {
        "had_bet": had_bet,
        "had_bet_sp": had_bet_sp,
        "had_confidence": had_confidence,
        "hhad_confirms_had": hhad_confirms_had,
        "ttg_bet": ttg_bet,
        "ttg_confidence": ttg_confidence,
        "crs_top1": crs_top1,
        "hafu_top1": hafu_top1,
        "expression": structure.main_market_expression if structure else "mixed_or_noisy",
        "priority": structure.research_priority if structure else "D",
        "consistency": structure.consistency_level if structure else "none",
        "gate_allowed": recommendation.gate.allowed,
        "allowed_plays": recommendation.gate.allowed_plays,
        "gate_reasons": recommendation.gate.reasons,
    }


# ── 结果判定 ────────────────────────────────────────────────────────────────

def evaluate_bet(
    play: str,
    bet_option: str,
    match: dict,
) -> tuple[bool, str]:
    """判断模拟投注是否命中。返回 (hit, actual_result)。"""
    home = match.get("home_score_90")
    away = match.get("away_score_90")
    if home is None or away is None:
        return False, "no_result"

    home = int(home)
    away = int(away)

    if play == "had":
        actual = "H" if home > away else "A" if home < away else "D"
        return bet_option == actual, actual

    if play == "ttg":
        total = home + away
        actual_option = str(total) if total <= 6 else "7"
        return bet_option == actual_option, actual_option

    if play == "crs":
        actual = f"s{home:02d}s{away:02d}"
        return bet_option == actual, actual

    if play == "hafu":
        half = match.get("half_score")
        if half and ":" in half:
            parts = half.split(":")
            try:
                hh, ha = int(parts[0]), int(parts[1])
            except ValueError:
                return False, "bad_half"
            h_result = "h" if hh > ha else "d" if hh == ha else "a"
            f_result = "h" if home > away else "d" if home == away else "a"
            actual = h_result + f_result
            return bet_option == actual, actual
        return False, "no_half"

    return False, "unsupported"


def get_sp_for_option(
    play: str,
    bet_option: str,
    sp_history: list[dict],
    match_id: str,
) -> float | None:
    """获取买入选项的 SP 值。"""
    records = [r for r in sp_history
               if str(r.get("match_id")) == match_id and r.get("play_type") == play]
    if not records:
        return None

    latest_time = max(str(r.get("snapshot_time", "")) for r in records)
    for r in records:
        if str(r.get("snapshot_time", "")) == latest_time and r.get("option_code") == bet_option:
            return float(r["sp_value"])

    # TTG "low"/"mid"/"high" 需要映射到具体 option
    if play == "ttg":
        return None

    return None


# ── 主逻辑 ──────────────────────────────────────────────────────────────────

def run_backtest(conn, *, detail: bool = False) -> dict:
    """回测所有策略。"""
    # 加载有赛果 + SP 的比赛
    cur = conn.execute("""
        SELECT DISTINCT m.match_id, m.match_num, m.home_team_name, m.away_team_name,
               m.result_90, m.home_score_90, m.away_score_90, m.half_score,
               m.full_score_90
        FROM sporttery_match m
        JOIN sporttery_sp_snapshot s ON s.match_id = m.match_id
        WHERE m.result_90 IS NOT NULL
        ORDER BY m.match_id
    """)
    matches = [dict(zip([d[0] for d in cur.description], row)) for row in cur.fetchall()]

    if not matches:
        print("没有可回测的比赛")
        return {}

    match_ids = [m["match_id"] for m in matches]
    sp_history = db.fetch_all_sp_history(conn, match_ids)

    # 提取每场比赛的信号
    match_signals = {}
    for m in matches:
        mid = m["match_id"]
        match_signals[mid] = extract_match_signals(m, mid, sp_history)

    # 逐策略回测
    strategy_results = []
    for strat in STRATEGIES:
        bets = []
        for m in matches:
            mid = m["match_id"]
            sig = match_signals[mid]

            if not strat["filter"](sig):
                continue

            bet_option = strat["bet_option"](sig)
            if bet_option is None:
                continue

            hit, actual = evaluate_bet(strat["play"], bet_option, m)
            sp = get_sp_for_option(strat["play"], bet_option, sp_history, mid)
            stake = strat["stake"]
            payout = round(sp * stake, 2) if hit and sp else 0.0

            bets.append({
                "match_id": mid,
                "match_info": f"{m['home_team_name']} vs {m['away_team_name']}",
                "score": m.get("full_score_90", "?"),
                "bet_option": bet_option,
                "sp": sp,
                "hit": hit,
                "actual": actual,
                "stake": stake,
                "payout": payout,
                "signal": sig,
            })

        total_stake = sum(b["stake"] for b in bets)
        total_payout = sum(b["payout"] for b in bets)
        hits = sum(1 for b in bets if b["hit"])
        total = len(bets)

        strategy_results.append({
            "name": strat["name"],
            "desc": strat["desc"],
            "play": strat["play"],
            "triggered": total,
            "hits": hits,
            "hit_rate": hits / total if total else 0,
            "total_stake": total_stake,
            "total_payout": total_payout,
            "profit_loss": total_payout - total_stake,
            "roi": (total_payout - total_stake) / total_stake if total_stake else 0,
            "bets": bets,
        })

    return {
        "match_count": len(matches),
        "strategies": strategy_results,
        "matches": matches,
        "match_signals": match_signals,
    }


def print_results(result: dict, *, detail: bool = False) -> None:
    """打印回测结果。"""
    if not result:
        return

    print(f"\n{'=' * 70}")
    print(f"策略回测结果 ({result['match_count']} 场比赛)")
    print(f"{'=' * 70}")

    # 策略汇总表
    print(f"\n{'策略':<20} {'触发':>4} {'命中':>4} {'命中率':>7} {'投入':>6} {'奖金':>8} {'盈亏':>8} {'ROI':>7}")
    print("-" * 70)

    for s in result["strategies"]:
        if s["triggered"] == 0 and s["name"] != "no-bet":
            continue
        hr = f"{s['hit_rate']:.1%}" if s["triggered"] else "---"
        roi = f"{s['roi']:.1%}" if s["total_stake"] else "---"
        print(
            f"{s['name']:<20} {s['triggered']:>4} {s['hits']:>4} {hr:>7} "
            f"{s['total_stake']:>6.0f} {s['total_payout']:>8.2f} "
            f"{s['profit_loss']:>+8.2f} {roi:>7}"
        )

    # 逐策略详情
    if detail:
        for s in result["strategies"]:
            if not s["bets"]:
                continue
            print(f"\n{'─' * 70}")
            print(f"策略: {s['name']} — {s['desc']}")
            print(f"{'─' * 70}")
            for b in s["bets"]:
                mark = "HIT" if b["hit"] else "MISS"
                sp_str = f"{b['sp']:.2f}" if b["sp"] else "?"
                pl = b["payout"] - b["stake"]
                pl_str = f"{pl:+.2f}"
                print(
                    f"  {mark} {b['match_info']:<25} {b['score']:<6} "
                    f"bet={b['bet_option']} sp={sp_str:<5} {pl_str:>7}"
                )

    # 最优策略推荐
    profitable = [s for s in result["strategies"] if s["profit_loss"] > 0 and s["triggered"] >= 3]
    if profitable:
        best = max(profitable, key=lambda s: s["roi"])
        print(f"\n最优策略: {best['name']} — {best['desc']}")
        print(f"  触发 {best['triggered']} 场, 命中 {best['hits']}, ROI {best['roi']:.1%}")


def main():
    parser = argparse.ArgumentParser(description="策略回测")
    parser.add_argument("--detail", action="store_true", help="逐场详情")
    args = parser.parse_args()

    conn = db.get_connection()
    try:
        result = run_backtest(conn, detail=args.detail)
        print_results(result, detail=args.detail)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
