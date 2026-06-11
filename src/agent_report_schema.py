"""Build stable LLM input packages from structured market analysis."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from src.market_structure import MarketStructure, PRIORITY_RANK


LLM_INSTRUCTION = (
    "请基于中国体彩竞彩足球SP变化分析市场表达。不要预测确定赛果，不要输出真实胜率，"
    "不要使用海外赔率逻辑。不要使用稳胆、必买、稳赚、模型预测等表达。"
)

FORBIDDEN_OUTPUT_TERMS = ["必胜", "稳赚", "稳胆", "真实胜率", "模型预测概率", "建议下注"]
CHINA_TZ = timezone(timedelta(hours=8))


def build_agent_report_package(
    match_info: dict,
    window_structures: dict[str, MarketStructure],
    *,
    debug_trends: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build compact default input for LLM market-expression explanation."""
    window_summaries = {}
    for window, structure in window_structures.items():
        window_summaries[window] = {
            "market_structure": structure.to_dict(),
            "summary_signals": _summary_signals(structure),
            "risk_flags": [risk.to_dict() for risk in structure.risk_flags],
        }

    package = {
        "match": {
            "match_id": str(match_info.get("match_id", "")),
            "match_num": match_info.get("match_num"),
            "league": match_info.get("league_name"),
            "match_time": _iso_match_time(match_info.get("match_time")),
            "home_team": match_info.get("home_team_name"),
            "away_team": match_info.get("away_team_name"),
            "handicap_line": _first_handicap_line(window_structures),
        },
        "window_summaries": window_summaries,
        "cross_window_summary": build_cross_window_summary(window_structures),
        "final_research_priority": final_research_priority(window_structures),
        "llm_instruction": LLM_INSTRUCTION,
    }
    if debug_trends is not None:
        package["debug_trend_details"] = debug_trends
    return package


def build_cross_window_summary(window_structures: dict[str, MarketStructure]) -> dict[str, str]:
    long_term = window_structures.get("open_to_latest")
    recent = window_structures.get("last_1h") or window_structures.get("last_6h")
    medium = window_structures.get("last_6h") or window_structures.get("last_24h")

    long_text = _direction_text(long_term, "开售至今")
    recent_text = _direction_text(recent, "临场")

    tempo = "全部窗口无明显方向，暂不适合作为重点研究对象。"
    if long_term and recent:
        if _same_expression(long_term, recent) and long_term.research_priority in {"A", "B"}:
            tempo = "长期与临场市场表达大体一致，结构延续性较好。"
        elif long_term.main_market_expression != "mixed_or_noisy" and recent.main_market_expression == "mixed_or_noisy":
            tempo = "长期有表达，但临场转弱或变乱，需要降低追随确定性。"
        elif long_term.main_market_expression == "mixed_or_noisy" and recent.main_market_expression != "mixed_or_noisy":
            tempo = "长期无明显方向，但临场出现新表达，适合人工复核是否为临场异动。"
        elif long_term.main_market_expression != recent.main_market_expression:
            tempo = "长期和临场表达不一致，需要重点排查信息变化和玩法冲突。"

    return {
        "long_term_direction": long_text,
        "mid_term_direction": _direction_text(medium, "最近6小时"),
        "recent_change": recent_text,
        "tempo_reading": tempo,
    }


def final_research_priority(window_structures: dict[str, MarketStructure]) -> str:
    priorities = [structure.research_priority for structure in window_structures.values() if structure.available]
    if not priorities:
        return "D"
    return sorted(priorities, key=lambda item: PRIORITY_RANK.get(item, 9))[0]


def validate_llm_output_json(data: dict[str, Any] | str) -> list[str]:
    """Validate downstream LLM output shape, banned phrases, and JSON parsing."""
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as exc:
            return [f"invalid json: {exc.msg}"]
        if not isinstance(data, dict):
            return ["json root must be an object"]

    required = {
        "market_reading",
        "play_consistency",
        "tempo_reading",
        "risk_explanations",
        "suggested_human_focus",
        "avoid_or_caution",
        "research_priority",
        "confidence_type",
    }
    errors = [f"missing field: {field}" for field in sorted(required - set(data))]
    text = str(data)
    for term in FORBIDDEN_OUTPUT_TERMS:
        if term in text:
            errors.append(f"forbidden term: {term}")
    if data.get("confidence_type") not in {None, "structure_confidence_not_win_probability"}:
        errors.append("confidence_type must be structure_confidence_not_win_probability")
    return errors


def _summary_signals(structure: MarketStructure) -> list[str]:
    signals = [f"市场表达: {structure.main_market_expression}", f"研究优先级: {structure.research_priority}"]
    if structure.had_direction:
        signals.append(f"胜平负: {structure.had_direction}")
    if structure.hhad_direction:
        signals.append(f"让球胜平负: {structure.hhad_direction}")
    if structure.ttg_direction:
        signals.append(f"总进球: {structure.ttg_direction}")
    return signals


def _direction_text(structure: MarketStructure | None, label: str) -> str:
    if structure is None or not structure.available:
        return f"{label}数据不足"
    return f"{label}{structure.main_market_expression}，优先级{structure.research_priority}"


def _same_expression(left: MarketStructure, right: MarketStructure) -> bool:
    return left.main_market_expression == right.main_market_expression


def _first_handicap_line(window_structures: dict[str, MarketStructure]) -> str | None:
    for window in ("open_to_latest", "last_24h", "last_6h", "last_1h"):
        structure = window_structures.get(window)
        if structure and structure.handicap_line is not None:
            return structure.handicap_line
    for structure in window_structures.values():
        if structure.handicap_line is not None:
            return structure.handicap_line
    return None


def _iso_match_time(value) -> str | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value:
        text = value.replace("T", " ")
        try:
            dt = datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                dt = datetime.strptime(text[:16], "%Y-%m-%d %H:%M")
            except ValueError:
                return value
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CHINA_TZ)
    return dt.astimezone(CHINA_TZ).isoformat()
