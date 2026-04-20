const appState = {
  status: null,
  events: [],
  minutes: 3,
  polling: false,
  timeoutSaving: false,
  resizeTimer: null
};

const POLL_INTERVAL_MS = 1000;
const SAMPLE_FETCH_RATE_PER_SECOND = 12;
const THEME_STORAGE_KEY = "presenceDashboardTheme";
const seriesColorVars = ["--green", "--coral", "--blue", "--amber", "--teal"];
const fallbackColors = ["#2f7d5c", "#d95c4a", "#2860a8", "#b7791f", "#0f766e"];

const connectionState = document.getElementById("connectionState");
const themeToggle = document.getElementById("themeToggle");
const homePresence = document.getElementById("homePresence");
const homeMeta = document.getElementById("homeMeta");
const timeoutForm = document.getElementById("timeoutForm");
const timeoutInput = document.getElementById("timeoutInput");
const timeoutMessage = document.getElementById("timeoutMessage");
const sensorGrid = document.getElementById("sensorGrid");
const eventList = document.getElementById("eventList");
const eventCount = document.getElementById("eventCount");
const canvas = document.getElementById("motionChart");
const ctx = canvas.getContext("2d");
const rssiCanvas = document.getElementById("rssiChart");
const rssiCtx = rssiCanvas.getContext("2d");

function getThemeColor(name, fallback) {
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();

  return value || fallback;
}

function getSeriesColor(index) {
  return getThemeColor(
    seriesColorVars[index % seriesColorVars.length],
    fallbackColors[index % fallbackColors.length]
  );
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
    // Local storage can be unavailable in strict browser modes.
  }
}

function setupThemeToggle() {
  const storedTheme = loadThemePreference();
  applyTheme(storedTheme || "light");

  themeToggle.addEventListener("click", () => {
    const nextTheme = document.documentElement.dataset.theme === "dark"
      ? "light"
      : "dark";
    applyTheme(nextTheme);
    saveThemePreference(nextTheme);
    drawChart();
    drawRssiChart();
  });
}

function formatClock(timestamp) {
  if (!timestamp) {
    return "Never";
  }

  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return "Unknown";
  }

  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  });
}

function formatAge(seconds) {
  if (seconds === null || seconds === undefined) {
    return "No motion";
  }
  if (seconds < 1) {
    return "Now";
  }
  if (seconds < 60) {
    return Math.round(seconds) + "s ago";
  }
  return Math.round(seconds / 60) + "m ago";
}

function getPirValue(event) {
  if (event.pir !== null && event.pir !== undefined) {
    return event.pir;
  }
  return event.motion;
}

function getWifiRssi(event) {
  if (event.wifi_rssi !== null && event.wifi_rssi !== undefined) {
    return event.wifi_rssi;
  }
  return event.rssi;
}

async function getJSON(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(url + " returned " + response.status);
  }
  return response.json();
}

async function postJSON(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(body)
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || url + " returned " + response.status);
  }
  return payload;
}

async function refresh() {
  if (appState.polling) {
    return;
  }

  appState.polling = true;

  try {
    const limit = Math.ceil(appState.minutes * 60 * SAMPLE_FETCH_RATE_PER_SECOND);
    const results = await Promise.all([
      getJSON("/status"),
      getJSON("/stored-samples?limit=" + limit)
    ]);

    appState.status = results[0];
    appState.events = results[1].samples || results[1].events || [];
    connectionState.textContent = "Live";
    connectionState.className = "pill present";
    render();
  } catch (error) {
    connectionState.textContent = "Offline";
    connectionState.className = "pill clear";
    console.error(error);
  } finally {
    appState.polling = false;
  }
}

function startPolling() {
  refresh();
  window.setInterval(refresh, POLL_INTERVAL_MS);
}

function render() {
  renderPresence();
  renderSensors();
  renderEvents();
  drawChart();
  drawRssiChart();
}

function renderPresence() {
  if (!appState.status) {
    return;
  }

  const sensors = Object.values(appState.status.sensors || {});
  const seenCount = sensors.filter(sensor => sensor.seen).length;
  const activeCount = sensors.filter(sensor => sensor.present).length;

  homePresence.textContent = appState.status.home_present ? "Present" : "Clear";
  homeMeta.textContent = activeCount + " active sensor" + (activeCount === 1 ? "" : "s")
    + " / " + seenCount + " seen. Timeout "
    + appState.status.presence_timeout_seconds + "s. Polling every 1s.";
  syncTimeoutControl(appState.status);
}

function syncTimeoutControl(status) {
  if (!timeoutInput || !status) {
    return;
  }

  if (status.presence_timeout_min_seconds !== undefined) {
    timeoutInput.min = status.presence_timeout_min_seconds;
  }
  if (status.presence_timeout_max_seconds !== undefined) {
    timeoutInput.max = status.presence_timeout_max_seconds;
  }
  if (document.activeElement !== timeoutInput && !appState.timeoutSaving) {
    timeoutInput.value = status.presence_timeout_seconds;
  }
}

function renderSensors() {
  const sensors = appState.status ? appState.status.sensors || {} : {};
  const entries = Object.entries(sensors);

  if (!entries.length) {
    sensorGrid.innerHTML = '<div class="empty">Waiting for ESP32 sensors.</div>';
    return;
  }

  sensorGrid.innerHTML = entries.map(([name, sensor]) => {
    const dotClass = sensor.pir ? "motion" : sensor.present ? "present" : "";
    const state = sensor.present ? "Present" : sensor.seen ? "Clear" : "Not seen";
    const pir = sensor.pir === null || sensor.pir === undefined
      ? "No PIR"
      : sensor.pir ? "Motion" : "Clear";
    const wifiRssi = sensor.wifi_rssi === null || sensor.wifi_rssi === undefined
      ? "-"
      : sensor.wifi_rssi + " dBm";
    const sampleCount = sensor.history ? sensor.history.stored_samples : 0;
    const avgRssi = sensor.history && sensor.history.wifi_rssi_avg !== null
      ? sensor.history.wifi_rssi_avg + " dBm"
      : "-";
    return `
      <article class="sensor-card">
        <p class="sensor-name"><span class="dot ${dotClass}"></span>${name}</p>
        <div class="sensor-metric"><span>Status</span><strong>${state}</strong></div>
        <div class="sensor-metric"><span>PIR</span><strong>${pir}</strong></div>
        <div class="sensor-metric"><span>Last motion</span><strong>${formatAge(sensor.seconds_since_last_motion)}</strong></div>
        <div class="sensor-metric"><span>Wi-Fi RSSI</span><strong>${wifiRssi}</strong></div>
        <div class="sensor-metric"><span>Avg RSSI</span><strong>${avgRssi}</strong></div>
        <div class="sensor-metric"><span>Samples</span><strong>${sampleCount}</strong></div>
      </article>
    `;
  }).join("");
}

function renderEvents() {
  const pirEvents = appState.events
    .filter(event => getPirValue(event) !== null && getPirValue(event) !== undefined)
    .slice(-12)
    .reverse();
  eventCount.textContent = pirEvents.length + " visible";

  if (!pirEvents.length) {
    eventList.innerHTML = '<div class="empty">Send PIR samples to see motion and clear events here.</div>';
    return;
  }

  eventList.innerHTML = pirEvents.map(event => {
    const pir = getPirValue(event);
    const state = pir === null || pir === undefined
      ? "RSSI sample"
      : pir ? "PIR motion" : "PIR clear";
    const rssi = getWifiRssi(event);
    const wifiRssi = rssi === null || rssi === undefined
      ? "-"
      : rssi + " dBm";
    return `
      <div class="event-row">
        <span class="event-time">${formatClock(event.timestamp)}</span>
        <strong>${event.sensor}</strong>
        <span>${state}</span>
        <span class="event-extra">${wifiRssi}</span>
      </div>
    `;
  }).join("");
}

function drawChart() {
  const status = appState.status;
  const events = appState.events || [];
  const sensors = status ? Object.keys(status.sensors || {}) : [];
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const width = Math.max(320, Math.floor(rect.width));
  const height = Math.max(320, Math.floor(rect.height));

  canvas.width = Math.floor(width * dpr);
  canvas.height = Math.floor(height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  ctx.fillStyle = getThemeColor("--chart-bg", "#fbfcfc");
  ctx.fillRect(0, 0, width, height);

  const left = width < 560 ? 82 : 122;
  const right = 22;
  const top = 30;
  const bottom = 44;
  const chartWidth = width - left - right;
  const chartHeight = height - top - bottom;
  const now = Date.now();
  const start = now - appState.minutes * 60 * 1000;
  const rowHeight = sensors.length ? chartHeight / sensors.length : chartHeight;
  const timeoutMs = status
    ? status.presence_timeout_seconds * 1000
    : 180000;
  const groupedEvents = groupEventsBySensor(events);

  drawGrid(width, height, left, right, top, bottom, start, now);

  if (!sensors.length) {
    ctx.fillStyle = getThemeColor("--chart-label", "#63736f");
    ctx.font = "700 16px Segoe UI, Arial, sans-serif";
    ctx.fillText("Waiting for sensor data", left, top + 34);
    return;
  }

  sensors.forEach((sensor, index) => {
    const y = top + index * rowHeight;
    const mid = y + rowHeight / 2;
    const color = getSeriesColor(index);

    ctx.fillStyle = getThemeColor("--chart-text", "#15211f");
    ctx.font = "700 12px Segoe UI, Arial, sans-serif";
    ctx.fillText(sensor, 12, mid + 4, left - 20);

    ctx.strokeStyle = getThemeColor("--chart-grid", "#d8e1de");
    ctx.beginPath();
    ctx.moveTo(left, y + rowHeight);
    ctx.lineTo(width - right, y + rowHeight);
    ctx.stroke();

    const sensorEvents = groupedEvents.get(sensor) || [];
    drawSensorTimeline({
      sensorEvents,
      color,
      start,
      now,
      timeoutMs,
      left,
      chartWidth,
      rowTop: y,
      rowHeight
    });
  });

  ctx.fillStyle = getThemeColor("--chart-label", "#63736f");
  ctx.font = "12px Segoe UI, Arial, sans-serif";
  ctx.fillText(appState.minutes + " min ago", left, height - 15);
  ctx.textAlign = "right";
  ctx.fillText("now", width - right, height - 15);
  ctx.textAlign = "left";
}

function drawRssiChart() {
  const status = appState.status;
  const samples = appState.events || [];
  const sensors = status ? Object.keys(status.sensors || {}) : [];
  const rect = rssiCanvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const width = Math.max(320, Math.floor(rect.width));
  const height = Math.max(320, Math.floor(rect.height));

  rssiCanvas.width = Math.floor(width * dpr);
  rssiCanvas.height = Math.floor(height * dpr);
  rssiCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  rssiCtx.clearRect(0, 0, width, height);

  rssiCtx.fillStyle = getThemeColor("--chart-bg", "#fbfcfc");
  rssiCtx.fillRect(0, 0, width, height);

  const left = width < 560 ? 54 : 72;
  const right = 22;
  const top = 28;
  const bottom = 44;
  const chartWidth = width - left - right;
  const chartHeight = height - top - bottom;
  const now = Date.now();
  const start = now - appState.minutes * 60 * 1000;
  const groupedSamples = groupEventsBySensor(samples);
  const rssiScale = getRssiScale(sensors, groupedSamples, start, now);

  drawRssiGrid({
    width,
    height,
    left,
    right,
    top,
    bottom,
    start,
    now,
    minRssi: rssiScale.min,
    maxRssi: rssiScale.max,
    rssiLines: rssiScale.lines
  });

  if (!sensors.length) {
    rssiCtx.fillStyle = getThemeColor("--chart-label", "#63736f");
    rssiCtx.font = "700 16px Segoe UI, Arial, sans-serif";
    rssiCtx.fillText("Waiting for RSSI samples", left, top + 34);
    return;
  }

  sensors.forEach((sensor, index) => {
    const color = getSeriesColor(index);
    const points = (groupedSamples.get(sensor) || [])
      .map(sample => ({
        time: sample.time,
        value: getWifiRssi(sample)
      }))
      .filter(point => (
        point.value !== null
        && point.value !== undefined
        && point.time >= start
        && point.time <= now
      ))
      .map(point => ({
        x: left + ((point.time - start) / (now - start)) * chartWidth,
        y: top + ((rssiScale.max - point.value) / (rssiScale.max - rssiScale.min)) * chartHeight,
        value: point.value
      }));

    drawRssiLine(points, color);

    if (points.length) {
      const last = points[points.length - 1];
      rssiCtx.fillStyle = color;
      rssiCtx.font = "700 12px Segoe UI, Arial, sans-serif";
      rssiCtx.fillText(sensor + " " + last.value + " dBm", 12, top + 16 + index * 18);
    }
  });
}

function drawRssiGrid(options) {
  const {
    width,
    height,
    left,
    right,
    top,
    bottom,
    start,
    now,
    minRssi,
    maxRssi,
    rssiLines
  } = options;
  const chartWidth = width - left - right;
  const chartHeight = height - top - bottom;
  const timeLines = 6;

  rssiCtx.strokeStyle = getThemeColor("--chart-grid", "#e5ece9");
  rssiCtx.lineWidth = 1;
  rssiCtx.fillStyle = getThemeColor("--chart-label", "#63736f");
  rssiCtx.font = "11px Segoe UI, Arial, sans-serif";

  rssiLines.forEach(value => {
    const y = top + ((maxRssi - value) / (maxRssi - minRssi)) * chartHeight;
    rssiCtx.beginPath();
    rssiCtx.moveTo(left, y);
    rssiCtx.lineTo(width - right, y);
    rssiCtx.stroke();
    rssiCtx.fillText(value + " dBm", 8, y + 4);
  });

  for (let i = 0; i <= timeLines; i += 1) {
    const x = left + (chartWidth / timeLines) * i;
    rssiCtx.beginPath();
    rssiCtx.moveTo(x, top);
    rssiCtx.lineTo(x, height - bottom);
    rssiCtx.stroke();

    if (i > 0 && i < timeLines) {
      const time = start + ((now - start) / timeLines) * i;
      rssiCtx.fillText(formatClock(time), x - 26, height - 15);
    }
  }

  rssiCtx.fillText(appState.minutes + " min ago", left, height - 15);
  rssiCtx.textAlign = "right";
  rssiCtx.fillText("now", width - right, height - 15);
  rssiCtx.textAlign = "left";
}

function getRssiScale(sensors, groupedSamples, start, now) {
  const values = [];

  sensors.forEach(sensor => {
    (groupedSamples.get(sensor) || []).forEach(sample => {
      const value = getWifiRssi(sample);
      if (
        value !== null
        && value !== undefined
        && sample.time >= start
        && sample.time <= now
      ) {
        values.push(value);
      }
    });
  });

  if (!values.length) {
    return {
      min: -95,
      max: -30,
      lines: [-90, -80, -70, -60, -50, -40]
    };
  }

  const observedMin = Math.min(...values);
  const observedMax = Math.max(...values);
  const observedSpan = observedMax - observedMin;
  const targetSpan = Math.max(12, observedSpan + 8);
  const center = (observedMin + observedMax) / 2;
  const min = Math.floor(center - targetSpan / 2);
  const max = Math.ceil(center + targetSpan / 2);

  return {
    min,
    max,
    lines: buildRssiGridLines(min, max)
  };
}

function buildRssiGridLines(minRssi, maxRssi) {
  const lineCount = 5;
  const step = (maxRssi - minRssi) / (lineCount - 1);
  const lines = [];

  for (let index = 0; index < lineCount; index += 1) {
    lines.push(Math.round(maxRssi - step * index));
  }

  return lines;
}

function drawRssiLine(points, color) {
  if (!points.length) {
    return;
  }

  rssiCtx.strokeStyle = color;
  rssiCtx.lineWidth = 2.5;
  rssiCtx.lineCap = "round";
  rssiCtx.lineJoin = "round";
  rssiCtx.beginPath();

  points.forEach((point, index) => {
    if (index === 0) {
      rssiCtx.moveTo(point.x, point.y);
      return;
    }
    rssiCtx.lineTo(point.x, point.y);
  });

  rssiCtx.stroke();

  points.forEach(point => {
    rssiCtx.fillStyle = color;
    rssiCtx.beginPath();
    rssiCtx.arc(point.x, point.y, 3, 0, Math.PI * 2);
    rssiCtx.fill();
  });
}

function groupEventsBySensor(events) {
  const grouped = new Map();

  events.forEach(event => {
    const time = new Date(event.timestamp).getTime();
    if (Number.isNaN(time)) {
      return;
    }

    const sensorEvents = grouped.get(event.sensor) || [];
    sensorEvents.push({ ...event, time });
    grouped.set(event.sensor, sensorEvents);
  });

  grouped.forEach(sensorEvents => {
    sensorEvents.sort((first, second) => first.time - second.time);
  });

  return grouped;
}

function drawSensorTimeline(options) {
  const {
    sensorEvents,
    color,
    start,
    now,
    timeoutMs,
    left,
    chartWidth,
    rowTop,
    rowHeight
  } = options;

  const rowBottom = rowTop + rowHeight;
  const highY = rowTop + rowHeight * 0.34;
  const lowY = rowBottom - rowHeight * 0.34;
  const sampleCount = Math.max(80, Math.floor(chartWidth / 5));
  const pirTransitions = getPirTransitionEvents(sensorEvents, start, now);

  const presencePoints = buildSignalPoints({
    start,
    now,
    left,
    chartWidth,
    highY,
    lowY,
    sampleCount,
    extraTimes: getPresenceTransitionTimes(sensorEvents, start, now, timeoutMs),
    isActiveAt: time => isSensorPresentAt(sensorEvents, time, timeoutMs)
  });
  const pirPoints = buildSignalPoints({
    start,
    now,
    left,
    chartWidth,
    highY,
    lowY,
    sampleCount,
    extraTimes: pirTransitions.map(event => event.time),
    isActiveAt: time => isPirReportingAt(sensorEvents, time)
  });

  drawSignalStroke(presencePoints, color, { alpha: 0.22, width: 7 });
  drawSignalStroke(pirPoints, color, { alpha: 1, width: 3 });
  drawEventDots(pirTransitions, start, now, left, chartWidth, lowY, highY, color);
}

function buildSignalPoints(options) {
  const {
    start,
    now,
    left,
    chartWidth,
    highY,
    lowY,
    sampleCount,
    extraTimes = [],
    isActiveAt
  } = options;
  const times = [];

  for (let i = 0; i <= sampleCount; i += 1) {
    const ratio = i / sampleCount;
    times.push(start + (now - start) * ratio);
  }

  extraTimes.forEach(time => {
    if (time >= start && time <= now) {
      times.push(time);
    }
  });

  return [...new Set(times)]
    .sort((first, second) => first - second)
    .map(time => {
      const ratio = (time - start) / (now - start);
      const active = isActiveAt(time);
      const value = active ? 1 : 0;

      return {
        x: left + chartWidth * ratio,
        y: lowY - (lowY - highY) * value,
        active
      };
    });
}

function isSensorPresentAt(sensorEvents, time, timeoutMs) {
  for (let i = sensorEvents.length - 1; i >= 0; i -= 1) {
    const event = sensorEvents[i];

    if (event.time > time) {
      continue;
    }

    if (!getPirValue(event)) {
      continue;
    }

    return time - event.time <= timeoutMs;
  }

  return false;
}

function isPirReportingAt(sensorEvents, time) {
  for (let i = sensorEvents.length - 1; i >= 0; i -= 1) {
    const event = sensorEvents[i];

    if (event.time > time) {
      continue;
    }

    const pir = getPirValue(event);
    if (pir === null || pir === undefined) {
      continue;
    }

    return Boolean(pir);
  }

  return false;
}

function drawSignalStroke(points, color, options = {}) {
  if (!points.length) {
    return;
  }

  ctx.save();
  ctx.globalAlpha = options.alpha === undefined ? 1 : options.alpha;
  ctx.lineWidth = options.width || 3;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.strokeStyle = color;
  ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  drawStepSegments(points);
  ctx.stroke();
  ctx.restore();
}

function drawStepSegments(points) {
  for (let index = 1; index < points.length; index += 1) {
    const point = points[index];
    const previous = points[index - 1];

    ctx.lineTo(point.x, previous.y);
    ctx.lineTo(point.x, point.y);
  }
}

function drawEventDots(transitionEvents, start, now, left, chartWidth, lowY, highY, color) {
  transitionEvents.forEach(event => {
    const x = left + ((event.time - start) / (now - start)) * chartWidth;
    const pir = getPirValue(event);
    const y = pir ? highY : lowY;

    ctx.fillStyle = pir ? color : getThemeColor("--chart-label", "#9aa6a3");
    ctx.beginPath();
    ctx.arc(x, y, pir ? 4 : 3, 0, Math.PI * 2);
    ctx.fill();
  });
}

function getPirTransitionEvents(sensorEvents, start, now) {
  const transitions = [];
  let previousPir;

  sensorEvents.forEach(event => {
    const pir = getPirValue(event);
    if (pir === null || pir === undefined) {
      return;
    }

    const nextPir = Boolean(pir);
    const changed = previousPir === undefined || nextPir !== previousPir;
    previousPir = nextPir;

    if (!changed || event.time < start || event.time > now) {
      return;
    }

    transitions.push({
      ...event,
      pir: nextPir,
      motion: nextPir
    });
  });

  return transitions;
}

function getPresenceTransitionTimes(sensorEvents, start, now, timeoutMs) {
  const times = [];

  sensorEvents.forEach(event => {
    if (!getPirValue(event)) {
      return;
    }

    const activeAt = event.time;
    const clearAt = event.time + timeoutMs;

    if (activeAt >= start && activeAt <= now) {
      times.push(activeAt);
    }
    if (clearAt >= start && clearAt <= now) {
      times.push(clearAt);
    }
  });

  return times;
}

function drawGrid(width, height, left, right, top, bottom, start, now) {
  const chartWidth = width - left - right;
  const gridCount = 6;

  ctx.strokeStyle = getThemeColor("--chart-grid", "#e5ece9");
  ctx.lineWidth = 1;
  ctx.fillStyle = getThemeColor("--chart-label", "#63736f");
  ctx.font = "11px Segoe UI, Arial, sans-serif";

  for (let i = 0; i <= gridCount; i += 1) {
    const x = left + (chartWidth / gridCount) * i;
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, height - bottom);
    ctx.stroke();

    if (i > 0 && i < gridCount) {
      const time = start + ((now - start) / gridCount) * i;
      ctx.fillText(formatClock(time), x - 26, height - 15);
    }
  }
}

document.getElementById("rangeButtons").addEventListener("click", event => {
  const button = event.target.closest("button[data-minutes]");
  if (!button) {
    return;
  }

  appState.minutes = Number(button.dataset.minutes);
  document.querySelectorAll("#rangeButtons button").forEach(item => {
    item.classList.toggle("active", item === button);
  });
  refresh();
});

timeoutForm.addEventListener("submit", async event => {
  event.preventDefault();

  const value = Number(timeoutInput.value);
  const min = Number(timeoutInput.min || 5);
  const max = Number(timeoutInput.max || 3600);

  if (!Number.isInteger(value) || value < min || value > max) {
    timeoutMessage.textContent = "Use " + min + "-" + max + " seconds.";
    return;
  }

  appState.timeoutSaving = true;
  timeoutMessage.textContent = "Saving...";

  try {
    const payload = await postJSON("/settings", {
      presence_timeout_seconds: value
    });

    if (appState.status) {
      appState.status.presence_timeout_seconds = payload.presence_timeout_seconds;
      appState.status.presence_timeout_min_seconds = payload.presence_timeout_min_seconds;
      appState.status.presence_timeout_max_seconds = payload.presence_timeout_max_seconds;
    }
    timeoutMessage.textContent = "Saved.";
    render();
    refresh();
  } catch (error) {
    timeoutMessage.textContent = error.message;
  } finally {
    appState.timeoutSaving = false;
  }
});

window.addEventListener("resize", () => {
  window.clearTimeout(appState.resizeTimer);
  appState.resizeTimer = window.setTimeout(() => {
    drawChart();
    drawRssiChart();
  }, 120);
});

setupThemeToggle();
startPolling();
