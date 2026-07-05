"""音频片段工具 — 添加音频片段、批量添加、音效、淡入淡出

支持本地文件路径和远程 URL（自动下载到本地缓存）。
适用于 Dify 工作流的代码节点。
"""

from typing import Optional, Dict, Any, List, Union

from pyJianYingDraft import AudioSegment, AudioMaterial, Timerange

from . import _context
from .material_path import resolve_material_path


def _resolve_audio_path(audio_path: str) -> str:
    return resolve_material_path(audio_path, ".mp3", "audio/mpeg,audio/*;q=0.9,*/*;q=0.8")


class AudioTool:
    """音频片段工具类"""

    @staticmethod
    @_context.catch_errors("添加音频")
    def add_audio(folder_path: str, draft_name: str,
                  audio_path: str, start: Union[str, int],
                  duration: Optional[Union[str, int]] = None,
                  speed: float = 1.0, volume: float = 1.0,
                  change_pitch: bool = False,
                  track_name: Optional[str] = None,
                  source_timerange_start: Optional[Union[str, int]] = None,
                  source_timerange_duration: Optional[Union[str, int]] = None) -> Dict[str, Any]:
        """添加单个音频片段到轨道

        Args:
            folder_path: 草稿根文件夹路径
            draft_name: 草稿名称
            audio_path: 音频文件路径或远程 URL（mp3, wav 等）
            start: 起始时间（微秒或时间字符串如 "5s"）
            duration: 持续时间（微秒或时间字符串），不指定则使用素材全长
            speed: 播放速度，默认1.0
            volume: 音量，默认1.0
            change_pitch: 是否跟随变速改变音调，默认False
            track_name: 目标轨道名称
            source_timerange_start: 素材截取起始时间
            source_timerange_duration: 素材截取持续时间

        Returns:
            dict: {"success": bool, "segment_id": str, "duration": int}
        """
        script = _context.load_script(folder_path, draft_name)

        audio_path = _resolve_audio_path(audio_path)

        start_us = _parse_time(start)
        duration_us = _parse_optional_time(duration)

        material = AudioMaterial(audio_path)

        if duration_us is None:
            if speed != 1.0:
                duration_us = round(material.duration / speed)
            else:
                duration_us = material.duration
        else:
            # 用户指定的 duration 超过素材时长时截断（TTS 舍入误差保护）
            max_dur = round(material.duration / speed) if speed != 1.0 else material.duration
            if duration_us > max_dur:
                duration_us = max_dur
        target_tr = Timerange(start_us, duration_us)

        source_tr = None
        source_start_us = _parse_optional_time(source_timerange_start)
        source_duration_us = _parse_optional_time(source_timerange_duration)
        if source_start_us is not None or source_duration_us is not None:
            src_start = source_start_us if source_start_us is not None else 0
            src_dur = source_duration_us if source_duration_us is not None else material.duration
            source_tr = Timerange(src_start, src_dur)

        segment = AudioSegment(
            material, target_tr,
            source_timerange=source_tr,
            speed=speed if source_tr is None else None,
            volume=volume,
            change_pitch=change_pitch
        )

        script.add_segment(segment, track_name)
        _context.save_script(script)

        return _context.make_result(
            True,
            f"音频片段已添加: {material.material_name}",
            segment_id=segment.segment_id,
            material_name=material.material_name,
            duration=segment.target_timerange.duration
        )

    @staticmethod
    @_context.catch_errors("批量添加音频")
    def add_audios_batch(folder_path: str, draft_name: str,
                         audio_infos: List[Dict[str, Any]],
                         track_name: Optional[str] = None) -> Dict[str, Any]:
        """批量添加音频片段

        Args:
            folder_path: 草稿根文件夹路径
            draft_name: 草稿名称
            audio_infos: 音频信息列表，每项包含:
                - audio_path (str): 音频文件路径或远程 URL（必须）
                - start (int): 起始时间微秒（必须）
                - end (int): 结束时间微秒（必须）
                - speed (float): 播放速度，默认1.0
                - volume (float): 音量，默认1.0
            track_name: 目标轨道名称

        Returns:
            dict: {"success": bool, "segment_ids": list[str], "count": int}
        """
        script = _context.load_script(folder_path, draft_name)
        segment_ids = []

        for info in audio_infos:
            audio_path = _resolve_audio_path(info["audio_path"])
            start = info["start"]
            end = info["end"]
            duration = end - start

            speed = info.get("speed", 1.0)
            volume = info.get("volume", 1.0)

            material = AudioMaterial(audio_path)
            target_tr = Timerange(start, duration)
            segment = AudioSegment(material, target_tr, speed=speed, volume=volume)
            script.add_segment(segment, track_name)
            segment_ids.append(segment.segment_id)

        _context.save_script(script)

        return _context.make_result(
            True,
            f"批量添加了 {len(segment_ids)} 个音频片段",
            segment_ids=segment_ids,
            count=len(segment_ids)
        )

    @staticmethod
    @_context.catch_errors("添加淡入淡出")
    def add_fade(folder_path: str, draft_name: str,
                 segment_id: str,
                 in_duration: Union[str, int],
                 out_duration: Union[str, int]) -> Dict[str, Any]:
        """为音频片段添加淡入淡出效果

        Args:
            folder_path: 草稿根文件夹路径
            draft_name: 草稿名称
            segment_id: 片段ID
            in_duration: 淡入时长（微秒或时间字符串）
            out_duration: 淡出时长（微秒或时间字符串）

        Returns:
            dict: {"success": bool}
        """
        script = _context.load_script(folder_path, draft_name)
        segment = _find_segment_by_id(script, segment_id)

        if segment is None:
            return _context.make_result(False, f"未找到片段 {segment_id}")

        if not isinstance(segment, AudioSegment):
            return _context.make_result(False, "该片段不是音频片段")

        segment.add_fade(in_duration, out_duration)
        _context.save_script(script)
        return _context.make_result(True, "淡入淡出已添加")

    @staticmethod
    @_context.catch_errors("添加关键帧")
    def add_volume_keyframe(folder_path: str, draft_name: str,
                            segment_id: str,
                            time_offset: int, volume: float) -> Dict[str, Any]:
        """为音频片段添加音量关键帧

        Args:
            folder_path: 草稿根文件夹路径
            draft_name: 草稿名称
            segment_id: 片段ID
            time_offset: 关键帧时间偏移量（微秒）
            volume: 音量值

        Returns:
            dict: {"success": bool}
        """
        script = _context.load_script(folder_path, draft_name)
        segment = _find_segment_by_id(script, segment_id)

        if segment is None:
            return _context.make_result(False, f"未找到片段 {segment_id}")

        segment.add_keyframe(time_offset, volume)
        _context.save_script(script)
        return _context.make_result(True, f"音量关键帧已添加: t={time_offset}, v={volume}")


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

def _parse_time(value):
    if value is None:
        return None
    from .time_tool import parse_time_value
    return parse_time_value(value)


def _parse_optional_time(value):
    if isinstance(value, str) and not value.strip():
        return None
    return _parse_time(value)


def _find_segment_by_id(script, segment_id):
    """在所有可编辑轨道和导入轨道中查找指定 ID 的片段"""
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
