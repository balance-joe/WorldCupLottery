"""Orchestrate SP trend, market structure, and agent report packages."""

from __future__ import annotations

from typing import Any

from src.agent_report_schema import build_agent_report_package
from src.market_structure import MarketStructure, analyze_market_structure
from src.sp_trend import WINDOWS, PlayTrend, analyze_play_trend


def analyze_match_windows(
    match_info: dict,
    sp_history: list[dict],
    *,
    windows: list[str] | tuple[str, ...] = WINDOWS,
    include_debug: bool = False,
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

    llm_package = build_agent_report_package(match_info, structures, debug_trends=debug_payload)
    return {
        "match": llm_package["match"],
        "market_structures": {window: structure.to_dict() for window, structure in structures.items()},
        "cross_window_summary": llm_package["cross_window_summary"],
        "final_research_priority": llm_package["final_research_priority"],
        "llm_input": llm_package,
        "debug_trend_details": debug_payload,
    }
