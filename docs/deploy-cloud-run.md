# Deploying to Cloud Run (Google Cloud free tier)

Written 2026-09-27. Everything here was built and verified locally; the deploy
itself has one step only a human can do, and it is the first one.

## What is already done

- **One image, one origin.** `Dockerfile` builds the frontend and the API into a
  single image, so the service answers the app and its data from one host. CORS
  is no longer part of the deployment question at all.
- **The frontend resolves its API from its own origin** in a production build
  (`web/src/api.ts`); only the dev server still points at `localhost:8000`.
- **The image was built and run.** 373 MB, both stages, and inside the container:
  `/` serves the app, `/assets/…` serves the bundle, an unknown `/api/v1/…` is a
  404, `/health/ready` answers `ready`, an authenticated call returns real data,
  and an unauthenticated one returns 401.
- **A real bug was found by running it.** `httpx` was declared only as a dev
  dependency while `brain/engine.py` imports it at module import, so the
  container failed on startup while every local test passed. It is now a runtime
  dependency.
- **`cloudbuild.yaml`** builds the image with no token in it at all. Vite inlines
  every `VITE_*` variable into the JavaScript it ships, so a token passed to the
  build would be readable by anyone who loaded the page. The owner token exists
  only in the service's runtime environment; the page asks for it and sends it
  back as `X-Brain-Token`.
- **`scripts/deploy-cloud-run.sh`** does the rest in five steps.

## The one step that needs you

```bash
gcloud auth login
```

`gcloud` is installed (SDK 586.0.0) but has **no credentialed account**, so this
cannot be done on your behalf — it opens a browser. A billing account must also
be attached to the project: Cloud Run has a permanent free tier, but it is part
of a billed project. No charge is expected inside the free limits.

## Then

```bash
cd "/Users/macmini/Projects/Digital Brain"
gcloud config set project <your-project-id>
./scripts/deploy-cloud-run.sh
```

The script enables the APIs, creates the Artifact Registry repository, builds,
deploys, and prints the URL plus a verification block. It generates a fresh owner
token unless you pass `BRAIN_OWNER_TOKEN=…`.

## Verify, rather than trust the exit code

```bash
URL=$(gcloud run services describe digital-brain --region us-central1 --format='value(status.url)')
curl -s "$URL/health/ready"; echo
curl -s -o /dev/null -w '%{http_code}\n' "$URL/api/v1/overview"          # 401
curl -s -H "X-Brain-Token: $TOKEN" "$URL/api/v1/overview" | head -c 200  # data
```

## What the free tier costs you, honestly

- **Cold starts.** `--min-instances 0` means the first request after a quiet
  period takes roughly 30s. That is a real demo problem and it is the price of
  $0.
- **Hosted data lives on Neon Postgres.** The image still *defaults* to
  `sqlite:////tmp/brain.db` so a container boots without extra accounts, but
  `scripts/deploy-cloud-run.sh` treats Neon as the hosted path: it loads
  `~/.digital-brain/neon-database-url` (or `BRAIN_DATABASE_URL` from the
  environment) and stores it in Secret Manager as `brain-database-url`, mounted
  into the service as `BRAIN_DATABASE_URL`. Never put the URL in a plain service
  env var — those are readable in the console. The Neon project used here is
  `digital-brain` (`ancient-queen-28972054`, aws-us-east-1, pooled). Restart
  proof against that project: capture → approve → new process → search +
  grounded chat still work. Local day-to-day stays SQLite or Compose Postgres.
- **The token is not in the bundle.** The image is built tokenless, so the served
  JavaScript contains no credential: an unauthenticated visitor gets an access
  gate that requests nothing and discloses nothing. The token lives only in the
  service's runtime environment, which is still worth keeping throwaway on a
  hosted demo — Cloud Run environment variables are readable by anyone with
  project access, and a Brain holding anything real deserves an owner token that
  is not shared with a demo.
- **The memory engine is in the image.** Boot order is proxy → engine → app.
  `SUPERMEMORY_EMBEDDING_RAM_LIMIT=0.25gb` keeps the embedding budget small;
  deploy uses **4 GiB / 1 vCPU / concurrency 1 / min-instances 0** because a
  2 GiB instance OOMs once the baked local model is resident (~1.2 GB baseline
  + extraction peak). Idle is $0 (scale-to-zero). Cloud Run free tier is
  ~360k GB-seconds/month ≈ **~25 hours of a 4 GiB instance** — enough for
  demos if you stay at min-instances 0; avoid always-on. A $10 monthly credit
  covers light overage, not a warm instance left up all month.
- **Embedding weights are baked, not downloaded at runtime.** The engine's local
  model is `Xenova/bge-base-en-v1.5` (~110 MB quantized ONNX). On Cloud Run,
  `/tmp` is an empty tmpfs every cold start, and Hugging Face often 429s Google
  egress — a first document then finishes with zero memories and the API reports
  `degraded` even when `PROXY_API_KEY` is correct. `scripts/fetch-embedding-model.sh`
  downloads the weights at image build time into `/opt/engine/models`;
  `engine/entrypoint.sh` copies them into `SUPERMEMORY_DATA_DIR/models` before
  the engine starts.
- **One instance, no coordination.** `--max-instances 1` is deliberate: turns are
  database rows with no lease, so more than one writer is untested. Concurrency
  is 1 so free-tier memory peaks stay predictable.

## If the engine has to be hosted too

It already is, in the merged image. Remaining hosted work is operational: keep
the provider key and Neon URL in Secret Manager, grant the runtime SA
`secretmanager.secretAccessor` (the deploy script fails hard if that grant
fails), and verify `engine.degraded === false` on `/api/v1/overview` after a
cold start — not just `/health/ready`.
