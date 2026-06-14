---
name: record-sporttery-ticket
description: Record confirmed China Sporttery football betting tickets into this project's SQLite betting ledger. Use when the user says they bought, will buy, wants to store, record, log, settle, or track a竞彩足球/Sporttery ticket, stake plan, parlay, single, total-goals bet, or betting bankroll result in the D:\python\football project.
---

# Record Sporttery Ticket

## Purpose

Use this skill to persist user-confirmed manual betting tickets into the project SQLite ledger at `data/sporttery.db`.

This skill records money tracking and ticket decisions only. It does not place bets, does not alter raw Sporttery snapshots, and does not claim any bet is certain.

## Workflow

1. Confirm the user has given a concrete ticket or stake plan.
   - Required per ticket: label, pass type, stake amount, selections.
   - Required per selection: match id or match number/team pair, play type, option, selected SP.
   - If SP is missing, look up the latest stored SP in `sporttery_sp_snapshot` before recording.
   - If `sp_snapshot_id` is missing, the script/database layer will try to resolve it from `match_id + play_type + option_code + sp_snapshot_time`.
   - By default, only record World Cup tickets for this project. If the user explicitly asks to record another league, include that league in the ticket notes.
2. Use the existing ledger schema:
   - `betting_ticket`: one row per physical/logical ticket.
   - `betting_ticket_selection`: one row per leg/selection.
3. Run `scripts/record_ticket.py` from this skill to insert the ticket JSON.
4. Read back the inserted rows and summarize ticket ids, total stake, expected max payout, and status.

## JSON Shape

Pass one object with a `tickets` array:

```json
{
  "bet_group": "2026-06-11-plan-50",
  "placed_at": "2026-06-11 15:00:00",
  "tickets": [
    {
      "ticket_label": "周四001 墨西哥胜 单关",
      "pass_type": "single",
      "stake_amount": 20,
      "unit_stake": 2,
      "multiplier": 10,
      "expected_min_payout": 25.2,
      "expected_max_payout": 25.2,
      "selections": [
        {
          "match_id": "2040162",
          "match_num": "周四001",
          "play_type": "had",
          "option_code": "H",
          "option_name": "主胜",
          "selected_sp": 1.26,
          "sp_snapshot_id": 123,
          "sp_snapshot_time": "2026-06-11 12:25:32"
        }
      ]
    }
  ]
}
```

Supported project play types:

- `had`: 胜平负, option codes `H`, `D`, `A`
- `hhad`: 让球胜平负, option codes `H`, `D`, `A`, include `goal_line`
- `ttg`: 总进球, option codes `0` through `7`

## Commands

Use the workspace Python that has `sqlite3`. In this project, the Conda Python is reliable:

```powershell
& "C:\Users\admin\.conda\envs\ml\python.exe" .skills\record-sporttery-ticket\scripts\record_ticket.py --ticket-json '{...}'
```

For larger payloads, use a JSON file and run:

```powershell
& "C:\Users\admin\.conda\envs\ml\python.exe" .skills\record-sporttery-ticket\scripts\record_ticket.py --ticket-file data\my_ticket_payload.json
```

Add `--allow-duplicate-group` only when the user explicitly wants multiple batches with the same `bet_group`.

## Query Links

Use this join to inspect tickets with their linked match and SP snapshot:

```sql
SELECT
  t.id AS ticket_id,
  t.bet_group,
  t.ticket_label,
  t.stake_amount,
  s.match_num,
  m.home_team_name,
  m.away_team_name,
  s.play_type,
  s.option_code,
  s.option_name,
  s.selected_sp,
  sp.id AS sp_snapshot_id,
  sp.snapshot_time
FROM betting_ticket t
JOIN betting_ticket_selection s ON s.ticket_id = t.id
LEFT JOIN sporttery_match m ON m.match_id = s.match_id
LEFT JOIN sporttery_sp_snapshot sp ON sp.id = s.sp_snapshot_id
WHERE t.bet_group = ?
ORDER BY t.id, s.leg_index;
```

## Settlement

When the user asks to record win/loss after results:

1. Fetch or verify 90-minute results using the project's result flow.
2. Update `betting_ticket.ticket_status`, `actual_payout`, `profit_loss`, and `settled_at`.
3. Update each `betting_ticket_selection.result_status` and `actual_result`.

Do not settle from guesses or unofficial score assumptions.

After Sporttery results are stored, run:

```powershell
& "C:\Users\admin\.conda\envs\ml\python.exe" -m scripts.settle_betting_tickets --bet-group 2026-06-11-plan-50
```

The settlement code supports:

- `had`: compare selected `H/D/A` to `sporttery_match.result_90`
- `hhad`: apply the home `goal_line` to the 90-minute home score, then compare `H/D/A`
- `ttg`: compare total 90-minute goals to `0` through `6`, with `7` meaning `7+`
