"""Optional gsplat renderer with a MockRenderer safety net.

The module intentionally keeps torch, numpy, Pillow, and gsplat imports lazy so
the rest of the app can boot cleanly on machines that only need fallback mode.
"""

from __future__ import annotations

import base64
import importlib
import math
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from threading import RLock
from typing import Any

from backend.app.rendering.camera import CameraState
from backend.app.rendering.mock import MockRenderer
from backend.app.rendering.renderer import RenderQuality, RenderResult


SH_C0 = 0.28209479177387814
PLY_NUMPY_DTYPES = {
    "char": "i1",
    "int8": "i1",
    "uchar": "u1",
    "uint8": "u1",
    "short": "i2",
    "int16": "i2",
    "ushort": "u2",
    "uint16": "u2",
    "int": "i4",
    "int32": "i4",
    "uint": "u4",
    "uint32": "u4",
    "float": "f4",
    "float32": "f4",
    "double": "f8",
    "float64": "f8",
}


class GsplatUnavailable(RuntimeError):
    """Raised when a real gsplat render path cannot be used."""


@dataclass(frozen=True)
class PlyProperty:
    name: str
    data_type: str


@dataclass(frozen=True)
class PlyHeader:
    data_format: str
    vertex_count: int
    vertex_properties: tuple[PlyProperty, ...]


@dataclass(frozen=True)
class GaussianArrays:
    means: Any
    quats: Any
    scales: Any
    opacities: Any
    colors: Any
    count: int


@dataclass(frozen=True)
class GsplatScene:
    path: str
    means: Any
    quats: Any
    scales: Any
    opacities: Any
    colors: Any
    count: int


class GsplatRenderer:
    """Render 3D Gaussian PLY files through gsplat when dependencies allow it."""

    name = "gsplat-renderer"

    def __init__(
        self,
        scene_ply_path: str = "",
        device: str = "cuda",
        fallback_renderer: MockRenderer | None = None,
    ) -> None:
        self.scene_ply_path = scene_ply_path
        self.device = device
        self._fallback = fallback_renderer or MockRenderer(scene_ply_path=scene_ply_path)
        self._lock = RLock()
        self._scene: GsplatScene | None = None
        self._failed_scene_path: str | None = None
        self._last_error: str | None = None
        self._torch, self._np, self._image_module, self._rasterization = self._load_runtime()

    def set_scene_ply_path(self, scene_ply_path: str) -> None:
        with self._lock:
            self.scene_ply_path = scene_ply_path
            self._fallback.set_scene_ply_path(scene_ply_path)
            self._fallback.set_fallback_reason(None)
            self._scene = None
            self._failed_scene_path = None
            self._last_error = None

    def render(
        self,
        camera: CameraState,
        width: int,
        height: int,
        quality: RenderQuality,
    ) -> RenderResult:
        try:
            with self._lock:
                return self._render_gsplat(
                    camera=camera,
                    width=width,
                    height=height,
                    quality=quality,
                )
        except Exception as exc:
            reason = f"gsplat fallback ({exc.__class__.__name__}: {exc})"
            self._last_error = reason
            self._fallback.set_fallback_reason(reason)
            return self._fallback.render(
                camera=camera,
                width=width,
                height=height,
                quality=quality,
            )

    def _load_runtime(self) -> tuple[Any, Any, Any, Any]:
        try:
            torch = importlib.import_module("torch")
            np = importlib.import_module("numpy")
            image_module = importlib.import_module("PIL.Image")
        except Exception as exc:
            raise GsplatUnavailable(f"required Python package is unavailable: {exc}") from exc

        if not self.device.startswith("cuda"):
            raise GsplatUnavailable("gsplat rendering currently expects a CUDA device")
        if not torch.cuda.is_available():
            raise GsplatUnavailable("CUDA is not available to torch")

        self._validate_gsplat_cuda_backend(torch=torch)

        try:
            rendering_module = importlib.import_module("gsplat.rendering")
            rasterization = rendering_module.rasterization
        except Exception:
            try:
                gsplat_module = importlib.import_module("gsplat")
                rasterization = gsplat_module.rasterization
            except Exception as exc:
                raise GsplatUnavailable(f"gsplat rasterization import failed: {exc}") from exc

        return torch, np, image_module, rasterization

    def _validate_gsplat_cuda_backend(self, torch: Any) -> None:
        try:
            cuda_backend = importlib.import_module("gsplat.cuda._backend")
            cuda_extension = getattr(cuda_backend, "_C", None)
        except Exception as exc:
            raise GsplatUnavailable(f"gsplat CUDA backend import failed: {exc}") from exc

        if cuda_extension is None:
            raise GsplatUnavailable(
                "gsplat CUDA extension is not built or failed to load; install a "
                "CUDA-enabled torch build and rebuild/reinstall gsplat"
            )

        if not (
            hasattr(cuda_extension, "CameraModelType")
            or hasattr(torch.classes, "gsplat")
            or hasattr(torch.ops, "gsplat")
        ):
            raise GsplatUnavailable(
                "gsplat CUDA extension loaded, but camera/projection bindings are missing"
            )

    def _render_gsplat(
        self,
        camera: CameraState,
        width: int,
        height: int,
        quality: RenderQuality,
    ) -> RenderResult:
        scene = self._get_scene()
        torch = self._torch
        if self.device.startswith("cuda"):
            torch.cuda.synchronize()

        start = time.perf_counter()
        viewmat, intrinsics = self._camera_tensors(camera=camera, width=width, height=height)
        background = torch.tensor([0.02, 0.025, 0.03], dtype=torch.float32, device=self.device)
        radius_clip = 1.0 if quality == "interactive" else 0.0

        with torch.inference_mode():
            render_colors, _alphas, _meta = self._rasterization(
                scene.means,
                scene.quats,
                scene.scales,
                scene.opacities,
                scene.colors,
                viewmat,
                intrinsics,
                width,
                height,
                backgrounds=background,
                render_mode="RGB",
                sh_degree=None,
                packed=True,
                camera_model="pinhole",
                radius_clip=radius_clip,
            )
            image_tensor = render_colors[0].clamp(0.0, 1.0).mul(255).to(torch.uint8)
            image_array = image_tensor.cpu().numpy()

        png = self._encode_png(image_array)
        if self.device.startswith("cuda"):
            torch.cuda.synchronize()
        elapsed_ms = (time.perf_counter() - start) * 1000
        return RenderResult(
            image_data_url=f"data:image/png;base64,{png}",
            width=width,
            height=height,
            render_ms=elapsed_ms,
            renderer=self.name,
            quality=quality,
        )

    def _get_scene(self) -> GsplatScene:
        if not self.scene_ply_path:
            raise RuntimeError("No scene PLY configured")
        if self._scene and self._scene.path == self.scene_ply_path:
            return self._scene
        if self._failed_scene_path == self.scene_ply_path and self._last_error:
            raise RuntimeError(self._last_error)

        try:
            arrays = load_gaussian_ply(self.scene_ply_path, np=self._np)
            scene = self._arrays_to_scene(path=self.scene_ply_path, arrays=arrays)
        except Exception as exc:
            self._failed_scene_path = self.scene_ply_path
            self._last_error = f"Could not load 3DGS PLY: {exc}"
            raise RuntimeError(self._last_error) from exc

        self._scene = scene
        self._failed_scene_path = None
        self._last_error = None
        return scene

    def _arrays_to_scene(self, path: str, arrays: GaussianArrays) -> GsplatScene:
        torch = self._torch

        def tensor(values: Any) -> Any:
            return torch.as_tensor(values, dtype=torch.float32, device=self.device).contiguous()

        return GsplatScene(
            path=path,
            means=tensor(arrays.means),
            quats=tensor(arrays.quats),
            scales=tensor(arrays.scales),
            opacities=tensor(arrays.opacities),
            colors=tensor(arrays.colors),
            count=arrays.count,
        )

    def _camera_tensors(
        self,
        camera: CameraState,
        width: int,
        height: int,
    ) -> tuple[Any, Any]:
        np = self._np
        torch = self._torch
        viewmat = orbit_camera_view_matrix(camera=camera, np=np)
        fov_y = math.radians(max(1.0, min(120.0, camera.fov)))
        focal = 0.5 * height / math.tan(fov_y * 0.5)
        intrinsics = np.array(
            [
                [focal, 0.0, width * 0.5],
                [0.0, focal, height * 0.5],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float32,
        )
        return (
            torch.as_tensor(viewmat, dtype=torch.float32, device=self.device).unsqueeze(0),
            torch.as_tensor(intrinsics, dtype=torch.float32, device=self.device).unsqueeze(0),
        )

    def _encode_png(self, image_array: Any) -> str:
        buffer = BytesIO()
        self._image_module.fromarray(image_array, mode="RGB").save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")


def load_gaussian_ply(scene_ply_path: str, np: Any) -> GaussianArrays:
    path = Path(scene_ply_path).expanduser()
    with path.open("rb") as handle:
        header = read_ply_header(handle)
        vertex_data = read_vertex_data(handle, header=header, np=np)

    if header.vertex_count <= 0:
        raise ValueError("PLY contains no vertex entries")
    require_vertex_fields(vertex_data, ("x", "y", "z"))

    means = np.stack(
        [vertex_data["x"], vertex_data["y"], vertex_data["z"]],
        axis=1,
    ).astype(np.float32)
    means = np.nan_to_num(means, nan=0.0, posinf=0.0, neginf=0.0)
    scales = extract_scales(vertex_data=vertex_data, means=means, np=np)
    quats = extract_quats(vertex_data=vertex_data, np=np)
    opacities = extract_opacities(vertex_data=vertex_data, count=header.vertex_count, np=np)
    colors = extract_colors(vertex_data=vertex_data, count=header.vertex_count, np=np)

    return GaussianArrays(
        means=np.ascontiguousarray(means, dtype=np.float32),
        quats=np.ascontiguousarray(quats, dtype=np.float32),
        scales=np.ascontiguousarray(scales, dtype=np.float32),
        opacities=np.ascontiguousarray(opacities, dtype=np.float32),
        colors=np.ascontiguousarray(colors, dtype=np.float32),
        count=header.vertex_count,
    )


def read_ply_header(handle: Any) -> PlyHeader:
    first_line = handle.readline().decode("ascii", errors="replace").strip()
    if first_line != "ply":
        raise ValueError("File does not start with a PLY header")

    data_format = ""
    vertex_count = -1
    vertex_properties: list[PlyProperty] = []
    current_element = ""

    while True:
        raw_line = handle.readline()
        if not raw_line:
            raise ValueError("PLY header ended before end_header")
        line = raw_line.decode("ascii", errors="replace").strip()
        if line == "end_header":
            break
        if not line or line.startswith("comment") or line.startswith("obj_info"):
            continue

        parts = line.split()
        if parts[0] == "format" and len(parts) >= 3:
            data_format = parts[1]
        elif parts[0] == "element" and len(parts) >= 3:
            current_element = parts[1]
            if current_element == "vertex":
                vertex_count = int(parts[2])
        elif parts[0] == "property" and current_element == "vertex":
            if len(parts) >= 5 and parts[1] == "list":
                raise ValueError("PLY vertex list properties are not supported")
            if len(parts) >= 3:
                vertex_properties.append(PlyProperty(name=parts[2], data_type=parts[1]))

    if data_format not in {"ascii", "binary_little_endian", "binary_big_endian"}:
        raise ValueError(f"Unsupported PLY format: {data_format or 'missing'}")
    if vertex_count < 0:
        raise ValueError("PLY header has no vertex element")
    if not vertex_properties:
        raise ValueError("PLY vertex element has no scalar properties")

    return PlyHeader(
        data_format=data_format,
        vertex_count=vertex_count,
        vertex_properties=tuple(vertex_properties),
    )


def read_vertex_data(handle: Any, header: PlyHeader, np: Any) -> dict[str, Any]:
    if header.data_format == "ascii":
        data = np.loadtxt(handle, dtype=np.float32, max_rows=header.vertex_count, ndmin=2)
        if data.shape[0] != header.vertex_count:
            raise ValueError("PLY ended before all vertex rows were read")
        if data.shape[1] < len(header.vertex_properties):
            raise ValueError("PLY vertex rows have fewer columns than the header declares")
        return {
            prop.name: data[:, index].astype(np.float32, copy=False)
            for index, prop in enumerate(header.vertex_properties)
        }

    dtype = np.dtype(
        [
            (prop.name, numpy_dtype_for_ply(prop.data_type, header.data_format))
            for prop in header.vertex_properties
        ]
    )
    data = np.fromfile(handle, dtype=dtype, count=header.vertex_count)
    if data.shape[0] != header.vertex_count:
        raise ValueError("PLY ended before all binary vertex rows were read")
    return {
        prop.name: data[prop.name].astype(np.float32, copy=False)
        for prop in header.vertex_properties
    }


def numpy_dtype_for_ply(data_type: str, data_format: str) -> str:
    try:
        dtype = PLY_NUMPY_DTYPES[data_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported PLY property type: {data_type}") from exc
    if dtype in {"i1", "u1"}:
        return dtype
    endian = "<" if data_format == "binary_little_endian" else ">"
    return f"{endian}{dtype}"


def require_vertex_fields(vertex_data: dict[str, Any], fields: tuple[str, ...]) -> None:
    missing = [field for field in fields if field not in vertex_data]
    if missing:
        raise ValueError(f"PLY is missing required vertex field(s): {', '.join(missing)}")


def extract_scales(vertex_data: dict[str, Any], means: Any, np: Any) -> Any:
    fields = ("scale_0", "scale_1", "scale_2")
    if all(field in vertex_data for field in fields):
        raw_scales = np.stack([vertex_data[field] for field in fields], axis=1)
        return np.exp(np.clip(raw_scales, -20.0, 10.0)).astype(np.float32)

    extent = float(np.max(np.ptp(means, axis=0))) if means.size else 1.0
    default_scale = max(extent * 0.005, 0.001)
    return np.full((means.shape[0], 3), default_scale, dtype=np.float32)


def extract_quats(vertex_data: dict[str, Any], np: Any) -> Any:
    fields = ("rot_0", "rot_1", "rot_2", "rot_3")
    if all(field in vertex_data for field in fields):
        quats = np.stack([vertex_data[field] for field in fields], axis=1).astype(np.float32)
    else:
        quats = np.zeros((len(next(iter(vertex_data.values()))), 4), dtype=np.float32)
        quats[:, 0] = 1.0

    norms = np.linalg.norm(quats, axis=1, keepdims=True)
    quats = quats / np.maximum(norms, 1e-8)
    invalid = norms[:, 0] <= 1e-8
    if np.any(invalid):
        quats[invalid] = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    return quats


def extract_opacities(vertex_data: dict[str, Any], count: int, np: Any) -> Any:
    if "opacity" not in vertex_data:
        return np.full((count,), 0.95, dtype=np.float32)
    opacity_logits = np.clip(vertex_data["opacity"], -20.0, 20.0)
    return (1.0 / (1.0 + np.exp(-opacity_logits))).astype(np.float32)


def extract_colors(vertex_data: dict[str, Any], count: int, np: Any) -> Any:
    dc_fields = ("f_dc_0", "f_dc_1", "f_dc_2")
    rgb_fields = ("red", "green", "blue")
    if all(field in vertex_data for field in dc_fields):
        dc = np.stack([vertex_data[field] for field in dc_fields], axis=1)
        return np.clip(dc * SH_C0 + 0.5, 0.0, 1.0).astype(np.float32)
    if all(field in vertex_data for field in rgb_fields):
        rgb = np.stack([vertex_data[field] for field in rgb_fields], axis=1)
        divisor = 255.0 if float(np.max(rgb)) > 1.0 else 1.0
        return np.clip(rgb / divisor, 0.0, 1.0).astype(np.float32)
    return np.full((count, 3), 0.82, dtype=np.float32)


def orbit_camera_view_matrix(camera: CameraState, np: Any) -> Any:
    target = np.array((camera.target + [0.0, 0.0, 0.0])[:3], dtype=np.float32)
    cos_pitch = math.cos(camera.pitch)
    offset = np.array(
        [
            math.sin(camera.yaw) * cos_pitch,
            math.sin(camera.pitch),
            -math.cos(camera.yaw) * cos_pitch,
        ],
        dtype=np.float32,
    )
    eye = target + offset * max(camera.distance, 0.001)
    forward = normalize_vector(target - eye, np=np)
    world_up = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    if abs(float(np.dot(forward, world_up))) > 0.98:
        world_up = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    right = normalize_vector(np.cross(world_up, forward), np=np)
    down = normalize_vector(np.cross(right, forward), np=np)

    view = np.eye(4, dtype=np.float32)
    view[:3, :3] = np.stack([right, down, forward], axis=0)
    view[:3, 3] = -view[:3, :3] @ eye
    return view


def normalize_vector(vector: Any, np: Any) -> Any:
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-8:
        return vector
    return vector / norm
