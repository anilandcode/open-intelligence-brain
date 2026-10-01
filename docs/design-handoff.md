# Open Brain — design continuation handoff

Prepared 1 October 2026 for another coding agent. This file is the handoff; no agent message, new task, deployment or remote update has been dispatched.

## Assignment

Continue building and refining the accepted Open Brain website and console from the current implementation. Preserve the current composition, typography and feature boundaries. This is a continuation of the existing design, not permission to replace it with a new template. No additional feature/change request is implied by this handoff; obtain the next concrete objective from the user before expanding scope.

## Read first

1. `AGENTS.md` and `docs/design.md` — working boundaries and authoritative design tokens/preferences.
2. `docs/design-structure.md` — exact section hierarchy, anchors, geometry and file ownership.
3. `docs/interface.md` — live/preview matrix and demo isolation.
4. `docs/ui-validation.md` — latest checks and limitations; older results are historical.
5. `docs/ui/caret-html-port.md` and `docs/ui/landing-console-review.md` — source mapping, artwork provenance and later corrections.
6. `docs/architecture.md` before any authentication, citations, approval or persistence changes. For architecture questions, read `graphify-out/GRAPH_REPORT.md` and use the graph/wiki when available.

## Baseline to preserve

- Website: faithful Caret HTML composition, four original scenic/pixel backgrounds, 1024px feature column, numbered patterned feature bands and continuous hairlines. No FAQ or oversized hero app window.
- Buttons: 16px/500 hero and final actions, 14px/500 navigation and chips. Feature paragraphs: 16px mobile and 18px from 768px. Hero support: 18px. Do not regress to thin 10–12px controls or tiny marketing prose.
- Landing wordmark: Open Brain text only. Miniature console brand headers also have no logo icon. Functional knowledge icons remain; actual console/access branding was not changed in that correction.
- Console: full-screen, no scenic wallpaper/frame/blur, 240px sidebar, 48px header, compact Supermemory layout. Subtle rounding: 10px panels, 6px controls, 7px navigation, 4px badges; outer shell 0px.
- Monochrome actions, restrained blue selected navigation, green only semantic status. Keep both console themes.
- Public illustrations are lightweight synthetic React, use shared console tokens and make no production requests. Live failure must never substitute demo records.
- Preserve source/proposal/canonical separation, approval authority, exact citations, immutable source versions, revisions, Studio and context-pack export.

## Workspace and review

Canonical project for this git checkout: `/Users/macmini/Projects/Digital Brain`. Design pack origin may also live under Google Drive `Ai Projects/Digital Brain`. Inspect the current branch, status and diff before changing anything. The design implementation contains substantial existing modified/untracked work; do not discard it or attribute it all to your session.

Frontend: `web/`. Scripts: `npm --prefix web run dev` (console-first, landing off), `npm --prefix web run dev:site` (public Caret landing on), `lint`, `test` (landing on for design suite), `build` (console-first), `build:site` (landing on). Backend checks use the Makefile. `VITE_SHOW_LANDING=true` enables the marketing site; Cloud Run console releases keep the Dockerfile default `false` so visitors get branded login. A temporary dependency/source mirror at `/private/tmp/digital-brain-ui-review` may serve `http://127.0.0.1:5173/#/` when Drive reads stall; it is disposable. Verify against canonical source before using it and copy edits back; never leave the only copy of a change in `/private/tmp`. Original reference checkout was available at `/private/tmp/brain-caret-reference`; if missing, use the supplied Caret repo. Do not depend on temporary paths as project assets.

Latest proofs: `docs/ui/screenshots/landing-console-review/brain-typography-desktop.png`, `brain-typography-features.png`, `docs/ui/screenshots/supermemory-console/rounded-overview.png`. Earlier matched Caret screenshots establish structure but precede later typography/preview refinements.

## Verified status and remaining checks

Latest frontend correction: lint, TypeScript/production build and 19 tests passed. Browser computed checks at 390/768/1440/1920px confirm restored text scale and no page overflow. Mobile hero and desktop hero/reuse band were visually inspected. Backend source/contracts were unchanged and backend tests were not rerun for that correction. Historical isolated backend evidence: 332 passed, 18 PostgreSQL skipped; this does not prove current production behavior.

Graphify refresh from the prior code correction completed: 1900 nodes, 4580 edges, 117 communities; zero paid semantic extraction. The earlier pending note is resolved. Refresh it again after future code changes. A Git whitespace check previously failed because synced-folder mmap reads were cancelled; rerun before integration. No fresh performance benchmark, field metrics, exhaustive cross-browser/screen-reader audit or full error-state audit is claimed.

## Completion checklist for future work

- Preserve the specified composition/tokens and use existing shared primitives. Document intentional changes rather than appending conflicting override notes.
- Check relevant routes in both themes at all four widths, short desktop navigation, keyboard focus and enlarged text. Use synthetic records for screenshots.
- Run frontend lint, type/build and tests; exercise affected isolated workflows. Run repository-required backend and frontend checks before any commit. Confirm public/demo interactions produce no production mutations and assets contain no private data or credentials.
- Update design/structure/interface docs when behavior or ownership changes, record current proof and limitations, and run `graphify update .` after code edits.
- Deliver a local reviewable result. Do not commit, push, merge, deploy to Google Cloud, create auth integrations or change backend contracts without a specific user request.
