"""
Generate the complete OpenAPI 3.1.0 specification for jianying_utils.
This script reads the existing spec as a base and augments it with
proper response schemas derived from the server.py implementation.

Usage:
    python generate_openapi.py [--output path.json]
"""

from __future__ import annotations
import json, sys, os, copy
from pathlib import Path
from typing import Any

import yaml

# ── Base schemas reused across responses ──────────────────────────────

SUCCESS_BASE = {
    "success": {"type": "boolean", "description": "操作是否成功", "default": True}
}

# Specific response schemas
RESPONSE_SCHEMAS = {
    "HealthResponse": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean", "description": "操作是否成功"},
            "status": {"type": "string", "description": "服务状态", "example": "ok"},
            "version": {"type": "string", "description": "API 版本号", "example": "0.2.0"},
            "drafts_dir": {"type": "string", "description": "草稿存储目录"},
            "active_drafts": {"type": "integer", "description": "当前活跃草稿数"}
        },
        "additionalProperties": False
    },
    "DraftCreateResponse": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean", "description": "操作是否成功"},
            "message": {"type": "string", "description": "操作结果消息"},
            "draft_id": {"type": "string", "description": "草稿唯一 ID（12 位 hex）", "example": "ac51f93630c2"},
            "draft_name": {"type": "string", "description": "草稿名称"},
            "draft_folder": {"type": "string", "description": "草稿文件夹路径"},
            "script_path": {"type": "string", "description": "草稿脚本文件路径"}
        },
        "additionalProperties": False
    },
    "DraftsListResponse": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean", "description": "操作是否成功"},
            "message": {"type": "string", "description": "操作结果消息"},
            "drafts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "draft_id": {"type": "string"},
                        "draft_name": {"type": "string"},
                        "draft_folder": {"type": "string"}
                    }
                }
            },
            "count": {"type": "integer", "description": "草稿总数"}
        },
        "additionalProperties": False
    },
    "DraftInfoResponse": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean", "description": "操作是否成功"},
            "message": {"type": "string", "description": "操作结果消息"},
            "draft_folder": {"type": "string", "description": "草稿文件夹路径"},
            "draft_name": {"type": "string", "description": "草稿名称"},
            "script_path": {"type": "string", "description": "草稿脚本文件路径"},
            "width": {"type": "integer", "description": "视频宽度"},
            "height": {"type": "integer", "description": "视频高度"},
            "fps": {"type": "integer", "description": "帧率"},
            "duration": {"type": "integer", "description": "草稿总时长（微秒）"}
        },
        "additionalProperties": False
    },
    "DraftExportResponse": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean", "description": "操作是否成功"},
            "message": {"type": "string", "description": "操作结果消息"},
            "json_string": {"type": "string", "description": "草稿 JSON 字符串"},
            "draft_name": {"type": "string", "description": "草稿名称"}
        },
        "additionalProperties": False
    },
    "GenericSuccessResponse": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean", "description": "操作是否成功", "default": True},
            "message": {"type": "string", "description": "操作结果消息"}
        },
        "additionalProperties": False
    },
    "DraftSaveResponse": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean", "description": "操作是否成功"},
            "message": {"type": "string", "description": "操作结果消息"},
            "script_path": {"type": "string", "description": "保存后的脚本文件路径"}
        },
        "additionalProperties": False
    },
    "TrackItem": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "轨道名称"},
            "type": {"type": "string", "description": "轨道类型"},
            "render_index": {"type": "integer", "description": "渲染层级"},
            "mute": {"type": "boolean", "description": "是否静音"},
            "segment_count": {"type": "integer", "description": "片段数量"},
            "source": {"type": "string", "description": "来源标识（imported=导入轨道）"}
        }
    },
    "TrackAddResponse": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean", "description": "操作是否成功"},
            "message": {"type": "string", "description": "操作结果消息"},
            "track_type": {"type": "string", "description": "轨道类型"},
            "track_name": {"type": "string", "description": "轨道名称"}
        },
        "additionalProperties": False
    },
    "TrackListResponse": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean", "description": "操作是否成功"},
            "message": {"type": "string", "description": "操作结果消息"},
            "tracks": {
                "type": "array",
                "items": {"$ref": "#/components/schemas/TrackItem"},
                "description": "轨道列表"
            }
        },
        "additionalProperties": False
    },
    "MetadataItem": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "内部名称"},
            "display_name": {"type": "string", "description": "显示名称"},
            "is_vip": {"type": "boolean", "description": "是否 VIP"},
            "resource_id": {"type": "string", "description": "资源 ID"},
            "effect_id": {"type": "string", "description": "效果 ID"},
            "duration_us": {"type": "integer", "description": "持续时间（微秒，动画类）"},
            "duration_seconds": {"type": "number", "description": "持续时间（秒，动画类）"},
            "params": {
                "type": "array",
                "items": {"$ref": "#/components/schemas/MetadataParamItem"},
                "description": "参数列表"
            }
        }
    },
    "MetadataParamItem": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "参数名称"},
            "default": {"type": "number", "description": "默认值"},
            "min": {"type": "number", "description": "最小值"},
            "max": {"type": "number", "description": "最大值"}
        }
    },
    "SegmentResponse": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean", "description": "操作是否成功"},
            "message": {"type": "string", "description": "操作结果消息"},
            "segment_id": {"type": "string", "description": "新创建片段的 ID"}
        },
        "additionalProperties": False
    },
    "BatchResponse": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean", "description": "操作是否成功"},
            "message": {"type": "string", "description": "操作结果消息"},
            "count": {"type": "integer", "description": "添加的片段数量"},
            "segment_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "新创建片段的 ID 列表"
            }
        },
        "additionalProperties": False
    },
    "TimeParseResponse": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean", "description": "操作是否成功"},
            "microseconds": {"type": "integer", "description": "解析后的微秒数", "example": 5000000},
            "message": {"type": "string", "description": "操作结果消息"}
        },
        "additionalProperties": False
    },
    "TimeFormatResponse": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean", "description": "操作是否成功"},
            "formatted": {"type": "string", "description": "格式化后的时间字符串", "example": "00:01:05.000"},
            "message": {"type": "string", "description": "操作结果消息"}
        },
        "additionalProperties": False
    },
    "SimpleWorkflowResponse": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean", "description": "操作是否成功"},
            "message": {"type": "string", "description": "操作结果消息"},
            "duration": {"type": "integer", "description": "草稿总时长（微秒）"},
            "duration_seconds": {"type": "number", "description": "草稿总时长（秒）"}
        },
        "additionalProperties": False
    },
    "MaterialVideoInfoResponse": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean", "description": "操作是否成功"},
            "message": {"type": "string", "description": "操作结果消息"},
            "duration": {"type": "integer", "description": "时长（微秒）"},
            "width": {"type": "integer", "description": "视频宽度"},
            "height": {"type": "integer", "description": "视频高度"},
            "type": {"type": "string", "description": "素材类型（video/image）"},
            "material_name": {"type": "string", "description": "素材文件名"},
            "path": {"type": "string", "description": "素材文件路径"}
        },
        "additionalProperties": False
    },
    "MaterialAudioDurationResponse": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean", "description": "操作是否成功"},
            "message": {"type": "string", "description": "操作结果消息"},
            "duration": {"type": "integer", "description": "音频时长（微秒）"},
            "duration_seconds": {"type": "number", "description": "音频时长（秒）"},
            "material_name": {"type": "string", "description": "素材文件名"},
            "path": {"type": "string", "description": "素材文件路径"}
        },
        "additionalProperties": False
    },
    "ImageSaveResponse": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean", "description": "操作是否成功"},
            "message": {"type": "string", "description": "操作结果消息"},
            "filename": {"type": "string", "description": "保存后的文件名"},
            "file_path": {"type": "string", "description": "服务端本地文件路径"},
            "download_url": {"type": "string", "description": "图片下载 URL"},
            "static_url": {"type": "string", "description": "可直接作为素材路径使用的静态 URL"},
            "media_type": {"type": "string", "description": "图片 MIME 类型"},
            "size": {"type": "integer", "description": "图片字节数"},
            "sha256": {"type": "string", "description": "图片内容 SHA256"}
        },
        "additionalProperties": False
    },
    "ImageGenerateResponse": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean", "description": "操作是否成功"},
            "message": {"type": "string", "description": "操作结果消息"},
            "filename": {"type": "string", "description": "保存后的文件名"},
            "file_path": {"type": "string", "description": "服务端本地文件路径"},
            "download_url": {"type": "string", "description": "图片下载 URL"},
            "static_url": {"type": "string", "description": "可直接作为素材路径使用的静态 URL"},
            "media_type": {"type": "string", "description": "图片 MIME 类型"},
            "size": {"type": "integer", "description": "图片字节数"},
            "sha256": {"type": "string", "description": "图片内容 SHA256"},
            "image_url": {"type": "string", "description": "推荐传给剪映后续素材接口的图片 URL"},
            "upstream_status": {"type": "integer", "description": "上游图片接口 HTTP 状态码"},
            "upstream_request_id": {"type": "string", "description": "上游响应 request id（如果有）"}
        },
        "additionalProperties": False
    },
    "MetadataListResponse": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean", "description": "操作是否成功"},
            "message": {"type": "string", "description": "操作结果消息"},
            "items": {
                "type": "array",
                "items": {"$ref": "#/components/schemas/MetadataItem"},
                "description": "元数据项列表"
            },
            "count": {"type": "integer", "description": "总数"}
        },
        "additionalProperties": False
    },
}

# ── Map each path+method to its response schema ───────────────────────

PATH_RESPONSE_MAP = {
    ("/health", "get"): "HealthResponse",
    ("/drafts", "post"): "DraftCreateResponse",
    ("/drafts", "get"): "DraftsListResponse",
    ("/drafts/{draft_id}", "get"): "DraftInfoResponse",
    ("/drafts/{draft_id}", "delete"): "GenericSuccessResponse",
    ("/drafts/{draft_id}/save", "post"): "DraftSaveResponse",
    ("/drafts/{draft_id}/export", "post"): "DraftExportResponse",
    ("/drafts/{draft_id}/tracks", "post"): "TrackAddResponse",
    ("/drafts/{draft_id}/tracks", "get"): "TrackListResponse",
    ("/drafts/{draft_id}/videos", "post"): "SegmentResponse",
    ("/drafts/{draft_id}/videos/batch", "post"): "BatchResponse",
    ("/drafts/{draft_id}/audios", "post"): "SegmentResponse",
    ("/drafts/{draft_id}/audios/batch", "post"): "BatchResponse",
    ("/drafts/{draft_id}/audios/fade", "post"): "GenericSuccessResponse",
    ("/drafts/{draft_id}/texts", "post"): "SegmentResponse",
    ("/drafts/{draft_id}/captions", "post"): "BatchResponse",
    ("/drafts/{draft_id}/effects/scene", "post"): "GenericSuccessResponse",
    ("/drafts/{draft_id}/effects/character", "post"): "GenericSuccessResponse",
    ("/drafts/{draft_id}/effects/filter", "post"): "GenericSuccessResponse",
    ("/drafts/{draft_id}/effects/batch", "post"): "BatchResponse",
    ("/drafts/{draft_id}/stickers", "post"): "SegmentResponse",
    ("/drafts/{draft_id}/animations/video-intro", "post"): "GenericSuccessResponse",
    ("/drafts/{draft_id}/animations/video-outro", "post"): "GenericSuccessResponse",
    ("/drafts/{draft_id}/animations/video-group", "post"): "GenericSuccessResponse",
    ("/drafts/{draft_id}/animations/text-intro", "post"): "GenericSuccessResponse",
    ("/drafts/{draft_id}/animations/text-outro", "post"): "GenericSuccessResponse",
    ("/drafts/{draft_id}/animations/text-loop", "post"): "GenericSuccessResponse",
    ("/drafts/{draft_id}/keyframes", "post"): "GenericSuccessResponse",
    ("/drafts/{draft_id}/keyframes/batch", "post"): "BatchResponse",
    ("/drafts/{draft_id}/transitions", "post"): "GenericSuccessResponse",
    ("/drafts/{draft_id}/transitions/batch", "post"): "BatchResponse",
    ("/drafts/{draft_id}/workflow/simple", "post"): "SimpleWorkflowResponse",
    ("/metadata/transitions", "get"): "MetadataListResponse",
    ("/metadata/filters", "get"): "MetadataListResponse",
    ("/metadata/fonts", "get"): "MetadataListResponse",
    ("/metadata/masks", "get"): "MetadataListResponse",
    ("/metadata/mix-modes", "get"): "MetadataListResponse",
    ("/metadata/video-intros", "get"): "MetadataListResponse",
    ("/metadata/video-outros", "get"): "MetadataListResponse",
    ("/metadata/video-group-anims", "get"): "MetadataListResponse",
    ("/metadata/text-intros", "get"): "MetadataListResponse",
    ("/metadata/text-outros", "get"): "MetadataListResponse",
    ("/metadata/text-loop-anims", "get"): "MetadataListResponse",
    ("/metadata/scene-effects", "get"): "MetadataListResponse",
    ("/metadata/character-effects", "get"): "MetadataListResponse",
    ("/metadata/audio-effects", "get"): "MetadataListResponse",
    ("/material/video-info", "get"): "MaterialVideoInfoResponse",
    ("/material/audio-duration", "get"): "MaterialAudioDurationResponse",
    ("/material/images", "post"): "ImageSaveResponse",
    ("/material/images/generate", "post"): "ImageGenerateResponse",
    ("/util/time/parse", "post"): "TimeParseResponse",
    ("/util/time/format", "post"): "TimeFormatResponse",
}

TIME_VALUE_DESCRIPTION = (
    "时间值。剪映内部使用微秒（μs）作为时间单位，1 秒 = 1,000,000 微秒。"
    "传 integer/number 或纯数字字符串时按微秒处理，例如 5000000 表示 5 秒；"
    "传带单位字符串时按时间表达式解析，例如 \"0.5s\"、\"5s\"、\"1m30s\"、\"1h2m3s\"。"
)

TIME_FIELD_DOCS = {
    "start": {
        "description": f"时间线起始时间。{TIME_VALUE_DESCRIPTION}",
        "examples": ["0s", 0, 5000000],
    },
    "duration": {
        "description": f"持续时长，不是结束时间。{TIME_VALUE_DESCRIPTION}",
        "examples": ["3s", 3000000],
    },
    "in_duration": {
        "description": f"淡入持续时长。{TIME_VALUE_DESCRIPTION}",
        "examples": ["0.5s", 500000],
    },
    "out_duration": {
        "description": f"淡出持续时长。{TIME_VALUE_DESCRIPTION}",
        "examples": ["0.5s", 500000],
    },
    "time_offset": {
        "description": f"相对片段起点的时间偏移。{TIME_VALUE_DESCRIPTION}",
        "examples": ["0.5s", 500000],
    },
    "microseconds": {
        "description": "微秒数（μs）。1 秒 = 1,000,000 微秒。",
        "examples": [5000000],
    },
    "time_input": {
        "description": TIME_VALUE_DESCRIPTION,
        "examples": ["5s", "1m30s", 5000000],
    },
}

END_FIELD_DOC = {
    "description": "结束时间，单位微秒（μs）。注意这是绝对结束时间，不是持续时长；持续时长 = end - start。",
    "examples": [5000000],
}


def load_existing_spec(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_dynamic_spec() -> dict:
    """Build schema from server.py models instead of reusing the stale static file."""
    from jianying_utils import server

    return server._openapi_fastapi_default()


def apply_response_schemas(spec: dict) -> dict:
    """Update all endpoint responses to reference proper schemas."""
    spec = copy.deepcopy(spec)

    # Add response schemas to components
    if "components" not in spec:
        spec["components"] = {}
    if "schemas" not in spec["components"]:
        spec["components"]["schemas"] = {}
    for name, schema in RESPONSE_SCHEMAS.items():
        spec["components"]["schemas"][name] = schema

    # Update path responses
    for path_url, path_obj in spec.get("paths", {}).items():
        for method, operation in path_obj.items():
            key = (path_url, method.lower())
            schema_name = PATH_RESPONSE_MAP.get(key)
            if schema_name and "responses" in operation:
                success_resp = operation["responses"].get("200", {})
                if "content" in success_resp:
                    content_type = success_resp["content"].get("application/json", {})
                    content_type["schema"] = {"$ref": f"#/components/schemas/{schema_name}"}
                    success_resp["content"]["application/json"] = content_type
                    success_resp["description"] = _describe_schema(schema_name)
                    operation["responses"]["200"] = success_resp

    return spec


def apply_time_unit_docs(spec: dict) -> dict:
    """Make time units explicit and consistent across schemas and operations."""
    spec = copy.deepcopy(spec)
    info = spec.setdefault("info", {})
    base_description = info.get("description", "")
    time_note = (
        "\n\n时间单位说明：剪映内部使用微秒（μs），1 秒 = 1,000,000 微秒。"
        "API 中 `start`、`duration`、`time_offset`、`in_duration`、`out_duration` 等字段"
        "通常支持两种写法：数字/纯数字字符串按微秒处理，带单位字符串如 `0.5s`、`5s`、"
        "`1m30s`、`1h2m3s` 会自动解析。批量接口中的 `end` 表示绝对结束时间，单位微秒，"
        "不是持续时长。"
    )
    if "时间单位说明" not in base_description:
        info["description"] = base_description + time_note

    for schema in spec.get("components", {}).get("schemas", {}).values():
        _patch_schema_time_fields(schema)

    for path_item in spec.get("paths", {}).values():
        for operation in path_item.values():
            if isinstance(operation, dict):
                _patch_operation_examples(operation)

    return spec


def _patch_schema_time_fields(schema: dict[str, Any]) -> None:
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for name, prop in properties.items():
            if not isinstance(prop, dict):
                continue
            if name in TIME_FIELD_DOCS:
                _merge_time_doc(prop, TIME_FIELD_DOCS[name])
            elif name == "end":
                _merge_time_doc(prop, END_FIELD_DOC)
            elif name.endswith("_seconds"):
                prop.setdefault("description", "秒数（s）。")
                prop.setdefault("examples", [5.0])
            elif name.endswith("_us"):
                prop.setdefault("description", "微秒数（μs）。1 秒 = 1,000,000 微秒。")
                prop.setdefault("examples", [5000000])
            _patch_schema_time_fields(prop)

    for key in ("items", "anyOf", "oneOf", "allOf"):
        value = schema.get(key)
        if isinstance(value, dict):
            _patch_schema_time_fields(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _patch_schema_time_fields(item)


def _merge_time_doc(prop: dict[str, Any], doc: dict[str, Any]) -> None:
    existing = prop.get("description", "")
    if "微秒" not in existing and "μs" not in existing:
        prop["description"] = doc["description"]
    elif prop.get("description"):
        prop["description"] = prop["description"].replace("如 5s", "如 \"5s\"")
    prop.setdefault("examples", doc["examples"])


def _patch_operation_examples(operation: dict[str, Any]) -> None:
    description = operation.get("description", "")
    if any(word in description for word in ("时间", "时长", "字幕", "音频", "视频", "特效", "滤镜", "转场", "关键帧")):
        if "时间单位" not in description:
            operation["description"] = description + (
                "\n\n时间单位：数字表示微秒（μs），如 5000000 = 5 秒；"
                "也可传字符串如 `5s`、`0.5s`、`1m30s`。"
            )


def _describe_schema(name: str) -> str:
    descriptions = {
        "HealthResponse": "服务健康状态",
        "DraftCreateResponse": "草稿创建成功，返回 draft_id",
        "DraftsListResponse": "活跃草稿列表",
        "DraftInfoResponse": "草稿详细信息（尺寸、时长、帧率等）",
        "DraftExportResponse": "草稿 JSON 导出",
        "GenericSuccessResponse": "操作成功",
        "TrackAddResponse": "轨道添加成功",
        "TrackListResponse": "轨道列表",
        "SegmentResponse": "片段添加成功，返回 segment_id",
        "BatchResponse": "批量操作成功",
        "TimeParseResponse": "时间解析结果",
        "TimeFormatResponse": "时间格式化结果",
        "SimpleWorkflowResponse": "一键创建完成",
        "MaterialVideoInfoResponse": "视频/图片素材信息",
        "MaterialAudioDurationResponse": "音频时长信息",
        "ImageSaveResponse": "图片保存结果",
        "ImageGenerateResponse": "图片生成保存结果",
        "MetadataListResponse": "元数据查询结果",
    }
    return descriptions.get(name, "Successful Response")


def generate(input_path: str | None, output_path: str):
    spec = load_existing_spec(input_path) if input_path else load_dynamic_spec()
    spec = apply_response_schemas(spec)
    spec = apply_time_unit_docs(spec)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)

    yaml_path = str(Path(output_path).with_suffix(".yaml"))
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(spec, f, allow_unicode=True, sort_keys=False)

    # Print summary
    paths_count = len(spec.get("paths", {}))
    schemas_count = len(spec.get("components", {}).get("schemas", {}))
    endpoints_count = sum(len(methods) for methods in spec.get("paths", {}).values())
    resp_mapped = sum(1 for k in PATH_RESPONSE_MAP
                      for p, ms in spec.get("paths", {}).items()
                      if p == k[0]
                      for m in ms
                      if m == k[1])

    print(f"OpenAPI spec generated: {output_path}")
    print(f"OpenAPI YAML generated: {yaml_path}")
    print(f"  Path groups: {paths_count}")
    print(f"  Total endpoints: {endpoints_count}")
    print(f"  Schema definitions: {schemas_count}")
    print(f"  Response schemas mapped: {resp_mapped} endpoints")

    # Verify JSON is valid
    with open(output_path, "r", encoding="utf-8") as f:
        json.load(f)
    print(f"  JSON validation: PASSED")


if __name__ == "__main__":
    _API_DIR = Path(__file__).parent.parent / "api"
    default_output = _API_DIR / "openapi.json"

    input_path = None  # 通常基于 FastAPI 动态输出，这里直接生成到 api/
    output_path = default_output

    # Parse args
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--input" and i + 1 < len(args):
            input_path = args[i + 1]
        elif arg == "--output" and i + 1 < len(args):
            output_path = args[i + 1]

    generate(str(input_path) if input_path else None, str(output_path))
