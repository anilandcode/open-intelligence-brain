# Interface architecture and capability matrix

The UI keeps original sources, proposed claims, working memory, and approved knowledge distinct. The public landing explains capture → human review → approved knowledge → cited reuse. Token access remains the live authentication mechanism; this UI phase does not add Google authentication or change API contracts.

## Routes and data boundaries

- `#/` opens the public landing even if a token is already present.
- `#/login` opens branded token access. Existing token-fragment handling strips the credential from the address bar.
- `#/console/<view>` selects the existing API client and authenticated workspace.
- `#/demo/<view>` selects an isolated synthetic adapter. Demo reads and mutations never call the production API, including when a real token is stored in the browser.
- Brain and Sources support `?record=<id>` detail links. Missing records show an unavailable message instead of substituting another record. Hash navigation supports refresh and browser back/forward.

The landing's embedded console loads the demo route in a separate document. Its local sample changes are discarded on reload. Production failures never trigger a sample-data fallback. Hosting, engine availability, and authentication are separate indicators; unknown state is displayed honestly.

## Capability matrix

“Live” means the frontend preserves an existing API workflow. It does not certify deployment availability or infrastructure reliability. Every live page also runs against the separate synthetic demo adapter.

| Surface | Live console | Demo / preview |
|---|---|---|
| Overview | Stored counts, pending reviews, recent knowledge, engine status | Synthetic health and review queue |
| Inbox | Edit, approve, reject with exact evidence | Local sample approval/rejection |
| Brain | Search, attention filters, sorting, evidence, revision history, superseding | Same page with local revisions |
| Playground | Canonical retrieval and cited answers | Keyword retrieval from approved sample records, no model |
| Studio | Interviews, questions, responses, completion, drafts and cited assembly | Same forms with local sample records |
| Activate | Approved-only context assembly, copy and Markdown export | Same builder using synthetic knowledge |
| Sources | Search, visibility/type filters, versions and immutable updates | Local sample version history |
| Analytics | Knowledge-health counts with named denominators | Synthetic counts; no usage/outcome attribution |
| Audit | Integrity signals and filterable domain event details | Synthetic events; possible conflicts remain signals |
| Import: Text | Existing capture endpoint | Local capture and opening-sentence sample extraction |
| Import: Files / URL | Explicit preview; no upload or web ingestion | Locally staged selection only |
| Workspaces | Explicit preview entry | Sample browsing and detail; tags are not permissions |
| Working Memory | Explicit preview entry | Search/status filters and source/approved relationships |
| Brain Graph | Explicit preview entry | Sample graph, filters, zoom/pan, inspection and accessible list |
| Connectors | Explicit preview entry | GitHub/Drive-first provider browsing and local configuration forms; no OAuth/sync |
| API Keys | Explicit preview entry | Scope/expiry row creation/removal; no credential issued |
| Agents & MCP | Documented setup shown through a preview entry | Hermes, Codex, Claude tabs; local stdio configuration and project HTTP adapter; connection status unavailable |
| Requests | Explicit preview entry | Synthetic operation/status/latency details, separate from domain Audit |
| Insights | Explicit preview entry | Labelled sample report, separate from knowledge-health Analytics |
| Turns / Proactivity | Explicit preview entries | Sample timeline and local policy controls; no execution or scheduling |
| Settings | Local appearance preference works | General, Team, Usage, Advanced, Account administration previews |

## Frontend modules

`App.tsx` owns the shell, navigation, access gate, loading/retry behavior and global search. `LivePages.tsx` retains working page handlers. `client.ts` provides the selected client; `demo.ts` holds synthetic state with no network or token dependency. `PreviewPages.tsx` owns future capability previews; Import Text alone calls the selected client. `GraphPreview.tsx` and `Detail.tsx` provide the graph and native modal drawer. `routes.ts` centralizes hash routing. `LandingPage.tsx` contains the public page.

The existing `api.ts` remains the live contract. Only approval creates new canonical knowledge. Source updates retain previous versions; canonical updates retain revisions. Citations keep the exact stored excerpt. Demo source-version proposals retain the corresponding version ID on approval.

## UI states and accessibility

Working screens provide populated, empty, loading and failed-request states. Refused authentication returns to token access. Future capabilities require an explicit preview entry. Failed form submissions keep the input and allow retry; submit actions disable while in flight. Global search and record links open the relevant detail.

Tables contain horizontal scrolling. The desktop sidebar scrolls independently, with a fixed account/status area. The mobile drawer contains focus, closes with Escape and restores its opener; closed navigation is inert, and the main page is inert while the drawer is open. Native modal dialogs provide browser focus containment, Escape handling and focus restoration. Buttons and fields have labels and visible focus styles. Graph nodes also have a list alternative and keyboard pan controls. Reduced-motion preferences suppress CSS animation. See `design.md` for tokens and `ui-validation.md` for verification evidence and limits.
