"""jianying_utils — 基于 pyJianYingDraft 的 Dify 工作流插件工具包

每个工具类封装一个功能域，所有方法返回统一的 dict 格式，
方便在 Dify 工作流的代码节点中调用。

工具类列表:
    - DraftManager: 草稿管理（创建/加载/复制/删除/保存）
    - TrackManager: 轨道管理（添加/列出轨道）
    - VideoTool: 视频/图片片段（添加/批量添加）
    - AudioTool: 音频片段（添加/批量/淡入淡出/关键帧）
    - TextTool: 文本/字幕（添加/批量/SRT导入）
    - EffectTool: 特效/滤镜（场景/人物特效/滤镜轨道/批量）
    - StickerTool: 贴纸
    - AnimationTool: 动画（入场/出场/组合/循环）
    - KeyframeTool: 关键帧
    - TransitionTool: 转场
    - TemplateTool: 模板（加载/替换/导入轨道）
    - MaterialTool: 素材管理（信息获取/裁剪设置）
    - MetadataQuery: 元数据查询（枚举列表）
    - TimeTool: 时间工具（解析/格式化/转换）
    - ExportTool: 导出工具（JSON序列化）
    - TTSTool: TTS 语音合成（Edge-TTS 免费接口）
"""

from .draft_manager import DraftManager
from .track_manager import TrackManager
from .video_tool import VideoTool
from .audio_tool import AudioTool
from .text_tool import TextTool
from .effect_tool import EffectTool
from .sticker_tool import StickerTool
from .animation_tool import AnimationTool
from .keyframe_tool import KeyframeTool
from .transition_tool import TransitionTool
from .template_tool import TemplateTool
from .material_tool import MaterialTool
from .metadata_query import MetadataQuery
from .time_tool import TimeTool
from .export_tool import ExportTool
from .tts_tool import TTSTool

__all__ = [
    "DraftManager",
    "TrackManager",
    "VideoTool",
    "AudioTool",
    "TextTool",
    "EffectTool",
    "StickerTool",
    "AnimationTool",
    "KeyframeTool",
    "TransitionTool",
    "TemplateTool",
    "MaterialTool",
    "MetadataQuery",
    "TimeTool",
    "ExportTool",
    "TTSTool",
]

__version__ = "0.2.0"
