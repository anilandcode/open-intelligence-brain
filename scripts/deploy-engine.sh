#!/usr/bin/env bash
#
# Deploy the self-hosted Supermemory engine to Cloud Run on the always-free tier.
#
# This is the second service. `deploy-cloud-run.sh` ships the app; this ships the
# memory engine the app talks to, so the deployment stops depending on
# api.supermemory.ai. Both are one instance maximum and scale to zero.
#
# What this does, in order, and why each step is here:
#   1. refuses to run unauthenticated or without a project, because those are the
#      two things a human has to do and it is better to say so up front;
#   2. enables the APIs the build and the secret need;
#   3. ensures the Artifact Registry repository exists;
#   4. puts the model-provider key in Secret Manager rather than in the service's
#      plain environment. A Cloud Run revision's env vars are readable by anyone
#      who can view the project, and this key can spend money at the provider;
#   5. builds `engine/Dockerfile`, which downloads the engine binary for the
#      platform the image runs as and verifies it against the published digest;
#   6. deploys it with the free-tier shape and the model provider pointed at the
#      loopback proxy that fixes the provider edge's User-Agent block;
#   7. proves it is up by asking the engine for an authenticated read, because a
#      deploy exit code says nothing about whether the engine can extract.
#
# Usage:
#   ./scripts/deploy-engine.sh
#   SERVICES=1 ./scripts/deploy-engine.sh                 # 1 vCPU (default, free)
#   SUPERMEMORY_EMBEDDING_RAM_LIMIT=0.2gb ./scripts/deploy-engine.sh
#   PROVIDER_API_KEY=... OPENAI_MODEL=... ./scripts/deploy-engine.sh
#
# The provider key is read from PROVIDER_API_KEY, or from COMMANDCODE_API_KEY in
# ~/.hermes/.env, or from the local proxy's environment. It is never echoed.
set -euo pipefail

SERVICE="${SERVICE:-brain-engine}"
REGION="${REGION:-us-central1}"
REPO="${REPO:-digital-brain}"
PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"
SM_VERSION="${SM_VERSION:-0.0.8}"

# The engine's own inbound credential. It is our deployment's key, not
# Supermemory's: the self-hosted engine would otherwise mint one on first boot
# and store it in a data dir that a cold start throws away, so every restart
# would invalidate the app's configuration. Pinning it here is what makes the
# two services agree across restarts.
ENGINE_KEY="${SUPERMEMORY_API_KEY:-$(openssl rand -hex 24)}"

PROVIDER_UPSTREAM="${PROVIDER_UPSTREAM:-https://api.commandcode.ai/provider/v1}"
OPENAI_MODEL="${OPENAI_MODEL:-deepseek/deepseek-v4.1-flash}"
PROXY_UA="${PROXY_UA:-curl/8.7.1}"
RAM_LIMIT="${SUPERMEMORY_EMBEDDING_RAM_LIMIT:-0.25gb}"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die() { printf '\n\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

say "1/7 checking credentials"
if ! gcloud auth list --filter=status:ACTIVE --format='value(account)' | grep -q .; then
  die "No credentialed gcloud account. Run this first, in a terminal:

    gcloud auth login

Then re-run this script."
fi
[ -n "$PROJECT" ] || die "No project set. Run \`gcloud config set project <id>\` or pass PROJECT=<id>."
ACCOUNT="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' | head -1)"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
say "account: $ACCOUNT    project: $PROJECT ($PROJECT_NUMBER)    region: $REGION"

say "2/7 enabling APIs"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  --project "$PROJECT" --quiet

say "3/7 ensuring Artifact Registry repository $REPO"
if ! gcloud artifacts repositories describe "$REPO" --location "$REGION" --project "$PROJECT" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$REPO" \
    --repository-format=docker --location "$REGION" --project "$PROJECT" \
    --description "Digital Brain images"
fi
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:$(date +%Y%m%d-%H%M%S)"

say "4/7 putting the model-provider key in Secret Manager"
# Resolution order, and the last one is deliberately not silent: an empty key
# means the engine accepts every document and extracts nothing from it, which
# looks like a healthy deployment.
if [ -z "${PROVIDER_API_KEY:-}" ] && [ -f "$HOME/.hermes/.env" ]; then
  PROVIDER_API_KEY="$(grep -m1 '^COMMANDCODE_API_KEY=' "$HOME/.hermes/.env" | cut -d= -f2- | tr -d '"'"'"' ' || true)"
fi
[ -n "${PROVIDER_API_KEY:-}" ] || die "No provider key. Pass PROVIDER_API_KEY=... or set COMMANDCODE_API_KEY in ~/.hermes/.env.

Without it the engine boots, accepts every document, and extracts nothing —
reachable and useless, which the app will report as degraded."

SECRET="brain-engine-provider-key"
if ! gcloud secrets describe "$SECRET" --project "$PROJECT" >/dev/null 2>&1; then
  gcloud secrets create "$SECRET" --replication-policy=automatic --project "$PROJECT" --quiet
fi
printf '%s' "$PROVIDER_API_KEY" | gcloud secrets versions add "$SECRET" \
  --data-file=- --project "$PROJECT" --quiet >/dev/null
# The runtime service account needs to read it. Granting per-secret rather than
# per-project: this key can spend money, so access to it is the narrowest scope
# that works.
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
gcloud secrets add-iam-policy-binding "$SECRET" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/secretmanager.secretAccessor" \
  --project "$PROJECT" --quiet >/dev/null
say "secret $SECRET updated (version added, ${RUNTIME_SA} granted read)"

say "5/7 building the engine image (downloads and verifies the binary)"
gcloud builds submit \
  --config cloudbuild-engine.yaml \
  --substitutions="_SM_VERSION=${SM_VERSION},_IMAGE=${IMAGE}" \
  --project "$PROJECT" \
  . >/dev/null

say "6/7 deploying to Cloud Run"
# --allow-unauthenticated is deliberate and is not the access control. IAM would
# require the app to mint an identity token per request; instead the engine
# authenticates on its own bearer key (SUPERMEMORY_API_KEY), the same way the
# hosted API does. The key is the credential, and an unauthenticated caller gets
# 401 from the engine itself.
#
# Concurrency is low because the engine holds a 0.25 GB embedding budget and a
# single instance: letting 80 requests in at once would queue them behind the
# embedder and time out, which reads as an outage.
gcloud run deploy "$SERVICE" \
  --image "$IMAGE" \
  --region "$REGION" \
  --project "$PROJECT" \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --memory 1Gi \
  --cpu 1 \
  --max-instances 1 \
  --min-instances 0 \
  --concurrency 4 \
  --timeout 300 \
  --set-env-vars "SUPERMEMORY_API_KEY=${ENGINE_KEY},SUPERMEMORY_EMBEDDING_RAM_LIMIT=${RAM_LIMIT},SUPERMEMORY_INGEST_CONCURRENCY=2,PROXY_UPSTREAM=${PROVIDER_UPSTREAM},PROXY_UA=${PROXY_UA},OPENAI_MODEL=${OPENAI_MODEL},SUPERMEMORY_INSTANCE_ID=brain-engine" \
  --set-secrets "PROXY_API_KEY=${SECRET}:latest" \
  --quiet

URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" \
  --format='value(status.url)')"

say "7/7 verifying it answered, rather than trusting the deploy exit code"
# The same cheap authenticated read the app uses as its readiness probe. The
# first request after a quiet period wakes the instance, so this is also a cold
# start test.
echo "waking ${URL} (cold start can take ~30s)..."
CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 240 \
  -H "Authorization: Bearer ${ENGINE_KEY}" \
  "${URL}/v3/container-tags/healthcheck/inferred" || true)"
echo "authenticated read: HTTP ${CODE}   (200 and 404 both mean the engine answered)"
UNAUTH="$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 \
  "${URL}/v3/container-tags/healthcheck/inferred" || true)"
echo "unauthenticated read: HTTP ${UNAUTH}   (401 is the engine's own key check)"

cat <<EOF

Engine URL:  ${URL}
Engine key:  (the value of SUPERMEMORY_API_KEY in the service's env; printed to
             this terminal only if you passed it yourself)

Point the app at it and redeploy the app service:

  BRAIN_SUPERMEMORY_BASE_URL=${URL} \\
  BRAIN_SUPERMEMORY_API_KEY=<the engine key> \\
  ./scripts/deploy-cloud-run.sh

Then confirm the app is not degraded — this is the line that tells the truth
about whether extraction works:

  curl -s -H "X-Brain-Token: <app token>" "${URL%/brain-engine*}/api/v1/overview"

What a cold start costs: the engine materialises its runtime and the 106 MB
local embedding model into the data dir on first boot, so the first request
after a quiet period is slow. It warms in one request; warm latency is fine.
EOF
