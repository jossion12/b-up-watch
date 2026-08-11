# syntax=docker/dockerfile:1.7
#
# 多阶段构建:
#   builder : 安装依赖 + 产出静态文件到 /app/dist
#   runtime : nginx:alpine 提供静态文件服务,并把 /api /ws 反代到 backend
#
# 用法:
#   docker build -t upwatch-frontend .

# ============================================================
# builder
# ============================================================
FROM node:20-alpine AS builder

WORKDIR /app

# 单独复制 lock 文件,装依赖
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

# 复制源码并构建
COPY . .
RUN npm run build

# ============================================================
# runtime
# ============================================================
FROM nginx:1.27-alpine AS runtime

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制 nginx 配置(同目录的 nginx.conf)
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q --spider http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]