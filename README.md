# JianYing Utils — 剪映草稿自动化 REST API

基于 [pyJianYingDraft](https://github.com/tianc43/pyJianYingDraft) 的剪映草稿自动化工具包，提供 REST API + Dify 工作流代码节点。

## 目录结构

```
jianying_utils/              # 仓库根目录
├── jianying_utils/          # Python 包（核心代码）
│   ├── __init__.py           #   包入口，导出所有工具类
│   ├── _context.py           #   内部上下文管理
│   ├── server.py             #   FastAPI 服务端
│   ├── draft_manager.py      #   草稿管理
│   ├── track_manager.py      #   轨道管理
│   ├── video_tool.py         #   视频/图片片段
│   ├── audio_tool.py         #   音频片段
│   ├── text_tool.py          #   文本/字幕
│   ├── effect_tool.py        #   特效/滤镜
│   ├── sticker_tool.py       #   贴纸
│   ├── animation_tool.py     #   入场/出场/组合/循环动画
│   ├── keyframe_tool.py      #   关键帧
│   ├── transition_tool.py    #   转场
│   ├── template_tool.py      #   模板
│   ├── material_tool.py      #   素材信息/裁剪
│   ├── metadata_query.py     #   元数据查询（枚举列表）
│   ├── time_tool.py          #   时间解析/格式化/转换
│   ├── export_tool.py        #   JSON 导出
│   └── generate_openapi.py   #   OpenAPI 生成脚本
├── api/                      # OpenAPI 规范文件
│   ├── openapi.json          #   OpenAPI 3.0.3 JSON
│   └── openapi.yaml          #   OpenAPI 3.0.3 YAML
├── examples/                 # 使用示例
│   ├── demo.py               #   完整工作流示例
│   └── session_demo.py       #   会话管理示例
├── swagger-viewer.html       # Swagger UI 查看器
├── Dockerfile                # Docker 镜像构建
├── docker-compose.yml        # Docker Compose 部署
├── requirements.txt          # Python 依赖
└── README.md
```

## 快速启动

### 本地运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动服务
uvicorn jianying_utils.server:app --host 0.0.0.0 --port 8000

# 或者直接运行
python -m jianying_utils.server
```

启动后访问：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- OpenAPI JSON: http://localhost:8000/openapi.json
- OpenAPI YAML: http://localhost:8000/openapi.yaml
- 健康检查: http://localhost:8000/health

### Docker 部署

```bash
# 构建并启动
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止
docker-compose down
```

### 服务器部署

```bash
# 生产环境启动（gunicorn + uvicorn workers）
uvicorn jianying_utils.server:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 4 \
    --no-access-log

# 或使用环境变量自定义草稿目录
export JIANYING_DRAFTS_DIR=/data/jianying/drafts
uvicorn jianying_utils.server:app --host 0.0.0.0 --port 8000
```

### 日志

服务启动时会自动配置日志输出到 stdout（`docker logs` / `docker-compose logs -f` 直接可见），格式为：

```
2026-07-01 10:23:01 INFO     jianying_utils.server: 草稿已创建: draft_id=a1b2c3d4e5f6 draft_name=demo
2026-07-01 10:23:02 ERROR    jianying_utils.audio_tool: 添加音频失败
Traceback (most recent call last):
  ...
```

- 每个 HTTP 请求都会记录一行 `METHOD PATH -> STATUS (耗时ms)`（2xx/3xx 用 INFO，4xx/5xx 用 WARNING）。
- 工具类方法（`DraftManager`/`AudioTool`/`VideoTool` 等）内部异常统一通过 `logger.exception` 记录完整堆栈，同时仍返回 `{"success": false, "message": "..."}`，不影响现有调用方行为。
- 日志级别通过 `JIANYING_LOG_LEVEL` 环境变量调整（默认 `INFO`，可选 `DEBUG`/`WARNING`/`ERROR`）：

```bash
export JIANYING_LOG_LEVEL=DEBUG
```

## API 概览

| 分类 | 端点 | 说明 |
|------|------|------|
| **系统** | `GET /health` | 健康检查 |
| **草稿** | `POST /drafts` | 创建草稿 |
| | `GET /drafts` | 列出所有草稿 |
| | `GET /drafts/{id}` | 获取草稿信息 |
| | `DELETE /drafts/{id}` | 删除草稿 |
| | `POST /drafts/{id}/save` | 保存草稿 |
| | `POST /drafts/{id}/export` | 导出草稿 JSON |
| **轨道** | `POST /drafts/{id}/tracks` | 添加轨道 |
| | `GET /drafts/{id}/tracks` | 列出轨道 |
| **视频** | `POST /drafts/{id}/videos` | 添加视频 |
| | `POST /drafts/{id}/videos/batch` | 批量添加视频 |
| **音频** | `POST /drafts/{id}/audios` | 添加音频 |
| | `POST /drafts/{id}/audios/batch` | 批量添加音频 |
| | `POST /drafts/{id}/audios/fade` | 淡入淡出 |
| **文本** | `POST /drafts/{id}/texts` | 添加文本 |
| | `POST /drafts/{id}/captions` | 批量添加字幕 |
| **特效** | `POST /drafts/{id}/effects/scene` | 场景特效 |
| | `POST /drafts/{id}/effects/character` | 人物特效 |
| | `POST /drafts/{id}/effects/filter` | 滤镜 |
| | `POST /drafts/{id}/effects/batch` | 批量特效 |
| **贴纸** | `POST /drafts/{id}/stickers` | 添加贴纸 |
| **动画** | `POST /drafts/{id}/animations/video-intro` | 视频入场 |
| | `POST /drafts/{id}/animations/video-outro` | 视频出场 |
| | `POST /drafts/{id}/animations/video-group` | 视频组合 |
| | `POST /drafts/{id}/animations/text-intro` | 文本入场 |
| | `POST /drafts/{id}/animations/text-outro` | 文本出场 |
| | `POST /drafts/{id}/animations/text-loop` | 文本循环 |
| **关键帧** | `POST /drafts/{id}/keyframes` | 添加关键帧 |
| | `POST /drafts/{id}/keyframes/batch` | 批量关键帧 |
| **转场** | `POST /drafts/{id}/transitions` | 添加转场 |
| | `POST /drafts/{id}/transitions/batch` | 批量转场 |
| **工作流** | `POST /drafts/{id}/workflow/simple` | 一键创建 |
| **元数据** | `GET /metadata/transitions` | 转场列表 |
| | `GET /metadata/filters` | 滤镜列表 |
| | `GET /metadata/fonts` | 字体列表 |
| | `GET /metadata/masks` | 蒙版列表 |
| | `GET /metadata/mix-modes` | 混合模式列表 |
| | `GET /metadata/video-intros` | 视频入场动画列表 |
| | `GET /metadata/video-outros` | 视频出场动画列表 |
| | `GET /metadata/video-group-anims` | 视频组合动画列表 |
| | `GET /metadata/text-intros` | 文本入场动画列表 |
| | `GET /metadata/text-outros` | 文本出场动画列表 |
| | `GET /metadata/text-loop-anims` | 文本循环动画列表 |
| | `GET /metadata/scene-effects` | 场景特效列表 |
| | `GET /metadata/character-effects` | 人物特效列表 |
| | `GET /metadata/audio-effects` | 音频特效列表 |
| **素材** | `GET /material/video-info` | 获取视频信息 |
| | `GET /material/audio-duration` | 获取音频时长 |
| | `POST /material/images` | 保存 Base64 图片并返回下载 URL |
| | `POST /material/images/generate` | 调用图片接口、保存图片并返回短 URL |
| **工具** | `POST /util/time/parse` | 解析时间 |
| | `POST /util/time/format` | 格式化时间 |
| | `POST /util/tts` | 文本转语音（Edge-TTS） |
| | `POST /util/tts/fish` | 文本转语音（Fish Audio） |
| | `GET /util/tts/voices` | 发音人列表 |

### Fish Audio TTS

Fish Audio 合成接口会读取 `FISH_API_KEY` 环境变量，也可以在请求体里临时传 `api_key`：

```http
POST /util/tts/fish
Content-Type: application/json

{
  "text": "Hello! Welcome to Fish Audio. This is my first AI-generated voice.",
  "model": "s2-pro",
  "format": "mp3"
}
```

常用可选参数包括 `reference_id`、`temperature`、`top_p`、`prosody`、`sample_rate`、`mp3_bitrate`、`latency`、`max_new_tokens`、`repetition_penalty` 等。生成文件默认保存到 `JIANYING_TTS_DIR`，并返回 `/util/tts/download/{filename}` 下载地址。

`prosody` 应传 JSON object，例如 `{"speed":1.15,"volume":0,"normalize_loudness":true}`；不要传 JSON 字符串。

## Dify 生成并保存图片素材

推荐让后台直接调用 OpenAI 兼容图片接口并保存文件，Dify 只接收短 JSON 响应，避免在工作流节点间传递大型 `b64_json` 响应导致 chunked 读取中断。

```http
POST /material/images/generate
Content-Type: application/json

{
  "endpoint_url": "https://tianc43.xyz/v1/images/generations",
  "api_key": "{{ IMAGE_API_KEY }}",
  "api_key_header": "Authorization",
  "model": "gpt-image-2",
  "prompt": "{{ storyboard_prompt }}",
  "response_format": "b64_json",
  "quality": "low",
  "size": "1024x576",
  "output_format": "webp",
  "output_compression": 70,
  "filename": "storyboard-01",
  "timeout_seconds": 900,
  "max_retries": 2
}
```

后续 `POST /drafts/{id}/videos` 的 `video_path` 优先使用响应里的 `image_url` 或 `static_url`。如果上游返回 401/403/422，服务日志会保留上游错误体和 request id，方便判断是 key、模型、额度还是内容策略问题。

## Dify 保存 b64_json 图片素材

如果上游 HTTP 节点返回 OpenAI 图片接口一类的 `b64_json`，推荐不要在 Dify 里长期传递整段 Base64。先调用后台保存成文件，再把返回的 URL 传给后续剪映接口：

```http
POST /material/images
Content-Type: application/json

{
  "b64_json": "{{ image_response.data[0].b64_json }}",
  "filename": "cover.png"
}
```

响应示例：

```json
{
  "success": true,
  "filename": "cover-a1b2c3d4e5f6.png",
  "download_url": "http://localhost:8000/material/images/download/cover-a1b2c3d4e5f6.png",
  "static_url": "http://localhost:8000/static/uploads/images/cover-a1b2c3d4e5f6.png",
  "file_path": "C:/.../uploads/images/cover-a1b2c3d4e5f6.png",
  "media_type": "image/png",
  "size": 123456,
  "sha256": "..."
}
```

后续 `POST /drafts/{id}/videos` 的 `video_path` 优先用 `static_url`；它会被服务端解析为本地文件，避免再次下载。跨机器部署或图片目录不在项目根目录时，用 `download_url` 更稳。默认图片保存目录是 `uploads/images`，可用 `JIANYING_IMAGE_DIR` 覆盖；单张图片默认限制 20MB，可用 `JIANYING_IMAGE_MAX_BYTES` 覆盖。

## 主题开头与片段级效果

视频开头可以先用 1-3 秒文字主题卡吸引注意力，再进入正文图片/视频。推荐流程：

1. `POST /drafts/{id}/texts` 添加主题文本，例如从 `0s` 到 `2s`，使用大字号、描边、阴影或背景。
2. `POST /drafts/{id}/animations/text-intro` 给主题文本加入场动画，必要时再加 `text-loop` 保持动感。
3. `POST /drafts/{id}/audios` 在主题抛出点添加短音效或重音，例如 `start: "0.6s"`、`duration: "0.5s"`。
4. 如果由 Hyperframes 或其他工具生成 1-3 秒开头动画，可把生成的视频作为普通素材通过 `POST /drafts/{id}/videos` 加到开头。

视频/图片片段现在支持在添加时直接挂载剪映 UI 里的圆角和“发光描边”：

```json
{
  "video_path": "/data/assets/topic-card.png",
  "start": "2s",
  "duration": "4s",
  "round_corner": 8,
  "glow_outline": {
    "color": "#000000",
    "size": 10
  }
}
```

说明：这些字段会写入剪映原生的 `materials.video_radius` 和 `materials.video_strokes`，并挂到片段的 `extra_material_refs`。已按剪映草稿验证：圆角 `8` 会保存为 `0.08`，发光描边黑色保存为 `[1,0,0,0]`，大小 `10` 保存为 `0.1`。

部署说明：代码不会硬编码本机剪映缓存路径。需要指定剪映效果资源路径时，可在运行环境配置 `JIANYING_EFFECT_CACHE_DIR`，或分别配置 `JIANYING_GLOW_STROKE_PATH`、`JIANYING_ROUND_RADIUS_PATH`。这些变量不配置时，服务端会写入空路径，由剪映按资源 ID 识别/补全。

## 本机 Downloader 导入草稿

服务端下载接口返回占位符无关的便携 ZIP 包：素材路径保持为
`audio/...`、`image/...`、`video/...`。用户本机通过 downloader 导入到剪映草稿目录。
导入器会扫描本机已有剪映草稿，获取正确的 `##_draftpath_placeholder_xxx_##`，
并重写 `draft_content.json`、`draft_info.json`、`draft_meta_info.json`。

```powershell
python -m jianying_utils.downloader install `
  --url "http://127.0.0.1:18532/drafts/<draft_id>/download" `
  --drafts-dir "<本机剪映草稿目录>"
```

如果用户机器上还没有任何剪映草稿，先在剪映里创建一个空草稿。导入器不会硬编码本机草稿目录，需要通过 `--drafts-dir` 或 `JIANYING_NATIVE_DRAFTS_DIR` 指定：

```powershell
python -m jianying_utils.downloader install `
  --url "http://server/drafts/<draft_id>/download" `
  --drafts-dir "<本机剪映草稿目录>" `
  --placeholder-id "<本机草稿占位符ID>"
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--url` | 草稿 ZIP 下载地址，也可以传本地 ZIP 路径 |
| `--drafts-dir` | 本机剪映草稿目录；不传时会尝试自动查找 |
| `--draft-name` | 导入后的草稿文件夹名称 |
| `--placeholder-id` | 手动指定本机剪映占位符 ID |
| `--overwrite` | 覆盖同名草稿目录 |

## 统一响应格式

所有端点返回统一的 JSON 结构：

```json
{
  "success": true,
  "message": "操作成功",
  "...": "..."
}
```

## Dify 代码节点使用

```python
from jianying_utils import TimeTool, DraftManager, TrackManager

# 时间解析
result = TimeTool.parse_time("5s")
# → {"success": True, "microseconds": 5000000, "message": "时间解析成功"}

# 创建草稿
result = DraftManager.create_draft("/tmp/drafts", "my_draft", 1920, 1080, 30)
# → {"success": True, "message": "草稿创建成功", "draft_folder": "...", ...}
```

## 技术栈

- Python 3.10+
- FastAPI + Pydantic v2
- OpenAPI 3.0.3
- pyJianYingDraft
- Docker / Docker Compose
