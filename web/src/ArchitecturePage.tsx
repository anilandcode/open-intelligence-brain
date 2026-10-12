import { ArrowRight, ArrowUpRight, Brain, FileText, GitBranch, Layers, Menu, ShieldCheck, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { goTo, openConsole, SHOW_LANDING } from "./routes";

/**
 * Public architecture page for the marketing site (and any build that ships the SPA).
 * Mirrors docs/architecture.md trust model in plain language — no secrets, no host internals.
 */

const layers = [
  {
    title: "Sources",
    body: "Original notes, interviews, decisions, and files. Content is versioned and hashed. Nothing here is trusted as truth on its own.",
  },
  {
    title: "Proposals",
    body: "Candidate lessons extracted from sources, each tied to an exact excerpt. Useful guesses only. Never searchable as approved knowledge.",
  },
  {
    title: "Canonical knowledge",
    body: "Exact wording a person approved. Grounded answers and agent tools read only this layer, with citations back to the source excerpt.",
  },
];

const flow = [
  { step: "01", title: "Capture", text: "A source is stored with type, sensitivity, and immutable versions." },
  { step: "02", title: "Extract", text: "Deterministic or optional engines propose candidates with evidence. Engine output never skips review." },
  { step: "03", title: "Review", text: "A person edits wording beside the excerpt, then approves or rejects." },
  { step: "04", title: "Reuse", text: "Search, Ask, context packs, and MCP tools return approved knowledge with citations." },
];

const boundaries = [
  {
    title: "Workspace",
    text: "One company Brain. Every row belongs to exactly one workspace. Cross-workspace reads report not found, never forbidden.",
  },
  {
    title: "Sensitivity",
    text: "public, internal, private. Member ceiling stops at internal. Owner and admin may read private. Applied on every read path after retrieval.",
  },
  {
    title: "Identity vs reach",
    text: "Sign-in proves who you are. Membership grants which workspace you may use. Login alone never invents access.",
  },
  {
    title: "People vs machines",
    text: "Sessions and API keys are separate credential classes. A request carries exactly one. Agents never approve or change policy.",
  },
];

const invariants = [
  "Only the approval endpoint creates canonical knowledge.",
  "Raw sources, proposals, and canonical knowledge stay in different tables.",
  "Every citation points to the original source, title, and exact excerpt.",
  "Source changes create a new version and hash. Old evidence stays addressable.",
  "Canonical wording changes create a knowledge revision. History is append-only.",
  "Agent tools cannot approve, reject, delete, or publish.",
  "Optional engines must not be required for read, review, or export.",
  "Machine keys are stored hashed. Session secrets are stored hashed.",
  "Answers abstain when nothing approved matches. No silent cross-workspace fallback.",
  "Model output never supplies workspace, owner, status, or permission.",
];

const surfaces = [
  { name: "Console", detail: "Human review, sources, Brain search, Ask, Studio, audit." },
  { name: "Hosted MCP", detail: "Remote agents: search, ask, status, intake as proposals only." },
  { name: "Local MCP", detail: "Stdio server for Hermes, Codex, Claude Code, and similar hosts." },
  { name: "Connectors", detail: "Drive, Notion, OneDrive fetch into the review queue, never straight to canonical." },
];

function Wordmark() {
  return (
    <a href={SHOW_LANDING ? "#/" : "#/architecture"} className="site-wordmark" aria-label="Open Brain home">
      <span>Open Brain</span>
    </a>
  );
}

export default function ArchitecturePage() {
  const [menu, setMenu] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const menuRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!menu) return;
    const dialog = dialogRef.current;
    const opener = menuRef.current;
    if (!dialog) return;
    dialog.setAttribute("closedby", "any");
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    function fallback(e: MouseEvent) {
      if (e.target !== dialog || !dialog) return;
      const r = dialog.getBoundingClientRect();
      if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) setMenu(false);
    }
    if (!("closedBy" in HTMLDialogElement.prototype)) dialog.addEventListener("click", fallback);
    return () => {
      dialog.removeEventListener("click", fallback);
      if (dialog.open && typeof dialog.close === "function") dialog.close();
      opener?.focus();
    };
  }, [menu]);

  const nav = (
    <>
      {SHOW_LANDING && (
        <a href="#/" onClick={() => setMenu(false)}>
          Home
        </a>
      )}
      <a href="#/architecture" aria-current="page" onClick={() => setMenu(false)}>
        Architecture
      </a>
      {SHOW_LANDING && (
        <>
          <a href="#how-it-works" onClick={() => setMenu(false)}>
            How it works
          </a>
          <a href="#provenance" onClick={() => setMenu(false)}>
            Our principles
          </a>
        </>
      )}
    </>
  );

  return (
    <div className="brain-site site-docs">
      <a className="skip-link" href="#architecture-main">
        Skip to content
      </a>
      <header className="site-nav">
        <Wordmark />
        <nav aria-label="Website navigation">{nav}</nav>
        <button className="site-primary site-nav-cta" onClick={() => openConsole()}>
          Open Brain <ArrowUpRight size={13} />
        </button>
        <button
          className="site-menu"
          ref={menuRef}
          aria-label="Open website navigation"
          aria-expanded={menu}
          aria-controls="architecture-mobile-navigation"
          onClick={() => setMenu(true)}
        >
          <Menu size={20} />
        </button>
      </header>
      {menu && (
        <dialog
          ref={dialogRef}
          id="architecture-mobile-navigation"
          className="site-mobile-dialog"
          aria-label="Website navigation"
          onClose={() => setMenu(false)}
          onCancel={(e) => {
            e.preventDefault();
            setMenu(false);
          }}
        >
          <div className="site-dialog-head">
            <Wordmark />
            <button aria-label="Close website navigation" onClick={() => setMenu(false)}>
              <X size={20} />
            </button>
          </div>
          <nav aria-label="Mobile website navigation">{nav}</nav>
          <button className="site-primary" onClick={() => openConsole()}>
            Open your Brain <ArrowUpRight size={14} />
          </button>
        </dialog>
      )}

      <main id="architecture-main" className="site-docs-main">
        <section className="site-docs-hero site-inner">
          <p className="site-docs-kicker">
            <ShieldCheck size={14} aria-hidden="true" /> Architecture
          </p>
          <h1>How Open Brain keeps knowledge trustworthy.</h1>
          <p>
            A governed knowledge system for people and agents. Sources stay evidence. Proposals stay candidates. Only human
            approval creates reusable truth, with citations that never detach.
          </p>
          <div className="site-actions">
            <button className="site-primary" onClick={() => openConsole()}>
              Open your Brain <ArrowUpRight size={13} />
            </button>
            {SHOW_LANDING && (
              <button className="site-secondary" onClick={() => goTo("landing")}>
                Back to home <ArrowRight size={13} />
              </button>
            )}
            <a className="site-secondary site-docs-link-btn" href="https://github.com/anilandcode/open-intelligence-brain/blob/main/docs/architecture.md">
              Full architecture on GitHub <ArrowUpRight size={13} />
            </a>
          </div>
        </section>

        <section className="site-docs-section site-inner" aria-labelledby="trust-heading">
          <h2 id="trust-heading">Trust boundary</h2>
          <p className="site-docs-lead">
            Source text is untrusted data. It cannot approve itself, establish identity, change policy, or authorize a tool.
          </p>
          <ol className="site-docs-flow">
            {flow.map((item) => (
              <li key={item.step}>
                <span>{item.step}</span>
                <strong>{item.title}</strong>
                <p>{item.text}</p>
              </li>
            ))}
          </ol>
          <div className="site-docs-pipeline" aria-hidden="true">
            <span>
              <FileText size={16} /> Source
            </span>
            <i />
            <span>
              <Layers size={16} /> Proposal
            </span>
            <i />
            <span>
              <ShieldCheck size={16} /> Review
            </span>
            <i />
            <span>
              <Brain size={16} /> Canonical
            </span>
            <i />
            <span>
              <GitBranch size={16} /> Cited answers
            </span>
          </div>
        </section>

        <section className="site-docs-section site-inner" aria-labelledby="layers-heading">
          <h2 id="layers-heading">Three layers</h2>
          <div className="site-docs-grid three">
            {layers.map((layer) => (
              <article key={layer.title}>
                <h3>{layer.title}</h3>
                <p>{layer.body}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="site-docs-section site-inner" aria-labelledby="boundaries-heading">
          <h2 id="boundaries-heading">Access boundaries</h2>
          <div className="site-docs-grid two">
            {boundaries.map((item) => (
              <article key={item.title}>
                <h3>{item.title}</h3>
                <p>{item.text}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="site-docs-section site-inner" aria-labelledby="invariants-heading">
          <h2 id="invariants-heading">Core invariants</h2>
          <p className="site-docs-lead">Rules the product will not bend. Full list lives in the repository architecture doc.</p>
          <ul className="site-docs-invariants">
            {invariants.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </section>

        <section className="site-docs-section site-inner" aria-labelledby="surfaces-heading">
          <h2 id="surfaces-heading">Surfaces</h2>
          <div className="site-docs-grid two">
            {surfaces.map((item) => (
              <article key={item.name}>
                <h3>{item.name}</h3>
                <p>{item.detail}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="site-docs-section site-inner" aria-labelledby="stack-heading">
          <h2 id="stack-heading">Runtime shape</h2>
          <div className="site-docs-stack">
            <p>
              <strong>Web</strong> React workbench and public site. Console-first or landing build from the same SPA.
            </p>
            <p>
              <strong>API</strong> FastAPI domain services: capture, approval, search, graph, studio, connectors, audit.
            </p>
            <p>
              <strong>Data</strong> PostgreSQL in production, SQLite locally. Dialect-aware full-text search; optional vector
              channel fused with keyword rank.
            </p>
            <p>
              <strong>Agents</strong> Hosted Streamable HTTP MCP and local stdio MCP. Read approved knowledge; capture only
              creates proposals.
            </p>
          </div>
        </section>

        <section className="site-final-section">
          <div className="site-inner">
            <div className="site-final-card">
              <h2>Read the full specification.</h2>
              <p>Invariants, data model, retrieval, and provider boundaries are maintained in the open repository.</p>
              <div className="site-actions">
                <a className="site-primary" href="https://github.com/anilandcode/open-intelligence-brain/blob/main/docs/architecture.md">
                  docs/architecture.md <ArrowUpRight size={13} />
                </a>
                <button className="site-secondary" onClick={() => openConsole()}>
                  Open your Brain <ArrowUpRight size={13} />
                </button>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="site-footer">
        <div className="site-inner">
          <p>
            Open Brain
            <br />
            Sources → review → approved knowledge
          </p>
          <div className="site-footer-bottom">
            <span>© 2026 Open Brain</span>
            <a href="https://github.com/anilandcode/open-intelligence-brain">
              Source code <ArrowUpRight size={12} />
            </a>
            <a href="#/architecture">Architecture</a>
            {SHOW_LANDING && <a href="#/">Home</a>}
            <a href="#architecture-main">Back to top ↑</a>
          </div>
        </div>
      </footer>
    </div>
  );
}
