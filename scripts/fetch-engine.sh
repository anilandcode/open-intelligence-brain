#!/usr/bin/env bash
# Fetch the self-hosted Supermemory engine binary for the current platform.
#
# The engine is published as per-platform binaries. A macOS workstation needs
# the darwin-arm64 build, but every GCP free-tier machine type is linux/amd64 —
# so the asset is resolved from `uname` instead of being hardcoded. Hardcoding
# darwin-arm64 is what made the Cloud Run deploy look impossible.
#
# Every asset below is verified against the sha256 published in the GitHub
# release for the pinned tag. Do not add an entry without its digest.
#
# Usage: scripts/fetch-engine.sh [dest-dir]
#        (default dest-dir: ~/.supermemory/downloads)
#
# SM_PLATFORM overrides asset resolution, e.g. SM_PLATFORM=Linux/x86_64 to
# fetch the asset a linux-x64 container image needs from an arm64 workstation.
set -euo pipefail

VERSION="${SM_VERSION:-0.0.8}"
TAG="server-v${VERSION}"
BASE_URL="https://github.com/supermemoryai/supermemory/releases/download/${TAG}"

DEST_DIR="${1:-$HOME/.supermemory/downloads}"

# Without the override the asset follows the machine we are on, which is right
# for a workstation install and wrong for a container build: an Apple Silicon
# host must still fetch the linux-x64 asset that the deployed image will run.
if [ -n "${SM_PLATFORM:-}" ]; then
  OS="${SM_PLATFORM%%/*}"
  ARCH="${SM_PLATFORM##*/}"
else
  OS="$(uname -s)"
  ARCH="$(uname -m)"
fi

# asset name | size in bytes | sha256
case "${OS}/${ARCH}" in
  Darwin/arm64)
    ASSET="supermemory-server-darwin-arm64"
    SIZE=270741952
    SHA256="12b7817a105ed0a9e70f96c461fb6f8dded5d70eaeb6034e774778c257bed78a"
    ;;
  Linux/x86_64|Linux/amd64)
    ASSET="supermemory-server-linux-x64"
    SIZE=312295037
    SHA256="87f32433d0179be80bb9d8a1bafbac65af4128324342a27ecb8bd1a77b5506f3"
    ;;
  Linux/aarch64|Linux/arm64)
    ASSET="supermemory-server-linux-arm64"
    SIZE=282461981
    SHA256="eeb9e62a8bf59646bd799a05d1a2981b945413a03640c3a39f4f267ad2d2bf37"
    ;;
  *)
    echo "unsupported platform: ${OS}/${ARCH}" >&2
    echo "no published ${TAG} build for it; add an asset + digest to this script." >&2
    exit 1
    ;;
esac

URL="${BASE_URL}/${ASSET}"
OUT="${DEST_DIR}/${ASSET}-${VERSION}"

mkdir -p "${DEST_DIR}"

echo "platform : ${OS}/${ARCH}"
echo "asset    : ${ASSET} (${SIZE} bytes)"
echo "target   : ${OUT}"

# Resumable: a 300 MB download over a flaky link should not restart from zero.
if [ -f "${OUT}" ]; then
  ACTUAL_SIZE="$(wc -c <"${OUT}" | tr -d ' ')"
  if [ "${ACTUAL_SIZE}" = "${SIZE}" ]; then
    echo "already present at full size; verifying digest"
  else
    echo "partial file (${ACTUAL_SIZE} bytes); resuming"
  fi
fi

if [ ! -f "${OUT}" ] || [ "$(wc -c <"${OUT}" | tr -d ' ')" != "${SIZE}" ]; then
  # A 300 MB download must survive a link that accepts the connection and then
  # goes quiet: the failure mode here is a hang, not an error, so plain
  # --retry never fires (a build sat for 56 minutes before err 92). Each flag
  # earns its place:
  #   --speed-limit/--speed-time  turn the hang into a fast, retryable failure
  #   --retry-all-errors          makes err 92 (HTTP/2 stream PROTOCOL_ERROR)
  #                               retryable at all
  #   --http1.1                   sidesteps that HTTP/2 stream bug in the
  #                               release CDN, which is where err 92 came from
  #   -C -                        resumes the partial file (curl also resumes
  #                               across --retry), not a 300 MB restart
  curl -fL \
    --http1.1 \
    --connect-timeout 20 \
    --speed-limit 65536 --speed-time 30 \
    --retry 6 --retry-delay 5 --retry-all-errors --retry-max-time 1200 \
    -C - -o "${OUT}" "${URL}"
fi

# `shasum` ships with macOS, `sha256sum` with coreutils on Linux.
if command -v sha256sum >/dev/null 2>&1; then
  ACTUAL_SHA="$(sha256sum "${OUT}" | awk '{print $1}')"
else
  ACTUAL_SHA="$(shasum -a 256 "${OUT}" | awk '{print $1}')"
fi

if [ "${ACTUAL_SHA}" != "${SHA256}" ]; then
  echo "sha256 mismatch for ${ASSET}" >&2
  echo "  expected ${SHA256}" >&2
  echo "  actual   ${ACTUAL_SHA}" >&2
  rm -f "${OUT}"
  exit 1
fi

chmod +x "${OUT}"
echo "verified : sha256 ${ACTUAL_SHA}"
echo "ready    : ${OUT}"
