# Landing and console consistency review — 1 October 2026

Reviewed the local homepage at 390, 768, 1440 and 1920px. Preserved the Caret section hierarchy, 1024px feature column, shared borders, patterns and original scenic artwork.

## Findings addressed

| Finding | Correction |
| --- | --- |
| Landing source/context windows used Mac-style dots, pale panels and 16–18px corners. | Compact web-console header, sidebar and active navigation. Opaque neutral surfaces and the console's 10px panel / 6px control / 7px navigation scale. |
| Landing and console colors/corners could drift independently. | Shared `web/src/console-theme.css` tokens, consumed by the real dark console and public illustrations. |
| Sample answer citations were decorative and clipped at narrow widths. | Shared expandable EvidenceCitation, contained card width, responsive stage heights. Both collapsed and expanded states fit at all four widths. |
| Scenic strip described itself as a web-console preview although the actual app has no wallpaper. | Relabelled it as a synthetic workflow illustration. Scenic backgrounds stay outside the opaque console illustrations. |
| Mobile human-control cells had inconsistent empty space. | Removed the extra minimum height on the last two cells at the mobile breakpoint. |

## Verification

- Eight responsive checks: collapsed/expanded sample answer at all four widths; no page horizontal overflow; both answer panels contained; preview window/panel radius 10px.
- All six decorative images loaded successfully during a complete desktop scroll review. Below-the-fold images remain lazy loaded.
- Workflow tabs respond to ArrowLeft and show the expected proposed state.
- Lint, TypeScript checks and production build passed. All 19 frontend tests passed, including public rendering without workspace requests and synthetic evidence interactions.
- Full desktop and section screenshots plus responsive JSON are saved under `docs/ui/screenshots/landing-console-review/`.
- A final mobile-menu focus check and extra console readback were interrupted by browser-control timeouts; they are not claimed as verified in this review. Mobile layout/citation checks completed before that interruption.
- Backend contracts and workflows were not changed. Backend tests were not repeated; no commit or deployment was made.

## Boundaries

These are lightweight React illustrations with synthetic data, not a mounted production console. Navigation links open isolated demo routes. Intentionally cropped source/context illustrations remain non-editable; the full demo supplies the complete workflows. Existing generated artwork was reused and its provenance remains in the earlier asset documentation.

## Typography correction — 1 October 2026

Compared the supplied Caret `clone/en/index.html`, including parent wrappers, rather than estimating typography from screenshots. Its hero/final buttons use `text-base font-medium` (16px/500), navigation and example chips use `text-sm font-medium` (14px/500), and feature paragraphs use `text-base md:text-lg md:leading-snug` (16px small; 18px from 768px). Restored those values and removed the port's smaller mobile overrides. Trust and final-CTA paragraphs follow the same 16/18px scale. Hero supporting text stays 18px. Fonts remain verified, self-hosted Figtree.

Removed the icon beside the landing wordmark, including the mobile navigation and illustrated console headers. Functional Brain icons inside knowledge illustrations remain.

Computed-style checks at 390, 768, 1440 and 1920px confirm 16px/500 primary actions, 16/18px feature paragraphs and no horizontal page overflow. Visual checks cover the mobile hero and desktop hero/reuse band. Lint, TypeScript/production build and all 19 frontend tests passed. This correction changes landing markup/style only; no backend changes, commit or deployment.

The delayed Graphify refresh subsequently completed: 1900 nodes, 4580 edges, 117 communities, AST-only. Synced-folder reads caused the Git whitespace check to fail with an mmap cancellation; that check is not reported as passed. The current design baseline and continuation rules are consolidated in [design.md](../design.md), [design-structure.md](../design-structure.md) and [design-handoff.md](../design-handoff.md).
