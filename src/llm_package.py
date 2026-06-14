"""
Generate structured LLM analysis packages from raw match data.

Output format designed for LLM consumption:
- Separates facts from interpretation
- Enforces hard stops on suspended matches
- Provides movement profiles (not just raw change)
- Adds time context for proper weighting
"""

from __future__ import annotations

from datetime import datetime

from src.structure_analysis import analyze_match_windows


def build_market_structure_llm_package(
    match_info: dict,
    sp_history: list[dict],
    *,
    windows: list[str] | tuple[str, ...] | None = None,
    debug: bool = False,
) -> dict:
    """
    Build the new LLM input package centered on market_structure.

    LLMs should consume this structure instead of inferring trends directly from
    raw SP rows.
    """
    result = analyze_match_windows(
        match_info,
        sp_history,
        windows=tuple(windows) if windows else ("open_to_latest", "last_24h", "last_6h", "last_1h"),
        include_debug=debug,
    )
    return result["llm_input"]


def build_llm_package(
    match_info: dict,
    sp_history: list[dict],
    match_detail: dict | None = None,
) -> dict:
    """Compatibility wrapper for the new market-structure-centered package."""
    del match_detail
    return build_market_structure_llm_package(match_info, sp_history)


# ── Internal builders ───────────────────────────────────────────────────────


def _classify_phase(hours: float | None, status: str | None) -> str:
    """Classify match phase by hours to kickoff (pure time dimension)."""
    if status == "4" or (hours is not None and hours < 0):
        return "closed_or_result"
    if hours is None:
        return "unknown"
    if hours > 24:
        return "early_pre_match"
    if hours > 3:
        return "pre_match"
    return "late_pre_match"


def _build_market(play_type: str, records: list[dict]) -> dict:
    """Build market summary with history and movement."""
    # Group by snapshot_time
    snapshots: dict[str, list[dict]] = {}
    for r in records:
        t = r.get("snapshot_time", "")
        snapshots.setdefault(t, []).append(r)

    times = sorted(snapshots.keys())
    if not times:
        return {}

    # First and last snapshot
    first_snap = {r["option_code"]: r for r in snapshots[times[0]]}
    last_snap = {r["option_code"]: r for r in snapshots[times[-1]]}

    goal_line = None
    options = []
    for code in sorted(last_snap.keys()):
        r = last_snap[code]
        first_r = first_snap.get(code, {})

        sp_change = None
        prob_change = None
        if first_r and first_r.get("sp_value"):
            sp_change = round(r["sp_value"] - first_r["sp_value"], 4)
            if first_r.get("implied_prob_norm") and r.get("implied_prob_norm"):
                prob_change = round(r["implied_prob_norm"] - first_r["implied_prob_norm"], 4)

        options.append({
            "code": code,
            "name": r.get("option_name", code),
            "current_sp": r["sp_value"],
            "current_prob": r.get("implied_prob_norm"),
            "open_sp": first_r.get("sp_value"),
            "open_prob": first_r.get("implied_prob_norm"),
            "sp_change": sp_change,
            "prob_change": prob_change,
            "snapshot_count": len([s for s in snapshots.values() if any(x["option_code"] == code for x in s)]),
        })

        if r.get("goal_line"):
            goal_line = r["goal_line"]

    # Low price options for ttg
    low_price = []
    if play_type == "ttg":
        opts_with_prob = [(o["code"], o["current_prob"] or 0) for o in options]
        opts_with_prob.sort(key=lambda x: -x[1])
        cumulative = 0
        for code, prob in opts_with_prob:
            low_price.append(code)
            cumulative += prob
            if cumulative >= 0.45:
                break

    return {
        "play_type": play_type,
        "goal_line": goal_line,
        "snapshot_times": times,
        "snapshot_count": len(times),
        "options": options,
        "low_price_options": low_price if play_type == "ttg" else None,
    }


def _build_movement(opt: dict) -> dict:
    """Build movement profile for a single option."""
    sp_change = opt.get("sp_change") or 0
    prob_change = opt.get("prob_change") or 0

    if abs(sp_change) < 0.05:
        pattern = "stable"
        volatility = "low"
    elif abs(sp_change) < 0.2:
        pattern = "gradual"
        volatility = "low"
    elif abs(sp_change) < 0.5:
        pattern = "moderate"
        volatility = "medium"
    else:
        pattern = "sharp"
        volatility = "high"

    direction = "down" if sp_change < 0 else "up" if sp_change > 0 else "flat"

    return {
        "direction": direction,
        "pattern": pattern,
        "volatility": volatility,
        "sp_change": sp_change,
        "sp_change_pct": round(sp_change / opt["open_sp"], 4) if opt.get("open_sp") else None,
        "prob_change": prob_change,
        "snapshot_count": opt.get("snapshot_count", 0),
    }


def _build_team_form(detail: dict) -> dict:
    """Build team form from matchResult API."""
    result = detail.get("matchResult", {}).get("value", {})
    form = {}

    for side, key in [("home", "home"), ("away", "away")]:
        side_data = result.get(key, {})
        stats = side_data.get("statistics", {})
        matches = side_data.get("matchList", [])

        results = []
        for m in matches[:5]:
            # Score perspective: fullCourtGoal is "home:away"
            home_goals = m.get("homeTeamFullCourtGoalCnt", "")
            away_goals = m.get("awayTeamFullCourtGoalCnt", "")
            home_name = m.get("homeTeamShortName", "")
            away_name = m.get("awayTeamShortName", "")

            # Determine this team's goals
            team_name = side_data.get("statistics", {}).get("teamShortName", "")
            if home_name == team_name:
                team_goals = int(home_goals) if home_goals else None
                opp_goals = int(away_goals) if away_goals else None
                opponent = away_name
            else:
                team_goals = int(away_goals) if away_goals else None
                opp_goals = int(home_goals) if home_goals else None
                opponent = home_name

            results.append({
                "date": m.get("matchDate"),
                "opponent": opponent,
                "team_goals": team_goals,
                "opponent_goals": opp_goals,
                "half_time": m.get("halfTimeGoal"),
                "result": m.get("teamMatchResult"),
                "tournament": m.get("tournamentShortName"),
            })

        form[side] = {
            "team": stats.get("teamShortName"),
            "last5_record": f"{stats.get('winGoalMatchCnt', 0)}胜{stats.get('drawMatchCnt', 0)}平{stats.get('lossGoalMatchCnt', 0)}负",
            "win_pct": stats.get("winProbability"),
            "draw_pct": stats.get("drawProbability"),
            "loss_pct": stats.get("lossProbability"),
            "goals_for": stats.get("goalCnt"),
            "goals_against": stats.get("lossGoalCnt"),
            "net_goals": stats.get("netGoal"),
            "results": results,
        }

    # Feature data
    feature = detail.get("matchFeature", {}).get("value", {})
    if feature:
        form["feature"] = {
            "home_last10": _fmt_record(feature.get("eachHomeAway", {}), "home"),
            "away_last10": _fmt_record(feature.get("eachHomeAway", {}), "away"),
            "home_goal_avg": feature.get("goalAvg", {}).get("homeGoalAvgCnt"),
            "away_goal_avg": feature.get("goalAvg", {}).get("awayGoalAvgCnt"),
            "home_loss_avg": feature.get("lossGoalAvg", {}).get("homeLossGoalAvgCnt"),
            "away_loss_avg": feature.get("lossGoalAvg", {}).get("awayLossGoalAvgCnt"),
        }

    return form


def _fmt_record(data: dict, side: str) -> str:
    """Format record string from feature data."""
    w = data.get(f"{side}WinGoalMatchCnt", 0)
    d = data.get(f"{side}DrawMatchCnt", 0)
    l = data.get(f"{side}LossGoalMatchCnt", 0)
    return f"{w}胜{d}平{l}负"


def _build_historical(detail: dict) -> dict:
    """Build historical context."""
    hist = detail.get("resultHistory", {}).get("value", {})
    h2h = hist.get("matchList", [])
    stats = hist.get("statistics", {})

    matches = []
    for m in h2h[:5]:
        matches.append({
            "date": m.get("matchDate"),
            "tournament": m.get("tournamentShortName"),
            "home": m.get("homeTeamShortName"),
            "away": m.get("awayTeamShortName"),
            "score": m.get("fullCourtGoal"),
            "half_time": m.get("halfTimeGoal"),
            "result": m.get("winningTeam"),
        })

    same_odds = detail.get("sameOdds", {}).get("value", {})

    return {
        "h2h_matches": matches,
        "h2h_count": stats.get("totalLegCnt", 0),
        "h2h_home_win_pct": stats.get("winProbability"),
        "h2h_draw_pct": stats.get("drawProbability"),
        "h2h_away_win_pct": stats.get("lossProbability"),
        "same_odds_count": same_odds.get("totalLegCnt", 0),
        "same_odds_home_win_pct": same_odds.get("winProbability"),
    }


def _classify_signals(markets, movement, team_form, historical, status_control) -> dict:
    """Classify data into positive, negative, structure, and uncertainty signals."""
    positive = []
    negative = []
    structure = []
    uncertainty = []

    # ── Status ───────────────────────────────────────────────────────────
    if not status_control.get("tradable"):
        uncertainty.append(f"比赛当前{status_control.get('match_status_name', '未知状态')}，不能形成投注动作")

    # ── Had movement ─────────────────────────────────────────────────────
    had = markets.get("had", {})
    if had:
        opts = {o["code"]: o for o in had.get("options", [])}
        h = opts.get("H", {})
        if h.get("sp_change") and h["sp_change"] < 0:
            positive.append(f"胜平负主胜SP下降{abs(h['sp_change']):.2f}，方向增强")
        if h.get("prob_change") and h["prob_change"] > 0.02:
            positive.append(f"主胜归一化概率提升{h['prob_change']:.1%}")

    # ── Hhad movement ────────────────────────────────────────────────────
    hhad = markets.get("hhad", {})
    if hhad:
        opts = {o["code"]: o for o in hhad.get("options", [])}
        h = opts.get("H", {})
        if h.get("sp_change") and h["sp_change"] < 0:
            positive.append(f"让球让胜SP下降{abs(h['sp_change']):.2f}，赢球幅度预期增强")
        # Check if hhad and had agree
        had_h = {o["code"]: o for o in had.get("options", [])}.get("H", {})
        if h.get("sp_change", 0) < 0 and had_h.get("sp_change", 0) < 0:
            positive.append("胜平负与让球胜平负方向一致")
        # Check if hhad prob is not very high
        if h.get("current_prob") and h["current_prob"] < 0.45:
            negative.append(f"让胜归一化概率仅{h['current_prob']:.1%}，未达到强确定性水平")

    # ── Ttg ──────────────────────────────────────────────────────────────
    ttg = markets.get("ttg", {})
    if ttg:
        low = ttg.get("low_price_options", [])
        if low:
            opts = {o["code"]: o for o in ttg.get("options", [])}
            total_prob = sum((opts.get(c, {}).get("current_prob") or 0) for c in low)
            if total_prob > 0.4:
                structure.append(f"总进球低赔集中在{'/'.join(low)}球({total_prob:.1%})，偏向中低比分结构")

    # ── Crs (比分) ──────────────────────────────────────────────────────
    crs = markets.get("crs", {})
    if crs:
        opts = crs.get("options", [])

        # 1. 低赔比分集中度
        opts_with_prob = [(o["code"], o.get("current_prob") or 0) for o in opts]
        opts_with_prob.sort(key=lambda x: -x[1])
        top_codes = []
        cumulative = 0
        for code, prob in opts_with_prob[:5]:
            top_codes.append(code)
            cumulative += prob
            if cumulative > 0.4:
                break
        if cumulative > 0.4 and len(top_codes) >= 3:
            name_map = {o["code"]: o.get("option_name", o["code"]) for o in opts}
            names = [name_map.get(c, c) for c in top_codes]
            structure.append(f"比分低赔集中在{'/'.join(names)}({cumulative:.1%})，偏向特定比分结构")

        # 2. 主胜其他 vs 客胜其他
        opts_dict = {o["code"]: o for o in opts}
        sh = opts_dict.get("s-1sh", {})
        sa = opts_dict.get("s-1sa", {})
        sh_prob = sh.get("current_prob") or 0
        sa_prob = sa.get("current_prob") or 0
        if sh_prob > 0 and sa_prob > 0:
            if sh_prob > sa_prob * 1.5:
                positive.append("主胜其他概率高于客胜其他，大比分偏向主队")
            elif sa_prob > sh_prob * 1.5:
                negative.append("客胜其他概率高于主胜其他，大比分偏向客队")

        # 3. 具体比分 SP 变化
        sp_changes = []
        for o in opts:
            if o.get("sp_change") and o.get("open_sp"):
                pct = abs(o["sp_change"]) / o["open_sp"]
                if pct > 0.10:
                    sp_changes.append((o["code"], o.get("option_name", o["code"]), o["sp_change"], pct))
        if sp_changes:
            sp_changes.sort(key=lambda x: -x[3])
            for code, name, change, pct in sp_changes[:2]:
                positive.append(f"比分 {name} SP 下降{pct:.1%}，市场预期增强")

    # ── Hafu (半全场) ───────────────────────────────────────────────────
    hafu = markets.get("hafu", {})
    if hafu:
        opts = {o["code"]: o for o in hafu.get("options", [])}

        # 1. 主/主（hh）概率
        hh = opts.get("hh", {})
        hh_prob = hh.get("current_prob") or 0
        if hh_prob > 0.25:
            positive.append(f"半全场主/主概率{hh_prob:.1%}，支持主队全程领先")

        # 2. 半场平局结构
        dh_prob = opts.get("dh", {}).get("current_prob") or 0
        dd_prob = opts.get("dd", {}).get("current_prob") or 0
        da_prob = opts.get("da", {}).get("current_prob") or 0
        half_draw = dh_prob + dd_prob + da_prob
        if half_draw > 0.40:
            structure.append(f"半场平局概率{half_draw:.1%}，比赛可能前半场胶着")

        # 3. 全场主胜结构
        ah_prob = opts.get("ah", {}).get("current_prob") or 0
        full_home = hh_prob + dh_prob + ah_prob
        if full_home > 0.50:
            positive.append(f"全场主胜概率{full_home:.1%}，主队获胜预期较强")

        # 4. hafu 与 had 方向一致性
        had_h = {o["code"]: o for o in had.get("options", [])}.get("H", {})
        if hh_prob > 0.25 and had_h.get("sp_change", 0) < 0:
            positive.append("半全场与胜平负方向一致，主队优势明显")

    # ── Team form ────────────────────────────────────────────────────────
    home_form = team_form.get("home", {})
    away_form = team_form.get("away", {})
    if home_form.get("win_pct") and int(home_form["win_pct"].replace("%", "")) >= 60:
        positive.append(f"主队近5场胜率{home_form['win_pct']}")
    if away_form.get("loss_pct") and int(away_form["loss_pct"].replace("%", "")) >= 40:
        positive.append(f"客队近5场败率{away_form['loss_pct']}")

    feature = team_form.get("feature", {})
    if feature.get("home_loss_avg") and float(feature["home_loss_avg"]) < 0.5:
        positive.append(f"主队近10场场均失球{feature['home_loss_avg']}，防守突出")
    if feature.get("away_loss_avg") and float(feature["away_loss_avg"]) > 1.0:
        positive.append(f"客队近10场场均失球{feature['away_loss_avg']}，防守薄弱")

    # ── Historical ───────────────────────────────────────────────────────
    if historical.get("h2h_count", 0) <= 1:
        uncertainty.append(f"历史交锋仅{historical.get('h2h_count', 0)}场，参考价值低")
    if historical.get("same_odds_count", 0) == 0:
        uncertainty.append("同奖历史样本为0，无法用同奖回查验证")

    # ── Movement volatility ──────────────────────────────────────────────
    for key, prof in movement.items():
        if prof.get("volatility") == "high":
            uncertainty.append(f"{key} SP波动较大({prof.get('pattern', '')})，需关注是否为临场异动")

    return {
        "positive_signals": positive,
        "negative_signals": negative,
        "structure_signals": structure,
        "uncertainty_flags": uncertainty,
    }
