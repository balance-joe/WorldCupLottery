"""Orchestrate SP trend, market structure, and agent report packages."""

from __future__ import annotations

from typing import Any

from src.agent_report_schema import build_agent_report_package
from src.market_structure import MarketStructure, analyze_market_structure
from src.non_sp_evidence import build_non_sp_evidence
from src.sp_trend import WINDOWS, PlayTrend, analyze_play_trend


def analyze_match_windows(
    match_info: dict,
    sp_history: list[dict],
    *,
    windows: list[str] | tuple[str, ...] = WINDOWS,
    include_debug: bool = False,
    detail_bundle: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """Analyze one match across windows and build an LLM-ready package."""
    match_id = str(match_info.get("match_id", ""))
    trend_details: dict[str, dict[str, PlayTrend]] = {}
    structures: dict[str, MarketStructure] = {}

    for window in windows:
        had = analyze_play_trend(match_id, "had", window, sp_history)
        hhad = analyze_play_trend(match_id, "hhad", window, sp_history)
        ttg = analyze_play_trend(match_id, "ttg", window, sp_history)
        trend_details[window] = {"had": had, "hhad": hhad, "ttg": ttg}
        structures[window] = analyze_market_structure(match_id, window, had, hhad, ttg)

    debug_payload = None
    if include_debug:
        debug_payload = {
            window: {play: trend.to_dict() for play, trend in trends.items()}
            for window, trends in trend_details.items()
        }

    sp_research_priority = _best_structure_priority(structures)
    non_sp_evidence = build_non_sp_evidence(detail_bundle) if detail_bundle else None
    blended_priority, blend_summary = _blend_research_priority(structures, sp_research_priority, non_sp_evidence)
    llm_package = build_agent_report_package(
        match_info,
        structures,
        debug_trends=debug_payload,
        non_sp_evidence=non_sp_evidence,
        sp_research_priority=sp_research_priority,
        non_sp_blend_summary=blend_summary,
    )
    llm_package["final_research_priority"] = blended_priority
    return {
        "match": llm_package["match"],
        "market_structures": {window: structure.to_dict() for window, structure in structures.items()},
        "cross_window_summary": llm_package["cross_window_summary"],
        "sp_research_priority": sp_research_priority,
        "final_research_priority": blended_priority,
        "non_sp_evidence": non_sp_evidence,
        "non_sp_blend_summary": blend_summary,
        "llm_input": llm_package,
        "debug_trend_details": debug_payload,
    }


def _best_structure_priority(structures: dict[str, MarketStructure]) -> str:
    priorities = [structure.research_priority for structure in structures.values() if structure.available]
    if not priorities:
        return "D"
    order = {"A": 0, "B": 1, "C": 2, "D": 3}
    return sorted(priorities, key=lambda item: order.get(item, 9))[0]


def _blend_research_priority(
    structures: dict[str, MarketStructure],
    sp_priority: str,
    non_sp_evidence: dict[str, Any] | None,
) -> tuple[str, dict[str, Any] | None]:
    if not non_sp_evidence:
        return sp_priority, None

    sp_lean = _derive_sp_lean(structures)
    non_sp_lean = non_sp_evidence.get("non_sp_lean", "neutral")
    confidence = non_sp_evidence.get("support_confidence", "none")
    risks = non_sp_evidence.get("risk_factors", [])

    reason = "non_sp_neutral"
    adjusted = sp_priority
    if sp_lean in {"home", "away"} and non_sp_lean == sp_lean and confidence in {"medium", "high"}:
        adjusted = _shift_priority(sp_priority, -1)
        reason = "non_sp_confirms_sp"
    elif sp_lean in {"home", "away"} and non_sp_lean in {"home", "away"} and non_sp_lean != sp_lean and confidence in {"medium", "high"}:
        adjusted = _shift_priority(sp_priority, 1)
        reason = "non_sp_conflicts_with_sp"
    elif len(risks) >= 2 and confidence in {"none", "low"}:
        adjusted = _shift_priority(sp_priority, 1)
        reason = "non_sp_adds_risk"

    if sp_priority == "D" and adjusted != "D":
        adjusted = "C"

    return adjusted, {
        "sp_lean": sp_lean,
        "non_sp_lean": non_sp_lean,
        "support_confidence": confidence,
        "risk_count": len(risks),
        "reason": reason,
        "adjusted_from": sp_priority,
        "adjusted_to": adjusted,
    }


def _derive_sp_lean(structures: dict[str, MarketStructure]) -> str:
    for window in ("open_to_latest", "last_24h", "last_6h", "last_1h"):
        structure = structures.get(window)
        if not structure or not structure.available:
            continue
        if structure.had_direction in {"home_win_strengthening", "home_unbeaten_strengthening"}:
            return "home"
        if structure.had_direction in {"away_win_strengthening", "away_unbeaten_strengthening"}:
            return "away"
        if structure.main_market_expression == "home_big_win_supported":
            return "home"
        if structure.main_market_expression == "away_not_lose_or_small_win_supported":
            return "away"
    return "neutral"


def _shift_priority(priority: str, offset: int) -> str:
    order = ["A", "B", "C", "D"]
    try:
        index = order.index(priority)
    except ValueError:
        return priority
    return order[max(0, min(len(order) - 1, index + offset))]
