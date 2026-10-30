# Multi-stage image for Render Free / local runs.
# Embedding model is baked at build time (no download on cold start).
FROM python:3.11-slim AS builder

WORKDIR /build
RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md uv.lock ./
COPY app ./app

# Install project into a relocatable venv
RUN uv sync --frozen --no-dev --no-editable \
    && uv pip install --python .venv/bin/python -e .

# Pre-download ONNX embedding model into a known cache dir
ENV FASTEMBED_CACHE_PATH=/build/model_cache
RUN mkdir -p /build/model_cache \
    && .venv/bin/python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5')"

FROM python:3.11-slim AS runtime

ARG GIT_COMMIT=unknown

RUN useradd --create-home --uid 10001 appuser
WORKDIR /app

COPY --from=builder /build/.venv /app/.venv
COPY --from=builder /build/app /app/app
COPY --from=builder /build/model_cache /app/model_cache
COPY alembic.ini pyproject.toml README.md ./

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    FASTEMBED_CACHE_PATH=/app/model_cache \
    EMBEDDING_ENABLED_AT_STARTUP=false \
    ENABLE_BENCH_ENDPOINTS=false \
    PORT=8000 \
    HOME=/home/appuser \
    GIT_COMMIT=${GIT_COMMIT}

RUN chown -R appuser:appuser /app /home/appuser

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"

CMD ["sh", "-c", "exec /app/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
