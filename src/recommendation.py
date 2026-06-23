"""竞彩推荐门控与候选生成模块。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from src.constants import CHINA_TZ, parse_time as _parse_time
from src.market_structure import MarketStructure, analyze_market_structure
from src.sp_trend import PlayTrend, analyze_play_trend
# 门控设置有意偏保守：在票单构建逻辑运行前，应先屏蔽弱势或过时的市场。
PLAY_SNAPSHOT_LIMITS = {
    "had": 2,
    "hhad": 2,
    "ttg": 2,
}
MAX_FRESHNESS_HOURS = 18


@dataclass(frozen=True)
class RecommendationGate:
    allowed: bool
    priority: str
    available_play_count: int
    allowed_plays: tuple[str, ...]
    blocked_plays: tuple[str, ...]
    reasons: tuple[str, ...]
    latest_snapshot_time: str | None
    snapshot_age_hours: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecommendationCandidates:
    had_options: tuple[str, ...]
    hhad_options: tuple[str, ...]
    ttg_options: tuple[str, ...]
    crs_options: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MatchSuggestion:
    play_type: str
    selections: tuple[str, ...]
    market_expression: str
    confidence: str
    reason: str
    risks: tuple[str, ...]
    gate_passed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MatchRecommendation:
    gate: RecommendationGate
    structure: MarketStructure
    had_trend: PlayTrend
    hhad_trend: PlayTrend
    ttg_trend: PlayTrend
    candidates: RecommendationCandidates
    suggestions: tuple[MatchSuggestion, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate.to_dict(),
            "structure": self.structure.to_dict(),
            "had_trend": self.had_trend.to_dict(),
            "hhad_trend": self.hhad_trend.to_dict(),
            "ttg_trend": self.ttg_trend.to_dict(),
            "candidates": self.candidates.to_dict(),
            "suggestions": [suggestion.to_dict() for suggestion in self.suggestions],
        }


def filter_sp_records_as_of(sp_records: list[dict], cutoff_time: str | None) -> list[dict]:
    """返回快照时间不晚于截止时间的记录。"""
    cutoff = _parse_time(cutoff_time)
    if cutoff is None:
        return list(sp_records)
    filtered = []
    for record in sp_records:
        snapshot_time = _parse_time(record.get("snapshot_time"))
        if snapshot_time is None or snapshot_time <= cutoff:
            filtered.append(record)
    return filtered


def build_match_recommendation(
    match_info: dict,
    sp_history: list[dict],
    *,
    window: str = "open_to_latest",
    now_time: str | None = None,
) -> MatchRecommendation:
    """分析单场比赛，返回带门控的推荐结果。"""
    match_id = str(match_info.get("match_id", ""))
    had = analyze_play_trend(match_id, "had", window, sp_history)
    hhad = analyze_play_trend(match_id, "hhad", window, sp_history)
    ttg = analyze_play_trend(match_id, "ttg", window, sp_history)
    structure = analyze_market_structure(match_id, window, had, hhad, ttg)
    gate = _build_gate(match_info, sp_history, structure, had, hhad, ttg, now_time=now_time)
    candidates = _build_candidates(sp_history, structure, had, hhad, ttg)
    suggestions = _build_suggestions(gate, structure, had, hhad, ttg, candidates)
    return MatchRecommendation(
        gate=gate,
        structure=structure,
        had_trend=had,
        hhad_trend=hhad,
        ttg_trend=ttg,
        candidates=candidates,
        suggestions=tuple(suggestions),
    )


def _build_gate(
    match_info: dict,
    sp_history: list[dict],
    structure: MarketStructure,
    had: PlayTrend,
    hhad: PlayTrend,
    ttg: PlayTrend,
    *,
    now_time: str | None = None,
) -> RecommendationGate:
    available_count = sum(1 for trend in (had, hhad, ttg) if trend.available)
    latest_snapshot_time = _latest_snapshot_time(sp_history)
    age_hours = _snapshot_age_hours(match_info, latest_snapshot_time, now_time=now_time)

    reasons: list[str] = []
    if structure.research_priority not in {"A", "B"}:
        reasons.append(f"priority_{structure.research_priority}_blocked")
    if available_count < 2:
        reasons.append("insufficient_play_coverage")
    if age_hours is not None and age_hours > MAX_FRESHNESS_HOURS:
        reasons.append("stale_snapshot")

    blocked: set[str] = set()
    if not had.available:
        blocked.update({"had", "crs"})
    if not ttg.available:
        blocked.add("ttg")
    if any(conflict.severity == "high" for conflict in structure.conflicts):
        blocked.update({"had", "crs", "hhad"})
        reasons.append("high_conflict_market")

    snapshot_counts = _snapshot_counts(sp_history)
    for play_type, minimum in PLAY_SNAPSHOT_LIMITS.items():
        if snapshot_counts.get(play_type, 0) < minimum:
            blocked.add(play_type)
            if play_type == "had":
                blocked.add("crs")
            reasons.append(f"{play_type}_not_enough_snapshots")

    allowed: list[str] = []
    for play_type in ("had", "hhad", "ttg", "crs"):
        if play_type in blocked:
            continue
        if play_type == "crs" and structure.main_market_expression == "mixed_or_noisy":
            blocked.add("crs")
            reasons.append("crs_requires_clear_structure")
            continue
        allowed.append(play_type)

    if not allowed:
        reasons.append("no_play_passed_gate")

    return RecommendationGate(
        allowed=bool(allowed) and structure.research_priority in {"A", "B"},
        priority=structure.research_priority,
        available_play_count=available_count,
        allowed_plays=tuple(allowed),
        blocked_plays=tuple(sorted(blocked)),
        reasons=tuple(dict.fromkeys(reasons)),
        latest_snapshot_time=latest_snapshot_time,
        snapshot_age_hours=round(age_hours, 2) if age_hours is not None else None,
    )


def _build_candidates(
    sp_history: list[dict],
    structure: MarketStructure,
    had: PlayTrend,
    hhad: PlayTrend,
    ttg: PlayTrend,
) -> RecommendationCandidates:
    had_options = _had_candidates(had)
    hhad_options = _hhad_candidates(hhad)
    ttg_options = _ttg_candidates(sp_history, ttg)
    crs_options = _crs_candidates(sp_history, structure, had_options, ttg_options)
    return RecommendationCandidates(
        had_options=tuple(had_options),
        hhad_options=tuple(hhad_options),
        ttg_options=tuple(ttg_options),
        crs_options=tuple(crs_options),
    )


def _build_suggestions(
    gate: RecommendationGate,
    structure: MarketStructure,
    had: PlayTrend,
    hhad: PlayTrend,
    ttg: PlayTrend,
    candidates: RecommendationCandidates,
) -> list[MatchSuggestion]:
    risk_codes = tuple(risk.code for risk in structure.risk_flags[:3])
    suggestions: list[MatchSuggestion] = []

    # 1. 胜负平建议（HAD 或 HHAD）
    result_suggestion = _result_suggestion(
        structure, had, hhad,
        candidates.had_options, candidates.hhad_options,
        risk_codes, gate,
    )
    if result_suggestion is not None:
        suggestions.append(result_suggestion)

    # 2. 比分建议（CRS）
    crs_suggestion = _crs_suggestion(
        structure, candidates.crs_options, risk_codes, gate,
    )
    if crs_suggestion is not None:
        suggestions.append(crs_suggestion)

    # 3. 进球数建议（TTG）
    ttg_suggestion = _ttg_suggestion(
        structure, ttg, candidates.ttg_options, risk_codes, gate,
    )
    if ttg_suggestion is not None:
        suggestions.append(ttg_suggestion)

    return suggestions


def _had_candidates(had: PlayTrend) -> list[str]:
    if not had.available:
        return []
    direction = had.main_direction
    if "home_win" in direction:
        return ["H"]
    if "away_win" in direction:
        return ["A"]
    if "draw" in direction:
        return ["D"]
    if "home_unbeaten" in direction:
        return ["H", "D"]
    if "away_unbeaten" in direction:
        return ["D", "A"]
    return []


def _hhad_candidates(hhad: PlayTrend) -> list[str]:
    if not hhad.available:
        return []
    return {
        "handicap_home_strengthening": ["H"],
        "handicap_draw_strengthening": ["D"],
        "handicap_away_strengthening": ["A"],
    }.get(hhad.main_direction, [])


def _ttg_candidates(sp_history: list[dict], ttg: PlayTrend) -> list[str]:
    if not ttg.available:
        return []
    latest = latest_play_snapshot(sp_history, "ttg")
    if not latest:
        return []
    groups = {
        "low_goal_strengthening": {"0", "1", "2"},
        "mid_goal_strengthening": {"2", "3"},
        "high_goal_strengthening": {"3", "4", "5", "6", "7"},
    }
    candidate_codes = groups.get(ttg.main_direction, set())
    if not candidate_codes:
        return []
    ranked = sorted(
        (row for row in latest if str(row.get("option_code")) in candidate_codes),
        key=lambda row: (-(row.get("implied_prob_norm") or 0), float(row.get("sp_value") or 999)),
    )
    return [str(row["option_code"]) for row in ranked[:2]]


def _crs_candidates(
    sp_history: list[dict],
    structure: MarketStructure,
    had_options: list[str],
    ttg_options: list[str],
) -> list[str]:
    latest = latest_play_snapshot(sp_history, "crs")
    if not latest:
        return []
    allowed_totals = {int(option) for option in ttg_options if str(option).isdigit()}
    scored = []
    for row in latest:
        score = score_from_crs_code(str(row.get("option_code", "")))
        if score is None:
            continue
        home_goals, away_goals = score
        result = "H" if home_goals > away_goals else "A" if away_goals > home_goals else "D"
        total = home_goals + away_goals
        if had_options and result not in had_options:
            continue
        if allowed_totals and not any(abs(total - allowed_total) <= 1 for allowed_total in allowed_totals):
            continue
        if structure.main_market_expression == "away_not_lose_or_small_win_supported" and total > 4:
            continue
        scored.append(row)
    ranked = sorted(scored, key=lambda row: -(row.get("implied_prob_norm") or 0))
    return [str(row["option_code"]) for row in ranked[:3]]


def _result_suggestion(
    structure: MarketStructure,
    had: PlayTrend,
    hhad: PlayTrend,
    had_options: tuple[str, ...],
    hhad_options: tuple[str, ...],
    risk_codes: tuple[str, ...],
    gate: RecommendationGate,
) -> MatchSuggestion | None:
    play_type = "had"
    selections = had_options
    direction = had.main_direction

    if (
        hhad.available
        and hhad_options
        and structure.main_market_expression in {"home_big_win_supported", "away_not_lose_or_small_win_supported"}
        and hhad.main_direction in {"handicap_home_strengthening", "handicap_away_strengthening"}
    ):
        play_type = "hhad"
        selections = hhad_options
        direction = hhad.main_direction

    if play_type == "had" and (not had.available or not had_options):
        return None
    if play_type == "hhad" and (not hhad.available or not hhad_options):
        return None
    if play_type == "had" and "had" not in structure.suggested_focus and structure.main_market_expression == "mixed_or_noisy":
        return None
    allowed_directions = {
        "had": {
            "home_win_strengthening",
            "away_win_strengthening",
            "draw_strengthening",
            "home_unbeaten_strengthening",
            "away_unbeaten_strengthening",
        },
        "hhad": {
            "handicap_home_strengthening",
            "handicap_away_strengthening",
        },
    }
    if direction not in allowed_directions[play_type]:
        return None

    reason = f"{'让球胜平负' if play_type == 'hhad' else '胜平负'}方向={direction}"
    if hhad.available and hhad.main_direction != "no_clear_direction":
        reason += f"，让球方向={hhad.main_direction}"

    return MatchSuggestion(
        play_type=play_type,
        selections=selections,
        market_expression=structure.main_market_expression,
        confidence=structure.research_priority,
        reason=reason,
        risks=risk_codes,
        gate_passed=play_type in gate.allowed_plays,
    )


def _crs_suggestion(
    structure: MarketStructure,
    crs_options: tuple[str, ...],
    risk_codes: tuple[str, ...],
    gate: RecommendationGate,
) -> MatchSuggestion | None:
    """比分建议：基于 CRS 候选选项生成。"""
    if not crs_options:
        return None

    gate_passed = "crs" in gate.allowed_plays
    reason = f"比分候选: {', '.join(crs_options[:3])}"
    if not gate_passed:
        reason += "（门禁未通过，仅观察）"

    return MatchSuggestion(
        play_type="crs",
        selections=crs_options[:3],
        market_expression=structure.main_market_expression,
        confidence=structure.research_priority,
        reason=reason,
        risks=risk_codes,
        gate_passed=gate_passed,
    )


def _ttg_suggestion(
    structure: MarketStructure,
    ttg: PlayTrend,
    ttg_options: tuple[str, ...],
    risk_codes: tuple[str, ...],
    gate: RecommendationGate,
) -> MatchSuggestion | None:
    """进球数建议：基于 TTG 候选选项生成。"""
    if not ttg_options:
        return None

    gate_passed = "ttg" in gate.allowed_plays
    direction = ttg.main_direction if ttg.available else "unknown"
    reason = f"进球方向={direction}，候选: {', '.join(ttg_options)}"
    if not gate_passed:
        reason += "（门禁未通过，仅观察）"

    return MatchSuggestion(
        play_type="ttg",
        selections=ttg_options,
        market_expression=structure.main_market_expression,
        confidence=structure.research_priority,
        reason=reason,
        risks=risk_codes,
        gate_passed=gate_passed,
    )


def _latest_snapshot_time(sp_history: list[dict]) -> str | None:
    parsed = [
        (_parse_time(record.get("snapshot_time")), str(record.get("snapshot_time")))
        for record in sp_history
        if record.get("play_type") in {"had", "hhad", "ttg"}
    ]
    parsed = [(dt, raw) for dt, raw in parsed if dt is not None]
    if not parsed:
        return None
    return max(parsed, key=lambda item: item[0])[1]


def _snapshot_age_hours(match_info: dict, latest_snapshot_time: str | None, *, now_time: str | None) -> float | None:
    latest_snapshot = _parse_time(latest_snapshot_time)
    if latest_snapshot is None:
        return None
    reference = _parse_time(now_time) or _parse_time(match_info.get("match_time"))
    if reference is None:
        return None
    return max(0.0, (reference - latest_snapshot).total_seconds() / 3600)


def _snapshot_counts(sp_history: list[dict]) -> dict[str, int]:
    counts: dict[str, set[str]] = {}
    for record in sp_history:
        play_type = str(record.get("play_type", "")).lower()
        if play_type not in PLAY_SNAPSHOT_LIMITS:
            continue
        snapshot_time = str(record.get("snapshot_time", ""))
        counts.setdefault(play_type, set()).add(snapshot_time)
    return {play_type: len(times) for play_type, times in counts.items()}


def latest_play_snapshot(sp_history: list[dict], play_type: str) -> list[dict]:
    """返回指定玩法在最新快照时间的全部记录。"""
    records = [record for record in sp_history if str(record.get("play_type", "")).lower() == play_type]
    if not records:
        return []
    latest_time = max(
        (str(record.get("snapshot_time", "")) for record in records),
        default="",
    )
    return [record for record in records if str(record.get("snapshot_time", "")) == latest_time]


def latest_option_sp(sp_history: list[dict], play_type: str, option_code: str | None) -> float | None:
    """返回指定玩法/选项在最新快照中的 SP 值，未找到返回 None。"""
    if not option_code:
        return None
    records = latest_play_snapshot(sp_history, play_type)
    for record in records:
        if str(record.get("option_code", "")) == option_code:
            sp = record.get("sp_value")
            if sp is not None:
                return float(sp)
    return None


def score_from_crs_code(code: str) -> tuple[int, int] | None:
    """从 CRS option_code（如 's02s01'）解析比分，返回 (主, 客) 或 None。"""
    if not code.startswith("s") or len(code) != 6 or code.startswith("s-1"):
        return None
    try:
        return int(code[1:3]), int(code[4:6])
    except ValueError:
        return None
