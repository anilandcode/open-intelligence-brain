# Digital Brain design system

## Direction

The public page adapts the supplied Cartesia study's warm paper, forest accent, editorial type hierarchy, section rhythm, restrained borders and paired calls to action. Its section sequence explains Brain's own product and trust model. No Cartesia customer claims, original service integrations, analytics scripts or study-only fonts are shipped. The hero is an original generated network illustration.

The console follows the user's Supermemory references: near-black neutral surfaces, gray borders, compact grouped navigation, wide data lists and centered setup panels. Following the user's correction, large green areas were removed. Blue marks navigation, focus and primary actions. Green is reserved for small labelled health indicators. Supermemory endpoints, benchmarks, pricing gates and compliance claims are not copied.

## Tokens

| Token | Dark console | Light console |
|---|---|---|
| Canvas | `#09090b` | `#f7f7f8` |
| Surface | `#101012` | `#ffffff` |
| Raised field | `#161619` | `#f1f1f3` |
| Border | `#27272d` | `#dedee3` |
| Main text | `#ececef` | `#202024` |
| Muted text | `#a0a0aa` | `#686870` |
| Navigation/focus blue | `#599df8` | `#216bcb` |
| Primary button | `#216bcb` with white text | `#216bcb` with white text |
| Health green | `#8ccda5` | `#287548` |

Landing paper is `#f4f4f1`; forest is `#004e23`; verdant is `#309d4b`. Landing defaults to light; console defaults to dark with a browser appearance preference and light alternative. Public landing currently retains its light editorial theme.

Fonts are self-hosted Inter for interface text, Source Serif 4 for public editorial emphasis, and IBM Plex Mono for code/metadata. No font CDN request is needed. `product.css` scopes console palette overrides with `data-surface="console"` and theme overrides with `data-theme`. Existing working layout styles remain underneath the product layer.

## Layout and components

Desktop sidebar: 224px. Header: 56px. Gutters scale from 20–48px. Setup previews center at a maximum of 960px. The sidebar becomes a drawer below 880px; forms stack and tables scroll inside their containers. The header collapses search/capture buttons to labelled icons on narrow screens. The account region remains reachable in short viewports.

Brain and Sources use compact list tables with evidence/version drawers. Inbox retains queue, editor, exact evidence and approval actions. Playground gives the composer and answer their own full-width panels. Studio retains interview/draft tabs. Activate assembles and exports existing approved context, with an explicit no-generation explanation.

Shared styling covers buttons, fields, tabs, labels, panels, empty states, status notices, and native dialogs. The graph uses a lightweight SVG with pointer pan, keyboard controls, zoom, filters, a legend and a list alternative. Public knowledge-flow lines animate through CSS; reduced-motion preferences disable animation. The embedded public preview is the actual React demo UI, not a fabricated workspace screenshot.

## Console-first release flag

`VITE_SHOW_LANDING` is a non-secret frontend build flag (default **false**).

- **false / unset (console release):** unauthenticated visitors and explicit landing hashes (`#/`, section anchors) resolve to branded login. Authenticated visitors open Overview. Demo routes stay available with synthetic data.
- **true (later website release):** public landing is enabled.

Do not put tokens or secrets in any `VITE_*` variable.

## Content and trust

Source material is evidence. Proposed claims and working memory are interpretations. Approved knowledge is a human decision. These categories keep distinct names, statuses and views. Availability is stated per feature; previews cannot pretend to connect services, issue keys, save policies, run agents or analyze real users. Public examples contain synthetic content only.

