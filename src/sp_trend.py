"""体彩竞彩足球市场的结构化 SP 趋势分析。

SP 是中国体彩的固定奖金值。此处生成的归一化权重是单一玩法内的
市场表达权重，不是真实概率，也不是模型预测。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any


SUPPORTED_PLAY_TYPES = {"had", "hhad", "ttg"}
from src.constants import CHINA_TZ, WINDOWS, parse_time as _parse_time

TREND_CONFIG = {
    "sp_strong_down_pct": -0.08,
    "sp_mild_down_pct": -0.03,
    "sp_mild_up_pct": 0.03,
    "sp_strong_up_pct": 0.08,
    "weight_strengthen_delta": 0.015,
    "weight_weaken_delta": -0.015,
    "confidence_high_gap": 0.04,
    "confidence_medium_gap": 0.02,
    "confidence_low_gap": 0.01,
    "no_clear_max_abs_delta": 0.01,
    "mixed_gap_threshold": 0.015,
    "popular_low_sp_threshold": 1.45,
    "goal_group_strengthen_delta": 0.025,
    "goal_group_gap_threshold": 0.015,
}

WINDOW_DURATIONS = {
    "last_24h": timedelta(hours=24),
    "last_6h": timedelta(hours=6),
}


@dataclass(frozen=True)
class TrendOption:
    option_code: str
    option_name: str | None
    sp_start: float
    sp_end: float
    sp_delta: float
    sp_delta_pct: float
    raw_implied_weight_start: float
    raw_implied_weight_end: float
    normalized_implied_weight_start: float
    normalized_implied_weight_end: float
    normalized_weight_delta: float
    sp_trend: str
    weight_trend: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PlayTrend:
    match_id: str
    play_type: str
    window: str
    available: bool
    reason: str | None
    snapshot_start_time: str | None = None
    snapshot_end_time: str | None = None
    options: tuple[TrendOption, ...] = ()
    main_direction: str = "no_clear_direction"
    direction_confidence: str = "none"
    direction_gap: float = 0.0
    volatility_level: str = "low"
    handicap_line: str | None = None
    goal_group_deltas: dict[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["options"] = [option.to_dict() for option in self.options]
        return data


def analyze_play_trend(
    match_id: str,
    play_type: str,
    window: str,
    sp_records: list[dict],
) -> PlayTrend:
    """根据已存储的 SP 快照分析单场比赛/玩法/时间窗口的趋势。"""
    match_id = str(match_id)
    play_type = play_type.lower()
    if play_type not in SUPPORTED_PLAY_TYPES:
        return _unavailable(match_id, play_type, window, "unsupported_play_type")
    if window not in WINDOWS:
        return _unavailable(match_id, play_type, window, "unsupported_window")

    records = [
        record for record in sp_records
        if str(record.get("match_id")) == match_id and str(record.get("play_type")).lower() == play_type
    ]
    snapshots = _group_complete_snapshots(records)
    if len(snapshots) < 2:
        return _unavailable(match_id, play_type, window, "not_enough_snapshots")

    selected = _select_window_snapshots(snapshots, window)
    if selected is None:
        return _unavailable(match_id, play_type, window, "not_enough_snapshots")

    start_time, start_rows, end_time, end_rows = selected
    options = _build_options(start_rows, end_rows)
    if not options:
        return _unavailable(match_id, play_type, window, "not_enough_options")

    direction_gap = _direction_gap(options)
    confidence = _direction_confidence(direction_gap)
    if play_type == "had":
        main_direction, confidence = _had_direction(options, direction_gap, confidence)
        goal_group_deltas = None
    elif play_type == "hhad":
        main_direction, confidence = _hhad_direction(options, direction_gap, confidence)
        goal_group_deltas = None
    else:
        main_direction, confidence, direction_gap, goal_group_deltas = _ttg_direction(options)

    return PlayTrend(
        match_id=match_id,
        play_type=play_type,
        window=window,
        available=True,
        reason=None,
        snapshot_start_time=_iso(start_time),
        snapshot_end_time=_iso(end_time),
        options=tuple(options),
        main_direction=main_direction,
        direction_confidence=confidence,
        direction_gap=round(direction_gap, 4),
        volatility_level=_volatility_level(options),
        handicap_line=_latest_handicap_line(end_rows) if play_type == "hhad" else None,
        goal_group_deltas=goal_group_deltas,
    )


def _unavailable(match_id: str, play_type: str, window: str, reason: str) -> PlayTrend:
    return PlayTrend(
        match_id=str(match_id),
        play_type=play_type,
        window=window,
        available=False,
        reason=reason,
    )


def _group_complete_snapshots(records: list[dict]) -> list[tuple[datetime, list[dict]]]:
    grouped: dict[datetime, list[dict]] = {}
    for record in records:
        snapshot_time = _parse_time(record.get("snapshot_time"))
        sp = _safe_sp(record.get("sp_value"))
        if snapshot_time is None or sp is None:
            continue
        copied = dict(record)
        copied["sp_value"] = sp
        grouped.setdefault(snapshot_time, []).append(copied)
    return sorted(grouped.items(), key=lambda item: item[0])


def _select_window_snapshots(
    snapshots: list[tuple[datetime, list[dict]]],
    window: str,
) -> tuple[datetime, list[dict], datetime, list[dict]] | None:
    if len(snapshots) < 2:
        return None
    # 开盘到最新
    if window == "open_to_latest":
        start_time, start_rows = snapshots[0]
        end_time, end_rows = snapshots[-1]
        return start_time, start_rows, end_time, end_rows

    end_time, end_rows = snapshots[-1]
    window_duration = WINDOW_DURATIONS[window]
    cutoff = end_time - window_duration
    # 窗口内的快照
    inside_window = [(t, rows) for t, rows in snapshots if t >= cutoff]
    if len(inside_window) >= 2:
        start_time, start_rows = inside_window[0]
        return start_time, start_rows, end_time, end_rows

    # 窗口边界附近的候选快照
    boundary_candidates = [
        (t, rows)
        for t, rows in snapshots
        if cutoff - window_duration <= t < cutoff
    ]
    if not inside_window or not boundary_candidates:
        return None

    start_time, start_rows = boundary_candidates[-1]
    return start_time, start_rows, end_time, end_rows


def _build_options(start_rows: list[dict], end_rows: list[dict]) -> list[TrendOption]:
    start_weights = _snapshot_weights(start_rows)
    end_weights = _snapshot_weights(end_rows)
    options = []
    for code in sorted(set(start_weights) & set(end_weights)):
        start = start_weights[code]
        end = end_weights[code]
        sp_delta = round(end["sp"] - start["sp"], 4)
        sp_delta_pct = round(sp_delta / start["sp"], 4) if start["sp"] else 0.0
        weight_delta = round(end["normalized"] - start["normalized"], 4)
        options.append(TrendOption(
            option_code=code,
            option_name=end["name"] or start["name"],
            sp_start=start["sp"],
            sp_end=end["sp"],
            sp_delta=sp_delta,
            sp_delta_pct=sp_delta_pct,
            raw_implied_weight_start=round(start["raw"], 6),
            raw_implied_weight_end=round(end["raw"], 6),
            normalized_implied_weight_start=round(start["normalized"], 6),
            normalized_implied_weight_end=round(end["normalized"], 6),
            normalized_weight_delta=weight_delta,
            sp_trend=_sp_trend(sp_delta_pct),
            weight_trend=_weight_trend(weight_delta),
        ))
    return options


def _snapshot_weights(rows: list[dict]) -> dict[str, dict[str, Any]]:
    weighted = {}
    for row in rows:
        sp = _safe_sp(row.get("sp_value"))
        code = str(row.get("option_code", ""))
        if not code or sp is None:
            continue
        raw = 1.0 / sp
        weighted[code] = {
            "sp": sp,
            "raw": raw,
            "name": row.get("option_name"),
        }
    total = sum(item["raw"] for item in weighted.values())
    if total <= 0:
        return {}
    for item in weighted.values():
        item["normalized"] = item["raw"] / total
    return weighted


def _sp_trend(sp_delta_pct: float) -> str:
    if sp_delta_pct <= TREND_CONFIG["sp_strong_down_pct"]:
        return "strong_down"
    if sp_delta_pct <= TREND_CONFIG["sp_mild_down_pct"]:
        return "mild_down"
    if sp_delta_pct >= TREND_CONFIG["sp_strong_up_pct"]:
        return "strong_up"
    if sp_delta_pct >= TREND_CONFIG["sp_mild_up_pct"]:
        return "mild_up"
    return "stable"


def _weight_trend(delta: float) -> str:
    if delta >= TREND_CONFIG["weight_strengthen_delta"]:
        return "strengthening"
    if delta <= TREND_CONFIG["weight_weaken_delta"]:
        return "weakening"
    return "stable"


def _direction_gap(options: list[TrendOption]) -> float:
    deltas = sorted((option.normalized_weight_delta for option in options), reverse=True)
    if len(deltas) < 2:
        return 0.0
    return round(deltas[0] - deltas[1], 4)


def _direction_confidence(gap: float) -> str:
    if gap >= TREND_CONFIG["confidence_high_gap"]:
        return "high"
    if gap >= TREND_CONFIG["confidence_medium_gap"]:
        return "medium"
    if gap >= TREND_CONFIG["confidence_low_gap"]:
        return "low"
    return "none"


def _had_direction(options: list[TrendOption], gap: float, confidence: str) -> tuple[str, str]:
    trends = {option.option_code: option.weight_trend for option in options}
    deltas = {option.option_code: option.normalized_weight_delta for option in options}
    if _no_clear(options, gap):
        return "no_clear_direction", "none"
    strengthening = {code for code, trend in trends.items() if trend == "strengthening"}
    weakening = {code for code, trend in trends.items() if trend == "weakening"}
    # 主胜+平增强且客胜走弱 → 主场不败强化
    if {"H", "D"} <= strengthening and "A" in weakening:
        return "home_unbeaten_strengthening", confidence
    # 平+客胜增强且主胜走弱 → 客场不败强化
    if {"D", "A"} <= strengthening and "H" in weakening:
        return "away_unbeaten_strengthening", confidence
    if confidence != "none":
        # 主胜增强且平+客胜走弱 → 主胜强化
        if trends.get("H") == "strengthening" and {"D", "A"} <= weakening:
            return "home_win_strengthening", confidence
        # 平增强且主胜+客胜走弱 → 平局强化
        if trends.get("D") == "strengthening" and {"H", "A"} <= weakening:
            return "draw_strengthening", confidence
        # 客胜增强且主胜+平走弱 → 客胜强化
        if trends.get("A") == "strengthening" and {"H", "D"} <= weakening:
            return "away_win_strengthening", confidence
    # 多方向增强且差距不明显 → 混合方向
    if len(strengthening) >= 2 and gap < TREND_CONFIG["mixed_gap_threshold"]:
        return "mixed_direction", confidence
    top_code = max(deltas, key=deltas.get)
    fallback = {
        "H": "home_win_strengthening",
        "D": "draw_strengthening",
        "A": "away_win_strengthening",
    }.get(top_code, "mixed_direction")
    return fallback if confidence != "none" else "mixed_direction", confidence


def _hhad_direction(options: list[TrendOption], gap: float, confidence: str) -> tuple[str, str]:
    if _no_clear(options, gap):
        return "no_clear_direction", "none"
    strengthening = [option for option in options if option.weight_trend == "strengthening"]
    # 多方向增强且差距不明显 → 混合方向
    if len(strengthening) >= 2 and gap < TREND_CONFIG["mixed_gap_threshold"]:
        return "mixed_direction", confidence
    top = max(options, key=lambda option: option.normalized_weight_delta)
    if top.weight_trend != "strengthening":
        return "no_clear_direction", "none"
    return {
        "H": "handicap_home_strengthening",
        "D": "handicap_draw_strengthening",
        "A": "handicap_away_strengthening",
    }.get(top.option_code, "mixed_direction"), confidence


def _ttg_direction(options: list[TrendOption]) -> tuple[str, str, float, dict[str, float]]:
    deltas = {option.option_code: option.normalized_weight_delta for option in options}
    # 注意："2" 在低进球组和中间进球组之间有意共享——
    # 它处于边界位置，其权重变化同时贡献到两组，
    # 使分析对 2 球附近的边际变化更敏感。
    groups = {
        "low_goals": sum(deltas.get(code, 0.0) for code in ("0", "1", "2")),
        "mid_goals": sum(deltas.get(code, 0.0) for code in ("2", "3")),
        "high_goals": sum(deltas.get(code, 0.0) for code in ("4", "5", "6", "7")),
    }
    groups = {key: round(value, 4) for key, value in groups.items()}
    ordered = sorted(groups.items(), key=lambda item: item[1], reverse=True)
    top_group, top_delta = ordered[0]
    gap = round(ordered[0][1] - ordered[1][1], 4)
    confidence = _direction_confidence(gap)
    # 最强方向未达到增强阈值 → 无明确进球方向
    if top_delta < TREND_CONFIG["goal_group_strengthen_delta"]:
        return "no_clear_goal_direction", "none", gap, groups
    # 组间差距不明显 → 分散的进球结构
    if gap < TREND_CONFIG["goal_group_gap_threshold"]:
        return "scattered_goal_structure", confidence, gap, groups
    direction = {
        "low_goals": "low_goal_strengthening",
        "mid_goals": "mid_goal_strengthening",
        "high_goals": "high_goal_strengthening",
    }[top_group]
    return direction, confidence, gap, groups


def _no_clear(options: list[TrendOption], gap: float) -> bool:
    return (
        all(abs(option.normalized_weight_delta) < TREND_CONFIG["no_clear_max_abs_delta"] for option in options)
        or gap < TREND_CONFIG["confidence_low_gap"]
        or not any(option.weight_trend == "strengthening" for option in options)
    )


def _volatility_level(options: list[TrendOption]) -> str:
    max_abs_pct = max((abs(option.sp_delta_pct) for option in options), default=0.0)
    if max_abs_pct >= 0.08:
        return "high"
    if max_abs_pct >= 0.03:
        return "medium"
    return "low"


def _latest_handicap_line(rows: list[dict]) -> str | None:
    for row in rows:
        line = row.get("goal_line")
        if line not in (None, ""):
            return str(line)
    return None


def _safe_sp(value) -> float | None:
    try:
        sp = float(value)
    except (TypeError, ValueError):
        return None
    if sp <= 0:
        return None
    return sp


def _iso(value: datetime) -> str:
    return value.astimezone(CHINA_TZ).isoformat()
