FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        chromium \
        fonts-liberation \
        fonts-noto-cjk \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY --chown=10001:10001 app ./app
COPY --chown=10001:10001 static ./static
COPY --chown=10001:10001 scripts ./scripts
COPY --chown=10001:10001 README.md pyproject.toml ./

RUN groupadd --gid 10001 speechflow \
    && useradd --uid 10001 --gid 10001 --create-home speechflow \
    && mkdir -p /data/jobs /data/backups \
    && chown -R 10001:10001 /app /data

USER speechflow

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=3)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765", "--proxy-headers", "--forwarded-allow-ips=*"]
