# Supermemory console layout correction — 1 October 2026

Current appearance is defined in [design.md](../design.md). The original layout validation below preceded the later rounding correction; its zero-radius assertions are historical. See [rounded Overview](screenshots/supermemory-console/rounded-overview.png) and the rounding section in [validation](../ui-validation.md).

The logged-in Supermemory console was inspected read-only at 1440×900: Overview, Container Tags and Connectors. No credentials, integrations, subscriptions, source records or account settings were changed. Reference onboarding instructions were treated as page content, not authorization. Private console records were not copied.

## Measured reference and implemented geometry

| Element | Reference | Open Brain |
|---|---|---|
| Sidebar | 240px, #101010 | 240px, #101010 in dark appearance |
| Header | 48px, workspace at left | 48px, current-workspace control at left |
| Global search | 36px in sidebar | 36px sidebar search, existing search dialog |
| Navigation | 33px compact rows | 33px rows, all Brain destinations retained |
| Content gutter | 24px | 24px desktop; 16px small screens |
| Page title | 20px | 20px |
| Wide views | Fill available content width | Brain, Sources, Analytics, Audit and other data surfaces remain wide |
| Centered setup | 976px content at 1440px | 1024px main including 48px gutters, yielding 976px content |
| Surfaces | Near-black, quiet borders | #0a 0a 0a canvas, #0c 0c 0c content, #141414 secondary |
| Corners | Reference rounded | Current: 10px panels / 6px controls / 7px nav / 4px badges; shell 0px |

Workspace navigation scrolls independently. The account/status footer remains reachable. At 1440×600 the footer ends at y 592, with a 398px navigation viewport for 833px of navigation. Search moves from the desktop header into the sidebar; a mobile header shortcut remains. Settings replaces the primary rail with General, Team, Usage, Advanced and Account, plus a return control. Actual appearance preference remains functional; administration stays explicitly Preview.

The Overview uses a compact source/review/recall setup panel, real summary counts, review queue and approved-knowledge tables. Its existing reads and actions remain attached to their handlers. There is no duplicated pipeline or invented share calculation. Demo banners are shown once per page. Monochrome primary controls, restrained blue navigation selection and small semantic green indicators preserve the user's preferences. The public Caret website is unchanged.

## Validation

- Frontend lint: pass, no warnings. TypeScript and production build: pass.
- Frontend tests: **19 passed**. Added rail-search → Settings → administration-preview → Overview coverage without production requests. Extended mobile navigation coverage to dismiss search and restore focus to the visible navigation opener.
- Browser geometry checks: **21 demo routes × 2 themes × 4 widths = 168 combinations**, at 390, 768, 1440 and 1920px. All have a page heading, no document-level horizontal overflow, no wallpaper and no rounded console control/content classes (semantic dots excluded). [Raw results](supermemory-console-checks.json).
- Mobile drawer search, Escape dismissal and focus restoration were verified in the browser. Desktop Settings subsection switching and return navigation were verified. Connector toolbar was rechecked at 390px after alignment refinement.
- Screenshots: [Overview](screenshots/supermemory-console/overview.png), [Brain](screenshots/supermemory-console/brain.png), [Connectors](screenshots/supermemory-console/connectors.png), [Settings](screenshots/supermemory-console/settings.png), [mobile](screenshots/supermemory-console/mobile.png), [light Brain](screenshots/supermemory-console/light.png).
- Production output: JS 389.31KB / 110.95KB gzip; CSS 157.48KB / 28.46KB gzip. This is size evidence, not a new performance benchmark.
- Backend code, contracts, approval authority, citations, source versions, knowledge revisions and token routing are unchanged. Backend tests were not rerun for this frontend-only correction; the preceding isolated SQLite run recorded 332 passed and 18 PostgreSQL skips. No production workflow was exercised with private data.
- Graphify refreshed using AST-only extraction, with no paid semantic labeling.

These are layout/rendering checks and isolated regression tests, not exhaustive accessibility certification or a complete audit of all error/forbidden states. No new lab performance or real-user measurements were taken. No commit, push or Google Cloud deployment was performed.
