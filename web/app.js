const state = {
  date: "",
  priority: "",
  search: "",
  matches: [],
  selectedMatchId: null,
  selectedDetail: null,
  currentPlayType: "had",
};

const PLAY_LABELS = {
  had: "胜平负",
  hhad: "让球胜平负",
  ttg: "总进球",
};

const PLAY_COLORS = ["#285c45", "#9f4a3d", "#9d7441", "#315f78", "#a65f31", "#5f5479", "#3f6d5c"];

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
    },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  const contentType = response.headers.get("content-type") || "";
  return contentType.includes("application/json") ? response.json() : response.text();
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) {
    el.textContent = value ?? "-";
  }
}

function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "-";
  }
  return new Intl.NumberFormat("zh-CN").format(Number(value));
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function formatDateTime(value) {
  if (!value) {
    return "-";
  }
  return String(value).replace("T", " ").slice(0, 16);
}

function priorityBadge(priority) {
  const safe = priority || "D";
  return `<span class="priority-badge priority-${safe}">${escapeHtml(safe)}</span>`;
}

function gateText(match) {
  if (match.gate_allowed) {
    return "通过";
  }
  return `拦截(${escapeHtml(match.gate_priority || "D")})`;
}

function buildMetricCards(summary, matches, tickets) {
  const cards = [
    {
      label: "比赛总数",
      value: matches.total,
      note: `日期 ${summary.activeDate}`,
    },
    {
      label: "SP 快照",
      value: summary.counts.sporttery_sp_snapshot,
      note: `最新 ${summary.latest_sp_snapshot || "-"}`,
    },
    {
      label: "原始快照",
      value: summary.counts.sporttery_raw_snapshot,
      note: `后端 ${summary.backend}`,
    },
    {
      label: "票据台账",
      value: tickets.total,
      note: `推荐表 ${summary.counts.daily_recommendation}`,
    },
  ];
  document.getElementById("metricCards").innerHTML = cards.map((card) => `
    <div class="metric-card">
      <span>${escapeHtml(card.label)}</span>
      <strong>${formatNumber(card.value)}</strong>
      <small>${escapeHtml(card.note)}</small>
    </div>
  `).join("");
}

function applyStatus(status) {
  const dot = document.getElementById("runDot");
  const badge = document.getElementById("fetchBadge");
  const running = Boolean(status.running);
  dot.classList.toggle("running", running);
  badge.classList.toggle("running", running);
  badge.classList.toggle("idle", !running);
  badge.textContent = running ? "running" : "idle";
  setText("runState", running ? "后台同步进行中" : "后台同步未运行");
  setText("backend", `backend: ${status.backend}`);
  setText("pid", status.pid || "-");
  setText("startedAt", formatDateTime(status.started_at));
  setText("stoppedAt", formatDateTime(status.stopped_at));
}

function renderMatches() {
  const body = document.getElementById("matchesBody");
  const query = state.search.trim().toLowerCase();
  const filtered = state.matches.filter((match) => {
    if (state.priority && match.priority !== state.priority) {
      return false;
    }
    if (!query) {
      return true;
    }
    const haystack = [
      match.match_num,
      match.league_name,
      match.home_team,
      match.away_team,
      match.main_pick,
      match.score_pick,
    ].join(" ").toLowerCase();
    return haystack.includes(query);
  });

  if (!filtered.length) {
    body.innerHTML = '<tr><td colspan="9" class="empty-cell">没有符合条件的比赛</td></tr>';
    return;
  }

  body.innerHTML = filtered.map((match) => `
    <tr class="match-row ${state.selectedMatchId === match.match_id ? "selected" : ""}" data-match-id="${escapeHtml(match.match_id)}">
      <td>${priorityBadge(match.priority)}</td>
      <td>
        <strong>${escapeHtml(match.match_num || "-")}</strong>
        <span class="subtle-line">${escapeHtml(match.match_status || "-")}</span>
      </td>
      <td>
        <span>${escapeHtml(match.league_name || "-")}</span>
        <span class="team-line">${escapeHtml(match.home_team || "-")} vs ${escapeHtml(match.away_team || "-")}</span>
      </td>
      <td>${escapeHtml(formatDateTime(match.match_time))}</td>
      <td>${escapeHtml(formatDateTime(match.latest_snapshot_time))}</td>
      <td>${escapeHtml(match.main_play ? `${match.main_play}:${match.main_pick} @ ${match.main_sp ?? "-"}` : "不买")}</td>
      <td>${escapeHtml(match.score_pick ? `${match.score_pick}${match.score_sp ? ` @ ${match.score_sp}` : ""}` : "-")}</td>
      <td>${escapeHtml(match.goal_range || "-")}</td>
      <td>${escapeHtml(gateText(match))}</td>
    </tr>
  `).join("");

  body.querySelectorAll(".match-row").forEach((row) => {
    row.addEventListener("click", () => {
      loadMatchDetail(row.dataset.matchId);
    });
  });
}

function renderLogs(lines) {
  document.getElementById("logs").textContent = lines.length ? lines.join("\n") : "暂无日志";
}

function renderTickets(tickets) {
  setText("ticketTotal", `${tickets.length} 张`);
  const host = document.getElementById("ticketList");
  if (!tickets.length) {
    host.innerHTML = '<div class="ticket-empty">暂无票据</div>';
    return;
  }
  host.innerHTML = tickets.slice(0, 8).map((ticket) => `
    <article class="ticket-card">
      <header>
        <strong>${escapeHtml(ticket.ticket_label || `Ticket #${ticket.id}`)}</strong>
        <span class="priority-badge priority-${ticket.ticket_status === "settled" ? "A" : "C"}">${escapeHtml(ticket.ticket_status || "pending")}</span>
      </header>
      <p>类型 ${escapeHtml(ticket.pass_type || "-")} · 来源 ${escapeHtml(ticket.source_type || "-")}</p>
      <p>下注 ${escapeHtml(String(ticket.stake_amount ?? "-"))} · 下单 ${escapeHtml(formatDateTime(ticket.placed_at))}</p>
    </article>
  `).join("");
}

function renderRiskList(risks) {
  const host = document.getElementById("riskList");
  if (!risks?.length) {
    host.innerHTML = '<li class="risk-pill">当前没有显著风险标记</li>';
    return;
  }
  host.innerHTML = risks.map((risk) => `
    <li class="risk-pill">${escapeHtml(risk.code)} · ${escapeHtml(risk.message)}</li>
  `).join("");
}

function renderSuggestions(suggestions) {
  const host = document.getElementById("suggestionList");
  if (!suggestions?.length) {
    host.innerHTML = '<article class="suggestion-card"><p>当前没有可展示的建议输出。</p></article>';
    return;
  }
  host.innerHTML = suggestions.map((suggestion) => `
    <article class="suggestion-card">
      <header>
        <strong>${escapeHtml(PLAY_LABELS[suggestion.play_type] || suggestion.play_type)} · ${escapeHtml((suggestion.selections || []).join(" / ") || "-")}</strong>
        <span class="gate-chip ${suggestion.gate_passed ? "pass" : ""}">${suggestion.gate_passed ? "门禁通过" : "仅观察"}</span>
      </header>
      <p>${escapeHtml(suggestion.reason || "-")}</p>
      <p>表达 ${escapeHtml(suggestion.market_expression || "-")} · 置信 ${escapeHtml(suggestion.confidence || "-")}</p>
    </article>
  `).join("");
}

function drawTrendChart(series) {
  const chart = document.getElementById("trendChart");
  const legend = document.getElementById("trendLegend");
  const width = 420;
  const height = 180;
  const padding = 18;
  const entries = Object.entries(series || {}).filter(([, points]) => Array.isArray(points) && points.length);

  if (!entries.length) {
    chart.innerHTML = `<text x="${width / 2}" y="${height / 2}" text-anchor="middle" fill="#6f7268" font-size="13">暂无走势数据</text>`;
    legend.innerHTML = "";
    return;
  }

  const values = entries.flatMap(([, points]) => points.map((point) => Number(point.sp)));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const longest = Math.max(...entries.map(([, points]) => points.length));

  const gridLines = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
    const y = padding + (height - padding * 2) * ratio;
    return `<line x1="${padding}" y1="${y}" x2="${width - padding}" y2="${y}" stroke="rgba(42,57,41,0.1)" stroke-width="1" />`;
  }).join("");

  const paths = entries.map(([code, points], index) => {
    const color = PLAY_COLORS[index % PLAY_COLORS.length];
    const d = points.map((point, pointIndex) => {
      const x = longest === 1
        ? width / 2
        : padding + ((width - padding * 2) * pointIndex) / Math.max(points.length - 1, 1);
      const y = height - padding - ((Number(point.sp) - min) / range) * (height - padding * 2);
      return `${pointIndex === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    }).join(" ");
    const last = points[points.length - 1];
    const lastX = longest === 1
      ? width / 2
      : padding + ((width - padding * 2) * (points.length - 1)) / Math.max(points.length - 1, 1);
    const lastY = height - padding - ((Number(last.sp) - min) / range) * (height - padding * 2);
    return {
      svg: `<path d="${d}" fill="none" stroke="${color}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" />
            <circle cx="${lastX.toFixed(2)}" cy="${lastY.toFixed(2)}" r="3.4" fill="${color}" />`,
      legend: `<span class="legend-item"><span class="legend-swatch" style="background:${color}"></span>${escapeHtml(code)} ${escapeHtml(String(last.sp))}</span>`,
    };
  });

  chart.innerHTML = `
    ${gridLines}
    <line x1="${padding}" y1="${height - padding}" x2="${width - padding}" y2="${height - padding}" stroke="rgba(42,57,41,0.18)" stroke-width="1.2" />
    ${paths.map((item) => item.svg).join("")}
  `;
  legend.innerHTML = paths.map((item) => item.legend).join("");
}

async function refreshMatchDetailChart(matchId, playType = state.currentPlayType) {
  const data = await request(`/api/matches/${encodeURIComponent(matchId)}/sp-history?play_type=${encodeURIComponent(playType)}`);
  drawTrendChart(data.series);
}

function applyDetail(detail) {
  state.selectedDetail = detail;
  document.getElementById("detailEmpty").classList.add("hidden");
  document.getElementById("detailContent").classList.remove("hidden");

  const match = detail.match || {};
  const structure = detail.recommendation?.structure || {};
  const gate = detail.recommendation?.gate || {};
  const suggestions = detail.recommendation?.suggestions || [];

  const priority = structure.research_priority || gate.priority || "D";
  const badge = document.getElementById("detailPriority");
  badge.className = `priority-badge priority-${priority}`;
  badge.textContent = priority;

  setText("detailMatchNum", match.match_num || match.match_id || "-");
  setText("detailTeams", `${match.home_team || "-"} vs ${match.away_team || "-"}`);
  setText("detailMeta", `${match.league_name || "-"} · ${formatDateTime(match.match_time)} · ${match.match_status || "-"}`);
  setText("detailScore", match.result_90 ? `${match.home_score ?? "-"}:${match.away_score ?? "-"} (${match.result_90})` : `${match.home_score ?? "-"}:${match.away_score ?? "-"}`);
  setText("marketExpression", structure.main_market_expression || "-");
  setText("gateResult", gate.allowed ? `通过 · ${gate.allowed_plays?.join("/") || "-"}` : `拦截 · ${gate.reasons?.join(", ") || "-"}`);

  renderRiskList(structure.risk_flags || []);
  renderSuggestions(suggestions);
}

async function loadMatchDetail(matchId) {
  state.selectedMatchId = matchId;
  renderMatches();
  const detail = await request(`/api/matches/${encodeURIComponent(matchId)}`);
  applyDetail(detail);
  await refreshMatchDetailChart(matchId, state.currentPlayType);
}

async function refreshDashboard() {
  const date = state.date || new Date().toISOString().slice(0, 10);
  setText("activeDate", date);
  const [status, summary, matches, logs, tickets] = await Promise.all([
    request("/api/status"),
    request("/api/db/summary"),
    request(`/api/matches?date=${encodeURIComponent(date)}`),
    request("/api/fetch/logs"),
    request("/api/tickets"),
  ]);

  summary.activeDate = summary.latest_sp_snapshot || date;
  state.matches = matches.matches || [];
  applyStatus(status);
  buildMetricCards(summary, matches, tickets);
  renderMatches();
  renderLogs(logs.lines || []);
  renderTickets(tickets.tickets || []);
  setText("globalSyncTop", `最后同步时间：${formatDateTime(summary.latest_sp_snapshot)}`);
  setText("globalSyncInline", formatDateTime(summary.latest_sp_snapshot));
  setText("globalSyncBottom", formatDateTime(summary.latest_sp_snapshot));
  setText("lastUpdated", `更新于 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`);

  if (!state.selectedMatchId && state.matches.length) {
    await loadMatchDetail(state.matches[0].match_id);
  } else if (state.selectedMatchId) {
    const stillExists = state.matches.some((match) => match.match_id === state.selectedMatchId);
    if (stillExists) {
      await loadMatchDetail(state.selectedMatchId);
    }
  }
}

function bindEvents() {
  const today = new Date().toISOString().slice(0, 10);
  state.date = today;
  document.getElementById("dateInput").value = today;

  document.getElementById("refreshBtn").addEventListener("click", () => refreshDashboard().catch(showError));

  document.getElementById("dateInput").addEventListener("change", (event) => {
    state.date = event.target.value;
    refreshDashboard().catch(showError);
  });

  document.getElementById("priorityFilter").addEventListener("change", (event) => {
    state.priority = event.target.value;
    renderMatches();
  });

  document.getElementById("searchInput").addEventListener("input", (event) => {
    state.search = event.target.value;
    renderMatches();
  });

  document.querySelectorAll(".tab-btn").forEach((button) => {
    button.addEventListener("click", async () => {
      document.querySelectorAll(".tab-btn").forEach((tab) => tab.classList.remove("active"));
      button.classList.add("active");
      state.currentPlayType = button.dataset.play;
      if (state.selectedMatchId) {
        try {
          await refreshMatchDetailChart(state.selectedMatchId, state.currentPlayType);
        } catch (error) {
          showError(error);
        }
      }
    });
  });
}

function showError(error) {
  console.error(error);
  const message = error instanceof Error ? error.message : String(error);
  document.getElementById("logs").textContent = `[UI error] ${message}\n\n` + document.getElementById("logs").textContent;
}

bindEvents();
refreshDashboard().catch(showError);
setInterval(() => {
  refreshDashboard().catch(showError);
}, 15000);
