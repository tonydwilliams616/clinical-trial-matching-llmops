# syntax=docker/dockerfile:1
#
# Three stages, like the PII gateway:
#   base    - Python deps + app code
#   test    - base + pytest; the build FAILS if any test fails
#   runtime - base, run as a non-root user (the image that gets pushed)
#
#   docker build --target test -t agent-worker:test .   runs the tests
#   docker build -t agent-worker:local .                builds runtime only

FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app/ app/

FROM base AS test
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt
COPY tests/ tests/
RUN python -m pytest -q

FROM base AS runtime
ARG GIT_SHA=dev
ENV GIT_SHA=${GIT_SHA}
# Fixed numeric UID so Kubernetes can enforce runAsNonRoot
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
USER 10001
CMD ["python", "-m", "app.worker"]
