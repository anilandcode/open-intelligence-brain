#!/usr/bin/env bash
# Fetch the local embedding weights the self-hosted engine expects.
#
# The engine defaults to Xenova/bge-base-en-v1.5 (768d). On a workstation the
# first document triggers a Hugging Face download into SUPERMEMORY_DATA_DIR/models.
# On Cloud Run that fails: /tmp is an empty tmpfs every cold start, and HF often
# answers Google egress with 429. A document then finalises with zero memories
# and the app honestly reports degraded — even when PROXY_API_KEY is correct.
#
# Bake the weights at image build time (this script), ship them under
# /opt/engine/models (outside /tmp), and let entrypoint copy them into the
# data dir before the engine starts. Embedding then needs no egress.
#
# Usage: scripts/fetch-embedding-model.sh [dest-dir]
# Default dest: ~/.supermemory/models
set -euo pipefail

REPO="${SM_EMBEDDING_REPO:-Xenova/bge-base-en-v1.5}"
DEST_DIR="${1:-$HOME/.supermemory/models}/${REPO}"
BASE_URL="https://huggingface.co/${REPO}/resolve/main"

# Paths relative to the model root. Quantized ONNX is the default transformers.js
# pick (~110 MB); full fp32 is ~436 MB and is not needed for the free-tier budget.
FILES=(
  "config.json:717"
  "tokenizer.json:711396"
  "tokenizer_config.json:366"
  "special_tokens_map.json:125"
  "vocab.txt:231508"
  "quantize_config.json:674"
  "onnx/model_quantized.onnx:110083337"
)

mkdir -p "${DEST_DIR}/onnx"

echo "repo     : ${REPO}"
echo "target   : ${DEST_DIR}"

fetch_one() {
  local rel="$1" expect_size="$2"
  local out="${DEST_DIR}/${rel}"
  local url="${BASE_URL}/${rel}"
  mkdir -p "$(dirname "$out")"

  if [ -f "$out" ]; then
    local actual
    actual="$(wc -c <"$out" | tr -d ' ')"
    if [ "$actual" = "$expect_size" ]; then
      echo "  ok ${rel} (${actual} bytes)"
      return 0
    fi
    echo "  partial ${rel} (${actual}/${expect_size}); resuming"
  else
    echo "  get ${rel} (${expect_size} bytes)"
  fi

  # Same stall/retry shape as fetch-engine.sh: HF can accept then crawl.
  curl -fL --http1.1 \
    --connect-timeout 20 \
    --speed-limit 32768 --speed-time 60 \
    --retry 6 --retry-delay 5 --retry-all-errors --retry-max-time 1800 \
    -C - -o "$out" "$url"

  local actual
  actual="$(wc -c <"$out" | tr -d ' ')"
  if [ "$actual" != "$expect_size" ]; then
    echo "size mismatch for ${rel}: got ${actual}, expected ${expect_size}" >&2
    exit 1
  fi
  echo "  ok ${rel}"
}

for entry in "${FILES[@]}"; do
  rel="${entry%%:*}"
  size="${entry##*:}"
  fetch_one "$rel" "$size"
done

echo "embedding model ready at ${DEST_DIR}"
