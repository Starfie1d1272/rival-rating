const state = {
  datasets: [],
  payload: null,
  frameIndex: 0,
  image: null,
  playing: false,
  timer: null,
  staticInfo: null,
};

const els = {
  datasetSelect: document.querySelector("#datasetSelect"),
  analyzeDataset: document.querySelector("#analyzeDataset"),
  fileInput: document.querySelector("#fileInput"),
  sampleSeconds: document.querySelector("#sampleSeconds"),
  maxFrames: document.querySelector("#maxFrames"),
  residualSeconds: document.querySelector("#residualSeconds"),
  verticalFovDeg: document.querySelector("#verticalFovDeg"),
  staticLos: document.querySelector("#staticLos"),
  statusText: document.querySelector("#statusText"),
  demoTitle: document.querySelector("#demoTitle"),
  demoMeta: document.querySelector("#demoMeta"),
  mapFrame: document.querySelector("#mapFrame"),
  mapImageLayer: document.querySelector("#mapImageLayer"),
  overlayImageLayer: document.querySelector("#overlayImageLayer"),
  canvas: document.querySelector("#mapCanvas"),
  playButton: document.querySelector("#playButton"),
  frameSlider: document.querySelector("#frameSlider"),
  frameReadout: document.querySelector("#frameReadout"),
  statT: document.querySelector("#statT"),
  statCT: document.querySelector("#statCT"),
  statContested: document.querySelector("#statContested"),
  statVacuum: document.querySelector("#statVacuum"),
  statTResidual: document.querySelector("#statTResidual"),
  statCTResidual: document.querySelector("#statCTResidual"),
  staticOrigin: document.querySelector("#staticOrigin"),
  staticVisible: document.querySelector("#staticVisible"),
  staticAreaSize: document.querySelector("#staticAreaSize"),
  staticCache: document.querySelector("#staticCache"),
  staticInfoText: document.querySelector("#staticInfoText"),
  playerList: document.querySelector("#playerList"),
  eventList: document.querySelector("#eventList"),
};

const ctx = els.canvas.getContext("2d");

init();

async function init() {
  bindEvents();
  await loadDatasets();
  drawEmpty();
}

function bindEvents() {
  els.analyzeDataset.addEventListener("click", () => analyzeSelectedDataset());
  els.fileInput.addEventListener("change", () => uploadSelectedFile());
  els.frameSlider.addEventListener("input", () => {
    state.frameIndex = Number(els.frameSlider.value);
    render();
  });
  els.playButton.addEventListener("click", togglePlayback);
  els.mapFrame.addEventListener("click", handleMapClick);
}

async function loadDatasets() {
  setStatus("Loading local dataset demos...");
  const res = await fetch("/api/datasets");
  const data = await res.json();
  state.datasets = data.demos || [];
  els.datasetSelect.innerHTML = "";
  for (const demo of state.datasets) {
    const option = document.createElement("option");
    option.value = demo.path;
    option.textContent = `${demo.mapName} · ${demo.name}`;
    els.datasetSelect.append(option);
  }
  setStatus(state.datasets.length ? `${state.datasets.length} local demos available.` : "No local demos found.");
}

async function analyzeSelectedDataset() {
  const path = els.datasetSelect.value;
  if (!path) return;
  const query = analysisQuery({ path });
  await loadAnalysis(`/api/analyze-existing?${query}`, {
    method: "POST",
  });
}

async function uploadSelectedFile() {
  const file = els.fileInput.files?.[0];
  if (!file) return;
  const query = analysisQuery({ filename: file.name });
  await loadAnalysis(`/api/upload?${query}`, {
    method: "POST",
    body: file,
  });
}

function analysisQuery(extra) {
  const params = new URLSearchParams({
    sampleSeconds: els.sampleSeconds.value || "4",
    maxFrames: els.maxFrames.value || "360",
    residualSeconds: els.residualSeconds.value || "3",
    verticalFovDeg: els.verticalFovDeg.value || "75",
    staticLos: els.staticLos.checked ? "1" : "0",
    ...extra,
  });
  return params.toString();
}

async function loadAnalysis(url, options) {
  stopPlayback();
  setBusy(true);
  const mode = els.staticLos.checked ? "precise static LOS" : "fast FOV/smoke";
  setStatus(`Analyzing demo with ${mode} mode...`);
  try {
    const res = await fetch(url, options);
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
    state.payload = data;
    state.frameIndex = 0;
    state.staticInfo = null;
    await loadMapImage(data.map.imageUrl);
    hydrateTimeline();
    renderStaticInfo();
    render();
    setStatus(`Loaded ${data.demo.fileName}. ${data.demo.frameCount} frames, ${data.map.areas.length} nav areas.`);
  } catch (error) {
    setStatus(error.message);
  } finally {
    setBusy(false);
  }
}

function setBusy(isBusy) {
  els.analyzeDataset.disabled = isBusy;
  els.fileInput.disabled = isBusy;
}

function setStatus(text) {
  els.statusText.textContent = text;
}

function loadMapImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      state.image = image;
      els.canvas.width = image.naturalWidth;
      els.canvas.height = image.naturalHeight;
      els.mapImageLayer.src = image.src;
      resolve();
    };
    image.onerror = reject;
    image.src = `${url}?t=${Date.now()}`;
  });
}

function hydrateTimeline() {
  const frames = state.payload.frames;
  els.frameSlider.min = "0";
  els.frameSlider.max = String(Math.max(0, frames.length - 1));
  els.frameSlider.value = "0";
  els.demoTitle.textContent = state.payload.demo.fileName;
  const config = state.payload.demo.config;
  els.demoMeta.textContent =
    `${state.payload.demo.mapName} · ${state.payload.demo.frameCount} frames · ` +
    `${state.payload.demo.sampleSeconds}s sample · ${config.residualSeconds}s residual · ` +
    `${config.verticalFovDeg}° vertical FOV · static LOS ${config.staticLos ? "on" : "off"}`;
  renderEvents();
}

function render() {
  if (!state.payload || !state.image) {
    drawEmpty();
    return;
  }
  const frame = state.payload.frames[state.frameIndex];
  if (!frame) return;

  ctx.clearRect(0, 0, els.canvas.width, els.canvas.height);
  drawAreas(frame);
  drawStaticInfoOverlay();
  drawSmokes(frame);
  drawPlayers(frame);
  syncOverlayImage();
  renderStats(frame);
  renderPlayers(frame);

  els.frameSlider.value = String(state.frameIndex);
  els.frameReadout.textContent =
    `Frame ${state.frameIndex + 1} / ${state.payload.frames.length} · ` +
    `R${frame.roundNum ?? "-"} · ${formatSeconds(frame.seconds)}`;
}

function drawEmpty() {
  ctx.fillStyle = "#10100f";
  ctx.fillRect(0, 0, els.canvas.width, els.canvas.height);
  ctx.fillStyle = "#a9a097";
  ctx.font = "16px system-ui";
  ctx.fillText("Load a demo to render map control.", 28, 42);
  syncOverlayImage();
}

function syncOverlayImage() {
  if (!els.overlayImageLayer) return;
  try {
    els.overlayImageLayer.src = els.canvas.toDataURL("image/png");
  } catch {
    els.overlayImageLayer.removeAttribute("src");
  }
}

function drawAreas(frame) {
  const control = frame.control;
  const t = new Set(control.T);
  const ct = new Set(control.CT);
  const contested = new Set(control.contested);
  drawResidualAreas(frame);
  for (const area of state.payload.map.areas) {
    let fill = null;
    if (contested.has(area.id)) fill = "rgba(158,124,255,0.46)";
    else if (t.has(area.id)) fill = "rgba(228,90,79,0.42)";
    else if (ct.has(area.id)) fill = "rgba(56,185,168,0.42)";
    if (!fill) continue;
    drawPolygon(area.polygon, fill, "rgba(10,10,10,0.18)");
  }
}

function drawResidualAreas(frame) {
  const residual = frame.residual || { T: [], CT: [], contested: [] };
  const t = residualMap(residual.T);
  const ct = residualMap(residual.CT);
  const contested = residualMap(residual.contested);
  for (const area of state.payload.map.areas) {
    let fill = null;
    if (contested.has(area.id)) {
      fill = residualFill("contested", contested.get(area.id).confidence);
    } else if (t.has(area.id)) {
      fill = residualFill("T", t.get(area.id).confidence);
    } else if (ct.has(area.id)) {
      fill = residualFill("CT", ct.get(area.id).confidence);
    }
    if (!fill) continue;
    drawPolygon(area.polygon, fill, "rgba(236,231,220,0.16)", { dash: [3, 4], lineWidth: 0.55 });
  }
}

function residualMap(entries) {
  return new Map((entries || []).map((entry) => [entry.id, entry]));
}

function residualFill(team, confidence) {
  const alpha = Math.max(0.07, Math.min(0.22, 0.07 + Number(confidence || 0) * 0.15));
  if (team === "T") return `rgba(228,90,79,${alpha})`;
  if (team === "CT") return `rgba(56,185,168,${alpha})`;
  return `rgba(158,124,255,${alpha})`;
}

function drawStaticInfoOverlay() {
  if (!state.staticInfo || !state.payload) return;
  const visible = new Set(state.staticInfo.visibleAreaIds || []);
  const originId = state.staticInfo.match?.originArea?.id;
  for (const area of state.payload.map.areas) {
    if (!visible.has(area.id)) continue;
    drawPolygon(area.polygon, "rgba(231,183,95,0.18)", "rgba(231,183,95,0.42)");
  }
  const origin = state.payload.map.areas.find((area) => area.id === originId);
  if (origin) drawPolygon(origin.polygon, "rgba(231,183,95,0.38)", "rgba(255,236,178,0.9)");
}

function drawPolygon(points, fill, stroke, options = {}) {
  if (!points.length) return;
  ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  for (const point of points.slice(1)) ctx.lineTo(point.x, point.y);
  ctx.closePath();
  ctx.fillStyle = fill;
  ctx.fill();
  ctx.strokeStyle = stroke;
  ctx.lineWidth = options.lineWidth ?? 0.4;
  ctx.setLineDash(options.dash || []);
  ctx.stroke();
  ctx.setLineDash([]);
}

function drawPlayers(frame) {
  const zValues = frame.players.map((player) => Number(player.position.z || 0));
  const minZ = zValues.length ? Math.min(...zValues) : 0;
  const maxZ = zValues.length ? Math.max(...zValues) : 0;
  const zRange = Math.max(1, maxZ - minZ);
  for (const player of frame.players) {
    const pos = toPixel(player.position);
    const zNorm = (Number(player.position.z || 0) - minZ) / zRange;
    ctx.beginPath();
    ctx.arc(pos.x, pos.y, 8 + zNorm * 5, 0, Math.PI * 2);
    ctx.strokeStyle = `rgba(231,183,95,${0.22 + zNorm * 0.58})`;
    ctx.lineWidth = 1.2;
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(pos.x, pos.y, 5, 0, Math.PI * 2);
    ctx.fillStyle = player.team === "T" ? "#f0786f" : "#63d4c6";
    ctx.fill();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = "#111";
    ctx.stroke();

    const angle = (player.yawDeg * Math.PI) / 180;
    ctx.beginPath();
    ctx.moveTo(pos.x, pos.y);
    ctx.lineTo(pos.x + Math.cos(angle) * 18, pos.y + Math.sin(angle) * 18);
    ctx.strokeStyle = pitchStroke(player.pitchDeg);
    ctx.lineWidth = 1.2;
    ctx.stroke();
  }
}

function pitchStroke(pitchDeg) {
  const pitch = Number(pitchDeg || 0);
  if (pitch < -8) return "rgba(231,183,95,0.9)";
  if (pitch > 8) return "rgba(126,166,255,0.86)";
  return "rgba(255,255,255,0.75)";
}

function drawSmokes(frame) {
  for (const smoke of frame.smokes) {
    const pos = toPixel(smoke.position);
    const scale = state.payload.map.metadata.scale;
    const radius = smoke.radius / scale;
    ctx.beginPath();
    ctx.arc(pos.x, pos.y, radius, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(216,208,194,0.34)";
    ctx.fill();
    ctx.strokeStyle = "rgba(245,238,228,0.55)";
    ctx.lineWidth = 1;
    ctx.stroke();
  }
}

function toPixel(position) {
  const meta = state.payload.map.metadata;
  return {
    x: (position.x - meta.pos_x) / meta.scale,
    y: (meta.pos_y - position.y) / meta.scale,
  };
}

function pixelToGame(point) {
  const meta = state.payload.map.metadata;
  return {
    x: point.x * meta.scale + meta.pos_x,
    y: meta.pos_y - point.y * meta.scale,
  };
}

function renderStats(frame) {
  els.statT.textContent = frame.control.T.length;
  els.statCT.textContent = frame.control.CT.length;
  els.statContested.textContent = frame.control.contested.length;
  els.statVacuum.textContent = frame.control.vacuumCount;
  els.statTResidual.textContent = (frame.residual?.T || []).length;
  els.statCTResidual.textContent = (frame.residual?.CT || []).length;
}

async function handleMapClick(event) {
  if (!state.payload || !state.image) return;
  const point = canvasEventToPixel(event);
  const game = pixelToGame(point);
  await loadStaticInfo(game);
}

function canvasEventToPixel(event) {
  const rect = els.mapFrame.getBoundingClientRect();
  return {
    x: ((event.clientX - rect.left) / rect.width) * els.canvas.width,
    y: ((event.clientY - rect.top) / rect.height) * els.canvas.height,
  };
}

async function loadStaticInfo(position) {
  const params = new URLSearchParams({
    x: position.x.toFixed(3),
    y: position.y.toFixed(3),
    computeMissing: "1",
  });
  setStatus("Querying static map info...");
  try {
    const res = await fetch(`/api/map-info/${state.payload.demo.mapName}?${params.toString()}`);
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
    state.staticInfo = data;
    renderStaticInfo();
    render();
    const origin = data.match.originArea.id;
    const source = data.computedNow ? "computed and cached" : "from cache";
    setStatus(`Static info ${source}: Nav ${origin} sees ${data.visibleAreaCount} nav areas.`);
  } catch (error) {
    setStatus(error.message);
  }
}

function renderStaticInfo() {
  const info = state.staticInfo;
  if (!info) {
    els.staticOrigin.textContent = "-";
    els.staticVisible.textContent = "0";
    els.staticAreaSize.textContent = "0";
    els.staticCache.textContent = "-";
    els.staticInfoText.textContent = "No coordinate selected.";
    return;
  }
  const origin = info.match.originArea;
  const query = info.query;
  els.staticOrigin.textContent = `Nav ${origin.id}`;
  els.staticVisible.textContent = String(info.visibleAreaCount);
  els.staticAreaSize.textContent = formatNumber(info.visibleAreaSize);
  els.staticCache.textContent = info.cacheComplete ? "Full" : "Partial";
  els.staticInfoText.textContent =
    `${info.match.type}, ${formatNumber(info.match.distance)}u from area centroid. ` +
    `Coordinate ${formatNumber(query.x)}, ${formatNumber(query.y)}.`;
}

function renderPlayers(frame) {
  els.playerList.innerHTML = "";
  for (const player of frame.players) {
    const row = document.createElement("div");
    row.className = "player-row";
    const zText = formatNumber(player.position.z);
    const pitch = Math.round(Number(player.pitchDeg || 0));
    const heightDelta = player.heightDeltaFromNav;
    const heightText = heightDelta === undefined ? "" : ` · ΔZ ${formatNumber(heightDelta)}`;
    row.innerHTML = `
      <span>
        ${escapeHtml(player.name)} <span class="event-time">${escapeHtml(player.place || "")}</span>
        <span class="player-meta">Z ${zText} · pitch ${pitch}°${heightText}</span>
      </span>
      <span class="team-pill ${player.team}">${player.team}</span>
    `;
    els.playerList.append(row);
  }
}

function renderEvents() {
  els.eventList.innerHTML = "";
  const events = state.payload.events.slice(0, 120);
  if (!events.length) {
    els.eventList.textContent = "No loss events in sampled frames.";
    return;
  }
  for (const event of events) {
    const row = document.createElement("div");
    row.className = "event-row";
    row.innerHTML = `
      <strong>${event.team} lost ${escapeHtml(event.label)}</strong>
      <div class="event-time">${formatSeconds(event.fromSeconds)} → ${formatSeconds(event.toSeconds)}</div>
    `;
    row.addEventListener("click", () => jumpToTick(event.toTick));
    els.eventList.append(row);
  }
}

function jumpToTick(tick) {
  const frames = state.payload.frames;
  let best = 0;
  let bestDistance = Infinity;
  frames.forEach((frame, index) => {
    const distance = Math.abs(frame.tick - tick);
    if (distance < bestDistance) {
      bestDistance = distance;
      best = index;
    }
  });
  state.frameIndex = best;
  render();
}

function togglePlayback() {
  if (!state.payload) return;
  if (state.playing) stopPlayback();
  else startPlayback();
}

function startPlayback() {
  state.playing = true;
  els.playButton.textContent = "Pause";
  state.timer = window.setInterval(() => {
    state.frameIndex = (state.frameIndex + 1) % state.payload.frames.length;
    render();
  }, 420);
}

function stopPlayback() {
  state.playing = false;
  els.playButton.textContent = "Play";
  if (state.timer) window.clearInterval(state.timer);
  state.timer = null;
}

function formatSeconds(seconds) {
  const safe = Math.max(0, Math.floor(seconds));
  const min = Math.floor(safe / 60);
  const sec = String(safe % 60).padStart(2, "0");
  return `${min}:${sec}`;
}

function formatNumber(value) {
  return Math.round(Number(value)).toLocaleString("en-US");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
