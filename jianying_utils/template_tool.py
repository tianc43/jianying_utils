"""模板工具 — 加载模板草稿、替换素材/文本、导入轨道

适用于 Dify 工作流的代码节点。
"""

import os
import urllib.parse
from typing import Optional, Dict, Any, List, Union

from pyJianYingDraft import (
    ScriptFile, AudioMaterial,
    Timerange, ShrinkMode, ExtendMode
)

from . import _context
from .material_path import resolve_material_path
from .video_material import create_video_material


# 缩短/延长模式映射
_SHRINK_MODE_MAP = {
    "cut_head": ShrinkMode.cut_head,
    "cut_tail": ShrinkMode.cut_tail,
    "cut_tail_align": ShrinkMode.cut_tail_align,
    "shrink": ShrinkMode.shrink,
}

_EXTEND_MODE_MAP = {
    "cut_material_tail": ExtendMode.cut_material_tail,
    "extend_head": ExtendMode.extend_head,
    "extend_tail": ExtendMode.extend_tail,
    "push_tail": ExtendMode.push_tail,
}


class TemplateTool:
    """模板工具类

    用于从已有草稿（模板）加载内容、替换素材和文本、导入轨道等。
    """

    @staticmethod
    @_context.catch_errors("加载模板")
    def load_template(folder_path: str, draft_name: str) -> Dict[str, Any]:
        """加载草稿作为模板进行编辑

        Args:
            folder_path: 草稿根文件夹路径
            draft_name: 草稿名称

        Returns:
            dict: {"success": bool, "tracks": list, "duration": int}
        """
        script = _context.load_script(folder_path, draft_name)

        tracks_info = []
        for track in script.imported_tracks:
            seg_count = len(getattr(track, 'segments', []))
            tracks_info.append({
                "name": track.name,
                "type": track.track_type.name,
                "render_index": track.render_index,
                "segment_count": seg_count,
                "editable": hasattr(track, 'segments')
            })

        return _context.make_result(
            True,
            f"模板 '{draft_name}' 已加载",
            tracks=tracks_info,
            duration=script.duration,
            width=script.width,
            height=script.height,
            fps=script.fps
        )

    @staticmethod
    @_context.catch_errors("获取轨道")
    def get_imported_tracks(folder_path: str, draft_name: str,
                            track_type: str,
                            name: Optional[str] = None,
                            index: Optional[int] = None) -> Dict[str, Any]:
        """获取模板中指定类型的导入轨道

        Args:
            folder_path: 草稿根文件夹路径
            draft_name: 草稿名称
            track_type: 轨道类型 "video" / "audio" / "text"
            name: 按名称筛选
            index: 按下标筛选（0为最下层）

        Returns:
            dict: {"success": bool, "track_name": str, "track_type": str, "segment_count": int}
        """
        from pyJianYingDraft import TrackType
        script = _context.load_script(folder_path, draft_name)

        type_map = {"video": TrackType.video, "audio": TrackType.audio, "text": TrackType.text}
        if track_type not in type_map:
            return _context.make_result(False, f"不支持的轨道类型 '{track_type}'")

        track = script.get_imported_track(type_map[track_type], name=name, index=index)

        seg_count = len(track)
        return _context.make_result(
            True,
            f"找到轨道: {track.name}",
            track_name=track.name,
            track_type=track.track_type.name,
            segment_count=seg_count,
            render_index=track.render_index
        )

    @staticmethod
    @_context.catch_errors("导入轨道")
    def import_track(folder_path: str, draft_name: str,
                     source_folder_path: str, source_draft_name: str,
                     track_type: str,
                     track_name: Optional[str] = None,
                     track_index: Optional[int] = None,
                     offset: Union[str, int] = 0,
                     new_name: Optional[str] = None) -> Dict[str, Any]:
        """从另一个草稿导入轨道到当前草稿

        Args:
            folder_path: 目标草稿根文件夹
            draft_name: 目标草稿名称
            source_folder_path: 源草稿根文件夹
            source_draft_name: 源草稿名称
            track_type: 轨道类型 "video" / "audio" / "text"
            track_name: 源轨道名称（用于筛选）
            track_index: 源轨道下标（用于筛选）
            offset: 时间偏移量
            new_name: 新轨道名称

        Returns:
            dict: {"success": bool}
        """
        from pyJianYingDraft import TrackType
        target = _context.load_script(folder_path, draft_name)
        source = _context.load_script(source_folder_path, source_draft_name)

        type_map = {"video": TrackType.video, "audio": TrackType.audio, "text": TrackType.text}
        if track_type not in type_map:
            return _context.make_result(False, f"不支持的轨道类型 '{track_type}'")

        track = source.get_imported_track(type_map[track_type], name=track_name, index=track_index)
        target.import_track(source, track, offset=offset, new_name=new_name)
        _context.save_script(target)

        return _context.make_result(True, f"轨道 '{track.name}' 已导入")

    @staticmethod
    @_context.catch_errors("替换素材")
    def replace_material_by_name(folder_path: str, draft_name: str,
                                 material_name: str,
                                 new_material_path: str,
                                 replace_crop: bool = False) -> Dict[str, Any]:
        """替换指定名称的素材（影响所有引用它的片段）

        Args:
            folder_path: 草稿根文件夹路径
            draft_name: 草稿名称
            material_name: 要替换的素材名称
            new_material_path: 新素材文件路径
            replace_crop: 是否替换裁剪设置（仅视频）

        Returns:
            dict: {"success": bool}
        """
        script = _context.load_script(folder_path, draft_name)

        # 判断是视频还是音频（根据扩展名初步判断）
        parsed_path = urllib.parse.urlparse(new_material_path).path
        ext_source = urllib.parse.unquote(parsed_path or new_material_path)
        ext = os.path.splitext(ext_source)[1].lower()
        video_exts = {'.mp4', '.mov', '.avi', '.mkv', '.gif', '.jpg', '.jpeg', '.png', '.bmp', '.webp'}
        audio_exts = {'.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a'}

        if ext in video_exts:
            resolved_path = resolve_material_path(new_material_path, ".jpg", "image/*,video/*;q=0.9,*/*;q=0.8")
            material = create_video_material(resolved_path)
        elif ext in audio_exts:
            resolved_path = resolve_material_path(new_material_path, ".mp3", "audio/mpeg,audio/*;q=0.9,*/*;q=0.8")
            material = AudioMaterial(resolved_path)
        else:
            return _context.make_result(False, f"不支持的素材格式: {ext}")

        script.replace_material_by_name(material_name, material, replace_crop=replace_crop)
        _context.save_script(script)

        return _context.make_result(True, f"素材 '{material_name}' 已替换为 {os.path.basename(resolved_path)}")

    @staticmethod
    @_context.catch_errors("替换文本")
    def replace_text(folder_path: str, draft_name: str,
                     track_type: str,
                     track_name: Optional[str],
                     track_index: Optional[int],
                     segment_index: int,
                     text: Union[str, List[str]]) -> Dict[str, Any]:
        """替换模板中指定文本片段的文字内容

        Args:
            folder_path: 草稿根文件夹路径
            draft_name: 草稿名称
            track_type: 轨道类型（应为 "text"）
            track_name: 轨道名称
            track_index: 轨道下标
            segment_index: 片段下标（从0开始）
            text: 新文字内容（普通文本为字符串，模板为字符串列表）

        Returns:
            dict: {"success": bool}
        """
        from pyJianYingDraft import TrackType
        script = _context.load_script(folder_path, draft_name)

        track = script.get_imported_track(TrackType.text, name=track_name, index=track_index)
        script.replace_text(track, segment_index, text)
        _context.save_script(script)

        return _context.make_result(True, f"文本已替换: 片段 [{segment_index}]")

    @staticmethod
    @_context.catch_errors("检查素材")
    def inspect_material(folder_path: str, draft_name: str) -> Dict[str, Any]:
        """查看草稿中的贴纸、气泡、花字素材元数据

        Args:
            folder_path: 草稿根文件夹路径
            draft_name: 草稿名称

        Returns:
            dict: {"success": bool, "stickers": list, "bubbles": list, "text_effects": list}
        """
        script = _context.load_script(folder_path, draft_name)

        stickers = []
        bubbles = []
        text_effects = []

        if "stickers" in script.imported_materials:
            for s in script.imported_materials["stickers"]:
                stickers.append({
                    "resource_id": s.get("resource_id", ""),
                    "name": s.get("name", "")
                })

        if "effects" in script.imported_materials:
            for e in script.imported_materials["effects"]:
                item = {
                    "effect_id": e.get("effect_id", ""),
                    "resource_id": e.get("resource_id", ""),
                    "name": e.get("name", "")
                }
                if e.get("type") == "text_shape":
                    bubbles.append(item)
                elif e.get("type") == "text_effect":
                    text_effects.append(item)

        return _context.make_result(
            True,
            f"素材检查完成: {len(stickers)} 贴纸, {len(bubbles)} 气泡, {len(text_effects)} 花字",
            stickers=stickers,
            bubbles=bubbles,
            text_effects=text_effects
        )
