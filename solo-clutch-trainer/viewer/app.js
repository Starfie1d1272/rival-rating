const canvas = document.querySelector("#traceCanvas");
const ctx = canvas.getContext("2d");
const fileInput = document.querySelector("#traceFile");
const scrubber = document.querySelector("#scrubber");
const frameLabel = document.querySelector("#frameLabel");
const winnerLabel = document.querySelector("#winnerLabel");
const valueLabel = document.querySelector("#valueLabel");
const eventList = document.querySelector("#eventList");
const traceMeta = document.querySelector("#traceMeta");
const playButton = document.querySelector("#playButton");
const prevButton = document.querySelector("#prevButton");
const nextButton = document.querySelector("#nextButton");
const speedButtons = Array.from(document.querySelectorAll("[data-speed]"));
const placeTButton = document.querySelector("#placeTButton");
const placeCTButton = document.querySelector("#placeCTButton");
const tAreaLabel = document.querySelector("#tAreaLabel");
const ctAreaLabel = document.querySelector("#ctAreaLabel");
const engineSelect = document.querySelector("#engineSelect");
const phaseCCheckpointFields = document.querySelector("#phaseCCheckpointFields");
const phaseCTCheckpoint = document.querySelector("#phaseCTCheckpoint");
const phaseCCTCheckpoint = document.querySelector("#phaseCCTCheckpoint");
const siteField = document.querySelector("#siteField");
const siteSelect = document.querySelector("#siteSelect");
const bombStateSelect = document.querySelector("#bombStateSelect");
const staticLosCheck = document.querySelector("#staticLosCheck");
const seedInput = document.querySelector("#seedInput");
const runButton = document.querySelector("#runButton");
const scenarioStatus = document.querySelector("#scenarioStatus");

const fallbackWorld = {
  minX: -90,
  maxX: 130,
  minY: -120,
  maxY: 80,
};

let trace = null;
let mapData = null;
let frameIndex = 0;
let timer = null;
let mapImage = null;
let mapDrawRect = null;
let navMask = null;
let selectedSide = "T";
let playbackSpeed = 1;
const selectedAreas = { T: null, CT: null };

drawEmpty();
updateCheckpointFields();
loadInitialState();

fileInput.addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  await setTrace(JSON.parse(await file.text()));
});

placeTButton.addEventListener("click", () => setSelectedSide("T"));
placeCTButton.addEventListener("click", () => setSelectedSide("CT"));

canvas.addEventListener("click", (event) => {
  if (!activeMap() || !mapDrawRect) return;
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  const point = {
    x: (event.clientX - rect.left) * scaleX,
    y: (event.clientY - rect.top) * scaleY,
  };
  const area = nearestAreaByCanvasPoint(point);
  if (!area) return;
  selectedAreas[selectedSide] = area.id;
  updateAreaLabels();
  render();
});

siteSelect.addEventListener("change", () => {
  if (siteSelect.value === "auto" && bombStateSelect.value !== "unplanted") {
    bombStateSelect.value = "unplanted";
  }
  if (siteSelect.value === "A" && bombStateSelect.value === "planted_b") {
    bombStateSelect.value = "unplanted";
  }
  if (siteSelect.value === "B" && bombStateSelect.value === "planted_a") {
    bombStateSelect.value = "unplanted";
  }
  render();
});

bombStateSelect.addEventListener("change", () => {
  if (bombStateSelect.value === "planted_a") siteSelect.value = "A";
  if (bombStateSelect.value === "planted_b") siteSelect.value = "B";
  render();
});

engineSelect.addEventListener("change", updateCheckpointFields);

runButton.addEventListener("click", async () => {
  await runSimulation();
});

scrubber.addEventListener("input", () => {
  frameIndex = Number(scrubber.value);
  render();
});

prevButton.addEventListener("click", () => {
  frameIndex = Math.max(0, frameIndex - 1);
  scrubber.value = String(frameIndex);
  render();
});

nextButton.addEventListener("click", () => {
  frameIndex = Math.min((trace?.frames.length ?? 1) - 1, frameIndex + 1);
  scrubber.value = String(frameIndex);
  render();
});

playButton.addEventListener("click", () => {
  if (timer) {
    stop();
    return;
  }
  startPlayback();
});

for (const button of speedButtons) {
  button.addEventListener("click", () => {
    playbackSpeed = Number(button.dataset.speed ?? 1);
    updateSpeedButtons();
    if (timer) {
      stop();
      startPlayback();
    }
  });
}

function startPlayback() {
  if (!trace?.frames?.length) return;
  playButton.textContent = "Pause";
  timer = window.setInterval(() => {
    frameIndex += 1;
    if (frameIndex >= trace.frames.length) {
      frameIndex = trace.frames.length - 1;
      stop();
    }
    scrubber.value = String(frameIndex);
    render();
  }, playbackIntervalMs());
}

async function loadInitialState() {
  const url = new URL(window.location.href);
  const traceUrl = url.searchParams.get("trace");
  if (traceUrl) {
    const response = await fetch(traceUrl);
    await setTrace(await response.json());
    return;
  }
  await loadMapData();
  updateCheckpointFields();
  scenarioStatus.textContent = "Click the map to place T and CT.";
  render();
}

async function loadMapData() {
  const response = await fetch("/api/dust2-map");
  mapData = await response.json();
  await loadTraceImage({ map: mapData });
}

async function setTrace(nextTrace) {
  trace = nextTrace;
  mapData = nextTrace.map ?? mapData;
  frameIndex = 0;
  scrubber.max = String(Math.max(0, trace.frames.length - 1));
  scrubber.value = "0";
  const selected = trace.summary?.selected_areas;
  if (selected?.T) selectedAreas.T = selected.T;
  if (selected?.CT) selectedAreas.CT = selected.CT;
  if (trace.summary?.site_choice === "auto") {
    siteSelect.value = "auto";
  } else if (trace.summary?.site) {
    siteSelect.value = trace.summary.site;
  }
  if (trace.summary?.bomb_state) bombStateSelect.value = trace.summary.bomb_state;
  stop();
  await loadTraceImage(trace);
  updateAreaLabels();
  render();
}

async function loadTraceImage(source) {
  mapImage = null;
  mapDrawRect = null;
  navMask = null;
  const url = source?.map?.imageDataUrl;
  if (!url) return;
  mapImage = new Image();
  await new Promise((resolve, reject) => {
    mapImage.onload = resolve;
    mapImage.onerror = reject;
    mapImage.src = url;
  });
}

async function runSimulation() {
  if (!selectedAreas.T || !selectedAreas.CT) {
    scenarioStatus.textContent = "Set both T and CT areas first.";
    return;
  }
  runButton.disabled = true;
  const engine = engineSelect.value;
  const isRl = engine.startsWith("rl-");
  const modelPhase = rlModelPhaseForEngine(engine);
  const engineName = rlEngineLabel(modelPhase);
  scenarioStatus.textContent = isRl ? `Running ${engineName}...` : "Simulating rules...";
  try {
    const response = await fetch(isRl ? "/api/rl-simulate" : "/api/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tAreaId: selectedAreas.T,
        ctAreaId: selectedAreas.CT,
        site: siteSelect.value,
        bombState: bombStateSelect.value,
        seed: Number(seedInput.value || 2607),
        staticLos: staticLosCheck.checked,
        frameStride: 10,
        roundSeconds: 40,
        bombTimerSeconds: 40,
        tickSeconds: 0.01,
        maxTurnDegPerTick: 18,
        maxPitchTurnDegPerTick: 18,
        modelPhase,
        tCheckpoint: phaseCTCheckpoint.value.trim() || undefined,
        ctCheckpoint: phaseCCTCheckpoint.value.trim() || undefined,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error ?? "simulation failed");
    await setTrace(payload);
    const engineLabel = payload.rl?.status?.startsWith("trained-") ? rlEngineLabel(payload.rl?.modelPhase ?? modelPhase) : "Rules";
    scenarioStatus.textContent = `Done (${engineLabel}): site ${payload.summary?.site ?? "-"}, ${payload.summary?.terminal_reason ?? "terminal"}`;
  } catch (error) {
    scenarioStatus.textContent = error instanceof Error ? error.message : String(error);
  } finally {
    runButton.disabled = false;
  }
}

function rlModelPhaseForEngine(engine) {
  if (engine === "rl-a") return "A";
  if (engine === "rl-b-candidate") return "B_CANDIDATE";
  if (engine === "rl-c-stable") return "C_STABLE";
  if (engine === "rl-c-candidate") return "C_CANDIDATE";
  return "B";
}

function rlEngineLabel(modelPhase) {
  if (modelPhase === "A") return "Phase A RL";
  if (modelPhase === "B_CANDIDATE") return "Phase B RL Candidate";
  if (modelPhase === "C_STABLE") return "Phase C Stable";
  if (modelPhase === "C_CANDIDATE") return "Phase C Candidate";
  return "Phase B RL Stable";
}

function updateCheckpointFields() {
  const isPhaseC = engineSelect.value.startsWith("rl-c-");
  phaseCCheckpointFields.hidden = !isPhaseC;
  siteField.hidden = isPhaseC;
  siteField.style.display = isPhaseC ? "none" : "";
  siteSelect.disabled = isPhaseC;
  if (isPhaseC) {
    if (bombStateSelect.value === "planted_a") siteSelect.value = "A";
    else if (bombStateSelect.value === "planted_b") siteSelect.value = "B";
    else siteSelect.value = "auto";
  }
}

function setSelectedSide(side) {
  selectedSide = side;
  placeTButton.classList.toggle("active", side === "T");
  placeCTButton.classList.toggle("active", side === "CT");
  scenarioStatus.textContent = `Placing ${side}`;
}

function stop() {
  if (timer) window.clearInterval(timer);
  timer = null;
  playButton.textContent = "Play";
}

function render() {
  if (trace?.frames?.length) {
    const frame = trace.frames[frameIndex];
    if (trace.schemaVersion?.startsWith("dust2")) {
      drawDust2Frame(frame);
    } else {
      drawLegacyFrame(frame);
    }
    frameLabel.textContent = `${frameIndex + 1} / ${trace.frames.length}`;
    winnerLabel.textContent = trace.summary?.winner ?? trace.terminal?.winner ?? "-";
    valueLabel.textContent = trace.summary?.terminal_reason ?? `${Math.round((frame.predicted_win_probability ?? 0) * 100)}%`;
    renderTraceMeta(frame);
    renderEvents(frame);
    return;
  }
  drawScenarioMap();
  frameLabel.textContent = "0 / 0";
  winnerLabel.textContent = "-";
  valueLabel.textContent = "-";
  renderTraceMeta(null);
  renderEvents({ events: [] });
}

function drawEmpty() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#242823";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#aab6ad";
  ctx.font = "18px system-ui";
  ctx.fillText("Loading Dust2 scenario editor.", 32, 48);
}

function drawScenarioMap() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#121513";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  drawDust2MapBase();
  drawDust2NavOverlay();
  drawDust2BombSites();
  drawScenarioSelection();
}

function drawDust2Frame(frame) {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#121513";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  drawDust2MapBase();
  drawDust2NavOverlay();
  drawDust2BombSites();
  drawDust2Utilities(frame.state.utilities ?? []);
  drawDust2Bomb(frame.state.bomb);
  drawScenarioSelection();
  drawDust2Agent(frame.state.agents.T, "#e9bf55", "T");
  drawDust2Agent(frame.state.agents.CT, "#62a8ff", "CT");
}

function drawDust2MapBase() {
  if (!mapImage) {
    ctx.fillStyle = "#242823";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    return;
  }
  const margin = 16;
  const scale = Math.min((canvas.width - margin * 2) / mapImage.naturalWidth, (canvas.height - margin * 2) / mapImage.naturalHeight);
  const width = mapImage.naturalWidth * scale;
  const height = mapImage.naturalHeight * scale;
  const x = (canvas.width - width) / 2;
  const y = (canvas.height - height) / 2;
  mapDrawRect = { x, y, width, height, scale };
  ctx.globalAlpha = 0.86;
  ctx.drawImage(mapImage, x, y, width, height);
  ctx.globalAlpha = 1;
}

function drawDust2NavOverlay() {
  const areas = activeMap()?.areas ?? [];
  if (!areas.length || !mapDrawRect) return;
  ctx.lineWidth = 0.55;
  ctx.strokeStyle = "rgba(214, 229, 217, 0.12)";
  ctx.fillStyle = "rgba(62, 92, 69, 0.05)";
  for (const area of areas) {
    if (!area.polygon?.length) continue;
    ctx.beginPath();
    const first = pixelToCanvas(area.polygon[0]);
    ctx.moveTo(first.x, first.y);
    for (const point of area.polygon.slice(1)) {
      const p = pixelToCanvas(point);
      ctx.lineTo(p.x, p.y);
    }
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
  }
}

function drawDust2BombSites() {
  const sites = activeMap()?.bombSites ?? {};
  const activeSite = activeSiteForDisplay();
  for (const [siteId, site] of Object.entries(sites)) {
    const areaIds = site.areaIds ?? [];
    const isActive = activeSite ? siteId === activeSite : true;
    for (const areaId of areaIds) {
      const area = areaById(areaId);
      if (!area?.polygon?.length) continue;
      drawMapPolygon(
        area.polygon,
        isActive ? "rgba(255, 88, 70, 0.24)" : "rgba(255, 88, 70, 0.10)",
        isActive ? "#ffde75" : "rgba(255, 116, 88, 0.72)",
        isActive ? 2 : 1,
      );
    }
    const p = gameToCanvas(site.position);
    ctx.fillStyle = "#f8f5df";
    ctx.font = "bold 14px system-ui";
    ctx.fillText(siteId, p.x + 8, p.y - 8);
  }
}

function drawMapPolygon(points, fillStyle, strokeStyle, lineWidth) {
  if (!points.length) return;
  const first = pixelToCanvas(points[0]);
  ctx.beginPath();
  ctx.moveTo(first.x, first.y);
  for (const point of points.slice(1)) {
    const p = pixelToCanvas(point);
    ctx.lineTo(p.x, p.y);
  }
  ctx.closePath();
  ctx.fillStyle = fillStyle;
  ctx.strokeStyle = strokeStyle;
  ctx.lineWidth = lineWidth;
  ctx.fill();
  ctx.stroke();
}

function drawScenarioSelection() {
  for (const [side, areaId] of Object.entries(selectedAreas)) {
    if (!areaId) continue;
    const area = areaById(areaId);
    if (!area) continue;
    const p = pixelToCanvas(area.pixelCentroid);
    const color = side === "T" ? "#e9bf55" : "#62a8ff";
    ctx.strokeStyle = "#101310";
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.arc(p.x, p.y, 16, 0, Math.PI * 2);
    ctx.stroke();
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(p.x, p.y, 12, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#101310";
    ctx.font = "bold 12px system-ui";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(side, p.x, p.y);
    ctx.textAlign = "start";
    ctx.textBaseline = "alphabetic";
  }
}

function drawDust2Utilities(utilities) {
  for (const utility of utilities) {
    const p = gameToCanvas(utility.position);
    const r = worldRadiusToCanvas(utility.radius);
    ctx.fillStyle = utility.kind === "smoke" ? "rgba(190, 201, 201, 0.34)" : "rgba(255, 98, 43, 0.34)";
    ctx.strokeStyle = utility.kind === "smoke" ? "rgba(238, 246, 246, 0.72)" : "rgba(255, 145, 76, 0.82)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }
}

function drawDust2Bomb(bomb) {
  if (!bomb?.position) return;
  const p = gameToCanvas(bomb.position);
  ctx.fillStyle = bomb.planted ? "#ffdf6c" : "#b9c2ba";
  ctx.strokeStyle = "#161810";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.rect(p.x - 7, p.y - 7, 14, 14);
  ctx.fill();
  ctx.stroke();
}

function drawDust2Agent(agent, color, label) {
  if (!agent) return;
  const p = gameToCanvas(agent.position);
  const aim = degToRad(agent.aimDeg ?? agent.aim_deg ?? 0);
  const rayEnd = agent.aimRayEnd ? gameToCanvas(agent.aimRayEnd) : aimRayEnd(p, aim);
  ctx.strokeStyle = agent.isAlive ?? agent.is_alive ? colorWithAlpha(color, agent.aimRayBlocked ? 0.58 : 0.72) : "rgba(255,255,255,0.28)";
  ctx.lineWidth = 1.2;
  line(p, rayEnd);
  ctx.fillStyle = color;
  ctx.globalAlpha = agent.isAlive ?? agent.is_alive ? 1 : 0.38;
  ctx.beginPath();
  ctx.arc(p.x, p.y, 8, 0, Math.PI * 2);
  ctx.fill();
  ctx.globalAlpha = 1;
  ctx.fillStyle = "#101310";
  ctx.font = "bold 12px system-ui";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(label, p.x, p.y);
  ctx.textAlign = "start";
  ctx.textBaseline = "alphabetic";
}

function aimRayEnd(start, aim) {
  if (!mapDrawRect) return start;
  const dx = Math.cos(aim);
  const dy = -Math.sin(aim);
  const maxDistance = Math.hypot(canvas.width, canvas.height);
  let lastDistance = 0;
  let blockedDistance = null;
  let firstBlockedDistance = null;
  let blockedRun = 0;
  for (let distance = 6; distance <= maxDistance; distance += 3) {
    const point = {
      x: start.x + dx * distance,
      y: start.y + dy * distance,
    };
    if (!pointInsideMapDrawRect(point) || !pointOnWalkableMask(point)) {
      firstBlockedDistance ??= distance;
      blockedRun += 3;
      if (blockedRun >= 18) {
        blockedDistance = firstBlockedDistance;
        break;
      }
      continue;
    }
    lastDistance = distance;
    firstBlockedDistance = null;
    blockedRun = 0;
  }
  if (blockedDistance === null) {
    return {
      x: start.x + dx * lastDistance,
      y: start.y + dy * lastDistance,
    };
  }
  let low = lastDistance;
  let high = blockedDistance;
  for (let i = 0; i < 5; i += 1) {
    const mid = (low + high) / 2;
    const point = {
      x: start.x + dx * mid,
      y: start.y + dy * mid,
    };
    if (pointInsideMapDrawRect(point) && pointOnWalkableMask(point)) {
      low = mid;
    } else {
      high = mid;
    }
  }
  return {
    x: start.x + dx * low,
    y: start.y + dy * low,
  };
}

function drawDust2Hud(frame) {
  const behavior = trace.summary?.behavior ?? {};
  const siteLabel = trace.summary?.site_choice === "auto" ? `auto->${trace.summary?.site ?? "?"}` : trace.summary?.site ?? siteSelect.value;
  const tIntent = frame.state.agents.T.macroIntent ?? "-";
  ctx.fillStyle = "rgba(0, 0, 0, 0.52)";
  ctx.fillRect(18, 18, 460, 150);
  ctx.fillStyle = "#f0f4ef";
  ctx.font = "14px system-ui";
  ctx.fillText(`de_dust2 | tick ${frame.tick} | ${frame.seconds.toFixed(2)}s`, 34, 44);
  ctx.fillText(`T ${frame.state.agents.T.action} | aim ${frame.state.agents.T.aimContext}`, 34, 68);
  ctx.fillText(`CT ${frame.state.agents.CT.action} | aim ${frame.state.agents.CT.aimContext}`, 34, 90);
  ctx.fillText(`site ${siteLabel} | bomb ${trace.summary?.bomb_state ?? bombStateSelect.value}`, 34, 112);
  ctx.fillText(`T intent ${tIntent}`, 34, 134);
  ctx.fillText(`aim quality ${Math.round((behavior.aim_quality_ratio ?? 0) * 100)}% | winner ${trace.summary?.winner ?? "-"}`, 34, 156);
}

function drawLegacyFrame(frame) {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#242823";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  drawGrid();
  drawWall({ x: 0, y: -100 }, { x: 0, y: 0 });
  drawLegacyAgent(frame.state.agents.T, "#e5b84b", "T", frame.observations.learner_enemy_visible);
  drawLegacyAgent(frame.state.agents.CT, "#61a6ff", "CT", frame.observations.opponent_enemy_visible);
}

function renderTraceMeta(frame) {
  if (!frame || !trace?.frames?.length) {
    setTraceMeta([["Status", activeMap() ? "Click the map to place T and CT, then run a simulation." : "Loading Dust2 scenario editor."]]);
    return;
  }
  if (trace.schemaVersion?.startsWith("dust2")) {
    const behavior = trace.summary?.behavior ?? {};
    const siteLabel = trace.summary?.site_choice === "auto" ? `auto->${trace.summary?.site ?? "?"}` : trace.summary?.site ?? siteSelect.value;
    const t = frame.state.agents.T;
    const ct = frame.state.agents.CT;
    setTraceMeta([
      ["Trace", `de_dust2 | tick ${frame.tick} | ${frame.seconds.toFixed(2)}s`],
      ["T", `${t.action} | aim ${t.aimContext}`],
      ["CT", `${ct.action} | aim ${ct.aimContext}`],
      ["Round", `site ${siteLabel} | bomb ${trace.summary?.bomb_state ?? bombStateSelect.value}`],
      ["Intent", `T ${t.macroIntent ?? "-"}`],
      ["Result", `aim ${Math.round((behavior.aim_quality_ratio ?? 0) * 100)}% | winner ${trace.summary?.winner ?? "-"}`],
    ]);
    return;
  }
  setTraceMeta([
    ["Trace", `tick ${frame.tick} | ${frame.seconds?.toFixed?.(1) ?? "-"}s`],
    ["T", `action ${frame.learner_action?.join(",") ?? "-"}`],
    ["CT", `action ${frame.opponent_action?.join(",") ?? "-"}`],
  ]);
}

function setTraceMeta(items) {
  traceMeta.replaceChildren();
  for (const [label, value] of items) {
    const item = document.createElement("span");
    item.className = "meta-item";
    const key = document.createElement("strong");
    key.textContent = label;
    const text = document.createTextNode(value);
    item.append(key, text);
    traceMeta.append(item);
  }
}

function updateSpeedButtons() {
  for (const button of speedButtons) {
    button.classList.toggle("active", Number(button.dataset.speed) === playbackSpeed);
  }
}

function playbackIntervalMs() {
  const frameMs = playbackFrameDurationMs();
  return Math.max(16, Math.round(frameMs / playbackSpeed));
}

function playbackFrameDurationMs() {
  const frames = trace?.frames ?? [];
  const deltas = [];
  for (let i = 1; i < Math.min(frames.length, 24); i += 1) {
    const current = Number(frames[i]?.seconds);
    const previous = Number(frames[i - 1]?.seconds);
    const delta = current - previous;
    if (Number.isFinite(delta) && delta > 0) deltas.push(delta);
  }
  if (!deltas.length) return trace?.schemaVersion?.startsWith("dust2") ? 200 : 140;
  deltas.sort((a, b) => a - b);
  return deltas[Math.floor(deltas.length / 2)] * 1000;
}

function drawGrid() {
  ctx.strokeStyle = "#30372f";
  ctx.lineWidth = 1;
  for (let x = -80; x <= 120; x += 20) {
    const a = projectLegacy({ x, y: fallbackWorld.minY });
    const b = projectLegacy({ x, y: fallbackWorld.maxY });
    line(a, b);
  }
  for (let y = -120; y <= 80; y += 20) {
    const a = projectLegacy({ x: fallbackWorld.minX, y });
    const b = projectLegacy({ x: fallbackWorld.maxX, y });
    line(a, b);
  }
}

function drawWall(from, to) {
  const a = projectLegacy(from);
  const b = projectLegacy(to);
  ctx.strokeStyle = "#eef5ea";
  ctx.lineWidth = 7;
  line(a, b);
}

function drawLegacyAgent(agent, color, label, visibleFlag) {
  const p = projectLegacy(agent.position);
  const aim = degToRad(agent.aim_deg);
  const rayEnd = {
    x: p.x + Math.cos(aim) * 58,
    y: p.y - Math.sin(aim) * 58,
  };
  ctx.strokeStyle = visibleFlag ? "#ffffff" : color;
  ctx.lineWidth = 2;
  line(p, rayEnd);
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(p.x, p.y, 14, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#111";
  ctx.font = "bold 13px system-ui";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(label, p.x, p.y);
  ctx.textAlign = "start";
  ctx.textBaseline = "alphabetic";
}

function drawLegacyHud(frame) {
  ctx.fillStyle = "rgba(0, 0, 0, 0.42)";
  ctx.fillRect(18, 18, 310, 84);
  ctx.fillStyle = "#f0f4ef";
  ctx.font = "15px system-ui";
  ctx.fillText(`tick ${frame.tick} | ${frame.seconds.toFixed(1)}s`, 34, 44);
  ctx.fillText(`T action ${frame.learner_action.join(",")}`, 34, 68);
  ctx.fillText(`CT action ${frame.opponent_action.join(",")}`, 34, 90);
}

function renderEvents(frame) {
  eventList.replaceChildren();
  const events = cumulativeEventsForFrame(frame);
  if (events.length === 0) {
    const item = document.createElement("li");
    item.textContent = "No events yet.";
    eventList.append(item);
    return;
  }
  for (const event of events) {
    const item = document.createElement("li");
    item.textContent = formatEvent(event);
    eventList.append(item);
  }
}

function cumulativeEventsForFrame(frame) {
  if (trace?.schemaVersion?.startsWith("dust2") && Array.isArray(trace.events) && Number.isFinite(frame.tick)) {
    return trace.events.filter((event) => Number(event.tick ?? -1) <= frame.tick);
  }
  return frame.events ?? [];
}

function formatEvent(event) {
  if (event.type === "site-choice") return `${event.side} chose ${event.site} (${event.mode})`;
  if (event.type === "site-rotate") return `${event.side} rotated ${event.from}->${event.to} (${event.reason})`;
  if (event.type === "macro-intent") return `${event.side} intent ${event.intent}`;
  if (event.type === "search-point") return `${event.side} searched likely angle`;
  if (event.type === "angle-clear") return `${event.side} ${event.kind ?? "clear"} angle`;
  if (event.type === "visible") return `${event.viewer} saw ${event.target}`;
  if (event.type === "shot") {
    const p = Math.round((event.probability ?? 0) * 100);
    const group = event.hitGroup ? ` ${event.hitGroup}` : "";
    const damage = Number(event.damage ?? 0);
    const hp = Number(event.targetHp ?? NaN);
    const suffix = event.hit ? `, dmg=${Math.round(damage * 100)}, hp=${Number.isFinite(hp) ? Math.round(hp * 100) : "?"}` : "";
    return `${event.shooter} shot ${event.target}${group} (${p}%, hit=${event.hit}${suffix})`;
  }
  if (event.type === "withheld-shot") {
    const p = Math.round((event.probability ?? 0) * 100);
    return `${event.shooter} withheld shot on ${event.target} (${p}%, ${event.reason})`;
  }
  if (event.type === "reload") return `${event.side} reloaded`;
  if (event.type === "smoke") return `${event.side} smoke deployed`;
  if (event.type === "fire") return `${event.side} fire deployed`;
  if (event.type === "fire-damage") return `${event.side} burning, hp=${event.hp}`;
  if (event.type === "jump") return `${event.side} jump/climb ${event.fromArea}->${event.toArea}`;
  if (event.type === "plant-progress") return `T planting ${event.progressTicks}/${event.requiredTicks}`;
  if (event.type === "bomb-planted") return `bomb planted ${event.site ?? ""}`;
  if (event.type === "defuse-progress") return `CT defusing ${event.progressTicks}/${event.requiredTicks}`;
  if (event.type === "bomb-defused") return "bomb defused";
  if (event.type === "bomb-exploded") {
    const affected = Array.isArray(event.affected) && event.affected.length ? `, affected=${event.affected.map((row) => row.side).join("/")}` : "";
    return `bomb exploded${affected}`;
  }
  if (event.type === "sound") return `${event.listener} heard ${event.source} (${Array.isArray(event.areaIds) ? event.areaIds.length : "?"} areas)`;
  if (event.type === "death") return `death: ${Array.isArray(event.dead) ? event.dead.join("/") : ""}`;
  if (event.type === "terminal") return `terminal: ${event.reason}, winner=${event.winner}`;
  return JSON.stringify(event);
}

function nearestAreaByCanvasPoint(point) {
  const areas = activeMap()?.areas ?? [];
  if (!areas.length || !mapDrawRect) return null;
  let best = null;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (const area of areas) {
    const p = pixelToCanvas(area.pixelCentroid);
    const d = Math.hypot(p.x - point.x, p.y - point.y);
    if (d < bestDistance) {
      best = area;
      bestDistance = d;
    }
  }
  return best;
}

function activeMap() {
  return trace?.map ?? mapData;
}

function activeSiteForDisplay() {
  if (trace?.summary?.site) return trace.summary.site;
  return siteSelect.value === "auto" ? null : siteSelect.value;
}

function areaById(areaId) {
  return (activeMap()?.areas ?? []).find((area) => String(area.id) === String(areaId));
}

function updateAreaLabels() {
  tAreaLabel.textContent = selectedAreas.T ?? "-";
  ctAreaLabel.textContent = selectedAreas.CT ?? "-";
}

function gameToCanvas(point) {
  const map = activeMap();
  if (!map?.metadata || !mapDrawRect) return { x: 0, y: 0 };
  const metadata = map.metadata;
  const pixel = {
    x: (point.x - metadata.pos_x) / metadata.scale,
    y: (metadata.pos_y - point.y) / metadata.scale,
  };
  return pixelToCanvas(pixel);
}

function pixelToCanvas(point) {
  if (!mapDrawRect) return { x: point.x, y: point.y };
  return {
    x: mapDrawRect.x + point.x * mapDrawRect.scale,
    y: mapDrawRect.y + point.y * mapDrawRect.scale,
  };
}

function pointInsideMapDrawRect(point) {
  if (!mapDrawRect) return false;
  return (
    point.x >= mapDrawRect.x &&
    point.x <= mapDrawRect.x + mapDrawRect.width &&
    point.y >= mapDrawRect.y &&
    point.y <= mapDrawRect.y + mapDrawRect.height
  );
}

function pointOnWalkableMask(point) {
  const mask = ensureNavMask();
  if (!mask) return true;
  const x = Math.round(point.x);
  const y = Math.round(point.y);
  if (x < 0 || x >= canvas.width || y < 0 || y >= canvas.height) return false;
  return mask.data[(y * canvas.width + x) * 4 + 3] > 20;
}

function ensureNavMask() {
  const areas = activeMap()?.areas ?? [];
  if (!areas.length || !mapDrawRect) return null;
  const key = [
    canvas.width,
    canvas.height,
    areas.length,
    mapDrawRect.x.toFixed(2),
    mapDrawRect.y.toFixed(2),
    mapDrawRect.width.toFixed(2),
    mapDrawRect.height.toFixed(2),
  ].join(":");
  if (navMask?.key === key) return navMask;

  const maskCanvas = document.createElement("canvas");
  maskCanvas.width = canvas.width;
  maskCanvas.height = canvas.height;
  const maskCtx = maskCanvas.getContext("2d");
  maskCtx.fillStyle = "#fff";
  maskCtx.strokeStyle = "#fff";
  maskCtx.lineWidth = 2.5;
  for (const area of areas) {
    if (!area.polygon?.length) continue;
    const first = pixelToCanvas(area.polygon[0]);
    maskCtx.beginPath();
    maskCtx.moveTo(first.x, first.y);
    for (const point of area.polygon.slice(1)) {
      const p = pixelToCanvas(point);
      maskCtx.lineTo(p.x, p.y);
    }
    maskCtx.closePath();
    maskCtx.fill();
    maskCtx.stroke();
  }
  navMask = {
    key,
    data: maskCtx.getImageData(0, 0, canvas.width, canvas.height).data,
  };
  return navMask;
}

function worldRadiusToCanvas(radius) {
  const map = activeMap();
  if (!map?.metadata || !mapDrawRect) return radius;
  return (radius / map.metadata.scale) * mapDrawRect.scale;
}

function projectLegacy(point) {
  const margin = 48;
  const width = canvas.width - margin * 2;
  const height = canvas.height - margin * 2;
  return {
    x: margin + ((point.x - fallbackWorld.minX) / (fallbackWorld.maxX - fallbackWorld.minX)) * width,
    y: margin + (1 - (point.y - fallbackWorld.minY) / (fallbackWorld.maxY - fallbackWorld.minY)) * height,
  };
}

function line(a, b) {
  ctx.beginPath();
  ctx.moveTo(a.x, a.y);
  ctx.lineTo(b.x, b.y);
  ctx.stroke();
}

function degToRad(deg) {
  return (deg * Math.PI) / 180;
}

function colorWithAlpha(hex, alpha) {
  const normalized = hex.startsWith("#") ? hex.slice(1) : hex;
  if (normalized.length !== 6) return hex;
  const r = Number.parseInt(normalized.slice(0, 2), 16);
  const g = Number.parseInt(normalized.slice(2, 4), 16);
  const b = Number.parseInt(normalized.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
