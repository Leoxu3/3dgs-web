#!/usr/bin/env python3
"""Difix3D+ Hugging Face pipeline adapter for this viewer.

This adapter avoids the upstream `src/inference_difix.py` checkpoint workflow.
It loads `nvidia/difix` or `nvidia/difix_ref` through DifixPipeline and writes
the exact output file expected by the viewer's CommandDifixRefiner.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence


def main() -> int:
    args = parse_args()
    python_executable = args.python or os.getenv("DIFIX3D_PYTHON")

    if python_executable and not args.worker:
        return subprocess.run(
            build_worker_command(python_executable, sys.argv),
            check=False,
        ).returncode

    run_hf_inference(args)
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Difix3D+ through Hugging Face without local checkpoints."
    )
    parser.add_argument("--input", required=True, help="Input image written by the viewer.")
    parser.add_argument("--output", required=True, help="Output image expected by the viewer.")
    parser.add_argument(
        "--camera",
        default=None,
        help="Camera JSON path from the viewer. Accepted for compatibility; unused.",
    )
    parser.add_argument(
        "--repo",
        default=os.getenv("DIFIX3D_REPO"),
        help=(
            "Path to nv-tlabs/Difix3D. The adapter adds its src/ directory to "
            "PYTHONPATH so `pipeline_difix` can be imported."
        ),
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
        help=(
            "Maximum side length when width or height is not explicitly set. "
            "Use 0 to disable the cap. Defaults to DIFIX3D_MAX_SIDE or 512."
        ),
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


def build_worker_command(python_executable: str, current_argv: Sequence[str]) -> list[str]:
    command = [python_executable, str(Path(__file__).resolve()), "--worker"]
    command.extend(arg for arg in current_argv[1:] if arg != "--worker")
    return command


def run_hf_inference(args: argparse.Namespace) -> None:
    add_difix_repo_to_path(args.repo)

    import torch
    from diffusers.utils import load_image
    from pipeline_difix import DifixPipeline

    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    input_image = load_image(str(input_path)).convert("RGB")
    width, height = select_dimensions(
        requested_width=args.width,
        requested_height=args.height,
        max_side=args.max_side,
        image_width=input_image.width,
        image_height=input_image.height,
    )
    input_image = resize_image(input_image, width=width, height=height)
    model_name = select_model_name(args.model_name, args.ref_image)

    pipe = DifixPipeline.from_pretrained(
        model_name,
        trust_remote_code=True,
        local_files_only=args.local_files_only,
    )
    pipe.to(args.device)
    pipe.set_progress_bar_config(disable=True)

    generator = torch.Generator(device=args.device).manual_seed(args.seed)
    pipeline_args = {
        "prompt": args.prompt,
        "image": input_image,
        "num_inference_steps": args.num_inference_steps,
        "timesteps": [args.timestep],
        "guidance_scale": args.guidance_scale,
        "height": height,
        "width": width,
        "generator": generator,
    }
    if args.ref_image:
        ref_image = load_image(str(Path(args.ref_image).expanduser())).convert("RGB")
        pipeline_args["ref_image"] = resize_image(
            ref_image,
            width=width,
            height=height,
        )

    with torch.inference_mode():
        output_image = pipe(**pipeline_args).images[0]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_image.save(output_path)


def add_difix_repo_to_path(raw_repo: str | None) -> None:
    if not raw_repo:
        return

    repo = Path(raw_repo).expanduser().resolve()
    src = repo / "src"
    if not src.exists():
        raise SystemExit(f"DIFIX3D_REPO/src does not exist: {src}")

    for path in (src, repo):
        path_string = str(path)
        if path_string not in sys.path:
            sys.path.insert(0, path_string)


def select_model_name(raw_model_name: str | None, ref_image: str | None) -> str:
    if raw_model_name:
        return raw_model_name
    return "nvidia/difix_ref" if ref_image else "nvidia/difix"


def select_dimensions(
    requested_width: int,
    requested_height: int,
    max_side: int,
    image_width: int,
    image_height: int,
) -> tuple[int, int]:
    explicit_size = requested_width > 0 and requested_height > 0
    if explicit_size:
        width = requested_width
        height = requested_height
    elif requested_width > 0:
        width = requested_width
        height = round(image_height * (width / image_width))
    elif requested_height > 0:
        height = requested_height
        width = round(image_width * (height / image_height))
    else:
        width = image_width
        height = image_height

    if not explicit_size and max_side > 0 and max(width, height) > max_side:
        scale = max_side / max(width, height)
        width = round(width * scale)
        height = round(height * scale)

    return round_to_multiple_of_8(width), round_to_multiple_of_8(height)


def resize_image(image: object, width: int, height: int) -> object:
    if getattr(image, "size", None) == (width, height):
        return image

    try:
        from PIL import Image

        resample = Image.Resampling.LANCZOS
    except (ImportError, AttributeError):
        resample = 1
    return image.resize((width, height), resample=resample)


def round_to_multiple_of_8(value: int) -> int:
    return max(8, value - (value % 8))


if __name__ == "__main__":
    raise SystemExit(main())
