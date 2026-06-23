"""竞彩足球数据管道的 FastAPI 控制面板。"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from src import db


ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
FETCH_COMMAND = [
    sys.executable,
    "-m",
    "scripts.fetch_sporttery",
    "--mode",
    "today",
    "--interval-seconds",
    "300",
    "--repeat",
    "0",
]

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    controller.start_fetch()
    yield


app = FastAPI(title="Football SP Control API", lifespan=_lifespan)
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


class ProcessController:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._started_at: str | None = None
        self._stopped_at: str | None = None
        self._logs: deque[str] = deque(maxlen=1000)

    def start_fetch(self) -> dict[str, Any]:
        with self._lock:
            if self._process and self._process.poll() is None:
                return self.status()
            env = os.environ.copy()
            env.setdefault("PYTHONIOENCODING", "utf-8")
            self._logs.clear()
            self._process = subprocess.Popen(
                FETCH_COMMAND,
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                bufsize=1,
            )
            self._started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._stopped_at = None
            threading.Thread(target=self._read_logs, daemon=True).start()
            return self.status()

    def status(self) -> dict[str, Any]:
        process = self._process
        running = bool(process and process.poll() is None)
        return {
            "running": running,
            "pid": process.pid if process else None,
            "return_code": None if running or not process else process.poll(),
            "started_at": self._started_at,
            "stopped_at": self._stopped_at,
            "command": " ".join(FETCH_COMMAND),
            "backend": db._db_backend(),
        }

    def logs(self) -> dict[str, Any]:
        return {"lines": list(self._logs)}

    def _read_logs(self) -> None:
        process = self._process
        if not process or process.stdout is None:
            return
        try:
            for line in process.stdout:
                self._logs.append(line.rstrip("\n"))
        except Exception:
            pass
        process.wait()
        if self._stopped_at is None:
            self._stopped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


controller = ProcessController()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (WEB_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/status")
def status() -> dict[str, Any]:
    return controller.status()


@app.get("/api/fetch/logs")
def fetch_logs() -> dict[str, Any]:
    return controller.logs()


_ALLOWED_TABLES = frozenset({
    "sporttery_match",
    "sporttery_sp_snapshot",
    "sporttery_raw_snapshot",
    "sporttery_api_error",
    "daily_recommendation",
    "betting_ticket",
    "betting_ticket_selection",
})


@app.get("/api/db/summary")
def db_summary() -> dict[str, Any]:
    try:
        conn = db.get_connection()
        db.ensure_tables(conn)
        counts = {}
        for table in _ALLOWED_TABLES:
            # 表名来自硬编码白名单，可防止注入攻击。
            counts[table] = conn.execute(f"SELECT COUNT(1) FROM {table}").fetchone()[0]
        latest_sp = conn.execute(
            "SELECT MAX(snapshot_time) FROM sporttery_sp_snapshot"
        ).fetchone()[0]
        conn.close()
    except Exception:
        raise HTTPException(status_code=500, detail="Database query failed") from None
    return {
        "backend": db._db_backend(),
        "counts": counts,
        "latest_sp_snapshot": str(latest_sp) if latest_sp else None,
    }


@app.get("/api/matches")
def api_matches(date: str | None = None) -> dict[str, Any]:
    """返回指定日期的比赛列表（含 SP 分析摘要）。"""
    from datetime import datetime as _dt
    from src.recommendation import build_match_recommendation, latest_option_sp
    from src.market_structure import PRIORITY_RANK

    match_date = date or _dt.now().strftime("%Y-%m-%d")
    try:
        conn = db.get_connection()
        db.ensure_tables(conn)
        matches = db.fetch_matches_for_analysis(conn, match_date=match_date)
        results = []
        for match in matches:
            match_id = str(match.get("match_id"))
            sp_history = db.fetch_all_sp_history(conn, [match_id])
            try:
                recommendation = build_match_recommendation(
                    match, sp_history, window="open_to_latest",
                    now_time=_dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
                # 主推
                main_play = main_pick = main_sp = None
                for s in getattr(recommendation, "suggestions", ()):
                    if s.play_type in {"had", "hhad"} and len(s.selections) == 1:
                        main_play, main_pick = s.play_type, s.selections[0]
                        for opt in (recommendation.hhad_trend.options if s.play_type == "hhad" else recommendation.had_trend.options):
                            if opt.option_code == main_pick:
                                main_sp = opt.sp_end
                                break
                        break
                # 比分
                score_pick = score_sp = None
                if recommendation.candidates.crs_options:
                    score_pick = recommendation.candidates.crs_options[0]
                    score_sp = latest_option_sp(sp_history, "crs", score_pick)
                # 进球范围
                goal_range = "/".join(recommendation.candidates.ttg_options) if recommendation.candidates.ttg_options else None

                priority = recommendation.structure.research_priority
                gate = recommendation.gate
            except Exception:
                main_play = main_pick = main_sp = score_pick = score_sp = goal_range = None
                priority = "D"
                gate = None

            results.append({
                "match_id": match_id,
                "match_num": match.get("match_num") or "",
                "league_name": match.get("league_name") or "",
                "home_team": match.get("home_team_name") or "",
                "away_team": match.get("away_team_name") or "",
                "match_time": match.get("match_time") or "",
                "match_status": match.get("match_status") or "",
                "home_score": match.get("home_score_90"),
                "away_score": match.get("away_score_90"),
                "result_90": match.get("result_90") or "",
                "priority": priority,
                "main_play": main_play,
                "main_pick": main_pick,
                "main_sp": main_sp,
                "score_pick": score_pick,
                "score_sp": score_sp,
                "goal_range": goal_range,
                "gate_allowed": gate.allowed if gate else False,
                "gate_priority": gate.priority if gate else "D",
            })
        # 按优先级排序
        priority_order = {"A": 0, "B": 1, "C": 2, "D": 3}
        results.sort(key=lambda r: (priority_order.get(r["priority"], 9), r.get("match_time") or ""))
        conn.close()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None
    return {"date": match_date, "matches": results, "total": len(results)}


@app.get("/api/matches/{match_id}")
def api_match_detail(match_id: str) -> dict[str, Any]:
    """返回单场比赛详情（含 SP 历史 + 分析）。"""
    from datetime import datetime as _dt
    from src.structure_analysis import analyze_match_windows
    from src.recommendation import build_match_recommendation

    try:
        conn = db.get_connection()
        db.ensure_tables(conn)
        match = db.fetch_match(conn, match_id)
        if not match:
            raise HTTPException(status_code=404, detail="Match not found")
        sp_history = db.fetch_all_sp_history(conn, [match_id])
        analysis = analyze_match_windows(match, sp_history, windows=("open_to_latest",), include_debug=True)
        recommendation = build_match_recommendation(
            match, sp_history, window="open_to_latest",
            now_time=_dt.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        conn.close()
        return {
            "match": {
                "match_id": match_id,
                "match_num": match.get("match_num") or "",
                "league_name": match.get("league_name") or "",
                "home_team": match.get("home_team_name") or "",
                "away_team": match.get("away_team_name") or "",
                "match_time": match.get("match_time") or "",
                "match_status": match.get("match_status") or "",
                "home_score": match.get("home_score_90"),
                "away_score": match.get("away_score_90"),
                "result_90": match.get("result_90") or "",
            },
            "analysis": analysis,
            "recommendation": recommendation.to_dict(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None


@app.get("/api/matches/{match_id}/sp-history")
def api_sp_history(match_id: str, play_type: str = "had") -> dict[str, Any]:
    """返回指定比赛的 SP 历史（用于图表渲染）。"""
    try:
        conn = db.get_connection()
        db.ensure_tables(conn)
        records = db.fetch_sp_history(conn, [match_id], play_type=play_type)
        conn.close()
        # 按 option_code 分组
        series: dict[str, list] = {}
        for r in records:
            code = str(r.get("option_code", ""))
            series.setdefault(code, []).append({
                "time": str(r.get("snapshot_time", "")),
                "sp": float(r.get("sp_value", 0)),
                "prob": float(r.get("implied_prob_norm") or 0),
            })
        return {"match_id": match_id, "play_type": play_type, "series": series}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None


@app.get("/api/tickets")
def api_tickets(bet_group: str | None = None) -> dict[str, Any]:
    """返回投注票列表。"""
    try:
        conn = db.get_connection()
        db.ensure_tables(conn)
        tickets = db.fetch_betting_tickets(conn, bet_group=bet_group)
        conn.close()
        return {"tickets": tickets, "total": len(tickets)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("run_api:app", host="127.0.0.1", port=9508, reload=False)
