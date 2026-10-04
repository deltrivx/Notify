# Notify — 多项目通知与交互中枢容器
# 镜像由 GitHub Actions 云端构建并推送 GHCR，禁止本地构建后上传。
FROM python:3.12-alpine

LABEL org.opencontainers.image.title="Notify"
LABEL org.opencontainers.image.description="Unraid multi-project notification and interaction hub"
LABEL org.opencontainers.image.source="https://github.com/deltrivx/Notify"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

# 只装运行期依赖（无编译依赖，alpine 体积小）
COPY app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app/ /app/

# 配置与数据目录（由 compose/run 挂载）
RUN mkdir -p /config /data

ENV CONFIG_DIR=/config \
    DATA_DIR=/data \
    PYTHONUNBUFFERED=1

# 管理界面
EXPOSE 8188

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8188/health', timeout=3)" || exit 1

CMD ["python", "-u", "/app/main.py"]
