"""SP 变动计算模块。

SP 视为中国体彩竞彩固定奖金值，非海外赔率。
"""

from __future__ import annotations


def latest_records(records: list[dict]) -> list[dict]:
    """返回每个 match/play/option 组合的最新一条记录。"""
    latest: dict[tuple[str, str, str], dict] = {}
    for record in records:
        key = (
            str(record.get("match_id", "")),
            str(record.get("play_type", "")),
            str(record.get("option_code", "")),
        )
        current = latest.get(key)
        if current is None or str(record.get("snapshot_time", "")) > str(current.get("snapshot_time", "")):
            latest[key] = record
    return sorted(
        latest.values(),
        key=lambda r: (str(r.get("match_id", "")), str(r.get("play_type", "")), str(r.get("option_code", ""))),
    )
