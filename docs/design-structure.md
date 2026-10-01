# Open Brain — design structure

Updated 1 October 2026. Preserve this structure when extending the accepted design. Styling tokens and typography are defined in [design.md](design.md); functional availability is defined in [interface.md](interface.md).

## Homepage tree and public anchors

| Order | Composition / components | Anchor | Required treatment |
| --- | --- | --- | --- |
| 1 | `Wordmark`, navigation, native mobile dialog | `landing-main` skip target | Text-only Open Brain wordmark; monochrome CTA; readable original button scale |
| 2 | Centered hero + `Wallpaper`, `GlassPill` | `product` on scenic strip | Shared-brain promise, two actions, 384px scenic strip, small floating approved-context control; no large console hero |
| 3 | `SectionFrame`, first `site-two-grid`, `RecallAnswer`, `RelatedKnowledge`, `RecallScene` | `recall` | [01] Recall; slash gutters; cited answer/related knowledge, then copy/chips beside square evidence scene |
| 4 | `SectionFrame`, two `site-split-row` rows, `CaptureWindow`, `ReviewScene` | `how-it-works`; retained `principles` anchor at end | [02] Capture & review; dot gutters; source window crop, then pastel sample proposal notification and knowledge dock |
| 5 | `SectionFrame`, `ContextWindow`, `ExportScene`, `RevisionScene` | `agents` | [03] Reuse; chevron gutters; asymmetric context/export row then copy beside stacked knowledge revisions |
| 6 | `SectionFrame`, `TrustDiagram`, 2×2 human-control grid | `provenance` | Dot gutters; approval, exact evidence, immutable source versions and revisions |
| 7 | Rectangular final CTA, faded lettering, footer | `landing-main` back-to-top link | Build on what you know; Open Brain / Explore demo; concise footer |

The navigation maps Inside the console → `product`, How it works → `how-it-works`, Our principles → `provenance`. Preserve existing anchors even when changing copy. The standalone FAQ and oversized hero console are removed; do not restore them through a generic template.

## Geometry

- Center the feature column at a maximum **1024px**. On large desktop the outer section frame has 32px inline padding.
- Patterned gutter padding: 24px base; 64px from 768px; 96px from 1024px; 160px from 1280px. Keep patterns visible outside the feature column.
- Adjacent cells/sections share continuous one-pixel borders. Preserve source hierarchy: outer band → patterned gutter → feature column → grid cells. Avoid isolated rounded card sections separated by large gaps.
- Feature graphics use 5:4 stages; the evidence landscape is square. Capture/review split rows are 384px high at desktop and stack below 1024px. Feature two-column grids stack below 768px.
- Keep deliberate app-window offsets and clipping. Below narrow container widths, previews hide the miniature sidebar and adjust card positions; expanded evidence/export content can enlarge the stage rather than clip useful controls.
- Headlines, paragraphs and graphic stages share cell borders but have deliberate internal whitespace. Enlarged prose must remain contained without shrinking fonts back to the rejected scale.
- Landing nav becomes a native modal drawer below 768px. Decorative scenery is hidden from assistive technology; real controls remain keyboard-operable.

## Console structure

`App.tsx` owns access, shell, navigation and search. Desktop: 240px sidebar, 48px header, 33px navigation rows, 36px rail search and 24px content gutters. Wide data views use available width; setup views have a 1024px main wrapper including gutters (976px usable desktop content). At widths up to 880px, use the existing mobile drawer and 16px content gutters. Sidebar navigation scrolls independently of the account/status footer.

The shell fills the browser at all widths: no wallpaper, inset window, shell border, rounding or blur. Content uses the shared 10/6/7/4px panel/control/nav/badge system. Settings replaces the primary rail with General, Team, Usage, Advanced and Account plus a return action. Appearance preference is real; future administration stays Preview.

Preserve Overview, Inbox, Brain, Playground, Studio, Activate, Sources, Analytics, Audit and Text Import workflows. Keep preview surfaces in their appropriate groups and visibly labelled. Review [interface.md](interface.md) before changing navigation or availability.

## Ownership and style load order

| File | Responsibility |
| --- | --- |
| `web/src/LandingPage.tsx` | Public section composition, synthetic examples, local interactions and mobile navigation |
| `web/src/landing.css` | Scoped public composition, typography, patterns, graphic crops and responsive rules |
| `web/src/console-theme.css` | Shared dark-console colors and panel/control/nav/badge radii used by actual console and public previews |
| `web/src/caret.css` | Console/public palette mapping, current console shell, controls, light appearance and final rounding rules |
| `web/src/product.css` | Retained console functional layout foundations |
| `web/src/main.tsx` | Self-hosted fonts and style order: legacy foundation styles → product → console-theme → caret → landing |
| `web/src/Evidence.tsx` | Shared exact-excerpt disclosure; preserve live citation behavior |
| `web/src/LivePages.tsx`, `client.ts`, `api.ts` | Existing live workflows and contracts |
| `web/src/demo.ts`, `PreviewPages.tsx`, `GraphPreview.tsx` | Isolated synthetic adapter and explicitly unavailable future capabilities |
| `web/src/Detail.tsx`, `routes.ts` | Record inspectors and hash navigation |
| `web/public/website/`, `docs/ui/media/` | Optimized delivery media and archived provenance masters respectively |

Source files are authoritative. Some older foundation rules are superseded by the current scoped layer; do not remove them blindly or add a new global reset. Keep token changes in the shared token owner and validate both the actual console and its public illustrations.

## Review contract for additions

Compare the existing and modified composition at 390, 768, 1440 and 1920px, plus a short desktop console. Check prose size/weight, border alignment, feature widths, pattern density, image crops, offsets, disclosure expansion, scroll containment and both console themes. Exercise keyboard and failure recovery for changed controls. Save synthetic-only proof screenshots and record limitations in [ui-validation.md](ui-validation.md). Update this structure only when an intentional design decision changes it.
