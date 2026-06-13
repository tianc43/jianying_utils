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

## API 概览（50 个端点）

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
| **工具** | `POST /util/time/parse` | 解析时间 |
| | `POST /util/time/format` | 格式化时间 |
| | `POST /util/tts` | 文本转语音（Edge-TTS） |
| | `GET /util/tts/voices` | 发音人列表 |

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
