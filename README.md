# Server-Friendly 3DGS Web Viewer Skeleton

This is a minimal Web app skeleton for a headless-server demo pipeline:

1. Browser camera interaction.
2. Backend raw render request.
3. Idle-triggered refinement request.
4. Fallback mode when Difix3D / Difix3D+ is unavailable.

The default renderer selection is now `RENDERER_BACKEND=auto`: the backend attempts to use a CUDA `gsplat` renderer when the optional dependencies are available, and falls back to `MockRenderer` otherwise. It does not require PyQt, DearPyGui, Tkinter, OpenCV `imshow`, X11, or Wayland.

## Setup

Conda example:

```bash
conda create -n 3dgs-web python=3.10 -y
conda activate 3dgs-web
pip install -e ".[dev]"
```

Optional gsplat renderer dependencies:

```bash
# Install a CUDA-enabled torch build for your server first, then:
pip install -e ".[dev,gsplat]"
```

The real renderer expects an INRIA-style 3D Gaussian Splatting PLY when available (`x/y/z`, `f_dc_*`, `opacity`, `scale_*`, `rot_*`). Simple PLY files with `x/y/z` and RGB fields can still be attempted with default Gaussian scale, but incompatible files automatically fall back to `MockRenderer`.

If the UI reports a gsplat fallback such as `CameraModelType` on `NoneType`, the Python package imported but its CUDA extension did not load. Confirm that `torch.cuda.is_available()` is true, `nvcc` or a matching prebuilt gsplat wheel is available, then reinstall/rebuild `gsplat`.

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
RENDERER_BACKEND=auto   # auto, gsplat, or mock
GSPLAT_DEVICE=cuda      # e.g. cuda or cuda:0
APP_RELOAD=1
```

Open `http://localhost:8000` locally, or access it through SSH tunneling when running on a remote server.
The PLY path can also be changed from the Web UI at runtime. Relative paths are resolved from the repository `src/` directory, and the backend validates that selected paths exist and end in `.ply`.

## Current Skeleton Endpoints

- `GET /api/health`
- `GET /api/scene`
- `POST /api/scene`
- `DELETE /api/scene`
- `GET /api/scenes`
- `POST /api/render`
- `POST /api/refine`

## Current Frontend Behavior

- Drag in the viewer to rotate the camera.
- Shift-drag, middle-drag, or right-drag to pan the target.
- Use the mouse wheel to zoom.
- Arrow keys rotate, `W/A/S/D` pans, `+/-` zooms, and `R` resets the camera when the viewer has focus.
- Enter a PLY path in the top bar to switch scenes without restarting the server.
- While the camera is moving, the browser requests lower-resolution raw renders.
- After 700 ms of camera idle time, the frontend requests an idle render and sends that image to `/api/refine`.
- The render status displays the renderer used for the latest frame. `gsplat-renderer` returns PNG frames from the selected PLY; `mock-svg-renderer` returns a camera-dependent SVG placeholder.
- `MockRenderer` fallback is preserved for missing packages, unavailable CUDA, missing scene path, unsupported PLY properties, and gsplat runtime errors.

## Test

```bash
pytest
```

## Next Implementation Steps

- Replace the fallback refiner in `backend/app/refinement/difix.py` with Difix3D / Difix3D+ integration.
- Improve camera calibration / scene normalization for different 3DGS datasets.
