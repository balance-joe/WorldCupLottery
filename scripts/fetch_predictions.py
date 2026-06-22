"""
抓取预测网站数据，存入 pred_match + pred_score_matrix 表。

Usage:
    python -m scripts.fetch_predictions
    python -m scripts.fetch_predictions --detail
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src import db

PRED_BASE = "http://43.137.46.40:8000"


def clean_team_name(name: str) -> str:
    """Strip emoji flags and special Unicode, keep Chinese name."""
    name = re.sub(r'[\U0001F1E0-\U0001F1FF]', '', name)  # Regional indicators
    name = re.sub(r'[\U0000FE00-\U0000FE0F]', '', name)   # Variation selectors
    name = re.sub(r'\U0000200D', '', name)                  # ZWJ
    return name.strip()

DDL_PRED_MATCH = """
CREATE TABLE IF NOT EXISTS pred_match (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pred_match_id INTEGER NOT NULL UNIQUE,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    match_date TEXT,
    venue TEXT,
    group_name TEXT,
    is_home_venue INTEGER DEFAULT 0,
    actual_score TEXT,
    -- 融合模型
    home_prob REAL,
    draw_prob REAL,
    away_prob REAL,
    -- 加权 Elo
    elo_home_prob REAL,
    elo_draw_prob REAL,
    elo_away_prob REAL,
    -- Dixon-Coles
    dc_home_prob REAL,
    dc_draw_prob REAL,
    dc_away_prob REAL,
    -- 大小球
    over_25_prob REAL,
    under_25_prob REAL,
    expected_goals_home REAL,
    expected_goals_away REAL,
    -- 列表页 top3 比分
    top_scores_json TEXT,
    -- 抓取时间
    fetched_at TEXT DEFAULT (datetime('now','localtime'))
);
"""

DDL_PRED_SCORE_MATRIX = """
CREATE TABLE IF NOT EXISTS pred_score_matrix (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pred_match_id INTEGER NOT NULL,
    home_goals INTEGER NOT NULL,
    away_goals INTEGER NOT NULL,
    probability REAL NOT NULL,
    UNIQUE(pred_match_id, home_goals, away_goals),
    FOREIGN KEY(pred_match_id) REFERENCES pred_match(pred_match_id)
);
"""


def ensure_pred_tables(conn: db.Connection) -> None:
    conn.execute(DDL_PRED_MATCH)
    conn.execute(DDL_PRED_SCORE_MATRIX)
    conn.commit()


def fetch_homepage() -> str | None:
    """Fetch the homepage HTML."""
    try:
        resp = requests.get(PRED_BASE, timeout=15)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"首页抓取失败: {e}")
        return None


def parse_match_links(html: str) -> list[int]:
    """Extract match IDs from homepage links."""
    ids = []
    for m in re.finditer(r'href="/match/(\d+)"', html):
        mid = int(m.group(1))
        if mid not in ids:
            ids.append(mid)
    return ids


def parse_homepage_card(html: str, match_id: int) -> dict | None:
    """Parse one match card from homepage HTML using BeautifulSoup."""
    soup = BeautifulSoup(html, "html.parser")
    card = soup.find("a", href=f"/match/{match_id}")
    if not card:
        return None

    result = {"pred_match_id": match_id}

    # Teams: get text from team spans, ignoring tflag spans
    team_spans = card.select(".teams-row .team")
    if len(team_spans) >= 2:
        result["home_team"] = team_spans[0].get_text(strip=True)
        result["away_team"] = team_spans[1].get_text(strip=True)

    # Score (if finished)
    score_el = card.select_one(".score.final")
    if score_el:
        score_text = score_el.get_text(strip=True).replace(" ", "")
        score_m = re.match(r'(\d+)-(\d+)', score_text)
        if score_m:
            result["actual_score"] = f"{score_m.group(1)}:{score_m.group(2)}"

    # Top scores
    top_scores = []
    for chip in card.select(".chip"):
        score_el = chip.find(string=re.compile(r'\d+-\d+'))
        em = chip.find("em")
        if score_el and em:
            score_text = score_el.strip()
            prob_text = em.get_text(strip=True).rstrip("%")
            top_scores.append({"score": score_text, "prob": float(prob_text)})
    result["top_scores_json"] = top_scores

    # Group
    group_el = card.select_one(".group-tag")
    if group_el:
        result["group_name"] = group_el.get_text(strip=True)

    # City / venue
    city_el = card.select_one(".city")
    if city_el:
        raw = city_el.get_text(strip=True)
        result["is_home_venue"] = 1 if "🏠" in raw else 0
        result["venue"] = re.sub(r'·.*', '', raw).strip()

    # Probability bar
    prob_bar = card.select_one(".prob-bar")
    if prob_bar:
        title = prob_bar.get("title", "")
        prob_m = re.search(r'主胜\s*([\d.]+)%\s*/\s*平\s*([\d.]+)%\s*/\s*客胜\s*([\d.]+)%', title)
        if prob_m:
            result["home_prob"] = float(prob_m.group(1)) / 100
            result["draw_prob"] = float(prob_m.group(2)) / 100
            result["away_prob"] = float(prob_m.group(3)) / 100

    return result


def fetch_detail(match_id: int) -> str | None:
    """Fetch a match detail page."""
    try:
        resp = requests.get(f"{PRED_BASE}/match/{match_id}", timeout=15)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  详情页 {match_id} 抓取失败: {e}")
        return None


def parse_detail(html: str) -> dict:
    """Parse detail page for model probabilities and score matrix."""
    result = {}

    # Team names from title tag: "墨西哥 vs 捷克 — 2026 世界杯预测"
    title_m = re.search(r'<title>(.*?)</title>', html)
    if title_m:
        title = title_m.group(1)
        vs_m = re.match(r'(.+?)\s+vs\s+(.+?)(?:\s*—|\s*｜|\s*$)', title)
        if vs_m:
            result["detail_home"] = clean_team_name(vs_m.group(1).strip())
            result["detail_away"] = clean_team_name(vs_m.group(2).strip())

    # Match date and venue from sub line
    sub_m = re.search(r'<p class="sub">(.*?)</p>', html, re.DOTALL)
    if sub_m:
        sub = sub_m.group(1)
        date_m = re.search(r'(\d{4}-\d{2}-\d{2})', sub)
        if date_m:
            result["match_date"] = date_m.group(1)

    # Dual model table
    compare_m = re.search(r'<table class="compare">(.*?)</table>', html, re.DOTALL)
    if compare_m:
        rows = re.findall(r'<tr>(.*?)</tr>', compare_m.group(1), re.DOTALL)
        for row in rows:
            cells = re.findall(r'<td>(.*?)</td>', row)
            if len(cells) == 4:
                label = cells[0].strip()
                try:
                    h, d, a = float(cells[1].rstrip('%')), float(cells[2].rstrip('%')), float(cells[3].rstrip('%'))
                except ValueError:
                    continue
                if "融合" in label:
                    result["home_prob"] = h / 100
                    result["draw_prob"] = d / 100
                    result["away_prob"] = a / 100
                elif "Elo" in label or "elo" in label:
                    result["elo_home_prob"] = h / 100
                    result["elo_draw_prob"] = d / 100
                    result["elo_away_prob"] = a / 100
                elif "Dixon" in label:
                    result["dc_home_prob"] = h / 100
                    result["dc_draw_prob"] = d / 100
                    result["dc_away_prob"] = a / 100

    # Over/under and expected goals
    note_m = re.search(r'<p class="note">(.*?)</p>', html, re.DOTALL)
    if note_m:
        note = note_m.group(1)
        over_m = re.search(r'>\s*2\.5\s*概率\s*<strong>([\d.]+)%</strong>', note)
        if over_m:
            result["over_25_prob"] = float(over_m.group(1)) / 100
            result["under_25_prob"] = 1 - result["over_25_prob"]
        goals_m = re.search(r'期望进球\s*([\d.]+)\s*:\s*([\d.]+)', note)
        if goals_m:
            result["expected_goals_home"] = float(goals_m.group(1))
            result["expected_goals_away"] = float(goals_m.group(2))

    # Score matrix
    matrix = []
    for cell in re.finditer(r'title="(\d+)-(\d+):\s*([\d.]+)%"', html):
        hg, ag, prob = int(cell.group(1)), int(cell.group(2)), float(cell.group(3)) / 100
        matrix.append({"home_goals": hg, "away_goals": ag, "probability": prob})
    result["score_matrix"] = matrix

    return result


def save_prediction(conn: db.Connection, data: dict) -> bool:
    """Save one match prediction. Returns True if inserted."""
    mid = data["pred_match_id"]

    # Check if already exists
    existing = conn.execute(
        "SELECT id FROM pred_match WHERE pred_match_id = ?", (mid,)
    ).fetchone()
    if existing:
        return False

    import json
    conn.execute(
        """
        INSERT INTO pred_match
            (pred_match_id, home_team, away_team, match_date, venue,
             group_name, is_home_venue, actual_score,
             home_prob, draw_prob, away_prob,
             elo_home_prob, elo_draw_prob, elo_away_prob,
             dc_home_prob, dc_draw_prob, dc_away_prob,
             over_25_prob, under_25_prob,
             expected_goals_home, expected_goals_away,
             top_scores_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            mid,
            data.get("home_team"),
            data.get("away_team"),
            data.get("match_date"),
            data.get("venue"),
            data.get("group_name"),
            data.get("is_home_venue", 0),
            data.get("actual_score"),
            data.get("home_prob"),
            data.get("draw_prob"),
            data.get("away_prob"),
            data.get("elo_home_prob"),
            data.get("elo_draw_prob"),
            data.get("elo_away_prob"),
            data.get("dc_home_prob"),
            data.get("dc_draw_prob"),
            data.get("dc_away_prob"),
            data.get("over_25_prob"),
            data.get("under_25_prob"),
            data.get("expected_goals_home"),
            data.get("expected_goals_away"),
            json.dumps(data.get("top_scores_json", []), ensure_ascii=False),
        ),
    )

    # Score matrix
    for cell in data.get("score_matrix", []):
        conn.execute(
            """
            INSERT OR IGNORE INTO pred_score_matrix
                (pred_match_id, home_goals, away_goals, probability)
            VALUES (?, ?, ?, ?)
            """,
            (mid, cell["home_goals"], cell["away_goals"], cell["probability"]),
        )

    conn.commit()
    return True


def main():
    parser = argparse.ArgumentParser(description="抓取预测网站数据")
    parser.add_argument("--detail", action="store_true", help="逐场详情")
    args = parser.parse_args()

    conn = db.get_connection()
    try:
        ensure_pred_tables(conn)

        print("抓取首页...")
        html = fetch_homepage()
        if not html:
            return

        match_ids = parse_match_links(html)
        print(f"发现 {len(match_ids)} 场比赛")

        inserted = 0
        skipped = 0
        errors = 0

        for i, mid in enumerate(match_ids, 1):
            # Parse homepage card
            card = parse_homepage_card(html, mid)
            if not card:
                print(f"  [{i}/{len(match_ids)}] {mid} 解析失败")
                errors += 1
                continue

            # Fetch detail page
            detail_html = fetch_detail(mid)
            if detail_html:
                detail = parse_detail(detail_html)
                card.update(detail)

            # Detail page has cleaner team names from title tag
            if detail:
                if detail.get("detail_home"):
                    card["home_team"] = detail["detail_home"]
                if detail.get("detail_away"):
                    card["away_team"] = detail["detail_away"]

            if save_prediction(conn, card):
                inserted += 1
                if args.detail:
                    h = card.get("home_team", "?")
                    a = card.get("away_team", "?")
                    hp = card.get("home_prob", 0)
                    dp = card.get("draw_prob", 0)
                    ap = card.get("away_prob", 0)
                    score = card.get("actual_score", "未赛")
                    print(f"  [{i}/{len(match_ids)}] {h} vs {a}  H{hp:.0%} D{dp:.0%} A{ap:.0%}  {score}")
            else:
                skipped += 1

            # Rate limit
            if i < len(match_ids):
                time.sleep(0.2)

        print(f"\n完成: 新增 {inserted}, 跳过 {skipped}, 失败 {errors}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
