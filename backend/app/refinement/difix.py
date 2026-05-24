"""Difix3D / Difix3D+ refiner adapters.

The real projects may be installed in different ways on lab machines, so this
module provides a small stable abstraction around either a Python callable or a
CLI command. If construction or runtime processing fails, the app returns the
input frame through `FallbackRefiner` instead of breaking the viewer.
`REFINER_BACKEND` selects adapter/fallback behavior; `DIFIX3D_VARIANT` is only a
label passed through to custom adapters.
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import selectors
import shlex
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

from backend.app.refinement.base import (
    Refiner,
    RefinerRuntimeError,
    RefinerUnavailable,
    RefinementResult,
)
from backend.app.refinement.fallback import FallbackRefiner
from backend.app.refinement.image_data import (
    decode_data_url,
    encode_data_url,
    extension_for_mime,
    mime_for_path,
    mime_type_from_data_url,
)

if TYPE_CHECKING:
    from backend.app.config import Settings


_BACKEND_ALIASES = {
    "": "auto",
    "auto": "auto",
    "none": "fallback",
    "off": "fallback",
    "disabled": "fallback",
    "fallback": "fallback",
    "adapter": "adapter",
    "configured": "adapter",
    "external": "adapter",
    "difix": "adapter",
    "difix3d": "adapter",
    "difix3d+": "adapter",
    "difix3d-plus": "adapter",
    "difix3d_plus": "adapter",
    "difix3dplus": "adapter",
    "plus": "adapter",
}

_VARIANT_ALIASES = {
    "difix": "difix3d",
    "difix3d": "difix3d",
    "difix3d+": "difix3d_plus",
    "difix3d-plus": "difix3d_plus",
    "difix3d_plus": "difix3d_plus",
    "difix3dplus": "difix3d_plus",
    "plus": "difix3d_plus",
}


@dataclass(frozen=True)
class DifixRefinerConfig:
    backend: str = "auto"
    variant: str = ""
    command_template: str = ""
    worker_command_template: str = ""
    python_callable: str = ""
    timeout_seconds: float = 120.0

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "DifixRefinerConfig":
        if settings is None:
            return cls(
                backend=os.getenv("REFINER_BACKEND", "auto"),
                variant=os.getenv("DIFIX3D_VARIANT", ""),
                command_template=os.getenv("DIFIX3D_COMMAND", ""),
                worker_command_template=os.getenv("DIFIX3D_WORKER_COMMAND", ""),
                python_callable=os.getenv("DIFIX3D_PYTHON_CALLABLE", ""),
                timeout_seconds=_float_env("DIFIX3D_TIMEOUT_SECONDS", 120.0),
            )

        return cls(
            backend=settings.refiner_backend,
            variant=settings.difix3d_variant,
            command_template=settings.difix3d_command,
            worker_command_template=settings.difix3d_worker_command,
            python_callable=settings.difix3d_python_callable,
            timeout_seconds=settings.difix3d_timeout_seconds,
        )


class SafeRefiner:
    """Runtime safety wrapper that preserves fallback behavior."""

    is_fallback = False

    def __init__(self, inner: Refiner) -> None:
        self.inner = inner
        self.name = inner.name
        self.variant = getattr(inner, "variant", "")

    def close(self) -> None:
        close = getattr(self.inner, "close", None)
        if callable(close):
            close()

    def refine(
        self,
        image_data_url: str,
        camera: dict[str, Any] | None = None,
    ) -> RefinementResult:
        if _is_svg_data_url(image_data_url):
            return FallbackRefiner(
                reason=(
                    "Difix3D skipped / fallback mode "
                    "(SVG placeholder input is not a raster frame)"
                )
            ).refine(image_data_url=image_data_url, camera=camera)

        try:
            return self.inner.refine(image_data_url=image_data_url, camera=camera)
        except Exception as exc:
            fallback = FallbackRefiner(
                reason=(
                    f"{self.inner.name} failed / fallback mode "
                    f"({exc.__class__.__name__}: {exc})"
                )
            )
            return fallback.refine(image_data_url=image_data_url, camera=camera)


class CommandDifixRefiner:
    is_fallback = False

    def __init__(self, variant: str, config: DifixRefinerConfig) -> None:
        if not config.command_template:
            raise RefinerUnavailable("DIFIX3D_COMMAND is not configured")

        self.variant = variant
        self.name = f"{variant}-command-refiner"
        self.command_template = config.command_template
        self.timeout_seconds = config.timeout_seconds

    def refine(
        self,
        image_data_url: str,
        camera: dict[str, Any] | None = None,
    ) -> RefinementResult:
        start = time.perf_counter()
        timings: dict[str, float] = {}

        phase_start = time.perf_counter()
        image_bytes, mime_type = decode_data_url(image_data_url)
        image_suffix = extension_for_mime(mime_type)
        timings["decode_input_ms"] = _elapsed_ms(phase_start)

        with tempfile.TemporaryDirectory(prefix="difix3d-refine-") as temp_dir:
            work_dir = Path(temp_dir)
            input_path = work_dir / f"input{image_suffix}"
            output_path = work_dir / f"output{image_suffix}"
            camera_path = work_dir / "camera.json"

            phase_start = time.perf_counter()
            input_path.write_bytes(image_bytes)
            camera_path.write_text(json.dumps(camera or {}), encoding="utf-8")
            timings["write_input_ms"] = _elapsed_ms(phase_start)

            phase_start = time.perf_counter()
            argv = self._command_args(
                input_path=input_path,
                output_path=output_path,
                camera_path=camera_path,
            )
            timings["build_command_ms"] = _elapsed_ms(phase_start)

            try:
                phase_start = time.perf_counter()
                subprocess.run(
                    argv,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                )
                timings["subprocess_ms"] = _elapsed_ms(phase_start)
            except subprocess.TimeoutExpired as exc:
                timings["subprocess_ms"] = _elapsed_ms(phase_start)
                raise RefinerRuntimeError(
                    f"command timed out after {self.timeout_seconds:g}s"
                ) from exc
            except subprocess.CalledProcessError as exc:
                timings["subprocess_ms"] = _elapsed_ms(phase_start)
                detail = _short_process_output(exc)
                raise RefinerRuntimeError(
                    f"command exited with status {exc.returncode}{detail}"
                ) from exc

            if not output_path.exists():
                raise RefinerRuntimeError(f"command did not create {output_path.name}")

            phase_start = time.perf_counter()
            output_bytes = output_path.read_bytes()
            timings["read_output_ms"] = _elapsed_ms(phase_start)

        output_mime = mime_for_path(output_path, fallback=mime_type)
        phase_start = time.perf_counter()
        image_data = encode_data_url(output_bytes, output_mime)
        timings["encode_output_ms"] = _elapsed_ms(phase_start)
        elapsed_ms = (time.perf_counter() - start) * 1000
        timings["total_ms"] = elapsed_ms
        return RefinementResult(
            image_data_url=image_data,
            latency_ms=elapsed_ms,
            refiner=self.name,
            status="ok",
            message=f"{self.variant} adapter refinement complete",
            fallback_mode=False,
            timings_ms=timings,
        )

    def _command_args(
        self,
        input_path: Path,
        output_path: Path,
        camera_path: Path,
    ) -> list[str]:
        try:
            command = self.command_template.format(
                input=str(input_path),
                output=str(output_path),
                camera=str(camera_path),
                variant=self.variant,
            )
        except KeyError as exc:
            raise RefinerRuntimeError(f"unknown command placeholder: {exc}") from exc

        argv = shlex.split(command)
        if not argv:
            raise RefinerRuntimeError("empty DIFIX3D_COMMAND")
        return argv


class WorkerDifixRefiner:
    """Persistent line-oriented worker adapter.

    The worker process keeps the Difix pipeline/model resident. Per request, the
    backend writes the input frame to a temporary file, sends a JSON line with
    input/output paths, and waits for a matching JSON response.
    """

    is_fallback = False

    def __init__(self, variant: str, config: DifixRefinerConfig) -> None:
        if not config.worker_command_template:
            raise RefinerUnavailable("DIFIX3D_WORKER_COMMAND is not configured")

        self.variant = variant
        self.name = f"{variant}-worker-refiner"
        self.worker_command_template = config.worker_command_template
        self.timeout_seconds = config.timeout_seconds
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None

    def refine(
        self,
        image_data_url: str,
        camera: dict[str, Any] | None = None,
    ) -> RefinementResult:
        start = time.perf_counter()
        timings: dict[str, float] = {}

        phase_start = time.perf_counter()
        image_bytes, mime_type = decode_data_url(image_data_url)
        image_suffix = extension_for_mime(mime_type)
        timings["decode_input_ms"] = _elapsed_ms(phase_start)

        with tempfile.TemporaryDirectory(prefix="difix3d-worker-refine-") as temp_dir:
            work_dir = Path(temp_dir)
            input_path = work_dir / f"input{image_suffix}"
            output_path = work_dir / f"output{image_suffix}"
            camera_path = work_dir / "camera.json"

            phase_start = time.perf_counter()
            input_path.write_bytes(image_bytes)
            camera_path.write_text(json.dumps(camera or {}), encoding="utf-8")
            timings["write_input_ms"] = _elapsed_ms(phase_start)

            with self._lock:
                phase_start = time.perf_counter()
                self._send_worker_request(
                    input_path=input_path,
                    output_path=output_path,
                    camera_path=camera_path,
                    camera=camera or {},
                )
                timings["worker_roundtrip_ms"] = _elapsed_ms(phase_start)

            if not output_path.exists():
                raise RefinerRuntimeError(f"worker did not create {output_path.name}")

            phase_start = time.perf_counter()
            output_bytes = output_path.read_bytes()
            timings["read_output_ms"] = _elapsed_ms(phase_start)

        output_mime = mime_for_path(output_path, fallback=mime_type)
        phase_start = time.perf_counter()
        image_data = encode_data_url(output_bytes, output_mime)
        timings["encode_output_ms"] = _elapsed_ms(phase_start)
        elapsed_ms = (time.perf_counter() - start) * 1000
        timings["total_ms"] = elapsed_ms
        return RefinementResult(
            image_data_url=image_data,
            latency_ms=elapsed_ms,
            refiner=self.name,
            status="ok",
            message=f"{self.variant} adapter refinement complete",
            fallback_mode=False,
            timings_ms=timings,
        )

    def close(self) -> None:
        with self._lock:
            self._terminate_process_locked()

    def _send_worker_request(
        self,
        input_path: Path,
        output_path: Path,
        camera_path: Path,
        camera: dict[str, Any],
    ) -> dict[str, Any]:
        process = self._ensure_process_locked()
        if process.stdin is None:
            raise RefinerRuntimeError("worker stdin is unavailable")

        request_id = uuid.uuid4().hex
        payload = {
            "request_id": request_id,
            "input": str(input_path),
            "output": str(output_path),
            "camera": camera,
            "camera_path": str(camera_path),
            "variant": self.variant,
        }

        try:
            process.stdin.write(json.dumps(payload) + "\n")
            process.stdin.flush()
        except BrokenPipeError as exc:
            self._terminate_process_locked()
            raise RefinerRuntimeError("worker pipe closed while sending request") from exc

        return self._read_worker_response(process=process, request_id=request_id)

    def _read_worker_response(
        self,
        process: subprocess.Popen[str],
        request_id: str,
    ) -> dict[str, Any]:
        if process.stdout is None:
            raise RefinerRuntimeError("worker stdout is unavailable")

        deadline = time.monotonic() + self.timeout_seconds
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)

        try:
            while True:
                if process.poll() is not None:
                    self._process = None
                    raise RefinerRuntimeError(
                        f"worker exited with status {process.returncode}"
                    )

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._terminate_process_locked()
                    raise RefinerRuntimeError(
                        f"worker timed out after {self.timeout_seconds:g}s"
                    )

                events = selector.select(timeout=remaining)
                if not events:
                    continue

                line = process.stdout.readline()
                if not line:
                    continue

                try:
                    response = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if response.get("request_id") != request_id:
                    continue
                if not response.get("ok"):
                    message = str(response.get("error") or "worker failed")
                    raise RefinerRuntimeError(message)
                return response
        finally:
            selector.close()

    def _ensure_process_locked(self) -> subprocess.Popen[str]:
        if self._process is not None and self._process.poll() is None:
            return self._process

        self._terminate_process_locked()
        argv = self._worker_args()
        try:
            self._process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise RefinerRuntimeError(f"could not start worker: {exc}") from exc
        return self._process

    def _worker_args(self) -> list[str]:
        try:
            command = self.worker_command_template.format(variant=self.variant)
        except KeyError as exc:
            raise RefinerRuntimeError(f"unknown worker command placeholder: {exc}") from exc

        argv = shlex.split(command)
        if not argv:
            raise RefinerRuntimeError("empty DIFIX3D_WORKER_COMMAND")
        return argv

    def _terminate_process_locked(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return

        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


class PythonCallableDifixRefiner:
    is_fallback = False

    def __init__(self, variant: str, config: DifixRefinerConfig) -> None:
        if not config.python_callable:
            raise RefinerUnavailable("DIFIX3D_PYTHON_CALLABLE is not configured")

        self.variant = variant
        self.name = f"{variant}-python-refiner"
        self.callable_path = config.python_callable
        self._callable = _load_python_callable(config.python_callable)

    def refine(
        self,
        image_data_url: str,
        camera: dict[str, Any] | None = None,
    ) -> RefinementResult:
        start = time.perf_counter()
        output = self._invoke(image_data_url=image_data_url, camera=camera)
        elapsed_ms = (time.perf_counter() - start) * 1000

        if isinstance(output, RefinementResult):
            return output

        image_data = _coerce_callable_output(output, input_data_url=image_data_url)
        return RefinementResult(
            image_data_url=image_data,
            latency_ms=elapsed_ms,
            refiner=self.name,
            status="ok",
            message=f"{self.variant} adapter refinement complete",
            fallback_mode=False,
        )

    def _invoke(
        self,
        image_data_url: str,
        camera: dict[str, Any] | None,
    ) -> Any:
        try:
            signature = inspect.signature(self._callable)
        except (TypeError, ValueError):
            return self._callable(image_data_url)

        parameters = signature.parameters
        if any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        ):
            return self._callable(
                image_data_url=image_data_url,
                camera=camera,
                variant=self.variant,
            )

        kwargs: dict[str, Any] = {}
        if "image_data_url" in parameters:
            kwargs["image_data_url"] = image_data_url
        elif "image" in parameters:
            kwargs["image"] = image_data_url
        if "camera" in parameters:
            kwargs["camera"] = camera
        if "variant" in parameters:
            kwargs["variant"] = self.variant
        if kwargs:
            return self._callable(**kwargs)

        positional_parameters = [
            parameter
            for parameter in parameters.values()
            if parameter.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        if len(positional_parameters) >= 2:
            return self._callable(image_data_url, camera)
        return self._callable(image_data_url)


def create_refiner(settings: Settings | None = None) -> Refiner:
    config = DifixRefinerConfig.from_settings(settings)
    backend = _normalize_backend(config.backend)
    variant = _resolve_variant(config)

    if backend == "fallback":
        return FallbackRefiner(
            reason="Difix3D unavailable / fallback mode (REFINER_BACKEND=fallback)"
        )

    try:
        refiner = _create_configured_refiner(
            backend=backend,
            variant=variant,
            config=config,
        )
    except RefinerUnavailable as exc:
        return FallbackRefiner(reason=f"Difix3D unavailable / fallback mode ({exc})")

    return SafeRefiner(refiner)


def _create_configured_refiner(
    backend: str,
    variant: str,
    config: DifixRefinerConfig,
) -> Refiner:
    if backend == "auto":
        if config.python_callable:
            return PythonCallableDifixRefiner(variant=variant, config=config)
        if config.worker_command_template:
            return WorkerDifixRefiner(variant=variant, config=config)
        if config.command_template:
            return CommandDifixRefiner(variant=variant, config=config)
        raise RefinerUnavailable(
            "no DIFIX3D_COMMAND, DIFIX3D_WORKER_COMMAND, or "
            "DIFIX3D_PYTHON_CALLABLE adapter is configured"
        )

    if backend != "adapter":
        raise RefinerUnavailable(f"unsupported REFINER_BACKEND={backend!r}")

    if config.python_callable:
        return PythonCallableDifixRefiner(variant=variant, config=config)
    if config.worker_command_template:
        return WorkerDifixRefiner(variant=variant, config=config)
    if config.command_template:
        return CommandDifixRefiner(variant=variant, config=config)

    raise RefinerUnavailable(
        "REFINER_BACKEND=adapter requires DIFIX3D_COMMAND, "
        "DIFIX3D_WORKER_COMMAND, or DIFIX3D_PYTHON_CALLABLE"
    )


def _normalize_backend(backend: str) -> str:
    normalized = backend.strip().lower().replace(" ", "_")
    return _BACKEND_ALIASES.get(normalized, normalized)


def _resolve_variant(config: DifixRefinerConfig) -> str:
    if config.variant.strip():
        return _normalize_variant(config.variant)

    backend_variant = _variant_from_legacy_backend(config.backend)
    if backend_variant:
        return backend_variant

    return "difix3d"


def _variant_from_legacy_backend(backend: str) -> str:
    normalized = backend.strip().lower().replace(" ", "_")
    return _VARIANT_ALIASES.get(normalized, "")


def _normalize_variant(variant: str) -> str:
    normalized = variant.strip().lower().replace(" ", "_")
    return _VARIANT_ALIASES.get(normalized, normalized)


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def _is_svg_data_url(image_data_url: str) -> bool:
    try:
        return mime_type_from_data_url(image_data_url).lower() == "image/svg+xml"
    except RefinerRuntimeError:
        return False


def _load_python_callable(callable_path: str) -> Callable[..., Any]:
    module_name, separator, attribute_path = callable_path.partition(":")
    if not separator or not module_name or not attribute_path:
        raise RefinerUnavailable(
            "DIFIX3D_PYTHON_CALLABLE must use the form 'module:function'"
        )

    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        raise RefinerUnavailable(
            f"could not import DIFIX3D_PYTHON_CALLABLE module {module_name!r}: {exc}"
        ) from exc

    target: Any = module
    try:
        for attribute in attribute_path.split("."):
            target = getattr(target, attribute)
    except AttributeError as exc:
        raise RefinerUnavailable(
            f"DIFIX3D_PYTHON_CALLABLE target {callable_path!r} was not found"
        ) from exc

    if not callable(target):
        raise RefinerUnavailable(
            f"DIFIX3D_PYTHON_CALLABLE target {callable_path!r} is not callable"
        )
    return target


def _coerce_callable_output(output: Any, input_data_url: str) -> str:
    _input_bytes, input_mime = decode_data_url(input_data_url)

    if isinstance(output, str):
        if output.startswith("data:"):
            return output
        output_path = Path(output)
        if output_path.exists():
            return encode_data_url(
                output_path.read_bytes(),
                mime_for_path(output_path, fallback=input_mime),
            )

    if isinstance(output, os.PathLike):
        output_path = Path(output)
        return encode_data_url(
            output_path.read_bytes(),
            mime_for_path(output_path, fallback=input_mime),
        )

    if isinstance(output, bytes):
        return encode_data_url(output, input_mime)

    if isinstance(output, dict):
        if isinstance(output.get("image_data_url"), str):
            return output["image_data_url"]
        if isinstance(output.get("data_url"), str):
            return output["data_url"]
        output_path = output.get("output_path") or output.get("path")
        if output_path is not None:
            path = Path(output_path)
            return encode_data_url(
                path.read_bytes(),
                mime_for_path(path, fallback=input_mime),
            )
        output_bytes = output.get("bytes")
        if isinstance(output_bytes, bytes):
            output_mime = str(output.get("mime_type") or input_mime)
            return encode_data_url(output_bytes, output_mime)

    raise RefinerRuntimeError(
        "Python callable must return a data URL, bytes, path, dict, or "
        "RefinementResult"
    )


def _short_process_output(exc: subprocess.CalledProcessError) -> str:
    output = (exc.stderr or exc.stdout or "").strip()
    if not output:
        return ""
    if len(output) > 1200:
        output = f"...{output[-1200:]}"
    return f": {output}"
