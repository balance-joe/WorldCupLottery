"""Settle recorded betting tickets after Sporttery results are backfilled."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Settle pending betting tickets")
    parser.add_argument("--bet-group", help="Only settle one bet_group")
    args = parser.parse_args()

    from src import db
    from src.settlement import settle_pending_tickets

    conn = db.get_connection()
    try:
        db.ensure_tables(conn)
        settlements = settle_pending_tickets(conn, bet_group=args.bet_group)
        print(f"settled_tickets: {len(settlements)}")
        for settlement in settlements:
            print(
                f"  ticket_id={settlement.ticket_id} status={settlement.status} "
                f"payout={settlement.actual_payout:.2f} profit_loss={settlement.profit_loss:.2f}"
            )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
