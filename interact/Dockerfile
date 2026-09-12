FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app
COPY interact/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && playwright install --with-deps chromium

COPY common /app/common
COPY interact /app/interact

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /ms-playwright \
    && chown -R appuser:appuser /app /ms-playwright
USER appuser
