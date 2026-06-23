"""跨玩法的市场结构分析，基于体彩 SP 趋势。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from src.sp_trend import TREND_CONFIG, PlayTrend


PRIORITY_RANK = {"A": 0, "B": 1, "C": 2, "D": 3}


@dataclass(frozen=True)
class MarketMessage:
    code: str
    severity: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MarketStructure:
    match_id: str
    window: str
    available: bool
    had_direction: str | None
    hhad_direction: str | None
    ttg_direction: str | None
    handicap_line: str | None
    consistency_level: str
    main_market_expression: str
    conflicts: tuple[MarketMessage, ...]
    risk_flags: tuple[MarketMessage, ...]
    suggested_focus: tuple[str, ...]
    avoid_focus: tuple[str, ...]
    research_priority: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["conflicts"] = [item.to_dict() for item in self.conflicts]
        data["risk_flags"] = [item.to_dict() for item in self.risk_flags]
        data["suggested_focus"] = list(self.suggested_focus)
        data["avoid_focus"] = list(self.avoid_focus)
        return data


def analyze_market_structure(
    match_id: str,
    window: str,
    had_trend: PlayTrend | None,
    hhad_trend: PlayTrend | None,
    ttg_trend: PlayTrend | None,
) -> MarketStructure:
    """将同一时间窗口的 had/hhad/ttg 趋势合并为一个市场表达。"""
    _validate_window(window, had_trend, hhad_trend, ttg_trend)
    available_trends = [trend for trend in (had_trend, hhad_trend, ttg_trend) if trend and trend.available]
    had_dir = _direction(had_trend)
    hhad_dir = _direction(hhad_trend)
    ttg_dir = _direction(ttg_trend)

    conflicts: list[MarketMessage] = []
    risks: list[MarketMessage] = []
    suggested: list[str] = []
    avoid: list[str] = []

    if len(available_trends) == 0:
        return _structure(
            match_id,
            window,
            False,
            had_dir,
            hhad_dir,
            ttg_dir,
            None,
            "none",
            "mixed_or_noisy",
            conflicts,
            risks,
            suggested,
            avoid,
            "D",
        )

    expression = "mixed_or_noisy"
    consistency = "mixed"

    hhad_state = _hhad_confirmation_state(had_trend, hhad_trend)
    if hhad_state:
        risk = _hhad_risk(hhad_state)
        risks.append(risk)
        if hhad_state == "hhad_counter_signal":
            conflicts.append(MarketMessage(
                "had_home_vs_hhad_counter",
                "high",
                "胜平负支持主队方向，但让球胜平负明确反向，不支持主队大胜。",
            ))
        elif hhad_state == "hhad_no_confirmation":
            conflicts.append(MarketMessage(
                "had_supports_home_but_hhad_not_confirm_big_win",
                "medium",
                "胜平负支持主队方向，但让球胜平负没有同步确认主队大胜。",
            ))

    if _home_big_win(had_trend, hhad_trend, ttg_trend):
        expression = "home_big_win_supported"
        consistency = "strong"
        suggested.extend(["had_home", "hhad_home", _ttg_focus(ttg_dir)])
    elif _home_small_win(had_trend, hhad_trend, ttg_trend):
        expression = "home_small_win_supported"
        consistency = "partial"
        suggested.extend(["had_home", _ttg_focus(ttg_dir)])
        avoid.append("hhad_home")
    elif _away_not_lose(had_trend, hhad_trend, ttg_trend):
        expression = "away_not_lose_or_small_win_supported"
        consistency = "partial"
        suggested.extend(["had_away_or_away_unbeaten", _ttg_focus(ttg_dir)])
    elif _goal_clear_result_unclear(had_trend, ttg_trend):
        expression = "goal_market_clear_but_result_unclear"
        consistency = "partial"
        suggested.append(_ttg_focus(ttg_dir))
    elif _all_no_clear(had_trend, hhad_trend, ttg_trend):
        expression = "mixed_or_noisy"
        consistency = "weak"

    if _popular_home_overheated(had_trend, hhad_trend, ttg_trend):
        risks.append(MarketMessage(
            "popular_home_win_overheated",
            "medium",
            "主胜处于低SP且继续走低，但让球和进球数没有同步支持大胜，主胜方向可能过热。",
        ))
        avoid.append("chase_low_sp_home")

    priority = _research_priority(available_trends, expression, conflicts, had_trend, hhad_trend, ttg_trend)
    if expression == "mixed_or_noisy":
        priority = "D" if _all_no_clear(had_trend, hhad_trend, ttg_trend) or len(available_trends) < 2 else "C"

    return _structure(
        match_id,
        window,
        len(available_trends) >= 1,
        had_dir,
        hhad_dir,
        ttg_dir,
        hhad_trend.handicap_line if hhad_trend and hhad_trend.available else None,
        consistency,
        expression,
        conflicts,
        risks,
        _dedupe(suggested),
        _dedupe(avoid),
        priority,
    )


def _structure(
    match_id: str,
    window: str,
    available: bool,
    had_direction: str | None,
    hhad_direction: str | None,
    ttg_direction: str | None,
    handicap_line: str | None,
    consistency_level: str,
    expression: str,
    conflicts: list[MarketMessage],
    risks: list[MarketMessage],
    suggested: list[str],
    avoid: list[str],
    priority: str,
) -> MarketStructure:
    return MarketStructure(
        match_id=str(match_id),
        window=window,
        available=available,
        had_direction=had_direction,
        hhad_direction=hhad_direction,
        ttg_direction=ttg_direction,
        handicap_line=handicap_line,
        consistency_level=consistency_level,
        main_market_expression=expression,
        conflicts=tuple(conflicts),
        risk_flags=tuple(risks),
        suggested_focus=tuple(item for item in suggested if item),
        avoid_focus=tuple(item for item in avoid if item),
        research_priority=priority,
    )


def _validate_window(window: str, *trends: PlayTrend | None) -> None:
    for trend in trends:
        if trend is not None and trend.window != window:
            raise ValueError("market_structure inputs must use the same window")


def _direction(trend: PlayTrend | None) -> str | None:
    if trend is None:
        return None
    if not trend.available:
        return "unavailable"
    return trend.main_direction


def _conf_at_least(trend: PlayTrend | None, minimum: str) -> bool:
    order = {"none": 0, "low": 1, "medium": 2, "high": 3}
    if trend is None or not trend.available:
        return False
    return order.get(trend.direction_confidence, 0) >= order[minimum]


def _home_big_win(had: PlayTrend | None, hhad: PlayTrend | None, ttg: PlayTrend | None) -> bool:
    return (
        _direction(had) == "home_win_strengthening"
        and _direction(hhad) == "handicap_home_strengthening"
        and _conf_at_least(hhad, "medium")
        and _direction(ttg) in {"mid_goal_strengthening", "high_goal_strengthening"}
    )


def _home_small_win(had: PlayTrend | None, hhad: PlayTrend | None, ttg: PlayTrend | None) -> bool:
    if _direction(had) not in {"home_win_strengthening", "home_unbeaten_strengthening"}:
        return False
    if _direction(hhad) in {"handicap_draw_strengthening", "handicap_away_strengthening"} and _conf_at_least(hhad, "medium"):
        return True
    if _direction(hhad) == "no_clear_direction" and _direction(ttg) in {"low_goal_strengthening", "mid_goal_strengthening"}:
        return True
    # 保护措施：不要仅从单一玩法判断结构
    available_count = sum(1 for t in (had, hhad, ttg) if t and t.available)
    if (hhad is None or not hhad.available) and available_count >= 2 and _direction(ttg) in {"low_goal_strengthening", "mid_goal_strengthening"}:
        return True
    return False


def _away_not_lose(had: PlayTrend | None, hhad: PlayTrend | None, ttg: PlayTrend | None) -> bool:
    return (
        _direction(had) in {"away_win_strengthening", "away_unbeaten_strengthening"}
        and (
            _direction(hhad) == "handicap_away_strengthening"
            or _direction(ttg) in {"low_goal_strengthening", "mid_goal_strengthening"}
        )
    )


def _goal_clear_result_unclear(had: PlayTrend | None, ttg: PlayTrend | None) -> bool:
    return (
        _direction(had) in {"no_clear_direction", "mixed_direction", "unavailable", None}
        and _direction(ttg) in {"low_goal_strengthening", "mid_goal_strengthening", "high_goal_strengthening"}
        and _conf_at_least(ttg, "medium")
    )


def _all_no_clear(*trends: PlayTrend | None) -> bool:
    available = [trend for trend in trends if trend and trend.available]
    return bool(available) and all(trend.direction_confidence in {"none", "low"} and "strengthening" not in trend.main_direction for trend in available)


def _hhad_confirmation_state(had: PlayTrend | None, hhad: PlayTrend | None) -> str | None:
    if _direction(had) not in {"home_win_strengthening", "home_unbeaten_strengthening"}:
        return None
    if hhad is None or not hhad.available:
        return "hhad_missing"
    if _direction(hhad) == "no_clear_direction" and hhad.direction_confidence in {"none", "low"}:
        return "hhad_no_confirmation"
    if _direction(hhad) in {"handicap_draw_strengthening", "handicap_away_strengthening"} and _conf_at_least(hhad, "medium"):
        return "hhad_counter_signal"
    return None


def _hhad_risk(state: str) -> MarketMessage:
    if state == "hhad_missing":
        return MarketMessage("hhad_missing", "low", "让球胜平负数据不足，不能确认是否支持大胜。")
    if state == "hhad_no_confirmation":
        return MarketMessage("hhad_no_confirmation", "medium-low", "让球胜平负无明显方向，对大胜确认不足。")
    return MarketMessage("hhad_counter_signal", "high", "让球胜平负明确反向，是主队大胜方向的强风险。")


def _popular_home_overheated(had: PlayTrend | None, hhad: PlayTrend | None, ttg: PlayTrend | None) -> bool:
    if _direction(had) != "home_win_strengthening" or not had.options:
        return False
    home = next((option for option in had.options if option.option_code == "H"), None)
    if home is None or home.sp_end > TREND_CONFIG["popular_low_sp_threshold"]:
        return False
    return _direction(hhad) != "handicap_home_strengthening" and _direction(ttg) != "high_goal_strengthening"


def _research_priority(
    available_trends: list[PlayTrend],
    expression: str,
    conflicts: list[MarketMessage],
    had: PlayTrend | None,
    hhad: PlayTrend | None,
    ttg: PlayTrend | None,
) -> str:
    high_conflicts = [item for item in conflicts if item.severity == "high"]
    medium_conflicts = [item for item in conflicts if item.severity in {"medium", "medium-low"}]
    if len(available_trends) < 2:
        return "D"
    if high_conflicts:
        return "C"
    if expression in {"home_big_win_supported"} and not high_conflicts:
        return "A"
    if expression in {"home_small_win_supported", "away_not_lose_or_small_win_supported"}:
        base = "B" if medium_conflicts else "A"
        # 若让球数据缺失则降级——关键确认信息不足
        if expression == "home_small_win_supported" and (hhad is None or not hhad.available):
            base = "B" if base == "A" else "C"
        return base
    if expression == "goal_market_clear_but_result_unclear":
        return "B" if _conf_at_least(ttg, "medium") else "C"
    if _direction(had) not in {None, "unavailable", "no_clear_direction", "mixed_direction"} or _direction(ttg) not in {None, "unavailable", "no_clear_goal_direction", "scattered_goal_structure"}:
        return "C"
    return "D"


def _ttg_focus(direction: str | None) -> str:
    return {
        "low_goal_strengthening": "ttg_0_2_goals",
        "mid_goal_strengthening": "ttg_2_3_goals",
        "high_goal_strengthening": "ttg_4_plus_goals",
    }.get(direction or "", "")


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))
