FROM python:3.11-slim

ARG PIP_INDEX_URL=""
ARG PLAYWRIGHT_DOWNLOAD_HOST=""

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BILINOVEL_HOST=0.0.0.0 \
    BILINOVEL_PORT=8765 \
    BILINOVEL_DATA_DIR=/data

WORKDIR /app

# 安装 Python 依赖与 Playwright Chromium 及其全部 Linux 系统运行库
# 国内服务器构建时可传入：
#   --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
#   --build-arg PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir ${PIP_INDEX_URL:+-i $PIP_INDEX_URL} -r /app/requirements.txt \
    && PLAYWRIGHT_DOWNLOAD_HOST="${PLAYWRIGHT_DOWNLOAD_HOST}" playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

# 复制项目核心代码与前端静态资源
COPY browser_launcher.py gui_service.py launch_gui.py rubbish_secret_map.py runtime_env.py scrape_linovelib.py text_converter.py to_epub.py start_server.sh /app/
COPY gui /app/gui
RUN chmod +x /app/start_server.sh && mkdir -p /data

VOLUME ["/data"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=3)" || exit 1

CMD ["python", "launch_gui.py", "--web", "--no-browser", "--host", "0.0.0.0", "--port", "8765"]
