"""
预测 vs SP 对比分析 + 预测准确率回测 + 价值场次发现。

Usage:
    python -m scripts.analyze_predictions
    python -m scripts.analyze_predictions --detail
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src import db


def clean_team_name(name: str) -> str:
    """Strip emoji flags and special Unicode, keep Chinese name."""
    # Chain regex ops — combining ranges in one character class causes issues
    name = re.sub(r'[\U0001F1E0-\U0001F1FF]', '', name)  # Regional indicators
    name = re.sub(r'[\U0000FE00-\U0000FE0F]', '', name)   # Variation selectors
    name = re.sub(r'\U0000200D', '', name)                  # ZWJ
    return name.strip()


def _fetch_dicts(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def load_predictions(conn) -> list[dict]:
    cur = conn.execute('''
        SELECT pred_match_id, home_team, away_team, match_date, actual_score,
               home_prob, draw_prob, away_prob,
               elo_home_prob, elo_draw_prob, elo_away_prob,
               dc_home_prob, dc_draw_prob, dc_away_prob,
               over_25_prob, expected_goals_home, expected_goals_away,
               top_scores_json
        FROM pred_match ORDER BY match_date, pred_match_id
    ''')
    return _fetch_dicts(cur)


def load_sporttery_matches(conn) -> list[dict]:
    cur = conn.execute('''
        SELECT match_id, home_team_name, away_team_name, match_time,
               result_90, home_score_90, away_score_90, full_score_90, half_score
        FROM sporttery_match
        ORDER BY match_time
    ''')
    return _fetch_dicts(cur)


def _date_range(date_str: str, delta_days: int = 1) -> list[str]:
    """Return date_str +/- delta_days."""
    from datetime import datetime, timedelta
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return [date_str] if date_str else []
    return [(dt + timedelta(days=d)).strftime("%Y-%m-%d") for d in range(-delta_days, delta_days + 1)]


def join_datasets(preds: list[dict], sporttery: list[dict]) -> list[dict]:
    """Join predictions with sporttery data by team name + date (±1 day)."""
    from collections import defaultdict

    # Build sporttery index: (clean_home, clean_away) -> [matches]
    st_by_teams = defaultdict(list)
    for m in sporttery:
        if not m.get("match_time"):
            continue
        date = str(m["match_time"])[:10]
        h = clean_team_name(m["home_team_name"])
        a = clean_team_name(m["away_team_name"])
        st_by_teams[(h, a)].append(m)

    joined = []
    for p in preds:
        h = clean_team_name(p["home_team"])
        a = clean_team_name(p["away_team"])
        pred_date = p.get("match_date", "")

        m = None

        # Exact team match
        candidates = st_by_teams.get((h, a), [])
        if not candidates:
            # Try reversed (some sites list away first)
            candidates = st_by_teams.get((a, h), [])

        if candidates:
            # Prefer same date, then ±1 day
            date_candidates = _date_range(pred_date)
            for dc in date_candidates:
                for c in candidates:
                    if str(c["match_time"])[:10] == dc:
                        m = c
                        break
                if m:
                    break
            # Fallback: just take the first candidate
            if not m and candidates:
                m = candidates[0]

        joined.append({
            "pred": p,
            "sporttery": m,
            "matched": m is not None,
            "pred_home": h,
            "pred_away": a,
            "date": pred_date,
        })

    return joined


def calc_sp_implied_prob(conn, match_id: str) -> dict | None:
    """从 SP 快照计算最新隐含概率。"""
    rows = conn.execute('''
        SELECT option_code, sp_value, implied_prob_norm
        FROM sporttery_sp_snapshot
        WHERE match_id = ? AND play_type = 'had'
        ORDER BY snapshot_time DESC
        LIMIT 3
    ''', (match_id,)).fetchall()

    if len(rows) < 3:
        return None

    probs = {}
    for r in rows:
        probs[r[0]] = r[2]  # implied_prob_norm

    return {
        "sp_home_prob": probs.get("H", 0),
        "sp_draw_prob": probs.get("D", 0),
        "sp_away_prob": probs.get("A", 0),
    }


def analyze(conn, *, detail: bool = False) -> dict:
    """Run full analysis."""
    preds = load_predictions(conn)
    sporttery = load_sporttery_matches(conn)
    joined = join_datasets(preds, sporttery)

    # ── 1. 匹配统计 ──────────────────────────────────────────────────────
    matched = [j for j in joined if j["matched"]]
    unmatched_pred = [j for j in joined if not j["matched"]]

    if detail:
        print(f"\n{'=' * 60}")
        print(f"数据匹配: {len(matched)}/{len(preds)} 场预测匹配到体彩数据")
        print(f"{'=' * 60}")

    # Deduplicate: one pred_match_id -> one sporttery match
    seen_pred_ids = set()
    deduped_matched = []
    for j in matched:
        pid = j["pred"]["pred_match_id"]
        if pid not in seen_pred_ids:
            seen_pred_ids.add(pid)
            deduped_matched.append(j)

    # ── 2. 预测 vs 实际准确率 ─────────────────────────────────────────────
    pred_results = []
    for j in deduped_matched:
        p = j["pred"]
        m = j["sporttery"]
        if not m.get("result_90"):
            continue

        # 预测方向 (home_prob is already 0-1 in DB)
        hp = p["home_prob"] if p["home_prob"] and p["home_prob"] <= 1 else p["home_prob"] / 100
        dp = p["draw_prob"] if p["draw_prob"] and p["draw_prob"] <= 1 else p["draw_prob"] / 100
        ap = p["away_prob"] if p["away_prob"] and p["away_prob"] <= 1 else p["away_prob"] / 100
        pred_dir = "H" if hp > dp and hp > ap else "A" if ap > dp else "D"
        pred_confidence = max(hp, dp, ap)

        actual = m["result_90"]
        hit = pred_dir == actual

        # SP 隐含概率
        sp_probs = calc_sp_implied_prob(conn, m["match_id"])

        pred_results.append({
            "match_id": m["match_id"],
            "home": j["pred_home"],
            "away": j["pred_away"],
            "score": m.get("full_score_90"),
            "pred_dir": pred_dir,
            "pred_prob": pred_confidence,
            "actual": actual,
            "hit": hit,
            "hp": hp, "dp": dp, "ap": ap,
            "sp": sp_probs,
            "elo_hp": p.get("elo_home_prob", 0) / 100 if p.get("elo_home_prob") else None,
            "elo_dp": p.get("elo_draw_prob", 0) / 100 if p.get("elo_draw_prob") else None,
            "elo_ap": p.get("elo_away_prob", 0) / 100 if p.get("elo_away_prob") else None,
            "dc_hp": p.get("dc_home_prob", 0) / 100 if p.get("dc_home_prob") else None,
            "dc_dp": p.get("dc_draw_prob", 0) / 100 if p.get("dc_draw_prob") else None,
            "dc_ap": p.get("dc_away_prob", 0) / 100 if p.get("dc_away_prob") else None,
            "over25": (p.get("over_25_prob") if p.get("over_25_prob") and p["over_25_prob"] <= 1 else (p.get("over_25_prob") or 0) / 100),
        })

    # ── 3. 预测准确率统计 ─────────────────────────────────────────────────
    total_pred = len(pred_results)
    hits = sum(1 for r in pred_results if r["hit"])

    if detail and pred_results:
        print(f"\n{'=' * 60}")
        print(f"预测准确率 ({total_pred} 场已赛)")
        print(f"{'=' * 60}")
        for r in pred_results:
            mark = "HIT" if r["hit"] else "MISS"
            sp_str = ""
            if r["sp"]:
                sp_str = f"  SP:H{r['sp']['sp_home_prob']:.0%} D{r['sp']['sp_draw_prob']:.0%} A{r['sp']['sp_away_prob']:.0%}"
            print(
                f"  {mark} {r['home']} vs {r['away']} {r['score']}  "
                f"pred={r['pred_dir']}({r['pred_prob']:.0%}) actual={r['actual']}{sp_str}"
            )

    # ── 4. 预测 vs SP 偏差分析 ────────────────────────────────────────────
    value_matches = []
    for j in deduped_matched:
        p = j["pred"]
        m = j["sporttery"]
        if not m:
            continue

        sp_probs = calc_sp_implied_prob(conn, m["match_id"])
        if not sp_probs:
            continue

        hp = p["home_prob"] if p["home_prob"] and p["home_prob"] <= 1 else p["home_prob"] / 100
        dp = p["draw_prob"] if p["draw_prob"] and p["draw_prob"] <= 1 else p["draw_prob"] / 100
        ap = p["away_prob"] if p["away_prob"] and p["away_prob"] <= 1 else p["away_prob"] / 100

        # 预测 - SP 隐含
        delta_h = hp - sp_probs["sp_home_prob"]
        delta_d = dp - sp_probs["sp_draw_prob"]
        delta_a = ap - sp_probs["sp_away_prob"]

        max_delta = max(abs(delta_h), abs(delta_d), abs(delta_a))
        if max_delta < 0.08:
            continue  # 偏差太小，不关注

        if abs(delta_h) == max_delta:
            direction = "H"
            delta = delta_h
        elif abs(delta_a) == max_delta:
            direction = "A"
            delta = delta_a
        else:
            direction = "D"
            delta = delta_d

        value_matches.append({
            "home": j["pred_home"],
            "away": j["pred_away"],
            "date": j["date"],
            "direction": direction,
            "pred_prob": hp if direction == "H" else dp if direction == "D" else ap,
            "sp_prob": sp_probs["sp_home_prob"] if direction == "H" else sp_probs["sp_draw_prob"] if direction == "D" else sp_probs["sp_away_prob"],
            "delta": delta,
            "actual": m.get("result_90"),
            "score": m.get("full_score_90"),
            "match_id": m.get("match_id"),
        })

    value_matches.sort(key=lambda x: -abs(x["delta"]))

    # ── 5. 汇总输出 ──────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"分析汇总")
    print(f"{'=' * 60}")
    print(f"预测比赛总数: {len(preds)}")
    print(f"匹配到体彩数据: {len(matched)}")
    print(f"已赛且可回测: {total_pred}")
    if total_pred > 0:
        print(f"预测方向命中: {hits}/{total_pred} = {hits/total_pred:.1%}")

    # 偏差大的场次
    if value_matches:
        print(f"\n{'─' * 60}")
        print(f"预测 vs SP 偏差 Top10 (预测说的 vs SP 说的)")
        print(f"{'─' * 60}")
        for v in value_matches[:10]:
            arrow = "pred>SP" if v["delta"] > 0 else "pred<SP"
            actual_mark = ""
            if v["actual"]:
                actual_mark = " HIT" if v["actual"] == v["direction"] else " MISS"
            print(
                f"  {v['home']} vs {v['away']}  {v['date']}  "
                f"{v['direction']} pred={v['pred_prob']:.0%} sp={v['sp_prob']:.0%} "
                f"delta={v['delta']:+.1%} {arrow}{actual_mark}"
            )

    # 如果按偏差买，模拟盈亏
    if value_matches and detail:
        print(f"\n{'─' * 60}")
        print(f"模拟: 只买偏差 >= 10% 的场次 (HAD 单关 10元)")
        print(f"{'─' * 60}")
        sim_stake = 0
        sim_payout = 0
        sim_count = 0
        sim_hits = 0
        for v in value_matches:
            if abs(v["delta"]) < 0.10:
                continue
            if not v["actual"]:
                continue
            sim_count += 1
            sim_stake += 10
            if v["actual"] == v["direction"]:
                # 用 SP 隐含概率的倒数作为模拟 SP
                sp_val = 1 / v["sp_prob"] if v["sp_prob"] > 0 else 3.0
                sim_payout += sp_val * 10
                sim_hits += 1
                print(f"  HIT {v['home']} vs {v['away']} bet={v['direction']} sp~{sp_val:.2f}")
            else:
                print(f"  MISS {v['home']} vs {v['away']} bet={v['direction']} actual={v['actual']}")

        if sim_count > 0:
            print(f"\n  触发: {sim_count} 命中: {sim_hits} 投入: {sim_stake} 奖金: {sim_payout:.2f} 盈亏: {sim_payout-sim_stake:+.2f}")

    # 三个模型对比
    if pred_results:
        print(f"\n{'─' * 60}")
        print(f"三模型准确率对比")
        print(f"{'─' * 60}")
        for model_name, key_h, key_d, key_a in [
            ("融合模型", "hp", "dp", "ap"),
            ("加权Elo", "elo_hp", "elo_dp", "elo_ap"),
            ("Dixon-Coles", "dc_hp", "dc_dp", "dc_ap"),
        ]:
            valid = [r for r in pred_results if r.get(key_h) is not None]
            if not valid:
                continue
            m_hits = 0
            for r in valid:
                probs = {r[key_h]: "H", r[key_d]: "D", r[key_a]: "A"}
                best = max(r[key_h], r[key_d], r[key_a])
                pred = probs[best]
                if pred == r["actual"]:
                    m_hits += 1
            print(f"  {model_name}: {m_hits}/{len(valid)} = {m_hits/len(valid):.1%}")

    return {
        "pred_results": pred_results,
        "value_matches": value_matches,
        "total_pred": total_pred,
        "hits": hits,
    }


def main():
    parser = argparse.ArgumentParser(description="预测 vs SP 对比分析")
    parser.add_argument("--detail", action="store_true", help="逐场详情")
    args = parser.parse_args()

    conn = db.get_connection()
    try:
        analyze(conn, detail=args.detail)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
