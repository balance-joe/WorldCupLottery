"""Parse raw API responses into flat record dicts."""

from __future__ import annotations

from datetime import datetime


# ── Schema validation ─────────────────────────────────────────────────────────

_MATCH_REQUIRED_TOP = {"value"}
_MATCH_REQUIRED_VALUE = {"matchInfoList"}
_MATCH_REQUIRED_SUB = {
    "matchId", "matchDate", "matchTime",
    "homeTeamAbbName", "awayTeamAbbName",
}

_FIXED_BONUS_REQUIRED_TOP = {"value"}
_FIXED_BONUS_REQUIRED_VALUE = {"oddsHistory"}


def validate_match_list_schema(raw: dict) -> list[str]:
    """Check top-level structure of a matchList response.

    Returns a list of human-readable warnings; empty means valid.
    """
    warnings: list[str] = []
    for key in _MATCH_REQUIRED_TOP:
        if key not in raw:
            warnings.append(f"matchList: missing top-level key '{key}'")
            return warnings  # can't go deeper

    value = raw["value"]
    for key in _MATCH_REQUIRED_VALUE:
        if key not in value:
            warnings.append(f"matchList.value: missing key '{key}'")

    for day in value.get("matchInfoList", []):
        for m in day.get("subMatchList", []):
            for key in _MATCH_REQUIRED_SUB:
                if key not in m:
                    warnings.append(f"matchList.subMatch item: missing '{key}'")
                    break  # one warning per match is enough
            break  # only validate first match to avoid flooding
        break

    return warnings


def validate_fixed_bonus_schema(raw: dict, match_id: str | int) -> list[str]:
    """Check top-level structure of a fixedBonus response.

    Returns a list of human-readable warnings; empty means valid.
    """
    warnings: list[str] = []
    for key in _FIXED_BONUS_REQUIRED_TOP:
        if key not in raw:
            warnings.append(f"fixedBonus({match_id}): missing top-level key '{key}'")
            return warnings

    value = raw["value"]
    for key in _FIXED_BONUS_REQUIRED_VALUE:
        if key not in value:
            warnings.append(f"fixedBonus({match_id}).value: missing key '{key}'")

    return warnings


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

    # ── crs (比分) ────────────────────────────────────────────────────────
    for item in odds.get("crsList", []):
        records.extend(parse_crs(item, match_id, single_map))

    # ── hafu (半全场) ─────────────────────────────────────────────────────
    for item in odds.get("hafuList", []):
        records.extend(parse_hafu(item, match_id, single_map))

    return records


def parse_crs(item: dict, match_id: str, single_map: dict) -> list[dict]:
    """
    Extract crs (比分) SP records from a single crsList item.

    Returns flat list of dicts with keys:
        match_id, play_type, option_code, option_name,
        sp_value, goal_line, is_single, snapshot_time
    """
    records = []
    snapshot_time = _parse_update_time(item)
    goal_line = item.get("goalLine", "")

    CRS_NAMES = {
        "s-1sh": "主胜其他",
        "s-1sd": "平其他",
        "s-1sa": "客胜其他",
    }

    for key, value in item.items():
        if key in ("updateDate", "updateTime", "goalLine"):
            continue
        if key.endswith("f"):
            continue
        sp = _safe_decimal(value)
        if sp is None:
            continue

        if key in CRS_NAMES:
            option_name = CRS_NAMES[key]
        elif key.startswith("s") and len(key) == 6:
            home = key[1:3].lstrip("0") or "0"
            away = key[4:6].lstrip("0") or "0"
            option_name = f"{home}:{away}"
        else:
            option_name = key

        records.append({
            "match_id": match_id,
            "play_type": "crs",
            "option_code": key,
            "option_name": option_name,
            "sp_value": sp,
            "goal_line": goal_line or None,
            "is_single": single_map.get("crs", 0),
            "snapshot_time": snapshot_time,
        })

    return records


def parse_hafu(item: dict, match_id: str, single_map: dict) -> list[dict]:
    """
    Extract hafu (半全场) SP records from a single hafuList item.

    Returns flat list of dicts with keys:
        match_id, play_type, option_code, option_name,
        sp_value, goal_line, is_single, snapshot_time
    """
    records = []
    snapshot_time = _parse_update_time(item)
    goal_line = item.get("goalLine", "")

    HAFU_NAMES = {
        "hh": "主/主",
        "hd": "主/平",
        "ha": "主/客",
        "dh": "平/主",
        "dd": "平/平",
        "da": "平/客",
        "ah": "客/主",
        "ad": "客/平",
        "aa": "客/客",
    }

    for key, value in item.items():
        if key in ("updateDate", "updateTime", "goalLine"):
            continue
        if key.endswith("f"):
            continue
        sp = _safe_decimal(value)
        if sp is None:
            continue
        if key not in HAFU_NAMES:
            continue

        records.append({
            "match_id": match_id,
            "play_type": "hafu",
            "option_code": key,
            "option_name": HAFU_NAMES[key],
            "sp_value": sp,
            "goal_line": goal_line or None,
            "is_single": single_map.get("hafu", 0),
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
