"""从竞彩比赛详情接口构建非 SP 证据摘要。"""

from __future__ import annotations

from typing import Any


def build_non_sp_evidence(detail_bundle: dict[str, dict]) -> dict[str, Any]:
    """将原始详情接口数据转换为紧凑的、适用于大语言模型的证据包。"""
    team_form = _build_team_form(detail_bundle)
    historical = _build_historical(detail_bundle)
    tables = _build_tables(detail_bundle)
    injuries = _build_injuries(detail_bundle)
    future_matches = _build_future_matches(detail_bundle)
    home_support_score, away_support_score, supporting_factors, risk_factors = _score_non_sp_evidence(
        team_form,
        historical,
        tables,
        injuries,
    )

    return {
        "team_form": team_form,
        "historical": historical,
        "tables": tables,
        "injuries": injuries,
        "future_matches": future_matches,
        "key_signals": _build_key_signals(team_form, historical, tables, injuries),
        "supporting_factors": supporting_factors,
        "risk_factors": risk_factors,
        "home_support_score": home_support_score,
        "away_support_score": away_support_score,
        "non_sp_lean": _lean_from_scores(home_support_score, away_support_score),
        "support_confidence": _support_confidence(home_support_score, away_support_score),
    }


def _build_team_form(detail: dict[str, dict]) -> dict[str, Any]:
    result = detail.get("matchResult", {}).get("value", {})
    form: dict[str, Any] = {}

    for side, key in (("home", "home"), ("away", "away")):
        side_data = result.get(key, {}) if isinstance(result, dict) else {}
        stats = side_data.get("statistics", {}) if isinstance(side_data, dict) else {}
        matches = side_data.get("matchList", []) if isinstance(side_data, dict) else []

        results = []
        team_name = stats.get("teamShortName", "")
        for match in matches[:5]:
            home_name = match.get("homeTeamShortName", "")
            away_name = match.get("awayTeamShortName", "")
            home_goals = _safe_int(match.get("homeTeamFullCourtGoalCnt"))
            away_goals = _safe_int(match.get("awayTeamFullCourtGoalCnt"))

            if home_name == team_name:
                team_goals, opponent_goals, opponent = home_goals, away_goals, away_name
            else:
                team_goals, opponent_goals, opponent = away_goals, home_goals, home_name

            results.append({
                "date": match.get("matchDate"),
                "opponent": opponent,
                "team_goals": team_goals,
                "opponent_goals": opponent_goals,
                "result": match.get("teamMatchResult"),
                "tournament": match.get("tournamentShortName"),
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

    feature = detail.get("matchFeature", {}).get("value", {})
    if isinstance(feature, dict) and feature:
        each = feature.get("eachHomeAway", {})
        form["feature"] = {
            "home_last10": _fmt_record(each, "home"),
            "away_last10": _fmt_record(each, "away"),
            "home_goal_avg": _coalesce(
                feature.get("goalAvg", {}).get("homeGoalAvgCnt"),
                feature.get("goalAvg", {}).get("homeGoalAvg"),
            ),
            "away_goal_avg": _coalesce(
                feature.get("goalAvg", {}).get("awayGoalAvgCnt"),
                feature.get("goalAvg", {}).get("awayGoalAvg"),
            ),
            "home_loss_avg": _coalesce(
                feature.get("lossGoalAvg", {}).get("homeLossGoalAvgCnt"),
                feature.get("lossGoalAvg", {}).get("homeLossGoalAvg"),
            ),
            "away_loss_avg": _coalesce(
                feature.get("lossGoalAvg", {}).get("awayLossGoalAvgCnt"),
                feature.get("lossGoalAvg", {}).get("awayLossGoalAvg"),
            ),
        }

    return form


def _build_historical(detail: dict[str, dict]) -> dict[str, Any]:
    hist = detail.get("resultHistory", {}).get("value", {})
    stats = hist.get("statistics", {}) if isinstance(hist, dict) else {}
    matches = []
    for match in hist.get("matchList", [])[:5] if isinstance(hist, dict) else []:
        matches.append({
            "date": match.get("matchDate"),
            "tournament": match.get("tournamentShortName"),
            "home": match.get("homeTeamShortName"),
            "away": match.get("awayTeamShortName"),
            "score": match.get("fullCourtGoal"),
            "result": match.get("winningTeam"),
        })

    same_odds = detail.get("sameOdds", {}).get("value", {})
    return {
        "h2h_matches": matches,
        "h2h_count": stats.get("totalLegCnt", 0),
        "h2h_home_win_pct": stats.get("winProbability"),
        "h2h_draw_pct": stats.get("drawProbability"),
        "h2h_away_win_pct": stats.get("lossProbability"),
        "same_odds_count": same_odds.get("totalLegCnt", 0) if isinstance(same_odds, dict) else 0,
        "same_odds_home_win_pct": same_odds.get("winProbability") if isinstance(same_odds, dict) else None,
    }


def _build_tables(detail: dict[str, dict]) -> dict[str, Any]:
    value = detail.get("matchTables", {}).get("value", {})
    if not isinstance(value, dict):
        return {}
    home_rank = _find_rank_entry(value, ("home", "host"))
    away_rank = _find_rank_entry(value, ("away", "guest", "visit"))
    return {
        "home_rank": home_rank,
        "away_rank": away_rank,
    }


def _build_injuries(detail: dict[str, dict]) -> dict[str, Any]:
    value = detail.get("injurySuspension", {}).get("value", {})
    if not isinstance(value, dict):
        return {}
    home_items = _extract_people_list(value, ("home", "host"))
    away_items = _extract_people_list(value, ("away", "guest", "visit"))
    return {
        "home_count": len(home_items),
        "away_count": len(away_items),
        "home_items": home_items[:5],
        "away_items": away_items[:5],
    }


def _build_future_matches(detail: dict[str, dict]) -> dict[str, Any]:
    value = detail.get("futureMatches", {}).get("value", {})
    if not isinstance(value, dict):
        return {}
    return {
        "home_next": _extract_match_list(value, ("home", "host")),
        "away_next": _extract_match_list(value, ("away", "guest", "visit")),
    }


def _build_key_signals(team_form: dict[str, Any], historical: dict[str, Any], tables: dict[str, Any], injuries: dict[str, Any]) -> list[str]:
    signals: list[str] = []
    home = team_form.get("home", {})
    away = team_form.get("away", {})
    feature = team_form.get("feature", {})

    if home.get("win_pct") and _pct_value(home["win_pct"]) >= 60:
        signals.append(f"主队近5场胜率{home['win_pct']}")
    if away.get("loss_pct") and _pct_value(away["loss_pct"]) >= 40:
        signals.append(f"客队近5场败率{away['loss_pct']}")
    if feature.get("home_loss_avg") and _safe_float(feature["home_loss_avg"]) is not None and _safe_float(feature["home_loss_avg"]) < 0.8:
        signals.append(f"主队近10场场均失球{feature['home_loss_avg']}")
    if feature.get("away_loss_avg") and _safe_float(feature["away_loss_avg"]) is not None and _safe_float(feature["away_loss_avg"]) > 1.2:
        signals.append(f"客队近10场场均失球{feature['away_loss_avg']}")
    if historical.get("h2h_count", 0):
        signals.append(f"历史交锋样本{historical['h2h_count']}场")
    if tables.get("home_rank") and tables.get("away_rank"):
        hr = tables["home_rank"].get("rank")
        ar = tables["away_rank"].get("rank")
        if hr is not None and ar is not None:
            signals.append(f"排名对比 主{hr} / 客{ar}")
    if injuries.get("home_count") or injuries.get("away_count"):
        signals.append(f"伤停数量 主{injuries.get('home_count', 0)} / 客{injuries.get('away_count', 0)}")
    return signals


def _score_non_sp_evidence(
    team_form: dict[str, Any],
    historical: dict[str, Any],
    tables: dict[str, Any],
    injuries: dict[str, Any],
) -> tuple[int, int, list[str], list[str]]:
    home_score = 0
    away_score = 0
    supporting: list[str] = []
    risks: list[str] = []

    home = team_form.get("home", {})
    away = team_form.get("away", {})
    feature = team_form.get("feature", {})

    if _pct_value(home.get("win_pct")) >= 60:
        home_score += 2
        supporting.append(f"主队近5场胜率{home['win_pct']}")
    if _pct_value(away.get("loss_pct")) >= 40:
        home_score += 1
        supporting.append(f"客队近5场败率{away['loss_pct']}")
    if _pct_value(away.get("win_pct")) >= 60:
        away_score += 2
        supporting.append(f"客队近5场胜率{away['win_pct']}")
    if _pct_value(home.get("loss_pct")) >= 40:
        away_score += 1
        supporting.append(f"主队近5场败率{home['loss_pct']}")

    home_loss_avg = _safe_float(feature.get("home_loss_avg"))
    away_loss_avg = _safe_float(feature.get("away_loss_avg"))
    if home_loss_avg is not None and home_loss_avg < 0.8:
        home_score += 1
        supporting.append(f"主队近10场场均失球{feature['home_loss_avg']}")
    if away_loss_avg is not None and away_loss_avg > 1.2:
        home_score += 1
        supporting.append(f"客队近10场场均失球{feature['away_loss_avg']}")
    if away_loss_avg is not None and away_loss_avg < 0.8:
        away_score += 1
        supporting.append(f"客队近10场场均失球{feature['away_loss_avg']}")
    if home_loss_avg is not None and home_loss_avg > 1.2:
        away_score += 1
        supporting.append(f"主队近10场场均失球{feature['home_loss_avg']}")

    home_rank = (tables.get("home_rank") or {}).get("rank")
    away_rank = (tables.get("away_rank") or {}).get("rank")
    if home_rank is not None and away_rank is not None:
        if home_rank < away_rank:
            home_score += 1
            supporting.append(f"排名优势 主{home_rank} / 客{away_rank}")
        elif away_rank < home_rank:
            away_score += 1
            supporting.append(f"排名优势 客{away_rank} / 主{home_rank}")

    home_injuries = injuries.get("home_count", 0)
    away_injuries = injuries.get("away_count", 0)
    if away_injuries >= home_injuries + 2:
        home_score += 1
        supporting.append(f"客队伤停更多 主{home_injuries} / 客{away_injuries}")
    elif home_injuries >= away_injuries + 2:
        away_score += 1
        supporting.append(f"主队伤停更多 主{home_injuries} / 客{away_injuries}")

    h2h_count = historical.get("h2h_count", 0)
    home_h2h = _pct_value(historical.get("h2h_home_win_pct"))
    away_h2h = _pct_value(historical.get("h2h_away_win_pct"))
    if h2h_count >= 3:
        if home_h2h >= 50:
            home_score += 1
            supporting.append(f"历史交锋主队占优 {historical.get('h2h_home_win_pct')}")
        elif away_h2h >= 50:
            away_score += 1
            supporting.append(f"历史交锋客队占优 {historical.get('h2h_away_win_pct')}")
    elif h2h_count <= 1:
        risks.append("历史交锋样本不足")

    if historical.get("same_odds_count", 0) == 0:
        risks.append("同奖历史样本不足")
    if home_injuries + away_injuries >= 4:
        risks.append("双方伤停总量较高")

    return home_score, away_score, supporting, risks


def _lean_from_scores(home_score: int, away_score: int) -> str:
    if home_score >= away_score + 2:
        return "home"
    if away_score >= home_score + 2:
        return "away"
    return "neutral"


def _support_confidence(home_score: int, away_score: int) -> str:
    gap = abs(home_score - away_score)
    top = max(home_score, away_score)
    if gap >= 3 and top >= 4:
        return "high"
    if gap >= 2 and top >= 3:
        return "medium"
    if gap >= 1 and top >= 2:
        return "low"
    return "none"


def _fmt_record(data: dict, side: str) -> str:
    if not isinstance(data, dict):
        return "0胜0平0负"
    w = data.get(f"{side}WinGoalMatchCnt", 0)
    d = data.get(f"{side}DrawMatchCnt", 0)
    l = data.get(f"{side}LossGoalMatchCnt", 0)
    return f"{w}胜{d}平{l}负"


def _find_rank_entry(value: dict[str, Any], side_tokens: tuple[str, ...]) -> dict[str, Any] | None:
    for key, data in value.items():
        lower = str(key).lower()
        if any(token in lower for token in side_tokens):
            entry = _normalize_rank_entry(data)
            if entry:
                return entry
    return None


def _normalize_rank_entry(data: Any) -> dict[str, Any] | None:
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                rank = _first_present(item, ("rank", "ranking", "serialNo", "sort"))
                team = _first_present(item, ("teamShortName", "teamName", "name"))
                points = _first_present(item, ("integral", "score", "points"))
                if rank is not None or team is not None or points is not None:
                    return {"team": team, "rank": _safe_int(rank), "points": points}
        return None
    if isinstance(data, dict):
        rank = _first_present(data, ("rank", "ranking", "serialNo", "sort"))
        team = _first_present(data, ("teamShortName", "teamName", "name"))
        points = _first_present(data, ("integral", "score", "points"))
        if rank is not None or team is not None or points is not None:
            return {"team": team, "rank": _safe_int(rank), "points": points}
    return None


def _extract_people_list(value: dict[str, Any], side_tokens: tuple[str, ...]) -> list[dict[str, Any]]:
    for key, data in value.items():
        lower = str(key).lower()
        if not any(token in lower for token in side_tokens):
            continue
        if isinstance(data, list):
            return [_normalize_person(item) for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            for inner in data.values():
                if isinstance(inner, list):
                    return [_normalize_person(item) for item in inner if isinstance(item, dict)]
    return []


def _normalize_person(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": _first_present(item, ("playerName", "name", "playerShortName")),
        "reason": _first_present(item, ("reason", "injuryReason", "status")),
        "position": _first_present(item, ("position", "positionName")),
    }


def _extract_match_list(value: dict[str, Any], side_tokens: tuple[str, ...]) -> list[dict[str, Any]]:
    for key, data in value.items():
        lower = str(key).lower()
        if not any(token in lower for token in side_tokens):
            continue
        candidates = data if isinstance(data, list) else next((v for v in data.values() if isinstance(v, list)), [])
        output = []
        for match in candidates[:3]:
            if not isinstance(match, dict):
                continue
            output.append({
                "date": _first_present(match, ("matchDate", "date")),
                "opponent": _first_present(match, ("againstTeamName", "opponent", "awayTeamShortName", "homeTeamShortName")),
                "tournament": _first_present(match, ("tournamentShortName", "leagueName", "matchName")),
            })
        return output
    return []


def _first_present(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct_value(value: Any) -> float:
    """解析百分比字符串（如 '60' 或 '60%'），并限制在 [0, 100] 范围内。"""
    text = str(value).strip().replace("%", "")
    try:
        v = float(text)
    except ValueError:
        return 0.0
    return max(0.0, min(100.0, v))


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None
