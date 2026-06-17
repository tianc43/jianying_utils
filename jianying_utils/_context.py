"""内部上下文管理器 — ScriptFile 的加载/保存/序列化桥接层

所有工具类通过此模块与 pyjianyingdraft 的 ScriptFile 交互。

两种使用模式:
1. **会话模式** (推荐): 通过 get_script/commit_script 在同一进程中链式操作，
   避免 save/reload 开销，适合 Dify 单代码节点内完成所有操作。
2. **文件模式**: 通过 load_script/save_script 在磁盘上持久化，
   适合跨进程或跨节点的独立调用。
"""

import os
import json
import re
import uuid
from typing import Optional, Dict, Any, Tuple, List

from pyJianYingDraft import DraftFolder, ScriptFile


# ---------------------------------------------------------------------------
# 会话管理器 — 在同一进程中保持 ScriptFile 状态
# ---------------------------------------------------------------------------

_sessions: Dict[str, ScriptFile] = {}


def _session_key(folder_path: str, draft_name: str) -> str:
    return os.path.normpath(os.path.join(folder_path, draft_name))


def get_script(folder_path: str, draft_name: str) -> ScriptFile:
    """获取 ScriptFile: 优先从会话缓存获取，否则从磁盘加载

    用于工具类的链式调用，避免重复的 save/reload。
    """
    key = _session_key(folder_path, draft_name)
    if key in _sessions:
        return _sessions[key]
    return load_script(folder_path, draft_name)


def commit_script(script: ScriptFile, folder_path: str, draft_name: str) -> None:
    """将修改后的 ScriptFile 存入会话缓存（不写磁盘）

    搭配 get_script 使用，在所有操作完成后统一 save。
    """
    key = _session_key(folder_path, draft_name)
    _sessions[key] = script


def flush_session(folder_path: str, draft_name: str) -> str:
    """将会话中的 ScriptFile 写入磁盘并清除缓存

    Returns:
        str: 保存的文件路径
    """
    key = _session_key(folder_path, draft_name)
    script = _sessions.pop(key, None)
    if script is not None:
        return save_script(script)
    return ""


def clear_session(folder_path: str, draft_name: str) -> None:
    """清除会话缓存（不写磁盘）"""
    key = _session_key(folder_path, draft_name)
    _sessions.pop(key, None)


# ---------------------------------------------------------------------------
# 核心加载/保存函数（文件模式）
# ---------------------------------------------------------------------------

def load_script(folder_path: str, draft_name: str) -> ScriptFile:
    """从磁盘加载草稿的 ScriptFile 对象（优先使用会话缓存）

    load_template 会将 JSON 中已有的轨道/片段放入 imported_tracks。
    单次会话内缓存命中时 imported_tracks 为空，script.tracks 包含所有
    可编辑轨道。跨会话加载时 imported_tracks 包含历史片段，API 需通过
    add_track 创建同名轨道后继续添加新片段，save_script 会自动合并。

    Args:
        folder_path: 草稿根文件夹路径
        draft_name: 草稿名称

    Returns:
        ScriptFile 对象
    """
    key = _session_key(folder_path, draft_name)
    if key in _sessions:
        return _sessions[key]

    folder = DraftFolder(folder_path)
    script = folder.load_template(draft_name)

    # 不再调用 _rebuild_tracks_from_imported：
    # save_script 会将 script.tracks 新片段合并进 imported_tracks，
    # 仅创建空壳没有意义（历史片段仍在 imported_tracks 中）。

    # 存入会话缓存
    _sessions[key] = script
    return script


def save_script(script: ScriptFile) -> str:
    """保存 ScriptFile 到磁盘（幂等），同时更新会话缓存

    核心策略：将 script.tracks 中的新片段合并到 imported_tracks 中，
    然后清空 script.tracks。这样无论缓存是否命中，dumps() 都只导出
    imported_tracks，从根本上避免轨道重复。

    同时修复 pyJianYingDraft 库的两处缺陷：
    1. TextSegment speed 未加入 materials.speeds
    2. add_animation 后动画素材未加入 materials.animations（由 animation_tool 自行处理）
    """
    from uuid import uuid4
    from pyJianYingDraft import TextSegment
    from pyJianYingDraft.template_mode import (
        import_track, ImportedMediaSegment, ImportedSegment,
        ImportedMediaTrack, ImportedTextTrack, EditableTrack,
    )

    # --- 修复 1: 文本片段 speed 素材补全（库缺陷 workaround） ---
    existing_speed_ids = {s.global_id for s in script.materials.speeds}
    for track in script.tracks.values():
        for seg in track.segments:
            if isinstance(seg, TextSegment):
                sid = seg.speed.global_id
                if sid not in existing_speed_ids:
                    script.materials.speeds.append(seg.speed)
                    existing_speed_ids.add(sid)

    # --- 核心: 将 script.tracks 新片段合并到 imported_tracks ---
    for track_name, track in script.tracks.items():
        if not track.segments:
            continue  # 空轨道不参与合并

        # 导出片段 dict，并补全 ImportedTrack 构造函数要求的字段
        new_segs_json = []
        for seg in track.segments:
            seg_dict = seg.export_json()
            if "render_index" not in seg_dict:
                seg_dict["render_index"] = seg_dict.get("track_render_index", 0)
            new_segs_json.append(seg_dict)

        # 查找同名的 imported track，追加片段
        found = False
        for imp_track in script.imported_tracks:
            if imp_track.name == track_name:
                # 更新 raw_data（ImportedTrack.export_json 使用它）
                imp_track.raw_data.setdefault("segments", []).extend(new_segs_json)
                # 同时更新 self.segments（EditableTrack.export_json 会覆盖 raw_data）
                if isinstance(imp_track, ImportedMediaTrack):
                    imp_track.segments.extend(
                        ImportedMediaSegment(s) for s in new_segs_json
                    )
                elif isinstance(imp_track, ImportedTextTrack):
                    imp_track.segments.extend(
                        ImportedSegment(s) for s in new_segs_json
                    )
                found = True
                break

        if not found:
            # 新建一条 imported track（首次保存或 API 新增了全新轨道）
            raw_data = {
                "attribute": 0,
                "flag": 0,
                "id": uuid4().hex,
                "is_default_name": False,
                "name": track_name,
                "segments": new_segs_json,
                "type": track.track_type.name,
            }
            imp_track = import_track(raw_data)
            script.imported_tracks.append(imp_track)

        # 合并后清除片段（内容已迁移到 imported_tracks），
        # 轨道壳保留供后续 add_segment 使用
        track.segments.clear()

    # 已合并到 imported_tracks 的轨道：清除片段后暂移出 script.tracks
    # （避免 dumps() 合并时重复），保存后再恢复空壳供后续 API 调用使用。
    imported_names = {t.name for t in script.imported_tracks}
    saved_tracks = {}
    for name in imported_names & set(script.tracks.keys()):
        saved_tracks[name] = script.tracks.pop(name)

    # ------------------------------------------------------------------
    # 将素材文件复制到草稿文件夹内，路径改为便携相对路径。
    # 本机 downloader 导入剪映时再改写为本机占位符路径。
    # ------------------------------------------------------------------
    draft_dir = os.path.dirname(script.save_path)
    _relocate_media_to_draft(draft_dir, script.materials.audios, "audio")
    _relocate_media_to_draft(draft_dir, script.materials.videos, "video")
    # imported_materials 也会被 dumps() 导出
    for mat_key in ("audios", "videos"):
        sub = "audio" if mat_key == "audios" else "video"
        for mat_dict in script.imported_materials.get(mat_key, []):
            _relocate_media_dict_to_draft(draft_dir, mat_dict, sub)

    draft_name = os.path.basename(draft_dir)
    if not script.content.get("name"):
        script.content["name"] = draft_name

    script.save()
    _update_draft_meta_info(script.save_path, script.content)
    # 根据 save_path 推断 (folder, draft_name) 并更新会话
    _cache_by_save_path(script)

    # 恢复轨道空壳，供后续 add_segment 使用
    script.tracks.update(saved_tracks)

    return script.save_path


def _cache_by_save_path(script: ScriptFile) -> None:
    """通过 save_path 反推 (folder_path, draft_name) 并更新会话"""
    if not script.save_path:
        return
    norm = os.path.normpath(script.save_path)
    draft_dir = os.path.dirname(norm)
    draft_name = os.path.basename(draft_dir)
    folder_path = os.path.dirname(draft_dir)
    key = _session_key(folder_path, draft_name)
    _sessions[key] = script


def _rebuild_tracks_from_imported(script: ScriptFile) -> None:
    """从 imported_tracks 重建 tracks dict，使加载的草稿轨道可编辑

    注意：只创建尚不存在的轨道，避免覆盖已有（含片段）的轨道。
    """
    from pyJianYingDraft import TrackType
    from pyJianYingDraft.track import Track

    if not script.imported_tracks:
        return

    for imp_track in script.imported_tracks:
        tt = imp_track.track_type
        if tt == TrackType.adjust:
            continue
        # 不覆盖已存在的同名轨道（可能已包含新添加的片段）
        if imp_track.name not in script.tracks:
            track = Track(tt, imp_track.name, imp_track.render_index, False)
            script.tracks[imp_track.name] = track


def create_script(folder_path: str, draft_name: str,
                  width: int = 1920, height: int = 1080, fps: int = 30,
                  maintrack_adsorb: bool = True,
                  allow_replace: bool = False) -> ScriptFile:
    """创建新草稿并返回 ScriptFile 对象

    Args:
        folder_path: 草稿根文件夹路径
        draft_name: 草稿名称
        width: 视频宽度（像素）
        height: 视频高度（像素）
        fps: 帧率
        maintrack_adsorb: 是否启用主轨道吸附
        allow_replace: 是否允许覆盖同名草稿

    Returns:
        ScriptFile 对象
    """
    folder = DraftFolder(folder_path)
    script = folder.create_draft(draft_name, width, height, fps,
                                 maintrack_adsorb=maintrack_adsorb,
                                 allow_replace=allow_replace)
    # 存入会话缓存
    key = _session_key(folder_path, draft_name)
    _sessions[key] = script
    return script


def get_draft_path(folder_path: str, draft_name: str) -> str:
    """获取草稿文件夹路径

    Returns:
        草稿文件夹完整路径
    """
    return os.path.join(folder_path, draft_name)


def get_script_path(folder_path: str, draft_name: str) -> str:
    """获取 draft_content.json 的完整路径

    Returns:
        draft_content.json 文件路径
    """
    return os.path.join(folder_path, draft_name, "draft_content.json")


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def parse_clip_settings(clip_settings: Optional[Dict[str, Any]]):
    """将字典转换为 ClipSettings 对象，若为 None 则返回 None"""
    if clip_settings is None:
        return None
    from pyJianYingDraft import ClipSettings
    return ClipSettings(**clip_settings)


def parse_text_style(style: Optional[Dict[str, Any]]):
    """将字典转换为 TextStyle 对象，若为 None 则返回默认值"""
    if style is None:
        return None
    from pyJianYingDraft import TextStyle
    return TextStyle(**style)


def parse_text_border(border: Optional[Dict[str, Any]]):
    """将字典转换为 TextBorder 对象"""
    if border is None:
        return None
    from pyJianYingDraft import TextBorder
    return TextBorder(**border)


def parse_text_background(background: Optional[Dict[str, Any]]):
    """将字典转换为 TextBackground 对象"""
    if background is None:
        return None
    from pyJianYingDraft import TextBackground
    return TextBackground(**background)


def parse_text_shadow(shadow: Optional[Dict[str, Any]]):
    """将字典转换为 TextShadow 对象"""
    if shadow is None:
        return None
    from pyJianYingDraft import TextShadow
    return TextShadow(**shadow)


def hex_color_to_rgb(hex_color: str) -> Tuple[float, float, float]:
    """将十六进制颜色 (#RRGGBB 或 #RRGGBBAA) 转换为 RGB 三元组 (0~1)"""
    hex_color = hex_color.lstrip('#')
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0
    return (r, g, b)


# ---------------------------------------------------------------------------
# 素材文件路径修复 — 保存时将素材复制到草稿文件夹内
# ---------------------------------------------------------------------------


def _relocate_media_to_draft(draft_dir: str, materials, mat_type: str) -> None:
    """将素材文件复制到草稿内的 audio/ / image/ / video/ 子目录。

    Args:
        draft_dir: 草稿文件夹路径
        materials: script.materials.audios 或 script.materials.videos
        mat_type: \"audio\" 或 \"video\"
    """
    import shutil
    sub_dir = os.path.join(draft_dir, mat_type)
    for mat in materials:
        target_type = _material_subdir(mat_type, mat)
        sub_dir = os.path.join(draft_dir, target_type)
        if not hasattr(mat, "path"):
            continue
        path = mat.path
        if not path:
            continue

        placeholder_suffix = _placeholder_suffix(path)
        if placeholder_suffix:
            fname = os.path.basename(placeholder_suffix)
            _copy_existing_placeholder_file(draft_dir, placeholder_suffix, target_type, fname)
            mat.path = f"{target_type}/{fname}"
            continue

        src = _resolve_material_path(draft_dir, path)
        if not src or not os.path.isfile(src):
            continue

        fname = os.path.basename(src)
        os.makedirs(sub_dir, exist_ok=True)
        dest = os.path.join(sub_dir, fname)
        if os.path.abspath(src) != os.path.abspath(dest) and not os.path.exists(dest):
            try:
                shutil.copy2(src, dest)
            except Exception:
                continue  # 跳过无法复制的文件
        mat.path = f"{target_type}/{fname}"
        mat.material_name = fname


def _relocate_media_dict_to_draft(draft_dir: str, mat_dict: dict,
                                  mat_type: str) -> None:
    """将 imported_materials 中的素材路径改为便携相对路径并复制文件。

    Args:
        draft_dir: 草稿文件夹路径
        mat_dict: imported_materials 中的单个素材字典
        mat_type: \"audio\" 或 \"video\"
    """
    import shutil
    target_type = _material_subdir(mat_type, mat_dict)
    path = mat_dict.get("path", "")
    if not path:
        return

    placeholder_suffix = _placeholder_suffix(path)
    if placeholder_suffix:
        fname = os.path.basename(placeholder_suffix)
        _copy_existing_placeholder_file(draft_dir, placeholder_suffix, target_type, fname)
        mat_dict["path"] = f"{target_type}/{fname}"
        return

    src = _resolve_material_path(draft_dir, path)
    if not src or not os.path.isfile(src):
        return

    fname = os.path.basename(src)
    sub_dir = os.path.join(draft_dir, target_type)
    os.makedirs(sub_dir, exist_ok=True)
    dest = os.path.join(sub_dir, fname)
    if os.path.abspath(src) != os.path.abspath(dest) and not os.path.exists(dest):
        try:
            shutil.copy2(src, dest)
        except Exception:
            return
    mat_dict["path"] = f"{target_type}/{fname}"
    # 同时更新 name / material_name 字段
    if "name" in mat_dict:
        mat_dict["name"] = fname
    if "material_name" in mat_dict:
        mat_dict["material_name"] = fname


def _path_is_within(child: str, parent: str) -> bool:
    """安全判断 child 是否在 parent 目录下（兼容 Windows 跨盘符）"""
    try:
        return os.path.commonpath([parent, child]) == os.path.normpath(parent)
    except ValueError:
        return False  # 跨盘符（如 C: 和 D:）视为不在同一目录


_PLACEHOLDER_RE = re.compile(r"^##_draftpath_placeholder_[^#]+_##[/\\](.+)$")


def _get_or_create_draft_placeholder_id(draft_dir: str) -> str:
    """获取草稿路径占位符 ID。

    剪映的占位符不是任意草稿 ID，而是本机草稿目录里的路径占位符 ID。
    优先复用已有剪映草稿中的 ID，否则再为当前草稿兜底生成并持久化。
    """
    env_value = os.environ.get("JIANYING_DRAFT_PLACEHOLDER_ID", "").strip()
    if env_value:
        return env_value

    for root in _candidate_placeholder_roots(draft_dir):
        detected = _detect_existing_draft_placeholder_id(root)
        if detected:
            return detected

    sidecar = os.path.join(draft_dir, ".draft_path_placeholder")
    try:
        if os.path.isfile(sidecar):
            value = open(sidecar, "r", encoding="utf-8").read().strip()
            if value:
                return value
    except Exception:
        pass

    value = str(uuid.uuid4()).upper()
    try:
        with open(sidecar, "w", encoding="utf-8") as f:
            f.write(value)
    except Exception:
        pass
    return value


def _candidate_placeholder_roots(draft_dir: str) -> List[str]:
    """返回可用于探测剪映占位符 ID 的草稿根目录候选。"""
    roots = [os.path.dirname(draft_dir)]

    native_root = os.environ.get("JIANYING_NATIVE_DRAFTS_DIR", "").strip()
    if native_root:
        roots.append(native_root)

    # Local Windows default used by this project during manual verification.
    roots.append(r"D:\jianying\JianyingPro Drafts")

    seen = set()
    result = []
    for root in roots:
        norm = os.path.normpath(root) if root else ""
        if norm and norm not in seen and os.path.isdir(norm):
            seen.add(norm)
            result.append(norm)
    return result


def _detect_existing_draft_placeholder_id(drafts_root: str) -> Optional[str]:
    """从同一剪映草稿根目录中探测本机占位符 ID。"""
    if not drafts_root or not os.path.isdir(drafts_root):
        return None

    from collections import Counter

    ids = Counter()
    try:
        draft_dirs = [
            os.path.join(drafts_root, name)
            for name in os.listdir(drafts_root)
            if os.path.isdir(os.path.join(drafts_root, name))
        ]
    except Exception:
        return None

    draft_dirs.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    for draft_dir in draft_dirs[:80]:
        content_path = os.path.join(draft_dir, "draft_content.json")
        try:
            with open(content_path, "rb") as f:
                prefix = f.read(1)
                if prefix != b"{":
                    continue
                f.seek(0)
                text = f.read().decode("utf-8-sig", errors="ignore")
        except Exception:
            continue
        ids.update(re.findall(r"##_draftpath_placeholder_([^#]+)_##", text))

    if not ids:
        return None
    return ids.most_common(1)[0][0]


def _placeholder_suffix(path: str) -> Optional[str]:
    """返回占位符后的相对路径，如 audio/a.mp3；非占位符返回 None。"""
    match = _PLACEHOLDER_RE.match(path.replace("\\", "/"))
    if not match:
        return None
    return match.group(1).replace("\\", "/")


def _make_placeholder_path(draft_uuid: str, suffix: str) -> str:
    normalized_suffix = suffix.replace("\\", "/")
    return f"##_draftpath_placeholder_{draft_uuid}_##/{normalized_suffix}"


def _resolve_material_path(draft_dir: str, path: str) -> Optional[str]:
    """将素材路径解析为磁盘文件路径，支持绝对路径和草稿内相对路径。"""
    if os.path.isabs(path):
        return path
    rel = path.replace("/", os.sep).replace("\\", os.sep)
    return os.path.join(draft_dir, rel)


def _material_subdir(mat_type: str, material) -> str:
    """剪映画稿中图片素材使用 image/，视频素材使用 video/。"""
    if mat_type != "video":
        return mat_type
    material_type = ""
    if isinstance(material, dict):
        material_type = str(material.get("type") or material.get("material_type") or "")
    else:
        material_type = str(getattr(material, "material_type", ""))
    return "image" if material_type == "photo" else "video"


def _copy_existing_placeholder_file(draft_dir: str, suffix: str,
                                    target_type: str, fname: str) -> None:
    """占位符路径已存在但目录不符合类型时，复制到目标目录。"""
    import shutil

    src = os.path.join(draft_dir, suffix.replace("/", os.sep).replace("\\", os.sep))
    if not os.path.isfile(src):
        return
    sub_dir = os.path.join(draft_dir, target_type)
    os.makedirs(sub_dir, exist_ok=True)
    dest = os.path.join(sub_dir, fname)
    if os.path.abspath(src) != os.path.abspath(dest) and not os.path.exists(dest):
        shutil.copy2(src, dest)


def normalize_draft_media_paths(script_path: str) -> None:
    """规范化已保存草稿中的素材路径为便携相对路径。"""
    if not os.path.isfile(script_path):
        return

    draft_dir = os.path.dirname(script_path)
    try:
        with open(script_path, "r", encoding="utf-8-sig") as f:
            draft = json.load(f)
    except Exception:
        return

    changed = False
    mats = draft.get("materials", {})
    if isinstance(mats, dict):
        for mat_key, mat_type in (("audios", "audio"), ("videos", "video")):
            for mat in mats.get(mat_key, []) if isinstance(mats.get(mat_key), list) else []:
                if not isinstance(mat, dict):
                    continue
                old_path = mat.get("path", "")
                new_path = _normalize_media_dict_path(draft_dir, mat, mat_type)
                changed = changed or (new_path != old_path)

    draft_name = os.path.basename(draft_dir)
    if not draft.get("name"):
        draft["name"] = draft_name
        changed = True

    if changed:
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(draft, f, ensure_ascii=False, indent=4)
    _update_draft_meta_info(script_path, draft)


def _normalize_media_dict_path(draft_dir: str, mat_dict: dict,
                               mat_type: str) -> str:
    """规范化 draft_content.json 中单个素材字典的 path 字段。"""
    import shutil

    target_type = _material_subdir(mat_type, mat_dict)
    path = mat_dict.get("path", "")
    if not path:
        return path

    suffix = _placeholder_suffix(path)
    if suffix:
        fname = os.path.basename(suffix)
        _copy_existing_placeholder_file(draft_dir, suffix, target_type, fname)
        new_path = f"{target_type}/{fname}"
        mat_dict["path"] = new_path
        return new_path

    src = _resolve_material_path(draft_dir, path)
    if not src or not os.path.isfile(src):
        return path

    fname = os.path.basename(src)
    sub_dir = os.path.join(draft_dir, target_type)
    os.makedirs(sub_dir, exist_ok=True)
    dest = os.path.join(sub_dir, fname)
    if os.path.abspath(src) != os.path.abspath(dest) and not os.path.exists(dest):
        shutil.copy2(src, dest)

    new_path = f"{target_type}/{fname}"
    mat_dict["path"] = new_path
    if mat_type == "audio" and "name" in mat_dict:
        mat_dict["name"] = fname
    if mat_type == "video" and "material_name" in mat_dict:
        mat_dict["material_name"] = fname
    return new_path


def _update_draft_meta_info(script_path: str, draft: Dict[str, Any]) -> None:
    """补齐 draft_meta_info.json 中剪映草稿列表和路径解析需要的字段。"""
    draft_dir = os.path.dirname(script_path)
    meta_path = os.path.join(draft_dir, "draft_meta_info.json")
    if not os.path.isfile(meta_path):
        return
    try:
        with open(meta_path, "r", encoding="utf-8-sig") as f:
            meta = json.load(f)
    except Exception:
        return

    draft_name = os.path.basename(draft_dir)
    drafts_root = os.path.dirname(draft_dir)
    updates = {
        "draft_name": draft_name,
        "draft_fold_path": draft_dir.replace("\\", "/"),
        "draft_root_path": drafts_root,
        "tm_duration": int(draft.get("duration") or 0),
    }
    if draft.get("id"):
        updates["draft_id"] = draft["id"]
    for key, value in updates.items():
        meta[key] = value

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=4)


def make_result(success: bool, message: str = "", **kwargs) -> Dict[str, Any]:
    """构造统一的返回结果字典"""
    result = {"success": success, "message": message}
    result.update(kwargs)
    return result
