FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY planner/requirements.txt /app/planner/requirements.txt
RUN pip install --no-cache-dir -r /app/planner/requirements.txt

COPY common /app/common
COPY planner /app/planner

RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

CMD ["uvicorn", "planner.app:app", "--host", "0.0.0.0", "--port", "8093"]
