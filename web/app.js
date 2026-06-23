async function request(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || res.statusText);
  }
  return res.json();
}

function setText(id, value) {
  document.getElementById(id).textContent = value ?? "-";
}

async function refreshStatus() {
  const status = await request("/api/status");
  const dot = document.getElementById("runDot");
  dot.classList.toggle("running", status.running);
  setText("runState", status.running ? "抓取中" : "未运行");
  setText("backend", `backend: ${status.backend}`);
  setText("command", status.command);
  setText("pid", status.pid);
  setText("startedAt", status.started_at);
  setText("stoppedAt", status.stopped_at);
}

async function refreshDb() {
  const summary = await request("/api/db/summary");
  const cards = document.getElementById("dbCards");
  cards.innerHTML = "";
  Object.entries(summary.counts).forEach(([name, count]) => {
    const el = document.createElement("div");
    el.innerHTML = `<span>${name}</span><strong>${count}</strong>`;
    cards.appendChild(el);
  });
  setText("latestSp", summary.latest_sp_snapshot);
}

async function refreshLogs() {
  const data = await request("/api/fetch/logs");
  document.getElementById("logs").textContent = data.lines.length
    ? data.lines.join("\n")
    : "暂无日志";
}

async function refreshAll() {
  await Promise.all([refreshStatus(), refreshDb(), refreshLogs()]);
}

document.getElementById("refreshBtn").addEventListener("click", refreshAll);

refreshAll();
setInterval(refreshAll, 5000);
