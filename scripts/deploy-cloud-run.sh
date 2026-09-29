#!/usr/bin/env bash
#
# Deploy the Digital Brain to Cloud Run on the always-free tier.
#
# The image now contains the app *and* the self-hosted memory engine — see
# Dockerfile. One service, one URL, one instance ceiling: the engine is not a
# second service because it mints its own API key on first boot and a co-located
# engine needs no key plumbing at all (engine/entrypoint.sh reads the key it just
# wrote and hands it to the app before the app starts).
#
# That leaves exactly one credential to place: the model provider key the
# engine's extraction agent drives. It goes into Secret Manager, not into the
# service's plain environment — a service env var is readable in the console, in
# `gcloud run services describe`, and in the deploy logs.
#
# What this does, in order, and why each step is here:
#   1. refuses to run unauthenticated, because `gcloud auth login` is the one
#      step that has to be done by a human and it is better to say so up front
#      than to fail three commands later;
#   2. enables the APIs a Cloud Run source deploy needs;
#   3. creates the Artifact Registry repository if it does not exist, because
#      the first push otherwise fails on a missing repo;
#   4. puts the provider key in Secret Manager and grants the runtime service
#      account access to it;
#   5. builds the image with no token in it at all — Vite inlines every VITE_*
#      variable into the served JavaScript, so a token passed to the build would
#      be readable by anyone who loaded the page;
#   6. deploys it with the free-tier shape: 1 instance maximum, 2 GiB, scaled to
#      zero. 2 GiB and not 1 GiB because the engine materialises a 172 MB runtime
#      into /tmp — tmpfs, which counts against the instance — and a 1 GiB
#      instance was measured dying at 1062 MiB while booting, before the app ever
#      bound its port.
#
# Usage:
#   ./scripts/deploy-cloud-run.sh                 # fresh token, key from ~/.hermes/.env
#   PROXY_API_KEY=... ./scripts/deploy-cloud-run.sh
#   BRAIN_OWNER_TOKEN=... ./scripts/deploy-cloud-run.sh
#   PROJECT=my-proj REGION=europe-west1 ./scripts/deploy-cloud-run.sh
#   BRAIN_DATABASE_URL=postgresql+psycopg://... ./scripts/deploy-cloud-run.sh
#
set -euo pipefail

SERVICE="${SERVICE:-digital-brain}"
REGION="${REGION:-us-central1}"
REPO="${REPO:-digital-brain}"
PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"
SEED_DEMO="${BRAIN_SEED_DEMO:-true}"
SECRET="${SECRET:-brain-provider-key}"
ENV_FILE="${ENV_FILE:-$HOME/.hermes/.env}"
# The provider the engine reaches through the loopback proxy, and the model its
# extraction agent drives. Both defaults are the pair verified end-to-end.
PROXY_UPSTREAM="${PROXY_UPSTREAM:-https://api.commandcode.ai/provider/v1}"
OPENAI_MODEL="${OPENAI_MODEL:-deepseek/deepseek-v4.1-flash}"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die() { printf '\n\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

say "1/6 checking credentials"
if ! gcloud auth list --filter=status:ACTIVE --format='value(account)' | grep -q .; then
  die "No credentialed gcloud account. Run this first, in a terminal:

    gcloud auth login

Then re-run this script. Everything after this step is autonomous."
fi
[ -n "$PROJECT" ] || die "No project set. Run \`gcloud config set project <id>\` or pass PROJECT=<id>."
ACCOUNT="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' | head -1)"
say "account: $ACCOUNT    project: $PROJECT    region: $REGION"

say "2/6 enabling APIs (no-ops if already enabled)"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  --project "$PROJECT" --quiet

say "3/6 ensuring Artifact Registry repository $REPO"
if ! gcloud artifacts repositories describe "$REPO" --location "$REGION" --project "$PROJECT" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$REPO" \
    --repository-format=docker --location "$REGION" --project "$PROJECT" \
    --description "Digital Brain images"
fi
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:$(date +%Y%m%d-%H%M%S)"

# The engine extracts nothing without a working model provider, and it fails
# silently when it has none, so this refuses to deploy a brain that would accept
# every document and produce no memories. Taken from the environment first, then
# from the local Hermes env file. Never echoed.
say "4/6 placing the model provider key in Secret Manager ($SECRET)"
if [ -z "${PROXY_API_KEY:-}" ] && [ -f "$ENV_FILE" ]; then
  PROXY_API_KEY="$(grep -E '^COMMANDCODE_API_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '\r\n"' | tr -d "'")"
fi
[ -n "${PROXY_API_KEY:-}" ] || die "No provider key. Pass PROXY_API_KEY=... or put COMMANDCODE_API_KEY=... in $ENV_FILE.

Without it the engine accepts every document and extracts nothing from any of
them — the silent-empty-store failure this project exists to prevent."

if ! gcloud secrets describe "$SECRET" --project "$PROJECT" >/dev/null 2>&1; then
  gcloud secrets create "$SECRET" --project "$PROJECT" --replication-policy=automatic \
    --labels=app=digital-brain
fi
printf '%s' "$PROXY_API_KEY" | gcloud secrets versions add "$SECRET" \
  --project "$PROJECT" --data-file=- >/dev/null
echo "  key stored as a new version of $SECRET (value not printed)"

# The runtime service account has to be allowed to read it. Cloud Run uses the
# default compute account unless one was chosen at deploy time.
RUNTIME_SA="${RUNTIME_SA:-$(gcloud iam service-accounts list --project "$PROJECT" \
  --filter='displayName:Compute Engine default service account' --format='value(email)' | head -1)}"
if [ -z "$RUNTIME_SA" ]; then
  PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
  RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
fi
if [ -n "$RUNTIME_SA" ]; then
  gcloud secrets add-iam-policy-binding "$SECRET" \
    --project "$PROJECT" --member="serviceAccount:${RUNTIME_SA}" \
    --role=roles/secretmanager.secretAccessor --quiet >/dev/null \
    && echo "  ${RUNTIME_SA} may read $SECRET" \
    || die "Could not grant ${RUNTIME_SA} roles/secretmanager.secretAccessor on $SECRET"
fi

# The owner token is set only at runtime now. It is not a build input, because
# Vite inlines every VITE_* variable into the served JavaScript — a token baked
# into the bundle is readable by anyone who loads the page. Generating one keeps
# a fresh deployment from shipping the source tree's dev token.
TOKEN="${BRAIN_OWNER_TOKEN:-$(openssl rand -hex 24)}"

say "5/6 building image (frontend + API + memory engine)"
gcloud builds submit \
  --config cloudbuild.yaml \
  --substitutions="_IMAGE=${IMAGE}" \
  --project "$PROJECT" \
  .

say "6/6 deploying to Cloud Run"
# BRAIN_SUPERMEMORY_BASE_URL and BRAIN_SUPERMEMORY_API_KEY are deliberately NOT
# set here: the entrypoint exports both from the engine it just started, and a
# copy in the service environment could only ever disagree with the engine that
# is actually running.
# Hosted default is Neon Postgres. Order of resolution:
#   1. BRAIN_DATABASE_URL in the environment (explicit override)
#   2. $HOME/.digital-brain/neon-database-url (written by neonctl setup)
#   3. image default sqlite:////tmp/brain.db (ephemeral only — cold start wipes it)
# The URL is a live credential, so it goes into Secret Manager like the provider
# key — never a plain service env var (those are readable in the console and in
# `gcloud run services describe`).
DB_SECRET="${DB_SECRET:-brain-database-url}"
NEON_URL_FILE="${NEON_URL_FILE:-$HOME/.digital-brain/neon-database-url}"
if [ -z "${BRAIN_DATABASE_URL:-}" ] && [ -f "$NEON_URL_FILE" ]; then
  BRAIN_DATABASE_URL="$(tr -d '\r\n' < "$NEON_URL_FILE")"
  echo "  database URL loaded from $NEON_URL_FILE (value not printed)"
fi
SECRET_BINDS="PROXY_API_KEY=${SECRET}:latest"
if [ -n "${BRAIN_DATABASE_URL:-}" ]; then
  if ! gcloud secrets describe "$DB_SECRET" --project "$PROJECT" >/dev/null 2>&1; then
    gcloud secrets create "$DB_SECRET" --project "$PROJECT" --replication-policy=automatic \
      --labels=app=digital-brain
  fi
  printf '%s' "$BRAIN_DATABASE_URL" | gcloud secrets versions add "$DB_SECRET" \
    --project "$PROJECT" --data-file=- >/dev/null
  echo "  database URL stored as a new version of $DB_SECRET (value not printed)"
  if [ -n "${RUNTIME_SA:-}" ]; then
    gcloud secrets add-iam-policy-binding "$DB_SECRET" \
      --project "$PROJECT" --member="serviceAccount:${RUNTIME_SA}" \
      --role=roles/secretmanager.secretAccessor --quiet >/dev/null \
      && echo "  ${RUNTIME_SA} may read $DB_SECRET" \
      || die "Could not grant ${RUNTIME_SA} roles/secretmanager.secretAccessor on $DB_SECRET"
  fi
  SECRET_BINDS="${SECRET_BINDS},BRAIN_DATABASE_URL=${DB_SECRET}:latest"
else
  echo "  WARNING: no BRAIN_DATABASE_URL — deploying with ephemeral /tmp SQLite."
  echo "  Data will not survive a cold start. Create Neon and write the URL to"
  echo "  $NEON_URL_FILE (postgresql+psycopg://…, mode 600) before a real ship."
fi

# A file, not --set-env-vars: a token on gcloud's argv is visible to `ps` and is
# written verbatim into gcloud's own ~/.config/gcloud/logs — the same class of
# leak as the bundle. 0600, and removed on exit.
ENV_FILE_YAML="$(mktemp "${TMPDIR:-/tmp}/brain-env.XXXXXX.yaml")"
chmod 600 "$ENV_FILE_YAML"
trap 'rm -f "$ENV_FILE_YAML"' EXIT
{
  printf 'BRAIN_OWNER_TOKEN: "%s"\n' "$TOKEN"
  printf 'BRAIN_SEED_DEMO: "%s"\n' "$SEED_DEMO"
  printf 'PROXY_UPSTREAM: "%s"\n' "$PROXY_UPSTREAM"
  printf 'OPENAI_MODEL: "%s"\n' "$OPENAI_MODEL"
} > "$ENV_FILE_YAML"

gcloud run deploy "$SERVICE" \
  --image "$IMAGE" \
  --region "$REGION" \
  --project "$PROJECT" \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --memory 4Gi \
  --cpu 1 \
  --max-instances 1 \
  --min-instances 0 \
  --concurrency 1 \
  --timeout 300 \
  --env-vars-file "$ENV_FILE_YAML" \
  --set-secrets "$SECRET_BINDS" \
  --quiet

URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" \
  --format='value(status.url)')"

say "deployed: $URL"

TOKEN_FILE="${BRAIN_TOKEN_FILE:-$HOME/.digital-brain/owner-token.txt}"
mkdir -p "$(dirname "$TOKEN_FILE")" && umask 077 && printf '%s\n' "$TOKEN" > "$TOKEN_FILE"

cat <<EOF

Owner token for this deployment was written to a file, not printed — a credential
in stdout ends up in shell scrollback, tee'd logs and CI logs alike:
  ${TOKEN_FILE}   (mode 600, runtime env only, never in the bundle)
  cat "${TOKEN_FILE}"     # paste the value into the page's access gate

Opening the page without it shows an access gate rather than the workspace:
  open "${URL}"

The first request after a quiet period takes roughly 40s, not 30s: the free tier
scales to zero, and the instance that comes up has to boot the engine before the
app starts listening. The engine's own boot is ~18s on a warm machine.

Verify it is actually up, rather than trusting the deploy exit code:
  curl -s "${URL}/health/ready"; echo
  curl -s -o /dev/null -w '%{http_code}\n' "${URL}/api/v1/overview"
  curl -s -H "X-Brain-Token: \$(cat ${TOKEN_FILE})" "${URL}/api/v1/overview" | head -c 200; echo

And verify the engine is actually extracting, which a 200 never proves — a
configured-but-blocked provider looks identical to an empty store from outside:
  gcloud logging read 'resource.labels.service_name="${SERVICE}" AND
    textPayload=~"\\-> POST /chat/completions"' --project "${PROJECT}" --limit 5
  gcloud logging read 'resource.labels.service_name="${SERVICE}" AND
    textPayload=~"<- 200"' --project "${PROJECT}" --limit 5
EOF
