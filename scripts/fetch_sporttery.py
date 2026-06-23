"""
Sporttery data fetcher CLI.

Usage:
    python -m scripts.fetch_sporttery --mode today
    python -m scripts.fetch_sporttery --mode match --match-id 2040162
    python -m scripts.fetch_sporttery --mode all
    python -m scripts.fetch_sporttery --mode today --interval-seconds 300 --repeat 12
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

api_client = None
parsers = None
probability = None
db = None


# ── Stats collector ──────────────────────────────────────────────────────────

class Stats:
    def __init__(self):
        self.matches_found = 0
        self.matches_saved = 0
        self.sp_records = 0
        self.snapshots_inserted = 0
        self.sp_deduped = 0
        self.api_calls = 0
        self.api_failures: list[str] = []
        self.api_errors_logged = 0
        self.missing_fields: list[str] = []
        self.schema_warnings: list[str] = []
        self.start_time = time.time()

    def report(self):
        elapsed = time.time() - self.start_time
        print("\n" + "=" * 60)
        print("抓取统计")
        print("=" * 60)
        print(f"  比赛发现:     {self.matches_found}")
        print(f"  比赛入库:     {self.matches_saved}")
        print(f"  SP 记录数:    {self.sp_records}")
        print(f"  快照写入:     {self.snapshots_inserted}")
        print(f"  快照去重:     {self.sp_deduped}")
        print(f"  API 调用:     {self.api_calls}")
        print(f"  API 失败:     {len(self.api_failures)}")
        print(f"  异常落库:     {self.api_errors_logged}")
        print(f"  耗时:         {elapsed:.1f}s")
        if self.api_failures:
            print("\n失败列表:")
            for f in self.api_failures:
                print(f"  ✗ {f}")
        if self.schema_warnings:
            print("\nSchema 告警:")
            for w in self.schema_warnings:
                print(f"  ⚠ {w}")
        if self.missing_fields:
            print("\n缺失字段:")
            for f in self.missing_fields:
                print(f"  ⚠ {f}")
        print("=" * 60)


# ── Save helper ──────────────────────────────────────────────────────────────

def _save_raw(conn, source: str, url: str, raw: dict, match_id: str | None = None, params: dict | None = None) -> bool:
    """Save raw snapshot and return True if new row inserted."""
    try:
        return db.save_raw_snapshot(conn, source, url, raw, match_id, params)
    except Exception as e:
        print(f"  ⚠ raw snapshot save failed: {e}")
        return False


def _log_api_error(conn, endpoint: str, error: str, stats: Stats,
                   match_id: str | None = None, params: dict | None = None) -> None:
    """Persist an API error to the database and count it."""
    try:
        db.save_api_error(conn, endpoint, error, match_id=match_id, request_params=params)
        stats.api_errors_logged += 1
    except Exception as e:
        print(f"  ⚠ error logging failed: {e}")


# ── Mode: match (single match) ───────────────────────────────────────────────

def run_match(match_id: str, conn, stats: Stats) -> list[dict]:
    """Fetch SP for a single match. Returns SP records."""
    print(f"\n抓取 SP: match_id={match_id}")
    stats.api_calls += 1

    raw, err = api_client.fetch_fixed_bonus(match_id)
    if err:
        stats.api_failures.append(f"fixedBonus({match_id}): {err}")
        _log_api_error(conn, "fixedBonus", err, stats, match_id=match_id)
        print(f"  ✗ 失败: {err}")
        return []

    _save_raw(conn, "fixedBonus", f"matchId={match_id}", raw, match_id)

    # Schema validation
    warnings = parsers.validate_fixed_bonus_schema(raw, match_id)
    for w in warnings:
        stats.schema_warnings.append(w)
        print(f"  ⚠ {w}")

    records = parsers.parse_fixed_bonus(raw, match_id)
    if not records:
        stats.missing_fields.append(f"match_id={match_id}: hadList/hhadList/ttgList 全部为空")
        print(f"  ⚠ 无 SP 数据")
        return []

    records = probability.calc_implied_prob(records)

    # Check for missing fields
    for r in records:
        if r["sp_value"] is None:
            stats.missing_fields.append(f"match_id={match_id} play={r['play_type']} option={r['option_code']}: sp_value is None")

    inserted = db.save_sp_snapshots(conn, records)
    deduped = len(records) - inserted
    stats.sp_records += len(records)
    stats.snapshots_inserted += inserted
    stats.sp_deduped += deduped

    # Group for display
    by_play = {}
    for r in records:
        by_play.setdefault(r["play_type"], []).append(r)

    for play_type, group in by_play.items():
        goal_line = group[0].get("goal_line", "")
        gl_str = f" ({goal_line})" if goal_line and play_type == "hhad" else ""
        parts = []
        for r in group:
            p = f"{r['option_name']}={r['sp_value']}"
            if r.get("implied_prob_norm"):
                p += f"({r['implied_prob_norm']:.1%})"
            parts.append(p)
        print(f"  {play_type}{gl_str}: {' | '.join(parts)}")

    return records


# ── Mode: today (match list + all SP) ────────────────────────────────────────

def run_today(conn, stats: Stats) -> None:
    """Fetch match list and all SP data."""
    print("抓取关注赛事列表...")
    stats.api_calls += 1

    raw, err = api_client.fetch_match_list()
    if err:
        stats.api_failures.append(f"matchList: {err}")
        _log_api_error(conn, "matchList", err, stats)
        print(f"✗ 失败: {err}")
        return

    _save_raw(conn, "matchList", "method=concern", raw)

    # Schema validation
    warnings = parsers.validate_match_list_schema(raw)
    for w in warnings:
        stats.schema_warnings.append(w)
        print(f"⚠ {w}")

    matches = parsers.parse_match_list(raw)
    stats.matches_found = len(matches)
    print(f"发现 {len(matches)} 场比赛")

    if not matches:
        stats.missing_fields.append("matchList: subMatchList 为空")
        return

    # Save matches
    saved = db.save_matches(conn, matches)
    stats.matches_saved = saved
    print(f"入库 {saved} 场比赛\n")

    # Fetch SP for each match
    all_records = []
    for i, m in enumerate(matches, 1):
        mid = m["match_id"]
        name = f"{m['home_team_name']} vs {m['away_team_name']}"
        print(f"[{i}/{len(matches)}] {name} ({m['league_name']})")

        records = run_match(mid, conn, stats)
        all_records.extend(records)

        # Rate limit: 0.3s between requests
        if i < len(matches):
            time.sleep(0.3)

    # Summary by play type
    if all_records:
        by_play = {}
        for r in all_records:
            by_play.setdefault(r["play_type"], []).append(r)
        print(f"\nSP 汇总:")
        for pt, recs in by_play.items():
            print(f"  {pt}: {len(recs)} 条")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    global api_client, parsers, probability, db

    parser = argparse.ArgumentParser(description="Sporttery data fetcher")
    parser.add_argument("--mode", choices=["today", "match", "all"], default="today",
                        help="today=抓关注列表+SP, match=单场SP, all=同today")
    parser.add_argument("--match-id", type=str, help="单场模式的 matchId")
    parser.add_argument("--interval-seconds", type=int, default=0,
                        help="定时抓取间隔秒数；0 表示只抓一次")
    parser.add_argument("--repeat", type=int, default=1,
                        help="抓取轮数；0 表示一直循环，需配合 --interval-seconds")
    args = parser.parse_args()

    if args.mode == "match" and not args.match_id:
        print("错误: --mode match 需要 --match-id 参数")
        sys.exit(1)
    if args.interval_seconds < 0:
        print("错误: --interval-seconds 不能为负数")
        sys.exit(1)
    if args.repeat < 0:
        print("错误: --repeat 不能为负数")
        sys.exit(1)
    if args.repeat == 0 and args.interval_seconds <= 0:
        print("错误: --repeat 0 需要设置 --interval-seconds")
        sys.exit(1)

    from src import api_client as _api_client
    from src import db as _db
    from src import parsers as _parsers
    from src import probability as _probability

    api_client = _api_client
    parsers = _parsers
    probability = _probability
    db = _db

    # Connect to DB
    try:
        conn = db.get_connection()
        print(f"已连接数据库: {conn.backend}")
    except Exception as e:
        print(f"数据库连接失败: {e}")
        sys.exit(1)

    try:
        db.ensure_tables(conn)
        cycle = 0
        while args.repeat == 0 or cycle < args.repeat:
            cycle += 1
            if args.repeat != 1 or args.interval_seconds:
                repeat_text = "∞" if args.repeat == 0 else str(args.repeat)
                print(f"\n轮询抓取 {cycle}/{repeat_text}  {datetime.now():%Y-%m-%d %H:%M:%S}")

            stats = Stats()
            if args.mode == "match":
                run_match(args.match_id, conn, stats)
            else:
                run_today(conn, stats)
            stats.report()

            if args.repeat != 0 and cycle >= args.repeat:
                break
            if args.interval_seconds <= 0:
                break
            print(f"等待 {args.interval_seconds}s 后继续抓取...")
            time.sleep(args.interval_seconds)
    except KeyboardInterrupt:
        print("\n已停止定时抓取")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
