# Interface architecture

The workbench follows the product research's central distinction: the Brain is not a generic document chat interface. It is a governed workspace for creating, judging, preserving, and activating company intelligence.

## Navigation model

| Area | User question | Current status |
|---|---|---|
| Overview | What needs attention and how healthy is the Brain? | Live |
| Inbox | What requires human judgement? | Live |
| Brain | What do we currently know or believe? | Live |
| Studio | What expert knowledge have we not written down yet? | Preview; planned for M3 |
| Activate | Which approved context should become work? | Preview; planned for M3 |
| Sources | What original material supports the Brain? | Live |
| Analytics | Which intelligence creates outcomes? | Health metrics live; outcome attribution preview |
| Audit | Why does the system believe this? | Live |

The standalone Ask view is opened from Overview or Brain. It deliberately searches only canonical knowledge and shows cited evidence or abstains.

## Review workspace

The Inbox is organised as a three-part judgement surface:

1. A compact proposal queue.
2. An editable canonical statement and rationale.
3. Exact source evidence and provenance.

Approval creates canonical knowledge with an immutable first revision. Rejection changes proposal state but never deletes or rewrites the source.

## Preview contract

Studio, Activate, and outcome analytics are included to make the intended product architecture inspectable before their APIs exist. Every preview:

- says that it is a preview in the navigation and page content;
- avoids fake recording, generation, publishing, or attribution actions;
- links back to a real workflow when one exists, such as importing an interview transcript;
- remains optional and cannot block existing source, review, Brain, Ask, audit, or export workflows.

## Responsive and accessibility baseline

- Semantic landmarks, headings, forms, labels, lists, details, and native dialog behavior.
- Visible keyboard focus, a skip link, and no color-only status indicators.
- Responsive desktop, tablet, and mobile navigation.
- Minimum touch targets increase for coarse pointers.
- Reduced-motion and forced-colors support.
- Offscreen canonical rows use `content-visibility` to reduce rendering work in larger Brains.

The interface uses system fonts and ships no remote visual assets, so strict local mode remains visually complete without a network connection.
