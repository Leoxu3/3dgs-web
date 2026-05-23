const viewer = document.querySelector("#viewer");
const rawImage = document.querySelector("#rawImage");
const refinedImage = document.querySelector("#refinedImage");
const scenePath = document.querySelector("#scenePath");
const sceneMeta = document.querySelector("#sceneMeta");
const sceneForm = document.querySelector("#sceneForm");
const sceneInput = document.querySelector("#sceneInput");
const sceneClear = document.querySelector("#sceneClear");
const sceneOptions = document.querySelector("#sceneOptions");
const cameraStateLabel = document.querySelector("#cameraState");
const pipelineState = document.querySelector("#pipelineState");
const cameraReadout = document.querySelector("#cameraReadout");
const renderTime = document.querySelector("#renderTime");
const refineLatency = document.querySelector("#refineLatency");
const fallbackState = document.querySelector("#fallbackState");
const modeTabs = Array.from(document.querySelectorAll(".mode-tab"));

const IDLE_DELAY_MS = 700;
const INTERACTIVE_RENDER_MIN_INTERVAL_MS = 90;
const CAMERA_LIMITS = {
  minPitch: -1.45,
  maxPitch: 1.45,
  minDistance: 0.4,
  maxDistance: 20,
};

const camera = {
  yaw: 0,
  pitch: 0,
  distance: 3,
  target: [0, 0, 0],
  fov: 45,
  up_axis: "z",
};

const CAMERA_ROTATE_SPEED = 0.01;
const CAMERA_PAN_SPEED = 0.0018;
const MAX_POINTER_DELTA = 80;

let isDragging = false;
let dragMode = "rotate";
let lastPointer = { x: 0, y: 0 };
let idleTimer = null;
let interactiveRenderTimer = null;
let interactiveRenderInFlight = false;
let interactiveRenderPending = false;
let lastInteractiveRenderAt = 0;
let renderSeq = 0;
let cameraVersion = 0;
let refineSeq = 0;
let activeRefineController = null;

function setPipeline(message, className = "") {
  pipelineState.textContent = message;
  pipelineState.className = className;
}

function isAbort(error) {
  return error.name === "AbortError";
}

function cameraSnapshot() {
  return {
    yaw: camera.yaw,
    pitch: camera.pitch,
    distance: camera.distance,
    target: [...camera.target],
    fov: camera.fov,
    up_axis: camera.up_axis,
  };
}

function updateCameraReadout() {
  const [x, y, z] = camera.target;
  cameraReadout.textContent =
    `Camera: yaw ${camera.yaw.toFixed(2)} | pitch ${camera.pitch.toFixed(2)} | ` +
    `dist ${camera.distance.toFixed(2)} | up ${camera.up_axis.toUpperCase()} | ` +
    `target ${x.toFixed(2)}, ${y.toFixed(2)}, ${z.toFixed(2)}`;
}

async function postJson(url, payload, options = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal: options.signal,
  });
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response));
  }
  return response.json();
}

async function deleteJson(url) {
  const response = await fetch(url, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response));
  }
  return response.json();
}

async function responseErrorMessage(response) {
  try {
    const data = await response.json();
    if (typeof data.detail === "string") return data.detail;
  } catch (_error) {
    // Fall through to the HTTP status line.
  }
  return `${response.status} ${response.statusText}`;
}

function renderSize(quality) {
  const rect = viewer.getBoundingClientRect();
  const scale = quality === "idle" ? 1 : 0.28;
  const minWidth = quality === "idle" ? 320 : 240;
  const minHeight = quality === "idle" ? 240 : 160;
  let width = Math.max(minWidth, Math.round(rect.width * scale));
  let height = Math.max(minHeight, Math.round(rect.height * scale));
  if (quality === "interactive") {
    const capScale = Math.min(1, 520 / width, 320 / height);
    width = Math.max(minWidth, Math.round(width * capScale));
    height = Math.max(minHeight, Math.round(height * capScale));
  }
  return {
    width,
    height,
  };
}

async function renderFrame(quality = "interactive") {
  const seq = ++renderSeq;
  const requestedCameraVersion = cameraVersion;
  const size = renderSize(quality);

  const result = await postJson("/api/render", {
    camera: cameraSnapshot(),
    width: size.width,
    height: size.height,
    quality,
  });

  if (seq !== renderSeq) return null;
  if (quality === "idle" && requestedCameraVersion !== cameraVersion) return null;
  rawImage.src = result.image_data_url;
  renderTime.textContent = `Render: ${result.render_ms} ms | ${result.renderer}`;
  return result;
}

function scheduleIdleRefine() {
  window.clearTimeout(idleTimer);
  idleTimer = window.setTimeout(runIdleRefine, IDLE_DELAY_MS);
}

function markMoving() {
  refineSeq += 1;
  if (activeRefineController) {
    activeRefineController.abort();
  }
  cameraStateLabel.textContent = "Camera moving";
  cameraStateLabel.className = "status-busy";
  setPipeline("Rendering raw", "status-busy");
}

function cameraChanged() {
  cameraVersion += 1;
  updateCameraReadout();
  markMoving();
  scheduleInteractiveRender();
  scheduleIdleRefine();
}

function scheduleInteractiveRender(immediate = false) {
  interactiveRenderPending = true;
  if (interactiveRenderInFlight) return;

  window.clearTimeout(interactiveRenderTimer);
  const elapsed = performance.now() - lastInteractiveRenderAt;
  const delay = immediate ? 0 : Math.max(0, INTERACTIVE_RENDER_MIN_INTERVAL_MS - elapsed);
  interactiveRenderTimer = window.setTimeout(flushInteractiveRender, delay);
}

async function flushInteractiveRender() {
  if (interactiveRenderInFlight || !interactiveRenderPending) return;

  interactiveRenderPending = false;
  interactiveRenderInFlight = true;
  lastInteractiveRenderAt = performance.now();

  try {
    await interactiveRender();
  } finally {
    interactiveRenderInFlight = false;
    if (interactiveRenderPending) {
      scheduleInteractiveRender();
    }
  }
}

async function runIdleRefine() {
  const seq = ++refineSeq;
  cameraStateLabel.textContent = "Camera idle";
  cameraStateLabel.className = "status-ok";
  setPipeline("Refining", "status-busy");

  try {
    const raw = await renderFrame("idle");
    if (!raw || seq !== refineSeq) return;

    activeRefineController = new AbortController();
    const refined = await postJson("/api/refine", {
      image_data_url: raw.image_data_url,
      camera: cameraSnapshot(),
    }, { signal: activeRefineController.signal });
    if (seq !== refineSeq) return;

    refinedImage.src = refined.image_data_url;
    refineLatency.textContent = `Refine: ${refined.latency_ms} ms`;
    fallbackState.textContent = refined.fallback_mode
      ? `Fallback: ${refined.message}`
      : "Fallback: off";
    fallbackState.className = refined.fallback_mode ? "status-busy" : "status-ok";
    setPipeline(refined.status === "fallback" ? "Fallback done" : "Refine done", "status-ok");
  } catch (error) {
    if (isAbort(error)) return;
    setPipeline(`Error: ${error.message}`, "status-error");
  }
}

async function interactiveRender() {
  try {
    await renderFrame("interactive");
  } catch (error) {
    if (isAbort(error)) return;
    setPipeline(`Error: ${error.message}`, "status-error");
  }
}

function rotateCamera(dx, dy) {
  camera.yaw += dx * CAMERA_ROTATE_SPEED;
  camera.pitch = Math.max(
    CAMERA_LIMITS.minPitch,
    Math.min(CAMERA_LIMITS.maxPitch, camera.pitch - dy * CAMERA_ROTATE_SPEED)
  );
}

function cameraBasis() {
  const offset = orbitCameraOffset();
  const forward = normalizeVector(scaleVector(offset, -1));
  const worldUp = axisVector(camera.up_axis);
  const right = normalizeVector(cross(forward, worldUp));
  const down = normalizeVector(cross(forward, right));
  return {
    right,
    up: scaleVector(down, -1),
  };
}

function orbitCameraOffset() {
  const pitch = clamp(camera.pitch, -Math.PI * 0.5 + 0.0001, Math.PI * 0.5 - 0.0001);
  const cosPitch = Math.cos(pitch);
  const { back, right } = orbitReferenceAxes(camera.up_axis);
  const horizontal = addVectors(
    scaleVector(back, Math.cos(camera.yaw)),
    scaleVector(right, Math.sin(camera.yaw))
  );
  return addVectors(
    scaleVector(horizontal, cosPitch),
    scaleVector(axisVector(camera.up_axis), Math.sin(pitch))
  );
}

function orbitReferenceAxes(upAxis) {
  let back = [0, -1, 0];
  if (upAxis === "y" || upAxis === "x") {
    back = [0, 0, 1];
  }
  const forward = scaleVector(back, -1);
  const right = normalizeVector(cross(forward, axisVector(upAxis)));
  return { back, right };
}

function axisVector(upAxis) {
  if (upAxis === "x") return [1, 0, 0];
  if (upAxis === "y") return [0, 1, 0];
  return [0, 0, 1];
}

function panCamera(dx, dy) {
  const panScale = camera.distance * CAMERA_PAN_SPEED;
  const { right, up } = cameraBasis();
  const offset = addVectors(
    scaleVector(right, -dx * panScale),
    scaleVector(up, dy * panScale)
  );
  camera.target = addVectors(camera.target, offset);
}

function cross(a, b) {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
}

function normalizeVector(vector) {
  const length = Math.hypot(vector[0], vector[1], vector[2]);
  if (length <= 1e-8) return vector;
  return scaleVector(vector, 1 / length);
}

function scaleVector(vector, scale) {
  return [vector[0] * scale, vector[1] * scale, vector[2] * scale];
}

function addVectors(a, b) {
  return [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function normalizedUpAxis(value) {
  return value === "x" || value === "y" || value === "z" ? value : "z";
}

function updateCameraFromPointer(event) {
  const rawDx = event.clientX - lastPointer.x;
  const rawDy = event.clientY - lastPointer.y;
  const dx = clamp(rawDx, -MAX_POINTER_DELTA, MAX_POINTER_DELTA);
  const dy = clamp(rawDy, -MAX_POINTER_DELTA, MAX_POINTER_DELTA);
  if (dragMode === "pan") {
    panCamera(dx, dy);
  } else {
    rotateCamera(dx, dy);
  }
  lastPointer = { x: event.clientX, y: event.clientY };
}

viewer.addEventListener("pointerdown", (event) => {
  viewer.focus();
  isDragging = true;
  dragMode = event.shiftKey || event.button === 1 || event.button === 2 ? "pan" : "rotate";
  lastPointer = { x: event.clientX, y: event.clientY };
  viewer.setPointerCapture(event.pointerId);
  viewer.classList.add("is-dragging");
  markMoving();
});

viewer.addEventListener("pointermove", (event) => {
  if (!isDragging) return;
  updateCameraFromPointer(event);
  cameraChanged();
});

function endPointerDrag(event) {
  if (!isDragging) return;
  isDragging = false;
  viewer.classList.remove("is-dragging");
  if (viewer.hasPointerCapture(event.pointerId)) {
    viewer.releasePointerCapture(event.pointerId);
  }
  scheduleIdleRefine();
}

viewer.addEventListener("pointerup", endPointerDrag);
viewer.addEventListener("pointercancel", endPointerDrag);
viewer.addEventListener("lostpointercapture", () => {
  isDragging = false;
  viewer.classList.remove("is-dragging");
  scheduleIdleRefine();
});

viewer.addEventListener("contextmenu", (event) => event.preventDefault());

viewer.addEventListener(
  "wheel",
  (event) => {
    event.preventDefault();
    camera.distance = Math.max(
      CAMERA_LIMITS.minDistance,
      Math.min(CAMERA_LIMITS.maxDistance, camera.distance + event.deltaY * 0.003)
    );
    cameraChanged();
  },
  { passive: false }
);

viewer.addEventListener("keydown", (event) => {
  const step = 0.08;
  const zoomStep = 0.2;
  const panStep = camera.distance * 0.035;
  const { right, up } = cameraBasis();
  let handled = true;
  if (event.key === "ArrowLeft") camera.yaw -= step;
  else if (event.key === "ArrowRight") camera.yaw += step;
  else if (event.key === "ArrowUp") camera.pitch = Math.min(CAMERA_LIMITS.maxPitch, camera.pitch + step);
  else if (event.key === "ArrowDown") camera.pitch = Math.max(CAMERA_LIMITS.minPitch, camera.pitch - step);
  else if (event.key === "=" || event.key === "+") camera.distance = Math.max(CAMERA_LIMITS.minDistance, camera.distance - zoomStep);
  else if (event.key === "-") camera.distance = Math.min(CAMERA_LIMITS.maxDistance, camera.distance + zoomStep);
  else if (event.key.toLowerCase() === "a") camera.target = addVectors(camera.target, scaleVector(right, -panStep));
  else if (event.key.toLowerCase() === "d") camera.target = addVectors(camera.target, scaleVector(right, panStep));
  else if (event.key.toLowerCase() === "w") camera.target = addVectors(camera.target, scaleVector(up, panStep));
  else if (event.key.toLowerCase() === "s") camera.target = addVectors(camera.target, scaleVector(up, -panStep));
  else if (event.key.toLowerCase() === "r") {
    camera.yaw = 0;
    camera.pitch = 0;
    camera.distance = 3;
    camera.target = [0, 0, 0];
  }
  else handled = false;

  if (!handled) return;
  event.preventDefault();
  cameraChanged();
});

modeTabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    const mode = tab.dataset.mode;
    modeTabs.forEach((item) => item.classList.toggle("is-active", item === tab));
    viewer.classList.remove("mode-raw", "mode-overlay", "mode-side-by-side");
    viewer.classList.add(`mode-${mode}`);
  });
});

function formatBytes(bytes) {
  if (typeof bytes !== "number") return "--";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value >= 10 ? 1 : 2)} ${units[unitIndex]}`;
}

function sceneState(scene) {
  if (!scene.path) return "not configured";
  if (!scene.is_ply) return "not a PLY";
  if (!scene.exists) return "missing";
  if (!scene.is_file) return "not a file";
  return "ready";
}

function updateSceneUi(scene) {
  const displayPath = scene.relative_path || scene.path || "not configured";
  const state = sceneState(scene);
  camera.up_axis = normalizedUpAxis(scene.vertical_axis);
  scenePath.textContent = `Scene: ${displayPath}`;
  sceneMeta.textContent = `PLY: ${state} | Axis: ${camera.up_axis.toUpperCase()} | Size: ${formatBytes(scene.size_bytes)}`;
  sceneInput.value = scene.path || "";
}

function setSceneControlsDisabled(disabled) {
  sceneInput.disabled = disabled;
  sceneClear.disabled = disabled;
  sceneForm.querySelectorAll("button").forEach((button) => {
    button.disabled = disabled;
  });
}

function resetRefinementForSceneChange(message) {
  refineSeq += 1;
  cameraVersion += 1;
  if (activeRefineController) {
    activeRefineController.abort();
  }
  refinedImage.removeAttribute("src");
  refineLatency.textContent = "Refine: -- ms";
  cameraStateLabel.textContent = "Camera idle";
  cameraStateLabel.className = "status-ok";
  setPipeline(message, "status-ok");
  scheduleInteractiveRender(true);
  scheduleIdleRefine();
}

async function loadSceneCandidates() {
  try {
    const response = await fetch("/api/scenes");
    if (!response.ok) throw new Error(await responseErrorMessage(response));
    const data = await response.json();
    sceneOptions.innerHTML = "";
    data.scenes.forEach((scene) => {
      const option = document.createElement("option");
      option.value = scene.path;
      option.label = scene.relative_path || scene.name || scene.path;
      sceneOptions.append(option);
    });
  } catch (_error) {
    sceneOptions.innerHTML = "";
  }
}

async function loadScene() {
  try {
    const response = await fetch("/api/scene");
    if (!response.ok) throw new Error(await responseErrorMessage(response));
    const data = await response.json();
    updateSceneUi(data.scene);
    fallbackState.textContent = data.fallback_mode ? "Fallback: on" : "Fallback: off";
    fallbackState.className = data.fallback_mode ? "status-busy" : "status-ok";
    setPipeline("Ready", "status-ok");
  } catch (error) {
    setPipeline(`Error: ${error.message}`, "status-error");
  }
}

async function setScenePath(path) {
  setSceneControlsDisabled(true);
  setPipeline("Loading scene", "status-busy");
  try {
    const data = await postJson("/api/scene", { path });
    updateSceneUi(data.scene);
    await loadSceneCandidates();
    resetRefinementForSceneChange(path.trim() ? "Scene loaded" : "Scene cleared");
  } catch (error) {
    setPipeline(`Scene error: ${error.message}`, "status-error");
  } finally {
    setSceneControlsDisabled(false);
  }
}

async function clearScenePath() {
  setSceneControlsDisabled(true);
  setPipeline("Clearing scene", "status-busy");
  try {
    const data = await deleteJson("/api/scene");
    updateSceneUi(data.scene);
    resetRefinementForSceneChange("Scene cleared");
  } catch (error) {
    setPipeline(`Scene error: ${error.message}`, "status-error");
  } finally {
    setSceneControlsDisabled(false);
  }
}

sceneForm.addEventListener("submit", (event) => {
  event.preventDefault();
  setScenePath(sceneInput.value);
});

sceneClear.addEventListener("click", () => {
  clearScenePath();
});

window.addEventListener("resize", () => {
  cameraChanged();
});

loadScene().then(() => {
  loadSceneCandidates();
  updateCameraReadout();
  scheduleInteractiveRender(true);
  scheduleIdleRefine();
});
