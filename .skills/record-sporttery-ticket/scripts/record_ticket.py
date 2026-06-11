from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_payload(args: argparse.Namespace) -> dict:
    if args.ticket_json and args.ticket_file:
        raise SystemExit("Use only one of --ticket-json or --ticket-file")
    if args.ticket_json:
        return json.loads(args.ticket_json)
    if args.ticket_file:
        path = Path(args.ticket_file)
        return json.loads(path.read_text(encoding="utf-8"))
    raise SystemExit("Missing --ticket-json or --ticket-file")


def _validate_payload(payload: dict) -> None:
    tickets = payload.get("tickets")
    if not isinstance(tickets, list) or not tickets:
        raise SystemExit("payload.tickets must be a non-empty list")

    for index, ticket in enumerate(tickets, start=1):
        for field in ("ticket_label", "pass_type", "stake_amount", "selections"):
            if field not in ticket:
                raise SystemExit(f"ticket {index}: missing {field}")
        if float(ticket["stake_amount"]) <= 0:
            raise SystemExit(f"ticket {index}: stake_amount must be positive")
        selections = ticket["selections"]
        if not isinstance(selections, list) or not selections:
            raise SystemExit(f"ticket {index}: selections must be a non-empty list")
        for leg_index, selection in enumerate(selections, start=1):
            for field in ("match_id", "play_type", "option_code", "selected_sp"):
                if field not in selection:
                    raise SystemExit(f"ticket {index} leg {leg_index}: missing {field}")
            if float(selection["selected_sp"]) <= 0:
                raise SystemExit(f"ticket {index} leg {leg_index}: selected_sp must be positive")


def _with_defaults(payload: dict, ticket: dict) -> dict:
    normalized = dict(ticket)
    if "bet_group" not in normalized:
        normalized["bet_group"] = payload.get("bet_group")
    if "placed_at" not in normalized and payload.get("placed_at"):
        normalized["placed_at"] = payload["placed_at"]
    normalized.setdefault("ticket_status", "pending")
    normalized.setdefault("unit_stake", 2)
    normalized.setdefault("multiplier", max(1, round(float(normalized["stake_amount"]) / 2)))
    if "expected_min_payout" not in normalized and "expected_max_payout" in normalized:
        normalized["expected_min_payout"] = normalized["expected_max_payout"]
    if "expected_max_payout" not in normalized and "expected_min_payout" in normalized:
        normalized["expected_max_payout"] = normalized["expected_min_payout"]
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser(description="Record manual Sporttery betting tickets into SQLite")
    parser.add_argument("--ticket-json", help="JSON payload string")
    parser.add_argument("--ticket-file", help="Path to JSON payload file")
    parser.add_argument("--db-path", help="Override SQLite path; defaults to data/sporttery.db")
    parser.add_argument("--allow-duplicate-group", action="store_true")
    args = parser.parse_args()

    root = _repo_root()
    sys.path.insert(0, str(root))

    from src import db

    if args.db_path:
        db._SQLITE_PATH = Path(args.db_path)

    payload = _load_payload(args)
    _validate_payload(payload)

    conn = db.get_connection()
    try:
        db.ensure_tables(conn)
        bet_group = payload.get("bet_group")
        if bet_group and not args.allow_duplicate_group and db.fetch_betting_tickets(conn, bet_group):
            raise SystemExit(
                f"bet_group already exists: {bet_group}. "
                "Use --allow-duplicate-group only if this is intentional."
            )

        inserted_ids = []
        total_stake = 0.0
        expected_max_total = 0.0
        for ticket in payload["tickets"]:
            normalized = _with_defaults(payload, ticket)
            inserted_ids.append(db.save_betting_ticket(conn, normalized))
            total_stake += float(normalized["stake_amount"])
            expected_max_total += float(normalized.get("expected_max_payout") or 0)

        result = {
            "inserted_ticket_ids": inserted_ids,
            "bet_group": bet_group,
            "ticket_count": len(inserted_ids),
            "total_stake": round(total_stake, 2),
            "expected_max_total": round(expected_max_total, 2),
            "db_path": str(db._SQLITE_PATH),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
