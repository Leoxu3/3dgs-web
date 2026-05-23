# Server-Friendly 3DGS Web Viewer Skeleton

This is a minimal Web app skeleton for a headless-server demo pipeline:

1. Browser camera interaction.
2. Backend raw render request.
3. Idle-triggered refinement request.
4. Fallback mode when Difix3D / Difix3D+ is unavailable.

The current implementation intentionally uses a stub renderer and fallback refiner. It does not require PyQt, DearPyGui, Tkinter, OpenCV `imshow`, X11, or Wayland.

## Setup

Conda example:

```bash
conda create -n 3dgs-web python=3.10 -y
conda activate 3dgs-web
pip install -e ".[dev]"
```

Virtualenv example:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run

```bash
./scripts/run_dev.sh
```

The server binds to `0.0.0.0:8000` by default.

Useful environment variables:

```bash
APP_HOST=0.0.0.0
APP_PORT=8000
SCENE_PLY_PATH=/path/to/scene.ply
APP_RELOAD=1
```

Open `http://localhost:8000` locally, or access it through SSH tunneling when running on a remote server.

## Current Skeleton Endpoints

- `GET /api/health`
- `GET /api/scene`
- `POST /api/render`
- `POST /api/refine`

## Current Frontend Behavior

- Drag in the viewer to rotate the camera.
- Shift-drag, middle-drag, or right-drag to pan the target.
- Use the mouse wheel to zoom.
- Arrow keys rotate, `W/A/S/D` pans, `+/-` zooms, and `R` resets the camera when the viewer has focus.
- While the camera is moving, the browser requests low-cost mock raw renders only.
- After 700 ms of camera idle time, the frontend requests an idle render and sends that image to `/api/refine`.
- The mock renderer is still used intentionally; it displays camera-dependent placeholder SVG output until a real `gsplat` renderer is integrated.

## Test

```bash
pytest
```

## Next Implementation Steps

- Replace the stub renderer in `backend/app/rendering/renderer.py` with a real `gsplat` implementation.
- Replace the fallback refiner in `backend/app/refinement/difix.py` with Difix3D / Difix3D+ integration.
- Keep fallback mode available for demo reliability.
