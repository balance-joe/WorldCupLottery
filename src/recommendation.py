"""Recommendation gates and candidate generation for Sporttery picks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from src.market_structure import MarketStructure, analyze_market_structure
from src.sp_trend import PlayTrend, analyze_play_trend


CHINA_TZ = timezone(timedelta(hours=8))
# Gate settings are intentionally conservative: they should block weak or stale
# markets before any ticket construction logic runs.
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
    ttg_options: tuple[str, ...]
    crs_options: tuple[str, ...]

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate.to_dict(),
            "structure": self.structure.to_dict(),
            "had_trend": self.had_trend.to_dict(),
            "hhad_trend": self.hhad_trend.to_dict(),
            "ttg_trend": self.ttg_trend.to_dict(),
            "candidates": self.candidates.to_dict(),
        }


def filter_sp_records_as_of(sp_records: list[dict], cutoff_time: str | None) -> list[dict]:
    """Return records whose snapshot_time is not later than the cutoff."""
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
    """Analyze one match and return a gated recommendation payload."""
    match_id = str(match_info.get("match_id", ""))
    had = analyze_play_trend(match_id, "had", window, sp_history)
    hhad = analyze_play_trend(match_id, "hhad", window, sp_history)
    ttg = analyze_play_trend(match_id, "ttg", window, sp_history)
    structure = analyze_market_structure(match_id, window, had, hhad, ttg)
    gate = _build_gate(match_info, sp_history, structure, had, hhad, ttg, now_time=now_time)
    candidates = _build_candidates(sp_history, structure, had, ttg)
    return MatchRecommendation(
        gate=gate,
        structure=structure,
        had_trend=had,
        hhad_trend=hhad,
        ttg_trend=ttg,
        candidates=candidates,
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
    ttg: PlayTrend,
) -> RecommendationCandidates:
    had_options = _had_candidates(had)
    ttg_options = _ttg_candidates(sp_history, ttg)
    crs_options = _crs_candidates(sp_history, structure, had_options, ttg_options)
    return RecommendationCandidates(
        had_options=tuple(had_options),
        ttg_options=tuple(ttg_options),
        crs_options=tuple(crs_options),
    )


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


def _ttg_candidates(sp_history: list[dict], ttg: PlayTrend) -> list[str]:
    if not ttg.available:
        return []
    latest = _latest_play_snapshot(sp_history, "ttg")
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
    latest = _latest_play_snapshot(sp_history, "crs")
    if not latest:
        return []
    allowed_totals = {int(option) for option in ttg_options if str(option).isdigit()}
    scored = []
    for row in latest:
        score = _score_from_crs_code(str(row.get("option_code", "")))
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


def _latest_play_snapshot(sp_history: list[dict], play_type: str) -> list[dict]:
    records = [record for record in sp_history if str(record.get("play_type", "")).lower() == play_type]
    if not records:
        return []
    latest_time = max(
        (str(record.get("snapshot_time", "")) for record in records),
        default="",
    )
    return [record for record in records if str(record.get("snapshot_time", "")) == latest_time]


def _score_from_crs_code(code: str) -> tuple[int, int] | None:
    if not code.startswith("s") or len(code) != 6 or code.startswith("s-1"):
        return None
    try:
        return int(code[1:3]), int(code[4:6])
    except ValueError:
        return None


def _parse_time(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=CHINA_TZ)
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("T", " ")
    if text.endswith("+08:00"):
        text = text[:-6]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=CHINA_TZ)
        except ValueError:
            continue
    return None
