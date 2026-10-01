# Faithful Caret HTML port — 30 September 2026

This is the structural/provenance report for that milestone. Later [preview and typography corrections](landing-console-review.md) supersede its rendered text sizes and illustrated shell styling. The authoritative current specification is [design.md](../design.md), with the section tree in [design-structure.md](../design-structure.md). Native dimensions/geometry measurements below describe the recorded comparison, not a fresh measurement after those corrections.

This correction replaces the previous landing composition. The landing port preserves backend behavior. Subsequent user steering also makes the console edge-to-edge, removes its wallpaper and frame, and retains the shared neutral design system. Local review: http://127.0.0.1:5173/#/.

## Source-to-product mapping

The starting source is `anilandcode/caret-clone`, `clone/en/index.html`, with `design/DESIGN.md` and `design/style-guide.html`. The actual wrapper hierarchy was adapted into `web/src/LandingPage.tsx`; its relevant geometry is in the replacement `web/src/landing.css`. No second override stylesheet, cloned Next runtime, analytics, service endpoints, copied fonts, customer portraits, meeting claims or subscription gates were introduced.

| Source composition | Brain composition |
|---|---|
| Centered hero and 384px scenic desktop strip | Shared-brain promise; small glass approved-context control opens the isolated demo |
| First two-column grid | Cited answer and related approved knowledge; source ghosts, linking lines and floating cards |
| Copy/chips and square scenic panel | Keyboard-operated Context/Evidence/History examples and an expandable exact synthetic citation |
| Two 384px split rows | Cropped original-source window; pastel proposal notification and Sources → Proposals → Knowledge dock |
| Asymmetric final grid | Cropped cited-context window; working copy/export illustration; original/revised wording composition |
| Bordered 2×2 privacy composition | Human approval, exact evidence, source versions and revision history, each with a subtle diagram |
| Rectangular CTA and faded wordmark | Build on what you know; Open Brain lettering and concise source-code footer |

The standalone FAQ and large hero console window were removed. Existing public section IDs remain. `SectionFrame`, `GraphicStage`, `GlassPill`, `AppWindow` and decorative `Wallpaper` components keep the structural rules together. Shared `EvidenceCitation` exposes the exact sample excerpt.

## Geometry and comparison evidence

Reference and implementation were captured at matching 390, 768, 1440 and 1920 CSS-pixel widths. All decorative Brain images had finished loading. Initial document horizontal overflow was zero at every width. Native section measurements are saved in [measurements.json](screenshots/caret-port/measurements.json).

| Property | Result |
|---|---|
| Maximum feature column | 1024px, x=208 at 1440 and x=448 at 1920 |
| Gutter padding | 24 / 64 / 96 / 160px at source breakpoints; outer 32px desktop frame |
| Desktop capture/review rows | 384px each; stacked below 1024px |
| Illustration regions | 5:4 stages; square scenic evidence stage; intentional app-window clipping |
| Borders | Shared one-pixel continuous boundaries; no separate card-section gaps |
| Patterns | Original small slash, dot and chevron SVG geometry, scoped to the website |

At 1440px the source hero is 797.5px high and Brain's is 793px; the first band is 1330.4px versus 1323.0px; capture/review is 832px in both; reuse is 1028.3px versus 1050.4px. These are close structural matches, not a claim of pixel-identical copy or original artwork. Different wording and interactive disclosure/copy controls change some heights. Narrow evidence and export stages have minimum heights so useful controls remain readable. Opening evidence or Markdown may expand their containing row. The corrected expanded evidence panel stays inside the mobile column.

For each width, the folder contains full pages, native section crops, top-aligned 50% overlays, and side-by-side section comparisons. Overlays retain native scale and pad the shorter section; they are geometry diagnostics, not similarity scores. The reference includes its own animation-dependent navigation state. The user's supplied complete screenshot additionally guided the source's layered graphic positions.

| Width | Brain | Reference |
|---|---|---|
| 390 | [Full page](screenshots/caret-port/brain-390.png) | [Full page](screenshots/caret-port/reference-390.png) |
| 768 | [Full page](screenshots/caret-port/brain-768.png) | [Full page](screenshots/caret-port/reference-768.png) |
| 1440 | [Full page](screenshots/caret-port/brain-1440.png) | [Full page](screenshots/caret-port/reference-1440.png) |
| 1920 | [Full page](screenshots/caret-port/brain-1920.png) | [Full page](screenshots/caret-port/reference-1920.png) |

[Full-page comparison](screenshots/caret-port/comparison-full-1440.png).

| 1440px section | Side by side | Overlay |
|---|---|---|
| Hero | [Compare](screenshots/caret-port/comparison-1440-hero.png) | [Overlay](screenshots/caret-port/overlay-1440-hero.png) |
| Recall | [Compare](screenshots/caret-port/comparison-1440-recall.png) | [Overlay](screenshots/caret-port/overlay-1440-recall.png) |
| Capture & review | [Compare](screenshots/caret-port/comparison-1440-capture-review.png) | [Overlay](screenshots/caret-port/overlay-1440-capture-review.png) |
| Reuse | [Compare](screenshots/caret-port/comparison-1440-reuse.png) | [Overlay](screenshots/caret-port/overlay-1440-reuse.png) |
| Human control | [Compare](screenshots/caret-port/comparison-1440-human-control.png) | [Overlay](screenshots/caret-port/overlay-1440-human-control.png) |
| CTA | [Compare](screenshots/caret-port/comparison-1440-final-cta.png) | [Overlay](screenshots/caret-port/overlay-1440-final-cta.png) |

The same section filenames are available with 390, 768 and 1920 instead of 1440.

## Asset provenance and delivery

Four original backgrounds were generated for this correction, without text, logos or interface elements. Masters are archived in `docs/ui/media/`; only downsampled delivery variants ship in `web/public/website/`.

| Master | Native dimensions | Use | Delivered widths |
|---|---|---|---|
| `caret-hero-master.png` | 1672×941 | Warm panoramic hero | 640, 960, 1440 |
| `caret-hills-master.png` | 1254×1254 | Hills/clouds evidence panel | 480, 768, 1024 |
| `caret-pastel-master.png` | 1672×941 | Peach/lilac/ice-blue pixel review composition | 640, 960, 1440 |
| `caret-goldblue-master.png` | 1672×941 | Yellow/blue textured source, context and revision crops | 640, 960, 1440 |

No upscaling was used and no 4K claim is made. [Asset metadata](media/caret-port-assets.json) records exact delivered dimensions and bytes for AVIF and WebP. Pictures use format fallbacks, width descriptors, explicit dimensions, eager/high-priority hero loading and lazy below-fold loading. Pixel patterns are baked into the generated media; all captions, pills, windows, citations, diagrams and docks remain crisp React/SVG content.

Three tiny decorative SVG patterns were extracted directly from the supplied source's `clone/images/bg-pattern-{slash,dot,arrow}.svg`. Brain symbols and diagrams use the existing Lucide icon package and original SVG lines. Existing verified self-hosted Figtree, Inter, Source Serif 4 and IBM Plex Mono are retained. Earlier dusk and mist masters remain archived as provenance. Their unused delivery variants were removed; the console has no background image.

## Behavior and accessibility boundaries

Public examples are synthetic and make no API calls. The page never mounts a full console. Workflow tabs display sample captured/proposed/approved states and explicitly disclose that no live approval occurs. Copy feedback includes failure recovery with selectable Markdown. Live tokens and private records are never inserted into public illustrations. Public hash navigation and token login behavior remain unchanged.

Browser checks exercised arrow/Home/End tab navigation, exact excerpt disclosure, capture/review/reuse states, clipboard success, and native mobile-menu Escape/focus recovery. Automated tests additionally cover clipboard failure and public network isolation. Focus outlines, native dialog naming, supported light dismissal, reduced-motion static rules and opaque blur fallbacks are present. Glass text was darkened behind light lettering to improve contrast. Decorative scenery and noninteractive connector maps are hidden from assistive technology.

This is not a complete assistive-technology or cross-browser certification. Native browser text enlargement and Safari's blur fallback still need broader device testing. Google guidance applied: responsive image formats/priority, inline-size container queries, Baseline defaults, and accessible native dialog dismissal. Existing console table semantics and production/demo separation are unchanged.

## Verification

See the latest section in [ui-validation.md](../ui-validation.md) for final automated results and Graphify refresh. Older console screenshots and performance measurements belong to the preceding milestone and are explicitly historical; they do not measure this corrected homepage. Nothing was deployed, pushed or committed.
