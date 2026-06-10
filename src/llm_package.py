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


def build_llm_package(
    match_info: dict,
    sp_history: list[dict],
    match_detail: dict | None = None,
) -> dict:
    """
    Build a complete LLM package from match data.

    Args:
        match_info: from sporttery_match table
        sp_history: from sporttery_sp_snapshot table (all play types)
        match_detail: optional, from detail APIs (feature, result, etc.)
    """
    now = datetime.now()
    match_time = match_info.get("match_time")
    if isinstance(match_time, str):
        match_time = datetime.strptime(match_time, "%Y-%m-%d %H:%M:%S")

    # ── Time context ─────────────────────────────────────────────────────
    hours_to_kickoff = None
    if match_time:
        delta = match_time - now
        hours_to_kickoff = round(delta.total_seconds() / 3600, 2)

    phase = _classify_phase(hours_to_kickoff, match_info.get("match_status"))

    time_context = {
        "snapshot_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "match_time": match_time.strftime("%Y-%m-%d %H:%M") if match_time else None,
        "hours_to_kickoff": hours_to_kickoff,
        "phase": phase,
    }

    # ── Status control ───────────────────────────────────────────────────
    status = match_info.get("match_status", "")
    tradable = status == "1"
    hard_stop_reason = None
    if not tradable:
        status_map = {"3": "暂停销售", "2": "未开售", "4": "已停售"}
        hard_stop_reason = status_map.get(status, f"状态码={status}")

    status_control = {
        "tradable": tradable,
        "match_status": status,
        "match_status_name": hard_stop_reason or "在售",
        "hard_stop_reason": hard_stop_reason,
    }

    # ── Markets (SP + movement) ──────────────────────────────────────────
    markets = {}
    for play_type, play_name in [("had", "胜平负"), ("hhad", "让球胜平负"), ("ttg", "总进球")]:
        records = [r for r in sp_history if r["play_type"] == play_type]
        if not records:
            continue
        markets[play_type] = _build_market(play_type, records)

    # ── Movement profile ─────────────────────────────────────────────────
    movement_profile = {}
    for play_type in ["had", "hhad"]:
        if play_type in markets:
            mkt = markets[play_type]
            for opt in mkt.get("options", []):
                key = f"{play_type}_{opt['code']}"
                movement_profile[key] = _build_movement(opt)

    # ── Team form ────────────────────────────────────────────────────────
    team_form = {}
    if match_detail:
        team_form = _build_team_form(match_detail)

    # ── Historical context ───────────────────────────────────────────────
    historical_context = {}
    if match_detail:
        historical_context = _build_historical(match_detail)

    # ── Signals ──────────────────────────────────────────────────────────
    signals = _classify_signals(markets, movement_profile, team_form, historical_context, status_control)

    # ── LLM constraints ──────────────────────────────────────────────────
    llm_constraints = {
        "can_recommend_ticket": tradable,
        "reason": hard_stop_reason if not tradable else None,
        "allowed_output": "full_analysis" if tradable else "analysis_only",
        "forbidden_phrases": ["稳赢", "必买", "稳胆", "必中", "无脑"],
    }

    return {
        "match": {
            "match_id": match_info.get("match_id"),
            "match_num": match_info.get("match_num"),
            "league": match_info.get("league_name"),
            "home": match_info.get("home_team_name"),
            "away": match_info.get("away_team_name"),
            "match_time": match_time.strftime("%Y-%m-%d %H:%M") if match_time else None,
        },
        "time_context": time_context,
        "status_control": status_control,
        "markets": markets,
        "movement_profile": movement_profile,
        "team_form": team_form,
        "historical_context": historical_context,
        "signals": signals,
        "llm_constraints": llm_constraints,
    }


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
