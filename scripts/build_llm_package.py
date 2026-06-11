"""
Build LLM analysis package for a match.

Usage:
    python -m scripts.build_llm_package --match-id 2040162
    python -m scripts.build_llm_package --match-id 2040162 --with-detail
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main():
    parser = argparse.ArgumentParser(description="Build LLM analysis package")
    parser.add_argument("--match-id", required=True, help="比赛 match_id")
    parser.add_argument("--with-detail", action="store_true",
                        help="包含对阵详情（需先手动获取 detail JSON）")
    parser.add_argument("--detail-path", type=str,
                        help="对阵详情 JSON 路径（默认 data/match_{id}_detail.json）")
    parser.add_argument("--output", type=str, help="输出路径（默认 data/packages/{id}.json）")
    args = parser.parse_args()

    from src import db
    from src.llm_package import build_llm_package

    conn = db.get_connection()

    try:
        # ── Match info ───────────────────────────────────────────────────
        cur = conn.execute(
            "SELECT * FROM sporttery_match WHERE match_id = ?",
            (args.match_id,),
        )
        row = cur.fetchone()
        if not row:
            print(f"错误: match_id={args.match_id} 不存在")
            sys.exit(1)

        cols = [d[0] for d in cur.description]
        match_info = dict(zip(cols, row))

        # ── SP history ───────────────────────────────────────────────────
        cur = conn.execute(
            "SELECT * FROM sporttery_sp_snapshot WHERE match_id = ? ORDER BY snapshot_time",
            (args.match_id,),
        )
        sp_cols = [d[0] for d in cur.description]
        sp_history = [dict(zip(sp_cols, r)) for r in cur.fetchall()]

        if not sp_history:
            print(f"警告: match_id={args.match_id} 无 SP 数据")

        # ── Detail (optional) ────────────────────────────────────────────
        detail = None
        if args.with_detail:
            detail_path = args.detail_path or str(_ROOT / "data" / f"match_{args.match_id}_detail.json")
            p = Path(detail_path)
            if p.exists():
                with open(p, encoding="utf-8") as f:
                    detail = json.load(f)
                print(f"已加载对阵详情: {p}")
            else:
                print(f"警告: 详情文件不存在 {p}，跳过")

        # ── Build package ────────────────────────────────────────────────
        package = build_llm_package(match_info, sp_history, detail)

        # ── Output ───────────────────────────────────────────────────────
        out_path = args.output or str(_ROOT / "data" / "packages" / f"{args.match_id}.json")
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(package, f, ensure_ascii=False, indent=2)

        print(f"已生成: {out_path}")

        # ── Summary ──────────────────────────────────────────────────────
        match = package["match"]
        tc = package["time_context"]
        sc = package["status_control"]
        sigs = package["signals"]

        print(f"\n{'=' * 50}")
        print(f"{match['home']} vs {match['away']}  ({match['league']})")
        print(f"开赛: {match['match_time']}  距开赛: {tc['hours_to_kickoff']}h  阶段: {tc['phase']}")
        print(f"状态: {sc['match_status_name']}  可投注: {sc['tradable']}")
        print(f"信号: 正面{len(sigs['positive_signals'])} 负面{len(sigs['negative_signals'])} "
              f"结构{len(sigs['structure_signals'])} 不确定{len(sigs['uncertainty_flags'])}")
        print(f"{'=' * 50}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
