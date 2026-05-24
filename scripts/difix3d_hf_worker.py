#!/usr/bin/env python3
"""Persistent Difix3D Hugging Face worker for low-latency refinement.

The one-shot `difix3d_hf_adapter.py` is simple and robust, but it pays Python
startup and model-loading cost for every frame. This worker loads the pipeline
once, then accepts newline-delimited JSON requests on stdin:

{"request_id": "...", "input": "/tmp/input.png", "output": "/tmp/output.png"}

It replies on stdout with a matching JSON line. Human-readable status goes to
stderr so the backend can keep stdout as a machine protocol.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from difix3d_hf_adapter import (
    add_difix_repo_to_path,
    resize_image,
    select_dimensions,
    select_model_name,
)


def main() -> int:
    args = parse_args()
    python_executable = args.python or os.getenv("DIFIX3D_PYTHON")

    if python_executable and not args.worker:
        os.execvp(
            python_executable,
            build_worker_exec_args(python_executable, sys.argv),
        )

    worker = HFDifixWorker(args)
    worker.run()
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a persistent Difix3D Hugging Face refinement worker."
    )
    parser.add_argument(
        "--repo",
        default=os.getenv("DIFIX3D_REPO"),
        help="Path to nv-tlabs/Difix3D. The repo src/ directory is added to sys.path.",
    )
    parser.add_argument(
        "--python",
        default=None,
        help="Python executable for the Difix3D environment. Defaults to DIFIX3D_PYTHON.",
    )
    parser.add_argument(
        "--model-name",
        default=os.getenv("DIFIX3D_MODEL_NAME"),
        help="Hugging Face model name. Defaults to nvidia/difix or nvidia/difix_ref.",
    )
    parser.add_argument(
        "--ref-image",
        default=os.getenv("DIFIX3D_REF_IMAGE"),
        help="Optional reference image for nvidia/difix_ref.",
    )
    parser.add_argument(
        "--prompt",
        default=os.getenv("DIFIX3D_PROMPT", "remove degradation"),
        help="Prompt passed to Difix3D.",
    )
    parser.add_argument(
        "--timestep",
        type=int,
        default=int(os.getenv("DIFIX3D_TIMESTEP", "199")),
        help="Diffusion timestep.",
    )
    parser.add_argument(
        "--num-inference-steps",
        type=int,
        default=int(os.getenv("DIFIX3D_NUM_INFERENCE_STEPS", "1")),
        help="Number of inference steps.",
    )
    parser.add_argument(
        "--guidance-scale",
        type=float,
        default=float(os.getenv("DIFIX3D_GUIDANCE_SCALE", "0.0")),
        help="Classifier-free guidance scale.",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=int(os.getenv("DIFIX3D_HEIGHT", "0")),
        help="Output height. 0 keeps the input aspect ratio and applies --max-side.",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=int(os.getenv("DIFIX3D_WIDTH", "0")),
        help="Output width. 0 keeps the input aspect ratio and applies --max-side.",
    )
    parser.add_argument(
        "--max-side",
        type=int,
        default=int(os.getenv("DIFIX3D_MAX_SIDE", "512")),
        help="Maximum side length when width or height is not explicitly set.",
    )
    parser.add_argument(
        "--device",
        default=os.getenv("DIFIX3D_DEVICE", "cuda"),
        help="Torch device for the pipeline.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=int(os.getenv("DIFIX3D_SEED", "42")),
        help="Torch random seed.",
    )
    parser.add_argument(
        "--local-files-only",
        action="store_true",
        default=os.getenv("DIFIX3D_LOCAL_FILES_ONLY", "0") == "1",
        help="Only use locally cached Hugging Face files.",
    )
    parser.add_argument(
        "--worker",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(argv)


def build_worker_exec_args(
    python_executable: str,
    current_argv: Sequence[str],
) -> list[str]:
    command = [python_executable, str(Path(__file__).resolve()), "--worker"]
    skip_next = False
    for arg in current_argv[1:]:
        if skip_next:
            skip_next = False
            continue
        if arg == "--worker":
            continue
        if arg == "--python":
            skip_next = True
            continue
        if arg.startswith("--python="):
            continue
        command.append(arg)
    return command


class HFDifixWorker:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        add_difix_repo_to_path(args.repo)

        import torch
        from PIL import Image
        from diffusers.utils import load_image
        from pipeline_difix import DifixPipeline

        self.torch = torch
        self.Image = Image
        self.load_image = load_image
        self.ref_image = (
            load_image(str(Path(args.ref_image).expanduser())).convert("RGB")
            if args.ref_image
            else None
        )

        if args.device.startswith("cuda"):
            torch.backends.cuda.matmul.allow_tf32 = True

        model_name = select_model_name(args.model_name, args.ref_image)
        print(
            f"Loading DifixPipeline {model_name} on {args.device}",
            file=sys.stderr,
            flush=True,
        )
        self.pipe = DifixPipeline.from_pretrained(
            model_name,
            trust_remote_code=True,
            local_files_only=args.local_files_only,
        )
        self.pipe.to(args.device)
        self.pipe.set_progress_bar_config(disable=True)
        print("Difix3D worker ready", file=sys.stderr, flush=True)

    def run(self) -> None:
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue

            request_id = ""
            try:
                request = json.loads(line)
                request_id = str(request.get("request_id") or "")
                action = request.get("action")
                if action == "ping":
                    response = {
                        "request_id": request_id,
                        "ok": True,
                        "status": "ready",
                    }
                elif action == "warmup":
                    response = self.warmup(request)
                else:
                    response = self.refine(request)
            except Exception as exc:
                response = {
                    "request_id": request_id,
                    "ok": False,
                    "error": f"{exc.__class__.__name__}: {exc}",
                }

            print(json.dumps(response), flush=True)

    def warmup(self, request: dict[str, Any]) -> dict[str, Any]:
        request_id = str(request.get("request_id") or "")
        base_size = max(8, self.args.max_side or 512)
        image_width = _positive_int(request.get("width")) or base_size
        image_height = _positive_int(request.get("height")) or base_size
        dummy_image = self.Image.new(
            "RGB",
            (image_width, image_height),
            color=(127, 127, 127),
        )
        _output_image, width, height = self.run_pipeline(dummy_image)
        return {
            "request_id": request_id,
            "ok": True,
            "status": "ready",
            "input_width": image_width,
            "input_height": image_height,
            "width": width,
            "height": height,
        }

    def refine(self, request: dict[str, Any]) -> dict[str, Any]:
        input_path = Path(str(request["input"])).expanduser().resolve()
        output_path = Path(str(request["output"])).expanduser().resolve()
        input_image = self.load_image(str(input_path)).convert("RGB")

        output_image, width, height = self.run_pipeline(input_image)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_image.save(output_path)
        return {
            "request_id": str(request.get("request_id") or ""),
            "ok": True,
            "output": str(output_path),
            "width": width,
            "height": height,
        }

    def run_pipeline(self, input_image: Any) -> tuple[Any, int, int]:
        width, height = select_dimensions(
            requested_width=self.args.width,
            requested_height=self.args.height,
            max_side=self.args.max_side,
            image_width=input_image.width,
            image_height=input_image.height,
        )
        input_image = resize_image(input_image, width=width, height=height)

        generator = self.torch.Generator(device=self.args.device).manual_seed(self.args.seed)
        pipeline_args = {
            "prompt": self.args.prompt,
            "image": input_image,
            "num_inference_steps": self.args.num_inference_steps,
            "timesteps": [self.args.timestep],
            "guidance_scale": self.args.guidance_scale,
            "height": height,
            "width": width,
            "generator": generator,
        }
        if self.ref_image is not None:
            pipeline_args["ref_image"] = resize_image(
                self.ref_image,
                width=width,
                height=height,
            )

        with self.torch.inference_mode():
            output_image = self.pipe(**pipeline_args).images[0]

        return output_image, width, height


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


if __name__ == "__main__":
    raise SystemExit(main())
