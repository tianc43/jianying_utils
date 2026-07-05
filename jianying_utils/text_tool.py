"""文本/字幕工具 — 添加文本、批量字幕、SRT导入、文本样式

适用于 Dify 工作流的代码节点。
"""

import json
from typing import Optional, Dict, Any, List, Union

from pyJianYingDraft import (
    TextSegment, TextStyle, TextBorder, TextBackground, TextShadow,
    Timerange, ClipSettings, FontType
)

from . import _context


class TextTool:
    """文本/字幕工具类"""

    @staticmethod
    @_context.catch_errors("添加文本")
    def add_text(folder_path: str, draft_name: str,
                 text: str, start: Union[str, int], duration: Union[str, int],
                 font: Optional[str] = None,
                 font_size: float = 8.0,
                 text_color: str = "#FFFFFF",
                 text_gradient: Optional[Dict[str, Any]] = None,
                 alpha: float = 1.0,
                 bold: bool = False,
                 italic: bool = False,
                 underline: bool = False,
                 alignment: int = 0,
                 vertical: bool = False,
                 letter_spacing: int = 0,
                 line_spacing: int = 0,
                 auto_wrapping: bool = False,
                 line_max_width: float = 0.82,
                 border: Optional[Dict[str, Any]] = None,
                 background: Optional[Dict[str, Any]] = None,
                 shadow: Optional[Dict[str, Any]] = None,
                 clip_settings: Optional[Dict[str, Any]] = None,
                 track_name: Optional[str] = None) -> Dict[str, Any]:
        """添加文本片段

        Args:
            folder_path: 草稿根文件夹路径
            draft_name: 草稿名称
            text: 文本内容
            start: 起始时间（微秒或时间字符串）
            duration: 持续时间（微秒或时间字符串）
            font: 字体名称（通过 MetadataQuery.list_fonts 获取可选值）
            font_size: 字体大小，默认8.0
            text_color: 文字颜色，十六进制格式 "#RRGGBB"，默认白色
            text_gradient: 渐变填充设置，优先于 text_color
            alpha: 文字不透明度 0~1，默认1.0
            bold: 是否加粗
            italic: 是否斜体
            underline: 是否下划线
            alignment: 对齐方式 0=左对齐, 1=居中, 2=右对齐
            vertical: 是否竖排文本
            letter_spacing: 字符间距
            line_spacing: 行间距
            auto_wrapping: 是否自动换行
            line_max_width: 最大行宽比例 0~1
            border: 描边设置字典 {"alpha": float, "color": str, "width": float}
            background: 背景设置字典 {"color": str, ...}
            shadow: 阴影设置字典 {"alpha": float, "color": str, "diffuse": float, "distance": float, "angle": float}
            clip_settings: 图像调节设置字典
            track_name: 目标轨道名称

        Returns:
            dict: {"success": bool, "segment_id": str}
        """
        script = _context.load_script(folder_path, draft_name)

        start_us = _parse_time(start)
        duration_us = _parse_time(duration)
        tr = Timerange(start_us, duration_us)

        # 字体
        font_enum = None
        if font:
            try:
                font_enum = FontType.from_name(font)
            except ValueError:
                return _context.make_result(False, f"未找到字体 '{font}'")

        # 颜色
        color_rgb = _hex_to_rgb(text_color)

        # 文本样式
        style = TextStyle(
            size=font_size,
            bold=bold, italic=italic, underline=underline,
            color=color_rgb, alpha=alpha,
            align=alignment, vertical=vertical,
            letter_spacing=letter_spacing, line_spacing=line_spacing,
            auto_wrapping=auto_wrapping, max_line_width=line_max_width
        )

        # 描边
        text_border = None
        if border:
            border_color = _hex_to_rgb(border.get("color", "#000000"))
            text_border = TextBorder(
                alpha=border.get("alpha", 1.0),
                color=border_color,
                width=border.get("width", 40.0)
            )

        # 背景
        text_bg = None
        if background:
            text_bg = TextBackground(
                color=background.get("color", "#000000"),
                style=background.get("style", 1),
                alpha=background.get("alpha", 1.0),
                round_radius=background.get("round_radius", 0.0),
                height=background.get("height", 0.14),
                width=background.get("width", 0.14),
                horizontal_offset=background.get("horizontal_offset", 0.5),
                vertical_offset=background.get("vertical_offset", 0.5)
            )

        # 阴影
        text_shadow = None
        if shadow:
            shadow_color = _hex_to_rgb(shadow.get("color", "#000000"))
            text_shadow = TextShadow(
                alpha=shadow.get("alpha", 1.0),
                color=shadow_color,
                diffuse=shadow.get("diffuse", 15.0),
                distance=shadow.get("distance", 5.0),
                angle=shadow.get("angle", -45.0)
            )

        cs = _context.parse_clip_settings(clip_settings)

        segment = TextSegment(
            text, tr,
            font=font_enum,
            style=style,
            clip_settings=cs,
            border=text_border,
            background=text_bg,
            shadow=text_shadow
        )

        script.add_segment(segment, track_name)
        _apply_text_gradient(script, segment.material_id, text_gradient)
        _context.save_script(script)

        return _context.make_result(
            True,
            f"文本片段已添加",
            segment_id=segment.segment_id
        )

    @staticmethod
    @_context.catch_errors("批量添加字幕")
    def add_captions_batch(folder_path: str, draft_name: str,
                           captions: List[Dict[str, Any]],
                           font: Optional[str] = None,
                           font_size: float = 5.0,
                           text_color: str = "#FFFFFF",
                           text_gradient: Optional[Dict[str, Any]] = None,
                           alpha: float = 1.0,
                           bold: bool = False,
                           italic: bool = False,
                           underline: bool = False,
                           alignment: int = 1,
                           letter_spacing: int = 0,
                           line_spacing: int = 0,
                           line_max_width: float = 0.82,
                           auto_wrapping: bool = True,
                           border: Optional[Dict[str, Any]] = None,
                           background: Optional[Dict[str, Any]] = None,
                           shadow: Optional[Dict[str, Any]] = None,
                           clip_settings: Optional[Dict[str, Any]] = None,
                           track_name: Optional[str] = None,
                           has_shadow: bool = False) -> Dict[str, Any]:
        """批量添加字幕

        Args:
            folder_path: 草稿根文件夹路径
            draft_name: 草稿名称
            captions: 字幕列表，每项包含:
                - text (str): 字幕文本（必须）
                - start (int): 起始时间微秒（必须）
                - end (int): 结束时间微秒（必须）
            font: 字体名称
            font_size: 字体大小，默认5.0（模仿剪映导入字幕的默认值）
            text_color: 文字颜色 "#RRGGBB"
            text_gradient: 渐变填充设置，优先于 text_color
            alpha: 不透明度 0~1
            bold/italic/underline: 文字样式开关
            alignment: 对齐方式 0=左 1=中 2=右
            letter_spacing/line_spacing: 间距
            line_max_width: 最大行宽
            auto_wrapping: 自动换行
            border: 描边设置
            background: 背景设置
            shadow: 阴影设置
            clip_settings: 图像调节设置
            track_name: 目标轨道名称
            has_shadow: 是否启用阴影（当 shadow 为 None 时使用默认阴影）

        Returns:
            dict: {"success": bool, "segment_ids": list, "count": int}
        """
        script = _context.load_script(folder_path, draft_name)

        font_enum = None
        if font:
            try:
                font_enum = FontType.from_name(font)
            except ValueError:
                return _context.make_result(False, f"未找到字体 '{font}'")

        color_rgb = _hex_to_rgb(text_color)

        style = TextStyle(
            size=font_size,
            bold=bold, italic=italic, underline=underline,
            color=color_rgb, alpha=alpha,
            align=alignment,
            letter_spacing=letter_spacing, line_spacing=line_spacing,
            auto_wrapping=auto_wrapping, max_line_width=line_max_width
        )

        text_border = None
        if border:
            border_color = _hex_to_rgb(border.get("color", "#000000"))
            text_border = TextBorder(
                alpha=border.get("alpha", 1.0),
                color=border_color,
                width=border.get("width", 40.0)
            )

        text_bg = None
        if background:
            text_bg = TextBackground(
                color=background.get("color", "#000000"),
                style=background.get("style", 1),
                alpha=background.get("alpha", 1.0),
                round_radius=background.get("round_radius", 0.0),
                height=background.get("height", 0.14),
                width=background.get("width", 0.14),
                horizontal_offset=background.get("horizontal_offset", 0.5),
                vertical_offset=background.get("vertical_offset", 0.5)
            )

        text_shadow = None
        if shadow:
            shadow_color = _hex_to_rgb(shadow.get("color", "#000000"))
            text_shadow = TextShadow(
                alpha=shadow.get("alpha", 1.0),
                color=shadow_color,
                diffuse=shadow.get("diffuse", 15.0),
                distance=shadow.get("distance", 5.0),
                angle=shadow.get("angle", -45.0)
            )
        elif has_shadow:
            text_shadow = TextShadow()

        # 默认字幕 clip_settings（模仿剪映导入字幕时的位置）
        if clip_settings is None:
            cs = ClipSettings(transform_y=-0.8)
        else:
            cs = _context.parse_clip_settings(clip_settings)

        segment_ids = []
        for cap in captions:
            text = cap["text"]
            start = cap["start"]
            end = cap["end"]
            duration = end - start
            tr = Timerange(start, duration)

            segment = TextSegment(
                text, tr,
                font=font_enum,
                style=style,
                clip_settings=cs,
                border=text_border,
                background=text_bg,
                shadow=text_shadow
            )
            script.add_segment(segment, track_name)
            _apply_text_gradient(script, segment.material_id, text_gradient)
            segment_ids.append(segment.segment_id)

        _context.save_script(script)

        return _context.make_result(
            True,
            f"批量添加了 {len(segment_ids)} 条字幕",
            segment_ids=segment_ids,
            count=len(segment_ids)
        )

    @staticmethod
    @_context.catch_errors("导入 SRT")
    def import_srt(folder_path: str, draft_name: str,
                   srt_path: str, track_name: str,
                   font: Optional[str] = None,
                   font_size: float = 5.0,
                   text_color: str = "#FFFFFF",
                   alignment: int = 1,
                   time_offset: Union[str, float] = 0.0,
                   clip_settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """从 SRT 文件导入字幕

        Args:
            folder_path: 草稿根文件夹路径
            draft_name: 草稿名称
            srt_path: SRT 文件路径
            track_name: 文本轨道名称（不存在则自动创建）
            font: 字体名称
            font_size: 字体大小
            text_color: 文字颜色
            alignment: 对齐方式
            time_offset: 字幕整体时间偏移
            clip_settings: 图像调节设置

        Returns:
            dict: {"success": bool, "count": int}
        """
        script = _context.load_script(folder_path, draft_name)

        font_enum = None
        if font:
            try:
                font_enum = FontType.from_name(font)
            except ValueError:
                return _context.make_result(False, f"未找到字体 '{font}'")

        color_rgb = _hex_to_rgb(text_color)

        style = TextStyle(
            size=font_size,
            color=color_rgb,
            align=alignment,
            auto_wrapping=True
        )

        if clip_settings is None:
            cs = ClipSettings(transform_y=-0.8)
        else:
            cs = _context.parse_clip_settings(clip_settings)

        script.import_srt(srt_path, track_name,
                          time_offset=time_offset,
                          text_style=style,
                          clip_settings=cs)
        _context.save_script(script)

        return _context.make_result(True, f"SRT 字幕已导入: {srt_path}")


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

def _parse_time(value):
    if value is None:
        return None
    from .time_tool import parse_time_value
    return parse_time_value(value)


def _hex_to_rgb(hex_color: str):
    """#RRGGBB → (r, g, b) 0~1"""
    h = hex_color.lstrip('#')
    return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)


def _apply_text_gradient(script, material_id: str, text_gradient: Optional[Dict[str, Any]]) -> None:
    """Patch a text material to use Jianying's gradient fill structure."""
    if not text_gradient:
        return

    gradient, use_letter_color = _normalize_text_gradient(text_gradient)
    for material in script.materials.texts:
        if not isinstance(material, dict) or material.get("id") != material_id:
            continue

        content = json.loads(material.get("content") or "{}")
        styles = content.get("styles") or []
        for style in styles:
            fill = style.setdefault("fill", {})
            fill.pop("alpha", None)
            fill["content"] = {
                "render_type": "gradient",
                "gradient": gradient,
            }
            if use_letter_color is not None:
                style["useLetterColor"] = use_letter_color

        material["content"] = json.dumps(content, ensure_ascii=False)
        material["text_color"] = material.get("text_color") or "#FFFFFF"
        material["use_effect_default_color"] = False
        return

    raise ValueError(f"未找到文本素材: {material_id}")


def _normalize_text_gradient(text_gradient: Dict[str, Any]):
    """Normalize API gradient input to the observed Jianying JSON shape."""
    if not isinstance(text_gradient, dict):
        raise TypeError("text_gradient 必须是 object")

    source = text_gradient.get("gradient")
    if source is not None:
        if not isinstance(source, dict):
            raise TypeError("text_gradient.gradient 必须是 object")
        gradient = dict(source)
    else:
        gradient = {}

    colors = gradient.get("color", text_gradient.get("colors", text_gradient.get("color")))
    if not isinstance(colors, list) or len(colors) < 2:
        raise ValueError("text_gradient.colors 至少需要两个颜色")

    color_values = [_normalize_gradient_color(color) for color in colors]
    count = len(color_values)
    alphas = _normalize_number_list(
        gradient.get("alpha", text_gradient.get("alphas", text_gradient.get("alpha"))),
        count,
        1.0,
        "alpha",
    )
    percents = _normalize_number_list(
        gradient.get("percent", text_gradient.get("percents", text_gradient.get("percent"))),
        count,
        None,
        "percent",
    )
    if percents is None:
        percents = [0.0] if count == 1 else [i / (count - 1) for i in range(count)]

    gradient.update(
        {
            "angle": gradient.get("angle", text_gradient.get("angle", 0)),
            "color": color_values,
            "alpha": alphas,
            "percent": percents,
            "mode": gradient.get("mode", text_gradient.get("mode", "all")),
        }
    )
    use_letter_color = text_gradient.get("useLetterColor", text_gradient.get("use_letter_color"))
    if use_letter_color is not None:
        use_letter_color = bool(use_letter_color)
    return gradient, use_letter_color


def _normalize_gradient_color(color):
    if isinstance(color, str):
        return list(_hex_to_rgb(color))
    if isinstance(color, (list, tuple)) and len(color) == 3:
        values = [float(v) for v in color]
        if any(v > 1 for v in values):
            values = [v / 255.0 for v in values]
        return values
    raise ValueError("渐变颜色必须是 #RRGGBB 字符串或 RGB 三元组")


def _normalize_number_list(value, count: int, default, name: str):
    if value is None:
        if default is None:
            return None
        return [default] * count
    if isinstance(value, (int, float)):
        return [float(value)] * count
    if not isinstance(value, list) or len(value) != count:
        raise ValueError(f"text_gradient.{name} 长度必须与 colors 一致")
    return [float(v) for v in value]
