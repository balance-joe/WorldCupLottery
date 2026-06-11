# analyzing-sp-trend

## Purpose

Use this skill when analyzing SP movement for one match, one play type, and one time window.

Supported play types:

- had: 胜平负
- hhad: 让球胜平负
- ttg: 总进球

Future play types such as crs and hafu may be added later. If crs is added, interpret it as market expression over score distribution, not exact score prediction.

## Required Inputs

Use structured data from `sp_trend.py`.

Never analyze raw SP changes directly if structured trend data is available.

Required fields:

- play_type
- window
- available
- reason
- options
- sp_start
- sp_end
- sp_delta_pct
- normalized_implied_weight_start
- normalized_implied_weight_end
- normalized_weight_delta
- sp_trend
- weight_trend
- main_direction
- direction_confidence
- direction_gap
- volatility_level

## Core Interpretation Rule

SP movement and normalized weight movement must be separated.

- SP down usually means implied market weight up.
- SP up usually means implied market weight down.
- Final direction must rely on normalized_weight_delta, not SP delta alone.

Use these terms:

- strengthening
- weakening
- stable
- no_clear_direction
- mixed_direction

Avoid these terms:

- true probability
- real win rate
- model probability
- predicted probability

## Trend Priority

When interpreting a trend, use this priority order:

1. available
2. normalized_weight_delta
3. weight_trend
4. main_direction
5. direction_confidence
6. sp_trend as auxiliary explanation

Do not use sp_delta_pct alone to determine direction.

## SP Trend vs Weight Trend Conflict

If `sp_trend` and `weight_trend` are inconsistent, rely on `normalized_weight_delta`.

Example:

“该选项 SP 虽然下降，但在同玩法内部归一化权重并未明显增强，说明其变化可能受到其他选项 SP 同步变化影响，不能单独解读为该方向增强。”

## Time Windows

Always distinguish:

- open_to_latest: long-term direction
- last_24h: recent direction
- last_6h: near-match direction
- last_1h: late movement

If long-term and late movement conflict, highlight the conflict.

## Window Priority

Interpretation weight:

```text
last_1h > last_6h > last_24h > open_to_latest
```

But late signals still need confirmation.

## Volatility Interpretation

- `high`: signal needs confirmation
- `medium`: interpret normally but avoid strong certainty
- `low`: direction is relatively more coherent

High volatility does not mean the signal is unusable. It means the signal needs confirmation.

## Data Insufficiency

If `available=false`, do not infer direction.

Use:

“该窗口快照不足，不能判断趋势。”
