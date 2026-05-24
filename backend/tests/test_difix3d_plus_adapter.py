import subprocess
import sys
from pathlib import Path


def test_difix3d_plus_adapter_copies_upstream_output(tmp_path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    adapter = project_root / "scripts" / "difix3d_plus_adapter.py"
    fake_repo = tmp_path / "Difix3D"
    fake_src = fake_repo / "src"
    fake_src.mkdir(parents=True)
    fake_model = fake_repo / "checkpoints" / "model.pkl"
    fake_model.parent.mkdir()
    fake_model.write_bytes(b"fake model")
    fake_inference = fake_src / "inference_difix.py"
    fake_inference.write_text(
        "import argparse\n"
        "import shutil\n"
        "from pathlib import Path\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--input_image', required=True)\n"
        "parser.add_argument('--prompt', required=True)\n"
        "parser.add_argument('--output_dir', required=True)\n"
        "parser.add_argument('--timestep', required=True)\n"
        "parser.add_argument('--height', required=True)\n"
        "parser.add_argument('--width', required=True)\n"
        "parser.add_argument('--model_path')\n"
        "parser.add_argument('--model_name')\n"
        "parser.add_argument('--ref_image')\n"
        "args = parser.parse_args()\n"
        "output = Path(args.output_dir) / Path(args.input_image).name\n"
        "output.parent.mkdir(parents=True, exist_ok=True)\n"
        "shutil.copyfile(args.input_image, output)\n",
        encoding="ascii",
    )

    input_image = tmp_path / "input.png"
    output_image = tmp_path / "nested" / "output.png"
    input_image.write_bytes(b"rendered-frame")

    subprocess.run(
        [
            sys.executable,
            str(adapter),
            "--repo",
            str(fake_repo),
            "--model-path",
            str(fake_model),
            "--input",
            str(input_image),
            "--output",
            str(output_image),
        ],
        check=True,
    )

    assert output_image.read_bytes() == b"rendered-frame"
