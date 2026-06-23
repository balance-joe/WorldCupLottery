# 竞彩足球 SP 异动雷达 + LLM 赛前分析系统

## 项目定位

不是 AI 自动预测胜平负，不是模型稳赚系统。

核心链路：

```
爬虫 → 快照库 → 指标引擎 → 信号识别 → LLM 分析 → 赛后复盘
```

---

## 快速开始

### 环境

- Python 3.11+
- requests
- pymysql
- fastapi
- uvicorn

### 安装

```bash
pip install -r requirements.txt
```

### 运行

```bash
# 启动控制台页面
python run_api.py
```

打开 `http://127.0.0.1:8000`，在页面里启动/停止 5 分钟循环抓取。

控制台启动的抓取命令固定为：

```bash
python -m scripts.fetch_sporttery --mode today --interval-seconds 300 --repeat 0
```

也可以直接命令行运行：

```bash
# 抓取关注列表全部比赛 + SP
python -m scripts.fetch_sporttery --mode today

# 抓取单场比赛
python -m scripts.fetch_sporttery --mode match --match-id 2040162

# 每 5 分钟抓一次，抓 12 轮
python -m scripts.fetch_sporttery --mode today --interval-seconds 300 --repeat 12

# 每 5 分钟一直抓，Ctrl+C 停止
python -m scripts.fetch_sporttery --mode today --interval-seconds 300 --repeat 0

# 抓取赛果并回填 90 分钟胜平负结果
python -m scripts.fetch_results --page-size 50

# 单场 SP 趋势与市场结构分析
python -m scripts.analyze_match_structure --match-id 2040162
python -m scripts.analyze_match_structure --match-id 2040162 --debug --save
python -m scripts.analyze_match_structure --match-id 2040162 --with-detail --fetch-detail --debug

# 当天/已入库比赛快速筛选
python -m scripts.analyze_today_matches
python -m scripts.analyze_today_matches --date 2026-06-12 --with-detail --fetch-detail

# 逐票复盘（按下单时点回看信号）
python -m scripts.analyze_tickets
python -m scripts.analyze_tickets --detail

# 策略回测（带推荐门禁）
python -m scripts.backtest_strategies
python -m scripts.backtest_strategies --detail

# 全玩法信号回测（研究用途）
python -m scripts.backtest_sp_signals
python -m scripts.backtest_all_playtypes

# 单场抓取非SP详情证据
python -m scripts.fetch_match_details --match-id 2040162 --output data/match_2040162_detail.json

# 可选：抓取外部预测源并和 SP/赛果做对比
python -m scripts.fetch_predictions --detail
python -m scripts.analyze_predictions --detail

```

### 生成 LLM 分析包

```bash
python -m scripts.build_llm_package --match-id 2040162
```

输出到 `data/packages/2040162.json`。

### 校验胜平负手工票

项目只做合法性校验，不自动下单。当前出票规则范围限定为 `had` 胜平负。

```python
from src.tickets import (
    build_ticket,
    make_had_selection,
    make_had_selection_from_sp_records,
    quote_ticket_with_latest_sp,
)

# 单关：必须是 1 场，并且该场 had 的 is_single=True
single = build_ticket(
    [make_had_selection("2040162", ["H"], is_single=True, match_status="1")],
    "single",
)

# 2 串 1：必须是 2 场不同比赛
parlay = build_ticket(
    [
        make_had_selection("2040162", ["H", "D"], match_status="1"),
        make_had_selection("2040163", ["A"], match_status="1"),
    ],
    "2x1",
    multiplier=2,
)

print(single.amount, parlay.amount)
```

如果已经从 `sporttery_sp_snapshot` 查出了 HAD SP 行，也可以直接用记录里的 `is_single`：

```python
selection = make_had_selection_from_sp_records(
    "2040162",
    ["H"],
    sp_records,
    match_status="1",
)
ticket = build_ticket([selection], "single")
```

出票前必须用最新 SP 重新报价：

```python
quote = quote_ticket_with_latest_sp(ticket, latest_sp_records)
print(quote.option_sp)
print(quote.min_potential_payout, quote.max_potential_payout)
```

---

## 目录结构

```
football/
├── scripts/
│   ├── __init__.py
│   ├── fetch_sporttery.py      # 赛程/SP 抓取入口
│   ├── fetch_results.py        # 赛果回填入口
│   ├── analyze_match_structure.py # 单场结构分析
│   ├── analyze_today_matches.py   # 比赛快速筛选 + 推荐门禁 + 候选玩法
│   ├── analyze_tickets.py         # 逐票复盘（按下单时点）
│   ├── backtest_strategies.py     # 规则化策略回测
│   ├── backtest_sp_signals.py     # 全玩法信号回测
│   ├── backtest_all_playtypes.py  # 全玩法临场单信号回测
│   ├── fetch_predictions.py       # 可选外部预测源抓取
│   └── analyze_predictions.py     # 外部预测源 vs SP/赛果对比
├── src/
│   ├── __init__.py
│   ├── config.py                # API 地址、请求头、DB 连接
│   ├── api_client.py            # HTTP 请求封装
│   ├── parsers.py               # 解析 API 响应
│   ├── probability.py           # 隐含概率计算
│   ├── sp_movement.py           # SP 变化计算
│   ├── sp_trend.py              # SP 趋势结构化分析
│   ├── market_structure.py      # 跨玩法市场结构判断
│   ├── recommendation.py        # 推荐门禁 + HAD/TTG/CRS 候选生成
│   ├── agent_report_schema.py   # LLM 结构化输入包
│   ├── structure_analysis.py    # 分析编排
│   ├── db.py                    # MySQL 数据库访问
│   ├── llm_package.py           # LLM 分析包生成器
│   └── tickets.py               # 胜平负手工票合法性校验
├── web/                         # FastAPI 控制台页面
├── tests/                       # 单元测试
├── run_api.py                   # FastAPI 控制入口
├── requirements.txt
└── README.md
```

---

## 数据库

### 表结构

| 表 | 用途 | 行数示例 |
|---|------|---------|
| `sporttery_raw_snapshot` | 原始 API 响应（永不覆盖） | 27 |
| `sporttery_match` | 比赛主表 | 26 |
| `sporttery_sp_snapshot` | SP 时间序列 + 隐含概率 | 483 |
| `sporttery_market_analysis` | SP 趋势/市场结构分析快照 | 0+ |
| `betting_ticket` | 手工票台账（含 `source_type`） | 0+ |
| `betting_ticket_selection` | 票内每条选择 | 0+ |

### 连接方式

运行时只使用 MySQL。配置写在项目根目录 `.env`，脚本通过 `src.db` 自动读取：

```powershell
$env:SPORTTERY_DB_BACKEND='mysql'
$env:SPORTTERY_MYSQL_HOST='your-host'
$env:SPORTTERY_MYSQL_PORT='3309'
$env:SPORTTERY_MYSQL_USER='football'
$env:SPORTTERY_MYSQL_PASSWORD='your-password'
$env:SPORTTERY_MYSQL_DATABASE='football'
```

SQLite 本地库已不作为业务数据源；仅单元测试内部使用临时 SQLite 隔离环境。

---

## API 端点

### 数据采集（已实现）

| API | 端点 | 用途 |
|-----|------|------|
| 赛程列表 | `getMatchDataPageListV1.qry?method=concern` | 比赛列表 + 基础 SP |
| 赛果开奖 | `getMatchDataPageListV1.qry?method=result&pageSize=20` | 赛果列表；字段 `sectionsNo999` 作为 90 分钟全场比分 |
| 完整 SP | `getFixedBonusV1.qry?clientCode=3001&matchId=` | 5 玩法当前 SP；API 自带 3-6 条历史变化记录，额外变化由定时快照补充 |

### 对阵详情（已探明，待集成）

| API | 用途 |
|-----|------|
| `getMatchHeadV1.qry` | 比赛头部信息 |
| `getMatchFeatureV1.qry` | 特征分析（近10场/交锋/进失球） |
| `getMatchResultV1.qry` | 比赛近况（近5场详细） |
| `getResultHistoryV1.qry` | 历史交锋 |
| `getFutureMatchesV1.qry` | 未来赛程 |
| `getMatchTablesV1.qry` | 积分榜 |
| `getMatchPlayerV1.qry` | 射手信息 |
| `getInjurySuspensionV1.qry` | 伤停一览 |
| `getSameOddsV1.qry` | 同奖历史回查 |
| `getTeamPooldivStatsV1.qry` | 彩果统计 |

---

## SP 与隐含概率

### 计算公式

```
implied_prob_raw  = 1 / sp_value
prob_sum          = sum(implied_prob_raw)  # 同一 match_id + play_type + snapshot_time
implied_prob_norm = implied_prob_raw / prob_sum
```

### 定时更新与 SP 变化

定时更新直接重复运行抓取入口。每次抓取会保留原始 API 快照，并把每个玩法选项写入 `sporttery_sp_snapshot`。同一 `match_id + snapshot_time + play_type + option_code` 会去重，新的 `snapshot_time` 会形成时间序列。

```bash
python -m scripts.fetch_sporttery --mode today --interval-seconds 300 --repeat 0
```

程序内计算 SP 变化：

```python
from src import db
from src.sp_movement import calculate_sp_movements

conn = db.get_connection()
history = db.fetch_sp_history(conn, ["2040162"], play_type="had")
movements = calculate_sp_movements(history)
```

变化指标包含：

- `change_from_first`：首笔 SP 到最新 SP 的变化。
- `change_pct_from_first`：首笔到最新的比例变化。
- `change_from_previous`：上一笔 SP 到最新 SP 的变化。
- `change_pct_from_previous`：上一笔到最新的比例变化。
- `direction_from_first` / `direction_from_previous`：`up`、`down`、`flat`。

出票前重新计算：

```python
latest = db.fetch_latest_sp_snapshots(conn, ["2040162"], play_type="had")
quote = quote_ticket_with_latest_sp(ticket, latest)
```

注意：这里的报价只是基于本地最新快照重新计算。最终中奖奖金仍以体彩出票成功时的 SP 为准。

---

## SP 趋势与市场结构分析

新增结构化分析链路：

```text
SP 快照
  -> 同玩法趋势
  -> normalized_implied_weight 变化
  -> had/hhad/ttg 主方向
  -> 跨玩法确认/冲突
  -> 市场结构表达
  -> LLM 解释包
```

核心原则：

- SP 是中国体彩固定奖金，不是海外赔率。
- `normalized_implied_weight` 只是同一玩法内部的市场表达权重，不是真实胜率。
- 趋势计算、方向判断、跨玩法结构判断全部由代码完成。
- LLM 只消费结构化结果，不直接从原始 SP 判断趋势。
- 不输出“稳赚”“稳胆”“必买”“模型预测概率”。

支持窗口：

```text
open_to_latest
last_24h
last_6h
```

同玩法趋势输出包括：

- `sp_delta` / `sp_delta_pct`
- `raw_implied_weight`
- `normalized_implied_weight`
- `normalized_weight_delta`
- `sp_trend`
- `weight_trend`
- `main_direction`
- `direction_confidence`

跨玩法结构输出包括：

- `main_market_expression`
- `consistency_level`
- `conflicts`
- `risk_flags`
- `suggested_focus`
- `avoid_focus`
- `research_priority`

单场分析：

```bash
python -m scripts.analyze_match_structure --match-id 2040162
python -m scripts.analyze_match_structure --match-id 2040162 --window open_to_latest --debug
python -m scripts.analyze_match_structure --match-id 2040162 --save
```

快速筛选：

```bash
python -m scripts.analyze_today_matches
python -m scripts.analyze_today_matches --window last_24h
python -m scripts.analyze_today_matches --date 2026-06-12 --with-detail --fetch-detail
```

### 推荐门禁与每日输出

项目现在把“读盘”和“出票建议”拆开：

- `market_structure` 负责描述市场表达
- `recommendation` 负责判断是否可买，并生成每日建议所需的主预测、进球区间和辅助比分

当前门禁规则：

- 只允许 `A/B` 优先级进入候选池
- `had/hhad/ttg` 至少要有 2 笔快照才能作为推荐依据
- 高冲突盘会拦截 `had/hhad/crs`
- `had` 不足时，不推荐 `crs`

`scripts.analyze_today_matches` 会直接打印：

- `分类: 主推场/观察场/过滤场`
- `正式主票: had:H / hhad:A / 不买`
- `正式比分小票: crs:s02s00 / 不买`
- `辅助观察: 进球区间、半场胜平负、半全场`
- `门禁: ...`

每日建议可以用赛前 SP 做资金回测：

```bash
python -m scripts.backtest_daily_suggestions --league 世界杯 --mode recommendation
python -m scripts.backtest_daily_suggestions --league 世界杯 --mode recommendation --unit-stake 2 --detail
```

收益口径：正式主票按结构选择 `HAD` 或 `HHAD`；正式比分小票只在主推场展示 `CRS`，和主票分开复盘；日报里的 `进球区间`、半场胜平负和半全场是观察/辅助字段，不进入主票收益。

### 非 SP 证据层

除 SP 市场表达外，项目现在还支持接入 detail APIs 形成第二层证据：

- `matchResult`：近况与近 5 场表现
- `matchFeature`：近 10 场进失球、主客记录
- `resultHistory`：历史交锋
- `matchTables`：排名信息
- `injurySuspension`：伤停数量
- `sameOdds`：同奖样本
- `futureMatches`：后续赛程

当前策略：

- `SP` 决定市场表达与基础优先级
- `非SP` 决定基本面倾向与校正
- `final_research_priority` 会在 `sp_research_priority` 基础上做一级上调或下调

### 返还率参考

由 SP 倒数和反推的理论返还率近似值，不等同于官方返奖比例。

| 玩法 | 典型 prob_sum | 理论返还率近似 |
|------|-------------|--------|
| had 胜平负 | ~1.13 | ~88.5% |
| hhad 让球胜平负 | ~1.13 | ~88.5% |
| ttg 总进球 | ~1.25 | ~80% |

### 玩法编码

| 编码 | 玩法 | 选项编码 |
|------|------|---------|
| had | 胜平负 | H / D / A |
| hhad | 让球胜平负 | H / D / A |
| ttg | 总进球 | 0 / 1 / 2 / 3 / 4 / 5 / 6 / 7 |
| crs | 比分 | s01s00 等（后续） |
| hafu | 半全场 | hh / hd / ha 等 |
| half_result | 半场胜平负 | H / D / A，由 hafu 聚合推断 |

当前本地 SP 数据没有独立半场进球玩法；半场相关预测/回测只覆盖 `hafu` 和由 `hafu` 聚合出的 `half_result`。

---

## 胜平负出票规则校验

当前项目只支持 `had` 胜平负手工票校验：

- 只允许 `had`，选项只允许 `H`、`D`、`A`。
- `match_status` 必须为 `"1"`，否则不能形成购票动作。
- 单关 `pass_type="single"`：只能包含 1 场比赛，且该场 API 返回的 `is_single` 必须为 `True`。
- 可以用 `make_had_selection_from_sp_records()` 从 HAD SP 行里推导 `is_single`，避免手工填错单关限制。
- 串关只支持 `N串1`，代码里写作 `Nx1`，例如 `2x1`、`3x1`。
- 串关至少 2 场，`N` 必须等于选择的比赛场数。
- 同一张票里同一场比赛只能出现一次，避免同场不同玩法或重复选择混入串关。
- 金额按 `注数 * 2元 * 倍数` 计算；复式选项会增加注数，例如 1 场选 `H/D`、另一场选 `A`，`2x1` 为 2 注。

## 票据台账与复盘

`betting_ticket.source_type` 用来区分票的来源，避免把系统票和人工赔率票混为一谈。

当前约定值：

- `SYSTEM`：按系统建议形成的票
- `USER_ODDS_ONLY`：只按赔率/个人直觉形成的票
- `USER_MODIFIED`：参考系统后人工改过的票
- `USER_ACTUAL`：用户实际购买，但不一定来自系统
- `UNKNOWN`：历史老票，来源未补标

逐票复盘脚本：

```bash
python -m scripts.analyze_tickets
python -m scripts.analyze_tickets --detail
```

复盘口径：

- 优先按 `betting_ticket_selection.sp_snapshot_time`
- 否则回退到 `betting_ticket.placed_at`
- 只分析该时间点之前已经存在的 SP 快照，避免赛后信息泄漏

## 可选外部预测源

项目支持抓取一个外部预测站点的数据，落库到 `pred_match / pred_score_matrix`，用于和 SP 结构做对比。

注意：

- 这是可选研究数据源，不是本项目的真值来源
- 不能替代中国体育彩票竞彩足球规则和 SP 结构本身
- 相关脚本只用于对比、校验、发现偏差，不应直接当成出票信号

---

## 赛果回填

赛果源使用移动端足球数据页面 `https://m.sporttery.cn/mjc/zqsj/?tab=result` 的真实列表接口：

```text
getMatchDataPageListV1.qry?method=result&pageSize=20
```

回填规则：

- `sectionsNo999` 作为 90 分钟全场比分，符合项目规则“足球结果为 90 分钟含伤停补时”。
- `sectionsNo1` 保存为半场比分，仅用于参考。
- `matchStatus=11` 等赛果页完成状态可回填；无法解析比分或 `无效场次` 不写入 `result_90`。
- `result_90`：主胜 `H`，平 `D`，客胜 `A`。

运行：

```bash
python -m scripts.fetch_results --page-size 50
python -m scripts.fetch_results --match-date 2026-06-10
```

回填字段写入 `sporttery_match.home_score_90`、`away_score_90`、`result_90`、`half_score`、`full_score_90`。

---

## LLM 分析包

### 结构

```json
{
  "match": {
    "match_id": "2040162",
    "match_num": "周三001",
    "league": "世界杯",
    "match_time": "2026-06-11T22:00:00+08:00",
    "home_team": "法国",
    "away_team": "丹麦",
    "handicap_line": "-1"
  },
  "window_summaries": {
    "open_to_latest": {
      "market_structure": {},
      "summary_signals": [],
      "risk_flags": []
    },
    "last_24h": {
      "market_structure": {},
      "summary_signals": [],
      "risk_flags": []
    },
    "last_6h": {
      "market_structure": {},
      "summary_signals": [],
      "risk_flags": []
    }
  },
  "cross_window_summary": {
    "long_term_direction": "开售至今主胜方向增强",
    "mid_term_direction": "最近6小时继续增强",
    "recent_change": "临场主胜方向减弱",
    "tempo_reading": "长期支持主队，但临场出现降温，需要谨慎。"
  },
  "final_research_priority": "B",
  "llm_instruction": "请基于中国体彩竞彩足球SP变化分析市场表达。不要预测确定赛果，不要输出真实胜率，不要使用海外赔率逻辑。不要使用稳胆、必买、稳赚、模型预测等表达。"
}
```

### 约束

- 输入以 `market_structure / summary_signals / risk_flags / cross_window_summary / final_research_priority` 为核心。
- LLM 只解释结构化结果，不直接从原始 SP 计算趋势。
- 不输出“必胜”“稳赚”“稳胆”“真实胜率”“模型预测概率”“建议下注多少”。
- `confidence_type` 只能表示结构置信，不表示赛果概率。

### 输出校验

- 字段完整性校验
- 禁用词校验
- JSON parse 校验

### LLM 输出 JSON Schema

```json
{
  "market_reading": "市场当前主要表达...",
  "play_consistency": "胜平负、让球、总进球之间的关系...",
  "tempo_reading": "长期与临场变化节奏...",
  "risk_explanations": [
    {
      "risk": "让球未确认大胜",
      "explanation": "胜平负主胜增强，但让球胜平负没有同步支持让胜，说明市场更偏主队小胜或不穿。"
    }
  ],
  "suggested_human_focus": [
    "优先人工查看胜平负主胜方向",
    "观察总进球2/3球结构"
  ],
  "avoid_or_caution": [
    "谨慎直接追让胜"
  ],
  "research_priority": "A",
  "confidence_type": "structure_confidence_not_win_probability"
}
```

---

## 开发优先级

```
✅ 1. 批量抓取脚本
✅ 2. raw_snapshot 入库
✅ 3. match 入库
✅ 4. had/hhad/ttg SP 入库
✅ 5. 隐含概率计算
✅ 5.1 胜平负手工票合法性校验
✅ 5.2 出票前按最新 SP 重新报价
✅ 6. 定时快照
✅ 7. SP 变化指标
✅ 8. SP 趋势与市场结构信号识别
✅ 9. LLM match package（v2）
✅ 10. LLM 结构化输入包
✅ 11. 赛果回填
⬜ 12. 复盘评估
```

---

## 原则

```text
先有稳定数据，再有指标。
先有指标，再有 LLM 分析。
先有 LLM 分析，再有赛后复盘。
复盘有效后，再考虑是否需要建模。
```

不做机器学习预测胜平负。不做自动投注。LLM 不能输出"稳赢""必买"。
