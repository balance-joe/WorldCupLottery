"""将原始 API 响应解析为扁平化的记录字典。"""

from __future__ import annotations

from datetime import datetime


# ── Schema 验证 ─────────────────────────────────────────────────────────

_MATCH_REQUIRED_TOP = {"value"}
_MATCH_REQUIRED_VALUE = {"matchInfoList"}
_MATCH_REQUIRED_SUB = {
    "matchId", "matchDate", "matchTime",
    "homeTeamAbbName", "awayTeamAbbName",
}

_FIXED_BONUS_REQUIRED_TOP = {"value"}
_FIXED_BONUS_REQUIRED_VALUE = {"oddsHistory"}


def validate_match_list_schema(raw: dict) -> list[str]:
    """检查 matchList 响应的顶层结构。

    返回可读的警告列表；空列表表示有效。
    """
    warnings: list[str] = []
    for key in _MATCH_REQUIRED_TOP:
        if key not in raw:
            warnings.append(f"matchList: missing top-level key '{key}'")
            return warnings  # 无法继续深入

    value = raw["value"]
    for key in _MATCH_REQUIRED_VALUE:
        if key not in value:
            warnings.append(f"matchList.value: missing key '{key}'")

    for day in value.get("matchInfoList", []):
        for m in day.get("subMatchList", []):
            for key in _MATCH_REQUIRED_SUB:
                if key not in m:
                    warnings.append(f"matchList.subMatch item: missing '{key}'")
                    break  # 每场比赛只需一条警告
            break  # 仅验证第一场比赛，避免信息过多
        break

    return warnings


def validate_fixed_bonus_schema(raw: dict, match_id: str | int) -> list[str]:
    """检查 fixedBonus 响应的顶层结构。

    返回可读的警告列表；空列表表示有效。
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
    从 getMatchDataPageListV1 响应中提取比赛基本信息。

    返回字典列表，包含以下键：
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
    从 getFixedBonusV1 响应中提取 had / hhad / ttg 的 SP 记录。

    API 返回 SP 变更历史——每个列表项有独立的 updateDate + updateTime，
    我们将其作为 snapshot_time。

    返回扁平化字典列表，包含以下键：
        match_id, play_type, option_code, option_name,
        sp_value, goal_line, is_single, snapshot_time
    """
    records = []
    odds = raw.get("value", {}).get("oddsHistory", {})
    match_id = str(match_id)

    # ── 单关映射 ────────────────────────────────────────────────────────
    single_map = {}
    for s in odds.get("singleList", []):
        pool = s.get("poolCode", "").lower()
        single_map[pool] = s.get("single", 0)

    # ── had（胜平负）────────────────────────────────────────────────────
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

    # ── hhad（让球胜平负）──────────────────────────────────────────────
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

    # ── ttg（总进球）────────────────────────────────────────────────────
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

    # ── crs（比分）────────────────────────────────────────────────────
    for item in odds.get("crsList", []):
        records.extend(parse_crs(item, match_id, single_map))

    # ── hafu（半全场）──────────────────────────────────────────────────
    for item in odds.get("hafuList", []):
        records.extend(parse_hafu(item, match_id, single_map))

    return records


def parse_crs(item: dict, match_id: str, single_map: dict) -> list[dict]:
    """
    从单个 crsList 项中提取 crs（比分）的 SP 记录。

    返回扁平化字典列表，包含以下键：
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
    从单个 hafuList 项中提取 hafu（半全场）的 SP 记录。

    返回扁平化字典列表，包含以下键：
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
    从 getMatchDataPageListV1(method=result) 中提取已完赛的比赛结果。

    sectionsNo999 是全场比分字段。根据项目规则，此比分视为包含伤停补时的
    90 分钟比赛结果。
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
    """提取 updateDate + updateTime，格式为 'YYYY-MM-DD HH:MM:SS'。"""
    date = item.get("updateDate", "")
    time_ = item.get("updateTime", "")
    if date and time_:
        return f"{date} {time_}"
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_decimal(val) -> float | None:
    """转换为浮点数，若为空或无效则返回 None。"""
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
