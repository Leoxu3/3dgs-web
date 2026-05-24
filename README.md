# Server-Friendly 3DGS Interactive Viewer

This is a Web app for a headless-server interactive 3DGS refinement demo:

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
REFINER_BACKEND=auto    # auto, adapter, or fallback
APP_RELOAD=1
```

Open `http://localhost:8000` locally, or access it through SSH tunneling when running on a remote server.
The PLY path can also be changed from the Web UI at runtime. Relative paths are resolved from the repository `src/` directory, and the backend validates that selected paths exist and end in `.ply`.

## Difix3D / Difix3D+ Refiner

The backend does not hard-code one Difix3D entrypoint. It runs a configured
adapter and keeps the viewer usable if the adapter is missing or fails.

- `REFINER_BACKEND=auto` uses a configured adapter when one is present, otherwise
  it falls back to returning the input image unchanged.
- `REFINER_BACKEND=adapter` enables adapter mode explicitly. Missing or failing
  adapters are still reported as fallback mode in the UI.
- `REFINER_BACKEND=fallback` forces the no-op fallback refiner.

`DIFIX3D_VARIANT` is only a label passed to adapters, such as `difix3d` or
`difix3d_plus`. Older values like `REFINER_BACKEND=difix3d_plus` are still
accepted, but new commands should use `REFINER_BACKEND=adapter` plus
`DIFIX3D_VARIANT`.

Recommended setup for interactive demos:

```bash
git clone https://github.com/nv-tlabs/Difix3D.git /path/to/Difix3D
cd /path/to/Difix3D
pip install -r requirements.txt

cd /path/to/Computer_Graphics/src
export REFINER_BACKEND=adapter
export DIFIX3D_REPO=/path/to/Difix3D
export DIFIX3D_MODEL_NAME=nvidia/difix
export DIFIX3D_TIMEOUT_SECONDS=180
export DIFIX3D_WORKER_COMMAND='python scripts/difix3d_hf_worker.py'
export APP_RELOAD=0
./scripts/run_dev.sh
```

The worker loads the model on the first request and reuses it for later idle
viewpoints. If Difix3D is installed in a separate conda environment, point the
worker at that Python executable:

```bash
export DIFIX3D_PYTHON=/path/to/miniconda3/envs/difix3d/bin/python
```

Other adapter options, if the worker does not fit your environment. Configure
only one adapter entry at a time; if multiple are set, the backend tries
`DIFIX3D_PYTHON_CALLABLE`, then `DIFIX3D_WORKER_COMMAND`, then
`DIFIX3D_COMMAND`.

```bash
export REFINER_BACKEND=adapter
export DIFIX3D_REPO=/path/to/Difix3D

# One-shot Hugging Face adapter. Simpler, but starts Python for every frame.
export DIFIX3D_COMMAND='python scripts/difix3d_hf_adapter.py --input {input} --output {output} --camera {camera}'

# Local checkpoint / upstream inference_difix.py compatibility adapter.
export DIFIX3D_MODEL_PATH=/path/to/Difix3D/checkpoints/model.pkl
export DIFIX3D_COMMAND='python scripts/difix3d_plus_adapter.py --input {input} --output {output} --camera {camera}'

# Custom CLI adapter.
export DIFIX3D_COMMAND='python -m your_difix_infer --input {input} --output {output} --camera {camera}'

# Python callable adapter.
export DIFIX3D_PYTHON_CALLABLE='my_difix_adapter:refine_image'
```

For CLI adapters, the backend replaces `{input}`, `{output}`, `{camera}`, and
`{variant}` before running the command. The adapter must read the input image and
write the refined image to `{output}`.

Common tuning variables:

```bash
DIFIX3D_PROMPT='remove degradation'
DIFIX3D_VARIANT=difix3d_plus
DIFIX3D_TIMESTEP=199
DIFIX3D_MAX_SIDE=512
DIFIX3D_HEIGHT=0
DIFIX3D_WIDTH=0
DIFIX3D_REF_IMAGE=/path/to/reference.png
DIFIX3D_LOCAL_FILES_ONLY=1  # use only when the Hugging Face model is cached
```

## Endpoints

- `GET /api/health`
- `GET /api/scene`
- `POST /api/scene`
- `DELETE /api/scene`
- `GET /api/scenes`
- `POST /api/render`
- `POST /api/refine`
- `POST /api/refine-view`

## Current Frontend Behavior

- Drag in the viewer to rotate the camera.
- Shift-drag, middle-drag, or right-drag to pan the target.
- Use the mouse wheel to zoom.
- Arrow keys rotate, `W/A/S/D` pans, `+/-` zooms, and `R` resets the camera when the viewer has focus.
- Enter a PLY path in the top bar to switch scenes without restarting the server.
- While the camera is moving, the browser requests lower-resolution raw renders.
- After 400 ms of camera idle time, the frontend calls `/api/refine-view`, which renders and refines the current view in one backend request.
- If the backend reports that a previous refinement is still running, the frontend keeps the raw view responsive and retries shortly.
- The render status displays the renderer used for the latest frame. `gsplat-renderer` returns PNG frames from the selected PLY; `mock-svg-renderer` returns a camera-dependent SVG placeholder.
- `MockRenderer` fallback is preserved for missing packages, unavailable CUDA, missing scene path, unsupported PLY properties, and gsplat runtime errors.

## Test

```bash
pytest
```
