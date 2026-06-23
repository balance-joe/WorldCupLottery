"""
从原始比赛数据生成结构化LLM分析包。

输出格式专为LLM消费设计：
- 将事实与解释分离
- 对停售比赛强制硬性停止
- 提供变动画像（而不仅是原始变化值）
- 添加时间上下文以进行合理加权
"""

from __future__ import annotations

from src.structure_analysis import analyze_match_windows


def build_market_structure_llm_package(
    match_info: dict,
    sp_history: list[dict],
    *,
    windows: list[str] | tuple[str, ...] | None = None,
    debug: bool = False,
) -> dict:
    """
    构建以市场结构为中心的新LLM输入包。

    LLM应使用此结构，而不是直接从原始SP行推断趋势。
    """
    result = analyze_match_windows(
        match_info,
        sp_history,
        windows=tuple(windows) if windows else ("open_to_latest", "last_24h", "last_6h"),
        include_debug=debug,
    )
    return result["llm_input"]


def build_llm_package(
    match_info: dict,
    sp_history: list[dict],
    match_detail: dict | None = None,
) -> dict:
    """新市场结构中心包的兼容性包装器。"""
    del match_detail
    return build_market_structure_llm_package(match_info, sp_history)


# ── 旧版信号分类器（保留用于测试覆盖）─────────────────────────────────────
# 生产环境信号逻辑位于 structure_analysis.py + agent_report_schema.py。
# 此函数保留是因为 test_llm_signals_crs_hafu.py 通过它测试
# CRS/HAFU 信号分类功能。


def _classify_signals(markets, movement, team_form, historical, status_control) -> dict:  # pragma: deprecated
    """将数据分类为正面、负面、结构性和不确定性信号。"""
    positive = []
    negative = []
    structure = []
    uncertainty = []

    # ── 状态 ───────────────────────────────────────────────────────────────
    if not status_control.get("tradable"):
        uncertainty.append(f"比赛当前{status_control.get('match_status_name', '未知状态')}，不能形成投注动作")

    # ── 胜平负变动 ─────────────────────────────────────────────────────────
    had = markets.get("had", {})
    if had:
        opts = {o["code"]: o for o in had.get("options", [])}
        h = opts.get("H", {})
        if h.get("sp_change") and h["sp_change"] < 0:
            positive.append(f"胜平负主胜SP下降{abs(h['sp_change']):.2f}，方向增强")
        if h.get("prob_change") and h["prob_change"] > 0.02:
            positive.append(f"主胜归一化概率提升{h['prob_change']:.1%}")

    # ── 让球胜平负变动 ─────────────────────────────────────────────────────
    hhad = markets.get("hhad", {})
    if hhad:
        opts = {o["code"]: o for o in hhad.get("options", [])}
        h = opts.get("H", {})
        if h.get("sp_change") and h["sp_change"] < 0:
            positive.append(f"让球让胜SP下降{abs(h['sp_change']):.2f}，赢球幅度预期增强")
        # 检查让球与胜平负是否一致
        had_h = {o["code"]: o for o in had.get("options", [])}.get("H", {})
        if h.get("sp_change", 0) < 0 and had_h.get("sp_change", 0) < 0:
            positive.append("胜平负与让球胜平负方向一致")
        # 检查让胜概率是否不高
        if h.get("current_prob") and h["current_prob"] < 0.45:
            negative.append(f"让胜归一化概率仅{h['current_prob']:.1%}，未达到强确定性水平")

    # ── 总进球 ─────────────────────────────────────────────────────────────
    ttg = markets.get("ttg", {})
    if ttg:
        low = ttg.get("low_price_options", [])
        if low:
            opts = {o["code"]: o for o in ttg.get("options", [])}
            total_prob = sum((opts.get(c, {}).get("current_prob") or 0) for c in low)
            if total_prob > 0.4:
                structure.append(f"总进球低赔集中在{'/'.join(low)}球({total_prob:.1%})，偏向中低比分结构")

    # ── 比分 ───────────────────────────────────────────────────────────────
    crs = markets.get("crs", {})
    if crs:
        opts = crs.get("options", [])

        # 1. 低赔比分集中度
        opts_with_prob = [(o["code"], o.get("current_prob") or 0) for o in opts]
        opts_with_prob.sort(key=lambda x: -x[1])
        top_codes = []
        cumulative = 0
        for code, prob in opts_with_prob[:5]:
            top_codes.append(code)
            cumulative += prob
            if cumulative > 0.4:
                break
        if cumulative > 0.4 and len(top_codes) >= 3:
            name_map = {o["code"]: o.get("option_name", o["code"]) for o in opts}
            names = [name_map.get(c, c) for c in top_codes]
            structure.append(f"比分低赔集中在{'/'.join(names)}({cumulative:.1%})，偏向特定比分结构")

        # 2. 主胜其他 vs 客胜其他
        opts_dict = {o["code"]: o for o in opts}
        sh = opts_dict.get("s-1sh", {})
        sa = opts_dict.get("s-1sa", {})
        sh_prob = sh.get("current_prob") or 0
        sa_prob = sa.get("current_prob") or 0
        if sh_prob > 0 and sa_prob > 0:
            if sh_prob > sa_prob * 1.5:
                positive.append("主胜其他概率高于客胜其他，大比分偏向主队")
            elif sa_prob > sh_prob * 1.5:
                negative.append("客胜其他概率高于主胜其他，大比分偏向客队")

        # 3. 具体比分 SP 变化
        sp_changes = []
        for o in opts:
            if o.get("sp_change") and o.get("open_sp"):
                pct = abs(o["sp_change"]) / o["open_sp"]
                if pct > 0.10:
                    sp_changes.append((o["code"], o.get("option_name", o["code"]), o["sp_change"], pct))
        if sp_changes:
            sp_changes.sort(key=lambda x: -x[3])
            for code, name, change, pct in sp_changes[:2]:
                positive.append(f"比分 {name} SP 下降{pct:.1%}，市场预期增强")

    # ── 半全场 ─────────────────────────────────────────────────────────────
    hafu = markets.get("hafu", {})
    if hafu:
        opts = {o["code"]: o for o in hafu.get("options", [])}

        # 1. 主/主（hh）概率
        hh = opts.get("hh", {})
        hh_prob = hh.get("current_prob") or 0
        if hh_prob > 0.25:
            positive.append(f"半全场主/主概率{hh_prob:.1%}，支持主队全程领先")

        # 2. 半场平局结构
        dh_prob = opts.get("dh", {}).get("current_prob") or 0
        dd_prob = opts.get("dd", {}).get("current_prob") or 0
        da_prob = opts.get("da", {}).get("current_prob") or 0
        half_draw = dh_prob + dd_prob + da_prob
        if half_draw > 0.40:
            structure.append(f"半场平局概率{half_draw:.1%}，比赛可能前半场胶着")

        # 3. 全场主胜结构
        ah_prob = opts.get("ah", {}).get("current_prob") or 0
        full_home = hh_prob + dh_prob + ah_prob
        if full_home > 0.50:
            positive.append(f"全场主胜概率{full_home:.1%}，主队获胜预期较强")

        # 4. hafu 与 had 方向一致性
        had_h = {o["code"]: o for o in had.get("options", [])}.get("H", {})
        if hh_prob > 0.25 and had_h.get("sp_change", 0) < 0:
            positive.append("半全场与胜平负方向一致，主队优势明显")

    # ── 球队状态 ───────────────────────────────────────────────────────────
    home_form = team_form.get("home", {})
    away_form = team_form.get("away", {})
    try:
        if home_form.get("win_pct") and int(str(home_form["win_pct"]).replace("%", "")) >= 60:
            positive.append(f"主队近5场胜率{home_form['win_pct']}")
    except (ValueError, TypeError):
        pass
    try:
        if away_form.get("loss_pct") and int(str(away_form["loss_pct"]).replace("%", "")) >= 40:
            positive.append(f"客队近5场败率{away_form['loss_pct']}")
    except (ValueError, TypeError):
        pass

    feature = team_form.get("feature", {})
    try:
        if feature.get("home_loss_avg") and float(feature["home_loss_avg"]) < 0.5:
            positive.append(f"主队近10场场均失球{feature['home_loss_avg']}，防守突出")
    except (ValueError, TypeError):
        pass
    try:
        if feature.get("away_loss_avg") and float(feature["away_loss_avg"]) > 1.0:
            positive.append(f"客队近10场场均失球{feature['away_loss_avg']}，防守薄弱")
    except (ValueError, TypeError):
        pass

    # ── 历史交锋 ───────────────────────────────────────────────────────────
    if historical.get("h2h_count", 0) <= 1:
        uncertainty.append(f"历史交锋仅{historical.get('h2h_count', 0)}场，参考价值低")
    if historical.get("same_odds_count", 0) == 0:
        uncertainty.append("同奖历史样本为0，无法用同奖回查验证")

    # ── 变动波动性 ─────────────────────────────────────────────────────────
    for key, prof in movement.items():
        if prof.get("volatility") == "high":
            uncertainty.append(f"{key} SP波动较大({prof.get('pattern', '')})，需关注是否为临场异动")

    return {
        "positive_signals": positive,
        "negative_signals": negative,
        "structure_signals": structure,
        "uncertainty_flags": uncertainty,
    }
