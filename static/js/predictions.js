const POLL_INTERVAL_MS = 5000;
const THEME_STORAGE_KEY = "presenceDashboardTheme";

const appState = {
  history: [],
  minutes: 3,
  polling: false,
  resizeTimer: null
};

const connectionState = document.getElementById("connectionState");
const themeToggle = document.getElementById("themeToggle");
const predictionHeadline = document.getElementById("predictionHeadline");
const predictionMeta = document.getElementById("predictionMeta");
const predictedNodeCount = document.getElementById("predictedNodeCount");
const occupiedCount = document.getElementById("occupiedCount");
const emptyCount = document.getElementById("emptyCount");
const lastUpdate = document.getElementById("lastUpdate");
const modelWindowInfo = document.getElementById("modelWindowInfo");
const roomState = document.getElementById("roomState");
const roomConfidence = document.getElementById("roomConfidence");
const roomWindowEnd = document.getElementById("roomWindowEnd");
const roomAggregation = document.getElementById("roomAggregation");
const modelPath = document.getElementById("modelPath");
const minSamples = document.getElementById("minSamples");
const sampleLimit = document.getElementById("sampleLimit");
const labelNote = document.getElementById("labelNote");
const skippedNodes = document.getElementById("skippedNodes");
const predictionChart = document.getElementById("predictionChart");
const predictionCtx = predictionChart.getContext("2d");
const predictionRangeButtons = document.getElementById("predictionRangeButtons");

function getThemeColor(name, fallback) {
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();

  return value || fallback;
}

function applyTheme(theme) {
  const nextTheme = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = nextTheme;
  themeToggle.textContent = nextTheme === "dark" ? "Light" : "Dark";
  themeToggle.setAttribute("aria-pressed", nextTheme === "dark" ? "true" : "false");
}

function loadThemePreference() {
  try {
    return window.localStorage.getItem(THEME_STORAGE_KEY);
  } catch (_error) {
    return null;
  }
}

function saveThemePreference(theme) {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch (_error) {
    // Ignore storage errors in restrictive browser modes.
  }
}

function setupThemeToggle() {
  applyTheme(loadThemePreference() || "light");

  themeToggle.addEventListener("click", () => {
    const nextTheme = document.documentElement.dataset.theme === "dark"
      ? "light"
      : "dark";
    applyTheme(nextTheme);
    saveThemePreference(nextTheme);
    drawPredictionChart();
  });
}

async function getJSON(url) {
  const response = await fetch(url, { cache: "no-store" });
  const payload = await response.json();

  if (!response.ok) {
    throw new Error(payload.error || url + " returned " + response.status);
  }

  return payload;
}

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "n/a";
  }

  return (Number(value) * 100).toFixed(1) + "%";
}

function formatTimestamp(timestamp) {
  if (!timestamp) {
    return "Unknown";
  }

  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return timestamp;
  }

  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  });
}

function formatStateLabel(state) {
  if (state === "occupied") {
    return "Occupied";
  }
  if (state === "empty") {
    return "Empty";
  }
  return "Unavailable";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderHeadline(room, predictedNodes, occupiedNodes, emptyNodes) {
  predictedNodeCount.textContent = String(predictedNodes);
  occupiedCount.textContent = String(occupiedNodes);
  emptyCount.textContent = String(emptyNodes);
  lastUpdate.textContent = formatTimestamp(Date.now());

  if (!room || !room.state) {
    predictionHeadline.textContent = "No live room prediction";
    predictionMeta.textContent = "The model is ready, but there are not enough recent feature windows to make a room-level decision yet.";
    return;
  }

  if (room.state === "occupied") {
    predictionHeadline.textContent = "Room reads occupied";
    predictionMeta.textContent = occupiedNodes + " node vote" + (occupiedNodes === 1 ? "" : "s")
      + " currently support occupied across " + predictedNodes + " active node window"
      + (predictedNodes === 1 ? "" : "s") + ".";
    return;
  }

  predictionHeadline.textContent = "Room reads empty";
  predictionMeta.textContent = "All " + predictedNodes + " active node window"
    + (predictedNodes === 1 ? "" : "s") + " currently agree on empty.";
}

function renderRoomDecision(room) {
  roomState.textContent = room && room.state
    ? formatStateLabel(room.state)
    : "Waiting for prediction";
  roomConfidence.textContent = room
    ? formatPercent(room.confidence)
    : "n/a";
  roomWindowEnd.textContent = room
    ? formatTimestamp(room.window_end)
    : "Unknown";
  roomAggregation.textContent = room && room.aggregation
    ? room.aggregation
    : "No aggregation rule available.";
}

function renderSkipped(skipped) {
  const entries = Object.entries(skipped || {}).sort(([first], [second]) => first.localeCompare(second));

  if (!entries.length) {
    skippedNodes.innerHTML = '<div class="empty">All known nodes currently have enough recent data for inference.</div>';
    return;
  }

  skippedNodes.innerHTML = entries.map(([nodeId, reason]) => `
    <div class="skipped-row">
      <span>${escapeHtml(nodeId)}</span>
      <strong>${escapeHtml(reason)}</strong>
    </div>
  `).join("");
}

function renderModelDetails(payload) {
  modelWindowInfo.textContent = "Window " + payload.window_seconds + "s";
  modelPath.textContent = payload.model_path || "Unknown";
  minSamples.textContent = payload.min_samples ?? "-";
  sampleLimit.textContent = payload.sample_limit ?? "-";
  labelNote.textContent = payload.label_note || "No label note provided.";
}

function renderError(message) {
  connectionState.textContent = "Offline";
  connectionState.className = "pill clear";
  predictionHeadline.textContent = "Prediction page is unavailable";
  predictionMeta.textContent = message;
  predictedNodeCount.textContent = "0";
  occupiedCount.textContent = "0";
  emptyCount.textContent = "0";
  lastUpdate.textContent = "Unavailable";
  modelWindowInfo.textContent = "Window -";
  roomState.textContent = "Unavailable";
  roomConfidence.textContent = "n/a";
  roomWindowEnd.textContent = "Unavailable";
  roomAggregation.textContent = "Unavailable";
  skippedNodes.innerHTML = '<div class="empty">No skipped-node information available.</div>';
  modelPath.textContent = "Unavailable";
  minSamples.textContent = "-";
  sampleLimit.textContent = "-";
  labelNote.textContent = "Unavailable";
  appState.history = [];
  drawPredictionChart();
}

function renderState(payload) {
  const room = payload.room_state || null;

  connectionState.textContent = "Live";
  connectionState.className = "pill present";
  renderHeadline(
    room,
    room ? room.predicted_nodes || 0 : 0,
    room ? room.occupied_nodes || 0 : 0,
    room ? room.empty_nodes || 0 : 0
  );
  renderRoomDecision(room);
  renderSkipped(payload.skipped);
  renderModelDetails(payload);
}

function renderHistory(payload) {
  appState.history = payload.history || [];
  drawPredictionChart();
}

function drawPredictionChart() {
  const rect = predictionChart.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const width = Math.max(280, Math.floor(rect.width));
  const height = Math.max(220, Math.floor(rect.height));

  predictionChart.width = Math.floor(width * dpr);
  predictionChart.height = Math.floor(height * dpr);
  predictionCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  predictionCtx.clearRect(0, 0, width, height);

  predictionCtx.fillStyle = getThemeColor("--chart-bg", "#fbfcfc");
  predictionCtx.fillRect(0, 0, width, height);

  const left = width < 420 ? 62 : 82;
  const right = width < 420 ? 14 : 22;
  const top = 28;
  const bottom = 44;
  const chartWidth = width - left - right;
  const chartHeight = height - top - bottom;
  const highY = top + chartHeight * 0.22;
  const lowY = top + chartHeight * 0.78;
  const now = Date.now();
  const start = now - appState.minutes * 60 * 1000;

  drawPredictionGrid({
    width,
    height,
    left,
    right,
    top,
    bottom,
    start,
    now,
    highY,
    lowY
  });

  const points = appState.history
    .map(entry => ({
      ...entry,
      time: new Date(entry.timestamp).getTime()
    }))
    .filter(entry => !Number.isNaN(entry.time) && entry.time >= start && entry.time <= now)
    .map(entry => ({
      ...entry,
      x: left + ((entry.time - start) / Math.max(now - start, 1)) * chartWidth,
      y: entry.state === "occupied" ? highY : lowY
    }));

  if (!points.length) {
    predictionCtx.fillStyle = getThemeColor("--chart-label", "#63736f");
    predictionCtx.font = "700 16px Segoe UI, Arial, sans-serif";
    predictionCtx.fillText("No prediction history yet", left, top + 34);
    return;
  }

  const occupiedColor = getThemeColor("--green", "#2f7d5c");
  const emptyColor = getThemeColor("--blue", "#2860a8");

  predictionCtx.lineWidth = 3;
  predictionCtx.lineCap = "round";
  predictionCtx.lineJoin = "round";
  predictionCtx.strokeStyle = getThemeColor("--teal", "#0f766e");
  predictionCtx.beginPath();
  predictionCtx.moveTo(points[0].x, points[0].y);
  drawPredictionStepSegments(points, now, start, left, chartWidth);
  predictionCtx.stroke();

  points.forEach(point => {
    predictionCtx.save();
    predictionCtx.globalAlpha = point.confidence === null || point.confidence === undefined
      ? 0.6
      : Math.max(0.35, Math.min(1, point.confidence));
    predictionCtx.fillStyle = point.state === "occupied" ? occupiedColor : emptyColor;
    predictionCtx.beginPath();
    predictionCtx.arc(point.x, point.y, 4, 0, Math.PI * 2);
    predictionCtx.fill();
    predictionCtx.restore();
  });
}

function drawPredictionGrid(options) {
  const {
    width,
    height,
    left,
    right,
    top,
    bottom,
    start,
    now,
    highY,
    lowY
  } = options;
  const chartWidth = width - left - right;
  const gridCount = width < 420 ? 3 : 6;

  predictionCtx.strokeStyle = getThemeColor("--chart-grid", "#e5ece9");
  predictionCtx.lineWidth = 1;
  predictionCtx.fillStyle = getThemeColor("--chart-label", "#63736f");
  predictionCtx.font = "11px Segoe UI, Arial, sans-serif";

  [highY, lowY].forEach((y, index) => {
    predictionCtx.beginPath();
    predictionCtx.moveTo(left, y);
    predictionCtx.lineTo(width - right, y);
    predictionCtx.stroke();
    predictionCtx.fillText(index === 0 ? "Occupied" : "Empty", 8, y + 4);
  });

  for (let i = 0; i <= gridCount; i += 1) {
    const x = left + (chartWidth / gridCount) * i;
    predictionCtx.beginPath();
    predictionCtx.moveTo(x, top);
    predictionCtx.lineTo(x, height - bottom);
    predictionCtx.stroke();

    if (i > 0 && i < gridCount) {
      const time = start + ((now - start) / gridCount) * i;
      predictionCtx.fillText(formatClock(time), x - 26, height - 15);
    }
  }

  predictionCtx.fillText(appState.minutes + " min ago", left, height - 15);
  predictionCtx.textAlign = "right";
  predictionCtx.fillText("now", width - right, height - 15);
  predictionCtx.textAlign = "left";
}

function drawPredictionStepSegments(points, now, start, left, chartWidth) {
  for (let index = 1; index < points.length; index += 1) {
    const point = points[index];
    const previous = points[index - 1];

    predictionCtx.lineTo(point.x, previous.y);
    predictionCtx.lineTo(point.x, point.y);
  }

  const last = points[points.length - 1];
  const nowX = left + ((now - start) / Math.max(now - start, 1)) * chartWidth;
  predictionCtx.lineTo(nowX, last.y);
}

function formatClock(timestamp) {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return "";
  }

  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  });
}

async function refreshPredictions() {
  if (appState.polling) {
    return;
  }

  appState.polling = true;

  try {
    const [statePayload, historyPayload] = await Promise.all([
      getJSON("/state"),
      getJSON("/prediction-history?minutes=" + appState.minutes)
    ]);

    if (!statePayload.ok) {
      renderError(statePayload.error || "The state endpoint returned an unexpected payload.");
      return;
    }

    if (!historyPayload.ok) {
      renderError(historyPayload.error || "The prediction-history endpoint returned an unexpected payload.");
      return;
    }

    renderState(statePayload);
    renderHistory(historyPayload);
  } catch (error) {
    renderError(error.message);
    console.error(error);
  } finally {
    appState.polling = false;
  }
}

predictionRangeButtons.addEventListener("click", event => {
  const button = event.target.closest("button[data-minutes]");
  if (!button) {
    return;
  }

  appState.minutes = Number(button.dataset.minutes);
  document.querySelectorAll("#predictionRangeButtons button").forEach(item => {
    item.classList.toggle("active", item === button);
  });
  refreshPredictions();
});

window.addEventListener("resize", () => {
  window.clearTimeout(appState.resizeTimer);
  appState.resizeTimer = window.setTimeout(() => {
    drawPredictionChart();
  }, 120);
});

setupThemeToggle();
refreshPredictions();
window.setInterval(refreshPredictions, POLL_INTERVAL_MS);
