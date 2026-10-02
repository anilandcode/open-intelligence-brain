#!/usr/bin/env bash
# The container's entrypoint: one image, three processes, in a deliberate order.
#
#   proxy (loopback)  →  engine (loopback)  →  app (0.0.0.0:$PORT)
#
# Why one container instead of two Cloud Run services. The engine mints its own
# API key on first boot and ignores SUPERMEMORY_API_KEY, so a second service
# would have to have that key harvested out of its logs and pasted into the
# app's environment — and re-harvested on every cold start, because a fresh
# instance mints a fresh key. Co-located, none of that exists: the engine only
# ever listens on loopback, the entrypoint reads the key the engine just wrote
# and hands it to the app before the app starts, and the app's engine calls are
# localhost calls, which the engine auto-authenticates. The free tier also bills
# per instance, so two services would cost two ceilings for one product.
#
# Why this file is a supervisor rather than an `exec`. The engine and the app
# both have to be alive at the same time, so no single process can be PID 1 by
# `exec`. The trap forwards SIGTERM (Cloud Run's stop signal, and the whole
# reason a stop is a stop rather than a 10-second timeout); `wait -n` takes the
# container down if any one of the three dies, so a half-dead instance is
# replaced rather than left serving 500s from an engine that is no longer there.
#
# Ordering matters for a second reason: Cloud Run only starts sending traffic
# once the container listens on $PORT, and the app is the last thing to start, so
# the instance is never marked ready with a cold engine behind it.
set -euo pipefail

ENGINE_BIN="${ENGINE_BIN:-/usr/local/bin/supermemory-server}"
PROXY_PORT="${PROXY_LISTEN_PORT:-6799}"
PROXY_ADDR="127.0.0.1:${PROXY_PORT}"
ENGINE_PORT="${SUPERMEMORY_ENGINE_PORT:-6767}"
APP_PORT="${PORT:-8080}"
DATA_DIR="${SUPERMEMORY_DATA_DIR:-/tmp/.supermemory}"
# The three container paths, overridable so this script can be exercised
# outside the image (host python, repo paths) instead of only inside a build.
PROXY_SCRIPT="${PROXY_SCRIPT:-/opt/engine/llm_proxy.py}"
APP_DIR="${APP_DIR:-/srv/api}"
UVICORN="${UVICORN:-uvicorn}"

die() { printf 'entrypoint: %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- guard rails
# Without an upstream the engine accepts every document and extracts nothing
# from any of them: a brain that fills with sources and never produces a
# proposal. That failure is silent — the engine's own log says only that a
# memory agent completed — so it is refused here instead of diagnosed later.
[ -n "${PROXY_UPSTREAM:-}" ] || die "PROXY_UPSTREAM is not set. Set it to the
  OpenAI-compatible provider base URL (…/v1) or the engine will extract nothing."
[ -n "${PROXY_API_KEY:-}" ] || die "PROXY_API_KEY is not set. The proxy holds the
  real provider key so the engine never sees it; without it every model call 401s."

# The engine appends /chat/completions to OPENAI_BASE_URL and the upstream
# already ends in /v1, so this default deliberately carries no /v1 of its own:
# with one, every call would land on …/v1/v1/chat/completions and 404.
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-http://${PROXY_ADDR}}"
case "${OPENAI_BASE_URL}" in
  *"${PROXY_ADDR}"*) ;;
  *) printf 'entrypoint: warning: OPENAI_BASE_URL=%s bypasses the proxy at %s;\n' \
       "${OPENAI_BASE_URL}" "${PROXY_ADDR}" >&2
     printf '  the provider edge blocks this engine with 403 and extraction will\n' >&2
     printf '  silently produce nothing.\n' >&2 ;;
esac
# A dummy: the real key lives in the proxy, one process away from the engine.
export OPENAI_API_KEY="${OPENAI_API_KEY:-proxy-injects-the-real-key}"

export SUPERMEMORY_PORT="${ENGINE_PORT}"
# Not sufficient on its own: the engine prefers a bare PORT, so see the engine
# launch below for why PORT is also pinned for that process.
export SUPERMEMORY_DATA_DIR="${DATA_DIR}"
mkdir -p "${DATA_DIR}"

# Seed local embedding weights into the writable data dir. Cloud Run's /tmp is
# an empty tmpfs every cold start, so the image cannot rely on files baked under
# SUPERMEMORY_DATA_DIR surviving. The image keeps a copy under
# SUPERMEMORY_MODELS_CACHE (default /opt/engine/models); we copy once per boot
# when the cache is missing so the engine never hits Hugging Face at runtime
# (HF 429 on Google egress was the hosted "degraded / no model provider" cause).
MODELS_CACHE="${SUPERMEMORY_MODELS_CACHE:-/opt/engine/models}"
MODELS_DEST="${DATA_DIR}/models"
if [ -d "${MODELS_CACHE}" ] && [ ! -f "${MODELS_DEST}/Xenova/bge-base-en-v1.5/onnx/model_quantized.onnx" ]; then
  mkdir -p "${MODELS_DEST}"
  # cp -a preserves structure; fail soft so a missing cache does not block boot
  # of an app-only image, but log loudly — extraction still needs these weights.
  if cp -a "${MODELS_CACHE}/." "${MODELS_DEST}/"; then
    echo "entrypoint: seeded embedding models from ${MODELS_CACHE} -> ${MODELS_DEST}"
  else
    echo "entrypoint: warning: could not seed embedding models from ${MODELS_CACHE}" >&2
  fi
fi

# The engine prints its own API key on every boot. It is only reachable on
# loopback, but a container's stdout is a log that outlives the instance, so the
# key is redacted on its way out instead of being archived in Cloud Logging.
#
# `sed -u` keeps lines from sitting in a 4 KB buffer, which matters when the only
# view of a cold start is the log; it is a GNU extension, so it is probed rather
# than assumed. No `\b` for the same reason: it is not in BSD sed's ERE, and this
# filter has to run on the host too.
SED_UNBUFFERED=""
if sed -u '' </dev/null >/dev/null 2>&1; then SED_UNBUFFERED="-u"; fi
exec > >(sed $SED_UNBUFFERED -E 's/sm_[A-Za-z0-9_-]{16,}/sm_[redacted]/g') 2>&1

wait_for_port() {
  local port="$1" pid="$2" label="$3" tries="${4:-150}"
  local i
  for i in $(seq 1 "$tries"); do
    if python3 - "$port" <<'PY' 2>/dev/null
import socket, sys
s = socket.socket()
s.settimeout(0.3)
try:
    s.connect(("127.0.0.1", int(sys.argv[1])))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
    then
      echo "entrypoint: ${label} ready on 127.0.0.1:${port} after ~$((i / 5))s"
      return 0
    fi
    kill -0 "$pid" 2>/dev/null || die "${label} exited during startup"
    sleep 0.2
  done
  die "${label} did not listen on ${port} within $((tries / 5))s"
}

# ------------------------------------------------------------------ 1: proxy
python3 "$PROXY_SCRIPT" & PROXY_PID=$!
wait_for_port "$PROXY_PORT" "$PROXY_PID" "proxy" 300

# ----------------------------------------------------------------- 2: engine
# 600 tries = 120s. The engine measured ~10s to first listen on a warm M-series
# Mac; a 1-vCPU Cloud Run cold start is slower than that, and budget here is far
# cheaper than a container that dies and gets retried.
# A bare PORT wins over SUPERMEMORY_PORT inside the engine — proved by it binding
# the app's port on a host run with both set — and Cloud Run always defines PORT.
# Left alone, the engine seizes the port the platform routes app traffic to,
# uvicorn fails to bind, and the container dies on every start. Pinned per-process
# so the engine gets its own port and the app keeps PORT.
PORT="${ENGINE_PORT}" SUPERMEMORY_PORT="${ENGINE_PORT}" "$ENGINE_BIN" & ENGINE_PID=$!
wait_for_port "$ENGINE_PORT" "$ENGINE_PID" "engine" 600

# The engine writes its key before it opens the socket, so by this point the file
# is already there; the loop is for the case where a future build reorders that.
KEY_FILE=""
for _ in $(seq 1 50); do
  KEY_FILE="$(find "${DATA_DIR}" -maxdepth 2 -name api-key -type f 2>/dev/null | head -1)"
  [ -n "$KEY_FILE" ] && break
  sleep 0.2
done
[ -n "$KEY_FILE" ] || die "engine never wrote an api-key file under ${DATA_DIR}"

# -------------------------------------------------------------------- 3: app
export BRAIN_SUPERMEMORY_BASE_URL="http://127.0.0.1:${ENGINE_PORT}"
export BRAIN_SUPERMEMORY_API_KEY="$(tr -d '\r\n' < "$KEY_FILE")"
# Strict local mode is NOT what its name suggests: api/brain/engine.py swaps in
# the deterministic engine and refuses this self-hosted one too, so it stays off.
unset BRAIN_STRICT_LOCAL

cd "$APP_DIR"
"$UVICORN" brain.main:app --host 0.0.0.0 --port "${APP_PORT}" & APP_PID=$!
# 900 tries = 180s. The app's startup runs Base.metadata.create_all plus the
# column migrations over Postgres (Neon), which on a cold pool can exceed the
# 60s this used to allow — and a miss here is a crash-looping container, not a
# slow one. 180s sits under Cloud Run's 240s startup-probe budget (the proxy +
# engine take ~10s of it), so a slow-but-fine boot survives instead of being
# killed mid-migration.
wait_for_port "$APP_PORT" "$APP_PID" "app" 900
echo "entrypoint: up — app on ${APP_PORT}, engine on ${ENGINE_PORT} (key from ${KEY_FILE})"

trap 'kill -TERM "$APP_PID" "$ENGINE_PID" "$PROXY_PID" 2>/dev/null || true; wait; exit 0' TERM INT
wait -n
