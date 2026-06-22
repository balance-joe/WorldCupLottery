"""
回测 SP 信号 vs 实际赛果，覆盖全部 5 种玩法。

用法:
    python -m scripts.backtest_sp_signals          # 汇总
    python -m scripts.backtest_sp_signals --detail  # 逐场详情
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src import db
from src.sp_trend import analyze_play_trend


# ── 信号提取 ────────────────────────────────────────────────────────────────

def _had_signal(sp_history: list[dict], match_id: str) -> str | None:
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


def _hhad_signal(sp_history: list[dict], match_id: str) -> tuple[str | None, str | None]:
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


def _hhad_actual(home: int, away: int, goal_line: str | None) -> str | None:
    """计算让球后的实际结果。"""
    if goal_line is None:
        return None
    try:
        adjusted = home + float(goal_line)
    except (ValueError, TypeError):
        return None
    if adjusted > away:
        return "H"
    if adjusted < away:
        return "A"
    return "D"


def _ttg_signal(sp_history: list[dict], match_id: str) -> str | None:
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


def _ttg_actual(total_goals: int) -> str:
    """实际总进球 → low/mid/high。"""
    if total_goals <= 2:
        return "low"
    if total_goals <= 3:
        return "mid"
    return "high"


def _crs_top_scores(sp_history: list[dict], match_id: str, n: int = 5) -> list[str]:
    """CRS 最新快照中概率最高的 n 个比分。返回比分字符串如 ['1:0', '0:0']。"""
    records = [r for r in sp_history
               if str(r.get("match_id")) == match_id and r.get("play_type") == "crs"]
    if not records:
        return []

    latest_time = max(str(r.get("snapshot_time", "")) for r in records)
    latest = [r for r in records if str(r.get("snapshot_time", "")) == latest_time]
    if not latest:
        return []

    scored = []
    for r in latest:
        prob = r.get("implied_prob_norm") or 0
        code = r["option_code"]
        # 转换 code → 比分字符串
        score = _crs_code_to_score(code)
        if score:
            scored.append((score, prob))
    scored.sort(key=lambda x: -x[1])
    return [s for s, _ in scored[:n]]


def _crs_code_to_score(code: str) -> str | None:
    """crs option_code → 比分字符串。如 's01s02' → '1:2'。"""
    if code in ("s-1sh", "s-1sd", "s-1sa"):
        return None  # "其他"类，跳过
    if code.startswith("s") and len(code) == 6:
        home = code[1:3].lstrip("0") or "0"
        away = code[4:6].lstrip("0") or "0"
        return f"{home}:{away}"
    return None


def _hafu_top_option(sp_history: list[dict], match_id: str) -> str | None:
    """HAFU 最新快照中概率最高的选项。返回如 'hh'。"""
    records = [r for r in sp_history
               if str(r.get("match_id")) == match_id and r.get("play_type") == "hafu"]
    if not records:
        return None

    latest_time = max(str(r.get("snapshot_time", "")) for r in records)
    latest = [r for r in records if str(r.get("snapshot_time", "")) == latest_time]
    if not latest:
        return None

    best = max(latest, key=lambda r: r.get("implied_prob_norm") or 0)
    return best["option_code"]


def _hafu_actual(half_score: str | None, home: int, away: int) -> str | None:
    """计算半全场实际结果。如 half='1:0', full='2:1' → 'hH' → 'hh'。"""
    if not half_score or ":" not in half_score:
        return None
    try:
        h_parts = half_score.split(":")
        half_h, half_a = int(h_parts[0]), int(h_parts[1])
    except (ValueError, IndexError):
        return None

    half_result = "h" if half_h > half_a else "d" if half_h == half_a else "a"
    full_result = "h" if home > away else "d" if home == away else "a"
    return half_result + full_result


# ── 回测主逻辑 ──────────────────────────────────────────────────────────────

def backtest(conn, *, detail: bool = False) -> dict:
    """对所有有赛果+SP历史的比赛做全玩法信号回测。"""
    cur = conn.execute("""
        SELECT DISTINCT m.match_id, m.home_team_name, m.away_team_name,
               m.result_90, m.home_score_90, m.away_score_90, m.half_score
        FROM sporttery_match m
        JOIN sporttery_sp_snapshot s ON s.match_id = m.match_id
        WHERE m.result_90 IS NOT NULL
        ORDER BY m.match_id
    """)
    matches = [dict(zip([d[0] for d in cur.description], row)) for row in cur.fetchall()]

    if not matches:
        print("没有可回测的比赛")
        return {}

    match_ids = [m["match_id"] for m in matches]
    sp_history = db.fetch_all_sp_history(conn, match_ids)

    # ── 逐场回测 ────────────────────────────────────────────────────────
    results = []
    for m in matches:
        mid = m["match_id"]
        actual = m["result_90"]
        home = m["home_score_90"]
        away = m["away_score_90"]
        total = (home or 0) + (away or 0)
        actual_score = f"{home}:{away}"

        had_sig = _had_signal(sp_history, mid)
        hhad_sig, hhad_line = _hhad_signal(sp_history, mid)
        hhad_actual = _hhad_actual(home or 0, away or 0, hhad_line)
        ttg_sig = _ttg_signal(sp_history, mid)
        ttg_act = _ttg_actual(total)
        crs_top = _crs_top_scores(sp_history, mid)
        hafu_sig = _hafu_top_option(sp_history, mid)
        hafu_act = _hafu_actual(m.get("half_score"), home or 0, away or 0)

        entry = {
            "match_id": mid,
            "home": m["home_team_name"],
            "away": m["away_team_name"],
            "actual": actual,
            "score": actual_score,
            "half_score": m.get("half_score"),
            "total_goals": total,
            # HAD
            "had_sig": had_sig,
            "had_hit": had_sig == actual if had_sig else None,
            # HHAD
            "hhad_sig": hhad_sig,
            "hhad_line": hhad_line,
            "hhad_actual": hhad_actual,
            "hhad_hit": hhad_sig == hhad_actual if hhad_sig and hhad_actual else None,
            # TTG
            "ttg_sig": ttg_sig,
            "ttg_actual": ttg_act,
            "ttg_hit": ttg_sig == ttg_act if ttg_sig else None,
            # CRS
            "crs_top5": crs_top,
            "crs_hit": actual_score in crs_top if crs_top else None,
            # HAFU
            "hafu_sig": hafu_sig,
            "hafu_actual": hafu_act,
            "hafu_hit": hafu_sig == hafu_act if hafu_sig and hafu_act else None,
        }
        results.append(entry)

    # ── 统计 ────────────────────────────────────────────────────────────
    stats = _compute_stats(results)

    # ── 输出 ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"回测结果: {len(results)} 场比赛")
    print(f"{'=' * 60}")

    _SMALL_SAMPLE_THRESHOLD = 20

    for label, key in [
        ("HAD 胜平负", "had"),
        ("HHAD 让球胜平负", "hhad"),
        ("TTG 总进球", "ttg"),
        ("CRS 比分 Top5", "crs"),
        ("HAFU 半全场", "hafu"),
    ]:
        s = stats.get(key, {})
        total = s.get("total", 0)
        hits = s.get("hits", 0)
        if total:
            rate = hits / total
            warn = " ⚠ 样本量不足，命中率仅供参考" if total < _SMALL_SAMPLE_THRESHOLD else ""
            print(f"  {label}: {hits}/{total} = {rate:.1%}{warn}")

    if detail:
        print(f"\n{'─' * 80}")
        print("逐场详情:")
        print(f"{'─' * 80}")
        for r in results:
            _print_detail(r)

    return {"matches": results, "stats": stats}


def _compute_stats(results: list[dict]) -> dict:
    stats = {}
    for key in ("had", "hhad", "ttg", "crs", "hafu"):
        hit_key = f"{key}_hit"
        hits = [r for r in results if r.get(hit_key) is True]
        misses = [r for r in results if r.get(hit_key) is False]
        total = len(hits) + len(misses)
        stats[key] = {"total": total, "hits": len(hits), "misses": len(misses)}
    return stats


def _print_detail(r: dict) -> None:
    def _mark(val):
        if val is True:
            return "+"
        if val is False:
            return "-"
        return "."

    parts = [
        f"{r['home']} vs {r['away']}",
        f"{r['score']}({r['actual']})",
        f"HAD:{r['had_sig'] or '-'}{_mark(r['had_hit'])}",
        f"HHAD:{r['hhad_sig'] or '-'}({r['hhad_line'] or '?'}){_mark(r['hhad_hit'])}",
        f"TTG:{r['ttg_sig'] or '-'}{_mark(r['ttg_hit'])}",
        f"CRS:{','.join(r['crs_top5'][:3]) or '-'}{_mark(r['crs_hit'])}",
        f"HAFU:{r['hafu_sig'] or '-'}{_mark(r['hafu_hit'])}",
    ]
    print(f"  {' | '.join(parts)}")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SP 信号回测")
    parser.add_argument("--detail", action="store_true", help="逐场详情")
    args = parser.parse_args()

    conn = db.get_connection()
    try:
        backtest(conn, detail=args.detail)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
