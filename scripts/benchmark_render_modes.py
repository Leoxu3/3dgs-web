#!/usr/bin/env python3
"""Collect render and refine timing samples from a running 3DGS Web server."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


MODES = ("moving", "idle", "refine-view")
CSV_COLUMNS = [
    "timestamp_utc",
    "mode",
    "endpoint",
    "quality",
    "sample",
    "discarded",
    "width",
    "height",
    "yaw_rad",
    "pitch_rad",
    "distance",
    "target_x",
    "target_y",
    "target_z",
    "fov",
    "up_axis",
    "client_wall_ms",
    "client_wall_s",
    "backend_render_ms",
    "backend_render_s",
    "render_wall_ms",
    "render_wall_s",
    "refine_wall_ms",
    "refine_wall_s",
    "total_wall_ms",
    "total_wall_s",
    "refined_latency_ms",
    "refined_latency_s",
    "renderer",
    "refiner",
    "status",
    "fallback_mode",
    "message",
]


@dataclass(frozen=True)
class Size:
    width: int
    height: int


def main() -> int:
    args = parse_args()
    try:
        modes = parse_modes(args.modes)
    except argparse.ArgumentTypeError as exc:
        raise SystemExit(f"error: {exc}") from exc
    interactive_size = args.same_size or args.interactive_size
    idle_size = args.same_size or args.idle_size

    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    if args.scene:
        post_json(args.base_url, "/api/scene", {"path": args.scene}, args.timeout)

    health = get_json(args.base_url, "/api/health", args.timeout)
    print(
        "Server:",
        f"renderer={health.get('renderer', 'unknown')}",
        f"refiner={health.get('refiner', 'unknown')}",
        f"fallback={health.get('fallback_mode', 'unknown')}",
    )

    if args.refiner_warmup and "refine-view" in modes:
        warmup = post_json(
            args.base_url,
            "/api/refiner/warmup",
            {"width": idle_size.width, "height": idle_size.height},
            args.timeout,
        )
        print(
            "Refiner warmup:",
            f"status={warmup.get('status', 'unknown')}",
            f"latency_ms={warmup.get('latency_ms', 'unknown')}",
        )

    rows: list[dict[str, Any]] = []
    total_samples = args.samples + args.discard

    with output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS)
        writer.writeheader()

        for mode in modes:
            for sample in range(total_samples):
                size = interactive_size if mode == "moving" else idle_size
                quality = "interactive" if mode == "moving" else "idle"
                camera = camera_for_sample(sample, total_samples, args)
                row = collect_sample(
                    base_url=args.base_url,
                    mode=mode,
                    quality=quality,
                    size=size,
                    camera=camera,
                    sample=sample,
                    discarded=sample < args.discard,
                    timeout=args.timeout,
                )
                writer.writerow(row)
                file.flush()
                rows.append(row)

                print_progress(row)
                if args.sleep > 0:
                    time.sleep(args.sleep)

    print(f"\nWrote {len(rows)} samples to {output}")
    print_summary(rows)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark moving raw renders, idle raw renders, and idle render+refine "
            "requests through the running 3DGS Web HTTP API."
        )
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Base URL of the running Web server.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmark_render_modes.csv"),
        help="CSV file to write.",
    )
    parser.add_argument(
        "--modes",
        default="moving,idle,refine-view",
        help=(
            "Comma-separated modes: moving, idle, refine-view. "
            "Aliases: interactive=moving, refine=refine-view."
        ),
    )
    parser.add_argument(
        "--samples",
        type=positive_int,
        default=60,
        help="Kept samples per mode after discarded warmup samples.",
    )
    parser.add_argument(
        "--discard",
        type=nonnegative_int,
        default=5,
        help="Initial samples per mode to mark as discarded in the CSV summary.",
    )
    parser.add_argument(
        "--interactive-size",
        type=parse_size,
        default=Size(520, 320),
        metavar="WIDTHxHEIGHT",
        help="Request size for moving/interactive raw renders.",
    )
    parser.add_argument(
        "--idle-size",
        type=parse_size,
        default=Size(960, 540),
        metavar="WIDTHxHEIGHT",
        help="Request size for idle raw renders and refine-view requests.",
    )
    parser.add_argument(
        "--same-size",
        type=parse_size,
        default=None,
        metavar="WIDTHxHEIGHT",
        help="Use one fixed request size for every mode for a fair renderer-cost run.",
    )
    parser.add_argument(
        "--scene",
        default="",
        help="Optional PLY path to set through POST /api/scene before benchmarking.",
    )
    parser.add_argument(
        "--no-refiner-warmup",
        dest="refiner_warmup",
        action="store_false",
        help="Skip POST /api/refiner/warmup before refine-view samples.",
    )
    parser.add_argument(
        "--timeout",
        type=positive_float,
        default=300.0,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--sleep",
        type=nonnegative_float,
        default=0.0,
        help="Sleep between samples in seconds.",
    )
    parser.add_argument(
        "--yaw-start-deg",
        type=float,
        default=0.0,
        help="Start yaw for the generated orbit camera path.",
    )
    parser.add_argument(
        "--yaw-end-deg",
        type=float,
        default=360.0,
        help="End yaw for the generated orbit camera path.",
    )
    parser.add_argument(
        "--pitch-deg",
        type=float,
        default=0.0,
        help="Fixed pitch for the generated camera path.",
    )
    parser.add_argument(
        "--distance",
        type=positive_float,
        default=3.0,
        help="Camera distance.",
    )
    parser.add_argument(
        "--target",
        type=parse_target,
        default=(0.0, 0.0, 0.0),
        metavar="X,Y,Z",
        help="Camera target.",
    )
    parser.add_argument(
        "--fov",
        type=positive_float,
        default=45.0,
        help="Camera field of view in degrees.",
    )
    parser.add_argument(
        "--up-axis",
        choices=("x", "y", "z"),
        default="z",
        help="Camera up axis.",
    )
    parser.set_defaults(refiner_warmup=True)
    return parser.parse_args()


def parse_modes(value: str) -> list[str]:
    aliases = {
        "interactive": "moving",
        "move": "moving",
        "moving": "moving",
        "idle": "idle",
        "refine": "refine-view",
        "refined": "refine-view",
        "refine-view": "refine-view",
    }
    modes: list[str] = []
    for raw_mode in value.split(","):
        key = raw_mode.strip().lower()
        if not key:
            continue
        try:
            mode = aliases[key]
        except KeyError as exc:
            raise argparse.ArgumentTypeError(f"unknown mode: {raw_mode}") from exc
        if mode not in modes:
            modes.append(mode)

    if not modes:
        raise argparse.ArgumentTypeError("at least one mode is required")
    return modes


def parse_size(value: str) -> Size:
    parts = value.lower().replace("*", "x").split("x")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("size must look like WIDTHxHEIGHT")
    try:
        width = int(parts[0])
        height = int(parts[1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("size dimensions must be integers") from exc

    if width < 64 or height < 64 or width > 4096 or height > 4096:
        raise argparse.ArgumentTypeError("size dimensions must be between 64 and 4096")
    return Size(width=width, height=height)


def parse_target(value: str) -> tuple[float, float, float]:
    parts = value.split(",")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("target must look like X,Y,Z")
    try:
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("target coordinates must be numbers") from exc


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return number


def nonnegative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return number


def positive_float(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return number


def nonnegative_float(value: str) -> float:
    number = float(value)
    if number < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return number


def camera_for_sample(
    sample: int,
    total_samples: int,
    args: argparse.Namespace,
) -> dict[str, Any]:
    fraction = sample / max(total_samples, 1)
    yaw_degrees = args.yaw_start_deg + (args.yaw_end_deg - args.yaw_start_deg) * fraction
    return {
        "yaw": math.radians(yaw_degrees),
        "pitch": math.radians(args.pitch_deg),
        "distance": args.distance,
        "target": list(args.target),
        "fov": args.fov,
        "up_axis": args.up_axis,
    }


def collect_sample(
    *,
    base_url: str,
    mode: str,
    quality: str,
    size: Size,
    camera: dict[str, Any],
    sample: int,
    discarded: bool,
    timeout: float,
) -> dict[str, Any]:
    endpoint = "/api/refine-view" if mode == "refine-view" else "/api/render"
    payload = {
        "camera": camera,
        "width": size.width,
        "height": size.height,
        "quality": quality,
    }

    client_start = time.perf_counter()
    response = post_json(base_url, endpoint, payload, timeout)
    client_wall_ms = elapsed_ms(client_start)

    if mode == "refine-view":
        raw = response.get("raw") or {}
        refined = response.get("refined") or {}
        timings = response.get("timings_ms") or {}
    else:
        raw = response
        refined = {}
        timings = {}

    render_ms = raw.get("render_ms")
    render_wall_ms = timings.get("render_wall_ms")
    refine_wall_ms = timings.get("refine_wall_ms")
    total_wall_ms = timings.get("total_wall_ms")
    refined_latency_ms = refined.get("latency_ms")
    status = refined.get("status") or ("ok" if raw else "unknown")

    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "endpoint": endpoint,
        "quality": quality,
        "sample": sample,
        "discarded": int(discarded),
        "width": size.width,
        "height": size.height,
        "yaw_rad": camera["yaw"],
        "pitch_rad": camera["pitch"],
        "distance": camera["distance"],
        "target_x": camera["target"][0],
        "target_y": camera["target"][1],
        "target_z": camera["target"][2],
        "fov": camera["fov"],
        "up_axis": camera["up_axis"],
        "client_wall_ms": round(client_wall_ms, 2),
        "client_wall_s": ms_to_seconds(client_wall_ms),
        "backend_render_ms": render_ms_or_blank(render_ms),
        "backend_render_s": ms_to_seconds_or_blank(render_ms),
        "render_wall_ms": render_ms_or_blank(render_wall_ms),
        "render_wall_s": ms_to_seconds_or_blank(render_wall_ms),
        "refine_wall_ms": render_ms_or_blank(refine_wall_ms),
        "refine_wall_s": ms_to_seconds_or_blank(refine_wall_ms),
        "total_wall_ms": render_ms_or_blank(total_wall_ms),
        "total_wall_s": ms_to_seconds_or_blank(total_wall_ms),
        "refined_latency_ms": render_ms_or_blank(refined_latency_ms),
        "refined_latency_s": ms_to_seconds_or_blank(refined_latency_ms),
        "renderer": raw.get("renderer", ""),
        "refiner": refined.get("refiner", ""),
        "status": status,
        "fallback_mode": refined.get("fallback_mode", ""),
        "message": refined.get("message", ""),
    }


def get_json(base_url: str, path: str, timeout: float) -> dict[str, Any]:
    return request_json(base_url=base_url, path=path, payload=None, timeout=timeout)


def post_json(
    base_url: str,
    path: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    return request_json(base_url=base_url, path=path, payload=payload, timeout=timeout)


def request_json(
    *,
    base_url: str,
    path: str,
    payload: dict[str, Any] | None,
    timeout: float,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        method="GET" if payload is None else "POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{url} failed with HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"{url} failed: {exc.reason}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{url} returned non-JSON response: {body[:200]}") from exc


def elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


def render_ms_or_blank(value: Any) -> str | float:
    if value is None or value == "":
        return ""
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return ""


def ms_to_seconds(value: float) -> float:
    return round(value / 1000.0, 6)


def ms_to_seconds_or_blank(value: Any) -> str | float:
    if value is None or value == "":
        return ""
    try:
        return ms_to_seconds(float(value))
    except (TypeError, ValueError):
        return ""


def print_progress(row: dict[str, Any]) -> None:
    timing = row["backend_render_ms"]
    if row["mode"] == "refine-view":
        timing = row["total_wall_ms"]
    discarded = " discarded" if row["discarded"] else ""
    print(
        f"{row['mode']:11s} sample={row['sample']:04d}{discarded} "
        f"client={row['client_wall_ms']} ms timing={timing} ms "
        f"status={row['status']}"
    )


def print_summary(rows: list[dict[str, Any]]) -> None:
    kept_rows = [row for row in rows if not row["discarded"]]
    if not kept_rows:
        return

    metrics = [
        "client_wall_ms",
        "backend_render_ms",
        "render_wall_ms",
        "refine_wall_ms",
        "total_wall_ms",
        "refined_latency_ms",
    ]
    print("\nSummary, discarded samples excluded:")
    for mode in MODES:
        mode_rows = [row for row in kept_rows if row["mode"] == mode]
        if not mode_rows:
            continue
        print(f"\n{mode}")
        for metric in metrics:
            values = numeric_values(row.get(metric) for row in mode_rows)
            if not values:
                continue
            print(
                f"  {metric:18s}"
                f" n={len(values):3d}"
                f" median={statistics.median(values):8.2f}"
                f" mean={statistics.fmean(values):8.2f}"
                f" p90={percentile(values, 90):8.2f}"
                f" p95={percentile(values, 95):8.2f}"
                f" min={min(values):8.2f}"
                f" max={max(values):8.2f}"
            )


def numeric_values(values: Any) -> list[float]:
    numbers: list[float] = []
    for value in values:
        if value is None or value == "":
            continue
        try:
            numbers.append(float(value))
        except (TypeError, ValueError):
            continue
    return numbers


def percentile(values: list[float], percentile_value: int) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    sorted_values = sorted(values)
    index = math.ceil((percentile_value / 100.0) * len(sorted_values)) - 1
    return sorted_values[max(0, min(index, len(sorted_values) - 1))]


if __name__ == "__main__":
    raise SystemExit(main())
