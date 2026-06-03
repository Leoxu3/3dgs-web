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
const saveRawFrameButton = document.querySelector("#saveRawFrame");
const saveRefinedFrameButton = document.querySelector("#saveRefinedFrame");

const IDLE_DELAY_MS = 400;
const REFINE_BUSY_RETRY_MS = 650;
const INTERACTIVE_RENDER_MIN_INTERVAL_MS = 90;
const INTERACTIVE_RENDER_SCALE = 0.28;
const IDLE_RENDER_SCALE = 0.6;
const RENDER_SIZE_STEP = 8;
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
let refinerWarmupPromise = null;
let refinerWarmupDone = false;

function setPipeline(message, className = "") {
  pipelineState.textContent = message;
  pipelineState.className = className;
}

function setFallbackState(enabled, message = "") {
  const summary = enabled ? summarizeFallbackMessage(message) : "off";
  fallbackState.textContent = `Fallback: ${summary}`;
  fallbackState.title = message || "";
  fallbackState.className = enabled ? "status-busy" : "status-ok";
}

function summarizeFallbackMessage(message) {
  if (!message) return "on";
  const compact = message.replace(/\s+/g, " ").trim();
  const lower = compact.toLowerCase();
  if (lower.includes("placeholder")) return "placeholder";
  if (lower.includes("svg")) return "placeholder";
  if (lower.includes("unavailable")) return "unavailable";
  if (lower.includes("failed")) return "failed";
  if (compact.length <= 42) return compact;
  return `${compact.slice(0, 39)}...`;
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

function cancelActiveRefinement() {
  if (!activeRefineController) return;
  activeRefineController.abort();
  activeRefineController = null;
}

function updateRefinedAvailability() {
  viewer.classList.toggle(
    "has-refined",
    hasFrame(refinedImage)
  );
}

function hasFrame(image) {
  return image.hasAttribute("src") && image.getAttribute("src") !== "";
}

function updateFrameDownloadButtons() {
  saveRawFrameButton.disabled = !hasFrame(rawImage);
  saveRefinedFrameButton.disabled = !hasFrame(refinedImage);
}

function setRefinedFrame(imageDataUrl) {
  refinedImage.src = imageDataUrl;
  updateRefinedAvailability();
  updateFrameDownloadButtons();
}

function clearRefinedFrame(latencyText = "Refine: -- ms") {
  refinedImage.removeAttribute("src");
  updateRefinedAvailability();
  updateFrameDownloadButtons();
  refineLatency.textContent = latencyText;
}

function pendingIdleRefineText() {
  return refinerWarmupDone ? "Refine: waiting for idle" : "Refine: -- ms";
}

function setRawFrame(frame) {
  rawImage.src = frame.image_data_url;
  renderTime.textContent = `Render: ${frame.render_ms} ms | ${frame.renderer}`;
  updateFrameDownloadButtons();
}

function saveFrame(kind, image) {
  const imageDataUrl = image.getAttribute("src") || "";
  if (!imageDataUrl) return;

  const link = document.createElement("a");
  link.href = imageDataUrl;
  link.download = frameFilename(kind, imageDataUrl, image);
  document.body.append(link);
  link.click();
  link.remove();
}

function frameFilename(kind, imageDataUrl, image) {
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  const width = Number(image.naturalWidth);
  const height = Number(image.naturalHeight);
  const size = width > 0 && height > 0 ? `-${width}x${height}` : "";
  return `3dgs-${kind}-${timestamp}${size}.${frameExtension(imageDataUrl)}`;
}

function frameExtension(imageDataUrl) {
  const match = /^data:([^;,]+)/.exec(imageDataUrl);
  const mimeType = match ? match[1].toLowerCase() : "";
  if (mimeType === "image/svg+xml") return "svg";
  if (mimeType === "image/jpeg") return "jpg";
  if (mimeType === "image/webp") return "webp";
  if (mimeType === "image/gif") return "gif";
  return "png";
}

function formatRefineLatency(refined) {
  if (refined.status === "busy") return "Refine: busy";

  const latency = Number(refined.latency_ms);
  const timings = refined.timings_ms || {};
  const workerMs = Number(timings.worker_roundtrip_ms ?? timings.subprocess_ms);
  const latencyText = Number.isFinite(latency)
    ? `${latency.toFixed(0)} ms`
    : "-- ms";

  if (Number.isFinite(workerMs) && workerMs > 0) {
    const label = timings.worker_roundtrip_ms ? "worker" : "subprocess";
    return `Refine: ${latencyText} | ${label} ${workerMs.toFixed(0)} ms`;
  }

  return `Refine: ${latencyText}`;
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

async function ensureRefinerWarmup() {
  if (refinerWarmupDone) return null;
  if (!refinerWarmupPromise) {
    refinerWarmupPromise = warmupRefiner(renderSize("idle"));
  }
  return refinerWarmupPromise;
}

async function warmupRefiner(size) {
  setPipeline("Loading refiner", "status-busy");
  refineLatency.textContent = "Refine: loading";

  try {
    const data = await postJson("/api/refiner/warmup", {
      width: size.width,
      height: size.height,
    });
    refinerWarmupDone = true;
    if (data.fallback_mode) {
      setFallbackState(true, data.message);
    } else {
      setFallbackState(false);
    }
    const warmupFailed = data.status === "error";
    setPipeline(
      warmupFailed ? "Refiner warmup failed" : "Ready",
      warmupFailed ? "status-error" : "status-ok"
    );
    if (Number.isFinite(Number(data.latency_ms))) {
      refineLatency.textContent = `Refine: warmup ${Number(data.latency_ms).toFixed(0)} ms`;
    }
    return data;
  } catch (error) {
    refinerWarmupDone = true;
    setFallbackState(true, error.message);
    setPipeline(`Error: ${error.message}`, "status-error");
    return null;
  }
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
  return renderSizesForViewport(viewerContentSize())[quality];
}

function renderSizesForViewport({ width: baseWidth, height: baseHeight }) {
  const aspectRatio = baseWidth / baseHeight;
  const candidates = {
    interactive: renderSizeCandidates({
      baseWidth,
      baseHeight,
      quality: "interactive",
      aspectRatio,
    }),
    idle: renderSizeCandidates({
      baseWidth,
      baseHeight,
      quality: "idle",
      aspectRatio,
    }),
  };
  const selected = {
    interactive: selectBestRenderCandidate(candidates.interactive),
    idle: selectBestRenderCandidate(candidates.idle),
  };
  const selectedSides = new Set(
    [selected.interactive.aspectSide, selected.idle.aspectSide].filter((side) => side !== 0)
  );

  if (selectedSides.size <= 1) {
    return renderSizeSelection(selected);
  }

  // Keep object-fit letterboxing on the same axis when switching between
  // interactive and idle renders.
  const wider = {
    interactive: selectBestRenderCandidate(candidates.interactive, 1),
    idle: selectBestRenderCandidate(candidates.idle, 1),
  };
  const narrower = {
    interactive: selectBestRenderCandidate(candidates.interactive, -1),
    idle: selectBestRenderCandidate(candidates.idle, -1),
  };

  return renderSizeSelection(
    renderSelectionScore(wider) <= renderSelectionScore(narrower) ? wider : narrower
  );
}

function renderSizeCandidates({ baseWidth, baseHeight, quality, aspectRatio }) {
  const minWidth = quality === "idle" ? 320 : 240;
  const minHeight = quality === "idle" ? 240 : 160;
  const minScale = Math.max(minWidth / baseWidth, minHeight / baseHeight);
  let scale = Math.max(
    quality === "idle" ? IDLE_RENDER_SCALE : INTERACTIVE_RENDER_SCALE,
    minScale
  );
  if (quality === "interactive") {
    const capScale = Math.min(1, 520 / baseWidth, 320 / baseHeight);
    if (capScale >= minScale) {
      scale = Math.min(scale, capScale);
    }
  }
  return buildRenderSizeCandidates({
    targetWidth: baseWidth * scale,
    targetHeight: baseHeight * scale,
    minWidth,
    minHeight,
    aspectRatio,
  });
}

function viewerContentSize() {
  const rect = viewer.getBoundingClientRect();
  return {
    width: Math.max(1, viewer.clientWidth || rect.width),
    height: Math.max(1, viewer.clientHeight || rect.height),
  };
}

function buildRenderSizeCandidates({ targetWidth, targetHeight, minWidth, minHeight, aspectRatio }) {
  const minRenderWidth = roundUpToMultiple(minWidth, RENDER_SIZE_STEP);
  const minRenderHeight = roundUpToMultiple(minHeight, RENDER_SIZE_STEP);
  const widths = nearbyMultiples(targetWidth, minRenderWidth);
  const heights = nearbyMultiples(targetHeight, minRenderHeight);
  const candidates = [];

  for (const width of widths) {
    for (const height of heights) {
      const candidateAspect = width / height;
      const aspectDelta = candidateAspect - aspectRatio;
      const aspectError = Math.abs(aspectDelta) / aspectRatio;
      const sizeError =
        Math.abs(width - targetWidth) / Math.max(1, targetWidth) +
        Math.abs(height - targetHeight) / Math.max(1, targetHeight);
      candidates.push({
        width,
        height,
        aspectSide: aspectDelta === 0 ? 0 : aspectDelta > 0 ? 1 : -1,
        score: aspectError * 5 + sizeError,
      });
    }
  }

  candidates.sort((a, b) => {
    if (a.score !== b.score) return a.score - b.score;
    return b.width * b.height - a.width * a.height;
  });
  return candidates;
}

function nearbyMultiples(targetValue, minValue) {
  const base = roundDownToMultiple(Math.round(targetValue), RENDER_SIZE_STEP);
  const values = new Set([
    minValue,
    roundDownToMultiple(Math.round(targetValue), RENDER_SIZE_STEP),
    roundUpToMultiple(Math.round(targetValue), RENDER_SIZE_STEP),
  ]);

  for (let offset = -2; offset <= 2; offset += 1) {
    const candidate = base + offset * RENDER_SIZE_STEP;
    if (candidate >= minValue) values.add(candidate);
  }

  return Array.from(values).sort((a, b) => a - b);
}

function selectBestRenderCandidate(candidates, aspectSide = 0) {
  const matching = candidates.find(
    (candidate) =>
      aspectSide === 0 || candidate.aspectSide === 0 || candidate.aspectSide === aspectSide
  );
  return matching || candidates[0];
}

function renderSelectionScore(selection) {
  return selection.interactive.score + selection.idle.score;
}

function renderSizeSelection(selection) {
  return {
    interactive: {
      width: selection.interactive.width,
      height: selection.interactive.height,
    },
    idle: {
      width: selection.idle.width,
      height: selection.idle.height,
    },
  };
}

function roundDownToMultiple(value, step) {
  return Math.max(step, Math.floor(value / step) * step);
}

function roundUpToMultiple(value, step) {
  return Math.max(step, Math.ceil(value / step) * step);
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
  setRawFrame(result);
  return result;
}

function scheduleIdleRefine() {
  window.clearTimeout(idleTimer);
  idleTimer = window.setTimeout(runIdleRefine, IDLE_DELAY_MS);
}

function markMoving() {
  refineSeq += 1;
  cancelActiveRefinement();
  clearRefinedFrame(pendingIdleRefineText());
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
  const requestedCameraVersion = cameraVersion;
  let controller = null;
  cameraStateLabel.textContent = "Camera idle";
  cameraStateLabel.className = "status-ok";

  if (!refinerWarmupDone) {
    await ensureRefinerWarmup();
    if (seq !== refineSeq || requestedCameraVersion !== cameraVersion) return;
  }

  const size = renderSize("idle");
  setPipeline("Refining", "status-busy");
  refineLatency.textContent = "Refine: running";

  try {
    controller = new AbortController();
    activeRefineController = controller;
    const view = await postJson("/api/refine-view", {
      camera: cameraSnapshot(),
      width: size.width,
      height: size.height,
      quality: "idle",
    }, { signal: controller.signal });
    if (seq !== refineSeq || requestedCameraVersion !== cameraVersion) return;

    if (view.raw) {
      setRawFrame(view.raw);
    }

    const refined = view.refined;
    if (refined.status === "busy") {
      refineLatency.textContent = formatRefineLatency(refined);
      setPipeline("Refine busy; retrying", "status-busy");
      window.setTimeout(() => {
        if (seq === refineSeq && requestedCameraVersion === cameraVersion) {
          runIdleRefine();
        }
      }, REFINE_BUSY_RETRY_MS);
      return;
    }

    setRefinedFrame(refined.image_data_url);
    refineLatency.textContent = formatRefineLatency(refined);
    setFallbackState(refined.fallback_mode, refined.message);
    setPipeline(refined.status === "fallback" ? "Fallback done" : "Refine done", "status-ok");
  } catch (error) {
    if (isAbort(error)) return;
    setPipeline(`Error: ${error.message}`, "status-error");
  } finally {
    if (controller && activeRefineController === controller) {
      activeRefineController = null;
    }
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
    viewer.classList.remove("mode-raw", "mode-refined", "mode-side-by-side");
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
  cancelActiveRefinement();
  rawImage.removeAttribute("src");
  clearRefinedFrame();
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
    setFallbackState(data.fallback_mode, data.fallback_mode ? "Difix3D unavailable / fallback mode" : "");
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
    setFallbackState(data.fallback_mode, data.fallback_mode ? "Difix3D unavailable / fallback mode" : "");
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
    setFallbackState(data.fallback_mode, data.fallback_mode ? "Difix3D unavailable / fallback mode" : "");
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

saveRawFrameButton.addEventListener("click", () => {
  saveFrame("raw", rawImage);
});

saveRefinedFrameButton.addEventListener("click", () => {
  saveFrame("refined", refinedImage);
});

window.addEventListener("resize", () => {
  cameraChanged();
});

updateFrameDownloadButtons();

loadScene().then(() => {
  loadSceneCandidates();
  updateCameraReadout();
  scheduleInteractiveRender(true);
  ensureRefinerWarmup().finally(scheduleIdleRefine);
});
