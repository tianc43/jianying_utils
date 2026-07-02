"""视频片段工具 — 添加视频/图片片段、批量添加、片段级效果

支持本地文件路径和远程 URL（自动下载到本地缓存）。
适用于 Dify 工作流的代码节点。
"""

import os
from typing import Optional, Dict, Any, List, Union
from uuid import uuid4

from pyJianYingDraft import (
    VideoSegment, Timerange, ClipSettings,
    FilterType, MaskType, TransitionType,
    VideoSceneEffectType, VideoCharacterEffectType
)
from pyJianYingDraft.metadata.mix_mode_meta import MixModeType

from . import _context
from .material_path import resolve_material_path
from .time_tool import TimeTool
from .video_material import create_video_material

_CLIP_SETTING_KEYS = {
    "alpha",
    "flip_horizontal",
    "flip_vertical",
    "rotation",
    "scale_x",
    "scale_y",
    "transform_x",
    "transform_y",
}
_ROUND_CORNER_KEYS = ("round_corner", "corner_radius", "border_radius", "radius")
_GLOW_OUTLINE_KEYS = ("glow_outline", "video_stroke", "stroke", "outline")
_JY_GLOW_STROKE_RESOURCE_ID = "7564725435079167268"
_JY_GLOW_STROKE_RESOURCE_NAME = "发光描边"
_JY_GLOW_STROKE_CACHE_KEY = "8e72ed2f2ebf94c811d01f3dc2ac948f"
_JY_ROUND_RADIUS_RESOURCE_ID = "7566153810800954665"
_JY_ROUND_RADIUS_RESOURCE_NAME = "圆角"
_JY_ROUND_RADIUS_CACHE_KEY = "25a4a6b0928108da1a32a3742adcd5f9"


def _resolve_media_path(media_path: str) -> str:
    return resolve_material_path(media_path, ".jpg", "image/*,video/*;q=0.9,*/*;q=0.8")


class VideoTool:
    """视频/图片片段工具类"""

    @staticmethod
    @_context.catch_errors("添加视频")
    def add_video(folder_path: str, draft_name: str,
                  video_path: str, start: Union[str, int],
                  duration: Optional[Union[str, int]] = None,
                  speed: float = 1.0, volume: float = 1.0,
                  change_pitch: bool = False,
                  clip_settings: Optional[Dict[str, Any]] = None,
                  effects: Optional[List[Dict[str, Any]]] = None,
                  filters: Optional[List[Dict[str, Any]]] = None,
                  mask: Optional[Dict[str, Any]] = None,
                  background_filling: Optional[Dict[str, Any]] = None,
                  mix_mode: Optional[str] = None,
                  track_name: Optional[str] = None,
                  source_timerange_start: Optional[Union[str, int]] = None,
                  source_timerange_duration: Optional[Union[str, int]] = None,
                  round_corner: Optional[float] = None,
                  glow_outline: Optional[Union[Dict[str, Any], bool]] = None) -> Dict[str, Any]:
        """添加单个视频/图片片段到轨道

        Args:
            folder_path: 草稿根文件夹路径
            draft_name: 草稿名称
            video_path: 视频/图片文件路径
            start: 片段在轨道上的起始时间（微秒或时间字符串如 "5s"）
            duration: 片段持续时间（微秒或时间字符串），不指定则自动根据素材计算
            speed: 播放速度，默认1.0
            volume: 音量，默认1.0
            change_pitch: 是否跟随变速改变音调，默认False
            clip_settings: 图像调节设置字典，可选键: alpha, flip_horizontal, flip_vertical,
                           rotation, scale_x, scale_y, transform_x, transform_y
            effects: 片段级视频特效列表，每项: {"effect_name": str, "type": "scene|character", "params": list}
            filters: 片段级滤镜列表，每项: {"filter_name": str, "intensity": float}
            mask: 蒙版设置字典
            background_filling: 背景填充设置字典
            mix_mode: 混合模式名称
            track_name: 目标轨道名称，当只有一条视频轨道时可省略
            source_timerange_start: 素材截取起始时间
            source_timerange_duration: 素材截取持续时间
            round_corner: 剪映圆角，取值范围 0~100，8 会写入 0.08
            glow_outline: 发光描边设置，如 {"color": "#000000", "size": 10}

        Returns:
            dict: {"success": bool, "segment_id": str}
        """
        script = _context.load_script(folder_path, draft_name)

        # 解析时间
        start_us = _context_parse_time(start)
        duration_us = _context_parse_time(duration) if duration is not None else None

        # 创建素材（支持 URL 自动下载）
        video_path = _resolve_media_path(video_path)
        material = create_video_material(video_path)

        # 计算目标时间范围
        if duration_us is None:
            if speed != 1.0:
                duration_us = round(material.duration / speed)
            else:
                duration_us = material.duration
        else:
            max_dur = round(material.duration / speed) if speed != 1.0 else material.duration
            if duration_us > max_dur:
                duration_us = max_dur
        target_tr = Timerange(start_us, duration_us)

        # 素材截取范围
        source_tr = None
        if source_timerange_start is not None or source_timerange_duration is not None:
            src_start = _context_parse_time(source_timerange_start) if source_timerange_start else 0
            src_dur = _context_parse_time(source_timerange_duration) if source_timerange_duration else material.duration
            source_tr = Timerange(src_start, src_dur)

        # 图像调节
        cs_dict = _extract_clip_settings({"clip_settings": clip_settings or {}})
        cs = ClipSettings(**cs_dict) if cs_dict else None

        # 创建片段
        segment = VideoSegment(
            material, target_tr,
            source_timerange=source_tr,
            speed=speed if source_tr is None else None,
            volume=volume,
            change_pitch=change_pitch,
            clip_settings=cs
        )
        resolved_round_corner = _extract_round_corner(
            {"round_corner": round_corner, "clip_settings": clip_settings}
        )
        resolved_glow_outline = _extract_glow_outline(
            {"glow_outline": glow_outline, "clip_settings": clip_settings}
        )
        if resolved_glow_outline:
            _attach_glow_outline(script, segment, resolved_glow_outline)
        if resolved_round_corner and not mask:
            _attach_round_radius(script, segment, resolved_round_corner)
        _apply_segment_enhancements(
            segment,
            effects=effects,
            filters=filters,
            mask=mask,
            background_filling=background_filling,
            mix_mode=mix_mode,
        )

        script.add_segment(segment, track_name)
        _context.save_script(script)

        return _context.make_result(
            True,
            f"视频片段已添加: {material.material_name}",
            segment_id=segment.segment_id,
            material_name=material.material_name,
            duration=segment.target_timerange.duration
        )

    @staticmethod
    @_context.catch_errors("批量添加视频")
    def add_videos_batch(folder_path: str, draft_name: str,
                         video_infos: List[Dict[str, Any]],
                         track_name: Optional[str] = None) -> Dict[str, Any]:
        """批量添加视频/图片片段

        Args:
            folder_path: 草稿根文件夹路径
            draft_name: 草稿名称
            video_infos: 视频信息列表，每项包含:
                - video_path (str): 视频文件路径（必须）
                - start (int): 起始时间微秒（必须）
                - end (int): 结束时间微秒（必须）
                - speed (float): 播放速度，默认1.0
                - volume (float): 音量，默认1.0
                - alpha (float): 透明度 0~1，默认1.0
                - transform_x (float): X位移
                - transform_y (float): Y位移
                - scale_x (float): X缩放
                - scale_y (float): Y缩放
                - effects (list[dict]): 片段级视频特效
                - filters (list[dict]): 片段级滤镜
                - mask (dict): 蒙版设置
                - background_filling (dict): 背景填充设置
                - mix_mode (str): 混合模式
                - round_corner (float): 剪映圆角，8 会写入 0.08
                - glow_outline (dict|bool): 发光描边，如 {"color": "#000000", "size": 10}
            track_name: 目标轨道名称

        Returns:
            dict: {"success": bool, "segment_ids": list[str], "count": int}
        """
        script = _context.load_script(folder_path, draft_name)
        segment_ids = []

        for info in video_infos:
            video_path = _resolve_media_path(info["video_path"])
            start = info["start"]
            end = info["end"]
            duration = end - start

            speed = info.get("speed", 1.0)
            volume = info.get("volume", 1.0)

            cs_dict = _extract_clip_settings(info)

            cs = ClipSettings(**cs_dict) if cs_dict else None

            material = create_video_material(video_path)
            target_tr = Timerange(start, duration)
            segment = VideoSegment(material, target_tr, speed=speed, volume=volume, clip_settings=cs)
            glow_outline = _extract_glow_outline(info)
            if glow_outline:
                _attach_glow_outline(script, segment, glow_outline)
            round_corner = _extract_round_corner(info)
            if round_corner and not info.get("mask"):
                _attach_round_radius(script, segment, round_corner)
            _apply_segment_enhancements(
                segment,
                effects=info.get("effects"),
                filters=info.get("filters"),
                mask=info.get("mask"),
                background_filling=info.get("background_filling"),
                mix_mode=info.get("mix_mode"),
            )
            script.add_segment(segment, track_name)
            segment_ids.append(segment.segment_id)

        _context.save_script(script)

        return _context.make_result(
            True,
            f"批量添加了 {len(segment_ids)} 个视频片段",
            segment_ids=segment_ids,
            count=len(segment_ids)
        )


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

def _context_parse_time(value):
    """解析时间值"""
    if value is None:
        return None
    from .time_tool import parse_time_value
    return parse_time_value(value)


def _extract_clip_settings(info: Dict[str, Any]) -> Dict[str, Any]:
    """提取 ClipSettings 支持的字段，兼容顶层字段和嵌套 clip_settings。"""
    clip_settings = info.get("clip_settings")
    cs_dict = {}
    if isinstance(clip_settings, dict):
        cs_dict.update({k: v for k, v in clip_settings.items() if k in _CLIP_SETTING_KEYS})
    cs_dict.update({k: info[k] for k in _CLIP_SETTING_KEYS if k in info})
    return cs_dict


def _extract_round_corner(info: Dict[str, Any]) -> Optional[float]:
    """提取剪映圆角，支持 round_corner 及常见 radius 别名。"""
    clip_settings = info.get("clip_settings")
    sources = [info]
    if isinstance(clip_settings, dict):
        sources.append(clip_settings)

    for source in sources:
        for key in _ROUND_CORNER_KEYS:
            value = source.get(key)
            if value is None:
                continue
            try:
                return max(0.0, min(100.0, float(value)))
            except (TypeError, ValueError):
                return None
    return None


def _extract_glow_outline(info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """提取发光描边设置，支持 glow_outline/video_stroke/stroke/outline。"""
    clip_settings = info.get("clip_settings")
    sources = [info]
    if isinstance(clip_settings, dict):
        sources.append(clip_settings)

    raw = None
    for source in sources:
        for key in _GLOW_OUTLINE_KEYS:
            if source.get(key) is not None:
                raw = source.get(key)
                break
        if raw is not None:
            break

    if raw is None or raw is False:
        return None
    if raw is True:
        raw = {}
    if isinstance(raw, str):
        raw = {"color": raw}
    if not isinstance(raw, dict):
        raise ValueError("glow_outline/video_stroke/stroke/outline 必须是对象、颜色字符串或 true")

    enabled = raw.get("enabled", raw.get("enable", True))
    if enabled is False:
        return None
    return {
        "color": raw.get("color", "#000000"),
        "size": _safe_float(raw.get("size", raw.get("value", 10.0)), 10.0),
        "alpha": _safe_float(raw.get("alpha", 1.0), 1.0),
        "path": raw.get("path"),
    }


def _attach_round_radius(script, segment: VideoSegment, radius: float) -> None:
    """按剪映 UI 圆角素材格式挂载 round_radius。"""
    normalized = max(0.0, min(100.0, float(radius))) / 100.0
    mat_id = _new_jy_id()
    _append_imported_material(script, "video_radius", {
        "id": mat_id,
        "type": "round_radius",
        "resource_id": _JY_ROUND_RADIUS_RESOURCE_ID,
        "source_platform": 1,
        "resource_name": _JY_ROUND_RADIUS_RESOURCE_NAME,
        "path": _resolve_effect_cache_path(
            "JIANYING_ROUND_RADIUS_PATH",
            _JY_ROUND_RADIUS_RESOURCE_ID,
            _JY_ROUND_RADIUS_CACHE_KEY,
        ),
        "radius": {
            "top_left": normalized,
            "top_right": normalized,
            "bottom_left": normalized,
            "bottom_right": normalized,
        },
    })
    segment.extra_material_refs.append(mat_id)


def _attach_glow_outline(script, segment: VideoSegment, outline: Dict[str, Any]) -> None:
    """按剪映 UI 发光描边素材格式挂载 video_stroke。"""
    mat_id = _new_jy_id()
    _append_imported_material(script, "video_strokes", {
        "id": mat_id,
        "type": "video_stroke",
        "enable_video_stroke": True,
        "resource_id": _JY_GLOW_STROKE_RESOURCE_ID,
        "source_platform": 1,
        "resource_name": _JY_GLOW_STROKE_RESOURCE_NAME,
        "path": outline.get("path") or _resolve_effect_cache_path(
            "JIANYING_GLOW_STROKE_PATH",
            _JY_GLOW_STROKE_RESOURCE_ID,
            _JY_GLOW_STROKE_CACHE_KEY,
        ),
        "color": _color_to_jy_argb(outline.get("color", "#000000"), outline.get("alpha", 1.0)),
        "adjust_params": [
            {
                "name": "effects_adjust_size",
                "value": max(0.0, min(100.0, float(outline.get("size", 10.0)))) / 100.0,
                "default_value": 0.3,
            },
            {
                "name": "effects_adjust_alpha",
                "default_value": 1.0,
            },
        ],
    })
    segment.extra_material_refs.append(mat_id)


def _append_imported_material(script, material_type: str, material: Dict[str, Any]) -> None:
    script.imported_materials.setdefault(material_type, []).append(material)


def _new_jy_id() -> str:
    return str(uuid4()).upper()


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _resolve_effect_cache_path(env_name: str, resource_id: str, cache_key: str) -> str:
    """Resolve Jianying effect cache path only from deployment configuration."""
    explicit = os.environ.get(env_name)
    if explicit:
        return _normalize_jy_path(explicit)

    effect_root = os.environ.get("JIANYING_EFFECT_CACHE_DIR") or os.environ.get("JY_EFFECT_CACHE_DIR")
    if effect_root:
        return _normalize_jy_path(os.path.join(effect_root, resource_id, cache_key))

    return ""


def _normalize_jy_path(path: str) -> str:
    return str(path).replace("\\", "/")


def _color_to_jy_argb(color: Any, alpha: float = 1.0) -> List[float]:
    """剪映该字段为 [alpha, red, green, blue]，黑色为 [1,0,0,0]。"""
    if isinstance(color, (list, tuple)):
        values = [float(v) for v in color]
        if len(values) == 4:
            return [_normalize_color(v) for v in values]
        if len(values) == 3:
            return [max(0.0, min(1.0, float(alpha)))] + [_normalize_color(v) for v in values]

    text = str(color or "#000000").strip()
    named = {"black": "#000000", "white": "#FFFFFF", "red": "#FF0000"}
    text = named.get(text.lower(), text)
    if text.startswith("#"):
        text = text[1:]
    if len(text) not in (6, 8):
        text = "000000"

    r = int(text[0:2], 16) / 255.0
    g = int(text[2:4], 16) / 255.0
    b = int(text[4:6], 16) / 255.0
    a = int(text[6:8], 16) / 255.0 if len(text) == 8 else max(0.0, min(1.0, float(alpha)))
    return [a, r, g, b]


def _normalize_color(value: float) -> float:
    if value > 1.0:
        return max(0.0, min(255.0, value)) / 255.0
    return max(0.0, min(1.0, value))


def _apply_segment_enhancements(segment: VideoSegment, *,
                                effects: Optional[List[Dict[str, Any]]] = None,
                                filters: Optional[List[Dict[str, Any]]] = None,
                                mask: Optional[Dict[str, Any]] = None,
                                background_filling: Optional[Dict[str, Any]] = None,
                                mix_mode: Optional[str] = None) -> None:
    """给视频片段挂载剪映支持的片段级附加素材。"""
    for item in effects or []:
        effect_name = item.get("effect_name") or item.get("effect_title") or item.get("name")
        if not effect_name:
            raise ValueError("effects item 缺少 effect_name/effect_title/name")
        params = item.get("params")
        effect_type = str(item.get("type", "scene")).lower()
        if effect_type == "character":
            segment.add_effect(VideoCharacterEffectType.from_name(effect_name), params=params)
        else:
            segment.add_effect(VideoSceneEffectType.from_name(effect_name), params=params)

    for item in filters or []:
        if isinstance(item, str):
            filter_name, intensity = item, 100.0
        else:
            filter_name = item.get("filter_name") or item.get("name")
            intensity = item.get("intensity", 100.0)
        if not filter_name:
            raise ValueError("filters item 缺少 filter_name/name")
        segment.add_filter(FilterType.from_name(filter_name), intensity=float(intensity))

    if mask:
        mask_name = mask.get("type") or mask.get("mask_type") or mask.get("name")
        if not mask_name:
            raise ValueError("mask 缺少 type/mask_type/name")
        kwargs = {
            "center_x": mask.get("center_x", 0.0),
            "center_y": mask.get("center_y", 0.0),
            "size": mask.get("size", 0.5),
            "rotation": mask.get("rotation", 0.0),
            "feather": mask.get("feather", 0.0),
            "invert": mask.get("invert", False),
        }
        if mask.get("rect_width") is not None:
            kwargs["rect_width"] = mask["rect_width"]
        if mask.get("round_corner") is not None:
            kwargs["round_corner"] = mask["round_corner"]
        segment.add_mask(MaskType.from_name(mask_name), **kwargs)

    if background_filling:
        fill_type = background_filling.get("type") or background_filling.get("fill_type")
        if not fill_type:
            raise ValueError("background_filling 缺少 type/fill_type")
        segment.add_background_filling(
            fill_type,
            blur=background_filling.get("blur", 0.0625),
            color=background_filling.get("color", "#00000000"),
        )

    if mix_mode:
        segment.set_mix_mode(MixModeType.from_name(mix_mode))
