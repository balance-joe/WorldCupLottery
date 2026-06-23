"""从结构化市场分析构建稳定的LLM输入包。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from src.constants import CHINA_TZ, WINDOWS
from src.market_structure import MarketStructure, PRIORITY_RANK


LLM_INSTRUCTION = (
    "请基于中国体彩竞彩足球SP变化分析市场表达。不要预测确定赛果，不要输出真实胜率，"
    "不要使用海外赔率逻辑。不要使用稳胆、必买、稳赚、模型预测等表达。"
)

FORBIDDEN_OUTPUT_TERMS = [
    "必胜", "稳赚", "稳胆", "真实胜率", "模型预测概率", "建议下注",
    "保证赢", "包赢", "必赢",
]


def build_agent_report_package(
    match_info: dict,
    window_structures: dict[str, MarketStructure],
    *,
    debug_trends: dict[str, Any] | None = None,
    non_sp_evidence: dict[str, Any] | None = None,
    sp_research_priority: str | None = None,
    non_sp_blend_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建LLM市场表达解释的紧凑默认输入。"""
    window_summaries = {}
    market_structure_summary = {}
    for window, structure in window_structures.items():
        structure_dict = structure.to_dict()
        window_summaries[window] = {
            "market_structure": structure_dict,
            "summary_signals": _summary_signals(structure),
            "risk_flags": [risk.to_dict() for risk in structure.risk_flags],
        }
        market_structure_summary[window] = structure_dict

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
        "market_structure": market_structure_summary,
        "public_info_context": _public_info_context(non_sp_evidence),
        "final_research_priority": final_research_priority(window_structures),
        "llm_instruction": LLM_INSTRUCTION,
    }
    if debug_trends is not None:
        package["debug"] = {"sp_trend_details": debug_trends}
    if non_sp_evidence is not None:
        package["non_sp_evidence"] = non_sp_evidence
    if sp_research_priority is not None:
        package["sp_research_priority"] = sp_research_priority
    if non_sp_blend_summary is not None:
        package["non_sp_blend_summary"] = non_sp_blend_summary
    return package


def build_cross_window_summary(window_structures: dict[str, MarketStructure]) -> dict[str, str]:
    long_term = window_structures.get("open_to_latest")
    recent = window_structures.get("last_6h")
    medium = window_structures.get("last_24h") or window_structures.get("last_6h")

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
        "mid_term_direction": _direction_text(medium, "最近24小时"),
        "recent_change": recent_text,
        "tempo_reading": tempo,
    }


def final_research_priority(window_structures: dict[str, MarketStructure]) -> str:
    priorities = [structure.research_priority for structure in window_structures.values() if structure.available]
    if not priorities:
        return "D"
    return sorted(priorities, key=lambda item: PRIORITY_RANK.get(item, 9))[0]


def validate_llm_output_json(data: dict[str, Any] | str) -> list[str]:
    """验证下游LLM输出结构、禁用短语和JSON解析。"""
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
    for window in WINDOWS:
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


def _public_info_context(non_sp_evidence: dict[str, Any] | None) -> dict[str, Any]:
    if not non_sp_evidence:
        return {
            "trigger_reason": "not_checked",
            "public_info_alignment": "not_checked",
            "public_info_reading": "未触发公开信息检索。",
            "findings": [],
            "unresolved_questions": [],
        }
    findings = list(non_sp_evidence.get("supporting_factors", []))
    unresolved = list(non_sp_evidence.get("risk_factors", []))
    alignment = {
        "home": "supports_sp_move",
        "away": "conflicts_with_sp_move",
        "neutral": "mixed_public_info" if findings or unresolved else "no_public_explanation",
    }.get(non_sp_evidence.get("non_sp_lean"), "no_public_explanation")
    reading = "未发现可靠公开信息解释该 SP 异动。"
    if findings:
        reading = "公开信息提供了部分背景线索，但仍需结合 SP 结构理解。"
    return {
        "trigger_reason": "non_sp_detail_bundle",
        "public_info_alignment": alignment,
        "public_info_reading": reading,
        "findings": findings,
        "unresolved_questions": unresolved,
    }
