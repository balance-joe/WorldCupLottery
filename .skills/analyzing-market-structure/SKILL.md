# analyzing-market-structure

## Purpose

Use this skill after SP trends have been calculated for had, hhad, and ttg.

The goal is to translate multiple play-type trends into market structure:

- home small win
- home big win
- away not lose / away small win
- no-draw structure
- draw risk
- goal market clear but result unclear
- mixed/noisy structure
- popular favorite overheated

## Required Inputs

Use `market_structure.py` output.

Required fields:

- available
- had_direction
- hhad_direction
- ttg_direction
- consistency_level
- main_market_expression
- conflicts
- risk_flags
- suggested_focus
- avoid_focus
- research_priority

## Core Rules

Do not analyze had in isolation.

Always check:

1. had direction
2. hhad confirmation, missing status, or counter-signal
3. ttg goal structure
4. conflicts
5. volatility
6. multi-window consistency
7. research priority
8. external model alignment from `http://43.137.46.40:8000/` when reachable

For post-match review, also check:

9. Whether other same-match play types gave a stronger contradictory signal.
10. Whether the winning selection was the strongest pre-match structure or only one plausible path.
11. Whether the chosen play type matched the ticket role: core structure ticket vs small-stake experiment.

## hhad Missing Is Not hhad Rejection

You must distinguish:

- `hhad_missing`
- `hhad_no_confirmation`
- `hhad_counter_signal`

Definitions:

- hhad_missing: hhad_trend.available = false
- hhad_no_confirmation: hhad is available, but no_clear_direction or low confidence
- hhad_counter_signal: hhad is available and clearly points against the had direction

Never say hhad missing means hhad does not support big win.

## Key Interpretations

- Home small win:
  “市场更像支持主队小胜，而不是大胜穿盘。”
- Home big win:
  “多玩法共同支持主队方向，且让球与进球数没有明显冲突。”
- Away not lose / away small win:
  “市场表达更偏客队不败或客队小胜方向。”
- Goal market clear but result unclear:
  “胜平负方向不清，但总进球结构有明显表达，人工研究应优先看进球数。”
- No-draw structure:
  “市场表达更偏分胜负，平局权重下降。”
- Draw risk:
  “平局风险增强，不适合胜负双选。”
- Popular favorite overheated:
  “热门方向可能过热，主胜性价比下降，需警惕小胜、不穿或平局风险。”

## Cross-Play Sanity Checks

- A win selection is cleaner when had direction and hhad direction both strengthen in the same team direction.
- A total-goals selection is cleaner when the chosen goal bucket strengthens and adjacent buckets support the same low/mid/high-goal story.
- A score selection is cleaner when:
  - its total goals agree with ttg structure, and
  - its result margin agrees with had/hhad structure.
- If ttg supports 2 goals but hhad supports home -1 draw, 2:0 and 1:1 have different structural stories. Do not treat them as equivalent.
- If a score selection wins while had/hhad point elsewhere, label it as high-variance rather than a core structure hit.
- If a match is D priority or mixed/noisy across windows, a winning ticket should remain categorized as noisy unless there was a specific play-type signal.

## External Model Alignment

When the external World Cup prediction site is available:

- Use it after, not before, SP structure analysis.
- Compare result direction, expected goals, top scorelines, and over/under profile.
- Promote confidence only when SP structure and external model both support the same story.
- Downgrade if the external model highlights a materially different story, such as:
  - SP favors a favorite, but external model shows near-even teams.
  - SP supports a low-goal score, but external model expects high goals.
  - SP supports a scoreline whose result/margin conflicts with model top scores.
- Keep the final language as market structure, not true probability.

## Data Completeness and Priority

- If only had is available, `research_priority` cannot be A.
- If had is available but hhad and ttg are both missing, `research_priority` must not be A.
- A priority means research value, not winning probability.

## Volatility Downgrade

If the main signal comes from a high-volatility play type, downgrade language unless:

1. another play type confirms the direction
2. public information supports the move
3. recent and middle windows are consistent

## Multi-Window Structure Risk

- If open_to_latest and last_1h point in opposite directions, add `late_window_reversal`.
- If major windows are consistent, add `trend_persistence`.

## Research Priority

- A: worth focused human review
- B: watchable but has conflict
- C: noisy or single-signal only
- D: skip unless there is external reason
