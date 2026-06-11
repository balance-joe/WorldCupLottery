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

### 安装

```bash
pip install -r requirements.txt
```

### 运行

```bash
# 抓取关注列表全部比赛 + SP（SQLite）
python -m scripts.fetch_sporttery --mode today

# 抓取单场比赛
python -m scripts.fetch_sporttery --mode match --match-id 2040162

# 每 5 分钟抓一次，抓 12 轮
python -m scripts.fetch_sporttery --mode today --interval-seconds 300 --repeat 12

# 每 5 分钟一直抓，Ctrl+C 停止
python -m scripts.fetch_sporttery --mode today --interval-seconds 300 --repeat 0

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
│   └── fetch_sporttery.py      # CLI 入口
├── src/
│   ├── __init__.py
│   ├── config.py                # API 地址、请求头、DB 连接
│   ├── api_client.py            # HTTP 请求封装
│   ├── parsers.py               # 解析 API 响应
│   ├── probability.py           # 隐含概率计算
│   ├── sp_movement.py           # SP 变化计算
│   ├── db.py                    # SQLite 数据库
│   ├── llm_package.py           # LLM 分析包生成器
│   └── tickets.py               # 胜平负手工票合法性校验
├── data/                        # SQLite 数据库 + 导出文件
├── tests/                       # 单元测试
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

### 连接方式

只使用 SQLite。数据文件在 `data/sporttery.db`，零配置。

---

## API 端点

### 数据采集（已实现）

| API | 端点 | 用途 |
|-----|------|------|
| 赛程列表 | `getMatchDataPageListV1.qry?method=concern` | 比赛列表 + 基础 SP |
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
| hafu | 半全场 | hh / hd / ha 等（后续） |

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

---

## LLM 分析包

### 结构

```json
{
  "match": {},
  "time_context": {},
  "status_control": {},
  "markets": { "had": {}, "hhad": {}, "ttg": {} },
  "movement_profile": {},
  "team_form": {},
  "historical_context": {},
  "signals": {
    "positive_signals": [],
    "negative_signals": [],
    "structure_signals": [],
    "uncertainty_flags": []
  },
  "llm_constraints": {}
}
```

### 信号分类规则

**positive_signals：** SP 下降方向增强、概率提升、多玩法方向一致、状态数据利好

**negative_signals：** 与主方向相反或削弱主方向的信号，例如让胜未同步下降、主胜下降但平局也下降、总进球结构不支持大胜

**structure_signals：** 玩法结构信号，不直接支持或反对主方向，但影响选市场策略。例如总进球低赔集中在 2/3 球、让球线偏深/偏浅

**uncertainty_flags：** 暂停销售、历史样本不足、同奖无参考、SP 波动异常

### 硬控件

```json
"llm_constraints": {
  "can_recommend_ticket": false,       // 暂停销售时为 false
  "reason": "暂停销售",
  "allowed_output": "analysis_only",   // 只能分析，不能推荐
  "forbidden_phrases": ["稳赢", "必买", "稳胆", "必中", "无脑"]
}
```

### movement_profile 字段

```json
{
  "direction": "down",       // up / down / flat
  "pattern": "gradual",      // stable / gradual / moderate / sharp
  "volatility": "low",       // low / medium / high
  "sp_change": -0.04,
  "sp_change_pct": -0.0299,
  "prob_change": 0.0201
}
```

### time_context.phase（纯时间维度）

| 阶段 | 条件 | 含义 |
|------|------|------|
| early_pre_match | >24h | 开盘早期趋势 |
| pre_match | 3-24h | 赛前观察 |
| late_pre_match | 0-3h | 临场异动期 |
| closed_or_result | <0h 或已停售 | 赛后 |

销售状态在 `status_control` 中单独判断，不混入时间阶段。

### LLM 输出 JSON Schema

```json
{
  "summary": "",
  "direction": "home_lean | draw_lean | away_lean | no_clear_direction",
  "market_view": {
    "preferred": "had | hhad | ttg | none",
    "avoid": [],
    "reason": ""
  },
  "goal_view": {
    "range": "0-1 | 2-3 | 4+ | unclear",
    "reason": ""
  },
  "risk_level": "low | medium | high",
  "confidence_level": "low | medium | high",
  "key_reasons": [],
  "risk_flags": [],
  "structure_notes": [],
  "watch_items": [],
  "action": "analysis_only | observe | no_action"
}
```

`match_status` 暂停销售时强制 `"action": "analysis_only"`。

`confidence_level` 由 LLM 输出等级（low/medium/high），不输出假精确数字。后续由系统根据 SP 一致性、变化幅度、数据完整度等计算 `system_confidence_score`。

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
⬜ 8. 信号识别
✅ 9. LLM match package（v2）
⬜ 10. LLM 分析报告
⬜ 11. 赛果回填
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
