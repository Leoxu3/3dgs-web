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
REFINER_BACKEND=auto    # auto, fallback, difix3d, or difix3d_plus
APP_RELOAD=1
```

Open `http://localhost:8000` locally, or access it through SSH tunneling when running on a remote server.
The PLY path can also be changed from the Web UI at runtime. Relative paths are resolved from the repository `src/` directory, and the backend validates that selected paths exist and end in `.ply`.

## Difix3D / Difix3D+ Refiner

The refinement layer is intentionally adapter-based so the demo can run on servers
where the exact Difix3D entrypoint differs. If no adapter is configured, or if an
adapter fails at runtime, `/api/refine` returns the input image unchanged and marks
the response as fallback mode.

Configuration options:

```bash
REFINER_BACKEND=auto
DIFIX3D_TIMEOUT_SECONDS=120
```

Use a CLI adapter when you have a command that can read one image and write one
image:

```bash
REFINER_BACKEND=difix3d_plus
DIFIX3D_COMMAND='python -m your_difix_infer --input {input} --output {output} --camera {camera}'
```

Available command placeholders are `{input}`, `{output}`, `{camera}`, and
`{variant}`. The backend writes the current frame to `{input}`, writes the camera
JSON to `{camera}`, expects the refined image at `{output}`, and then converts it
back to a browser data URL.

If you do not have a local `checkpoints/model.pkl`, use the Hugging Face adapter.
This follows the official diffusers quickstart and does not call
`src/inference_difix.py`:

```bash
git clone https://github.com/nv-tlabs/Difix3D.git /path/to/Difix3D
cd /path/to/Difix3D
pip install -r requirements.txt

cd /path/to/Computer_Graphics/src
export REFINER_BACKEND=difix3d_plus
export DIFIX3D_REPO=/path/to/Difix3D
export DIFIX3D_MODEL_NAME=nvidia/difix
export DIFIX3D_TIMEOUT_SECONDS=180
export DIFIX3D_COMMAND='python scripts/difix3d_hf_adapter.py --input {input} --output {output} --camera {camera}'
./scripts/run_dev.sh
```

The first run downloads the model through Hugging Face. If Difix3D is installed
in a different conda environment, point the adapter at that Python executable:

```bash
export DIFIX3D_PYTHON=/path/to/miniconda3/envs/difix3d/bin/python
```

If you do have a local checkpoint and want to use the upstream inference script,
use the included `inference_difix.py` compatibility adapter because the upstream
script writes to an output directory instead of an exact output file:

```bash
git clone https://github.com/nv-tlabs/Difix3D.git /path/to/Difix3D
cd /path/to/Difix3D
pip install -r requirements.txt

cd /path/to/Computer_Graphics/src
export REFINER_BACKEND=difix3d_plus
export DIFIX3D_REPO=/path/to/Difix3D
export DIFIX3D_MODEL_PATH=/path/to/Difix3D/checkpoints/model.pkl
export DIFIX3D_TIMEOUT_SECONDS=180
export DIFIX3D_COMMAND='python scripts/difix3d_plus_adapter.py --input {input} --output {output} --camera {camera}'
./scripts/run_dev.sh
```

Optional Difix3D+ adapter variables:

```bash
DIFIX3D_PYTHON=/path/to/difix/conda/env/bin/python
DIFIX3D_PROMPT='remove degradation'
DIFIX3D_TIMESTEP=199
DIFIX3D_HEIGHT=576
DIFIX3D_WIDTH=1024
DIFIX3D_MAX_SIDE=512
DIFIX3D_REF_IMAGE=/path/to/reference.png
```

Use a Python adapter when you have an importable function:

```bash
REFINER_BACKEND=difix3d
DIFIX3D_PYTHON_CALLABLE='my_difix_adapter:refine_image'
```

The callable may accept `image_data_url`, `camera`, and `variant` keyword
arguments. It may return a data URL, bytes, an output path, a dict containing
`image_data_url` / `data_url` / `output_path` / `bytes`, or a `RefinementResult`.

## Endpoints

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

- Add a project-specific Difix3D / Difix3D+ adapter command or Python callable for the target server environment.
- Improve camera calibration / scene normalization for different 3DGS datasets.
