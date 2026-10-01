# Open Brain — current design system

Updated 1 October 2026. This is the authoritative visual specification. Read it with [design structure](design-structure.md), [handoff](design-handoff.md), [capability matrix](interface.md) and [validation](ui-validation.md). Current source and these specifications supersede the older AgenticX, wallpaper/inset-console and square-console experiments.

## Accepted direction

The website preserves the supplied [Caret composition](https://caret-clone.vercel.app/): actual HTML wrapper/grid structure, numbered bands, continuous hairlines, patterned gutters, clipped illustrations, colorful pixel-textured scenery and faded footer lettering. The reference repository is `anilandcode/caret-clone`, particularly `clone/en/index.html`, `design/DESIGN.md` and `design/style-guide.html`. Open Brain copy and original artwork replace Caret product claims and illustrations. Do not reduce this to generic cards using a similar palette.

The console uses the reviewed Supermemory spatial layout: compact sidebar and header, quiet near-black content surfaces, subtle rounding and blue navigation selection. It fills the browser. It has no wallpaper, outer inset, desktop frame or shell blur. Scenic media belongs to website illustrations only.

Primary controls are monochrome. Green is limited to small semantic health/status indicators. Do not restore the earlier forest-green theme. Public branding is the text wordmark **Open Brain**, without an adjacent logo icon, including mobile navigation and illustrated console headers. Functional Brain symbols inside knowledge illustrations remain. The actual console/access branding was not changed by the landing-wordmark correction.

## Palette and shape

| Role | Website | Dark console | Light console |
| --- | --- | --- | --- |
| Canvas | `#09090b` | `#0a0a0a` | `#ffffff` |
| Content surface | `#18181b` base; illustrations use console tokens | `#0c0c0c` | `#ffffff` |
| Secondary surface | `#27272a` | `#141414` | `#f4f4f5` |
| Sidebar | — | `#101010` | `#fafafa` |
| Main text | `#fafafa` | `#fafafa` | `#09090b` |
| Muted text | `#9f9fa9` | `#a0a0a0` | `#65656e` |
| Primary control | `#e4e4e7`, dark text | `#e4e4e7`, dark text | `#18181b`, light text |
| Border | white 10%; grid borders `#27272a` | white 8% | `#e4e4e7` |
| Selected navigation | — | `#83b6ff` on `#102031` | existing light blue tokens |

Shared values live in `web/src/console-theme.css`. Panels/dialogs use **10px**, fields/controls **6px**, navigation **7px**, compact badges **4px** in both console themes and corresponding public console illustrations. Shared table/header corners meet cleanly; inner row boundaries may stay square. The outer console shell, sidebar and header have **0px** corners. Status dots stay circular. Website CTA buttons and glass pills are intentionally pill-shaped; do not apply console corners indiscriminately to the public composition.

Dark is the console default. Preserve the working browser-stored light appearance preference.

## Typography — restored from the original HTML

Verified self-hosted fonts: Figtree 400/500/600 for website text, Inter for display headings and the console interface, Source Serif 4 for occasional editorial emphasis, IBM Plex Mono for metadata. Figtree's open-font source is [erikdkennedy/figtree](https://github.com/erikdkennedy/figtree); do not redistribute the mirror's study-only fonts or add a font CDN.

| Website role | Size / line height | Weight |
| --- | --- | --- |
| Hero heading | 48/48px desktop; 40/40px below 768px | 450, Inter with available-font fallback |
| Hero supporting paragraph | 18/28px, including mobile | 400 |
| Hero/final CTA | 16/20px; minimum height 40px | 500 |
| Navigation CTA | 14/20px; minimum height 36px | 500 |
| Desktop navigation | 14px | 500 |
| Example chips | 14/20px; minimum height 32px | 500 |
| Feature paragraphs | 16/24px below 768px; 18/24.75px from 768px | 400 |
| Human-control paragraphs | 16/22px below 768px; 18/24.75px from 768px | 400 |
| Final CTA paragraph | 16/24px below 768px; 18/24.75px from 768px | 400 |
| Feature headings | 24px desktop; 21px tablet; 22px below 768px | 500 |
| Copy action / inline feature link | 14px | 500 |
| Footer description / footer metadata | 14px / 12px | 400 |

These values restore the original `text-base`, `text-sm font-medium`, and `md:text-lg md:leading-snug` hierarchy. Do not reintroduce the 10–12px regular-weight primary buttons or 13–14px marketing paragraphs. Small, intentionally cropped console illustrations have their own compact UI metadata scale; do not enlarge every diagram label as if it were marketing prose. The actual console retains its compact 13px base, 20px page headings, 12px page descriptions and table content. This landing correction did not change console typography.

## Media and composition

Four original backgrounds: warm panoramic hero, square hills/clouds, peach/lilac/ice-blue pixel review scene, yellow/blue textured source/context/revision crops. Native masters, licensing/provenance and responsive dimensions are recorded in [the port report](ui/caret-html-port.md). Delivery files live in `web/public/website/`; masters are archived under `docs/ui/media/`. AVIF/WebP variants are downsampled, never claimed as native 4K. Earlier dusk/mist masters are archival, not current artwork.

Render text, citations, windows, lines, cards, docks and pills separately in React/SVG. Never bake UI text into artwork. Slash, dot and chevron patterns remain scoped to the website. Scenic strip wording identifies a **synthetic workflow illustration**, not the real console's background. Public source/context windows consume shared console color/corner tokens and use opaque surfaces, compact web headers/sidebar navigation and blue selection; do not restore Mac window dots, pale frosted editors or oversized corners.

## Extension rules

- Preserve the section sequence, wrapper hierarchy, proportions and shared borders documented in [design-structure.md](design-structure.md).
- Extend existing primitives and tokens. Edit the owning rules rather than adding another broad override stylesheet. Keep the public `.brain-site` layer scoped and console-specific rules scoped to the console.
- Do not mount the full console on the public homepage. Use lightweight synthetic compositions. Demo interactions never call production APIs or consume private records/tokens.
- Preserve labels, keyboard tab behavior, evidence disclosures, copy success/failure feedback and native mobile-menu focus restoration.
- Keep images dimensioned, responsive and decorative; hero eager/high priority, below-fold images lazy. Respect reduced motion and provide opaque blur fallbacks. Use Google Modern Web Guidance with Baseline defaults and progressive enhancement.
- Retain semantic tables and contained horizontal scrolling. Navigation scrolls independently while the account area remains reachable.
- Backend failures stay failures; never substitute demo data. Read [architecture](architecture.md) before changing approval, citations, authentication or persistence.
- New capabilities must use the existing Live/Preview boundaries in [interface.md](interface.md). Design work does not authorize backend additions or deployment.

## Validation references

The latest landing typography/wordmark proof is [desktop](ui/screenshots/landing-console-review/brain-typography-desktop.png) and [feature band](ui/screenshots/landing-console-review/brain-typography-features.png). The [landing review](ui/landing-console-review.md) records public preview alignment and typography checks. [Rounded Overview](ui/screenshots/supermemory-console/rounded-overview.png) records the accepted console rounding. Original matched Caret comparisons establish composition, but precede the final typography and preview-shell corrections; do not treat them as exact current screenshots.

See [ui-validation.md](ui-validation.md) for what passed and what remains unverified. No Google Cloud deployment, new authentication or native desktop software is part of this design baseline.
