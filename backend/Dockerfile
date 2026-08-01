# syntax=docker/dockerfile:1

FROM python:3.13-slim

# ffmpeg and ffprobe are run as subprocesses by the mux stage. The python
# packages that bundle their own ffmpeg are not used: PyAV's unsigned DLLs are
# blocked by Smart App Control on the dev machine, so the pipeline drives the
# system binary instead.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    PYTHONUNBUFFERED=1

# Dependencies first, in their own layer. Application code changes on every
# commit; the lockfile does not, so this layer stays cached across deploys.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .

EXPOSE 8000

# Shell form so $PORT expands. Railway assigns it at runtime and it is not set
# at build time, so the exec form would pass the literal string through.
#
# One worker, deliberately. The job queue lives in this process's memory, so a
# second worker would get its own private queue and jobs would vanish into
# whichever one happened to answer.
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
