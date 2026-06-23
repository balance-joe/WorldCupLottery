"""回测引擎：策略评估 + 信号回测。

提供 CLI、前端 API、agent function calling 三种调用方式。
懒加载避免 import 链触发 db 依赖。
"""


def __getattr__(name: str):
    if name == "run_backtest":
        from src.backtest.engine import run_backtest
        return run_backtest
    if name == "run_single_match_backtest":
        from src.backtest.engine import run_single_match_backtest
        return run_single_match_backtest
    if name == "list_strategies":
        from src.backtest.registry import list_strategies
        return list_strategies
    if name == "get_strategy":
        from src.backtest.registry import get_strategy
        return get_strategy
    if name in ("BacktestReport", "StrategyResult", "BetResult"):
        from src.backtest import types
        return getattr(types, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
