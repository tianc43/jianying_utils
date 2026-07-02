"""素材管理工具 — 创建视频/音频素材对象、获取素材信息

适用于 Dify 工作流的代码节点。
"""

from typing import Dict, Any

from pyJianYingDraft import AudioMaterial, CropSettings

from . import _context
from .material_path import resolve_material_path
from .video_material import create_video_material


class MaterialTool:
    """素材管理工具类"""

    @staticmethod
    @_context.catch_errors("获取素材信息")
    def get_video_info(path: str) -> Dict[str, Any]:
        """获取视频/图片素材信息

        Args:
            path: 素材文件路径

        Returns:
            dict: {"success": bool, "duration": int, "width": int, "height": int, "type": str}
        """
        path = resolve_material_path(path, ".jpg", "image/*,video/*;q=0.9,*/*;q=0.8")
        mat = create_video_material(path)
        return _context.make_result(
            True,
            f"素材信息: {mat.material_name}",
            duration=mat.duration,
            width=mat.width,
            height=mat.height,
            type=mat.material_type,
            material_name=mat.material_name,
            path=mat.path
        )

    @staticmethod
    @_context.catch_errors("获取音频时长")
    def get_audio_duration(path: str) -> Dict[str, Any]:
        """获取音频素材时长

        Args:
            path: 音频文件路径

        Returns:
            dict: {"success": bool, "duration": int, "duration_seconds": float}
        """
        path = resolve_material_path(path, ".mp3", "audio/mpeg,audio/*;q=0.9,*/*;q=0.8")
        mat = AudioMaterial(path)
        duration_sec = mat.duration / 1_000_000.0
        return _context.make_result(
            True,
            f"音频时长: {duration_sec:.2f}s",
            duration=mat.duration,
            duration_seconds=round(duration_sec, 3),
            material_name=mat.material_name,
            path=mat.path
        )

    @staticmethod
    def create_crop_settings(upper_left_x: float = 0.0, upper_left_y: float = 0.0,
                             upper_right_x: float = 1.0, upper_right_y: float = 0.0,
                             lower_left_x: float = 0.0, lower_left_y: float = 1.0,
                             lower_right_x: float = 1.0, lower_right_y: float = 1.0) -> Dict[str, Any]:
        """创建裁剪设置字典

        坐标系原点在左上角，各值范围 0~1。

        Args:
            upper_left_x/y: 左上角坐标
            upper_right_x/y: 右上角坐标
            lower_left_x/y: 左下角坐标
            lower_right_x/y: 右下角坐标

        Returns:
            dict: 裁剪设置字典
        """
        return {
            "upper_left_x": upper_left_x, "upper_left_y": upper_left_y,
            "upper_right_x": upper_right_x, "upper_right_y": upper_right_y,
            "lower_left_x": lower_left_x, "lower_left_y": lower_left_y,
            "lower_right_x": lower_right_x, "lower_right_y": lower_right_y
        }
