"""Settlement helpers for recorded manual Sporttery tickets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src import db


@dataclass(frozen=True)
class LegSettlement:
    selection_id: int
    status: str
    actual_result: str


@dataclass(frozen=True)
class TicketSettlement:
    ticket_id: int
    status: str
    actual_payout: float
    profit_loss: float
    leg_settlements: tuple[LegSettlement, ...]


def evaluate_leg(selection: dict, match: dict) -> tuple[str, str]:
    """Return (status, actual_result) for one betting leg.

    Result status is one of: hit, miss, pending, unsupported.
    """
    home = match.get("home_score_90")
    away = match.get("away_score_90")
    if home is None or away is None:
        return "pending", ""

    home_score = int(home)
    away_score = int(away)
    play_type = selection.get("play_type")
    option_code = str(selection.get("option_code"))

    if play_type == "had":
        actual = _had_result(home_score, away_score)
        return ("hit" if option_code == actual else "miss"), actual

    if play_type == "hhad":
        goal_line = selection.get("goal_line")
        if goal_line in (None, ""):
            return "unsupported", "missing_goal_line"
        actual = _hhad_result(home_score, away_score, str(goal_line))
        return ("hit" if option_code == actual else "miss"), actual

    if play_type == "ttg":
        total = home_score + away_score
        actual = "7" if total >= 7 else str(total)
        return ("hit" if option_code == actual else "miss"), actual

    if play_type == "crs":
        actual = f"{home_score}:{away_score}"
        return ("hit" if option_code == actual else "miss"), actual

    return "unsupported", str(play_type or "")


def settle_pending_tickets(conn: db.Connection, *, bet_group: str | None = None) -> list[TicketSettlement]:
    """Settle pending tickets whose legs all have final match results."""
    tickets = _fetch_pending_tickets(conn, bet_group)
    settlements: list[TicketSettlement] = []
    for ticket in tickets:
        selections = _fetch_ticket_selections(conn, ticket["id"])
        if not selections:
            continue

        leg_results: list[LegSettlement] = []
        has_pending = False
        has_unsupported = False
        has_miss = False

        for selection in selections:
            match = db.fetch_match(conn, selection["match_id"]) or {}
            status, actual = evaluate_leg(selection, match)
            if status == "pending":
                has_pending = True
            elif status == "unsupported":
                has_unsupported = True
            elif status == "miss":
                has_miss = True
            leg_results.append(LegSettlement(selection["id"], status, actual))

        if has_pending:
            continue

        if has_unsupported:
            ticket_status = "needs_review"
            actual_payout = 0.0
        elif has_miss:
            ticket_status = "lost"
            actual_payout = 0.0
        else:
            ticket_status = "won"
            actual_payout = _ticket_payout(ticket, selections)

        profit_loss = round(actual_payout - float(ticket["stake_amount"]), 2)
        _update_ticket(conn, ticket["id"], ticket_status, actual_payout, profit_loss)
        for leg in leg_results:
            _update_selection(conn, leg)
        conn.commit()

        settlements.append(TicketSettlement(
            ticket_id=int(ticket["id"]),
            status=ticket_status,
            actual_payout=actual_payout,
            profit_loss=profit_loss,
            leg_settlements=tuple(leg_results),
        ))

    return settlements


def _had_result(home_score: int, away_score: int) -> str:
    if home_score > away_score:
        return "H"
    if home_score < away_score:
        return "A"
    return "D"


def _hhad_result(home_score: int, away_score: int, goal_line: str) -> str:
    adjusted_home = home_score + int(goal_line)
    return _had_result(adjusted_home, away_score)


def _ticket_payout(ticket: dict, selections: list[dict]) -> float:
    combined_sp = 1.0
    for selection in selections:
        combined_sp *= float(selection["selected_sp"])
    return round(combined_sp * float(ticket.get("unit_stake") or 2) * int(ticket.get("multiplier") or 1), 2)


def _fetch_pending_tickets(conn: db.Connection, bet_group: str | None) -> list[dict]:
    sql = "SELECT * FROM betting_ticket WHERE ticket_status = 'pending'"
    params: tuple[str, ...] = ()
    if bet_group is not None:
        sql += " AND bet_group = ?"
        params = (bet_group,)
    sql += " ORDER BY placed_at, id"
    return _fetch_dicts(conn.execute(sql, params))


def _fetch_ticket_selections(conn: db.Connection, ticket_id: int) -> list[dict]:
    return _fetch_dicts(conn.execute(
        "SELECT * FROM betting_ticket_selection WHERE ticket_id = ? ORDER BY leg_index",
        (ticket_id,),
    ))


def _update_ticket(conn: db.Connection, ticket_id: int, status: str, payout: float, profit_loss: float) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        UPDATE betting_ticket
        SET ticket_status = ?,
            actual_payout = ?,
            profit_loss = ?,
            settled_at = ?,
            updated_at = datetime('now','localtime')
        WHERE id = ?
        """,
        (status, payout, profit_loss, now, ticket_id),
    )


def _update_selection(conn: db.Connection, leg: LegSettlement) -> None:
    conn.execute(
        """
        UPDATE betting_ticket_selection
        SET result_status = ?,
            actual_result = ?
        WHERE id = ?
        """,
        (leg.status, leg.actual_result, leg.selection_id),
    )


def _fetch_dicts(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
