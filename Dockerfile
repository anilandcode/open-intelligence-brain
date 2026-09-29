# syntax=docker/dockerfile:1
# check=skip=SecretsUsedInArgOrEnv
#
# The build-time token is not a secret being leaked into an image layer by
# accident: it is the browser's copy of the owner token, and every token the
# browser holds is public by definition. The warning is silenced here so it
# stays meaningful for the places where it matters. Everything a real brain
# holds should therefore live on a deployment with a throwaway token, never the
# owner token of a database that contains anything real.
#
# One image, one origin. The frontend, the API and the memory engine all live in
# this image and run in one container, so a single URL is a complete deployment
# and there is no CORS question to answer.
#
# The engine is in this image rather than a service of its own because of how it
# authenticates: it mints its own API key on first boot and ignores
# SUPERMEMORY_API_KEY, so a separate service would need that key harvested from
# its logs and re-harvested on every cold start. Co-located, the entrypoint reads
# the key the engine just wrote and passes it to the app before the app starts,
# and the app's engine calls are localhost calls, which the engine
# auto-authenticates. It also keeps a free-tier deployment at one instance
# ceiling instead of two.
#
# This reverses the earlier note in this file that the engine could not fit: that
# was written against the engine's default 1.0 GB embedding budget. Measured
# with SUPERMEMORY_EMBEDDING_RAM_LIMIT=0.25gb, the engine settles at ~57-70 MB
# RSS idle with a measured 237 MB peak during prewarm, and materialises a 172 MB
# runtime (rivet + pglite wasm) into its data dir. The local embedding weights
# (~110 MB quantized ONNX) are baked into the image under /opt/engine/models and
# copied into the data dir on boot — /tmp is an empty tmpfs on Cloud Run, and
# Hugging Face 429s Google egress on cold-start download. Engine + model +
# uvicorn fit inside the 2 GiB instance we deploy (1 GiB OOMs at boot).
#
# Boot order is proxy → engine → app, so Cloud Run never marks the instance ready
# while the engine behind it is still cold. Expect ~40s for the first request
# after a quiet period: scale-to-zero start plus the engine's own boot.

# ---------------------------------------------------------------- fetch stage
FROM debian:bookworm-slim AS engine
ARG VERSION=0.0.8

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY scripts/fetch-engine.sh /tmp/fetch-engine.sh

# SM_PLATFORM is set explicitly rather than left to `uname`: built under
# emulation on an Apple Silicon host, `uname` reports the *host* and would put a
# darwin-arm64 binary into a linux image. TARGETARCH (BuildKit's automatic
# platform arg) is what the image will actually run as.
#
# TARGETARCH is empty under the legacy builder, which `docker build` inside
# Cloud Build can still be, and an unmatched empty value would fail the build
# with a confusing "no published engine build" error. So the fallback is
# `uname -m` *inside the build container*, which is always Linux and — in the
# non-emulated builds we actually do — is the target platform. Both spellings of
# each arch are accepted because the two sources spell them differently.
ARG TARGETARCH=
RUN set -eux; \
    ARCH="${TARGETARCH:-$(uname -m)}"; \
    case "${ARCH}" in \
      amd64|x86_64) SM_PLATFORM="Linux/x86_64" ;; \
      arm64|aarch64) SM_PLATFORM="Linux/aarch64" ;; \
      *) echo "no published engine build for arch=${ARCH}" >&2; exit 1 ;; \
    esac; \
    SM_VERSION="${VERSION}" SM_PLATFORM="${SM_PLATFORM}" bash /tmp/fetch-engine.sh /out; \
    cp /out/supermemory-server-* /out/supermemory-server; \
    chmod +x /out/supermemory-server

# Local embedding weights (Xenova/bge-base-en-v1.5). Separate stage so the
# runtime image never needs curl, and so Cloud Build can cache this layer
# independently of the app. Copied to /opt/engine/models — not /tmp — because
# Cloud Run mounts an empty tmpfs over /tmp on every cold start.
FROM debian:bookworm-slim AS embeddings
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY scripts/fetch-embedding-model.sh /tmp/fetch-embedding-model.sh
RUN bash /tmp/fetch-embedding-model.sh /out

# ---------------------------------------------------------------- web stage
FROM node:24-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm ci
COPY web/ ./
# No token is passed in here, and none may be: Vite inlines every `VITE_*`
# variable into the shipped JavaScript, so a build-time token would be readable
# by anyone who opens the page. The bundle is built tokenless and asks for one
# at runtime instead.
RUN npm run build

# ------------------------------------------------------------ runtime stage
FROM python:3.12-slim AS runtime

# Bundled CA roots because the proxy talks HTTPS to the provider. libstdc++6 and
# libgcc-s1 are what the Bun single-file engine binary links against.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates libstdc++6 libgcc-s1 \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /srv/api
COPY api/pyproject.toml api/README-placeholder.md ./
COPY api/brain ./brain
RUN pip install --no-cache-dir .
# The app resolves its static directory as parents[2] / "web" / "dist" from
# brain/main.py, so the image keeps the api/ and web/ layout instead of
# flattening it — otherwise the frontend mounts at a path nothing looks in.
COPY --from=web /web/dist /srv/web/dist

# ------------------------------------------------------------- engine inside
COPY --from=engine /out/supermemory-server /usr/local/bin/supermemory-server
COPY engine/llm_proxy.py engine/entrypoint.sh /opt/engine/
RUN chmod +x /opt/engine/entrypoint.sh
COPY --from=embeddings /out /opt/engine/models

# The engine listens on loopback only. Cloud Run routes nothing but $PORT, so
# this is defence in depth rather than the only thing keeping it private.
ENV SUPERMEMORY_ENGINE_PORT=6767 \
    SUPERMEMORY_DATA_DIR=/tmp/.supermemory \
    SUPERMEMORY_MODELS_CACHE=/opt/engine/models \
    SUPERMEMORY_DISABLE_TELEMETRY=true \
    SUPERMEMORY_NO_UPDATE_CHECK=true \
    SUPERMEMORY_NO_STARTUP_ANIMATION=true \
    SUPERMEMORY_NO_OPEN=true \
    SUPERMEMORY_NO_COLOR=true \
    SUPERMEMORY_MCP=false \
    SUPERMEMORY_RUN_CRONS_AT_BOOT=false \
    PROXY_LISTEN_HOST=127.0.0.1 \
    PROXY_LISTEN_PORT=6799 \
    PROXY_UA=curl/8.7.1

# 0.25gb is measured, not guessed: the default 1.0 GB embedding budget does not
# fit a 1 GiB instance, and the bare `256m` form is silently ignored — the value
# must carry a `gb` suffix. At 0.25gb the engine boots reporting a 0.3 GB budget
# above a 0.1 GB baseline and holds 2 concurrent ingests.
ENV SUPERMEMORY_EMBEDDING_RAM_LIMIT=0.25gb

# The model the engine's extraction agent drives, and the provider it reaches
# through the proxy. Both are overridable at deploy time; the model name is the
# one verified end-to-end against this provider.
ENV OPENAI_MODEL=deepseek/deepseek-v4.1-flash

# /tmp is the writable path on Cloud Run, and it is where the engine materialises
# its runtime. A deployment that must keep data points BRAIN_DATABASE_URL at
# Postgres (Neon free tier, psycopg is already a dependency); a stateless demo
# keeps the default so its disposability is honest rather than accidental.
ENV BRAIN_DATABASE_URL=sqlite:////tmp/brain.db
EXPOSE 8080

ENTRYPOINT ["/opt/engine/entrypoint.sh"]
