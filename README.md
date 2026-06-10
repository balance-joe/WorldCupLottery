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
- requests, PyMySQL

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

# 使用 MySQL
python -m scripts.fetch_sporttery --mode today --backend mysql
```

### 生成 LLM 分析包

```bash
python -m scripts.build_llm_package --match-id 2040162
```

输出到 `data/packages/2040162.json`。

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
│   ├── db.py                    # SQLite/MySQL 双后端
│   └── llm_package.py           # LLM 分析包生成器
├── db/
│   └── schema.sql               # MySQL DDL
├── data/                        # SQLite 数据库 + 导出文件
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

**SQLite（默认）：** 数据文件在 `data/sporttery.db`，零配置。

**MySQL：** 设置环境变量或修改 `src/config.py`：

```bash
export SPORTTERY_DB_HOST=127.0.0.1
export SPORTTERY_DB_PORT=3306
export SPORTTERY_DB_USER=football
export SPORTTERY_DB_PASSWORD=xxx
export SPORTTERY_DB_NAME=football
```

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
⬜ 6. 定时快照
⬜ 7. SP 变化指标
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
