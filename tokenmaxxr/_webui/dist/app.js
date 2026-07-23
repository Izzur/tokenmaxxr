// tokenmaxxr WebUI — vanilla JS, no build step.
const $ = (sel) => document.querySelector(sel);
const cards = $("#cards");
const providerSel = $("#provider");
const windowSel = $("#window");
const chart = $("#chart");
const historySec = $("#history");
const auto = $("#auto");
let timer = null;

async function jget(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}
async function jpost(url) {
  const r = await fetch(url, { method: "POST" });
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

function fmtPct(n) {
  return `${Math.max(0, Math.min(100, n || 0))}%`;
}
function fmtReset(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    const diff = d - Date.now();
    if (diff < 0) return "now";
    const m = Math.floor(diff / 60000);
    if (m < 60) return `${m}m`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h`;
    return `${Math.floor(h / 24)}d`;
  } catch { return ""; }
}

function renderCard(p) {
  const div = document.createElement("div");
  div.className = "card";
  const head = document.createElement("h2");
  head.textContent = p.name;
  const status = document.createElement("span");
  status.className = `status ${p.status}`;
  status.textContent = p.status;
  head.appendChild(status);
  div.appendChild(head);
  if (p.error) {
    const e = document.createElement("div");
    e.className = "status error";
    e.textContent = p.error;
    div.appendChild(e);
  }
  for (const w of p.windows || []) {
    const row = document.createElement("div");
    row.className = "window";
    const label = document.createElement("div");
    label.className = "row";
    const pct = w.pct_used || 0;
    label.innerHTML = `<span>${w.label}</span><span>${fmtPct(pct)} · ${fmtReset(w.reset_at)}</span>`;
    const bar = document.createElement("div");
    const cls = pct >= 90 ? "err" : pct >= 70 ? "warn" : "";
    bar.className = `bar ${cls}`;
    bar.innerHTML = `<span style="width:${pct}%"></span>`;
    row.appendChild(label);
    row.appendChild(bar);
    div.appendChild(row);
  }
  return div;
}

async function loadUsage() {
  const doc = await jget("/api/usage");
  cards.innerHTML = "";
  for (const p of doc.providers) cards.appendChild(renderCard(p));
  // Populate provider filter
  const existing = new Set([...providerSel.options].map(o => o.value));
  for (const p of doc.providers) {
    if (!existing.has(p.id)) {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.name;
      providerSel.appendChild(opt);
    }
  }
  historySec.hidden = false;
  await loadHistory();
}

async function loadHistory() {
  const params = new URLSearchParams();
  if (providerSel.value) params.set("provider", providerSel.value);
  if (windowSel.value) params.set("window", windowSel.value);
  const rows = await jget(`/api/history?${params}`);
  drawChart(rows);
}

function drawChart(rows) {
  const ctx = chart.getContext("2d");
  ctx.clearRect(0, 0, chart.width, chart.height);
  if (!rows.length) {
    ctx.fillStyle = "#888";
    ctx.fillText("no history yet", 12, 24);
    return;
  }
  // Group by window
  const byWin = new Map();
  for (const r of rows) {
    if (!byWin.has(r.window)) byWin.set(r.window, []);
    byWin.get(r.window).push(r);
  }
  const padX = 40, padY = 10;
  const w = chart.width - padX * 2;
  const h = chart.height - padY * 2;
  ctx.strokeStyle = "#888";
  ctx.beginPath();
  ctx.moveTo(padX, padY + h);
  ctx.lineTo(padX + w, padY + h);
  ctx.stroke();
  const colors = { "5h": "#059669", "7d": "#2563eb", "30d": "#d97706" };
  for (const [win, pts] of byWin) {
    pts.sort((a, b) => a.ts.localeCompare(b.ts));
    ctx.strokeStyle = colors[win] || "#888";
    ctx.beginPath();
    pts.forEach((p, i) => {
      const x = padX + (i / Math.max(1, pts.length - 1)) * w;
      const y = padY + h - (p.pct_used / 100) * h;
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    });
    ctx.stroke();
    // legend
    ctx.fillStyle = colors[win] || "#888";
    ctx.fillText(win, padX + ([...byWin.keys()].indexOf(win)) * 30, padY + 12);
  }
}

$("#refresh").addEventListener("click", async () => {
  $("#refresh").textContent = "refreshing…";
  try {
    await jpost("/api/refresh");
    await loadUsage();
  } finally {
    $("#refresh").textContent = "refresh now";
  }
});
providerSel.addEventListener("change", loadHistory);
windowSel.addEventListener("change", loadHistory);
auto.addEventListener("change", () => {
  if (auto.checked) {
    timer = setInterval(loadUsage, 60_000);
  } else if (timer) {
    clearInterval(timer);
    timer = null;
  }
});

loadUsage().catch((e) => {
  cards.textContent = `Error: ${e.message}`;
});
