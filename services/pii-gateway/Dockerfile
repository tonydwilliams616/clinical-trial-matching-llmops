# syntax=docker/dockerfile:1
#
# Three stages:
#   base    - Python deps + the spaCy language model + app code
#   test    - base + pytest; the build FAILS if any test fails
#   runtime - base, run as a non-root user (the image that gets pushed)
#
#   docker build --target test -t pii-gateway:test .   runs the tests
#   docker build -t pii-gateway:local .                builds runtime only

FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

# The model is baked into the image: pods run in private subnets with no
# internet route, so nothing may be downloaded at start-up.
ARG SPACY_MODEL_URL=https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.8.0/en_core_web_lg-3.8.0-py3-none-any.whl
RUN pip install "${SPACY_MODEL_URL}"

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
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
