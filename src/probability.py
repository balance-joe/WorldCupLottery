"""根据 SP 值计算隐含概率。"""

from __future__ import annotations

from collections import defaultdict


def calc_implied_prob(records: list[dict]) -> list[dict]:
    """
    计算每条 SP 记录的隐含概率。

    按 (match_id, play_type, snapshot_time) 分组，对每组执行：
        implied_prob_raw  = 1 / sp_value
        prob_sum          = sum(implied_prob_raw)
        implied_prob_norm = implied_prob_raw / prob_sum

    直接修改原列表并返回。
    """
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for r in records:
        key = (r["match_id"], r["play_type"], r.get("snapshot_time", ""))
        groups[key].append(r)

    for key, group in groups.items():
        raw_probs = []
        for r in group:
            if r["sp_value"] and r["sp_value"] > 0:
                raw = 1.0 / r["sp_value"]
            else:
                raw = 0.0
            r["implied_prob_raw"] = raw
            raw_probs.append(raw)

        prob_sum = sum(raw_probs)
        for r in group:
            r["prob_sum"] = prob_sum
            if prob_sum > 0:
                r["implied_prob_norm"] = r["implied_prob_raw"] / prob_sum
            else:
                r["implied_prob_norm"] = 0.0

    return records
