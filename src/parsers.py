"""Parse raw API responses into flat record dicts."""

from __future__ import annotations

from datetime import datetime


def parse_match_list(raw: dict) -> list[dict]:
    """
    Extract match basic info from getMatchDataPageListV1 response.

    Returns list of dicts with keys:
        match_id, match_num, league_id, league_name,
        home_team_id, away_team_id, home_team_name, away_team_name,
        match_time, match_status
    """
    matches = []
    for day in raw.get("value", {}).get("matchInfoList", []):
        for m in day.get("subMatchList", []):
            match_time_str = f"{m.get('matchDate', '')} {m.get('matchTime', '')}".strip()
            match_time = None
            if match_time_str and match_time_str != " ":
                try:
                    match_time = datetime.strptime(match_time_str, "%Y-%m-%d %H:%M")
                except ValueError:
                    pass

            matches.append({
                "match_id": str(m.get("matchId", "")),
                "match_num": m.get("matchNumStr", ""),
                "league_id": str(m.get("leagueId", "")),
                "league_name": m.get("leagueAbbName", ""),
                "home_team_id": str(m.get("homeTeamId", "")),
                "away_team_id": str(m.get("awayTeamId", "")),
                "home_team_name": m.get("homeTeamAbbName", ""),
                "away_team_name": m.get("awayTeamAbbName", ""),
                "match_time": match_time,
                "match_status": str(m.get("matchStatus", "")),
            })
    return matches


def parse_fixed_bonus(raw: dict, match_id: str | int) -> list[dict]:
    """
    Extract had / hhad / ttg SP records from getFixedBonusV1 response.

    The API returns SP change history — each list item has its own
    updateDate + updateTime. We use that as snapshot_time.

    Returns flat list of dicts with keys:
        match_id, play_type, option_code, option_name,
        sp_value, goal_line, is_single, snapshot_time
    """
    records = []
    odds = raw.get("value", {}).get("oddsHistory", {})
    match_id = str(match_id)

    # ── single关 map ────────────────────────────────────────────────────────
    single_map = {}
    for s in odds.get("singleList", []):
        pool = s.get("poolCode", "").lower()
        single_map[pool] = s.get("single", 0)

    # ── had (胜平负) ────────────────────────────────────────────────────────
    for item in odds.get("hadList", []):
        snapshot_time = _parse_update_time(item)
        goal_line = item.get("goalLine", "")
        for code, field in [("H", "h"), ("D", "d"), ("A", "a")]:
            sp = _safe_decimal(item.get(field))
            if sp is not None:
                records.append({
                    "match_id": match_id,
                    "play_type": "had",
                    "option_code": code,
                    "option_name": {"H": "主胜", "D": "平", "A": "客胜"}[code],
                    "sp_value": sp,
                    "goal_line": goal_line or None,
                    "is_single": single_map.get("had", 0),
                    "snapshot_time": snapshot_time,
                })

    # ── hhad (让球胜平负) ───────────────────────────────────────────────────
    for item in odds.get("hhadList", []):
        snapshot_time = _parse_update_time(item)
        goal_line = item.get("goalLine", "")
        for code, field in [("H", "h"), ("D", "d"), ("A", "a")]:
            sp = _safe_decimal(item.get(field))
            if sp is not None:
                records.append({
                    "match_id": match_id,
                    "play_type": "hhad",
                    "option_code": code,
                    "option_name": {"H": "让胜", "D": "让平", "A": "让负"}[code],
                    "sp_value": sp,
                    "goal_line": goal_line or None,
                    "is_single": single_map.get("hhad", 0),
                    "snapshot_time": snapshot_time,
                })

    # ── ttg (总进球) ────────────────────────────────────────────────────────
    for item in odds.get("ttgList", []):
        snapshot_time = _parse_update_time(item)
        goal_line = item.get("goalLine", "")
        for i in range(8):
            field = f"s{i}"
            sp = _safe_decimal(item.get(field))
            if sp is not None:
                code = str(i) if i < 7 else "7"
                label = f"{i}球" if i < 7 else "7+球"
                records.append({
                    "match_id": match_id,
                    "play_type": "ttg",
                    "option_code": code,
                    "option_name": label,
                    "sp_value": sp,
                    "goal_line": goal_line or None,
                    "is_single": single_map.get("ttg", 0),
                    "snapshot_time": snapshot_time,
                })

    return records


def parse_result_list(raw: dict) -> list[dict]:
    """
    Extract completed match results from getMatchDataPageListV1(method=result).

    sectionsNo999 is the page's full-time score field. Per project rules this
    is treated as football result over 90 minutes including stoppage time.
    """
    results = []
    for day in raw.get("value", {}).get("matchInfoList", []):
        for m in day.get("subMatchList", []):
            full_score = m.get("sectionsNo999")
            home_score, away_score = _parse_score(full_score)
            result_90 = None
            if home_score is not None and away_score is not None:
                if home_score > away_score:
                    result_90 = "H"
                elif home_score < away_score:
                    result_90 = "A"
                else:
                    result_90 = "D"

            match_time_str = f"{m.get('matchDate', '')} {m.get('matchTime', '')}".strip()
            match_time = None
            if match_time_str and match_time_str != " ":
                try:
                    match_time = datetime.strptime(match_time_str, "%Y-%m-%d %H:%M")
                except ValueError:
                    pass

            results.append({
                "match_id": str(m.get("matchId", "")),
                "match_num": m.get("matchNumStr", ""),
                "league_id": str(m.get("leagueId", "")),
                "league_name": m.get("leagueAbbName", ""),
                "home_team_id": str(m.get("homeTeamId", "")),
                "away_team_id": str(m.get("awayTeamId", "")),
                "home_team_name": m.get("homeTeamAbbName", ""),
                "away_team_name": m.get("awayTeamAbbName", ""),
                "match_time": match_time,
                "match_status": str(m.get("matchStatus", "")),
                "match_status_name": m.get("matchStatusName", ""),
                "half_score": m.get("sectionsNo1"),
                "full_score_90": full_score,
                "home_score_90": home_score,
                "away_score_90": away_score,
                "result_90": result_90,
                "result_source": "sporttery_zqsj",
            })
    return results


def _parse_update_time(item: dict) -> str:
    """Extract updateDate + updateTime as 'YYYY-MM-DD HH:MM:SS'."""
    date = item.get("updateDate", "")
    time_ = item.get("updateTime", "")
    if date and time_:
        return f"{date} {time_}"
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_decimal(val) -> float | None:
    """Convert to float, return None if empty/invalid."""
    if val is None or val == "" or val == "0":
        return None
    try:
        v = float(val)
        return v if v > 0 else None
    except (ValueError, TypeError):
        return None


def _parse_score(score) -> tuple[int | None, int | None]:
    if not isinstance(score, str) or ":" not in score:
        return None, None
    left, right = score.split(":", 1)
    try:
        return int(left), int(right)
    except ValueError:
        return None, None
