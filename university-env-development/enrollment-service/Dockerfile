# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.12

# ---------- Stage 1 : build des dépendances ----------
FROM python:${PYTHON_VERSION}-slim AS builder

WORKDIR /build

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------- Stage 2 : image finale minimale ----------
FROM python:${PYTHON_VERSION}-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp

# libpq5 : lib client runtime pour psycopg2 (pas besoin des headers de dev)
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && pip uninstall -y pip setuptools 2>/dev/null || true \
    && groupadd -g 1000 appgroup \
    && useradd -u 1000 -g appgroup -M -s /usr/sbin/nologin appuser

WORKDIR /app

COPY --from=builder /install /usr/local
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini wsgi.py entrypoint.sh gunicorn.conf.py ./

RUN chmod +x entrypoint.sh && chown -R appuser:appgroup /app

USER appuser

EXPOSE 5003

ENTRYPOINT ["./entrypoint.sh"]