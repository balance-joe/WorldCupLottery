"""统一信号提取。消除三个回测脚本中的重复逻辑。"""

from __future__ import annotations

from src.recommendation import (
    build_match_recommendation,
    latest_option_sp,
    latest_play_snapshot,
    score_from_crs_code,
)
from src.sp_trend import analyze_play_trend


def extract_had_signal(sp_history: list[dict], match_id: str) -> str | None:
    """HAD 趋势信号 → H/D/A。"""
    for window in ("open_to_latest", "last_24h", "last_6h"):
        trend = analyze_play_trend(match_id, "had", window, sp_history)
        if not trend.available:
            continue
        d = trend.main_direction
        if "home_win" in d:
            return "H"
        if "draw" in d:
            return "D"
        if "away_win" in d:
            return "A"
    return None


def extract_hhad_signal(sp_history: list[dict], match_id: str) -> tuple[str | None, str | None]:
    """HHAD 趋势信号 → (方向, 让球数)。"""
    for window in ("open_to_latest", "last_24h", "last_6h"):
        trend = analyze_play_trend(match_id, "hhad", window, sp_history)
        if not trend.available:
            continue
        d = trend.main_direction
        direction = None
        if "home" in d:
            direction = "H"
        elif "draw" in d:
            direction = "D"
        elif "away" in d:
            direction = "A"
        if direction:
            return direction, trend.handicap_line
    return None, None


def extract_ttg_signal(sp_history: list[dict], match_id: str) -> str | None:
    """TTG 趋势信号 → low/mid/high。"""
    for window in ("open_to_latest", "last_24h", "last_6h"):
        trend = analyze_play_trend(match_id, "ttg", window, sp_history)
        if not trend.available:
            continue
        d = trend.main_direction
        if "low_goal" in d:
            return "low"
        if "mid_goal" in d:
            return "mid"
        if "high_goal" in d:
            return "high"
    return None


def extract_crs_top(sp_history: list[dict], match_id: str, n: int = 5) -> list[str]:
    """CRS 最新快照中概率最高的 n 个比分。返回如 ['1:0', '0:0']。"""
    records = [
        r for r in sp_history
        if str(r.get("match_id")) == match_id and r.get("play_type") == "crs"
    ]
    if not records:
        return []
    latest_time = max(str(r.get("snapshot_time", "")) for r in records)
    latest = [r for r in records if str(r.get("snapshot_time", "")) == latest_time]
    scored = []
    for r in latest:
        prob = r.get("implied_prob_norm") or 0
        score = _crs_code_to_score(str(r["option_code"]))
        if score:
            scored.append((score, prob))
    scored.sort(key=lambda x: -x[1])
    return [s for s, _ in scored[:n]]


def extract_hafu_top(sp_history: list[dict], match_id: str) -> str | None:
    """HAFU 最新快照中概率最高的选项 code。"""
    records = [
        r for r in sp_history
        if str(r.get("match_id")) == match_id and r.get("play_type") == "hafu"
    ]
    if not records:
        return None
    latest_time = max(str(r.get("snapshot_time", "")) for r in records)
    latest = [r for r in records if str(r.get("snapshot_time", "")) == latest_time]
    if not latest:
        return None
    best = max(latest, key=lambda r: r.get("implied_prob_norm") or 0)
    return str(best["option_code"])


def extract_match_signals(
    match_info: dict,
    match_id: str,
    sp_history: list[dict],
) -> dict:
    """提取一场比赛的全部信号，供策略过滤器使用。"""
    recommendation = build_match_recommendation(match_info, sp_history, window="open_to_latest")
    had_trend = recommendation.had_trend
    hhad_trend = recommendation.hhad_trend
    ttg_trend = recommendation.ttg_trend
    structure = recommendation.structure

    # HAD 买什么
    had_bet = None
    had_bet_sp = None
    had_confidence = "none"
    if had_trend.available:
        if recommendation.candidates.had_options:
            had_bet = recommendation.candidates.had_options[0]
        had_confidence = had_trend.direction_confidence
        if had_bet and had_trend.options:
            for opt in had_trend.options:
                if opt.option_code == had_bet:
                    had_bet_sp = opt.sp_end

    # HHAD 是否确认 HAD
    hhad_confirms_had = False
    if had_bet and hhad_trend.available:
        hd = hhad_trend.main_direction
        if had_bet == "H" and "home" in hd:
            hhad_confirms_had = True
        elif had_bet == "A" and "away" in hd:
            hhad_confirms_had = True
        elif had_bet == "D" and "draw" in hd:
            hhad_confirms_had = True

    # TTG 买什么
    ttg_bet = None
    ttg_confidence = "none"
    if ttg_trend.available:
        ttg_confidence = ttg_trend.direction_confidence
        if recommendation.candidates.ttg_options:
            ttg_bet = recommendation.candidates.ttg_options[0]

    # CRS 最高概率
    crs_top1 = None
    if recommendation.candidates.crs_options:
        crs_top1 = recommendation.candidates.crs_options[0]
    else:
        crs_records = [
            r for r in sp_history
            if str(r.get("match_id")) == match_id and r.get("play_type") == "crs"
        ]
        if crs_records:
            latest_time = max(str(r.get("snapshot_time", "")) for r in crs_records)
            latest = [r for r in crs_records if str(r.get("snapshot_time", "")) == latest_time]
            if latest:
                best = max(latest, key=lambda r: r.get("implied_prob_norm") or 0)
                crs_top1 = best["option_code"]

    # HAFU 最高概率
    hafu_top1 = None
    hafu_records = [
        r for r in sp_history
        if str(r.get("match_id")) == match_id and r.get("play_type") == "hafu"
    ]
    if hafu_records:
        latest_time = max(str(r.get("snapshot_time", "")) for r in hafu_records)
        latest = [r for r in hafu_records if str(r.get("snapshot_time", "")) == latest_time]
        if latest:
            best = max(latest, key=lambda r: r.get("implied_prob_norm") or 0)
            hafu_top1 = best["option_code"]

    return {
        "had_bet": had_bet,
        "had_bet_sp": had_bet_sp,
        "had_confidence": had_confidence,
        "hhad_confirms_had": hhad_confirms_had,
        "ttg_bet": ttg_bet,
        "ttg_confidence": ttg_confidence,
        "crs_top1": crs_top1,
        "hafu_top1": hafu_top1,
        "expression": structure.main_market_expression if structure else "mixed_or_noisy",
        "priority": structure.research_priority if structure else "D",
        "consistency": structure.consistency_level if structure else "none",
        "gate_allowed": recommendation.gate.allowed,
        "allowed_plays": recommendation.gate.allowed_plays,
        "gate_reasons": recommendation.gate.reasons,
    }


def _crs_code_to_score(code: str) -> str | None:
    """crs option_code → 比分字符串。如 's01s02' → '1:2'。"""
    if code in ("s-1sh", "s-1sd", "s-1sa"):
        return None
    if code.startswith("s") and len(code) == 6:
        home = code[1:3].lstrip("0") or "0"
        away = code[4:6].lstrip("0") or "0"
        return f"{home}:{away}"
    return None
