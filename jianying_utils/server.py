"""JianYing Draft API Server — FastAPI + OpenAPI

独立部署架构：服务端管理草稿目录，创建草稿返回 draft_id，
后续所有操作通过 draft_id 进行，无需客户端关心文件路径。

启动:
    uvicorn jianying_utils.server:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import os
import uuid
import re
import base64
import binascii
import hashlib
import socket
import urllib.error
import urllib.parse
import urllib.request
from http.client import IncompleteRead
import time
import tempfile
from typing import Optional, Dict, Any, List, Union
from pathlib import Path

from fastapi import FastAPI, Query, Body, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import zipfile
import io
from fastapi.responses import Response, FileResponse, StreamingResponse
from pydantic import BaseModel, Field
import json as _json

from jianying_utils import (
    DraftManager, TrackManager, VideoTool, AudioTool,
    TextTool, EffectTool, StickerTool, AnimationTool,
    KeyframeTool, TransitionTool, MaterialTool,
    MetadataQuery, TimeTool, ExportTool, TTSTool
)
from jianying_utils import _context
from jianying_utils.logging_config import setup_logging
from jianying_utils.video_material import create_video_material

setup_logging()
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# 项目根目录 & 关键路径
# ═══════════════════════════════════════════════════════════════════════════
_PROJECT_ROOT = Path(__file__).parent.parent   # 仓库根目录
_API_DIR = _PROJECT_ROOT / "api"                # OpenAPI 静态文件目录

# 草稿存储目录（可通过环境变量覆盖）
DRAFTS_DIR = os.environ.get("JIANYING_DRAFTS_DIR", str(_PROJECT_ROOT / "drafts"))
os.makedirs(DRAFTS_DIR, exist_ok=True)

# 静态 OpenAPI 文件路径
_OPENAPI_JSON = _API_DIR / "openapi.json"
_OPENAPI_YAML = _API_DIR / "openapi.yaml"

# ═══════════════════════════════════════════════════════════════════════════

# 部署时的 URL 前缀（nginx 反向代理路径），本地开发可不设
ROOT_PATH = os.environ.get("ROOT_PATH", "")
DEPLOY_URL = os.environ.get("DEPLOY_URL", "http://localhost:8000")

app = FastAPI(
    title="JianYing Draft API",
    description="剪映草稿自动化 — 独立部署 REST API",
    version="0.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
    root_path=ROOT_PATH,
    root_path_in_servers=False,
    servers=[{"url": DEPLOY_URL, "description": "剪映草稿 API 服务器"}],
    generate_unique_id_function=lambda route: route.name,
)

@app.on_event("startup")
def _log_startup_info():
    """记录启动信息（无论通过 uvicorn.run 还是 gunicorn worker 启动都会执行）"""
    logger.info("JianYing Draft API 启动完成 (pid=%d)", os.getpid())
    logger.info("Drafts dir:   %s", DRAFTS_DIR)
    logger.info("OpenAPI:      %s/openapi.json", DEPLOY_URL)
    logger.info("Swagger UI:   %s/docs", DEPLOY_URL)

# ═══════════════════════════════════════════════════════════════════════════
# 重写 openapi() — 直接返回本地静态文件，不再动态生成
# ═══════════════════════════════════════════════════════════════════════════
def _load_static_openapi():
    """加载本地 openapi.json，让 /docs /redoc /openapi.json 使用静态文件"""
    if _OPENAPI_JSON.exists():
        with open(_OPENAPI_JSON, encoding="utf-8") as f:
            schema = _json.load(f)
        # 动态替换 servers URL 为实际部署地址
        schema["servers"] = [{"url": DEPLOY_URL, "description": "剪映草稿 API 服务器"}]
        app.openapi_schema = schema
        return app.openapi_schema
    # 降级：本地文件不存在时用 FastAPI 动态生成
    return _openapi_fastapi_default()

_openapi_fastapi_default = app.openapi
app.openapi = _load_static_openapi

@app.get("/openapi.yaml", include_in_schema=False, tags=["系统"])
def openapi_yaml():
    """返回带当前部署地址的 OpenAPI YAML。"""
    import yaml
    spec = _load_static_openapi()
    yaml_str = yaml.dump(spec, allow_unicode=True, default_flow_style=False, sort_keys=False)
    return Response(content=yaml_str, media_type="application/x-yaml")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

@app.middleware("http")
async def _log_requests(request: Request, call_next):
    """统一请求日志：方法、路径、状态码、耗时。

    gunicorn 的 --access-logfile 只覆盖生产部署；开发时直接用 uvicorn 启动
    则完全没有请求记录，这里统一走应用日志，两种启动方式下都能看到。
    """
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        logger.exception("%s %s 处理异常 (%.1fms)", request.method, request.url.path, elapsed_ms)
        raise
    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
    log_fn = logger.info if response.status_code < 400 else logger.warning
    log_fn("%s %s -> %d (%.1fms)", request.method, request.url.path, response.status_code, elapsed_ms)
    return response

# 挂载静态文件目录（Swagger UI 查看器等）
if _PROJECT_ROOT.is_dir():
    app.mount("/static", StaticFiles(directory=str(_PROJECT_ROOT)), name="static")

# TTS 音频输出目录
_TTS_DIR = os.environ.get("JIANYING_TTS_DIR", tempfile.gettempdir())
os.makedirs(_TTS_DIR, exist_ok=True)

# Image material output directory. Defaults under project root so /static URLs work.
_IMAGE_DIR = os.environ.get("JIANYING_IMAGE_DIR", str(_PROJECT_ROOT / "uploads" / "images"))
_IMAGE_MAX_BYTES = int(os.environ.get("JIANYING_IMAGE_MAX_BYTES", str(20 * 1024 * 1024)))
_IMAGE_UPSTREAM_MAX_BODY_BYTES = int(os.environ.get(
    "JIANYING_IMAGE_UPSTREAM_MAX_BODY_BYTES",
    str((_IMAGE_MAX_BYTES * 4 // 3) + (2 * 1024 * 1024)),
))
os.makedirs(_IMAGE_DIR, exist_ok=True)
_IMAGE_CHUNK_DIR = os.environ.get("JIANYING_IMAGE_CHUNK_DIR", os.path.join(_IMAGE_DIR, "_chunks"))
os.makedirs(_IMAGE_CHUNK_DIR, exist_ok=True)

_SOUND_EFFECT_DIR = os.environ.get("JIANYING_SOUND_EFFECT_DIR", str(_PROJECT_ROOT / "assets" / "sound_effect"))
_SOUND_EFFECT_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".flac"}
_AUDIO_MEDIA_TYPES = {
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".wav": "audio/wav",
}

# 草稿注册表文件（多 worker 共享，通过文件系统同步）
_REGISTRY_FILE = os.path.join(DRAFTS_DIR, "_draft_registry.json")

_draft_registry: Dict[str, tuple] = {}

def _load_disk_registry() -> Dict[str, list]:
    """从磁盘加载注册表（处理其他 worker 写入的草稿）"""
    try:
        if os.path.exists(_REGISTRY_FILE):
            with open(_REGISTRY_FILE, "r", encoding="utf-8") as f:
                return _json.load(f)
    except Exception:
        logger.warning("草稿注册表读取失败，将视为空注册表: %s", _REGISTRY_FILE, exc_info=True)
    return {}

def _save_disk_registry(reg: Dict[str, list]):
    """持久化注册表到磁盘"""
    os.makedirs(DRAFTS_DIR, exist_ok=True)
    with open(_REGISTRY_FILE + ".tmp", "w", encoding="utf-8") as f:
        _json.dump(reg, f, ensure_ascii=False)
    os.replace(_REGISTRY_FILE + ".tmp", _REGISTRY_FILE)

def _resolve(draft_id: str) -> tuple:
    """解析 draft_id → (folder, name)，支持多 worker"""
    # 1) 本地内存缓存
    if draft_id in _draft_registry:
        return _draft_registry[draft_id]
    # 2) 磁盘注册表（其他 worker 创建）
    disk = _load_disk_registry()
    if draft_id in disk:
        folder, name = disk[draft_id]
        _draft_registry[draft_id] = (folder, name)
        return (folder, name)
    raise HTTPException(404, f"草稿不存在: {draft_id}")

def _ok(**kw) -> dict:
    return {"success": True, **kw}

def _return_or_raise(result: dict) -> dict:
    """Return tool results, but surface business failures as HTTP failures."""
    if result.get("success") is False:
        raise HTTPException(status_code=500, detail=result)
    return result

def _safe_filename_stem(value: str) -> str:
    stem = os.path.splitext(os.path.basename(value or ""))[0]
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", stem).strip(".-_")
    return stem[:80] or "image"

def _decode_b64_json(value: str) -> bytes:
    if not value:
        raise HTTPException(400, "b64_json 不能为空")
    payload = value.strip()
    if payload.startswith("data:"):
        _, _, payload = payload.partition(",")
    payload = "".join(payload.split())
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(400, "b64_json 不是有效的 Base64 数据") from exc
    if not data:
        raise HTTPException(400, "图片数据为空")
    if len(data) > _IMAGE_MAX_BYTES:
        raise HTTPException(413, f"图片超过大小限制: {_IMAGE_MAX_BYTES} bytes")
    return data

def _detect_image(data: bytes) -> tuple[str, str]:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif", "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    raise HTTPException(415, "仅支持 PNG/JPEG/WebP/GIF 图片")

def _project_static_url(path: str) -> str:
    try:
        relative = Path(path).resolve().relative_to(_PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return ""
    return f"{DEPLOY_URL}/static/{urllib.parse.quote(relative, safe='/')}"

def _sound_effect_item(file_path: Path) -> dict:
    digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
    static_url = _project_static_url(str(file_path))
    try:
        relative_path = file_path.resolve().relative_to(_PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        relative_path = file_path.name
    return {
        "name": file_path.stem,
        "filename": file_path.name,
        "relative_path": relative_path,
        "file_path": str(file_path.resolve()),
        "static_url": static_url,
        "audio_path": static_url,
        "media_type": _AUDIO_MEDIA_TYPES.get(file_path.suffix.lower(), "application/octet-stream"),
        "size": file_path.stat().st_size,
        "sha256": digest,
    }

def _save_image_bytes(data: bytes, filename_hint: Optional[str] = None) -> dict:
    ext, media_type = _detect_image(data)
    digest = hashlib.sha256(data).hexdigest()
    stem = _safe_filename_stem(filename_hint or f"image-{digest[:12]}")
    if not stem.endswith(digest[:12]):
        stem = f"{stem}-{digest[:12]}"
    filename = f"{stem}.{ext}"
    file_path = os.path.abspath(os.path.join(_IMAGE_DIR, filename))

    image_root = os.path.abspath(_IMAGE_DIR)
    if os.path.commonpath([image_root, file_path]) != image_root:
        raise HTTPException(400, "无效的文件名")

    if not os.path.isfile(file_path):
        with open(file_path, "wb") as output:
            output.write(data)

    return _ok(
        message="图片已保存",
        filename=filename,
        file_path=file_path,
        download_url=f"{DEPLOY_URL}/material/images/download/{filename}",
        static_url=_project_static_url(file_path),
        media_type=media_type,
        size=len(data),
        sha256=digest,
    )

def _ensure_http_url(url: str, label: str = "url") -> str:
    value = (url or "").strip()
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(400, f"{label} 必须是 http/https URL")
    return value

def _read_limited(response, max_bytes: int) -> bytes:
    data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(413, f"上游响应超过大小限制: {max_bytes} bytes")
    return data

def _summarize_upstream_error(status_code: int, headers: dict[str, str], body: bytes) -> str:
    text = body.decode("utf-8", errors="replace").strip()
    if len(text) > 1200:
        text = text[:1200] + "...(truncated)"
    request_id = (
        headers.get("x-request-id")
        or headers.get("x-client-request-id")
        or headers.get("cf-ray")
        or ""
    )
    prefix = f"上游图片接口返回 HTTP {status_code}"
    if request_id:
        prefix += f" request_id={request_id}"
    return f"{prefix}: {text}" if text else prefix

def _post_json(url: str, payload: dict, headers: dict[str, str], timeout_seconds: int) -> tuple[int, dict[str, str], bytes]:
    data = _json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "JianYingUtils/0.2 image-material-proxy",
        **headers,
    }
    request = urllib.request.Request(
        _ensure_http_url(url, "endpoint_url"),
        data=data,
        method="POST",
        headers=request_headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return response.status, dict(response.headers.items()), _read_limited(response, _IMAGE_UPSTREAM_MAX_BODY_BYTES)
    except urllib.error.HTTPError as exc:
        response_headers = dict(exc.headers.items()) if exc.headers else {}
        error_body = exc.read(2048)
        detail = _summarize_upstream_error(exc.code, response_headers, error_body)
        logger.warning("%s", detail)
        raise HTTPException(exc.code, detail) from exc

def _fetch_image_url(url: str, timeout_seconds: int) -> bytes:
    request = urllib.request.Request(
        _ensure_http_url(url, "image url"),
        method="GET",
        headers={
            "Accept": "image/png,image/jpeg,image/webp,image/gif,*/*;q=0.8",
            "User-Agent": "JianYingUtils/0.2 image-material-proxy",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            content_type = response.headers.get("Content-Type", "")
            if content_type and not content_type.lower().startswith("image/"):
                raise HTTPException(415, f"上游图片 URL 返回非图片类型: {content_type}")
            data = _read_limited(response, _IMAGE_MAX_BYTES)
    except urllib.error.HTTPError as exc:
        response_headers = dict(exc.headers.items()) if exc.headers else {}
        detail = _summarize_upstream_error(exc.code, response_headers, exc.read(2048))
        logger.warning("%s", detail)
        raise HTTPException(exc.code, f"上游图片 URL 下载失败: {detail}") from exc
    _detect_image(data)
    return data

def _call_image_generation(body: "ImageGenerateRequest") -> dict:
    payload: dict[str, Any] = dict(body.extra_body or {})
    payload["model"] = body.model
    payload["prompt"] = body.prompt
    if body.response_format:
        payload["response_format"] = body.response_format
    for key in ("quality", "size", "output_format", "output_compression", "n"):
        value = getattr(body, key)
        if value is not None:
            payload[key] = value

    headers: dict[str, str] = {}
    if body.api_key:
        header_name = (body.api_key_header or "Authorization").strip() or "Authorization"
        if header_name.lower() == "authorization":
            headers[header_name] = f"Bearer {body.api_key}"
        else:
            headers[header_name] = body.api_key
    for key, value in (body.headers or {}).items():
        if value is not None:
            headers[str(key)] = str(value)

    retries = max(0, min(body.max_retries, 5))
    timeout_seconds = max(1, min(body.timeout_seconds, 3600))
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        try:
            status, response_headers, response_body = _post_json(
                body.endpoint_url,
                payload,
                headers,
                timeout_seconds,
            )
            try:
                upstream_json = _json.loads(response_body.decode("utf-8"))
            except UnicodeDecodeError as exc:
                raise HTTPException(502, "上游图片接口返回了非 UTF-8 JSON") from exc
            except _json.JSONDecodeError as exc:
                raise HTTPException(502, f"上游图片接口返回了无效 JSON: {response_body[:300]!r}") from exc

            images = upstream_json.get("data") or []
            if not images or not isinstance(images, list):
                raise HTTPException(502, "上游图片接口响应缺少 data[0]")
            first = images[0] or {}
            if not isinstance(first, dict):
                raise HTTPException(502, "上游图片接口 data[0] 格式无效")

            if first.get("b64_json"):
                image_bytes = _decode_b64_json(str(first["b64_json"]))
            elif first.get("url"):
                image_bytes = _fetch_image_url(str(first["url"]), timeout_seconds)
            else:
                raise HTTPException(502, "上游图片接口响应缺少 b64_json 或 url")

            result = _save_image_bytes(image_bytes, body.filename)
            normalized_headers = {str(k).lower(): str(v) for k, v in response_headers.items()}
            result.update(
                image_url=result.get("static_url") or result.get("download_url", ""),
                upstream_status=status,
                upstream_request_id=(
                    normalized_headers.get("x-request-id")
                    or normalized_headers.get("x-client-request-id")
                    or normalized_headers.get("cf-ray", "")
                ),
            )
            return result
        except HTTPException:
            raise
        except (TimeoutError, socket.timeout, urllib.error.URLError, IncompleteRead, OSError) as exc:
            last_error = exc
            logger.warning(
                "调用上游图片接口失败，attempt=%d/%d endpoint=%s error=%s",
                attempt + 1,
                retries + 1,
                body.endpoint_url,
                exc,
            )
            if attempt >= retries:
                break

    raise HTTPException(502, f"调用上游图片接口失败: {last_error}") from last_error

# ═══════════════════════════════════════════════════════════════════════════
# Models
# ═══════════════════════════════════════════════════════════════════════════

TIME_VALUE_DESC = (
    "时间值。剪映内部单位为微秒（μs），1 秒 = 1,000,000 微秒。"
    "传数字或纯数字字符串时按微秒处理，例如 5000000 表示 5 秒；"
    "也可传带单位字符串，例如 \"0.5s\"、\"5s\"、\"1m30s\"、\"1h2m3s\"。"
)
START_TIME_DESC = f"片段在时间线上的起始时间。{TIME_VALUE_DESC}"
DURATION_TIME_DESC = f"持续时长，不是结束时间。{TIME_VALUE_DESC}"
END_TIME_US_DESC = "结束时间，单位微秒（μs）。注意这是绝对结束时间，不是持续时长；持续时长 = end - start。"
START_TIME_US_DESC = "起始时间，单位微秒（μs）。1 秒 = 1,000,000 微秒。"
TIME_OFFSET_DESC = f"相对片段起点的时间偏移。{TIME_VALUE_DESC}"

class DraftCreate(BaseModel):
    width: int = Field(1920, description="视频宽度（像素）")
    height: int = Field(1080, description="视频高度（像素）")
    fps: int = Field(30, description="帧率")
    name: str = Field("", description="草稿名称（可选，不填则自动生成）")

class TrackAdd(BaseModel):
    track_type: str = Field(..., description="轨道类型: video / audio / text / effect / filter / sticker")
    track_name: Optional[str] = Field(None, description="轨道名称（同类型多条时必填）")
    mute: bool = Field(False, description="是否静音")
    relative_index: int = Field(0, description="相对图层位置，越大越靠前")

class VideoAdd(BaseModel):
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "video_path": "https://example.com/image.png",
                    "start": "0s",
                    "duration": "5s",
                    "track_name": "main"
                },
                {
                    "video_path": "D:/materials/clip.mp4",
                    "start": 5000000,
                    "duration": 3000000
                }
            ]
        }
    }

    video_path: str = Field(..., description="视频/图片文件路径或远程 URL")
    start: Union[str, int] = Field(..., description=START_TIME_DESC, examples=["0s", 0, 5000000])
    duration: Optional[Union[str, int]] = Field(None, description=f"{DURATION_TIME_DESC}不填则自动根据素材时长计算。", examples=["5s", 5000000])
    speed: float = Field(1.0, description="播放速度")
    volume: float = Field(1.0, description="音量")
    alpha: Optional[float] = Field(None, description="不透明度 0~1")
    transform_x: Optional[float] = Field(None, description="X 位移")
    transform_y: Optional[float] = Field(None, description="Y 位移")
    scale_x: Optional[float] = Field(None, description="X 缩放")
    scale_y: Optional[float] = Field(None, description="Y 缩放")
    clip_settings: Optional[Dict[str, Any]] = Field(None, description="图像调节设置")
    round_corner: Optional[float] = Field(None, description="剪映原生圆角 0~100，8 会写入 0.08")
    glow_outline: Optional[Union[Dict[str, Any], bool]] = Field(
        None,
        description="剪映发光描边，如 {\"color\":\"#000000\",\"size\":10}；true 使用黑色大小 10"
    )
    effects: Optional[List[Dict[str, Any]]] = Field(None, description="片段级视频特效列表")
    filters: Optional[List[Dict[str, Any]]] = Field(None, description="片段级滤镜列表")
    mask: Optional[Dict[str, Any]] = Field(None, description="片段级蒙版设置")
    background_filling: Optional[Dict[str, Any]] = Field(None, description="片段背景填充设置")
    mix_mode: Optional[str] = Field(None, description="混合模式名称")
    track_name: Optional[str] = Field(None, description="目标轨道名称")

class VideoBatch(BaseModel):
    video_infos: List[Dict[str, Any]] = Field(
        ...,
        description=(
            "视频/图片信息列表。每项至少包含 video_path、start、end；"
            "start/end 为微秒（μs），end 是绝对结束时间，不是持续时长。"
            "示例：[{\"video_path\":\"/path/a.png\",\"start\":0,\"end\":5000000}]。"
        ),
    )
    track_name: Optional[str] = Field(None, description="目标轨道名称")

class AudioAdd(BaseModel):
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "audio_path": "https://example.com/audio.mp3",
                    "start": "0s",
                    "duration": "5s",
                    "volume": 0.8
                },
                {
                    "audio_path": "D:/materials/bgm.mp3",
                    "start": 5000000,
                    "duration": 3000000
                }
            ]
        }
    }

    audio_path: str = Field(..., description="音频文件路径或远程 URL")
    start: Union[str, int] = Field(..., description=START_TIME_DESC, examples=["0s", 0, 5000000])
    duration: Optional[Union[str, int]] = Field(None, description=f"{DURATION_TIME_DESC}不填则使用素材全长。", examples=["5s", 5000000])
    speed: float = Field(1.0, description="播放速度")
    volume: float = Field(1.0, description="音量")
    track_name: Optional[str] = Field(None, description="目标轨道名称")

class AudioBatch(BaseModel):
    audio_infos: List[Dict[str, Any]] = Field(
        ...,
        description=(
            "音频信息列表。每项至少包含 audio_path、start、end；"
            "start/end 为微秒（μs），end 是绝对结束时间，不是持续时长。"
            "示例：[{\"audio_path\":\"/path/a.mp3\",\"start\":0,\"end\":5000000}]。"
        ),
    )
    track_name: Optional[str] = Field(None, description="目标轨道名称")

class CaptionItem(BaseModel):
    text: str = Field(..., description="字幕文本")
    start: int = Field(..., description=START_TIME_US_DESC, examples=[0])
    end: int = Field(..., description=END_TIME_US_DESC, examples=[5000000])

class TextAdd(BaseModel):
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "text": "标题文本",
                    "start": "0s",
                    "duration": "3s",
                    "font_size": 10,
                    "text_color": "#FFFFFF",
                    "text_gradient": {
                        "colors": ["#FFBF17", "#2D5094"],
                        "alphas": [1, 1],
                        "percents": [0.949115, 0.283923],
                        "angle": 0,
                        "mode": "all"
                    }
                }
            ]
        }
    }

    text: str = Field(..., description="文本内容")
    start: Union[str, int] = Field(..., description=START_TIME_DESC, examples=["0s", 0])
    duration: Union[str, int] = Field(..., description=DURATION_TIME_DESC, examples=["3s", 3000000])
    font: Optional[str] = Field(None, description="字体名称")
    font_size: float = Field(8.0, description="字体大小")
    text_color: str = Field("#FFFFFF", description="文字颜色 #RRGGBB")
    text_gradient: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "文字渐变填充设置，优先于 text_color。"
            "示例: {\"colors\":[\"#FFBF17\",\"#2D5094\"],"
            "\"alphas\":[1,1],\"percents\":[0.949115,0.283923],"
            "\"angle\":0,\"mode\":\"all\"}"
        ),
    )
    alpha: float = Field(1.0, description="不透明度 0~1")
    bold: bool = Field(False, description="加粗")
    italic: bool = Field(False, description="斜体")
    underline: bool = Field(False, description="下划线")
    alignment: int = Field(0, description="对齐: 0=左 1=中 2=右")
    vertical: bool = Field(False, description="竖排文本")
    letter_spacing: int = Field(0, description="字符间距")
    line_spacing: int = Field(0, description="行间距")
    border: Optional[Dict[str, Any]] = Field(None, description="描边设置")
    background: Optional[Dict[str, Any]] = Field(None, description="背景设置")
    shadow: Optional[Dict[str, Any]] = Field(None, description="阴影设置")
    clip_settings: Optional[Dict[str, Any]] = Field(None, description="图像调节")
    track_name: Optional[str] = Field(None, description="目标轨道名称")

class CaptionsAdd(BaseModel):
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "captions": [
                        {"text": "第一句字幕", "start": 0, "end": 2500000},
                        {"text": "第二句字幕", "start": 2500000, "end": 5000000}
                    ],
                    "font_size": 5,
                    "text_color": "#FFFFFF",
                    "text_gradient": {
                        "colors": ["#FFBF17", "#2D5094"],
                        "alphas": [1, 1],
                        "percents": [0.949115, 0.283923],
                        "angle": 0,
                        "mode": "all"
                    }
                }
            ]
        }
    }

    captions: List[CaptionItem] = Field(..., description="字幕列表")
    font: Optional[str] = Field(None, description="字体名称")
    font_size: float = Field(5.0, description="字体大小")
    text_color: str = Field("#FFFFFF", description="文字颜色")
    text_gradient: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "文字渐变填充设置，优先于 text_color。"
            "示例: {\"colors\":[\"#FFBF17\",\"#2D5094\"],"
            "\"alphas\":[1,1],\"percents\":[0.949115,0.283923],"
            "\"angle\":0,\"mode\":\"all\"}"
        ),
    )
    alpha: float = Field(1.0, description="不透明度")
    bold: bool = Field(False, description="加粗")
    italic: bool = Field(False, description="斜体")
    underline: bool = Field(False, description="下划线")
    alignment: int = Field(1, description="对齐方式: 0=左 1=中 2=右")
    letter_spacing: int = Field(0, description="字符间距")
    line_spacing: int = Field(0, description="行间距")
    line_max_width: float = Field(0.82, description="最大行宽比例")
    auto_wrapping: bool = Field(True, description="自动换行")
    border: Optional[Dict[str, Any]] = Field(None, description="描边设置")
    background: Optional[Dict[str, Any]] = Field(None, description="背景设置")
    shadow: Optional[Dict[str, Any]] = Field(None, description="阴影设置")
    clip_settings: Optional[Dict[str, Any]] = Field(None, description="图像调节")
    track_name: Optional[str] = Field(None, description="目标轨道名称")
    has_shadow: bool = Field(False, description="启用阴影")

class EffectAdd(BaseModel):
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "effect_name": "金粉",
                    "start": "0s",
                    "duration": "3s",
                    "params": [50]
                }
            ]
        }
    }

    effect_name: str = Field(..., description="特效名称")
    start: Union[str, int] = Field(..., description=START_TIME_DESC, examples=["0s", 0])
    duration: Union[str, int] = Field(..., description=DURATION_TIME_DESC, examples=["3s", 3000000])
    params: Optional[List[float]] = Field(None, description="特效参数 0~100")
    track_name: Optional[str] = Field(None, description="特效轨道名称")

class EffectBatch(BaseModel):
    effect_infos: List[Dict[str, Any]] = Field(..., description=f"特效列表。每项中的 start、duration 均遵循：{TIME_VALUE_DESC}")
    track_name: Optional[str] = Field(None, description="特效轨道名称")

class FilterAdd(BaseModel):
    filter_name: str = Field(..., description="滤镜名称")
    start: Union[str, int] = Field(..., description=START_TIME_DESC, examples=["0s", 0])
    duration: Union[str, int] = Field(..., description=DURATION_TIME_DESC, examples=["3s", 3000000])
    intensity: float = Field(100.0, description="滤镜强度 0~100")
    track_name: Optional[str] = Field(None, description="滤镜轨道名称")

class StickerAdd(BaseModel):
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "resource_id": "sticker_resource_id",
                    "start": "1s",
                    "duration": "2s",
                    "transform_x": 0,
                    "transform_y": 0,
                    "scale_x": 1,
                    "scale_y": 1
                }
            ]
        }
    }

    resource_id: str = Field(..., description="贴纸资源 ID")
    start: Union[str, int] = Field(..., description=START_TIME_DESC, examples=["0s", 0])
    duration: Union[str, int] = Field(..., description=DURATION_TIME_DESC, examples=["3s", 3000000])
    transform_x: float = Field(0.0, description="X 位移")
    transform_y: float = Field(0.0, description="Y 位移")
    scale_x: float = Field(1.0, description="X 缩放")
    scale_y: float = Field(1.0, description="Y 缩放")
    alpha: float = Field(1.0, description="不透明度")
    rotation: float = Field(0.0, description="旋转角度")
    track_name: Optional[str] = Field(None, description="目标轨道名称")

class AnimationAdd(BaseModel):
    segment_id: str = Field(..., description="片段 ID")
    animation_name: str = Field(..., description="动画名称")
    duration: Optional[Union[str, int]] = Field(None, description=f"动画持续时长。{DURATION_TIME_DESC}不填则使用动画默认值。", examples=["0.5s", 500000])

class KeyframeAdd(BaseModel):
    segment_id: str = Field(..., description="片段 ID")
    property_name: str = Field(..., description="属性名称")
    time_offset: Union[str, int] = Field(..., description=TIME_OFFSET_DESC, examples=["0.5s", 500000])
    value: float = Field(..., description="属性值")

class KeyframeBatch(BaseModel):
    keyframes: List[Dict[str, Any]] = Field(..., description=f"关键帧列表。每项中的 time_offset 遵循：{TIME_VALUE_DESC}")

class TransitionAdd(BaseModel):
    segment_id: str = Field(..., description="片段 ID")
    transition_name: str = Field(..., description="转场名称")
    duration: Optional[Union[str, int]] = Field(None, description=f"转场持续时长。{DURATION_TIME_DESC}不填则使用转场默认值。", examples=["0.5s", 500000])

class TransitionBatch(BaseModel):
    transitions: List[Dict[str, Any]] = Field(..., description=f"转场列表。每项中的 duration 遵循：{TIME_VALUE_DESC}")

class AudioFade(BaseModel):
    segment_id: str = Field(..., description="片段 ID")
    in_duration: Union[str, int] = Field(..., description=f"淡入持续时长。{DURATION_TIME_DESC}", examples=["0.5s", 500000])
    out_duration: Union[str, int] = Field(..., description=f"淡出持续时长。{DURATION_TIME_DESC}", examples=["0.5s", 500000])

class TimeParse(BaseModel):
    model_config = {
        "json_schema_extra": {
            "examples": [
                {"time_input": "5s"},
                {"time_input": "1m30s"},
                {"time_input": 5000000}
            ]
        }
    }

    time_input: Union[str, float, int] = Field(..., description=TIME_VALUE_DESC, examples=["5s", "1m30s", 5000000])

class TimeFormat(BaseModel):
    microseconds: int = Field(..., description="微秒数（μs）。1 秒 = 1,000,000 微秒。", examples=[5000000])

class TTSRequest(BaseModel):
    text: str = Field(..., description="要合成的文本（支持 SSML）")
    voice: str = Field("zh-CN-XiaoxiaoNeural", description="发音人 ShortName")
    rate: str = Field("+0%", description="语速，如 +20% 加快，-10% 减慢")
    pitch: str = Field("+0Hz", description="音调，如 +5Hz 升高，-5Hz 降低")
    output_path: Optional[str] = Field(None, description="输出文件路径（可选）")

class FishProsodyControl(BaseModel):
    speed: float = Field(1.0, description="语速倍率，0.5~2.0")
    volume: float = Field(0.0, description="音量调整 dB")
    normalize_loudness: bool = Field(True, description="是否规范化响度（S2-Pro）")

class FishTTSRequest(BaseModel):
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "text": "Hello! Welcome to Fish Audio. This is my first AI-generated voice.",
                    "model": "s2-pro",
                    "format": "mp3"
                }
            ]
        }
    }

    text: str = Field(..., description="要合成的文本")
    api_key: Optional[str] = Field(None, description="Fish Audio API Key；不传则读取 FISH_API_KEY 环境变量")
    model: str = Field("s2-pro", description="Fish Audio TTS 模型，推荐 s2-pro")
    output_path: Optional[str] = Field(None, description="输出文件路径（可选）")
    reference_id: Optional[Union[str, List[str]]] = Field(None, description="声音模型 ID；多说话人可传 ID 数组")
    temperature: Optional[float] = Field(None, ge=0, le=1, description="表现力控制，默认由 Fish Audio 决定")
    top_p: Optional[float] = Field(None, ge=0, le=1, description="nucleus sampling 多样性")
    prosody: Optional[FishProsodyControl] = Field(None, description="语速、音量和响度控制")
    chunk_length: Optional[int] = Field(None, ge=100, le=300, description="文本分块长度")
    normalize: Optional[bool] = Field(None, description="是否规范化文本")
    format: str = Field("mp3", description="输出格式: wav/pcm/mp3/opus")
    sample_rate: Optional[int] = Field(None, description="采样率 Hz")
    mp3_bitrate: Optional[int] = Field(None, description="MP3 码率 kbps: 64/128/192")
    opus_bitrate: Optional[int] = Field(None, description="Opus 码率 bps: -1000/24000/32000/48000/64000")
    latency: Optional[str] = Field(None, description="延迟质量模式: low/normal/balanced")
    max_new_tokens: Optional[int] = Field(None, description="每个文本块生成的最大音频 token")
    repetition_penalty: Optional[float] = Field(None, description="重复惩罚，默认 1.2")
    min_chunk_length: Optional[int] = Field(None, ge=0, le=100, description="最小分块字符数")
    condition_on_previous_chunks: Optional[bool] = Field(None, description="是否使用前文音频作为上下文")
    early_stop_threshold: Optional[float] = Field(None, ge=0, le=1, description="批处理早停阈值")

class ImageB64SaveRequest(BaseModel):
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "b64_json": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB...",
                    "filename": "generated-cover.png"
                }
            ]
        }
    }

    b64_json: str = Field(..., description="Base64 图片数据，可传纯 b64_json 或 data URL")
    filename: Optional[str] = Field(None, description="期望文件名；服务端会清理路径并按真实图片类型修正扩展名")

class ImageB64ChunkSaveRequest(BaseModel):
    upload_id: str = Field(..., description="分片上传 ID，同一张图片保持一致")
    index: int = Field(..., description="当前分片序号，从 0 开始")
    total: int = Field(..., description="分片总数")
    chunk: str = Field(..., description="当前 Base64 文本分片")
    filename: Optional[str] = Field(None, description="期望文件名；仅最后一个分片用于保存结果")

class ImageGenerateRequest(BaseModel):
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "endpoint_url": "https://example.com/v1/images/generations",
                    "api_key": "sk-...",
                    "model": "gpt-image-2",
                    "prompt": "手绘插画风格的心理学短视频分镜",
                    "response_format": "b64_json",
                    "quality": "low",
                    "size": "1024x576",
                    "output_format": "webp",
                    "output_compression": 70,
                    "filename": "storyboard-01",
                    "timeout_seconds": 900,
                    "max_retries": 2,
                }
            ]
        }
    }

    endpoint_url: str = Field(..., description="OpenAI 兼容图片生成接口 URL，例如 https://host/v1/images/generations")
    api_key: Optional[str] = Field(None, description="上游图片接口 API key")
    api_key_header: str = Field("Authorization", description="API key 请求头。Authorization 会自动加 Bearer，其它值如 x-api-key 会原样发送 key")
    model: str = Field("gpt-image-2", description="图片模型名称")
    prompt: str = Field(..., description="图片生成提示词")
    response_format: Optional[str] = Field("b64_json", description="上游返回格式，支持 b64_json 或 url；置空则不发送")
    quality: Optional[str] = Field("low", description="图片质量")
    size: Optional[str] = Field("1024x576", description="图片尺寸")
    output_format: Optional[str] = Field("webp", description="输出格式")
    output_compression: Optional[int] = Field(70, description="输出压缩质量")
    n: Optional[int] = Field(None, description="生成数量；本端点只保存第一张")
    filename: Optional[str] = Field(None, description="期望文件名；服务端会清理路径并按真实图片类型修正扩展名")
    timeout_seconds: int = Field(900, description="单次上游请求超时秒数，最大 3600")
    max_retries: int = Field(2, description="上游网络失败重试次数，最大 5")
    headers: Optional[Dict[str, str]] = Field(None, description="额外上游请求头")
    extra_body: Optional[Dict[str, Any]] = Field(None, description="透传给上游的额外 JSON 字段")

class TTSVoiceItem(BaseModel):
    ShortName: str = Field(..., description="发音人标识")
    DisplayName: str = Field(..., description="显示名称")
    Gender: str = Field(..., description="性别")
    Style: str = Field(..., description="风格描述")

class TTSSynthesizeResponse(BaseModel):
    success: bool = Field(True, description="操作是否成功")
    message: str = Field("", description="操作结果消息")
    audio_path: str = Field("", description="音频文件路径")
    download_url: str = Field("", description="音频下载 URL")
    duration_seconds: float = Field(0.0, description="合成耗时（秒）")
    voice: str = Field("", description="使用的发音人")
    provider: str = Field("", description="TTS 服务提供方")
    model: str = Field("", description="使用的模型")
    format: str = Field("", description="音频格式")

class ImageSaveResponse(BaseModel):
    success: bool = Field(True, description="操作是否成功")
    message: str = Field("", description="操作结果消息")
    filename: str = Field("", description="保存后的文件名")
    file_path: str = Field("", description="服务端本地文件路径")
    download_url: str = Field("", description="图片下载 URL")
    static_url: str = Field("", description="可直接作为素材路径使用的静态 URL")
    media_type: str = Field("", description="图片 MIME 类型")
    size: int = Field(0, description="图片字节数")
    sha256: str = Field("", description="图片内容 SHA256")

class SoundEffectItem(BaseModel):
    name: str = Field("", description="音效展示名称（不含扩展名）")
    filename: str = Field("", description="音效文件名")
    relative_path: str = Field("", description="相对项目根目录的路径")
    file_path: str = Field("", description="服务端本地文件路径")
    static_url: str = Field("", description="可直接作为素材路径使用的静态 URL")
    audio_path: str = Field("", description="推荐传给音频接口的音频路径")
    media_type: str = Field("", description="音频 MIME 类型")
    size: int = Field(0, description="音频字节数")
    sha256: str = Field("", description="音频内容 SHA256")

class SoundEffectListResponse(BaseModel):
    success: bool = Field(True, description="操作是否成功")
    message: str = Field("", description="操作结果消息")
    sound_effects: List[SoundEffectItem] = Field(default_factory=list, description="音效文件列表")
    items: List[SoundEffectItem] = Field(default_factory=list, description="音效文件列表别名")
    count: int = Field(0, description="音效文件数量")

class ImageGenerateResponse(ImageSaveResponse):
    image_url: str = Field("", description="推荐传给剪映后续素材接口的图片 URL")
    upstream_status: int = Field(0, description="上游图片接口 HTTP 状态码")
    upstream_request_id: str = Field("", description="上游响应 request id（如果有）")

class TTSVoicesResponse(BaseModel):
    success: bool = Field(True, description="操作是否成功")
    message: str = Field("", description="操作结果消息")
    voices: List[TTSVoiceItem] = Field(default_factory=list, description="发音人列表")
    count: int = Field(0, description="发音人数量")

class SimpleWorkflow(BaseModel):
    width: int = Field(1920, description="视频宽度")
    height: int = Field(1080, description="视频高度")
    captions: List[CaptionItem] = Field(default_factory=list, description="字幕列表")
    title_text: Optional[str] = Field(None, description="标题文本")
    video_path: Optional[str] = Field(None, description="视频文件路径")
    audio_path: Optional[str] = Field(None, description="音频文件路径")

# ═══════════════════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════════════════

class HealthResponse(BaseModel):
    success: bool = Field(True, description="操作是否成功")
    status: str = Field("ok", description="服务状态")
    version: str = Field(..., description="API 版本号")
    drafts_dir: str = Field(..., description="草稿存储目录")
    active_drafts: int = Field(..., description="当前活跃草稿数")

class DraftItem(BaseModel):
    draft_id: str = Field(..., description="草稿唯一 ID")
    draft_name: str = Field(..., description="草稿名称")
    draft_folder: str = Field(..., description="草稿文件夹路径")

class DraftCreateResponse(BaseModel):
    success: bool = Field(True, description="操作是否成功")
    message: str = Field("", description="操作结果消息")
    draft_id: str = Field(..., description="草稿唯一 ID（12 位 hex）")
    draft_name: str = Field(..., description="草稿名称")
    draft_folder: str = Field(..., description="草稿文件夹路径")
    script_path: str = Field(..., description="草稿脚本文件路径")
    download_url: str = Field("", description="草稿文件下载 URL")

class DraftsListResponse(BaseModel):
    success: bool = Field(True, description="操作是否成功")
    message: str = Field("", description="操作结果消息")
    drafts: List[DraftItem] = Field(default_factory=list, description="草稿列表")
    count: int = Field(0, description="草稿总数")

class DraftInfoResponse(BaseModel):
    success: bool = Field(True, description="操作是否成功")
    message: str = Field("", description="操作结果消息")
    draft_folder: str = Field("", description="草稿文件夹路径")
    draft_name: str = Field("", description="草稿名称")
    script_path: str = Field("", description="草稿脚本文件路径")
    width: int = Field(0, description="视频宽度")
    height: int = Field(0, description="视频高度")
    fps: int = Field(0, description="帧率")
    duration: int = Field(0, description="草稿总时长（微秒）")
    download_url: str = Field("", description="草稿文件下载 URL")

class DraftSaveResponse(BaseModel):
    success: bool = Field(True, description="操作是否成功")
    message: str = Field("", description="操作结果消息")
    script_path: str = Field("", description="保存后的脚本文件路径")
    download_url: str = Field("", description="草稿文件下载 URL")

class DraftExportResponse(BaseModel):
    success: bool = Field(True, description="操作是否成功")
    message: str = Field("", description="操作结果消息")
    json_string: str = Field("", description="草稿 JSON 字符串")
    draft_name: str = Field("", description="草稿名称")

class GenericSuccessResponse(BaseModel):
    success: bool = Field(True, description="操作是否成功")
    message: str = Field("", description="操作结果消息")

class TrackItem(BaseModel):
    name: str = Field(..., description="轨道名称")
    type: str = Field(..., description="轨道类型")
    render_index: int = Field(..., description="渲染层级")
    mute: bool = Field(False, description="是否静音")
    segment_count: int = Field(0, description="片段数量")
    source: Optional[str] = Field(None, description="来源标识（imported=导入轨道）")

class TrackAddResponse(BaseModel):
    success: bool = Field(True, description="操作是否成功")
    message: str = Field("", description="操作结果消息")
    track_type: str = Field("", description="轨道类型")
    track_name: str = Field("", description="轨道名称")

class TrackListResponse(BaseModel):
    success: bool = Field(True, description="操作是否成功")
    message: str = Field("", description="操作结果消息")
    tracks: List[TrackItem] = Field(default_factory=list, description="轨道列表")

class SegmentResponse(BaseModel):
    success: bool = Field(True, description="操作是否成功")
    message: str = Field("", description="操作结果消息")
    segment_id: str = Field("", description="新创建片段的 ID")

class BatchResponse(BaseModel):
    success: bool = Field(True, description="操作是否成功")
    message: str = Field("", description="操作结果消息")
    count: int = Field(0, description="添加的片段数量")
    segment_ids: List[str] = Field(default_factory=list, description="新创建片段的 ID 列表")

class SimpleWorkflowResponse(BaseModel):
    success: bool = Field(True, description="操作是否成功")
    message: str = Field("", description="操作结果消息")
    duration: int = Field(0, description="草稿总时长（微秒）")
    duration_seconds: float = Field(0.0, description="草稿总时长（秒）")

class MetadataParamItem(BaseModel):
    name: str = Field(..., description="参数名称")
    default: float = Field(0.0, description="默认值")
    min: float = Field(0.0, description="最小值")
    max: float = Field(0.0, description="最大值")

class MetadataItem(BaseModel):
    name: str = Field(..., description="内部名称")
    display_name: str = Field(..., description="显示名称")
    is_vip: bool = Field(False, description="是否 VIP")
    resource_id: str = Field("", description="资源 ID")
    effect_id: str = Field("", description="效果 ID")
    duration_us: Optional[int] = Field(None, description="持续时间（微秒，动画类）")
    duration_seconds: Optional[float] = Field(None, description="持续时间（秒，动画类）")
    params: Optional[List[MetadataParamItem]] = Field(None, description="参数列表")

class MetadataListResponse(BaseModel):
    success: bool = Field(True, description="操作是否成功")
    message: str = Field("", description="操作结果消息")
    items: List[MetadataItem] = Field(default_factory=list, description="元数据项列表")
    count: int = Field(0, description="总数")

class MaterialVideoInfoResponse(BaseModel):
    success: bool = Field(True, description="操作是否成功")
    message: str = Field("", description="操作结果消息")
    duration: int = Field(0, description="时长（微秒）")
    width: int = Field(0, description="视频宽度")
    height: int = Field(0, description="视频高度")
    type: str = Field("", description="素材类型（video/image）")
    material_name: str = Field("", description="素材文件名")
    path: str = Field("", description="素材文件路径")

class MaterialAudioDurationResponse(BaseModel):
    success: bool = Field(True, description="操作是否成功")
    message: str = Field("", description="操作结果消息")
    duration: int = Field(0, description="音频时长（微秒）")
    duration_seconds: float = Field(0.0, description="音频时长（秒）")
    material_name: str = Field("", description="素材文件名")
    path: str = Field("", description="素材文件路径")

class TimeParseResponse(BaseModel):
    success: bool = Field(True, description="操作是否成功")
    message: str = Field("", description="操作结果消息")
    microseconds: int = Field(..., description="解析后的微秒数")

class TimeFormatResponse(BaseModel):
    success: bool = Field(True, description="操作是否成功")
    message: str = Field("", description="操作结果消息")
    formatted: str = Field(..., description="格式化后的时间字符串")

# ═══════════════════════════════════════════════════════════════════════════
# 系统
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/health", tags=["系统"], summary="健康检查", response_model=HealthResponse)
def health():
    """检查服务运行状态"""
    merged = {**_load_disk_registry(), **_draft_registry}
    return {"success": True, "status": "ok", "version": "0.2.0", "drafts_dir": DRAFTS_DIR,
            "active_drafts": len(merged)}

# ═══════════════════════════════════════════════════════════════════════════
# 草稿管理
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/drafts", tags=["草稿管理"], summary="创建草稿", response_model=DraftCreateResponse)
def create_draft(body: DraftCreate):
    """创建新草稿，返回 draft_id 供后续所有操作使用"""
    draft_id = uuid.uuid4().hex[:12]
    name = body.name or draft_id
    result = DraftManager.create_draft(
        DRAFTS_DIR, name, body.width, body.height, body.fps, allow_replace=True
    )
    if not result["success"]:
        logger.error("创建草稿失败: draft_name=%s reason=%s", name, result["message"])
        raise HTTPException(500, result["message"])
    _draft_registry[draft_id] = (DRAFTS_DIR, name)
    # 同步到磁盘（供其他 worker 查找）
    _save_disk_registry({**_load_disk_registry(), draft_id: [DRAFTS_DIR, name]})
    logger.info("草稿已创建: draft_id=%s draft_name=%s", draft_id, name)
    return _ok(draft_id=draft_id, draft_name=name,
               draft_folder=result.get("draft_folder"),
               script_path=result.get("script_path"),
               download_url=f"{DEPLOY_URL}/drafts/{draft_id}/download")

@app.get("/drafts", tags=["草稿管理"], summary="列出所有草稿", response_model=DraftsListResponse)
def list_drafts():
    """列出当前活跃的所有草稿（含其他 worker 创建的）"""
    # 合并磁盘注册表
    merged = {**_load_disk_registry(), **_draft_registry}
    items = [{"draft_id": did, "draft_name": name,
              "draft_folder": os.path.join(folder, name)}
             for did, (folder, name) in merged.items()]
    return _ok(drafts=items, count=len(items))

@app.get("/drafts/{draft_id}", tags=["草稿管理"], summary="获取草稿信息", response_model=DraftInfoResponse)
def get_draft(draft_id: str):
    """查看指定草稿的基本信息（尺寸、时长等）"""
    folder, name = _resolve(draft_id)
    result = DraftManager.load_draft(folder, name)
    result["download_url"] = f"{DEPLOY_URL}/drafts/{draft_id}/download"
    return result

@app.delete("/drafts/{draft_id}", tags=["草稿管理"], summary="删除草稿", response_model=GenericSuccessResponse)
def delete_draft(draft_id: str):
    """删除指定草稿及其文件"""
    folder, name = _resolve(draft_id)
    result = DraftManager.remove_draft(folder, name)
    _draft_registry.pop(draft_id, None)
    # 同步磁盘
    disk = _load_disk_registry()
    disk.pop(draft_id, None)
    _save_disk_registry(disk)
    _context.clear_session(folder, name)
    if result["success"]:
        logger.info("草稿已删除: draft_id=%s draft_name=%s", draft_id, name)
    else:
        logger.warning("删除草稿失败: draft_id=%s reason=%s", draft_id, result["message"])
    return result

@app.post("/drafts/{draft_id}/save", tags=["草稿管理"], summary="保存草稿", response_model=DraftSaveResponse)
def save_draft(draft_id: str):
    """将草稿写入磁盘，返回下载 URL"""
    folder, name = _resolve(draft_id)
    result = DraftManager.save_draft(folder, name)
    result["download_url"] = f"{DEPLOY_URL}/drafts/{draft_id}/download"
    return result

@app.post("/drafts/{draft_id}/export", tags=["草稿管理"], summary="导出草稿 JSON", response_model=DraftExportResponse)
def export_draft(draft_id: str):
    """导出草稿为 JSON 字符串"""
    folder, name = _resolve(draft_id)
    return ExportTool.dumps_to_string(folder, name)

@app.get("/drafts/{draft_id}/download", tags=["草稿管理"], summary="下载草稿文件(ZIP)")
def download_draft(draft_id: str):
    """下载占位符无关的便携草稿 ZIP 包（含 JSON + 所有关联素材文件）。"""
    folder, name = _resolve(draft_id)
    script_path = os.path.join(folder, name, "draft_content.json")
    if not os.path.isfile(script_path):
        raise HTTPException(404, f"草稿文件不存在，请先调用 POST /drafts/{draft_id}/save")

    # 下载前仍确保素材文件已被复制到 audio/ / video/ / image/ 子目录；
    # ZIP 内的 JSON 会被转换为相对路径，不泄漏服务端/本机占位符。
    _context.normalize_draft_media_paths(script_path)

    # 构建 ZIP
    buf = io.BytesIO()
    draft_dir = os.path.dirname(script_path)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(draft_dir):
            for fname in files:
                if fname == ".draft_path_placeholder":
                    continue
                fp = os.path.join(root, fname)
                arcname = os.path.relpath(fp, draft_dir).replace("\\", "/")
                if _is_draft_json_file(fname):
                    zf.writestr(arcname, _portable_json_file(fp, draft_dir, name))
                else:
                    zf.write(fp, arcname)

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}.zip"'}
    )


_DRAFT_PLACEHOLDER_RE = re.compile(r"^##_draftpath_placeholder_[^#]+_##[/\\](.+)$")


def _is_draft_json_file(filename: str) -> bool:
    return (
        filename in {
            "draft_content.json",
            "draft_info.json",
            "draft_meta_info.json",
            "attachment_pc_common.json",
            "draft_agency_config.json",
        }
        or filename.startswith("template")
        and filename.endswith(".tmp")
    )


def _portable_json_file(path: str, draft_dir: str, draft_name: str) -> str:
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = _json.load(f)
    except Exception:
        logger.debug("草稿 JSON 解析失败，按原始文本打包: %s", path, exc_info=True)
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    data = _make_portable_json(data, draft_dir, draft_name)
    return _json.dumps(data, ensure_ascii=False, indent=4)


def _make_portable_json(obj: Any, draft_dir: str, draft_name: str) -> Any:
    if isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            if key in {"draft_fold_path", "draft_root_path"} and isinstance(value, str):
                result[key] = ""
            elif key == "draft_name" and isinstance(value, str):
                result[key] = draft_name
            elif key == "name" and isinstance(value, str) and not value:
                result[key] = draft_name
            else:
                result[key] = _make_portable_json(value, draft_dir, draft_name)
        return result
    if isinstance(obj, list):
        return [_make_portable_json(value, draft_dir, draft_name) for value in obj]
    if isinstance(obj, str):
        return _portable_material_path(obj, draft_dir)
    return obj


def _portable_material_path(value: str, draft_dir: str) -> str:
    match = _DRAFT_PLACEHOLDER_RE.match(value.replace("\\", "/"))
    if match:
        return match.group(1).replace("\\", "/")

    if os.path.isabs(value):
        try:
            rel = os.path.relpath(value, draft_dir)
        except ValueError:
            return value
        if not rel.startswith(".."):
            return rel.replace("\\", "/")
    return value

# ═══════════════════════════════════════════════════════════════════════════
# 轨道
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/drafts/{draft_id}/tracks", tags=["轨道"], summary="添加轨道", response_model=TrackAddResponse)
def add_track(draft_id: str, body: TrackAdd):
    """向草稿添加一条轨道"""
    folder, name = _resolve(draft_id)
    return TrackManager.add_track(folder, name, body.track_type, body.track_name,
                                  mute=body.mute, relative_index=body.relative_index)

@app.get("/drafts/{draft_id}/tracks", tags=["轨道"], summary="列出轨道", response_model=TrackListResponse)
def list_tracks(draft_id: str):
    """列出草稿中所有轨道"""
    folder, name = _resolve(draft_id)
    return TrackManager.list_tracks(folder, name)

# ═══════════════════════════════════════════════════════════════════════════
# 视频
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/drafts/{draft_id}/videos", tags=["视频"], summary="添加视频", response_model=SegmentResponse)
def add_video(draft_id: str, body: VideoAdd):
    """添加单个视频或图片片段"""
    folder, name = _resolve(draft_id)
    d = body.model_dump()
    clip = d.pop("clip_settings", None) or {}
    for k in ("alpha", "transform_x", "transform_y", "scale_x", "scale_y"):
        v = d.pop(k, None)
        if v is not None: clip[k] = v
    if clip: d["clip_settings"] = clip
    del d["video_path"]
    return _return_or_raise(VideoTool.add_video(folder, name, body.video_path, **d))

@app.post("/drafts/{draft_id}/videos/batch", tags=["视频"], summary="批量添加视频", response_model=BatchResponse)
def add_videos_batch(draft_id: str, body: VideoBatch):
    """批量添加视频或图片片段"""
    folder, name = _resolve(draft_id)
    return _return_or_raise(VideoTool.add_videos_batch(folder, name, body.video_infos, body.track_name))

# ═══════════════════════════════════════════════════════════════════════════
# 音频
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/drafts/{draft_id}/audios", tags=["音频"], summary="添加音频", response_model=SegmentResponse)
def add_audio(draft_id: str, body: AudioAdd):
    """添加单个音频片段"""
    folder, name = _resolve(draft_id)
    return AudioTool.add_audio(folder, name, body.audio_path, body.start,
                               body.duration, body.speed, body.volume,
                               track_name=body.track_name)

@app.post("/drafts/{draft_id}/audios/batch", tags=["音频"], summary="批量添加音频", response_model=BatchResponse)
def add_audios_batch(draft_id: str, body: AudioBatch):
    """批量添加音频片段"""
    folder, name = _resolve(draft_id)
    return AudioTool.add_audios_batch(folder, name, body.audio_infos, body.track_name)

@app.post("/drafts/{draft_id}/audios/fade", tags=["音频"], summary="淡入淡出", response_model=GenericSuccessResponse)
def audio_fade(draft_id: str, body: AudioFade):
    """为音频片段添加淡入淡出效果"""
    folder, name = _resolve(draft_id)
    return AudioTool.add_fade(folder, name, body.segment_id, body.in_duration, body.out_duration)

# ═══════════════════════════════════════════════════════════════════════════
# 文本 & 字幕
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/drafts/{draft_id}/texts", tags=["文本"], summary="添加文本", response_model=SegmentResponse)
def add_text(draft_id: str, body: TextAdd):
    """添加单个文本片段（支持描边、背景、阴影等样式）"""
    folder, name = _resolve(draft_id)
    return TextTool.add_text(folder, name, **body.model_dump())

@app.post("/drafts/{draft_id}/captions", tags=["字幕"], summary="批量添加字幕", response_model=BatchResponse)
def add_captions(draft_id: str, body: CaptionsAdd):
    """批量添加字幕片段"""
    folder, name = _resolve(draft_id)
    return TextTool.add_captions_batch(folder, name, **body.model_dump())

# ═══════════════════════════════════════════════════════════════════════════
# 特效 & 滤镜
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/drafts/{draft_id}/effects/scene", tags=["特效"], summary="添加场景特效", response_model=GenericSuccessResponse)
def effect_scene(draft_id: str, body: EffectAdd):
    """向特效轨道添加场景特效"""
    folder, name = _resolve(draft_id)
    return EffectTool.add_scene_effect(folder, name, body.effect_name,
                                       body.start, body.duration, body.params, body.track_name)

@app.post("/drafts/{draft_id}/effects/character", tags=["特效"], summary="添加人物特效", response_model=GenericSuccessResponse)
def effect_character(draft_id: str, body: EffectAdd):
    """向特效轨道添加人物特效"""
    folder, name = _resolve(draft_id)
    return EffectTool.add_character_effect(folder, name, body.effect_name,
                                            body.start, body.duration, body.params, body.track_name)

@app.post("/drafts/{draft_id}/effects/filter", tags=["特效"], summary="添加滤镜", response_model=GenericSuccessResponse)
def effect_filter(draft_id: str, body: FilterAdd):
    """向滤镜轨道添加滤镜"""
    folder, name = _resolve(draft_id)
    return EffectTool.add_filter_track(folder, name, body.filter_name,
                                       body.start, body.duration, body.intensity, body.track_name)

@app.post("/drafts/{draft_id}/effects/batch", tags=["特效"], summary="批量添加特效", response_model=BatchResponse)
def effect_batch(draft_id: str, body: EffectBatch):
    """批量添加视频特效"""
    folder, name = _resolve(draft_id)
    return EffectTool.add_effects_batch(folder, name, body.effect_infos, body.track_name)

# ═══════════════════════════════════════════════════════════════════════════
# 贴纸
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/drafts/{draft_id}/stickers", tags=["贴纸"], summary="添加贴纸", response_model=SegmentResponse)
def add_sticker(draft_id: str, body: StickerAdd):
    """添加贴纸片段"""
    folder, name = _resolve(draft_id)
    return StickerTool.add_sticker(folder, name, **body.model_dump())

# ═══════════════════════════════════════════════════════════════════════════
# 动画
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/drafts/{draft_id}/animations/video-intro", tags=["动画"], summary="视频入场动画", response_model=GenericSuccessResponse)
def anim_video_intro(draft_id: str, body: AnimationAdd):
    """为视频片段添加入场动画"""
    folder, name = _resolve(draft_id)
    return AnimationTool.add_video_intro(folder, name, body.segment_id, body.animation_name, body.duration)

@app.post("/drafts/{draft_id}/animations/video-outro", tags=["动画"], summary="视频出场动画", response_model=GenericSuccessResponse)
def anim_video_outro(draft_id: str, body: AnimationAdd):
    """为视频片段添加出场动画"""
    folder, name = _resolve(draft_id)
    return AnimationTool.add_video_outro(folder, name, body.segment_id, body.animation_name, body.duration)

@app.post("/drafts/{draft_id}/animations/video-group", tags=["动画"], summary="视频组合动画", response_model=GenericSuccessResponse)
def anim_video_group(draft_id: str, body: AnimationAdd):
    """为视频片段添加组合动画"""
    folder, name = _resolve(draft_id)
    return AnimationTool.add_video_group_animation(folder, name, body.segment_id, body.animation_name, body.duration)

@app.post("/drafts/{draft_id}/animations/text-intro", tags=["动画"], summary="文本入场动画", response_model=GenericSuccessResponse)
def anim_text_intro(draft_id: str, body: AnimationAdd):
    """为文本片段添加入场动画"""
    folder, name = _resolve(draft_id)
    return AnimationTool.add_text_intro(folder, name, body.segment_id, body.animation_name, body.duration)

@app.post("/drafts/{draft_id}/animations/text-outro", tags=["动画"], summary="文本出场动画", response_model=GenericSuccessResponse)
def anim_text_outro(draft_id: str, body: AnimationAdd):
    """为文本片段添加出场动画"""
    folder, name = _resolve(draft_id)
    return AnimationTool.add_text_outro(folder, name, body.segment_id, body.animation_name, body.duration)

@app.post("/drafts/{draft_id}/animations/text-loop", tags=["动画"], summary="文本循环动画", response_model=GenericSuccessResponse)
def anim_text_loop(draft_id: str, body: AnimationAdd):
    """为文本片段添加循环动画"""
    folder, name = _resolve(draft_id)
    return AnimationTool.add_text_loop(folder, name, body.segment_id, body.animation_name)

# ═══════════════════════════════════════════════════════════════════════════
# 关键帧
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/drafts/{draft_id}/keyframes", tags=["关键帧"], summary="添加关键帧", response_model=GenericSuccessResponse)
def add_keyframe(draft_id: str, body: KeyframeAdd):
    """为片段属性添加关键帧"""
    folder, name = _resolve(draft_id)
    return KeyframeTool.add_keyframe(folder, name, body.segment_id,
                                     body.property_name, body.time_offset, body.value)

@app.post("/drafts/{draft_id}/keyframes/batch", tags=["关键帧"], summary="批量添加关键帧", response_model=BatchResponse)
def add_keyframes_batch(draft_id: str, body: KeyframeBatch):
    """批量添加关键帧"""
    folder, name = _resolve(draft_id)
    return KeyframeTool.add_keyframes_batch(folder, name, body.keyframes)

# ═══════════════════════════════════════════════════════════════════════════
# 转场
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/drafts/{draft_id}/transitions", tags=["转场"], summary="添加转场", response_model=GenericSuccessResponse)
def add_transition(draft_id: str, body: TransitionAdd):
    """为视频片段添加转场效果"""
    folder, name = _resolve(draft_id)
    return TransitionTool.add_transition(folder, name, body.segment_id,
                                         body.transition_name, body.duration)

@app.post("/drafts/{draft_id}/transitions/batch", tags=["转场"], summary="批量添加转场", response_model=BatchResponse)
def add_transitions_batch(draft_id: str, body: TransitionBatch):
    """批量添加转场效果"""
    folder, name = _resolve(draft_id)
    return TransitionTool.add_transitions_batch(folder, name, body.transitions)

# ═══════════════════════════════════════════════════════════════════════════
# 一键工作流
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/drafts/{draft_id}/workflow/simple", tags=["工作流"], summary="一键创建", response_model=SimpleWorkflowResponse)
def workflow_simple(draft_id: str, body: SimpleWorkflow):
    """一键创建完整草稿内容（视频 + 音频 + 字幕 + 标题）"""
    folder, name = _resolve(draft_id)
    from pyJianYingDraft import (
        DraftFolder, TrackType, TextSegment, VideoSegment, AudioSegment,
        VideoMaterial, AudioMaterial, Timerange, ClipSettings,
        TextStyle, TextBorder, tim
    )
    from jianying_utils.material_path import resolve_material_path

    script = _context.get_script(folder, name)
    if not script:
        folder_obj = DraftFolder(folder)
        script = folder_obj.load_template(name)
        _context.commit_script(script, folder, name)

    video_path = resolve_material_path(body.video_path, ".jpg", "image/*,video/*;q=0.9,*/*;q=0.8") if body.video_path else ""
    if video_path and os.path.exists(video_path):
        script.add_track(TrackType.video)
        mat = create_video_material(video_path)
        script.add_segment(VideoSegment(mat, Timerange(0, mat.duration)))

    audio_path = resolve_material_path(body.audio_path, ".mp3", "audio/mpeg,audio/*;q=0.9,*/*;q=0.8") if body.audio_path else ""
    if audio_path and os.path.exists(audio_path):
        script.add_track(TrackType.audio)
        mat = AudioMaterial(audio_path)
        dur = min(mat.duration, script.duration or mat.duration)
        seg = AudioSegment(mat, Timerange(0, dur), volume=0.5)
        seg.add_fade("1s", "2s")
        script.add_segment(seg)

    if body.captions:
        script.add_track(TrackType.text, "captions")
        style = TextStyle(size=5, bold=True, color=(1, 1, 1), align=1, auto_wrapping=True)
        cs = ClipSettings(transform_y=-0.8)
        for cap in body.captions:
            seg = TextSegment(cap.text, Timerange(cap.start, cap.end - cap.start),
                              style=style, clip_settings=cs)
            script.add_segment(seg, "captions")

    if body.title_text:
        script.add_track(TrackType.text, "title", relative_index=1)
        title_style = TextStyle(size=14, bold=True, color=(1, 0.42, 0.21), align=1)
        title_border = TextBorder(color=(0, 0, 0), width=60)
        title_cs = ClipSettings(transform_y=0.45, scale_x=1.5, scale_y=1.5)
        seg = TextSegment(body.title_text, Timerange(tim("0.5s"), tim("3s")),
                          style=title_style, border=title_border, clip_settings=title_cs)
        script.add_segment(seg, "title")

    _context.commit_script(script, folder, name)
    script.save()
    return _ok(duration=script.duration, duration_seconds=round(script.duration / 1e6, 1))

# ═══════════════════════════════════════════════════════════════════════════
# 元数据查询
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/metadata/transitions", tags=["元数据"], summary="查询转场列表", response_model=MetadataListResponse)
def metadata_transitions(mode: int = 0):
    """查询可用转场（mode: 0=全部 1=VIP 2=免费）"""
    return MetadataQuery.list_transitions(mode)

@app.get("/metadata/filters", tags=["元数据"], summary="查询滤镜列表", response_model=MetadataListResponse)
def metadata_filters(mode: int = 0):
    return MetadataQuery.list_filters(mode)

@app.get("/metadata/fonts", tags=["元数据"], summary="查询字体列表", response_model=MetadataListResponse)
def metadata_fonts(mode: int = 0):
    return MetadataQuery.list_fonts(mode)

@app.get("/metadata/masks", tags=["元数据"], summary="查询蒙版列表", response_model=MetadataListResponse)
def metadata_masks():
    return MetadataQuery.list_masks()

@app.get("/metadata/mix-modes", tags=["元数据"], summary="查询混合模式列表", response_model=MetadataListResponse)
def metadata_mix_modes():
    return MetadataQuery.list_mix_modes()

@app.get("/metadata/video-intros", tags=["元数据"], summary="查询视频入场动画", response_model=MetadataListResponse)
def metadata_video_intros(mode: int = 0):
    return MetadataQuery.list_video_intros(mode)

@app.get("/metadata/video-outros", tags=["元数据"], summary="查询视频出场动画", response_model=MetadataListResponse)
def metadata_video_outros(mode: int = 0):
    return MetadataQuery.list_video_outros(mode)

@app.get("/metadata/video-group-anims", tags=["元数据"], summary="查询视频组合动画", response_model=MetadataListResponse)
def metadata_video_group_anims(mode: int = 0):
    return MetadataQuery.list_video_group_animations(mode)

@app.get("/metadata/text-intros", tags=["元数据"], summary="查询文本入场动画", response_model=MetadataListResponse)
def metadata_text_intros(mode: int = 0):
    return MetadataQuery.list_text_intros(mode)

@app.get("/metadata/text-outros", tags=["元数据"], summary="查询文本出场动画", response_model=MetadataListResponse)
def metadata_text_outros(mode: int = 0):
    return MetadataQuery.list_text_outros(mode)

@app.get("/metadata/text-loop-anims", tags=["元数据"], summary="查询文本循环动画", response_model=MetadataListResponse)
def metadata_text_loop_anims(mode: int = 0):
    return MetadataQuery.list_text_loop_anims(mode)

@app.get("/metadata/scene-effects", tags=["元数据"], summary="查询场景特效列表", response_model=MetadataListResponse)
def metadata_scene_effects(mode: int = 0):
    return MetadataQuery.list_video_scene_effects(mode)

@app.get("/metadata/character-effects", tags=["元数据"], summary="查询人物特效列表", response_model=MetadataListResponse)
def metadata_character_effects(mode: int = 0):
    return MetadataQuery.list_video_character_effects(mode)

@app.get("/metadata/audio-effects", tags=["元数据"], summary="查询音频特效列表", response_model=MetadataListResponse)
def metadata_audio_effects(mode: int = 0):
    return MetadataQuery.list_audio_scene_effects(mode)

# ═══════════════════════════════════════════════════════════════════════════
# 素材工具
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/material/video-info", tags=["素材"], summary="获取视频信息", response_model=MaterialVideoInfoResponse)
def material_video_info(path: str):
    """获取视频/图片素材的尺寸、时长等信息"""
    return MaterialTool.get_video_info(path)

@app.get("/material/audio-duration", tags=["素材"], summary="获取音频时长", response_model=MaterialAudioDurationResponse)
def material_audio_duration(path: str):
    """获取音频文件的时长"""
    return MaterialTool.get_audio_duration(path)

@app.get("/material/sound-effects", tags=["素材"], summary="查询后端内置音效列表", response_model=SoundEffectListResponse)
def material_sound_effects():
    """List audio files under assets/sound_effect for workflow sound prompts."""
    root = Path(_SOUND_EFFECT_DIR)
    if not root.is_dir():
        return _ok(message=f"音效目录不存在: {_SOUND_EFFECT_DIR}", sound_effects=[], items=[], count=0)

    files = sorted(
        (p for p in root.iterdir() if p.is_file() and p.suffix.lower() in _SOUND_EFFECT_EXTS),
        key=lambda p: p.name.lower(),
    )
    sound_effects = [_sound_effect_item(path) for path in files]
    return _ok(message=f"找到 {len(sound_effects)} 个音效", sound_effects=sound_effects, items=sound_effects, count=len(sound_effects))

@app.post("/material/images", tags=["素材"], summary="保存 Base64 图片素材", response_model=ImageSaveResponse)
def material_save_image(body: ImageB64SaveRequest):
    """Decode b64_json image data, save it, and return URLs usable by workflows."""
    data = _decode_b64_json(body.b64_json)
    return _save_image_bytes(data, body.filename)

@app.post("/material/images/generate", tags=["素材"], summary="生成并保存图片素材", response_model=ImageGenerateResponse)
def material_generate_image(body: ImageGenerateRequest):
    """Call an OpenAI-compatible image API server-side, save the image, and return short URLs."""
    return _call_image_generation(body)

@app.post("/material/images/chunks", tags=["素材"], summary="分片保存 Base64 图片素材")
def material_save_image_chunk(body: ImageB64ChunkSaveRequest):
    """Accept small b64_json chunks and save the image after the final chunk."""
    upload_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", body.upload_id or "").strip(".-_")
    if not upload_id:
        raise HTTPException(400, "upload_id 不能为空")
    if body.total <= 0 or body.total > 1000:
        raise HTTPException(400, "total 必须在 1 到 1000 之间")
    if body.index < 0 or body.index >= body.total:
        raise HTTPException(400, "index 超出范围")

    chunk_dir = os.path.abspath(os.path.join(_IMAGE_CHUNK_DIR, upload_id))
    chunk_root = os.path.abspath(_IMAGE_CHUNK_DIR)
    if os.path.commonpath([chunk_root, chunk_dir]) != chunk_root:
        raise HTTPException(400, "无效的 upload_id")
    os.makedirs(chunk_dir, exist_ok=True)

    chunk = "".join(str(body.chunk or "").split())
    if body.index == 0 and chunk.startswith("data:"):
        _, _, chunk = chunk.partition(",")
    if not chunk:
        raise HTTPException(400, "chunk 不能为空")

    chunk_path = os.path.join(chunk_dir, f"{body.index:06d}.part")
    with open(chunk_path, "w", encoding="ascii") as output:
        output.write(chunk)

    received = len([name for name in os.listdir(chunk_dir) if name.endswith(".part")])
    if received < body.total:
        return _ok(message="图片分片已接收", upload_id=upload_id, received=received, total=body.total, complete=False)

    parts = []
    for index in range(body.total):
        part_path = os.path.join(chunk_dir, f"{index:06d}.part")
        if not os.path.isfile(part_path):
            raise HTTPException(400, f"缺少图片分片: {index}")
        parts.append(Path(part_path).read_text(encoding="ascii"))

    data = _decode_b64_json("".join(parts))
    result = _save_image_bytes(data, body.filename)
    result.update(upload_id=upload_id, received=received, total=body.total, complete=True)

    for name in os.listdir(chunk_dir):
        os.remove(os.path.join(chunk_dir, name))
    os.rmdir(chunk_dir)
    return result

@app.get("/material/images/download/{filename}", tags=["素材"], summary="下载图片素材")
def material_download_image(filename: str):
    """Download an image saved by POST /material/images."""
    safe_name = os.path.basename(filename)
    file_path = os.path.abspath(os.path.join(_IMAGE_DIR, safe_name))
    image_root = os.path.abspath(_IMAGE_DIR)
    if os.path.commonpath([image_root, file_path]) != image_root or not os.path.isfile(file_path):
        raise HTTPException(404, f"图片文件不存在: {safe_name}")
    _, media_type = _detect_image(Path(file_path).read_bytes()[:32])
    return FileResponse(
        file_path,
        media_type=media_type,
        filename=safe_name,
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'}
    )

# ═══════════════════════════════════════════════════════════════════════════
# 时间工具
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/util/time/parse", tags=["工具"], summary="解析时间", response_model=TimeParseResponse)
def time_parse(body: TimeParse):
    """将时间字符串解析为微秒数"""
    return TimeTool.parse_time(body.time_input)

@app.post("/util/time/format", tags=["工具"], summary="格式化时间", response_model=TimeFormatResponse)
def time_format(body: TimeFormat):
    """将微秒数格式化为可读时间字符串"""
    return TimeTool.format_time(body.microseconds)

# ═══════════════════════════════════════════════════════════════════════════
# TTS 语音合成
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/util/tts", tags=["工具"], summary="文本转语音", response_model=TTSSynthesizeResponse)
def tts_synthesize(body: TTSRequest):
    """将文本合成为语音（Edge-TTS，免费）"""
    result = TTSTool.synthesize(
        text=body.text,
        voice=body.voice,
        rate=body.rate,
        pitch=body.pitch,
        output_path=body.output_path,
    )
    # 拼接下载 URL（后续切 OSS 只需改这里的 URL 生成逻辑）
    if result.get("success") and result.get("audio_path"):
        fname = os.path.basename(result["audio_path"])
        result["download_url"] = f"{DEPLOY_URL}/util/tts/download/{fname}"
        result["provider"] = "edge-tts"
        result["format"] = "mp3"
    return result

@app.post("/util/tts/fish", tags=["工具"], summary="Fish Audio 文本转语音", response_model=TTSSynthesizeResponse)
def tts_fish_synthesize(body: FishTTSRequest):
    """使用 Fish Audio API 将文本合成为语音。"""
    result = TTSTool.synthesize_fish(
        text=body.text,
        api_key=body.api_key,
        model=body.model,
        output_path=body.output_path,
        reference_id=body.reference_id,
        temperature=body.temperature,
        top_p=body.top_p,
        prosody=body.prosody.model_dump() if body.prosody else None,
        chunk_length=body.chunk_length,
        normalize=body.normalize,
        format=body.format,
        sample_rate=body.sample_rate,
        mp3_bitrate=body.mp3_bitrate,
        opus_bitrate=body.opus_bitrate,
        latency=body.latency,
        max_new_tokens=body.max_new_tokens,
        repetition_penalty=body.repetition_penalty,
        min_chunk_length=body.min_chunk_length,
        condition_on_previous_chunks=body.condition_on_previous_chunks,
        early_stop_threshold=body.early_stop_threshold,
    )
    if result.get("success") and result.get("audio_path"):
        fname = os.path.basename(result["audio_path"])
        result["download_url"] = f"{DEPLOY_URL}/util/tts/download/{fname}"
        result["provider"] = "fish-audio"
    return result

@app.get("/util/tts/voices", tags=["工具"], summary="发音人列表", response_model=TTSVoicesResponse)
def tts_voices():
    """获取可用的发音人列表"""
    return TTSTool.list_voices()

@app.get("/util/tts/download/{filename}", tags=["工具"], summary="下载 TTS 音频")
def tts_download(filename: str):
    """下载 TTS 合成的音频文件（后续可切 OSS 预签名 URL）"""
    # 安全检查：只允许访问 TTS 目录下的文件
    safe_name = os.path.basename(filename)  # 防路径穿越
    file_path = os.path.join(_TTS_DIR, safe_name)
    if not os.path.isfile(file_path):
        raise HTTPException(404, f"音频文件不存在: {safe_name}")
    suffix = Path(safe_name).suffix.lower()
    media_type = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".opus": "audio/opus",
        ".pcm": "application/octet-stream",
    }.get(suffix, "application/octet-stream")
    return FileResponse(
        file_path,
        media_type=media_type,
        filename=safe_name,
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'}
    )

# ═══════════════════════════════════════════════════════════════════════════
# 启动
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("jianying_utils.server:app", host="0.0.0.0", port=8000, reload=True)
