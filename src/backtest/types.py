"""回测结果数据类型。所有类型可直接 JSON 序列化。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class BetResult:
    """单笔模拟投注结果。"""
    match_id: str
    match_info: str          # "主队 vs 客队"
    score: str | None        # "2:1"
    play_type: str           # "had"|"hhad"|"ttg"|"crs"|"hafu"
    bet_option: str          # 下注选项 code
    sp_value: float | None   # 下注时 SP
    hit: bool | None         # None = 无法判定（缺少赛果）
    actual_result: str       # 实际结果 code
    stake: float
    payout: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StrategyResult:
    """单个策略的回测汇总。"""
    strategy_name: str
    strategy_desc: str
    play_type: str | None
    total_bets: int
    wins: int
    losses: int
    hit_rate: float
    total_stake: float
    total_payout: float
    profit_loss: float
    roi: float
    bets: tuple[BetResult, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["bets"] = [b.to_dict() for b in self.bets]
        return data


@dataclass(frozen=True)
class BacktestReport:
    """完整回测报告。"""
    match_count: int
    strategies: tuple[StrategyResult, ...]
    computed_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_count": self.match_count,
            "strategies": [s.to_dict() for s in self.strategies],
            "computed_at": self.computed_at,
        }
