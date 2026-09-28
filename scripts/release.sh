#!/usr/bin/env bash
# release.sh — package the Brain for distribution.
#
# Usage: ./scripts/release.sh [version]
#
# Creates a release bundle with:
# - Backend (Python package)
# - Frontend (built static files)
# - Docker image
# - Documentation
# - Hermes skill
#
# The bundle is ready for deployment to Cloud Run, Docker, or local install.

set -euo pipefail

VERSION="${1:-$(git describe --tags --always --dirty 2>/dev/null || echo 'dev')}"
DIST_DIR="dist/release"
BUNDLE_NAME="open-intelligence-brain-${VERSION}"

echo "🧠 Packaging Open Intelligence Brain ${VERSION}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Clean
rm -rf "${DIST_DIR}"
mkdir -p "${DIST_DIR}/${BUNDLE_NAME}"

# Build frontend
echo "📦 Building frontend..."
cd web && npm run build && cd ..
cp -r web/dist "${DIST_DIR}/${BUNDLE_NAME}/frontend"

# Copy backend
echo "📦 Packaging backend..."
cp -r api "${DIST_DIR}/${BUNDLE_NAME}/api"
cp requirements.txt "${DIST_DIR}/${BUNDLE_NAME}/" 2>/dev/null || true
cp pyproject.toml "${DIST_DIR}/${BUNDLE_NAME}/" 2>/dev/null || true

# Copy config
echo "📦 Copying configuration..."
cp Dockerfile "${DIST_DIR}/${BUNDLE_NAME}/"
cp docker-compose.yml "${DIST_DIR}/${BUNDLE_NAME}/"
cp Makefile "${DIST_DIR}/${BUNDLE_NAME}/"
cp .env.example "${DIST_DIR}/${BUNDLE_NAME}/" 2>/dev/null || true
cp AGENTS.md "${DIST_DIR}/${BUNDLE_NAME}/"

# Copy docs
echo "📦 Copying documentation..."
cp -r docs "${DIST_DIR}/${BUNDLE_NAME}/"
cp README.md "${DIST_DIR}/${BUNDLE_NAME}/"
cp CHANGELOG.md "${DIST_DIR}/${BUNDLE_NAME}/"
cp LICENSE "${DIST_DIR}/${BUNDLE_NAME}/" 2>/dev/null || true

# Copy Hermes skill
echo "📦 Copying Hermes skill..."
cp -r hermes-skill "${DIST_DIR}/${BUNDLE_NAME}/"

# Copy scripts
echo "📦 Copying scripts..."
cp -r scripts "${DIST_DIR}/${BUNDLE_NAME}/"

# Create archive
echo "📦 Creating archive..."
cd "${DIST_DIR}"
tar -czf "${BUNDLE_NAME}.tar.gz" "${BUNDLE_NAME}"
cd ../..

echo ""
echo "✅ Release bundle: ${DIST_DIR}/${BUNDLE_NAME}.tar.gz"
echo ""
echo "To deploy:"
echo "  Docker:  docker compose up --build"
echo "  Local:   make install && make dev-api && make dev-web"
echo "  Cloud:   ./scripts/deploy-cloud-run.sh"
echo "  Hermes:  cp -r hermes-skill/ ~/.hermes/skills/digital-brain/"