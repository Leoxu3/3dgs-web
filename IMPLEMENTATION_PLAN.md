# Implementation Plan

## Current Repository State

- `AGENTS.md`: project instructions and constraints.
- No backend, frontend, renderer, refinement module, sample data, tests, or README exist yet.

## Guiding Constraints

- Use a Web GUI suitable for a headless server.
- Avoid PyQt, DearPyGui, OpenCV `imshow`, Tkinter, X11, and Wayland requirements.
- Prioritize a demoable MVP over research completeness.
- Always provide fallback behavior when Difix3D / Difix3D+ is unavailable.

## Minimal Proposed Structure

```text
src/
  AGENTS.md
  IMPLEMENTATION_PLAN.md
  README.md
  pyproject.toml
  scripts/
    run_dev.sh
  backend/
    app/
      main.py
      config.py
      api/
        routes.py
        websocket.py
      rendering/
        camera.py
        renderer.py
        ply_loader.py
      refinement/
        difix.py
        fallback.py
      static/
        index.html
        app.js
        styles.css
    tests/
      test_fallback.py
      test_api_health.py
  data/
    .gitkeep
```

## Phased Implementation

### Phase 1: Skeleton and Fallback Demo

- Add FastAPI backend with health and scene-info endpoints.
- Serve a simple browser UI from FastAPI static files.
- Implement frontend camera state controls and idle debounce.
- Implement a fallback refinement module that returns the input image.
- Verify the app starts on `0.0.0.0` without desktop GUI dependencies.

### Phase 2: Raw Render Pipeline

- Add 3DGS scene configuration and `.ply` path handling.
- Implement a renderer interface with `MockRenderer` first, then a `gsplat` backend.
- Return raw rendered frames to the browser while the camera moves.
- Add render timing / FPS display.

### Phase 3: Idle Refinement Pipeline

- On camera idle, request a higher-resolution render or captured frame.
- Send the image through Difix3D / Difix3D+ when available.
- Keep fallback mode active when Difix3D import, weights, or runtime execution fails.
- Return refinement latency and status to the frontend.

### Phase 4: Comparison UI

- Add raw-only, refined overlay, and side-by-side display modes.
- Add status bar states: moving, idle, refining, done, fallback, error.
- Ensure refinement requests do not block camera movement.

### Phase 5: Reproducibility and Tests

- Add README setup and run instructions.
- Add minimal backend tests for health, fallback refinement, and request schema.
- Add a one-command dev runner.
- Document known limitations, supported `.ply` assumptions, and Difix3D setup notes.

## MVP Completion Target

The first demo should run with one command, open in a browser through SSH tunneling, accept camera interaction, debounce idle state, call the backend for refinement, and visibly report fallback mode if Difix3D is unavailable.
