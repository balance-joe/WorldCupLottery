"""已记录手动竞彩票单的结算辅助模块。"""

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
    """返回单个投注关的（状态, 实际结果）。

    结果状态为以下之一：hit（命中）、miss（未中）、pending（待定）、unsupported（不支持）。
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
        actual_code = _crs_code(home_score, away_score)
        return ("hit" if option_code == actual_code else "miss"), actual_code

    if play_type == "hafu":
        half_score = match.get("half_score")
        actual_code = _hafu_code(half_score, home_score, away_score)
        if actual_code is None:
            return "unsupported", "missing_half_score"
        return ("hit" if option_code == actual_code else "miss"), actual_code

    return "unsupported", str(play_type or "")


def settle_pending_tickets(conn: db.Connection, *, bet_group: str | None = None) -> list[TicketSettlement]:
    """结算所有关卡已有最终比赛结果的待结算票单。"""
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


def _crs_code(home_score: int, away_score: int) -> str:
    """根据比分构建 CRS option_code，例如 (2, 1) -> 's02s01'。

    超出单独列出的 CRS 矩阵范围的比分（每队 < 5 且总进球 < 7）
    映射到对应的"其他"代码：s-1sh（主胜其他）、s-1sd（平其他）、s-1sa（客胜其他）。
    """
    if home_score >= 5 or away_score >= 5 or (home_score + away_score) >= 7:
        if home_score > away_score:
            return "s-1sh"
        if home_score < away_score:
            return "s-1sa"
        return "s-1sd"
    return f"s{home_score:02d}s{away_score:02d}"


def _hafu_code(half_score: str | None, home_score: int, away_score: int) -> str | None:
    """根据半场和全场比分构建 HAFU option_code，例如 '1:0', 2, 1 -> 'hh'。"""
    if not half_score or ":" not in half_score:
        return None
    try:
        parts = half_score.split(":")
        half_h, half_a = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return None
    half = "h" if half_h > half_a else "d" if half_h == half_a else "a"
    full = "h" if home_score > away_score else "d" if home_score == away_score else "a"
    return half + full


def _had_result(home_score: int, away_score: int) -> str:
    if home_score > away_score:
        return "H"
    if home_score < away_score:
        return "A"
    return "D"


def _hhad_result(home_score: int, away_score: int, goal_line: str) -> str:
    adjusted_home = home_score + float(goal_line)
    # 以浮点数比较；当调整后为半球（如 1.5）时，永远不会等于整数的 away_score，
    # 因此结果只能是 H 或 A，不会出现 D。
    if adjusted_home > away_score:
        return "H"
    if adjusted_home < away_score:
        return "A"
    return "D"


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
            updated_at = ?
        WHERE id = ?
        """,
        (status, payout, profit_loss, now, now, ticket_id),
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
    """委托给 db._fetch_dicts 实现一致的游标到字典转换。"""
    return db._fetch_dicts(cur)
