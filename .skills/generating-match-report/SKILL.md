# generating-match-report

## Purpose

Use this skill to generate a human-readable match report from structured SP trend, market structure, and public information context.

## Required Inputs

Reports must consume the unified `agent_report_schema`.

Required sections:

- match
- window_summaries
- cross_window_summary
- market_structure
- public_info_context when available
- final_research_priority

Do not directly read raw SP snapshots.

## Output Style

Be concise, structured, and risk-aware.

Do not output long essays.

## Required Human-Readable Sections

1. 一句话结论
2. SP 结构表达
3. 跨玩法确认/冲突
4. 时间窗口变化
5. 公开信息解释
6. 风险点
7. 人工研究建议
8. 不建议方向

## Required JSON Output

```json
{
  "market_reading": "",
  "play_consistency": "",
  "tempo_reading": "",
  "public_info_reading": "",
  "risk_explanations": [
    {
      "risk": "",
      "explanation": ""
    }
  ],
  "suggested_human_focus": [],
  "avoid_or_caution": [],
  "research_priority": "A/B/C/D",
  "confidence_type": "structure_confidence_not_win_probability"
}
```

## public_info_reading Rule

- If public info was not triggered: `未触发公开信息检索。`
- If triggered but no reliable information: `未发现可靠公开信息解释该 SP 异动。`
- If public information exists: `公开信息与 SP 变化方向一致/冲突/混合。`

Do not leave this field empty.

## Forbidden Language

Do not use:

- 必胜
- 稳胆
- 稳赚
- 包中
- 稳赢
- 真实胜率
- 模型预测概率
- 推荐下注金额
- 梭哈

## Correct Language

Use:

- 市场表达
- 结构支持
- 方向增强
- 风险增加
- 值得人工继续研究
- 不适合作为核心方向
- 结构置信度，不是赛果概率
