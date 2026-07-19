FROM python:3.10-slim-bookworm

LABEL maintainer="jianying-utils"
LABEL description="剪映草稿自动化 REST API"

# 配置 Debian 国内镜像源
# 安装系统依赖 (libmediainfo 供 pymediainfo 使用)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libmediainfo0v5 \
    && rm -rf /var/lib/apt/lists/*

# 工作目录
WORKDIR /app

# 配置 pip 国内镜像
# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --timeout 180 --retries 10 -r requirements.txt

# 复制项目代码（只复制需要的目录）
COPY jianying_utils/ jianying_utils/
COPY api/ api/
COPY assets/ assets/
COPY swagger-viewer.html .
COPY requirements.txt .

# 设置草稿存储目录 & 部署 URL 前缀
ENV JIANYING_DRAFTS_DIR=/app/drafts
ENV ROOT_PATH=/jianying-utils
ENV DEPLOY_URL=https://tianc43.xyz/jianying-utils
RUN mkdir -p /app/drafts

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# 单 worker 部署（避免多 worker 间状态竞争）
CMD ["gunicorn", "jianying_utils.server:app", \
     "--workers", "1", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "300", \
     "--graceful-timeout", "30", \
     "--keep-alive", "5", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
