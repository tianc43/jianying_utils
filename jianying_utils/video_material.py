"""Compatibility helpers for pyJianYingDraft video/photo materials."""

from __future__ import annotations

import os
from typing import Optional

from pyJianYingDraft import CropSettings, VideoMaterial


def create_video_material(
    path: str,
    material_name: Optional[str] = None,
    crop_settings: CropSettings = CropSettings(),
) -> VideoMaterial:
    """Create a VideoMaterial, converting WebP photos when MediaInfo omits size.

    pyJianYingDraft can classify WebP files as photos but MediaInfo may leave
    width/height empty. The exported draft then fails because JianYing requires
    non-empty image dimensions. Converting the WebP to a PNG sidecar keeps the
    API contract unchanged while giving pyJianYingDraft a format it parses
    reliably.
    """
    material = VideoMaterial(path, material_name=material_name, crop_settings=crop_settings)
    if _has_dimensions(material):
        return material

    converted_path = _convert_webp_to_png_if_needed(path)
    if converted_path == path:
        return material
    return VideoMaterial(converted_path, material_name=material_name, crop_settings=crop_settings)


def _has_dimensions(material: VideoMaterial) -> bool:
    return material.width is not None and material.height is not None


def _convert_webp_to_png_if_needed(path: str) -> str:
    if os.path.splitext(path)[1].lower() != ".webp":
        return path

    png_path = f"{path}.png"
    if _is_cache_current(path, png_path):
        return png_path

    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("WebP 图片需要 Pillow 才能转换为 PNG: pip install Pillow") from exc

    with Image.open(path) as image:
        image.save(png_path, "PNG")
    return png_path


def _is_cache_current(source_path: str, cache_path: str) -> bool:
    return os.path.isfile(cache_path) and os.path.getmtime(cache_path) >= os.path.getmtime(source_path)
