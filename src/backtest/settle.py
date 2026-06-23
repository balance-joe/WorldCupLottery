"""回测专用结算逻辑。复用 settlement.py 的规则，适配回测场景。"""

from __future__ import annotations

from src.backtest.types import BetResult
from src.recommendation import latest_option_sp


def evaluate_bet(
    play_type: str,
    bet_option: str,
    match: dict,
) -> tuple[bool | None, str]:
    """判断模拟投注是否命中。返回 (hit, actual_result)。

    与 settlement.evaluate_leg 逻辑一致，但输入更简洁。
    """
    home = match.get("home_score_90")
    away = match.get("away_score_90")
    if home is None or away is None:
        return None, "no_result"

    home = int(home)
    away = int(away)

    if play_type == "had":
        actual = "H" if home > away else "A" if home < away else "D"
        return bet_option == actual, actual

    if play_type == "hhad":
        goal_line = match.get("goal_line")
        if goal_line in (None, ""):
            return None, "no_goal_line"
        try:
            adjusted = home + float(goal_line)
        except (ValueError, TypeError):
            return None, "bad_goal_line"
        actual = "H" if adjusted > away else "A" if adjusted < away else "D"
        return bet_option == actual, actual

    if play_type == "ttg":
        total = home + away
        actual = str(total) if total <= 6 else "7"
        return bet_option == actual, actual

    if play_type == "crs":
        actual = f"s{home:02d}s{away:02d}"
        return bet_option == actual, actual

    if play_type == "hafu":
        half = match.get("half_score")
        if not half or ":" not in str(half):
            return None, "no_half"
        try:
            parts = str(half).split(":")
            hh, ha = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            return None, "bad_half"
        h_result = "h" if hh > ha else "d" if hh == ha else "a"
        f_result = "h" if home > away else "d" if home == away else "a"
        actual = h_result + f_result
        return bet_option == actual, actual

    return None, "unsupported_play"


def settle_bet(
    play_type: str,
    bet_option: str,
    match: dict,
    sp_value: float | None,
    stake: float,
) -> BetResult:
    """构建完整的 BetResult。"""
    hit, actual = evaluate_bet(play_type, bet_option, match)
    payout = round(sp_value * stake, 2) if hit and sp_value else 0.0
    home = match.get("home_score_90")
    away = match.get("away_score_90")
    score = f"{home}:{away}" if home is not None and away is not None else None
    return BetResult(
        match_id=str(match.get("match_id", "")),
        match_info=f"{match.get('home_team_name', '?')} vs {match.get('away_team_name', '?')}",
        score=score,
        play_type=play_type,
        bet_option=bet_option,
        sp_value=sp_value,
        hit=hit,
        actual_result=actual,
        stake=stake,
        payout=payout,
    )


def get_sp_for_option(
    play_type: str,
    bet_option: str,
    sp_history: list[dict],
    match_id: str,
) -> float | None:
    """获取买入选项的 SP 值。"""
    records = [
        r for r in sp_history
        if str(r.get("match_id")) == match_id and r.get("play_type") == play_type
    ]
    if not records:
        return None
    latest_time = max(str(r.get("snapshot_time", "")) for r in records)
    for r in records:
        if str(r.get("snapshot_time", "")) == latest_time and r.get("option_code") == bet_option:
            return float(r["sp_value"])
    return None
