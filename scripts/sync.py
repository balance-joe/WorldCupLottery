"""
竞彩足球定时同步脚本 — 赛果回填 + 赔率更新

Usage:
    python -m scripts.sync                    # 单次执行
    python -m scripts.sync --interval 300     # 每 5 分钟循环
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src import api_client, parsers, probability, db


# ── 赛果回填 ─────────────────────────────────────────────────────────────────

def sync_results(conn) -> int:
    """拉取已结束比赛，更新比分和赛果。返回更新数量。"""
    raw, err = api_client.fetch_result_list(page_size=50)
    if err:
        print(f"  ✗ 赛果拉取失败: {err}")
        return 0

    db.save_raw_snapshot(conn, "matchResults", "method=result", raw)

    results = parsers.parse_result_list(raw)
    if not results:
        print("  无已结束比赛")
        return 0

    updated = db.save_match_results(conn, results)
    print(f"  赛果更新: {updated} 场")
    return updated


# ── 赛程同步 ─────────────────────────────────────────────────────────────────

def sync_matches(conn) -> list[dict]:
    """拉取关注赛事列表，入库。返回比赛列表。"""
    raw, err = api_client.fetch_match_list()
    if err:
        print(f"  ✗ 赛程拉取失败: {err}")
        return []

    db.save_raw_snapshot(conn, "matchList", "method=concern", raw)

    matches = parsers.parse_match_list(raw)
    if matches:
        db.save_matches(conn, matches)
        print(f"  赛程: {len(matches)} 场在售")
    return matches


# ── 赔率同步 ─────────────────────────────────────────────────────────────────

def sync_odds(conn, matches: list[dict]) -> int:
    """逐场抓取 SP 赔率。返回总记录数。"""
    total = 0
    for i, m in enumerate(matches, 1):
        mid = m["match_id"]
        name = f"{m['home_team_name']} vs {m['away_team_name']}"
        print(f"  [{i}/{len(matches)}] {name}", end="")

        raw, err = api_client.fetch_fixed_bonus(mid)
        if err:
            print(f" ✗ {err}")
            continue

        db.save_raw_snapshot(conn, "fixedBonus", f"matchId={mid}", raw, mid)

        records = parsers.parse_fixed_bonus(raw, mid)
        if records:
            records = probability.calc_implied_prob(records)
            inserted = db.save_sp_snapshots(conn, records)
            total += inserted
            print(f" ({len(records)} 条)")
        else:
            print(" (无数据)")

        if i < len(matches):
            time.sleep(0.3)

    return total


# ── 单轮同步 ─────────────────────────────────────────────────────────────────

def run_sync(conn) -> None:
    """执行一轮完整同步：赛果 → 赛程 → 赔率。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'=' * 50}")
    print(f"同步 {now}")
    print(f"{'=' * 50}")

    t0 = time.time()

    # 1. 赛果回填
    sync_results(conn)

    # 2. 赛程同步
    matches = sync_matches(conn)

    # 3. 赔率同步
    if matches:
        total = sync_odds(conn, matches)
        print(f"\n  赔率写入: {total} 条")

    elapsed = time.time() - t0
    print(f"  耗时: {elapsed:.1f}s")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="竞彩足球定时同步")
    parser.add_argument("--interval", type=int, default=0,
                        help="循环间隔（秒），0=单次执行")
    args = parser.parse_args()

    try:
        conn = db.get_connection()
        print(f"已连接 SQLite: {db._SQLITE_PATH}")
    except Exception as e:
        print(f"数据库连接失败: {e}")
        sys.exit(1)

    try:
        db.ensure_tables(conn)

        if args.interval > 0:
            print(f"定时同步: 每 {args.interval} 秒 (Ctrl+C 停止)")
            print(f"静默时段: 01:00-09:00")
            while True:
                now = datetime.now()
                hour = now.hour

                if 1 <= hour < 9:
                    print(f"\n{now.strftime('%H:%M')} 静默时段，等待至 09:00...")
                    wait = (9 - hour - 1) * 3600 + (60 - now.minute) * 60
                    try:
                        time.sleep(min(wait, 3600))
                    except KeyboardInterrupt:
                        print("\n同步已停止")
                        break
                    continue

                run_sync(conn)

                print(f"\n等待 {args.interval} 秒...")
                try:
                    time.sleep(args.interval)
                except KeyboardInterrupt:
                    print("\n同步已停止")
                    break
        else:
            run_sync(conn)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
