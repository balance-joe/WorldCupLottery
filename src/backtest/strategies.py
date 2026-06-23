"""策略注册表：数据驱动的策略定义，可序列化。"""

from __future__ import annotations

from typing import Any


# ── 策略定义 ────────────────────────────────────────────────────────────────

STRATEGY_DEFS: dict[str, dict[str, Any]] = {
    "A-HAD": {
        "name": "A-HAD",
        "desc": "只买 priority A 的 HAD 方向",
        "play_type": "had",
        "conditions": {
            "priority": ["A"],
            "gate_allowed": True,
            "play_in_allowed": "had",
        },
        "pick": "had_first",
        "stake": 10,
    },
    "AB-HAD": {
        "name": "AB-HAD",
        "desc": "买 priority A+B 的 HAD 方向",
        "play_type": "had",
        "conditions": {
            "priority": ["A", "B"],
            "gate_allowed": True,
            "play_in_allowed": "had",
        },
        "pick": "had_first",
        "stake": 10,
    },
    "triple-confirm": {
        "name": "triple-confirm",
        "desc": "三线一致时买 HAD (home_big_win / away_not_lose)",
        "play_type": "had",
        "conditions": {
            "gate_allowed": True,
            "play_in_allowed": "had",
            "expression": [
                "home_big_win_supported",
                "away_not_lose_or_small_win_supported",
            ],
        },
        "pick": "had_first",
        "stake": 10,
    },
    "low-sp-high-conf": {
        "name": "low-sp-high-conf",
        "desc": "低 SP (<1.6) + medium/high 置信的 HAD",
        "play_type": "had",
        "conditions": {
            "gate_allowed": True,
            "play_in_allowed": "had",
            "had_sp_max": 1.6,
            "had_confidence": ["medium", "high"],
        },
        "pick": "had_first",
        "stake": 10,
    },
    "mid-sp-confirm": {
        "name": "mid-sp-confirm",
        "desc": "中等 SP (1.6-2.5) + hhad 确认的 HAD",
        "play_type": "had",
        "conditions": {
            "gate_allowed": True,
            "play_in_allowed": "had",
            "had_sp_min": 1.6,
            "had_sp_max": 2.5,
            "hhad_confirms_had": True,
        },
        "pick": "had_first",
        "stake": 10,
    },
    "TTG-medium-conf": {
        "name": "TTG-medium-conf",
        "desc": "TTG medium/high 置信时买 TTG 方向",
        "play_type": "ttg",
        "conditions": {
            "gate_allowed": True,
            "play_in_allowed": "ttg",
            "ttg_confidence": ["medium", "high"],
        },
        "pick": "ttg_first",
        "stake": 10,
    },
    "CRS-top1": {
        "name": "CRS-top1",
        "desc": "CRS 最高概率比分",
        "play_type": "crs",
        "conditions": {
            "gate_allowed": True,
            "play_in_allowed": "crs",
            "crs_top1_not_null": True,
        },
        "pick": "crs_top1",
        "stake": 2,
    },
    "HAFU-top1": {
        "name": "HAFU-top1",
        "desc": "HAFU 最高概率选项",
        "play_type": "hafu",
        "conditions": {
            "gate_allowed": True,
            "hafu_top1_not_null": True,
        },
        "pick": "hafu_top1",
        "stake": 2,
    },
    "ABC-HAD-any": {
        "name": "ABC-HAD-any",
        "desc": "只要 had 有方向就买 (对照组)",
        "play_type": "had",
        "conditions": {
            "gate_allowed": True,
            "play_in_allowed": "had",
            "had_bet_not_null": True,
        },
        "pick": "had_first",
        "stake": 10,
    },
}


def list_strategy_summaries() -> list[dict[str, Any]]:
    """返回所有策略摘要（供 agent function calling 使用）。"""
    return [
        {
            "name": s["name"],
            "desc": s["desc"],
            "play_type": s["play_type"],
            "conditions": s["conditions"],
            "stake": s["stake"],
        }
        for s in STRATEGY_DEFS.values()
    ]


def match_conditions(strategy_def: dict[str, Any], signals: dict) -> bool:
    """检查 signals 是否满足策略的 conditions。"""
    conds = strategy_def.get("conditions", {})

    # priority 过滤
    allowed_priorities = conds.get("priority")
    if allowed_priorities and signals.get("priority") not in allowed_priorities:
        return False

    # gate 必须通过
    if conds.get("gate_allowed") and not signals.get("gate_allowed", False):
        return False

    # 玩法必须在允许列表中
    required_play = conds.get("play_in_allowed")
    if required_play:
        allowed_plays = signals.get("allowed_plays", ())
        if required_play not in allowed_plays:
            return False

    # expression 过滤
    allowed_expressions = conds.get("expression")
    if allowed_expressions and signals.get("expression") not in allowed_expressions:
        return False

    # HAD SP 范围
    had_sp = signals.get("had_bet_sp")
    sp_max = conds.get("had_sp_max")
    sp_min = conds.get("had_sp_min")
    if sp_max is not None and (had_sp is None or had_sp >= sp_max):
        return False
    if sp_min is not None and (had_sp is None or had_sp < sp_min):
        return False

    # HAD 置信度
    allowed_conf = conds.get("had_confidence")
    if allowed_conf and signals.get("had_confidence") not in allowed_conf:
        return False

    # HHAD 确认 HAD
    if conds.get("hhad_confirms_had") and not signals.get("hhad_confirms_had", False):
        return False

    # TTG 置信度
    allowed_ttg_conf = conds.get("ttg_confidence")
    if allowed_ttg_conf and signals.get("ttg_confidence") not in allowed_ttg_conf:
        return False

    # CRS top1 非空
    if conds.get("crs_top1_not_null") and signals.get("crs_top1") is None:
        return False

    # HAFU top1 非空
    if conds.get("hafu_top1_not_null") and signals.get("hafu_top1") is None:
        return False

    # HAD bet 非空
    if conds.get("had_bet_not_null") and signals.get("had_bet") is None:
        return False

    return True


def pick_option(strategy_def: dict[str, Any], signals: dict) -> str | None:
    """根据策略的 pick 规则从 signals 中选取下注选项。"""
    pick_rule = strategy_def.get("pick", "")

    if pick_rule == "had_first":
        return signals.get("had_bet")
    if pick_rule == "ttg_first":
        return signals.get("ttg_bet")
    if pick_rule == "crs_top1":
        return signals.get("crs_top1")
    if pick_rule == "hafu_top1":
        return signals.get("hafu_top1")
    return None
