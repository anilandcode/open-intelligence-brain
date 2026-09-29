# Free hosted deployment — plan

Goal: the whole Digital Brain setup online, publicly reachable, at $0, with no
Supermemory cloud API and no new paid accounts.

Status: partly implemented, 2026-09-27. Step 1 (one origin) is done — the
frontend is served by the API, and the frontend resolves its API from its own
origin in a production build. Cloud Run artifacts exist and the image is built
and run locally. See `docs/deploy-cloud-run.md` and `docs/harness.md`. Step 2
(the engine under 1 GB) is measured, not open — the engine fits in 246 MB at
`SUPERMEMORY_EMBEDDING_RAM_LIMIT=0.25gb`. The deploy itself is waiting on
`gcloud auth login`.
"Measured locally" below records the real blocker: a provider edge that rejects
the engine's own HTTP client.

## The constraint that decides everything

The self-hosted engine, on its own boot log:

```
[ingest] memory limit 1.0 GB above baseline (0.1 GB)
embeddings  local · Xenova/bge-base-en-v1.5 · 768d
```

So the engine wants **~1.1 GB of RAM**: 0.1 GB baseline plus a 1.0 GB
embedding budget. Its footprint on disk is 258 MB binary + 106 MB of model
weights.

Every genuinely-free application host in the table below sits at or below
1 GB. That single mismatch is why "host everything free, publicly" is harder
than it looks, and it is worth knowing before building anything.

The lever exists: the binary reads `SUPERMEMORY_EMBEDDING_RAM_LIMIT` and
`SUPERMEMORY_LOCAL_EMBEDDING_MODEL`. Whether the engine can run inside 1 GB
with a smaller embedding budget is an experiment, not an assumption. **That
experiment is step 2 below and everything else branches on its result.**

## Component map

| Component | Footprint | Free home | Status |
|---|---|---|---|
| Frontend (static) | ~1 MB | Cloudflare Pages / Vercel | builds today |
| FastAPI backend | 112 MB venv, 5,091 lines | Cloud Run (1 GB, 0.083 vCPU) | fits |
| Database | — | Neon free (Postgres, scale-to-zero) | wired: project `digital-brain`, deploy loads URL via Secret Manager |
| Memory engine | 1.1 GB RAM, 364 MB disk | **no verified free home** | the blocker |
| LLM | — | operator's own key | already have one |

## Why each option is in or out

**Cloud Run free — 2M requests/month, 1 GB, 0.083 vCPU.** Fits the backend
comfortably. Two real costs: instances scale to zero, so the first request after
a quiet minute takes roughly 30s, which is awkward mid-demo; and the 1 GB
ceiling is exactly the engine problem above.

**Neon free over Supabase free.** Both are Postgres. Neon scales compute to
zero and does not pause the project, so a demo link stays alive. Supabase free
pauses after one week of inactivity, which means returning to a cold database
and re-establishing that it still exists. For a demo that will be left alone,
Neon is the better fit. Supabase is the better fit if the team later wants auth
and storage in the same place.

**Cloudflare Workers — ruled out for the backend.** Free plan gives 10 ms of
CPU per request. The overview endpoint alone does an auth check, a workspace
count, an activity query, and an engine probe. Persistence would also mean
rewriting the SQLAlchemy data layer against D1, which is a port, not a deploy.
The frontend on Pages is fine; the API is not.

**Vercel — ruled out.** Free tier is static plus serverless functions. The
backend is a long-running process.

**Supermemory cloud — ruled out deliberately.** This is the point of the
exercise. The engine is MIT licensed and prints its own key on first boot, so
the cloud API is opt-in, never required. Invariant 21 records this.

**The company-brain deploy button — not our path.** Its own
`.dev.vars.example` marks `SUPERMEMORY_API_KEY` as required, "this is where the
brain reads and writes memory," fetched from `console.supermemory.ai`. It is a
Slack agent runtime on Workers, not a governed knowledge system, and it is the
opposite of getting off their cloud.

## Options

### A. Everything on this laptop, one tunnel

```
cloudflared tunnel --url http://localhost:8000
```

Backend, SQLite database, and the engine all run here. The tunnel gives a
public `trycloudflare.com` URL. No account, no signup, no CORS work once the
app is served from a single origin.

Cost: $0. Limits: this machine must stay awake, and the URL changes each run.
Realistic life: a day or two, or as long as the laptop is on.

### B. Hosted app, engine on this laptop

Cloud Run serves the API and Pages serves the frontend; Neon holds the data;
the engine stays here and is reached over a second tunnel.

Gains a durable public URL and a real Postgres. Costs a fragile cross-network
dependency: if the laptop sleeps, extraction stops and the engine reports
`degraded` — which the interface now shows honestly, but it is a worse demo.

### C. Fully hosted, engine included — needs the step 2 experiment

If the engine can run inside Cloud Run's 1 GB with a reduced embedding budget,
then Cloud Run can host the backend and the engine as two services, and the
whole thing is durable and free with no laptop dependency.

If it cannot, this option is closed on free tiers, and the honest answer is
that the memory engine is the one component with no free public home.

## Recommendation

Ship A first. It is one command, it exercises every layer including the engine,
and it de-risks the demo today. Then run the step 2 experiment, because its
result decides whether C is real. Take B only if a durable URL matters more
than the engine being local.

## Steps

1. **Serve from one origin.** Mount the built frontend on the FastAPI app and
   make the frontend resolve its API from `window.location` instead of the
   hardcoded `http://localhost:8000`. Removes CORS from the picture entirely
   and makes any single tunnel a complete working URL. Needs no credentials.
   **Done 2026-09-27** — see `docs/deploy-cloud-run.md`.
2. **Test the engine at reduced memory.** Set
   `SUPERMEMORY_EMBEDDING_RAM_LIMIT` low and measure actual RSS under load.
   Decides option C.
3. **Point the engine at the operator's own OpenAI-compatible key.** Already
   supported (`OPENAI_API_KEY` + `OPENAI_BASE_URL` + `OPENAI_MODEL`); the engine
   currently reports `degraded` only because no model is configured. No
   Supermemory cloud, no Cloudflare account, no marginal cost.
4. **Postgres path.** **Done.** Neon project `digital-brain` holds production
   data; `~/.digital-brain/neon-database-url` is the local handle; deploy puts
   it in Secret Manager. Dev still defaults to SQLite; Compose uses local
   Postgres 16. Restart gate proven against the live Neon instance.
5. **Tunnel and demo.** One command, verified end to end.

## Measured locally (2026-09-27)

Four things came out of running the real engine against the real app. The first
two change the deploy; the third is a bug that was fixed; the fourth is what is
now verified.

**1. The RAM lever works, but only in the right unit.** `SUPERMEMORY_EMBEDDING_RAM_LIMIT=256m` is *silently ignored* — the engine boots with its default 1.0 GB embedding budget and the boot log still reads `memory limit 1.0 GB above baseline`. The value must carry a `gb` suffix: with `0.25gb` the same line reads `memory limit 0.3 GB above baseline (0.1 GB)`. Measured RSS with that budget, after the engine had processed roughly twenty documents: **246 MB**. That fits Cloud Run's 1 GB free ceiling with room to spare, so option C is no longer blocked by memory — it is blocked by point 2.

**2. The provider edge blocks the engine's own HTTP client.** The engine calls its model provider with `python-httpx` as the User-Agent, and that request is answered **403 with a Cloudflare block page**, not JSON. The engine then logs only `memory agent completed (5908ms, 0 memories)`, so the failure looks like "the model returned nothing" rather than "the request never reached a model". Sending an ordinary client User-Agent on the same request returns 200. A deployed engine therefore needs a UA-overriding sidecar in front of its provider — a 40-line logging proxy was enough here — or a provider that does not filter Python clients. Without it, a hosted engine accepts every document and extracts nothing, which is exactly the silent-empty-store failure this project exists to prevent.

**3. The readiness probe was lying.** `SupermemoryEngine.available()` decided "no model provider configured" from a *fixed* probe sentence. The engine de-duplicates semantically, so the second and every later probe found its own earlier facts already in the store, correctly created no new memory, and the check reported a perfectly healthy engine as having no model. The probe text now carries a per-run reference token, and the status flips from `degraded` to `reachable` — verified in the running app.

**4. What is verified end to end, live.** Capture through the API → engine extraction → proposal → human approval → canonical knowledge, with the engine told the decision. Extraction produced four to five correct atomic facts per document, splitting compound sentences and preserving entities and reference numbers. The engine-derived path is proven against real engine data, not a stub: proposal `prop_c4d01286cf1d4a11` (approved) carries engine memory id `YNYvV1ETgxDpEgwRj1haX3` and reached canonical knowledge as `know_27e4ff78a1f74b10`. Note the engine's own rule: an inferred fact is served as `isInference: true` only *until* a human approves it, after which the flag clears — so the review queue is self-clearing and re-syncing one source cannot re-raise a decided fact.

## What this plan does not solve

- Team membership, org hierarchy, and per-team ACLs. `ReadScope` enforces role
  sensitivity, but companies buy "my marketing team can read marketing," and
  that layer does not exist yet.
- Pagination, vector search, and a durable job queue. Fine at demo scale, not
  at company scale.
- Free tiers are for demos and side projects. Cloud Run's cold starts and
  Neon's scale-to-zero are acceptable until someone depends on them, and no
  longer after that.
