# syntax=docker/dockerfile:1
#
# The self-hosted Supermemory engine, as a container the free tier can run.
#
# The engine is published as per-platform single-file binaries, so this image
# downloads the one for the platform it is being built for and verifies it
# against the digest in `scripts/fetch-engine.sh`. The script is the single
# source of truth for asset name, size and sha256: the alternative was repeating
# those numbers here, which is how a pinned digest silently stops matching the
# thing it pins.
#
# It is a Bun-compiled binary, not a native server, which is worth knowing
# before trying to read its flags: `supermemory-server --help` prints Bun's own
# help menu. The configuration surface is environment variables, extracted from
# the binary rather than guessed — SUPERMEMORY_PORT, SUPERMEMORY_DATA_DIR,
# SUPERMEMORY_API_KEY, SUPERMEMORY_EMBEDDING_RAM_LIMIT, the
# SUPERMEMORY_LOCAL_EMBEDDING_* family, and OPENAI_BASE_URL / OPENAI_MODEL for
# the model provider.
#
# Build (from the repository root, so the fetch script is in the context):
#   docker buildx build --platform linux/amd64 -f engine/Dockerfile -t brain-engine .
#
# The second reason this file exists: the engine's own HTTP client is refused by
# the provider's edge. See engine/llm_proxy.py.

ARG VERSION=0.0.8

# ---------------------------------------------------------------- fetch stage
FROM debian:bookworm-slim AS engine
ARG VERSION
ARG TARGETARCH

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY scripts/fetch-engine.sh /tmp/fetch-engine.sh

# SM_PLATFORM is set explicitly rather than left to `uname`: built under
# emulation on an Apple Silicon host, `uname` reports the host and would put a
# darwin-arm64 binary in a linux image. TARGETARCH is what the image will
# actually run as.
RUN set -eux; \
    case "${TARGETARCH}" in \
      amd64) SM_PLATFORM="Linux/x86_64" ;; \
      arm64) SM_PLATFORM="Linux/aarch64" ;; \
      *) echo "no published engine build for TARGETARCH=${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    SM_VERSION="${VERSION}" SM_PLATFORM="${SM_PLATFORM}" bash /tmp/fetch-engine.sh /out; \
    cp /out/supermemory-server-* /out/supermemory-server; \
    chmod +x /out/supermemory-server

# -------------------------------------------------------------- runtime stage
FROM python:3.12-slim AS runtime

# Bundled CA roots: the proxy talks HTTPS to the provider. libstdc++6 and
# libgcc-s1 are what a Bun single-file binary links against.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates libstdc++6 libgcc-s1 \
 && rm -rf /var/lib/apt/lists/*

COPY --from=engine /out/supermemory-server /usr/local/bin/supermemory-server
COPY engine/llm_proxy.py engine/entrypoint.sh /opt/engine/
RUN chmod +x /opt/engine/entrypoint.sh

# Boot should be quiet and offline-ish: no telemetry, no update check, no
# startup animation, no attempt to open a browser on a machine with no display.
ENV PYTHONUNBUFFERED=1 \
    SUPERMEMORY_PORT=8080 \
    SUPERMEMORY_DATA_DIR=/tmp/.supermemory \
    SUPERMEMORY_DISABLE_TELEMETRY=true \
    SUPERMEMORY_NO_UPDATE_CHECK=true \
    SUPERMEMORY_NO_STARTUP_ANIMATION=true \
    SUPERMEMORY_NO_OPEN=true \
    SUPERMEMORY_NO_COLOR=true \
    PROXY_LISTEN_HOST=127.0.0.1 \
    PROXY_LISTEN_PORT=6799 \
    PROXY_UA=curl/8.7.1

# 0.25gb is measured, not guessed: the default 1.0 GB embedding budget does not
# fit a 1 GiB instance, and the bare `256m` form is silently ignored — the value
# must carry a `gb` suffix. At 0.25gb the engine boots reporting a 0.3 GB budget
# and held a measured 246 MB RSS after ~20 documents.
ENV SUPERMEMORY_EMBEDDING_RAM_LIMIT=0.25gb

# /tmp is the writable path on Cloud Run. The engine materialises its runtime
# (pglite, onnxruntime, the embedding worker) into the data dir on first boot,
# so this is also where the local embedding model lands.
EXPOSE 8080

ENTRYPOINT ["/opt/engine/entrypoint.sh"]
