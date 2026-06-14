---
name: reviewing-sporttery-ticket-results
description: Review settled or winning China Sporttery football tickets in the D:\python\football project. Use when the user asks why a ticket won or lost, wants to复盘中奖/亏损, compare winnings to pre-match SP, detect hindsight bias, classify ticket quality, or improve future竞彩足球 betting analysis from recorded results.
---

# Reviewing Sporttery Ticket Results

## Purpose

Use this skill to review bought Sporttery tickets after match results are known.

The goal is not to prove the result was predictable. The goal is to classify whether the ticket had reusable pre-match structure.

## Required Workflow

1. Read the recorded ticket from `betting_ticket` and `betting_ticket_selection` when available.
2. Reconstruct the pre-match board from `sporttery_sp_snapshot` and raw `fixedBonus` snapshots when needed.
3. Review every available same-match play type:
   - `had`: result direction.
   - `hhad`: margin and favorite-risk structure.
   - `ttg`: goal-count structure.
   - `crs` from raw snapshots only when exact score is relevant.
4. Compare the chosen selection with plausible alternatives from the same board.
5. Assign one ticket-quality label:
   - `structure_hit`: the ticket won and multiple pre-match structures supported the story.
   - `single_signal_hit`: the ticket won and one play type supported it, but the full market was mixed.
   - `result_hit`: the ticket won but pre-match structure was weak, noisy, or conflicting.
   - `structure_miss`: the ticket lost despite a coherent pre-match structure.
   - `avoid_lesson`: the ticket lost and pre-match structure already warned against it.
6. Preserve the original role:
   - core ticket: conservative or multi-structure confirmation.
   - experiment ticket: small-stake, higher SP, one-angle logic.
   - conflict ticket: selected despite visible cross-play conflict.

## Anti-Hindsight Checks

Always ask:

- What would the same SP board have suggested before the result?
- Did the winning option strengthen more than its alternatives?
- Did adjacent goal buckets or score lines support the same story?
- Did hhad confirm the result margin or conflict with it?
- Was the match priority C/D and therefore noisy despite the win?
- Was this choice only justified because the final score is now known?

## Exact Score Review

For exact-score hits:

- Treat the hit as high-variance by default.
- Check raw `fixedBonus.value.oddsHistory.crsList`.
- Map score codes such as `s01s01` to `1:1`.
- Compare the score with:
  - ttg total-goals movement.
  - had result direction.
  - hhad margin direction.
- If the score's total goals agree with ttg but its result/margin conflicts with had/hhad, label it `single_signal_hit` or `result_hit`, not `structure_hit`.

## Output Format

Keep the review blunt:

- What won or lost.
- The recorded SP and payout.
- The pre-match supporting signals.
- The pre-match conflicting signals.
- The ticket-quality label.
- What rule should change next time.

Do not use deterministic prediction language.
