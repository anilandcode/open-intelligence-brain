# Open Brain — current validation status

Updated 1 October 2026. [Design](design.md), [structure](design-structure.md) and [agent handoff](design-handoff.md) are the current continuation specifications. The sections below preserve earlier evidence; square-console, wallpaper and previous landing/performance notes are historical and must not override the current design.

## Latest landing correction

Restored original Caret HTML typography: hero/final buttons 16px/500, nav/chips 14px/500, feature/human-control/final paragraphs 16px below 768px and 18px from 768px. Removed the icon beside the landing wordmark and illustrated console brand headers. Real console typography and access branding were unchanged. Shared preview/console colors and corners remain in `console-theme.css`.

- Frontend lint, TypeScript/production build and all **19 frontend tests passed** on the verified source mirror. Canonical edited source was byte-compared with the mirror.
- Computed checks at **390, 768, 1440 and 1920px** confirmed text size/weight, no page horizontal overflow and no icon inside `.site-wordmark`. Mobile example-chip rows remained contained.
- Visual checks: mobile hero and desktop hero/reuse band. [Desktop proof](ui/screenshots/landing-console-review/brain-typography-desktop.png), [feature proof](ui/screenshots/landing-console-review/brain-typography-features.png), [review details](ui/landing-console-review.md). This is not a fresh full-page overlay comparison.
- Accepted console baseline: full-screen with no wallpaper; 240px sidebar, 48px header, 10px panels / 6px controls / 7px nav / 4px badges. Prior rounding checks covered all 21 demo routes at 390/1440px (42 combinations), plus light Settings. The 168-combination layout checks below preceded the rounding correction.
- The delayed Graphify code refresh has now completed: **1900 nodes, 4580 edges, 117 communities**, AST-only, zero paid semantic extraction. The prior pending refresh note is resolved.
- Git whitespace verification previously failed with a synced-folder mmap cancellation; it is not recorded as passed.
- Backend code/contracts were unchanged; backend tests were not rerun for the latest CSS/markup correction. Historical isolated evidence below is 332 passing backend cases and 18 PostgreSQL skips, not a new run or production assurance.

## Limits and delivery

No new throttled performance benchmark, real-user measurement, exhaustive accessibility/cross-browser audit or every loading/forbidden/error-state review was performed. A final mobile-menu focus check during the earlier landing alignment review timed out; earlier successful focus checks are historical evidence, not a fresh rerun. No commit, push or Google Cloud deployment has been made in this design phase. The latest documentation update changes Markdown only and does not require another application test run.

---

# Historical console layout verification — before rounding correction, 1 October 2026

The Supermemory layout correction supersedes the earlier console geometry and palette below. Website remains the faithful Caret port. Sidebar 240px, header 48px, desktop gutters 24px, setup content 976px, square corners and no wallpaper. Frontend lint (no warnings), TypeScript, **19 tests** and production build pass. All 21 routes passed computed layout checks in both themes at 390/768/1440/1920px (**168 combinations**). Mobile search dismissal returns focus to the visible navigation opener. Secondary Settings navigation and short-desktop footer access are verified.

[Detailed correction and limits](ui/supermemory-console-layout.md), [raw checks](ui/supermemory-console-checks.json), [screenshots](ui/screenshots/supermemory-console/overview.png). Backend contracts/workflows are unchanged; backend checks below belong to the preceding isolated run and were not repeated for this frontend-only change. No deployment, push or commit.

---

# Historical faithful-port / full-screen milestone, 30 September 2026

This section records that milestone only; the current baseline above supersedes its square-corner and typography descriptions. The faithful Caret HTML landing port is complete, followed by the requested full-screen console correction. Local review: http://127.0.0.1:5173/#/ and http://127.0.0.1:5173/#/demo/brain. No deployment, push or commit was performed.

## Square console correction — 1 October 2026

User requested less or no rounding. Console geometry tokens now use 0px, with a console-only policy for cards, tables, fields, controls, badges, tabs, navigation, and dialogs. The context-builder field also uses the shared token instead of a hard-coded 5px radius. Small semantic status dots stay circular. Website artwork is unaffected.

All 21 demo routes were checked for computed radii and document overflow at the default desktop width: no rounded content/control classes remained, excluding semantic status dots. [Results](ui/square-console-checks.json). Brain was also checked at 390px and in light appearance without horizontal overflow. Evidence/history and global search dialogs have 0px radii. Screenshots: [desktop](ui/screenshots/square-console/brain-console-square.png), [mobile](ui/screenshots/square-console/brain-console-square-mobile.png), [Overview](ui/screenshots/square-console/brain-console-square-overview.png). Lint, TypeScript and build pass; all 18 frontend tests pass. No backend code, data, authentication or deployment changed. Graphify was updated with AST-only extraction.

## Checks recorded at that milestone

- Frontend lint, TypeScript, all **18 frontend tests**, and production build passed after the console correction. JS 390.68KB / 111.20KB gzip; CSS 146.42KB / 26.61KB gzip.
- Backend lint passed. Fresh isolated SQLite suite: **332 passed, 18 PostgreSQL cases skipped**. Backend code and contracts were not changed by the subsequent console CSS correction. PostgreSQL behavior remains unverified.
- Website/reference full-page and matched section screenshots were refreshed at 390, 768, 1440 and 1920px. Measurements, comparisons, overlays and asset provenance: [faithful port report](ui/caret-html-port.md). No document-level overflow at those widths. Expanded exact evidence remains inside the 390px column; context export and copy success/failure are covered by tests and browser checks.
- All 21 demo console routes checked in both themes at 390, 768, 1440 and 1920px: **168 current combinations**, with no document-level horizontal overflow, no body background image, and a shell starting at x=0 and matching viewport width. [Current results](ui/fullscreen-console-checks.json). This is a shell/rendering check, not exhaustive auditing of every record or failure state.
- The console uses the website's shared Caret neutrals, Figtree/Inter typography, hairlines, square console corners (0px) and monochrome primary controls. No outer frame, margin, shell blur or wallpaper remains. Light appearance persists.
- Mobile navigation independently scrolls, keeps its footer visible, closes on Escape and restores focus to its opener. At 1440×600 the full-height sidebar has a 332px scrolling navigation region for 1097px of content, with its footer ending at 584px. Contained table overflow is retained.
- Final production credential/foreign-endpoint marker scan was clean; no unused mist wallpaper variants ship.
- Public synthetic interactions remain isolated from production; tests cover routing, tabs, citations, workflow samples, retained failures and demo/live boundaries. No backend request fallback substitutes synthetic records.

## Guidance and limits recorded at that milestone

The applied Google guidance remains size-aware styling, responsive tables, optimized decorative pictures, hero image priority and native dialog dismissal with a fallback. All decorative media is now on the website; console image-set wallpaper was removed. Original masters have documented genuine dimensions; no upscaling is claimed. Reduced motion is supported and website glass has opaque fallbacks.

Earlier performance observations below belong to the previous landing composition. They are **not current performance results**. No fresh throttled lab benchmark or real-user measurement was taken for this correction. Native browser zoom, Safari, comprehensive screen-reader auditing, contrast certification and all loading/empty/forbidden variants remain unverified. Regression tests are isolated, not a production-data exercise. See [interface capability matrix](interface.md) for live/preview boundaries.

Graphify was refreshed through AST-only extraction after code changes; community names were retained or derived from hubs without paid semantic relabeling. The local review build and screenshot artifacts are delivered without changing Google Cloud, authentication, deployment or backend capabilities.

---

# Earlier Caret milestone — historical validation

Reviewed locally on 30 September 2026. Source and locked frontend dependencies are mirrored in `/private/tmp/digital-brain-ui-review` because Google Drive stalls during dependency reads/writes. Preview: http://127.0.0.1:5173/#/. No deployment, push or production mutation was performed.

## Frontend and assets

- Lint: passed without warnings.
- Frontend: 18 tests passed, including public-preview network isolation and explicit sample abstention.
- TypeScript and production build: passed. JS 385.50KB / 110.26KB gzip; CSS 139.15KB / 24.63KB gzip.
- Production scan: no quoted 64-character hex credential, build-time token marker or copied Supermemory MCP endpoint found.
- Backend source/contracts unchanged. Backend lint passed; isolated SQLite suite: **325 passed, 25 skipped** in 115.90s. Temporary test servers were enabled for the successful run after sandbox loopback restrictions caused fixture setup failures. A temporary offline dependency environment avoided stalled Google Drive imports. Seven of those skips were SPA containment cases because the temporary backend mirror initially lacked `web/dist`; after mounting the exact production build, all **7 passed** in a targeted rerun. Across those runs, **332 distinct backend cases passed**, with **18 PostgreSQL cases still skipped**. PostgreSQL parity/restart behavior remains unverified.

Existing isolated regression tests cover token access, cited answers, source/version forms, knowledge history, Studio, local demo approval, exact source-version citation pointers, missing-record states, retry with retained input, preview credentials and mobile focus recovery. Public preview tabs and context copying issue no production requests. Synthetic records alone appear in public imagery/screenshots.

## Browser checks

All 21 demo console routes rendered in dark and light at 390, 768, 1440 and 1920px: **168 combinations**. Headings were present and none produced document-level horizontal overflow. These are rendering/overflow checks, not an exhaustive visual audit of every possible error state. Tables remain horizontally scrollable inside their containers. Evidence: [console results](ui/caret-responsive-checks.json).

Landing and login were also checked at all four widths with no page overflow: [public results](ui/caret-public-checks.json). Screenshots include all 21 console surfaces, website/mobile/full-page, light Brain, login and short desktop: [index](ui/README.md).

A 1440×600 console viewport had a 566px sidebar with a 298px independently scrolling navigation region containing 1097px of navigation; the account area remained reachable. Mobile navigation focused its close button, Escape dismissed it, and focus returned to Open navigation. The public native menu also restored its opener on Escape. Public tabs supported Home/End, evidence disclosures displayed the exact synthetic excerpt, FAQ expanded, out-of-sample questions abstained, and context copying reported success. Underlying live request/error behavior remains covered by fixtures; no private production dataset was used.

Reduced-motion rules and opaque blur fallbacks are present. Shared palette text pairs use readable neutral contrast. Full screen-reader, browser zoom, Safari fallback, contrast certification and every loading/empty/forbidden variant in both themes have not been exhaustively audited. Those limits must not be presented as complete accessibility certification.

## Google Modern Web Guidance

Official guidance was searched and retrieved before applying features, using the `modern-web-guidance` CLI and its reviewed skill version. Default: Baseline Widely available, with progressive enhancement. Entry point: [Google guidance](https://developer.chrome.com/docs/modern-web-guidance/get-started).

| Retrieved guide | Applied behavior |
|---|---|
| `size-aware-styling` | Inline-size containers adapt public previews/cards; normal responsive layout remains the fallback. |
| `responsive-table` | Native header/table structure, sticky header and contained horizontal overflow; no destructive table-to-card reset. |
| `deliver-optimized-decorative-images` | AVIF/WebP responsive picture sources; console image-set has standard URL fallback and true 832/1664 density variants. |
| `optimize-image-priority` | Explicit image dimensions and srcset; eager/high-priority hero, lazy decorative image component below the fold. |
| `light-dismiss-a-dialog` | Native mobile modal, accessible name, close/Escape restoration, `closedby` and supported outside-click fallback. Existing form drawers retain their dismissal behavior. |

Generated masters are native 1672×941, with no upscaling or claimed 4K quality. Interface elements are rendered separately. No cloned Next.js runtime, service integration or mirrored font file is shipped.

## Local performance

A separate temporary copy of the production build was instrumented with native PerformanceObserver entries and served on loopback. Instrumentation was **not** copied into workspace source or shipped assets. Chromium, unthrottled local network/CPU, reload measurements with warm browser cache; one measured run at each width. These are lab observations, not real-user 75th-percentile metrics or a Lighthouse score.

| Viewport | LCP | Observed layout-shift sum | Slowest observed event duration |
|---|---|---|---|
| 1440×900 | 276ms | 0.0000096 | 72ms across 8 entries |
| 390×900 | 216ms | 0 | 56ms across 6 entries |

Interactions exercised preview tabs, a sample question and submission. Event entries used a 16ms reporting threshold. The maximum recorded event duration is a responsiveness sample, **not a full INP calculation**. No field INP or throttled cold-network/mobile benchmark was measured. Local LCP/CLS are below the requested 2.5s/0.1 thresholds; deployment and real-user data are still required. [Google thresholds](https://web.dev/articles/vitals). Raw observations: [performance JSON](ui/caret-performance.json).

## Delivery and boundaries

`docs/design.md` describes current files/tokens/media provenance. `docs/interface.md` preserves the live/preview capability matrix. Graphify was refreshed through AST-only extraction: 1860 nodes, 4533 edges, 111 communities; community names were preserved or derived from hubs without paid semantic relabeling.

Frontend preview is local and reviewable. Google Cloud deployment, authentication integration, native desktop functionality, new backend capabilities and production reliability testing remain separate milestones.

## Console rounding verification — 1 October 2026

- Updated Supermemory-style rounding verified in a freshly loaded browser: panels 10px, controls 6px, navigation 7px; full-screen shell 0px.
- All 21 demo routes rendered at 390px and 1440px with headings present and no page-level horizontal overflow (42 checks).
- Light Settings appearance and 6px controls verified; restored dark Overview for review.
- Production build passed; Graphify refreshed to 1,891 nodes, 4,570 edges and 119 communities.
- Screenshot: `docs/ui/screenshots/supermemory-console/rounded-overview.png`; rendering results: `rounded-checks.json` in the same folder.
- This was a CSS-only change; workflow regression tests were not repeated. No production deployment.

## Landing preview consistency — 1 October 2026

Shared dark-console color and corner tokens now drive the landing product illustrations. See [landing and console review](ui/landing-console-review.md) for findings, responsive evidence and validation limits.
