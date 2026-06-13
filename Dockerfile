FROM python:3.10-slim-bookworm

LABEL maintainer="jianying-utils"
LABEL description="剪映草稿自动化 REST API"

# 配置 Debian 国内镜像源
RUN sed -i 's|http://deb.debian.org/debian|https://mirrors.tuna.tsinghua.edu.cn/debian|g' /etc/apt/sources.list.d/debian.sources && \
    sed -i 's|http://security.debian.org/debian-security|https://mirrors.tuna.tsinghua.edu.cn/debian-security|g' /etc/apt/sources.list.d/debian.sources
# 安装系统依赖 (libmediainfo 供 pymediainfo 使用)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libmediainfo0v5 \
    && rm -rf /var/lib/apt/lists/*

# 工作目录
WORKDIR /app

# 配置 pip 国内镜像
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码（只复制需要的目录）
COPY jianying_utils/ jianying_utils/
COPY api/ api/
COPY swagger-viewer.html .
COPY requirements.txt .

# 设置草稿存储目录
ENV JIANYING_DRAFTS_DIR=/app/drafts
RUN mkdir -p /app/drafts

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# 生产环境：gunicorn + uvicorn workers（自动多核、崩溃重启、优雅退出）
# 本地开发：直接运行 uvicorn jianying_utils.server:app --host 0.0.0.0 --port 8000
CMD ["gunicorn", "jianying_utils.server:app", \
     "--workers", "4", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "120", \
     "--graceful-timeout", "30", \
     "--keep-alive", "5", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
