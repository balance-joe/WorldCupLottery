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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("run_api:app", host="127.0.0.1", port=9508, reload=False)
