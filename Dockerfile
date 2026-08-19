# One image, two processes: `gunicorn wsgi:app` and `python3 -m jobmatch.worker`.
# They share it deliberately — the worker is the same code with a different
# entrypoint, and a second image would be a second thing to keep in step.
#
# The base is Microsoft's Playwright image because the `profesia` adapter drives
# a real Chromium and the system libraries it needs (~40 of them) are already
# installed and already versioned against the browser. Installing them by hand
# on a slim base is how you find out at 2am that one is missing.
#
# It is big — 3.8 GB before any of our code, since it carries Firefox and WebKit
# we never launch. Deleting those saves nothing: they live in a base layer, and
# a `rm` in a later layer only hides them. Splitting web onto a slim base
# wouldn't help either, because the same box still pulls this one for the
# worker. So: one image, sized for a VPS disk rather than for a scale-to-zero
# PaaS — which is the trade DEPLOY.md picks a VPS for in the first place.
#
# PLAYWRIGHT_VERSION pins both halves of that contract in one place: the image
# tag ships the browser binaries, and the pip package has to be the version that
# knows where they are. Bump them together or Chromium is "not found".
ARG PLAYWRIGHT_VERSION=1.62.0

# ── Builder: wheels only, so no pip cache or toolchain reaches the runtime ──
FROM mcr.microsoft.com/playwright/python:v${PLAYWRIGHT_VERSION}-noble AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# The Playwright image ships Ubuntu's python3 without ensurepip, so `venv` is an
# apt package away. Builder-only: the runtime stage just runs out of the copied
# venv, which needs nothing but the interpreter it points at.
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Re-pinned after requirements.txt (which only floors it): the pip package must
# match the browsers baked into the base image.
ARG PLAYWRIGHT_VERSION
RUN pip install "playwright==${PLAYWRIGHT_VERSION}"


# ── Runtime ────────────────────────────────────────────────────────────────
FROM mcr.microsoft.com/playwright/python:v${PLAYWRIGHT_VERSION}-noble

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    DATA_DIR=/app/data

COPY --from=builder /opt/venv /opt/venv

# Non-root, with a fixed uid so a bind-mounted DATA_DIR has predictable
# ownership on the host. The Playwright image runs its browsers as a normal
# user anyway — `--no-sandbox` in scan.py is what makes Chromium agree to it.
RUN useradd --create-home --uid 10001 jobmatch

WORKDIR /app
COPY --chown=jobmatch:jobmatch . .

# CVs live here (`config.resume_path`), and so does the SQLite file if anyone
# runs this image without Postgres. Created before the volume mount so the
# directory is owned by jobmatch either way.
RUN mkdir -p /app/data/resumes && chown -R jobmatch:jobmatch /app/data

USER jobmatch

EXPOSE 8000

# Overridden by the worker service in docker-compose.yml. Two workers because
# `wsgi.py` is safe with several as of Phase 4 — scan state is in the `scans`
# row, not in a module global — and one is a single slow request away from
# looking down. The timeout is generous: a CV upload parses a PDF inline.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120", \
     "--access-logfile", "-", "--error-logfile", "-", "wsgi:app"]
