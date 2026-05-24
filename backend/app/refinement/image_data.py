"""Helpers for passing browser image data URLs to external refiners."""

from __future__ import annotations

import base64
import binascii
from pathlib import Path

from backend.app.refinement.base import RefinerRuntimeError


_EXTENSION_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}

_MIME_BY_EXTENSION = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}


def decode_data_url(image_data_url: str) -> tuple[bytes, str]:
    mime_type = mime_type_from_data_url(image_data_url)
    try:
        header, payload = image_data_url.split(",", 1)
    except ValueError as exc:
        raise RefinerRuntimeError("expected image data URL") from exc

    if not header.startswith("data:"):
        raise RefinerRuntimeError("expected image data URL")

    header_parts = header[5:].split(";")
    if "base64" not in header_parts:
        raise RefinerRuntimeError("only base64 image data URLs are supported")

    try:
        image_bytes = base64.b64decode(payload, validate=True)
    except binascii.Error as exc:
        raise RefinerRuntimeError("invalid base64 image payload") from exc

    return image_bytes, mime_type


def mime_type_from_data_url(image_data_url: str) -> str:
    try:
        header, _payload = image_data_url.split(",", 1)
    except ValueError as exc:
        raise RefinerRuntimeError("expected image data URL") from exc

    if not header.startswith("data:"):
        raise RefinerRuntimeError("expected image data URL")

    header_parts = header[5:].split(";")
    return header_parts[0] or "application/octet-stream"


def encode_data_url(image_bytes: bytes, mime_type: str) -> str:
    payload = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime_type};base64,{payload}"


def extension_for_mime(mime_type: str) -> str:
    return _EXTENSION_BY_MIME.get(mime_type, ".png")


def mime_for_path(path: Path, fallback: str = "image/png") -> str:
    return _MIME_BY_EXTENSION.get(path.suffix.lower(), fallback)
