# NetKâr API ve worker imajı (aynı imaj, farklı komut). Çok aşamalı, root olmayan kullanıcı.
# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.13

# ---- Derleme aşaması: uv ile bağımlılıkları kurar ----------------------------
FROM python:${PYTHON_VERSION}-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app

# Önce yalnız bağımlılıklar (katman önbelleği), sonra kod.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

# ---- Çalışma aşaması: derleyici ve uv yok --------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime
RUN groupadd --system --gid 10001 netkar \
 && useradd --system --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin netkar
COPY --from=build /opt/venv /opt/venv
COPY --from=build /app /app
ENV PATH="/opt/venv/bin:${PATH}" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/v1/health', timeout=2).status == 200 else 1)"]
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
