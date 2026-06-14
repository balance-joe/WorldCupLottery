# using-sporttery-sp-analysis

## Purpose

Use this skill when analyzing Chinese Sports Lottery football matches based on Sporttery SP data.

This project is not a prediction system. It is a SP structure analysis and human decision support system.

## Core Rules

- Treat SP as 中国体育彩票 fixed-prize value, not bookmaker odds.
- Do not use overseas bookmaker logic unless explicitly requested.
- Default to World Cup matches only for ticket planning in this project.
- Exclude non-World-Cup matches from "today's buy" or slate-screening answers unless the user explicitly asks for another league.
- Do not output true win probability.
- Do not say 稳胆, 必买, 稳赚, 包中, 必胜, 稳赢, 梭哈.
- Do not directly recommend betting money.
- Do not output stake sizing unless the user explicitly asks for budget planning.
- Do not let LLM infer match direction from raw SP alone.
- Always rely on structured outputs from:
  - `sp_trend.py`
  - `market_structure.py`
  - `tavily_context.py` when available
- Before finalizing a ticket plan, cross-check the relevant World Cup match on `http://43.137.46.40:8000/` when reachable.
- Treat that site as an external team-strength/score model, not as Sporttery SP. Use it only as confirmation or contradiction for our SP structure.

## Correct Goal

The goal is to identify:

- Whether the match is worth human research.
- Whether had/hhad/ttg structures confirm or conflict.
- Whether a popular direction is overheated.
- Whether there is a no-draw structure.
- Whether there is draw risk.
- Whether a cold direction has structural support.
- Whether public information explains SP movement.
- Whether a post-match hit was supported by pre-match structure or was mostly result variance.
- Whether the external model site supports, conflicts with, or is neutral toward the SP-based conclusion.

## External Model Cross-Check

For each candidate ticket plan:

1. First form the SP-based view from Sporttery data.
2. Then check the matching World Cup fixture on `http://43.137.46.40:8000/`.
3. Extract only decision-relevant fields:
   - fused win/draw/loss probabilities.
   - weighted Elo direction.
   - Dixon-Coles direction.
   - expected goals.
   - over/under 2.5 split.
   - top scorelines.
4. Label alignment:
   - `supports`: external model and SP structure tell the same story.
   - `partial`: external model supports one part, such as low goals, but not the result direction.
   - `conflicts`: external model points against the SP-based play.
   - `neutral`: no clear help.
   - `unavailable`: site cannot be reached or match is not listed.
5. If alignment is `conflicts`, downgrade the ticket role or avoid making it a core ticket.
6. If alignment is `supports`, the ticket can be promoted only when SP structure itself is already coherent.

Never replace Sporttery SP structure with the external model. The website answers “team/model view”; this project answers “Sporttery market structure.”

## Post-Match Review Rule

When reviewing tickets after results are known:

- Separate `structure hit` from `result hit`.
- First reconstruct the pre-match SP structure from stored snapshots.
- Review all available play types for the same match, not only the winning selection.
- Look for stronger contrary signals before calling the original choice high quality.
- Do not upgrade a noisy D/C priority match just because the ticket won.
- Treat exact-score hits as high-variance unless score-market movement also agreed with had/hhad/ttg structure.
- Preserve the original ticket class:
  - core structure ticket: multiple play types confirmed before kickoff.
  - small-stake experiment: weak/noisy structure with one reasonable angle.
  - result-only hit: won but lacked pre-match structural support.

## Forbidden Framing

Never frame the result as:

- this team will win
- the model predicts
- true probability
- sure bet
- stable profit
- 稳胆
- 必买
- 包中
- 稳赚

Use this framing instead:

- market expression
- structure supports
- structure conflicts
- risk flag
- worth human review
- not suitable as core direction
- structure confidence, not match-result probability

## Output Philosophy

The system should help users:

- 少碰错场
- 少追过热
- 少买冲突玩法
- 提高每张票的逻辑质量

The system must not pretend it can guarantee results.
