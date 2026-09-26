# Official Python image manifest verified against Docker Hub on 2026-09-26.
FROM python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /build

COPY pyproject.toml README.md LICENSE.txt ./
COPY src ./src
RUN python -m pip install "build>=1.3,<2" \
    && python -m build --wheel --outdir /dist


FROM python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 AS runtime-base

ENV HOME=/home/qig \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MAGICK_TEMPORARY_PATH=/tmp \
    TMPDIR=/tmp

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        libmagickcore-6.q16-6-extra \
        libmagickwand-6.q16-6 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 qig \
    && useradd --uid 10001 --gid qig --home-dir /home/qig \
        --shell /usr/sbin/nologin --no-create-home qig \
    && install -d -o qig -g qig /app /config /home/qig /output

COPY --from=builder /dist/*.whl /tmp/dist/
RUN python -m pip install /tmp/dist/*.whl \
    && rm -rf /tmp/dist
COPY --chown=10001:10001 config.yaml /config/config.yaml

WORKDIR /app
USER 10001:10001


# CI-only target: fixture-backed rendering without credentials or network calls.
FROM runtime-base AS smoke

COPY --chown=10001:10001 scripts/offline_render_smoke.py /smoke/offline_render_smoke.py
COPY --chown=10001:10001 tests/fixtures/verse_one_translation.json /smoke/verse.json
ENTRYPOINT ["python", "/smoke/offline_render_smoke.py"]
CMD ["--fixture", "/smoke/verse.json", "--output-dir", "/output"]


FROM runtime-base AS runtime

VOLUME ["/config", "/output"]
ENTRYPOINT ["quran-image-generator"]
CMD ["--config", "/config/config.yaml", "--output-dir", "/output", "--no-open"]
