"""SP movement calculations.

SP is treated as Sporttery fixed-prize value, not bookmaker odds.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpMovement:
    match_id: str
    play_type: str
    option_code: str
    first_snapshot_time: str
    previous_snapshot_time: str | None
    latest_snapshot_time: str
    first_sp: float
    previous_sp: float | None
    latest_sp: float
    change_from_first: float
    change_pct_from_first: float
    change_from_previous: float | None
    change_pct_from_previous: float | None
    direction_from_first: str
    direction_from_previous: str | None


def calculate_sp_movements(records: list[dict]) -> list[SpMovement]:
    """Calculate SP movement for each match/play/option series.

    The input can contain mixed matches and play types. Each movement compares:
    - first -> latest, for long-window drift
    - previous -> latest, for the newest tick
    """
    grouped: dict[tuple[str, str, str], list[dict]] = {}
    for record in records:
        key = (
            str(record.get("match_id", "")),
            str(record.get("play_type", "")),
            str(record.get("option_code", "")),
        )
        grouped.setdefault(key, []).append(record)

    movements = []
    for (match_id, play_type, option_code), group in grouped.items():
        ordered = sorted(group, key=lambda r: str(r.get("snapshot_time", "")))
        if not ordered:
            continue

        first = ordered[0]
        latest = ordered[-1]
        previous = ordered[-2] if len(ordered) >= 2 else None

        first_sp = float(first["sp_value"])
        latest_sp = float(latest["sp_value"])
        previous_sp = float(previous["sp_value"]) if previous else None

        change_from_first = round(latest_sp - first_sp, 4)
        change_pct_from_first = _pct_change(change_from_first, first_sp)
        change_from_previous = None
        change_pct_from_previous = None
        direction_from_previous = None
        if previous_sp is not None:
            change_from_previous = round(latest_sp - previous_sp, 4)
            change_pct_from_previous = _pct_change(change_from_previous, previous_sp)
            direction_from_previous = _direction(change_from_previous)

        movements.append(SpMovement(
            match_id=match_id,
            play_type=play_type,
            option_code=option_code,
            first_snapshot_time=str(first.get("snapshot_time", "")),
            previous_snapshot_time=str(previous.get("snapshot_time", "")) if previous else None,
            latest_snapshot_time=str(latest.get("snapshot_time", "")),
            first_sp=first_sp,
            previous_sp=previous_sp,
            latest_sp=latest_sp,
            change_from_first=change_from_first,
            change_pct_from_first=change_pct_from_first,
            change_from_previous=change_from_previous,
            change_pct_from_previous=change_pct_from_previous,
            direction_from_first=_direction(change_from_first),
            direction_from_previous=direction_from_previous,
        ))

    return sorted(
        movements,
        key=lambda m: (m.match_id, m.play_type, m.option_code),
    )


def latest_records(records: list[dict]) -> list[dict]:
    """Return the latest row for each match/play/option."""
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


def _pct_change(change: float, base: float) -> float:
    if base == 0:
        return 0.0
    return round(change / base, 4)


def _direction(change: float) -> str:
    if change > 0:
        return "up"
    if change < 0:
        return "down"
    return "flat"
