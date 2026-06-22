"""
全玩法逐场临场回测: HHAD / TTG / CRS, 每场 1 个信号。

Usage:
    python -m scripts.backtest_all_playtypes
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src import db
from src.sp_trend import analyze_play_trend


def code_to_score(code: str) -> str:
    if code.startswith("s") and len(code) == 6:
        h = code[1:3].lstrip("0") or "0"
        a = code[4:6].lstrip("0") or "0"
        return f"{h}:{a}"
    return code


def main():
    conn = db.get_connection()

    cur = conn.execute("""
        SELECT DISTINCT m.match_id, m.match_num, m.home_team_name, m.away_team_name,
               m.match_time, m.result_90, m.home_score_90, m.away_score_90
        FROM sporttery_match m
        JOIN sporttery_sp_snapshot s ON s.match_id = m.match_id
        WHERE m.result_90 IS NOT NULL
        ORDER BY m.match_id
    """)
    matches = [dict(zip([d[0] for d in cur.description], row)) for row in cur.fetchall()]
    match_ids = [m["match_id"] for m in matches]
    sp_history = db.fetch_all_sp_history(conn, match_ids)

    def get_all_upto_latest(match_id, play_type):
        """获取到最新快照为止的全部数据（趋势计算需要多个快照）。"""
        recs = [r for r in sp_history
                if str(r.get("match_id")) == match_id and r.get("play_type") == play_type]
        return recs

    def get_latest(match_id, play_type):
        """获取最新快照的记录（CRS 用）。"""
        recs = [r for r in sp_history
                if str(r.get("match_id")) == match_id and r.get("play_type") == play_type]
        if not recs:
            return []
        latest_time = max(str(r.get("snapshot_time", "")) for r in recs)
        return [r for r in recs if str(r.get("snapshot_time", "")) == latest_time]

    # ── HHAD ────────────────────────────────────────────────────────────
    print("=" * 80)
    print("HHAD 让球胜平负 (临场, 每场 1 个信号)")
    print("=" * 80)
    print(f"{'比赛':<22} {'比分':<6} {'让球':<5} {'实际':<5} {'信号':<28} {'conf':<7} {'SP':>6} {'命中':>4}")
    print("-" * 80)

    hhad_results = []
    for m in matches:
        mid = m["match_id"]
        home, away = m["home_score_90"], m["away_score_90"]
        if home is None or away is None:
            continue

        snapshot = get_all_upto_latest(mid, "hhad")
        if len(snapshot) < 3:
            continue

        hhad = analyze_play_trend(mid, "hhad", "open_to_latest", snapshot)
        if not hhad.available:
            continue

        d = hhad.main_direction
        goal_line = hhad.handicap_line
        if not goal_line:
            continue

        signal = None
        if "home" in d:
            signal = "H"
        elif "away" in d:
            signal = "A"
        elif "draw" in d:
            signal = "D"
        if signal is None:
            continue

        try:
            adjusted = int(home) + int(goal_line)
        except (ValueError, TypeError):
            continue
        if adjusted > int(away):
            actual = "H"
        elif adjusted < int(away):
            actual = "A"
        else:
            actual = "D"

        current_sp = None
        latest_t = max(str(r.get("snapshot_time", "")) for r in snapshot)
        # 从最新快照取 SP
        latest_snap = [r for r in snapshot if str(r.get("snapshot_time", "")) == latest_t]
        for r in latest_snap:
            if r.get("option_code") == signal:
                current_sp = r.get("sp_value")
                break

        hit = signal == actual
        mark = "HIT" if hit else "MISS"
        sp_str = f"{current_sp:.2f}" if current_sp else "?"
        name = f"{m['home_team_name']} vs {m['away_team_name']}"[:20]
        score = m.get("full_score_90", "?")

        print(f"{name:<22} {score:<6} {goal_line:<5} {actual:<5} {d:<28} {hhad.direction_confidence:<7} {sp_str:>6} {mark:>4}")
        hhad_results.append({"hit": hit, "sp": current_sp})

    h_total = len(hhad_results)
    if h_total:
        h_hits = sum(1 for r in hhad_results if r["hit"])
        print(f"\nHHAD 汇总: {h_hits}/{h_total} = {h_hits/h_total:.1%}")
        for label, lo, hi in [("<1.6", 0, 1.6), ("1.6-2.5", 1.6, 2.5), (">2.5", 2.5, 99)]:
            g = [r for r in hhad_results if r["sp"] and lo <= r["sp"] < hi]
            if g:
                h = sum(1 for r in g if r["hit"])
                stake = len(g) * 10
                payout = sum(r["sp"] * 10 for r in g if r["hit"])
                print(f"  SP {label:<8} {h}/{len(g)} = {h/len(g):.1%}  投入:{stake} 奖金:{payout:.2f} 盈亏:{payout-stake:+.2f}")

    # ── TTG ─────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("TTG 总进球 (临场, 每场 1 个信号)")
    print("=" * 80)
    print(f"{'比赛':<22} {'比分':<6} {'总球':<5} {'信号':<22} {'conf':<7} {'SP':>6} {'命中':>4}")
    print("-" * 80)

    ttg_results = []
    for m in matches:
        mid = m["match_id"]
        home, away = m["home_score_90"], m["away_score_90"]
        if home is None or away is None:
            continue
        total = int(home) + int(away)

        snapshot = get_all_upto_latest(mid, "ttg")
        if len(snapshot) < 3:
            continue

        ttg = analyze_play_trend(mid, "ttg", "open_to_latest", snapshot)
        if not ttg.available:
            continue

        d = ttg.main_direction
        signal = None
        if "low_goal" in d:
            signal = "low"
        elif "mid_goal" in d:
            signal = "mid"
        elif "high_goal" in d:
            signal = "high"
        if signal is None:
            continue

        hit = False
        if signal == "low" and total <= 2:
            hit = True
        elif signal == "mid" and 2 <= total <= 3:
            hit = True
        elif signal == "high" and total >= 4:
            hit = True

        group_map = {"low": ("0", "1", "2"), "mid": ("2", "3"), "high": ("4", "5", "6", "7")}
        codes = group_map[signal]
        latest_t = max(str(r.get("snapshot_time", "")) for r in snapshot)
        latest_snap = [r for r in snapshot if str(r.get("snapshot_time", "")) == latest_t]
        best_r = None
        for r in latest_snap:
            if r.get("option_code") in codes:
                if best_r is None or (r.get("implied_prob_norm") or 0) > (best_r.get("implied_prob_norm") or 0):
                    best_r = r
        current_sp = best_r["sp_value"] if best_r else None

        mark = "HIT" if hit else "MISS"
        sp_str = f"{current_sp:.2f}" if current_sp else "?"
        name = f"{m['home_team_name']} vs {m['away_team_name']}"[:20]
        score = m.get("full_score_90", "?")

        print(f"{name:<22} {score:<6} {total:<5} {d:<22} {ttg.direction_confidence:<7} {sp_str:>6} {mark:>4}")
        ttg_results.append({"hit": hit, "sp": current_sp, "signal": signal})

    t_total = len(ttg_results)
    if t_total:
        t_hits = sum(1 for r in ttg_results if r["hit"])
        print(f"\nTTG 汇总: {t_hits}/{t_total} = {t_hits/t_total:.1%}")
        for sig in ["low", "mid", "high"]:
            g = [r for r in ttg_results if r["signal"] == sig]
            if g:
                h = sum(1 for r in g if r["hit"])
                stake = len(g) * 10
                payout = sum(r["sp"] * 10 for r in g if r["hit"])
                print(f"  {sig:<6} {h}/{len(g)} = {h/len(g):.1%}  投入:{stake} 奖金:{payout:.2f} 盈亏:{payout-stake:+.2f}")

    # ── CRS Top-N ───────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("CRS 比分 Top-N (临场)")
    print("=" * 80)
    print(f"{'比赛':<22} {'实际':<6} {'Top1':<6} {'Top1 SP':>7} {'Top3':<15} {'命中':>4}")
    print("-" * 70)

    crs_top1_hit = 0
    crs_top3_hit = 0
    crs_total = 0
    crs_sp_sum = 0

    for m in matches:
        mid = m["match_id"]
        home, away = m["home_score_90"], m["away_score_90"]
        if home is None or away is None:
            continue
        actual_score = f"{home}:{away}"

        snapshot = get_latest(mid, "crs")
        if not snapshot:
            continue

        crs_total += 1
        scored = sorted(snapshot, key=lambda r: -(r.get("implied_prob_norm") or 0))
        top1_code = scored[0]["option_code"] if scored else ""
        top1_sp = scored[0]["sp_value"] if scored else 0
        top3_codes = [r["option_code"] for r in scored[:3]]

        top1_score = code_to_score(top1_code)
        top3_scores = [code_to_score(c) for c in top3_codes]

        hit1 = top1_score == actual_score
        hit3 = actual_score in top3_scores

        if hit1:
            crs_top1_hit += 1
            crs_sp_sum += top1_sp
        if hit3:
            crs_top3_hit += 1

        mark = "HIT" if hit1 else "TOP3" if hit3 else "MISS"
        name = f"{m['home_team_name']} vs {m['away_team_name']}"[:20]
        print(f"{name:<22} {actual_score:<6} {top1_score:<6} {top1_sp:>7.2f} {' '.join(top3_scores):<15} {mark:>4}")

    if crs_total:
        print(f"\nCRS Top1: {crs_top1_hit}/{crs_total} = {crs_top1_hit/crs_total:.1%}")
        print(f"CRS Top3: {crs_top3_hit}/{crs_total} = {crs_top3_hit/crs_total:.1%}")
        if crs_top1_hit:
            print(f"CRS Top1 命中时平均 SP: {crs_sp_sum/crs_top1_hit:.2f}")

    conn.close()


if __name__ == "__main__":
    main()
