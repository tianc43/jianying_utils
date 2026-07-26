"""关键帧工具 — 为片段属性添加关键帧动画

适用于 Dify 工作流的代码节点。
"""

from typing import Optional, Dict, Any, List, Union
from uuid import uuid4

from pyJianYingDraft import KeyframeProperty, AudioSegment

from . import _context


# 属性名称到枚举的映射
_PROPERTY_MAP = {
    "position_x": KeyframeProperty.position_x,
    "position_y": KeyframeProperty.position_y,
    "rotation": KeyframeProperty.rotation,
    "scale_x": KeyframeProperty.scale_x,
    "scale_y": KeyframeProperty.scale_y,
    "uniform_scale": KeyframeProperty.uniform_scale,
    "alpha": KeyframeProperty.alpha,
    "saturation": KeyframeProperty.saturation,
    "contrast": KeyframeProperty.contrast,
    "brightness": KeyframeProperty.brightness,
    "volume": KeyframeProperty.volume,
    # 兼容剪映原始命名
    "KFTypePositionX": KeyframeProperty.position_x,
    "KFTypePositionY": KeyframeProperty.position_y,
    "KFTypeRotation": KeyframeProperty.rotation,
    "KFTypeScaleX": KeyframeProperty.scale_x,
    "KFTypeScaleY": KeyframeProperty.scale_y,
    "KFTypeAlpha": KeyframeProperty.alpha,
    "KFTypeSaturation": KeyframeProperty.saturation,
    "KFTypeContrast": KeyframeProperty.contrast,
    "KFTypeBrightness": KeyframeProperty.brightness,
    "KFTypeVolume": KeyframeProperty.volume,
}


class KeyframeTool:
    """关键帧工具类

    支持的属性:
    - position_x: X位移（半画布宽为单位）
    - position_y: Y位移（半画布高为单位）
    - rotation: 顺时针旋转角度
    - scale_x: X轴缩放 (1.0=不缩放)
    - scale_y: Y轴缩放 (1.0=不缩放)
    - uniform_scale: 等比缩放 (与 scale_x/scale_y 互斥)
    - alpha: 不透明度 (1.0=完全不透明)
    - saturation: 饱和度 (0.0=原始, -1.0~1.0)
    - contrast: 对比度 (0.0=原始, -1.0~1.0)
    - brightness: 亮度 (0.0=原始, -1.0~1.0)
    - volume: 音量 (1.0=原始音量)
    """

    @staticmethod
    @_context.catch_errors("添加关键帧")
    def add_keyframe(folder_path: str, draft_name: str,
                     segment_id: str,
                     property_name: str,
                     time_offset: Union[str, int],
                     value: float) -> Dict[str, Any]:
        """为片段属性添加关键帧

        Args:
            folder_path: 草稿根文件夹路径
            draft_name: 草稿名称
            segment_id: 片段ID
            property_name: 属性名称，可选值见上方说明
            time_offset: 关键帧时间偏移量（微秒或时间字符串，相对于片段起始点）
            value: 属性在该时刻的值

        Returns:
            dict: {"success": bool}
        """
        if property_name not in _PROPERTY_MAP:
            return _context.make_result(
                False,
                f"不支持的属性 '{property_name}'，可选: {list(_PROPERTY_MAP.keys())}"
            )

        prop = _PROPERTY_MAP[property_name]
        offset = _parse_time(time_offset)
        script = _context.load_script(folder_path, draft_name)
        segment = _find_segment(script, segment_id)

        if segment is None:
            if not _add_imported_keyframe(
                script, segment_id, prop, offset, value
            ):
                return _context.make_result(False, f"未找到片段 {segment_id}")
        elif prop == KeyframeProperty.volume and isinstance(segment, AudioSegment):
            segment.add_keyframe(offset, value)
        else:
            segment.add_keyframe(prop, offset, value)

        _context.save_script(script)

        return _context.make_result(
            True,
            f"关键帧已添加: {property_name}={value} @ t={time_offset}"
        )

    @staticmethod
    @_context.catch_errors("批量添加关键帧")
    def add_keyframes_batch(folder_path: str, draft_name: str,
                            keyframes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """批量添加关键帧

        Args:
            folder_path: 草稿根文件夹路径
            draft_name: 草稿名称
            keyframes: 关键帧列表，每项:
                - segment_id (str): 片段ID（必须）
                - property (str): 属性名称（必须）
                - offset (int): 时间偏移量微秒（必须）
                - value (float): 属性值（必须）

        Returns:
            dict: {"success": bool, "count": int}
        """
        script = _context.load_script(folder_path, draft_name)
        count = 0

        for kf in keyframes:
            seg_id = kf.get("segment_id")
            prop_name = kf.get("property")
            offset_value = kf.get("time_offset", kf.get("offset"))
            if (
                not seg_id
                or prop_name not in _PROPERTY_MAP
                or offset_value is None
                or "value" not in kf
            ):
                continue

            offset = _parse_time(offset_value)
            value = kf["value"]
            prop = _PROPERTY_MAP[prop_name]
            segment = _find_segment(script, seg_id)

            if segment is None:
                if not _add_imported_keyframe(
                    script, seg_id, prop, offset, value
                ):
                    continue
            elif prop == KeyframeProperty.volume and isinstance(segment, AudioSegment):
                segment.add_keyframe(offset, value)
            else:
                segment.add_keyframe(prop, offset, value)
            count += 1

        _context.save_script(script)

        return _context.make_result(True, f"批量添加了 {count} 个关键帧", count=count)

    @staticmethod
    def list_properties() -> Dict[str, Any]:
        """列出所有支持的关键帧属性

        Returns:
            dict: {"success": bool, "properties": list[dict]}
        """
        props = [
            {"name": "position_x", "description": "X位移，半画布宽为单位", "range": "任意实数"},
            {"name": "position_y", "description": "Y位移，半画布高为单位", "range": "任意实数"},
            {"name": "rotation", "description": "顺时针旋转角度", "range": "任意实数"},
            {"name": "scale_x", "description": "X轴缩放", "range": "1.0=不缩放"},
            {"name": "scale_y", "description": "Y轴缩放", "range": "1.0=不缩放"},
            {"name": "uniform_scale", "description": "等比缩放（与scale_x/y互斥）", "range": "1.0=不缩放"},
            {"name": "alpha", "description": "不透明度", "range": "0~1, 1.0=完全不透明"},
            {"name": "saturation", "description": "饱和度", "range": "-1.0~1.0, 0.0=原始"},
            {"name": "contrast", "description": "对比度", "range": "-1.0~1.0, 0.0=原始"},
            {"name": "brightness", "description": "亮度", "range": "-1.0~1.0, 0.0=原始"},
            {"name": "volume", "description": "音量", "range": "1.0=原始音量"},
        ]
        return _context.make_result(True, f"共 {len(props)} 种属性", properties=props)


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

def _parse_time(value):
    if value is None:
        return None
    from .time_tool import parse_time_value
    return parse_time_value(value)


def _find_segment(script, segment_id):
    """在可编辑轨道和导入轨道中查找指定 ID 的片段"""
    for track in script.tracks.values():
        for seg in track.segments:
            if seg.segment_id == segment_id:
                return seg
    # 跨进程/缓存 miss 时片段仅存在于 imported_tracks
    for imp_track in script.imported_tracks:
        for seg_data in imp_track.raw_data.get("segments", []):
            if seg_data.get("id") == segment_id:
                return None  # 原始数据不可编辑
    return None


def _raw_property_type(prop: KeyframeProperty) -> str:
    if prop == KeyframeProperty.uniform_scale:
        return KeyframeProperty.scale_x.value
    return prop.value


def _add_imported_keyframe(
    script,
    segment_id: str,
    prop: KeyframeProperty,
    time_offset: int,
    value: float,
) -> bool:
    """Attach a linear keyframe to an already-saved/imported segment."""
    seg_data = None
    seg_obj = None
    for imp_track in script.imported_tracks:
        for index, item in enumerate(imp_track.raw_data.get("segments", [])):
            if item.get("id") == segment_id:
                seg_data = item
                if hasattr(imp_track, "segments") and index < len(imp_track.segments):
                    seg_obj = imp_track.segments[index]
                break
        if seg_data is not None:
            break
    if seg_data is None:
        return False

    property_type = _raw_property_type(prop)
    containers = seg_data.setdefault("common_keyframes", [])
    container = next(
        (
            item
            for item in containers
            if item.get("property_type") == property_type
        ),
        None,
    )
    if container is None:
        container = {
            "id": uuid4().hex,
            "keyframe_list": [],
            "material_id": "",
            "property_type": property_type,
        }
        containers.append(container)

    container.setdefault("keyframe_list", []).append(
        {
            "curveType": "Line",
            "graphID": "",
            "id": uuid4().hex,
            "left_control": {"x": 0.0, "y": 0.0},
            "right_control": {"x": 0.0, "y": 0.0},
            "time_offset": time_offset,
            "values": [value],
        }
    )
    container["keyframe_list"].sort(
        key=lambda item: int(item.get("time_offset") or 0)
    )
    if seg_obj is not None:
        seg_obj.raw_data = seg_data
    return True
