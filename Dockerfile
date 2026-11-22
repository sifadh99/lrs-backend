# syntax=docker/dockerfile:1
# GetCode API image.  Build:  docker build -t lrs-backend:dev .
#
# Two stages: "builder" installs the Python packages into a virtualenv,
# "runtime" copies only that virtualenv + our code. pip's caches and anything
# needed just for installing never reach the final image.

ARG PYTHON_VERSION=3.14

# ---------- stage 1: install dependencies ----------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# --without-pip: the venv gets no pip of its own (14 MB). The builder's pip installs
# INTO it with --python, so the final image has no package installer at all.
RUN python -m venv --without-pip /opt/venv

# Only requirements.txt first: this layer (the slow pip install) is reused from the
# build cache until the requirements change, not on every code change.
COPY requirements.txt .
RUN pip --python /opt/venv/bin/python install -r requirements.txt


# ---------- stage 2: what actually runs ----------
FROM python:${PYTHON_VERSION}-slim AS runtime

# PYTHONDONTWRITEBYTECODE: no .pyc files at runtime (the filesystem may be read-only)
# PYTHONUNBUFFERED: print/log lines go out at once, so `docker logs` is never behind
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    FORWARDED_ALLOW_IPS=127.0.0.1

# A fixed, unprivileged user. If someone breaks into the app they are not root,
# and the fixed UID lets Kubernetes enforce runAsNonRoot / runAsUser later.
# Also remove the base image's own pip: nothing should install packages at runtime, and
# image scanners stop flagging pip CVEs. (Size stays: the files live in a base layer.)
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
 && python -m pip uninstall --yes --quiet pip

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
# Code is owned by root and only readable by "app": the app cannot rewrite itself.
COPY app ./app
COPY migrations ./migrations
COPY seed ./seed

USER 10001:10001
EXPOSE 8000

# Docker / compose use this; Kubernetes ignores it and uses its own probes.
# Python's urllib, because the slim image has no curl.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]

# exec form (JSON array): uvicorn is PID 1 and gets SIGTERM directly -> graceful shutdown.
# --proxy-headers: trust X-Forwarded-For only from the IPs in FORWARDED_ALLOW_IPS
# (compose/k8s set it to the proxy), so login lockout sees the real client IP.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
