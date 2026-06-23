"""
回测每日建议/纯信号预测：按赛前 SP 快照生成建议或预测，再和实际赛果对比。

Usage:
    python -m scripts.backtest_daily_suggestions
    python -m scripts.backtest_daily_suggestions --league 世界杯
    python -m scripts.backtest_daily_suggestions --league 世界杯 --detail
    python -m scripts.backtest_daily_suggestions --league 世界杯 --mode signal
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src import db
from src.recommendation import build_match_recommendation, filter_sp_records_as_of


def _evaluate_suggestion(
    play_type: str,
    selections: tuple[str, ...],
    match: dict,
    *,
    goal_line: str | None = None,
) -> tuple[bool | None, str | None]:
    home = match.get("home_score_90")
    away = match.get("away_score_90")
    if home is None or away is None:
        return None, None

    home = int(home)
    away = int(away)

    if play_type == "had":
        actual = "H" if home > away else "A" if away > home else "D"
        return actual in selections, actual

    if play_type == "hhad":
        if goal_line in (None, ""):
            return None, None
        adjusted_home = home + float(goal_line)
        actual = "H" if adjusted_home > away else "A" if adjusted_home < away else "D"
        return actual in selections, actual

    if play_type == "ttg":
        total = home + away
        actual = str(total) if total <= 6 else "7"
        return actual in selections, actual

    if play_type == "crs":
        actual = f"s{home:02d}s{away:02d}"
        return actual in selections, actual

    if play_type == "hafu":
        actual = _hafu_actual(match)
        if actual is None:
            return None, None
        return actual in selections, actual

    if play_type == "half_result":
        actual = _half_result_actual(match)
        if actual is None:
            return None, None
        return actual in selections, actual

    return None, None


def _settle_suggestion(
    play_type: str,
    selections: tuple[str, ...],
    match: dict,
    sp_history: list[dict],
    *,
    unit_stake: float = 2.0,
) -> dict:
    goal_line = _latest_goal_line(sp_history, play_type)
    hit, actual = _evaluate_suggestion(play_type, selections, match, goal_line=goal_line)
    selected_sps = {
        selection: _latest_option_sp(sp_history, play_type, selection)
        for selection in selections
    }
    if hit is None or any(sp is None for sp in selected_sps.values()):
        return {
            "settleable": False,
            "unit_count": len(selections),
            "stake": 0.0,
            "payout": 0.0,
            "profit": 0.0,
            "selected_sps": selected_sps,
            "goal_line": goal_line,
        }

    stake = round(unit_stake * len(selections), 2)
    payout = 0.0
    if hit is True and actual in selected_sps:
        payout = round(unit_stake * float(selected_sps[actual]), 2)
    return {
        "settleable": True,
        "unit_count": len(selections),
        "stake": stake,
        "payout": payout,
        "profit": round(payout - stake, 2),
        "selected_sps": selected_sps,
        "goal_line": goal_line,
    }


def _settle_single_prediction(
    play_type: str,
    selection: str,
    match: dict,
    sp_history: list[dict],
    *,
    unit_stake: float = 2.0,
) -> dict:
    if play_type == "half_result":
        hit, actual = _evaluate_suggestion(play_type, (selection,), match)
        return {
            "settleable": False,
            "stake": 0.0,
            "payout": 0.0,
            "profit": 0.0,
            "sp": None,
            "hit": hit,
            "actual": actual,
        }

    goal_line = _latest_goal_line(sp_history, play_type)
    hit, actual = _evaluate_suggestion(play_type, (selection,), match, goal_line=goal_line)
    sp_value = _latest_option_sp(sp_history, play_type, selection)
    if hit is None or sp_value is None:
        return {
            "settleable": False,
            "stake": 0.0,
            "payout": 0.0,
            "profit": 0.0,
            "sp": sp_value,
            "hit": hit,
            "actual": actual,
        }

    stake = round(unit_stake, 2)
    payout = round(unit_stake * sp_value, 2) if hit is True else 0.0
    return {
        "settleable": True,
        "stake": stake,
        "payout": payout,
        "profit": round(payout - stake, 2),
        "sp": sp_value,
        "hit": hit,
        "actual": actual,
    }


def _latest_play_snapshot(sp_history: list[dict], play_type: str) -> list[dict]:
    records = [record for record in sp_history if str(record.get("play_type", "")).lower() == play_type]
    if not records:
        return []
    latest_time = max((str(record.get("snapshot_time", "")) for record in records), default="")
    return [record for record in records if str(record.get("snapshot_time", "")) == latest_time]


def _score_from_crs_code(code: str) -> tuple[int, int] | None:
    if not code.startswith("s") or len(code) != 6 or code.startswith("s-1"):
        return None
    try:
        return int(code[1:3]), int(code[4:6])
    except ValueError:
        return None


def _half_score(match: dict) -> tuple[int, int] | None:
    value = match.get("half_score")
    if not isinstance(value, str) or ":" not in value:
        return None
    try:
        home, away = value.split(":", 1)
        return int(home), int(away)
    except ValueError:
        return None


def _half_result_actual(match: dict) -> str | None:
    score = _half_score(match)
    if score is None:
        return None
    home, away = score
    return "H" if home > away else "A" if away > home else "D"


def _hafu_actual(match: dict) -> str | None:
    half = _half_result_actual(match)
    home = match.get("home_score_90")
    away = match.get("away_score_90")
    if half is None or home is None or away is None:
        return None
    home = int(home)
    away = int(away)
    full = "H" if home > away else "A" if away > home else "D"
    return (half + full).lower()


def _predict_had(recommendation, sp_history: list[dict]) -> str | None:
    if recommendation.candidates.had_options:
        return recommendation.candidates.had_options[0]

    latest = _latest_play_snapshot(sp_history, "had")
    if latest:
        best = max(
            latest,
            key=lambda row: (
                row.get("implied_prob_norm") or 0,
                -float(row.get("sp_value") or 999),
            ),
        )
        return str(best.get("option_code"))

    expression = recommendation.structure.main_market_expression
    if expression in {"home_small_win_supported", "home_big_win_supported"}:
        return "H"
    if expression == "away_not_lose_or_small_win_supported":
        return "A"
    return None


def _predict_hafu(sp_history: list[dict]) -> str | None:
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


def _predict_half_result(sp_history: list[dict]) -> str | None:
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


def _predict_crs(recommendation, sp_history: list[dict], had_pred: str | None, ttg_pred: str | None) -> str | None:
    if recommendation.candidates.crs_options:
        return recommendation.candidates.crs_options[0]

    latest = _latest_play_snapshot(sp_history, "crs")
    if not latest or (had_pred is None and ttg_pred is None):
        return None

    allowed_total = int(ttg_pred) if ttg_pred and str(ttg_pred).isdigit() else None
    ranked = sorted(latest, key=lambda row: -(row.get("implied_prob_norm") or 0))
    for row in ranked:
        code = str(row.get("option_code", ""))
        score = _score_from_crs_code(code)
        if score is None:
            continue
        home_goals, away_goals = score
        result = "H" if home_goals > away_goals else "A" if away_goals > home_goals else "D"
        total = home_goals + away_goals
        if had_pred and result != had_pred:
            continue
        if allowed_total is not None and abs(total - allowed_total) > 1:
            continue
        return code

    return None


def _build_forced_predictions(
    recommendation,
    sp_history: list[dict],
    *,
    exclude_high_sp_away: bool = False,
) -> dict[str, str | None]:
    had_pred = _predict_had(recommendation, sp_history)
    if exclude_high_sp_away and had_pred == "A":
        had_sp = _latest_option_sp(sp_history, "had", had_pred)
        if had_sp is not None and had_sp >= 1.60:
            had_pred = None
    ttg_interval = _build_ttg_interval(recommendation, sp_history)
    crs_pred = _predict_crs(recommendation, sp_history, had_pred, ttg_interval[0] if ttg_interval else None)
    hafu_pred = _predict_hafu(sp_history)
    half_result_pred = _predict_half_result(sp_history)
    return {
        "had": had_pred,
        "crs": crs_pred,
        "hafu": hafu_pred,
        "half_result": half_result_pred,
    }


def _play_snapshot_count(sp_history: list[dict], play_type: str) -> int:
    return len({
        str(record.get("snapshot_time", ""))
        for record in sp_history
        if str(record.get("play_type", "")).lower() == play_type
    })


def _build_ttg_interval(recommendation, sp_history: list[dict]) -> tuple[str, ...]:
    if recommendation.candidates.ttg_options:
        return recommendation.candidates.ttg_options

    latest = _latest_play_snapshot(sp_history, "ttg")
    if not latest:
        return ()

    ranked = sorted(
        latest,
        key=lambda row: (
            -(row.get("implied_prob_norm") or 0),
            float(row.get("sp_value") or 999),
        ),
    )
    return tuple(str(row.get("option_code")) for row in ranked[:2])


def _latest_option_sp(sp_history: list[dict], play_type: str, option_code: str) -> float | None:
    latest = _latest_play_snapshot(sp_history, play_type)
    if not latest:
        return None
    for row in latest:
        if str(row.get("option_code")) == option_code:
            try:
                return float(row.get("sp_value"))
            except (TypeError, ValueError):
                return None
    return None


def _latest_goal_line(sp_history: list[dict], play_type: str) -> str | None:
    latest = _latest_play_snapshot(sp_history, play_type)
    if not latest:
        return None
    for row in latest:
        goal_line = row.get("goal_line")
        if goal_line not in (None, ""):
            return str(goal_line)
    return None


def _had_bucket(selection: str | None, sp_value: float | None) -> str | None:
    if selection == "H":
        if sp_value is not None and sp_value < 1.60:
            return "low_sp_home"
        return "mid_high_sp_home"
    if selection == "A":
        if sp_value is not None and sp_value < 1.60:
            return "low_sp_away"
        return "high_sp_away"
    return None


def run_backtest(conn, *, league: str | None = None, mode: str = "signal", unit_stake: float = 2.0) -> dict:
    query = """
        SELECT DISTINCT m.match_id, m.match_num, m.league_name, m.match_time,
               m.home_team_name, m.away_team_name, m.result_90,
               m.home_score_90, m.away_score_90, m.full_score_90, m.half_score
        FROM sporttery_match m
        JOIN sporttery_sp_snapshot s ON s.match_id = m.match_id
        WHERE m.result_90 IS NOT NULL
    """
    params: list[str] = []
    if league:
        query += " AND m.league_name = ?"
        params.append(league)
    query += " ORDER BY m.match_time, m.match_id"

    cur = conn.execute(query, params)
    matches = [dict(zip([d[0] for d in cur.description], row)) for row in cur.fetchall()]
    if not matches:
        return {"match_count": 0, "league": league, "rows": [], "stats": {}}

    match_ids = [str(m["match_id"]) for m in matches]
    all_sp_history = db.fetch_all_sp_history(conn, match_ids)
    history_by_match: dict[str, list[dict]] = {}
    for row in all_sp_history:
        history_by_match.setdefault(str(row.get("match_id")), []).append(row)

    rows = []
    for match in matches:
        match_id = str(match["match_id"])
        prematch_history = filter_sp_records_as_of(history_by_match.get(match_id, []), match.get("match_time"))
        recommendation = build_match_recommendation(match, prematch_history, window="open_to_latest", now_time=match.get("match_time"))
        had_snapshot_count = _play_snapshot_count(prematch_history, "had")
        ttg_snapshot_count = _play_snapshot_count(prematch_history, "ttg")
        crs_available = bool(_latest_play_snapshot(prematch_history, "crs"))
        hafu_available = bool(_latest_play_snapshot(prematch_history, "hafu")) and bool(match.get("half_score"))
        signal_ready = {
            "had": had_snapshot_count >= 2,
            "ttg": ttg_snapshot_count >= 2,
            "crs": crs_available,
            "hafu": hafu_available,
            "half_result": hafu_available,
        }

        if mode == "recommendation":
            prediction_enabled = recommendation.gate.allowed
        else:
            prediction_enabled = signal_ready["had"] or signal_ready["ttg"] or signal_ready["hafu"]

        forced_predictions = _build_forced_predictions(
            recommendation,
            prematch_history,
            exclude_high_sp_away=(mode == "recommendation"),
        ) if prediction_enabled else {
            "had": None,
            "crs": None,
            "hafu": None,
            "half_result": None,
        }
        ttg_interval = _build_ttg_interval(recommendation, prematch_history) if prediction_enabled else ()
        for play_type, ready in signal_ready.items():
            if play_type == "ttg":
                continue
            if not ready:
                forced_predictions[play_type] = None
        if not signal_ready["ttg"]:
            ttg_interval = ()

        suggestion_rows = []
        for suggestion in recommendation.suggestions:
            settlement = _settle_suggestion(
                suggestion.play_type,
                suggestion.selections,
                match,
                prematch_history,
                unit_stake=unit_stake,
            )
            hit, actual = _evaluate_suggestion(
                suggestion.play_type,
                suggestion.selections,
                match,
                goal_line=settlement.get("goal_line"),
            )
            suggestion_rows.append({
                "play_type": suggestion.play_type,
                "selections": suggestion.selections,
                "confidence": suggestion.confidence,
                "reason": suggestion.reason,
                "hit": hit,
                "actual": actual,
                "settlement": settlement,
            })

        prediction_rows = {}
        for play_type, selection in forced_predictions.items():
            if selection is None:
                prediction_rows[play_type] = {"selection": None, "hit": None, "actual": None}
                continue
            settlement = _settle_single_prediction(
                play_type,
                selection,
                match,
                prematch_history,
                unit_stake=unit_stake,
            )
            prediction_rows[play_type] = {
                "selection": selection,
                "hit": settlement["hit"],
                "actual": settlement["actual"],
                "sp": settlement["sp"],
                "settlement": settlement,
            }
        interval_hit, interval_actual = _evaluate_suggestion("ttg", ttg_interval, match) if ttg_interval else (None, None)

        rows.append({
            "match_id": match_id,
            "match_num": match.get("match_num"),
            "league_name": match.get("league_name"),
            "match_time": match.get("match_time"),
            "match_info": f"{match.get('home_team_name')} vs {match.get('away_team_name')}",
            "score": match.get("full_score_90"),
            "half_score": match.get("half_score"),
            "result_90": match.get("result_90"),
            "priority": recommendation.structure.research_priority,
            "market_expression": recommendation.structure.main_market_expression,
            "gate_allowed": recommendation.gate.allowed,
            "gate_reasons": recommendation.gate.reasons,
            "prediction_enabled": prediction_enabled,
            "prediction_mode": mode,
            "signal_ready": signal_ready,
            "suggestions": suggestion_rows,
            "predictions": prediction_rows,
            "ttg_interval": {
                "selections": ttg_interval,
                "hit": interval_hit,
                "actual": interval_actual,
            },
        })

    stats = _compute_stats(rows)
    return {
        "match_count": len(matches),
        "league": league,
        "mode": mode,
        "unit_stake": unit_stake,
        "rows": rows,
        "stats": stats,
    }


def _compute_stats(rows: list[dict]) -> dict:
    stats = {
        "matches_with_suggestions": 0,
        "matches_without_suggestions": 0,
        "play_type": {},
        "suggestion_roi": {
            "tickets": 0,
            "units": 0,
            "stake": 0.0,
            "payout": 0.0,
            "profit": 0.0,
            "missing_sp": 0,
            "play_type": {},
        },
        "prediction_matches": 0,
        "prediction_all_hit_matches": 0,
        "prediction_any_hit_matches": 0,
        "prediction_play_type": {},
        "prediction_roi": {
            "tickets": 0,
            "stake": 0.0,
            "payout": 0.0,
            "profit": 0.0,
            "missing_sp": 0,
            "play_type": {},
        },
        "ttg_interval": {"total": 0, "hits": 0},
        "had_crs_pair": {"total": 0, "both_hit": 0, "had_hit_only": 0, "crs_hit_only": 0},
        "had_buckets": {},
    }
    for row in rows:
        if row["suggestions"]:
            stats["matches_with_suggestions"] += 1
        else:
            stats["matches_without_suggestions"] += 1
        for suggestion in row["suggestions"]:
            bucket = stats["play_type"].setdefault(suggestion["play_type"], {"total": 0, "hits": 0})
            bucket["total"] += 1
            if suggestion["hit"] is True:
                bucket["hits"] += 1
            settlement = suggestion["settlement"]
            roi = stats["suggestion_roi"]
            if not settlement["settleable"]:
                roi["missing_sp"] += 1
                continue
            roi["tickets"] += 1
            roi["units"] += settlement["unit_count"]
            roi["stake"] = round(roi["stake"] + settlement["stake"], 2)
            roi["payout"] = round(roi["payout"] + settlement["payout"], 2)
            roi["profit"] = round(roi["profit"] + settlement["profit"], 2)
            roi_bucket = roi["play_type"].setdefault(
                suggestion["play_type"],
                {"tickets": 0, "units": 0, "stake": 0.0, "payout": 0.0, "profit": 0.0},
            )
            roi_bucket["tickets"] += 1
            roi_bucket["units"] += settlement["unit_count"]
            roi_bucket["stake"] = round(roi_bucket["stake"] + settlement["stake"], 2)
            roi_bucket["payout"] = round(roi_bucket["payout"] + settlement["payout"], 2)
            roi_bucket["profit"] = round(roi_bucket["profit"] + settlement["profit"], 2)
        if row["prediction_enabled"]:
            stats["prediction_matches"] += 1
            pred_hits = []
            all_present = True
            for play_type, payload in row["predictions"].items():
                if not row["signal_ready"].get(play_type):
                    continue
                if payload["selection"] is None:
                    all_present = False
                    continue
                bucket = stats["prediction_play_type"].setdefault(play_type, {"total": 0, "hits": 0})
                bucket["total"] += 1
                if payload["hit"] is True:
                    bucket["hits"] += 1
                    pred_hits.append(True)
                elif payload["hit"] is False:
                    pred_hits.append(False)
                settlement = payload.get("settlement") or {}
                roi = stats["prediction_roi"]
                if settlement.get("settleable"):
                    roi["tickets"] += 1
                    roi["stake"] = round(roi["stake"] + settlement["stake"], 2)
                    roi["payout"] = round(roi["payout"] + settlement["payout"], 2)
                    roi["profit"] = round(roi["profit"] + settlement["profit"], 2)
                    roi_bucket = roi["play_type"].setdefault(
                        play_type,
                        {"tickets": 0, "stake": 0.0, "payout": 0.0, "profit": 0.0},
                    )
                    roi_bucket["tickets"] += 1
                    roi_bucket["stake"] = round(roi_bucket["stake"] + settlement["stake"], 2)
                    roi_bucket["payout"] = round(roi_bucket["payout"] + settlement["payout"], 2)
                    roi_bucket["profit"] = round(roi_bucket["profit"] + settlement["profit"], 2)
                elif play_type != "half_result":
                    roi["missing_sp"] += 1
            if pred_hits and all_present and all(pred_hits):
                stats["prediction_all_hit_matches"] += 1
            if any(pred_hits):
                stats["prediction_any_hit_matches"] += 1
            if row["signal_ready"].get("ttg") and row["ttg_interval"]["selections"]:
                stats["ttg_interval"]["total"] += 1
                if row["ttg_interval"]["hit"] is True:
                    stats["ttg_interval"]["hits"] += 1
            had_payload = row["predictions"].get("had", {})
            crs_payload = row["predictions"].get("crs", {})
            if row["signal_ready"].get("had") and had_payload.get("selection"):
                bucket_name = _had_bucket(had_payload.get("selection"), had_payload.get("sp"))
                if bucket_name:
                    bucket = stats["had_buckets"].setdefault(bucket_name, {"total": 0, "hits": 0})
                    bucket["total"] += 1
                    if had_payload.get("hit") is True:
                        bucket["hits"] += 1
            if row["signal_ready"].get("had") and row["signal_ready"].get("crs") and had_payload.get("selection") and crs_payload.get("selection"):
                stats["had_crs_pair"]["total"] += 1
                had_hit = had_payload.get("hit") is True
                crs_hit = crs_payload.get("hit") is True
                if had_hit and crs_hit:
                    stats["had_crs_pair"]["both_hit"] += 1
                elif had_hit:
                    stats["had_crs_pair"]["had_hit_only"] += 1
                elif crs_hit:
                    stats["had_crs_pair"]["crs_hit_only"] += 1
    return stats


def print_results(result: dict, *, detail: bool = False) -> None:
    league = result["league"] or "全部赛事"
    mode_label = "正式建议回测" if result.get("mode") == "recommendation" else "纯信号回测"
    print(f"\n{'=' * 72}")
    print(f"{mode_label}: {league}  {result['match_count']} 场")
    print(f"{'=' * 72}")

    stats = result["stats"]
    if result.get("mode") == "recommendation":
        print(
            f"形成正式建议: {stats.get('matches_with_suggestions', 0)} 场  |  "
            f"无正式建议: {stats.get('matches_without_suggestions', 0)} 场"
        )
    else:
        print(
            f"有正式建议: {stats.get('matches_with_suggestions', 0)} 场  |  "
            f"无正式建议: {stats.get('matches_without_suggestions', 0)} 场"
        )

    for play_type in ("had", "hhad", "ttg", "crs"):
        bucket = stats.get("play_type", {}).get(play_type)
        if not bucket:
            continue
        total = bucket["total"]
        hits = bucket["hits"]
        print(f"  {play_type.upper():<4} {hits}/{total} = {hits / total:.1%}")

    roi = stats.get("suggestion_roi", {})
    if roi.get("stake"):
        roi_rate = roi["profit"] / roi["stake"]
        print(
            f"\n建议票收益(每选项1注, 单注{result.get('unit_stake', 2):g}元): "
            f"票项 {roi['tickets']}  注数 {roi['units']}  "
            f"投入 {roi['stake']:.2f}  奖金 {roi['payout']:.2f}  "
            f"盈亏 {roi['profit']:+.2f}  ROI {roi_rate:.1%}"
        )
        for play_type in ("had", "hhad", "ttg", "crs"):
            bucket = roi.get("play_type", {}).get(play_type)
            if not bucket:
                continue
            bucket_roi = bucket["profit"] / bucket["stake"] if bucket["stake"] else 0.0
            print(
                f"  {play_type.upper():<4} 票项 {bucket['tickets']}  注数 {bucket['units']}  "
                f"投入 {bucket['stake']:.2f}  奖金 {bucket['payout']:.2f}  "
                f"盈亏 {bucket['profit']:+.2f}  ROI {bucket_roi:.1%}"
            )
        if roi.get("missing_sp"):
            print(f"  未结算票项: {roi['missing_sp']} (缺少赛前 SP 或赛果)")

    prediction_matches = stats.get("prediction_matches", 0)
    if prediction_matches:
        print("\n信号预测统计:")
        print(
            f"  有信号比赛: {prediction_matches} 场  |  "
            f"至少命中1项: {stats.get('prediction_any_hit_matches', 0)} 场  |  "
            f"给出预测项全中: {stats.get('prediction_all_hit_matches', 0)} 场"
        )
        for play_type in ("had", "crs", "hafu", "half_result"):
            bucket = stats.get("prediction_play_type", {}).get(play_type)
            if not bucket:
                continue
            total = bucket["total"]
            hits = bucket["hits"]
            print(f"  预测{play_type.upper():<4} {hits}/{total} = {hits / total:.1%}")
        prediction_roi = stats.get("prediction_roi", {})
        if prediction_roi.get("stake"):
            roi_rate = prediction_roi["profit"] / prediction_roi["stake"]
            print(
                f"  预测项单注收益: 票项 {prediction_roi['tickets']}  "
                f"投入 {prediction_roi['stake']:.2f}  奖金 {prediction_roi['payout']:.2f}  "
                f"盈亏 {prediction_roi['profit']:+.2f}  ROI {roi_rate:.1%}"
            )
            for play_type in ("had", "crs", "hafu"):
                bucket = prediction_roi.get("play_type", {}).get(play_type)
                if not bucket:
                    continue
                bucket_roi = bucket["profit"] / bucket["stake"] if bucket["stake"] else 0.0
                print(
                    f"    {play_type.upper():<4} 票项 {bucket['tickets']}  "
                    f"投入 {bucket['stake']:.2f}  奖金 {bucket['payout']:.2f}  "
                    f"盈亏 {bucket['profit']:+.2f}  ROI {bucket_roi:.1%}"
                )
            crs_bucket = prediction_roi.get("play_type", {}).get("crs")
            if result.get("mode") == "recommendation" and crs_bucket:
                crs_roi = crs_bucket["profit"] / crs_bucket["stake"] if crs_bucket["stake"] else 0.0
                print(
                    f"  正式比分小票(CRS): 票项 {crs_bucket['tickets']}  "
                    f"投入 {crs_bucket['stake']:.2f}  奖金 {crs_bucket['payout']:.2f}  "
                    f"盈亏 {crs_bucket['profit']:+.2f}  ROI {crs_roi:.1%}"
                )
        interval = stats.get("ttg_interval", {})
        if interval.get("total"):
            print(
                f"  TTG区间 {interval['hits']}/{interval['total']} = "
                f"{interval['hits'] / interval['total']:.1%}"
            )
        pair = stats.get("had_crs_pair", {})
        if pair.get("total"):
            print(
                f"  HAD+CRS 联合: 总场次 {pair['total']}  |  "
                f"双中 {pair['both_hit']}  |  HAD单中 {pair['had_hit_only']}  |  "
                f"CRS单中 {pair['crs_hit_only']}"
            )
        had_buckets = stats.get("had_buckets", {})
        if had_buckets:
            print("  HAD分层:")
            label_map = {
                "low_sp_home": "低SP主胜",
                "mid_high_sp_home": "中高SP主胜",
                "low_sp_away": "低SP客胜",
                "high_sp_away": "高SP客胜",
            }
            for key in ("low_sp_home", "low_sp_away", "mid_high_sp_home", "high_sp_away"):
                bucket = had_buckets.get(key)
                if not bucket:
                    continue
                print(f"    {label_map[key]} {bucket['hits']}/{bucket['total']} = {bucket['hits'] / bucket['total']:.1%}")

    if detail:
        print(f"\n{'─' * 72}")
        print("逐场对比")
        print(f"{'─' * 72}")
        for row in result["rows"]:
            if row["suggestions"]:
                suggestion_text = " | ".join(
                    f"{item['play_type']}:{'/'.join(item['selections'])}"
                    f"[{'HIT' if item['hit'] else 'MISS' if item['hit'] is False else '-'}"
                    f"->{item['actual'] or '-'}"
                    f" 投入{item['settlement']['stake']:.2f}"
                    f" 奖金{item['settlement']['payout']:.2f}"
                    f" 盈亏{item['settlement']['profit']:+.2f}]"
                    for item in row["suggestions"]
                )
            else:
                suggestion_text = "-"
            prediction_text = " | ".join(
                f"{play}:{payload['selection'] or '-'}"
                f"[{'HIT' if payload['hit'] else 'MISS' if payload['hit'] is False else '-'}"
                f"->{payload['actual'] or '-'}]"
                for play, payload in row["predictions"].items()
            )
            interval_text = (
                f"{'/'.join(row['ttg_interval']['selections'])}"
                f"[{'HIT' if row['ttg_interval']['hit'] else 'MISS' if row['ttg_interval']['hit'] is False else '-'}"
                f"->{row['ttg_interval']['actual'] or '-'}]"
                if row["signal_ready"].get("ttg") and row["ttg_interval"]["selections"]
                else "-[-->-]"
            )
            signal_text = ",".join(
                play for play, ready in row["signal_ready"].items() if ready
            ) or "-"
            print(
                f"{row['match_num']} {row['match_info']} 半场{row.get('half_score') or '-'} 全场{row['score']} "
                f"优先级:{row['priority']} 表达:{row['market_expression']} "
                f"信号:{signal_text} 建议:{suggestion_text} 预测:{prediction_text} TTG区间:{interval_text}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="回测每日建议 vs 实际赛果")
    parser.add_argument("--league", help="只回测指定赛事，如 世界杯")
    parser.add_argument("--mode", choices=("signal", "recommendation"), default="signal", help="signal=纯信号回测, recommendation=正式建议回测")
    parser.add_argument("--unit-stake", type=float, default=2.0, help="每注金额，默认 2 元")
    parser.add_argument("--detail", action="store_true", help="输出逐场详情")
    args = parser.parse_args()

    conn = db.get_connection()
    try:
        result = run_backtest(conn, league=args.league, mode=args.mode, unit_stake=args.unit_stake)
        print_results(result, detail=args.detail)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
