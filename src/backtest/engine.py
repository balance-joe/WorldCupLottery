"""回测引擎：加载数据 → 提取信号 → 逐策略评估 → 汇总。"""

from __future__ import annotations

from datetime import datetime

from src import db
from src.backtest.signals import extract_match_signals
from src.backtest.settle import get_sp_for_option, settle_bet
from src.backtest.strategies import STRATEGY_DEFS, list_strategy_summaries, match_conditions, pick_option
from src.backtest.types import BacktestReport, BetResult, StrategyResult


def run_backtest(
    conn,
    *,
    strategy_names: list[str] | None = None,
    league: str | None = None,
    match_date_from: str | None = None,
    match_date_to: str | None = None,
    unit_stake: float = 2.0,
) -> BacktestReport:
    """回测指定策略（默认全部）。

    Args:
        conn: 数据库连接
        strategy_names: 要回测的策略名列表，None = 全部
        league: 只回测指定赛事
        match_date_from: 比赛日期起始（含）
        match_date_to: 比赛日期截止（含）
        unit_stake: 每注金额（影响 payout 计算，但策略自身有 stake 定义）

    Returns:
        BacktestReport
    """
    # 确定要跑的策略
    if strategy_names:
        strats = {name: STRATEGY_DEFS[name] for name in strategy_names if name in STRATEGY_DEFS}
    else:
        strats = dict(STRATEGY_DEFS)

    if not strats:
        return BacktestReport(match_count=0, strategies=(), computed_at=_now())

    # 加载有赛果 + SP 的比赛
    matches = _load_matches(conn, league=league, date_from=match_date_from, date_to=match_date_to)
    if not matches:
        return BacktestReport(match_count=0, strategies=(), computed_at=_now())

    match_ids = [m["match_id"] for m in matches]
    sp_history = db.fetch_all_sp_history(conn, match_ids)

    # 提取每场比赛的信号
    match_signals = {}
    for m in matches:
        mid = str(m["match_id"])
        match_signals[mid] = extract_match_signals(m, mid, sp_history)

    # 逐策略回测
    results: list[StrategyResult] = []
    for strat_def in strats.values():
        bets: list[BetResult] = []
        for m in matches:
            mid = str(m["match_id"])
            sig = match_signals[mid]

            if not match_conditions(strat_def, sig):
                continue

            bet_option = pick_option(strat_def, sig)
            if bet_option is None:
                continue

            sp = get_sp_for_option(strat_def["play_type"], bet_option, sp_history, mid)
            stake = strat_def["stake"]
            result = settle_bet(strat_def["play_type"], bet_option, m, sp, stake)
            # 用策略定义的 stake 覆盖
            if result.stake != stake:
                payout = round(sp * stake, 2) if result.hit and sp else 0.0
                result = BetResult(
                    match_id=result.match_id,
                    match_info=result.match_info,
                    score=result.score,
                    play_type=result.play_type,
                    bet_option=result.bet_option,
                    sp_value=result.sp_value,
                    hit=result.hit,
                    actual_result=result.actual_result,
                    stake=stake,
                    payout=payout,
                )
            bets.append(result)

        wins = sum(1 for b in bets if b.hit is True)
        losses = sum(1 for b in bets if b.hit is False)
        total = len(bets)
        total_stake = sum(b.stake for b in bets)
        total_payout = sum(b.payout for b in bets)
        results.append(StrategyResult(
            strategy_name=strat_def["name"],
            strategy_desc=strat_def["desc"],
            play_type=strat_def["play_type"],
            total_bets=total,
            wins=wins,
            losses=losses,
            hit_rate=round(wins / total, 4) if total else 0.0,
            total_stake=round(total_stake, 2),
            total_payout=round(total_payout, 2),
            profit_loss=round(total_payout - total_stake, 2),
            roi=round((total_payout - total_stake) / total_stake, 4) if total_stake else 0.0,
            bets=tuple(bets),
        ))

    # 按 ROI 降序排序
    results.sort(key=lambda r: r.roi, reverse=True)
    return BacktestReport(
        match_count=len(matches),
        strategies=tuple(results),
        computed_at=_now(),
    )


def run_single_match_backtest(
    conn,
    match_id: str,
    strategy_names: list[str] | None = None,
) -> dict:
    """单场回测（给前端详情用）。"""
    match = db.fetch_match(conn, match_id)
    if not match:
        return {"error": "match not found"}

    sp_history = db.fetch_all_sp_history(conn, [match_id])
    signals = extract_match_signals(match, match_id, sp_history)

    if strategy_names:
        strats = {name: STRATEGY_DEFS[name] for name in strategy_names if name in STRATEGY_DEFS}
    else:
        strats = dict(STRATEGY_DEFS)

    results = []
    for strat_def in strats.values():
        if not match_conditions(strat_def, signals):
            results.append({"strategy": strat_def["name"], "triggered": False})
            continue

        bet_option = pick_option(strat_def, signals)
        if bet_option is None:
            results.append({"strategy": strat_def["name"], "triggered": False})
            continue

        sp = get_sp_for_option(strat_def["play_type"], bet_option, sp_history, match_id)
        result = settle_bet(strat_def["play_type"], bet_option, match, sp, strat_def["stake"])
        results.append({
            "strategy": strat_def["name"],
            "triggered": True,
            "bet": result.to_dict(),
        })

    return {
        "match_id": match_id,
        "signals": signals,
        "strategy_results": results,
    }


def _load_matches(
    conn,
    *,
    league: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """加载有赛果 + SP 历史的比赛。"""
    sql = """
        SELECT DISTINCT m.match_id, m.match_num, m.league_name, m.match_time,
               m.home_team_name, m.away_team_name, m.result_90,
               m.home_score_90, m.away_score_90, m.half_score, m.full_score_90
        FROM sporttery_match m
        JOIN sporttery_sp_snapshot s ON s.match_id = m.match_id
        WHERE m.result_90 IS NOT NULL
    """
    params: list = []
    if league:
        sql += " AND m.league_name = ?"
        params.append(league)
    if date_from:
        sql += " AND date(m.match_time) >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND date(m.match_time) <= ?"
        params.append(date_to)
    sql += " ORDER BY m.match_time, m.match_id"

    cur = conn.execute(sql, params)
    return [dict(zip([d[0] for d in cur.description], row)) for row in cur.fetchall()]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
