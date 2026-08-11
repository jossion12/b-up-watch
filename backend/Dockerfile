# syntax=docker/dockerfile:1.7
#
# 多阶段构建:
#   base    : Python + 系统依赖(ffmpeg / gcc / curl)
#   runtime : base + 核心依赖(FastAPI / sentence-transformers / milvus-lite)
#             —— 这是默认目标
#   asr     : runtime + 本地 ASR 依赖(torch + qwen-asr)
#             —— 镜像会显著变大,只在需要本地 ASR 时启用
#
# 用法:
#   docker build --target runtime -t upwatch-backend .
#   docker build --target asr     -t upwatch-backend:asr .
#
# 在 docker-compose.yml 里通过 build.target 切换。

ARG PYTHON_VERSION=3.11

# ============================================================
# base
# ============================================================
FROM python:${PYTHON_VERSION}-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

# 编译期工具 + 运行期工具(ffmpeg 给 ASR 用,基础也带上保持一致)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libffi-dev \
        curl \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ============================================================
# runtime(默认目标)
# ============================================================
FROM base AS runtime

# 先复制依赖描述,单独一层缓存
COPY pyproject.toml README.md ./
# 创建一个最小的 app/__init__.py 让 pip install -e 不会失败
RUN mkdir -p app && touch app/__init__.py

# 安装核心依赖
RUN pip install --upgrade pip \
 && pip install -e "."

# 再复制源码(源码变动不会让 pip 这一层失效)
COPY app ./app

# 数据目录(SQLite + Milvus Lite + 语料)
RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ============================================================
# asr(可选,带本地 ASR 推理)
# ============================================================
FROM runtime AS asr

# 装 ASR 额外依赖(torch + qwen-asr + transformers)
RUN pip install -e ".[asr]"

# 默认设备;模型路径由运行时通过环境变量传入
ENV QWEN_ASR_DEVICE=cuda:0