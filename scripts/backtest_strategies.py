"""
策略回测：在全部有 SP+赛果的比赛上模拟不同买入策略。

用法:
    python -m scripts.backtest_strategies
    python -m scripts.backtest_strategies --detail
    python -m scripts.backtest_strategies --strategy A-HAD --league 世界杯
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src import db
from src.backtest.engine import run_backtest
from src.backtest.registry import list_strategies


def main():
    parser = argparse.ArgumentParser(description="策略回测")
    parser.add_argument("--detail", action="store_true", help="逐场详情")
    parser.add_argument("--strategy", action="append", help="指定策略名（可多次使用）")
    parser.add_argument("--league", help="只回测指定赛事")
    parser.add_argument("--date-from", help="比赛日期起始（YYYY-MM-DD）")
    parser.add_argument("--date-to", help="比赛日期截止（YYYY-MM-DD）")
    parser.add_argument("--list", action="store_true", help="列出所有可用策略")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    args = parser.parse_args()

    if args.list:
        for s in list_strategies():
            print(f"  {s['name']:<20} {s['desc']}")
            print(f"    玩法: {s['play_type']}  注额: {s['stake']}")
        return

    conn = db.get_connection()
    try:
        report = run_backtest(
            conn,
            strategy_names=args.strategy,
            league=args.league,
            match_date_from=args.date_from,
            match_date_to=args.date_to,
        )

        if args.json:
            print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
            return

        print(f"\n{'=' * 70}")
        print(f"策略回测结果 ({report.match_count} 场比赛)")
        print(f"计算时间: {report.computed_at}")
        print(f"{'=' * 70}")

        print(f"\n{'策略':<20} {'触发':>4} {'命中':>4} {'命中率':>7} {'投入':>6} {'奖金':>8} {'盈亏':>8} {'ROI':>7}")
        print("-" * 70)

        for s in report.strategies:
            if s.total_bets == 0:
                continue
            hr = f"{s.hit_rate:.1%}"
            roi = f"{s.roi:.1%}"
            print(
                f"{s.strategy_name:<20} {s.total_bets:>4} {s.wins:>4} {hr:>7} "
                f"{s.total_stake:>6.0f} {s.total_payout:>8.2f} "
                f"{s.profit_loss:>+8.2f} {roi:>7}"
            )

        if args.detail:
            for s in report.strategies:
                if not s.bets:
                    continue
                print(f"\n{'─' * 70}")
                print(f"策略: {s.strategy_name} — {s.strategy_desc}")
                print(f"{'─' * 70}")
                for b in s.bets:
                    mark = "HIT" if b.hit else "MISS"
                    sp_str = f"{b.sp_value:.2f}" if b.sp_value else "?"
                    pl = b.payout - b.stake
                    pl_str = f"{pl:+.2f}"
                    print(
                        f"  {mark} {b.match_info:<25} {b.score or '?':<6} "
                        f"bet={b.bet_option} sp={sp_str:<5} {pl_str:>7}"
                    )

        # 最优策略
        profitable = [s for s in report.strategies if s.profit_loss > 0 and s.total_bets >= 3]
        if profitable:
            best = max(profitable, key=lambda s: s.roi)
            print(f"\n最优策略: {best.strategy_name} — {best.strategy_desc}")
            print(f"  触发 {best.total_bets} 场, 命中 {best.wins}, ROI {best.roi:.1%}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
