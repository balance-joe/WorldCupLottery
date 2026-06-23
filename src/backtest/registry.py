"""策略发现接口（供 agent function calling 使用）。"""

from __future__ import annotations

from typing import Any

from src.backtest.strategies import STRATEGY_DEFS, list_strategy_summaries


def list_strategies() -> list[dict[str, Any]]:
    """返回所有可用策略的摘要。

    每个策略包含: name, desc, play_type, conditions, stake
    """
    return list_strategy_summaries()


def get_strategy(name: str) -> dict[str, Any] | None:
    """根据名称获取单个策略的完整定义。"""
    strat = STRATEGY_DEFS.get(name)
    if strat is None:
        return None
    return dict(strat)
