import importlib.util
from pathlib import Path


def load_adapter_module():
    project_root = Path(__file__).resolve().parents[2]
    adapter_path = project_root / "scripts" / "difix3d_hf_adapter.py"
    spec = importlib.util.spec_from_file_location("difix3d_hf_adapter", adapter_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hf_adapter_selects_default_model_names() -> None:
    adapter = load_adapter_module()

    assert adapter.select_model_name(None, None) == "nvidia/difix"
    assert adapter.select_model_name(None, "/tmp/ref.png") == "nvidia/difix_ref"
    assert adapter.select_model_name("custom/model", None) == "custom/model"


def test_hf_adapter_rounds_dimensions_to_nearest_multiple_of_8() -> None:
    adapter = load_adapter_module()

    assert adapter.select_dimensions(
        requested_width=0,
        requested_height=0,
        max_side=0,
        image_width=961,
        image_height=541,
    ) == (960, 544)
    assert adapter.select_dimensions(
        requested_width=1024,
        requested_height=576,
        max_side=512,
        image_width=961,
        image_height=541,
    ) == (1024, 576)


def test_hf_adapter_caps_dimensions_by_default_max_side() -> None:
    adapter = load_adapter_module()

    assert adapter.select_dimensions(
        requested_width=0,
        requested_height=0,
        max_side=512,
        image_width=1280,
        image_height=720,
    ) == (512, 288)
    assert adapter.select_dimensions(
        requested_width=0,
        requested_height=256,
        max_side=512,
        image_width=1280,
        image_height=720,
    ) == (456, 256)


def test_hf_adapter_builds_worker_command() -> None:
    adapter = load_adapter_module()

    command = adapter.build_worker_command(
        "/opt/conda/envs/difix/bin/python",
        [
            "scripts/difix3d_hf_adapter.py",
            "--input",
            "in.png",
            "--output",
            "out.png",
        ],
    )

    assert command[0] == "/opt/conda/envs/difix/bin/python"
    assert command[2] == "--worker"
    assert command[-4:] == ["--input", "in.png", "--output", "out.png"]
