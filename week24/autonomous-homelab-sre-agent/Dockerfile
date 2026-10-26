FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /bin/

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=0 \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH" \
    LANGGRAPH_STRICT_MSGPACK=true \
    PYTHONDONTWRITEBYTECODE=1 \
    W24_PROJECT_ROOT=/app \
    W24_DATA_DIR=/data

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY README.md ./
COPY src ./src
COPY vault ./vault
COPY evals ./evals
RUN uv sync --locked --no-dev --no-editable \
    && rm -f /bin/uv /bin/uvx \
    && mkdir -p /data /app/vault/reports \
    && chown 65532:65532 /data /app/vault/reports

USER 65532:65532
ENTRYPOINT ["w24-sre"]
CMD ["eval"]
