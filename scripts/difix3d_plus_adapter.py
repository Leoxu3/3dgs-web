#!/usr/bin/env python3
"""CLI adapter from this viewer's refiner contract to nv-tlabs/Difix3D.

The viewer's CommandDifixRefiner expects a command that reads one image from
`--input` and writes one exact file to `--output`. The upstream Difix3D
`src/inference_difix.py` script writes to an output directory and keeps the
input filename, so this wrapper runs the upstream script and copies the
generated file to the requested output path.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    args = parse_args()
    repo = resolve_path(args.repo or os.getenv("DIFIX3D_REPO"), "DIFIX3D_REPO")
    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    script_path = resolve_script(repo, args.script)
    python_executable = args.python or os.getenv("DIFIX3D_PYTHON") or sys.executable

    model_args = build_model_args(args)
    if not model_args:
        raise SystemExit(
            "Configure DIFIX3D_MODEL_PATH or DIFIX3D_MODEL_NAME, or pass "
            "--model-path/--model-name."
        )

    with tempfile.TemporaryDirectory(prefix="difix3d-plus-output-") as output_dir:
        command = [
            python_executable,
            str(script_path),
            "--input_image",
            str(input_path),
            "--prompt",
            args.prompt,
            "--output_dir",
            output_dir,
            "--timestep",
            str(args.timestep),
            "--height",
            str(args.height),
            "--width",
            str(args.width),
            *model_args,
        ]
        if args.ref_image:
            command.extend(["--ref_image", args.ref_image])

        subprocess.run(command, cwd=repo, check=True)

        generated_path = find_generated_image(Path(output_dir), input_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(generated_path, output_path)

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Difix3D+ inference for one image and write one output file."
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
        default=None,
        help="Path to nv-tlabs/Difix3D. Defaults to DIFIX3D_REPO.",
    )
    parser.add_argument(
        "--script",
        default=None,
        help=(
            "Path to inference_difix.py. Defaults to "
            "$DIFIX3D_REPO/src/inference_difix.py."
        ),
    )
    parser.add_argument(
        "--python",
        default=None,
        help="Python executable for the Difix3D environment. Defaults to DIFIX3D_PYTHON.",
    )
    parser.add_argument(
        "--model-path",
        default=os.getenv("DIFIX3D_MODEL_PATH"),
        help="Path to model.pkl. Defaults to DIFIX3D_MODEL_PATH.",
    )
    parser.add_argument(
        "--model-name",
        default=os.getenv("DIFIX3D_MODEL_NAME"),
        help="Pretrained model name. Defaults to DIFIX3D_MODEL_NAME.",
    )
    parser.add_argument(
        "--ref-image",
        default=os.getenv("DIFIX3D_REF_IMAGE"),
        help="Optional reference image or directory for nvidia/difix_ref.",
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
        "--height",
        type=int,
        default=int(os.getenv("DIFIX3D_HEIGHT", "576")),
        help="Inference height.",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=int(os.getenv("DIFIX3D_WIDTH", "1024")),
        help="Inference width.",
    )
    return parser.parse_args()


def resolve_path(raw_path: str | None, label: str) -> Path:
    if not raw_path:
        raise SystemExit(f"{label} is required.")
    path = Path(raw_path).expanduser().resolve()
    if not path.exists():
        raise SystemExit(f"{label} does not exist: {path}")
    return path


def resolve_script(repo: Path, raw_script: str | None) -> Path:
    script = Path(raw_script).expanduser() if raw_script else repo / "src" / "inference_difix.py"
    if not script.is_absolute():
        script = (repo / script).resolve()
    if not script.exists():
        raise SystemExit(f"Difix3D inference script does not exist: {script}")
    return script


def build_model_args(args: argparse.Namespace) -> list[str]:
    model_args: list[str] = []
    if args.model_path:
        model_args.extend(["--model_path", str(Path(args.model_path).expanduser())])
    if args.model_name:
        model_args.extend(["--model_name", args.model_name])
    return model_args


def find_generated_image(output_dir: Path, input_path: Path) -> Path:
    expected = output_dir / input_path.name
    if expected.exists():
        return expected

    image_candidates = [
        path
        for path in output_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    ]
    if len(image_candidates) == 1:
        return image_candidates[0]

    generated = ", ".join(path.name for path in image_candidates) or "none"
    raise SystemExit(
        f"Could not find Difix3D output for {input_path.name}; generated files: {generated}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
