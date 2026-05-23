"""Server-safe mock renderer used until a real 3DGS backend is wired in."""

from __future__ import annotations

import base64
import html
import math
import time

from backend.app.rendering.camera import CameraState
from backend.app.rendering.renderer import RenderQuality, RenderResult


class MockRenderer:
    name = "mock-svg-renderer"

    def __init__(self, scene_ply_path: str = "") -> None:
        self.scene_ply_path = scene_ply_path

    def set_scene_ply_path(self, scene_ply_path: str) -> None:
        self.scene_ply_path = scene_ply_path

    def render(
        self,
        camera: CameraState,
        width: int,
        height: int,
        quality: RenderQuality,
    ) -> RenderResult:
        start = time.perf_counter()
        svg = self._build_svg(camera=camera, width=width, height=height, quality=quality)
        encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
        elapsed_ms = (time.perf_counter() - start) * 1000
        return RenderResult(
            image_data_url=f"data:image/svg+xml;base64,{encoded}",
            width=width,
            height=height,
            render_ms=elapsed_ms,
            renderer=self.name,
            quality=quality,
        )

    def _build_svg(
        self,
        camera: CameraState,
        width: int,
        height: int,
        quality: RenderQuality,
    ) -> str:
        scene_label = self.scene_ply_path or "No PLY configured"
        target = ", ".join(f"{value:.2f}" for value in camera.target[:3])
        bg = "#121820" if quality == "interactive" else "#172013"
        accent = "#49b6ff" if quality == "interactive" else "#85d66d"
        secondary = "#f2bf5e" if quality == "interactive" else "#49b6ff"
        safe_scene_label = html.escape(scene_label)
        safe_quality = html.escape(quality)
        min_dim = min(width, height)
        camera_scale = max(0.35, min(2.4, 3.0 / max(camera.distance, 0.1)))
        target_x = camera.target[0] if len(camera.target) > 0 else 0.0
        target_y = camera.target[1] if len(camera.target) > 1 else 0.0
        target_z = camera.target[2] if len(camera.target) > 2 else 0.0
        center_x = width * 0.5 - target_x * min_dim * 0.08
        center_y = height * 0.52 + camera.pitch * height * 0.10 + target_y * min_dim * 0.08
        horizon_y = height * (0.52 + camera.pitch * 0.18)
        point_markup = self._mock_point_cloud(
            center_x=center_x,
            center_y=center_y,
            camera=camera,
            min_dim=min_dim,
            scale=camera_scale,
            accent=accent,
            secondary=secondary,
        )
        grid_markup = self._mock_grid(
            width=width,
            height=height,
            horizon_y=horizon_y,
            yaw=camera.yaw,
            scale=camera_scale,
        )

        return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="{bg}"/>
  {grid_markup}
  <circle cx="{center_x:.1f}" cy="{center_y:.1f}" r="{min_dim * 0.20 * camera_scale:.1f}" fill="{accent}" opacity="0.12"/>
  <circle cx="{center_x:.1f}" cy="{center_y:.1f}" r="{min_dim * 0.055 * camera_scale:.1f}" fill="{secondary}" opacity="0.42"/>
  {point_markup}
  <g fill="#f5f7fb" font-family="Inter, Arial, sans-serif">
    <text x="28" y="44" font-size="20" font-weight="700">Raw 3DGS Render Placeholder</text>
    <text x="28" y="76" font-size="14" fill="#aeb8c6">Renderer: {self.name} | Quality: {safe_quality}</text>
    <text x="28" y="{height - 92}" font-size="14">Yaw {camera.yaw:.2f} | Pitch {camera.pitch:.2f} | Distance {camera.distance:.2f}</text>
    <text x="28" y="{height - 64}" font-size="14">Target [{target}] | FOV {camera.fov:.1f} | Mock view x/z {target_x:.2f}/{target_z:.2f}</text>
    <text x="28" y="{height - 36}" font-size="14" fill="#aeb8c6">Scene: {safe_scene_label}</text>
  </g>
</svg>"""

    def _mock_grid(
        self,
        width: int,
        height: int,
        horizon_y: float,
        yaw: float,
        scale: float,
    ) -> str:
        lines: list[str] = [
            f'<line x1="0" y1="{horizon_y:.1f}" x2="{width}" y2="{horizon_y:.1f}" stroke="#ffffff" stroke-opacity="0.16"/>'
        ]
        vanishing_x = width * (0.5 + math.sin(yaw) * 0.22)
        for index in range(-5, 6):
            floor_x = width * (0.5 + index * 0.13 + math.cos(yaw) * 0.02)
            lines.append(
                f'<line x1="{vanishing_x:.1f}" y1="{horizon_y:.1f}" x2="{floor_x:.1f}" y2="{height}" '
                'stroke="#ffffff" stroke-opacity="0.12"/>'
            )
        for index in range(1, 8):
            depth = index / 8
            y = horizon_y + (height - horizon_y) * (depth**1.65)
            opacity = 0.06 + depth * 0.10
            lines.append(
                f'<path d="M0 {y:.1f} C {width * 0.32:.1f} {y - scale * 10:.1f}, '
                f'{width * 0.68:.1f} {y + scale * 10:.1f}, {width} {y:.1f}" '
                f'stroke="#ffffff" stroke-opacity="{opacity:.2f}" fill="none"/>'
            )
        line_markup = "".join(lines)
        return f'<g fill="none" stroke-width="1">{line_markup}</g>'

    def _mock_point_cloud(
        self,
        center_x: float,
        center_y: float,
        camera: CameraState,
        min_dim: int,
        scale: float,
        accent: str,
        secondary: str,
    ) -> str:
        points: list[str] = []
        for index in range(54):
            layer = (index % 9) / 8
            angle = index * 2.399963 + camera.yaw
            radius = (0.12 + layer * 0.36) * min_dim * scale
            wobble = math.sin(index * 1.7 + camera.pitch * 3.0) * min_dim * 0.012 * scale
            x = center_x + math.cos(angle) * radius + wobble
            y = center_y + math.sin(angle) * radius * (0.46 + math.cos(camera.pitch) * 0.12)
            y -= math.sin(camera.pitch) * min_dim * 0.10
            dot_radius = max(2.4, min_dim * (0.005 + (1 - layer) * 0.004) * scale)
            color = accent if index % 3 else secondary
            opacity = 0.38 + (1 - layer) * 0.38
            points.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{dot_radius:.1f}" '
                f'fill="{color}" opacity="{opacity:.2f}"/>'
            )
        point_markup = "".join(points)
        return f"<g>{point_markup}</g>"
