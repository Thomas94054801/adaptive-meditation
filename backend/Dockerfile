# Adaptive Meditation API.
#
# Built from the repository root so the knowledge files ship inside the image:
#   docker build -f backend/Dockerfile -t adaptive-meditation-api .
#
# The base image is multi-architecture, so this builds natively on the ARM64
# OCI Ampere A1 target and on an Apple Silicon workstation without emulation.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

# Non-root from the start; the application never needs to write to its own tree.
RUN groupadd --system app && useradd --system --gid app --home-dir /srv --shell /usr/sbin/nologin app

# Dependencies first so a source-only change does not reinstall them.
COPY backend/pyproject.toml backend/README.md ./backend/
COPY backend/app ./backend/app
RUN python -m pip install --no-cache-dir ./backend

COPY backend/alembic.ini ./backend/
COPY backend/migrations ./backend/migrations
COPY knowledge ./knowledge

# The package is installed into site-packages, so KNOWLEDGE_DIR must be explicit
# rather than resolved relative to the source tree.
ENV KNOWLEDGE_DIR=/srv/knowledge \
    APP_ENV=production

USER app
EXPOSE 8000

# No AI or TTS credential is baked in. Secrets arrive from the runtime
# environment; none is required for the service to start and recommend.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz').read()"

# Two workers matches the 2 OCPU target and stays well inside the 768 MB ceiling.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
