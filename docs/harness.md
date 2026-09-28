# The harness layer — event intake, triage, turns

Written 2026-09-27, alongside `api/brain/{harness,triage,turns}.py`.

The Brain used to have one entrance: a human pasted a document and the engine
proposed facts from it. This layer adds the other entrance — an event arrives,
something decides whether to act on it, and if it does, the act is a turn with a
budget, a plan and a gate. The shape is taken from
[supermemoryai/company-brain](https://github.com/supermemoryai/company-brain);
the decisions are ours, and the deliberate differences are listed at the end.

## The invariants

Each one exists to stop a specific failure, and each is pinned by a test in
`api/tests/test_triage.py` and `api/tests/test_turns.py`.

1. **Only three actions exist** — `answer`, `investigate`, `pass`. A model
   cannot invent a fourth, because the parser only recognises these three.
2. **Only a grammatical reply is believed.** A chatty reply ("I think you should
   probably look into this") parses to nothing rather than being read as
   agreement. See `parse_triage`.
3. **An unreadable reply stays silent.** A parse failure on a passive message
   resolves to `pass`, not to a guess. This is the reference runtime's rule and
   it is the right one: an unreadable reply is the one case where acting is
   indistinguishable from guessing.
4. **Being named is the request.** An explicit mention or DM never depended on
   triage, so it is still answered when the reply is unreadable or the model
   says `PASS`. Silence here is the failure users actually notice.
5. **A turn is a row, not a process.** Nothing spawns a background worker. A
   turn is a database row with a status; whoever calls the next step advances
   it. That is what makes "stop" real and makes a restart safe.
6. **The step budget ends a turn cleanly.** At the budget the turn completes
   with `stop_reason=budget_exhausted`; it does not fail and does not continue.
7. **Write tools are unreachable from inside a turn.** Approving a proposal,
   superseding knowledge and restoring a workspace are human decisions. A turn
   that asks for one gets a refusal naming that reason, not a 403 from a role
   check it could be granted later.
8. **The plan is fixed when the turn is created.** A turn cannot add work to its
   own plan, so a step cannot widen the turn's own authority.
9. **A newer question supersedes an older one** in the same channel, and the
   superseded turn records which event displaced it.

## The route surface

| Method | Path | What it does |
|---|---|---|
| POST | `/api/v1/events` | Intake. Classifies, applies policy, triages, creates the turn. |
| GET | `/api/v1/turns` | Turns in the caller's workspace. |
| GET | `/api/v1/turns/{id}` | One turn with its steps and plan. |
| POST | `/api/v1/turns/{id}/step` | Advance one step, spending one unit of budget. |
| POST | `/api/v1/turns/{id}/steer` | Add an instruction to a running turn. |
| POST | `/api/v1/turns/{id}/suspend` | Park the turn for a human decision. |
| POST | `/api/v1/turns/{id}/resume` | Approve or deny, and continue or end. |
| POST | `/api/v1/turns/{id}/stop` | End it now, with a reason. |
| GET/PUT | `/api/v1/proactivity` | Per-channel policy. PUT requires owner or admin. |

## Policy, per channel

`MODES = ("off", "mentions", "contextual", "proactive")`. The default is
`mentions`: the Brain acts when named and stays quiet otherwise. Every downgrade
records the rule that caused it in `TriageDecision.source` — `policy`,
`grammar`, `fallback`, `+floor`, `+evidence`, `+affirmative`, `+disabled` — so a
`pass` is explainable after the fact rather than mysterious.

## Honest differences from the reference

- **Three actions, not four.** company-brain's grammar has `ANSWER | ACK |
  INVESTIGATE | PASS`. Ours folds `ACK` into the reaction field: `answer` reacts
  `white_check_mark`, `investigate` reacts `mag`, `pass` reacts nothing. There is
  no separate "acknowledge only" action.
- **Triage is deterministic, not a model call.** The reference triages with a
  cheap model profile. We have no model configured (see
  `docs/free-hosting-plan.md`), so `TRIAGE_VERSION = "deterministic-triage-v1"`
  is rules over the text, with the model's reply treated as an optional opinion
  that must arrive in the grammar to count. When a key is configured the same
  grammar reads the model's line, so the contract does not change.
- **No Slack.** Intake is a plain HTTP endpoint. The event model has `channel`
  and `author` fields so a Slack or Teams adapter is a translation layer, not a
  rewrite, but no adapter exists yet.
- **No leases, no multi-worker coordination.** The reference runs on Durable
  Objects with leases. Our turns are rows with no lock, which is safe at one
  worker and is the honest limit of this version.
- **Not ported:** automations, skills, the tool catalog, org hierarchy and
  per-team ACLs, the memory tag registry, and the rollout cursors. The
  architecture spec already names the first three as out of scope.
