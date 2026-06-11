# using-sporttery-sp-analysis

## Purpose

Use this skill when analyzing Chinese Sports Lottery football matches based on Sporttery SP data.

This project is not a prediction system. It is a SP structure analysis and human decision support system.

## Core Rules

- Treat SP as 中国体育彩票 fixed-prize value, not bookmaker odds.
- Do not use overseas bookmaker logic unless explicitly requested.
- Do not output true win probability.
- Do not say 稳胆, 必买, 稳赚, 包中, 必胜, 稳赢, 梭哈.
- Do not directly recommend betting money.
- Do not output stake sizing unless the user explicitly asks for budget planning.
- Do not let LLM infer match direction from raw SP alone.
- Always rely on structured outputs from:
  - `sp_trend.py`
  - `market_structure.py`
  - `tavily_context.py` when available

## Correct Goal

The goal is to identify:

- Whether the match is worth human research.
- Whether had/hhad/ttg structures confirm or conflict.
- Whether a popular direction is overheated.
- Whether there is a no-draw structure.
- Whether there is draw risk.
- Whether a cold direction has structural support.
- Whether public information explains SP movement.

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
