import { FormEvent, KeyboardEvent as ReactKeyboardEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, Archive, ArrowRight, ArrowUpDown, BarChart3, BookOpen, Boxes, Brain, Check, CheckCircle2,
  ChevronRight, CircleDot, Clock3, Copy, Download, FileText, Fingerprint, History, Home,
  Inbox, Layers3, Menu, MessageSquareText, Mic2, Plus, Search,
  ShieldCheck, Sparkles, TriangleAlert, X,
} from "lucide-react";
import {
  api, ChatResult, Integrity, Knowledge, KnowledgeRevision, Overview, Proposal, Source,
  clearToken, getToken, hasToken, setToken, Unauthorized,
} from "./api";

type View =
  | "overview" | "inbox" | "brain" | "studio" | "activate"
  | "analytics" | "sources" | "audit" | "ask";
type NavItem = { id: View; label: string; icon: typeof Home; future?: boolean };

const primaryNav: NavItem[] = [
  { id: "overview", label: "Overview", icon: Home },
  { id: "inbox", label: "Inbox", icon: Inbox },
  { id: "brain", label: "Brain", icon: Brain },
  { id: "studio", label: "Studio", icon: Mic2, future: true },
  { id: "activate", label: "Activate", icon: Sparkles },
];

const systemNav: NavItem[] = [
  { id: "sources", label: "Sources", icon: Archive },
  { id: "analytics", label: "Analytics", icon: BarChart3 },
  { id: "audit", label: "Audit", icon: Activity },
];

const navLabel = Object.fromEntries(
  [...primaryNav, ...systemNav].map((item) => [item.id, item.label]),
) as Record<View, string>;

type BrainSort = "recent" | "revisions" | "attention" | "alpha";

/* Sorts read straight off the stored record — approved_at, revision_count, integrity
   flags — so nothing on screen is inferred or estimated. */
const BRAIN_SORTS: Record<BrainSort, { label: string; compare: (a: Knowledge, b: Knowledge) => number }> = {
  recent: {
    label: "Newest",
    compare: (a, b) => new Date(b.approved_at).getTime() - new Date(a.approved_at).getTime(),
  },
  revisions: {
    label: "Most revised",
    compare: (a, b) =>
      b.revision_count - a.revision_count ||
      new Date(b.approved_at).getTime() - new Date(a.approved_at).getTime(),
  },
  attention: {
    label: "Needs attention",
    compare: (a, b) =>
      Number(b.stale || b.conflict_ids.length > 0) - Number(a.stale || a.conflict_ids.length > 0) ||
      b.revision_count - a.revision_count,
  },
  alpha: { label: "A–Z", compare: (a, b) => a.statement.localeCompare(b.statement) },
};

const BRAIN_SORT_ORDER = Object.keys(BRAIN_SORTS) as BrainSort[];

const titleMap: Record<View, { title: string; description: string }> = {
  overview: {
    title: "Good thinking should compound.",
    description: "Turn raw expertise into approved, reusable company intelligence—without losing the evidence behind it.",
  },
  inbox: {
    title: "Review inbox",
    description: "Inspect every proposal beside its original evidence before it becomes part of the Brain.",
  },
  brain: {
    title: "Your Brain",
    description: "Search the positions, lessons, decisions, and language your organisation has explicitly approved.",
  },
  studio: {
    title: "Intelligence Studio",
    description: "A guided workspace for turning expert conversations into theses, stories, frameworks, and evidence.",
  },
  activate: {
    title: "Activate intelligence",
    description: "Build a trusted context pack and transform it into briefs, articles, sales narratives, and agent context.",
  },
  analytics: {
    title: "Intelligence analytics",
    description: "Understand which ideas get reused, where evidence is weak, and what knowledge contributes to outcomes.",
  },
  sources: {
    title: "Source library",
    description: "Keep interviews, research, notes, and decisions separate from the interpretations built from them.",
  },
  audit: {
    title: "Audit trail",
    description: "See why the system believes what it believes, what changed, and which items need attention.",
  },
  ask: {
    title: "Ask your Brain",
    description: "Ask a question across approved knowledge and inspect the original evidence behind the response.",
  },
};

function timeAgo(value: string) {
  const seconds = Math.max(1, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function EmptyState({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <section className="empty-state">
      <div className="empty-icon" aria-hidden="true">{icon}</div>
      <h2>{title}</h2>
      <p>{children}</p>
    </section>
  );
}

function AppNav({
  label, items, view, proposalCount, onNavigate,
}: {
  label: string; items: NavItem[]; view: View; proposalCount: number; onNavigate: (view: View) => void;
}) {
  return (
    <div className="nav-group">
      <span className="nav-label">{label}</span>
      <ul>
        {items.map((item) => {
          const Icon = item.icon;
          return (
            <li key={item.id}>
              <button
                className={view === item.id ? "active" : ""}
                onClick={() => onNavigate(item.id)}
                aria-current={view === item.id ? "page" : undefined}
              >
                <Icon size={17} aria-hidden="true" />
                <span>{item.label}</span>
                {item.id === "inbox" && proposalCount > 0 && <span className="nav-count">{proposalCount}</span>}
                {item.future && view !== item.id && <span className="nav-preview">Soon</span>}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

type PaletteItem = {
  id: string;
  label: string;
  hint?: string;
  group: string;
  icon: ReactNode;
  run: () => void;
};

function CommandPalette({ knowledge, sources, onNavigate, onClose }: {
  knowledge: Knowledge[]; sources: Source[]; onNavigate: (view: View) => void; onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    inputRef.current?.focus();
    return () => { if (dialog.open && typeof dialog.close === "function") dialog.close(); };
  }, []);

  const items = useMemo<PaletteItem[]>(() => {
    const needle = query.toLowerCase().trim();
    const hit = (value: string) => !needle || value.toLowerCase().includes(needle);
    const navRows = [
      ...primaryNav.map((item) => ({ item, group: "Workspace" })),
      ...systemNav.map((item) => ({ item, group: "System" })),
    ];
    const nav: PaletteItem[] = navRows.map(({ item, group }) => {
      const Icon = item.icon;
      return {
        id: `nav-${item.id}`,
        label: item.label,
        hint: item.future ? "Preview" : undefined,
        group,
        icon: <Icon size={16} aria-hidden="true" />,
        run: () => onNavigate(item.id),
      };
    });
    const canon: PaletteItem[] = knowledge
      .filter((item) => hit(`${item.statement} ${item.type} ${item.source_title}`))
      .slice(0, 5)
      .map((item) => ({
        id: `knowledge-${item.id}`,
        label: item.statement,
        hint: `${item.type} · v${item.version}`,
        group: "Approved knowledge",
        icon: <BookOpen size={16} aria-hidden="true" />,
        run: () => onNavigate("brain"),
      }));
    const library: PaletteItem[] = sources
      .filter((item) => hit(`${item.title} ${item.kind}`))
      .slice(0, 4)
      .map((item) => ({
        id: `source-${item.id}`,
        label: item.title,
        hint: `${item.kind} · v${item.current_version}`,
        group: "Source library",
        icon: <FileText size={16} aria-hidden="true" />,
        run: () => onNavigate("sources"),
      }));
    const filteredNav = nav.filter((item) => hit(item.label));
    return [...filteredNav, ...canon, ...library];
  }, [query, knowledge, sources, onNavigate]);

  function handleKey(event: ReactKeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((prev) => (items.length ? (prev + 1) % items.length : 0));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((prev) => (items.length ? (prev - 1 + items.length) % items.length : 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const item = items[active];
      if (item) { onClose(); item.run(); }
    }
  }

  const groups = items.reduce<Record<string, PaletteItem[]>>((acc, item) => {
    (acc[item.group] ??= []).push(item);
    return acc;
  }, {});
  const flatIndex = (item: PaletteItem) => items.indexOf(item);

  return (
    <dialog ref={dialogRef} className="palette" aria-label="Search and jump to" onCancel={(event) => { event.preventDefault(); onClose(); }}>
      <div className="palette-field">
        <Search size={18} aria-hidden="true" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(event) => { setQuery(event.target.value); setActive(0); }}
          onKeyDown={handleKey}
          placeholder="Search knowledge, sources, or jump to a view…"
          aria-label="Search knowledge, sources, or jump to a view"
          aria-controls="palette-results"
        />
        <kbd>esc</kbd>
      </div>
      <div className="palette-results" id="palette-results" role="listbox" aria-label="Results">
        {items.length === 0 && <p className="palette-empty">Nothing matches “{query}”. Try a shorter phrase.</p>}
        {Object.entries(groups).map(([group, groupItems]) => (
          <div className="palette-group" key={group}>
            <span className="palette-group-label">{group}</span>
            {groupItems.map((item) => (
              <button
                key={item.id}
                type="button"
                role="option"
                aria-selected={flatIndex(item) === active}
                className={`palette-item ${flatIndex(item) === active ? "palette-item--active" : ""}`}
                onMouseEnter={() => setActive(flatIndex(item))}
                onClick={() => { onClose(); item.run(); }}
              >
                <span className="palette-item-icon">{item.icon}</span>
                <span className="palette-item-label">{item.label}</span>
                <span className="palette-item-hint">{item.hint}</span>
              </button>
            ))}
          </div>
        ))}
      </div>
      <div className="palette-foot">
        <span><kbd>↑</kbd><kbd>↓</kbd> navigate</span>
        <span><kbd>↵</kbd> open</span>
        <span>{items.length} result{items.length === 1 ? "" : "s"}</span>
      </div>
    </dialog>
  );
}

/* The access token is deliberately not part of the bundle, so an unauthenticated
   browser is met with somewhere to put one. The page discloses nothing: it
   renders this gate, and no request leaves it until a token is present. */
function AccessGate({ refused, onUnlock }: { refused: boolean; onUnlock: (token: string) => void }) {
  const [value, setValue] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!value.trim()) return;
    onUnlock(value.trim());
  }

  return (
    <div className="access-gate">
      <form className="access-card panel-card" onSubmit={submit}>
        <div className="brand">
          <span className="brand-mark" aria-hidden="true"><Brain size={20} strokeWidth={2.2} /></span>
          <span className="eyebrow">Open Brain</span>
        </div>
        <h1 className="access-title">Access token</h1>
        <p className="access-copy">
          This Brain answers only to the token its owner issued, and that token is never
          compiled into the page you just loaded.
        </p>
        {refused && (
          <div className="alert alert--error" role="alert">
            <TriangleAlert size={18} strokeWidth={2.1} />
            <span>That token was refused. Check it and try again.</span>
          </div>
        )}
        <div className="form-field">
          <label htmlFor="brain-token">Token</label>
          <input
            id="brain-token"
            className="input"
            type="password"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder="Paste the token you were given"
            autoComplete="off"
            spellCheck={false}
            autoFocus
          />
          <span className="field-help">
            Held in this browser&rsquo;s session storage, dropped when the tab closes, and sent as
            the <code>X-Brain-Token</code> header. A link may carry it instead as
            <code>#token=&hellip;</code>, which never reaches a server log.
          </span>
        </div>
        <div className="access-actions">
          <button className="primary-button" type="submit" disabled={!value.trim()}>
            Open the Brain
          </button>
          <span className="access-hint">No token? Ask whoever runs this Brain.</span>
        </div>
      </form>
    </div>
  );
}

export default function App() {
  const [view, setView] = useState<View>("overview");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [knowledge, setKnowledge] = useState<Knowledge[]>([]);
  const [integrity, setIntegrity] = useState<Integrity | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [showCapture, setShowCapture] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  // The token is not in the bundle, so the page starts locked until this browser
  // presents one. `tokenRefused` only distinguishes a wrong token from none.
  const [tokenRequired, setTokenRequired] = useState(!hasToken());
  const [tokenRefused, setTokenRefused] = useState(false);

  async function refresh() {
    try {
      setError("");
      const [overviewData, sourceData, proposalData, knowledgeData, integrityData] = await Promise.all([
        api.overview(), api.sources(), api.proposals(), api.knowledge(), api.integrity(),
      ]);
      setOverview(overviewData);
      setSources(sourceData);
      setProposals(proposalData);
      setKnowledge(knowledgeData);
      setIntegrity(integrityData);
    } catch (requestError) {
      recordRequestError(requestError);
    } finally {
      setLoading(false);
    }
  }

  // A refused token reopens the access screen; anything else is a real failure
  // of the Brain and belongs in the error banner.
  function recordRequestError(requestError: unknown) {
    if (requestError instanceof Unauthorized) {
      clearToken();
      setTokenRefused(true);
      setTokenRequired(true);
      setLoading(false);
      return;
    }
    setError(requestError instanceof Error ? requestError.message : "Could not load the workspace.");
  }

  function unlock(value: string) {
    setToken(value);
    setTokenRefused(false);
    setLoading(true);
    setTokenRequired(false);
  }

  useEffect(() => {
    // Nothing is requested before a token is present: an unauthenticated page
    // load must not reach the API at all.
    if (tokenRequired) return;
    let active = true;
    Promise.all([api.overview(), api.sources(), api.proposals(), api.knowledge(), api.integrity()])
      .then(([overviewData, sourceData, proposalData, knowledgeData, integrityData]) => {
        if (!active) return;
        setOverview(overviewData);
        setSources(sourceData);
        setProposals(proposalData);
        setKnowledge(knowledgeData);
        setIntegrity(integrityData);
      })
      .catch((requestError: unknown) => {
        if (!active) return;
        recordRequestError(requestError);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [tokenRequired]);

  useEffect(() => {
    function handleCommandSearch(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen(true);
        setMenuOpen(false);
      }
    }
    document.addEventListener("keydown", handleCommandSearch);
    return () => document.removeEventListener("keydown", handleCommandSearch);
  }, []);

  function navigate(next: View) {
    setView(next);
    setMenuOpen(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function handleExport() {
    try {
      const response = await fetch(api.exportUrl, { headers: { "X-Brain-Token": getToken() } });
      if (response.status === 401) throw new Unauthorized();
      if (!response.ok) throw new Error("Export failed");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `brain-export-${new Date().toISOString().slice(0, 10)}.json`;
      link.click();
      URL.revokeObjectURL(url);
      setNotice("Portable Brain export downloaded.");
    } catch (exportError) {
      if (exportError instanceof Unauthorized) recordRequestError(exportError);
      else setError("The workspace could not be exported.");
    }
  }

  const current = titleMap[view];

  if (tokenRequired) return <AccessGate refused={tokenRefused} onUnlock={unlock} />;

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <aside className={`sidebar ${menuOpen ? "sidebar--open" : ""}`} aria-label="Workspace navigation">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true"><Brain size={21} strokeWidth={2.1} /></div>
          <div><strong>Open Brain</strong><span>Intelligence OS</span></div>
        </div>
        <div className="workspace-switcher" aria-label="Current workspace: Personal Brain">
          <span className="workspace-avatar">P</span>
          <span><small>Workspace</small><strong>Personal Brain</strong></span>
          <ChevronRight size={15} aria-hidden="true" />
        </div>
        <nav aria-label="Primary navigation">
          <AppNav label="Workspace" items={primaryNav} view={view} proposalCount={proposals.length} onNavigate={navigate} />
          <AppNav label="System" items={systemNav} view={view} proposalCount={proposals.length} onNavigate={navigate} />
        </nav>
        <div className="sidebar-footer">
          <div className="rail-status">
            <span className="status-light" aria-hidden="true" />
            <span><strong>Local mode</strong><small>Hosted AI is off</small></span>
            <ShieldCheck size={15} aria-hidden="true" />
          </div>
          <div className="rail-account">
            <span className="workspace-avatar">L</span>
            <span><strong>Local workspace</strong><small>No account connected</small></span>
            <button className="rail-action" onClick={handleExport} title="Export workspace" aria-label="Export workspace"><Download size={15} /></button>
          </div>
          <span className="version-label">Open Brain · v0.3 interface</span>
        </div>
      </aside>

      {menuOpen && <button className="scrim" aria-label="Close navigation" onClick={() => setMenuOpen(false)} />}

      <div className="main-column">
        <header className="topbar">
          <div className="topbar-start">
            <button className="menu-button" onClick={() => setMenuOpen(true)} aria-label="Open navigation"><Menu size={20} /></button>
            <nav className="topbar-crumbs" aria-label="Breadcrumb">
              <span>Personal Brain</span>
              <ChevronRight size={13} aria-hidden="true" />
              <strong>{navLabel[view]}</strong>
            </nav>
          </div>
          <div className="topbar-actions">
            <button className="command-button" onClick={() => setPaletteOpen(true)}>
              <Search size={16} aria-hidden="true" />
              <span>Search or jump to…</span>
              <kbd>⌘K</kbd>
            </button>
            <button className="capture-button" onClick={() => setShowCapture(true)}><Plus size={17} /> Capture source</button>
          </div>
        </header>

        <main id="main-content">
          <header className="page-heading">
            <div><h1>{current.title}</h1><p>{current.description}</p></div>
            {view === "brain" && <button className="secondary-button btn--pill" onClick={() => navigate("ask")}><MessageSquareText size={17} /> Ask the Brain</button>}
            {view === "sources" && <button className="primary-button btn--pill" onClick={() => setShowCapture(true)}><Plus size={17} /> Add source</button>}
            {view === "audit" && <button className="secondary-button btn--pill" onClick={handleExport}><Download size={17} /> Export audit data</button>}
          </header>

          {error && <div className="alert alert--error" role="alert"><X size={18} /><span>{error}</span><button onClick={() => setError("")}>Dismiss</button></div>}
          {notice && <div className="alert alert--success" role="status"><Check size={18} /><span>{notice}</span><button onClick={() => setNotice("")}>Dismiss</button></div>}

          {loading ? <LoadingState /> : (
            <>
              {view === "overview" && overview && <OverviewView overview={overview} proposals={proposals} knowledge={knowledge} integrity={integrity} onNavigate={navigate} />}
              {view === "inbox" && <InboxView proposals={proposals} onChanged={refresh} onNotice={setNotice} onError={setError} />}
              {view === "brain" && <BrainView initial={knowledge} onChanged={refresh} onNotice={setNotice} onError={setError} />}
              {view === "sources" && <SourcesView sources={sources} onChanged={refresh} onNotice={setNotice} onError={setError} />}
              {view === "ask" && <AskView />}
              {view === "studio" && <StudioPreview onCapture={() => setShowCapture(true)} />}
              {view === "activate" && <ActivateView knowledge={knowledge} onNavigate={navigate} onNotice={setNotice} />}
              {view === "analytics" && <AnalyticsPreview overview={overview} knowledge={knowledge} integrity={integrity} />}
              {view === "audit" && overview && <AuditView overview={overview} integrity={integrity} />}
            </>
          )}
        </main>
      </div>

      {showCapture && (
        <CaptureDialog
          onClose={() => setShowCapture(false)}
          onCreated={async () => {
            setShowCapture(false);
            setNotice("Source captured and proposals added to your inbox.");
            await refresh();
            navigate("inbox");
          }}
          onError={setError}
        />
      )}
      {paletteOpen && (
        <CommandPalette
          knowledge={knowledge}
          sources={sources}
          onNavigate={navigate}
          onClose={() => setPaletteOpen(false)}
        />
      )}
    </div>
  );
}
function LoadingState() {
  return (
    <div className="overview-layout loading-board" role="status" aria-live="polite" aria-label="Loading workspace">
      <section className="hero-card" aria-hidden="true">
        <div className="hero-copy">
          <div className="skeleton skeleton--pill" />
          <div className="skeleton skeleton--title" />
          <div className="skeleton skeleton--title skeleton--title-short" />
          <div className="skeleton skeleton--line" />
          <div className="skeleton skeleton--line skeleton--line-short" />
          <div className="skeleton-actions"><div className="skeleton skeleton--button" /><div className="skeleton skeleton--button" /></div>
        </div>
        <div className="skeleton skeleton--orbit" />
      </section>
      <section className="metric-strip" aria-hidden="true">
        {[0, 1, 2, 3].map((tile) => (
          <div className="metric-item" key={tile}>
            <div className="skeleton skeleton--icon" />
            <div className="loading-metric-body">
              <div className="skeleton skeleton--line skeleton--line-tight" />
              <div className="skeleton skeleton--value" />
              <div className="skeleton skeleton--line skeleton--line-short" />
            </div>
          </div>
        ))}
      </section>
      <section className="panel-card" aria-hidden="true">
        <div className="loading-panel-head"><div className="skeleton skeleton--line skeleton--line-tight" /><div className="skeleton skeleton--title" /></div>
        <div className="skeleton skeleton--panel" />
      </section>
      <span className="sr-only">Loading your Brain…</span>
    </div>
  );
}

function OverviewView({
  overview, proposals, knowledge, integrity, onNavigate,
}: {
  overview: Overview; proposals: Proposal[]; knowledge: Knowledge[]; integrity: Integrity | null; onNavigate: (view: View) => void;
}) {
  const attentionCount = (integrity?.stale_count ?? 0) + (integrity?.conflict_count ?? 0);
  const extracted = overview.canonical + overview.pending_reviews;
  const approvedShare = extracted ? overview.canonical / extracted : 0;
  // Order-independent reductions: neither list's server ordering is assumed.
  const oldestWaiting = proposals.length
    ? proposals.reduce((oldest, item) => (item.created_at < oldest.created_at ? item : oldest))
    : null;
  const latestEvent = overview.recent_activity.length
    ? overview.recent_activity.reduce((newest, item) => (item.created_at > newest.created_at ? item : newest))
    : null;
  return (
    <div className="overview-layout">
      <section className="hero-card">
        <div className="hero-copy">
          <div className="hero-signals">
            <span className="signal-pill"><span /> {attentionCount ? `${attentionCount} integrity signals` : "Knowledge system healthy"}</span>
            {/* Which engine produced the proposals below. A silent fallback to
                local extraction is how a deployment ends up believing it is
                running on a model when it is not, so it sits next to the
                existing health signal where it is read, not below the fold. */}
            <span
              className={`signal-pill signal-pill--engine engine-note--${overview.engine.name}${
                overview.engine.degraded ? " engine-note--degraded" : ""
              }`}
              title={overview.engine.detail}
            >
              <span className="engine-dot" aria-hidden="true" />
              {overview.engine.degraded
                ? "not learning from new sources"
                : `${overview.engine.name} extraction`}
            </span>
          </div>
          <h2 className="hero-title">
            <span className="hero-title-figure">{overview.canonical.toLocaleString()}</span>
            <span className="hero-title-unit">{overview.canonical === 1 ? "approved atom" : "approved atoms"}</span>
            <em>{overview.pending_reviews ? `${overview.pending_reviews} still waiting on your call.` : "Nothing is waiting on you."}</em>
          </h2>
          <p>Every statement here traces back to a source excerpt. Nothing becomes knowledge until a person approves the exact wording.</p>
          <div className="hero-actions">
            <button className="primary-button" onClick={() => onNavigate(proposals.length ? "inbox" : "sources")}>{proposals.length ? "Review next proposal" : "Capture your first source"}<ArrowRight size={17} /></button>
            <button className="light-button" onClick={() => onNavigate("ask")}><MessageSquareText size={17} /> Ask the Brain</button>
          </div>
        </div>
        <aside className="hero-ratio" aria-label="Approval ratio">
          <span className="hero-ratio-value">{Math.round(approvedShare * 100)}<small>%</small></span>
          <span className="hero-ratio-label">of {extracted.toLocaleString()} extracted claims approved</span>
          <span className="hero-ratio-bar" role="img" aria-label={`${Math.round(approvedShare * 100)} percent of extracted claims approved`}>
            <span style={{ width: `${Math.round(approvedShare * 100)}%` }} />
          </span>
          <dl className="hero-facts">
            <div><dt>Oldest waiting</dt><dd>{oldestWaiting ? timeAgo(oldestWaiting.created_at) : "—"}</dd></div>
            <div><dt>Latest activity</dt><dd>{latestEvent ? timeAgo(latestEvent.created_at) : "—"}</dd></div>
          </dl>
        </aside>
      </section>

      <section className="metric-strip" aria-label="Workspace summary">
        <Metric label="Approved knowledge" value={overview.canonical} detail="Ready to reuse" icon={<CheckCircle2 />} tone="green" share={approvedShare} shareNote={`${Math.round(approvedShare * 100)}% of ${extracted} extracted claims`} />
        <Metric label="Waiting for review" value={overview.pending_reviews} detail="Needs judgement" icon={<Clock3 />} tone="amber" share={extracted ? 1 - approvedShare : 0} shareNote={`${Math.round((1 - approvedShare) * 100)}% still unreviewed`} />
        <Metric label="Source material" value={overview.sources} detail="Immutable originals" icon={<Boxes />} tone="blue" />
        <Metric label="Integrity signals" value={attentionCount} detail={attentionCount ? "Needs attention" : "No issues found"} icon={<ShieldCheck />} tone={attentionCount ? "violet" : ""} />
      </section>

      <section className="pipeline-card panel-card">
        <div className="card-heading">
          <div><span className="section-kicker">Knowledge pipeline</span><h2>How the Brain gets smarter</h2><p className="section-sub">Each stage keeps the original evidence attached to the claim it produced.</p></div>
          <span className="updated-label"><span /> Live workspace</span>
        </div>
        <div className="pipeline">
          <button onClick={() => onNavigate("sources")}><span className="pipeline-icon"><Archive size={19} /></span><span><small>01 · Capture</small><strong>{overview.sources} sources</strong><em>Original material stays intact</em></span></button>
          <ChevronRight size={18} className="pipeline-arrow" aria-hidden="true" />
          <button onClick={() => onNavigate("inbox")}><span className="pipeline-icon pipeline-icon--amber"><Inbox size={19} /></span><span><small>02 · Judge</small><strong>{overview.pending_reviews} proposals</strong><em>Humans decide what is true</em></span></button>
          <ChevronRight size={18} className="pipeline-arrow" aria-hidden="true" />
          <button onClick={() => onNavigate("brain")}><span className="pipeline-icon pipeline-icon--green"><Brain size={19} /></span><span><small>03 · Compound</small><strong>{overview.canonical} canonical atoms</strong><em>Approved context gets reused</em></span></button>
        </div>
      </section>

      <section className="work-grid">
        <div className="panel-card queue-preview">
          <div className="card-heading"><div><span className="section-kicker">Needs judgement</span><h2>Review queue</h2><p className="section-sub">Nothing enters the canon until a person approves the exact wording.</p></div><button className="text-button" onClick={() => onNavigate("inbox")}>Open inbox <ArrowRight size={15} /></button></div>
          {proposals.length ? (
            <div className="overview-table-scroll">
              <table className="overview-table">
                <thead>
                  <tr>
                    <th scope="col" className="num">#</th>
                    <th scope="col">Proposed statement</th>
                    <th scope="col">Type</th>
                    <th scope="col">Source</th>
                    <th scope="col" className="num">Added</th>
                    <th scope="col"><span className="sr-only">Action</span></th>
                  </tr>
                </thead>
                <tbody>
                  {proposals.slice(0, 4).map((proposal, index) => (
                    <tr key={proposal.id}>
                      <td className="num overview-table-index">{String(index + 1).padStart(2, "0")}</td>
                      <td className="overview-table-statement" title={proposal.statement}>{proposal.statement}</td>
                      <td><span className="type-chip">{proposal.type}</span></td>
                      <td className="overview-table-source" title={proposal.source_title}>{proposal.source_title}</td>
                      <td className="num overview-table-age">{timeAgo(proposal.created_at)}</td>
                      <td className="num">
                        <button className="table-go" onClick={() => onNavigate("inbox")} aria-label={`Review proposal: ${proposal.statement}`}>Review<ArrowRight size={14} /></button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <EmptyState icon={<Check />} title="Inbox clear">New extractions will appear here when you capture another source.</EmptyState>}
        </div>

        <div className="panel-card recent-preview">
          <div className="card-heading"><div><span className="section-kicker">Current canon</span><h2>Recently approved</h2><p className="section-sub">The positions your team and agents can safely reuse today.</p></div><button className="text-button" onClick={() => onNavigate("brain")}>View Brain <ArrowRight size={15} /></button></div>
          {knowledge.length ? (
            <div className="overview-table-scroll">
              <table className="overview-table overview-table--canon">
                <thead>
                  <tr>
                    <th scope="col">Approved statement</th>
                    <th scope="col">Type</th>
                    <th scope="col">Ver</th>
                    <th scope="col" className="num">Approved</th>
                    <th scope="col"><span className="sr-only">State</span></th>
                  </tr>
                </thead>
                <tbody>
                  {knowledge.slice(0, 4).map((item) => (
                    <tr key={item.id}>
                      <td className="overview-table-statement" title={item.statement}>{item.statement}</td>
                      <td><span className="type-chip">{item.type}</span></td>
                      <td><span className="version-chip">v{item.version}</span></td>
                      <td className="num overview-table-age">{timeAgo(item.approved_at)}</td>
                      <td className="num">
                        {item.stale || item.conflict_ids.length
                          ? <TriangleAlert size={16} className="attention-icon" aria-label="Needs attention" />
                          : <CheckCircle2 size={16} className="verified-icon" aria-label="Verified" />}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <EmptyState icon={<BookOpen />} title="No canonical knowledge">Approve a proposal to begin building the Brain.</EmptyState>}
        </div>
      </section>
    </div>
  );
}

function SortHeader({ label, sortKey, sort, onSort, numeric }: {
  label: string; sortKey: string; sort: { key: string; dir: "asc" | "desc" };
  onSort: (key: string) => void; numeric?: boolean;
}) {
  const active = sort.key === sortKey;
  return (
    <th scope="col" className={numeric ? "num" : undefined} aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}>
      <button type="button" className={`sort-button ${active ? "sort-button--active" : ""}`} onClick={() => onSort(sortKey)}>
        {label}<ArrowUpDown size={13} aria-hidden="true" data-dir={active ? sort.dir : "none"} />
      </button>
    </th>
  );
}

type SortableRow = { [key: string]: string | number };

function useSortedRows<T extends SortableRow>(rows: T[], initialKey: string, initialDir: "asc" | "desc" = "desc") {
  const [sort, setSort] = useState<{ key: string; dir: "asc" | "desc" }>({ key: initialKey, dir: initialDir });
  const sorted = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      const av = a[sort.key];
      const bv = b[sort.key];
      const cmp = typeof av === "number" && typeof bv === "number" ? av - bv : String(av).localeCompare(String(bv));
      return sort.dir === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [rows, sort]);
  function toggle(key: string) {
    setSort((prev) => ({ key, dir: prev.key === key && prev.dir === "desc" ? "asc" : "desc" }));
  }
  return { sorted, sort, toggle };
}

type Period = "1d" | "7d" | "30d" | "all";

const PERIODS: Array<{ id: Period; label: string }> = [
  { id: "1d", label: "24h" },
  { id: "7d", label: "7d" },
  { id: "30d", label: "30d" },
  { id: "all", label: "All" },
];
const PERIOD_MS: Record<Period, number> = { "1d": 86_400_000, "7d": 604_800_000, "30d": 2_592_000_000, all: 0 };

function filterByPeriod<T extends { created_at: string }>(rows: T[], period: Period): T[] {
  if (period === "all") return rows;
  const cutoff = Date.now() - PERIOD_MS[period];
  return rows.filter((row) => new Date(row.created_at).getTime() >= cutoff);
}

function PeriodFilter({ period, onChange }: { period: Period; onChange: (next: Period) => void }) {
  return (
    <div className="segmented" role="group" aria-label="Time range">
      {PERIODS.map((option) => (
        <button key={option.id} type="button" aria-pressed={period === option.id} onClick={() => onChange(option.id)}>
          {option.label}
        </button>
      ))}
    </div>
  );
}

function Metric({ label, value, detail, icon, tone, share, shareNote }: {
  label: string; value: number; detail: string; icon: ReactNode; tone: string; share?: number; shareNote?: string;
}) {
  const pct = typeof share === "number" ? Math.round(share * 100) : null;
  return (
    <article className={`metric-item metric-item--${tone}`}>
      <span className={`metric-icon metric-icon--${tone}`} aria-hidden="true">{icon}</span>
      <div>
        <small className="metric-label">{label}</small>
        <strong className="metric-value">{value.toLocaleString()}</strong>
        <span className="metric-foot"><span className={`status-dot status-dot--${tone}`} aria-hidden="true" />{detail}</span>
        {pct !== null && (
          <span className="metric-share">
            <span className="bar bar--accent" role="img" aria-label={`${pct}% — ${shareNote ?? detail}`}><span style={{ width: `${pct}%` }} /></span>
            {shareNote && <small>{shareNote}</small>}
          </span>
        )}
      </div>
    </article>
  );
}

function InboxView({ proposals, onChanged, onNotice, onError }: { proposals: Proposal[]; onChanged: () => Promise<void>; onNotice: (value: string) => void; onError: (value: string) => void }) {
  const [selectedId, setSelectedId] = useState(proposals[0]?.id ?? "");
  const selected = proposals.find((proposal) => proposal.id === selectedId) ?? proposals[0];

  if (!selected) return <section className="panel-card"><EmptyState icon={<CheckCircle2 />} title="Your inbox is clear">Every current proposal has been reviewed. Capture new material when you are ready.</EmptyState></section>;

  return (
    <section className="review-workspace">
      <aside className="review-queue" aria-label="Proposal queue">
        <header><div><span className="section-kicker">Queue</span><h2>{proposals.length} to review</h2></div><span className="queue-badge">{proposals.length}</span></header>
        <div className="review-queue-list">
          {proposals.map((proposal, index) => (
            <button key={proposal.id} className={selected.id === proposal.id ? "active" : ""} onClick={() => setSelectedId(proposal.id)} aria-current={selected.id === proposal.id ? "true" : undefined}>
              <span className="queue-number">{String(index + 1).padStart(2, "0")}</span>
              <span><small>{proposal.type}</small><strong>{proposal.statement}</strong><em>{proposal.source_title}</em></span>
            </button>
          ))}
        </div>
      </aside>
      <ReviewEditor key={selected.id} proposal={selected} onChanged={onChanged} onNotice={onNotice} onError={onError} />
    </section>
  );
}

function ReviewEditor({ proposal, onChanged, onNotice, onError }: { proposal: Proposal; onChanged: () => Promise<void>; onNotice: (value: string) => void; onError: (value: string) => void }) {
  const [statement, setStatement] = useState(proposal.statement);
  const [rationale, setRationale] = useState(proposal.rationale);
  const [busy, setBusy] = useState(false);
  const [rejectMode, setRejectMode] = useState(false);
  const [rejectReason, setRejectReason] = useState("");

  async function approve(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    try {
      await api.approveProposal(proposal.id, statement, rationale);
      onNotice("Proposal approved and added to canonical knowledge.");
      await onChanged();
    } catch (requestError) {
      onError(requestError instanceof Error ? requestError.message : "Approval failed.");
    } finally { setBusy(false); }
  }

  async function reject() {
    if (!rejectReason.trim()) return;
    setBusy(true);
    try {
      await api.rejectProposal(proposal.id, rejectReason.trim());
      onNotice("Proposal rejected. The source remains unchanged.");
      await onChanged();
    } catch (requestError) {
      onError(requestError instanceof Error ? requestError.message : "Rejection failed.");
    } finally { setBusy(false); }
  }

  return (
    <article className="review-editor">
      <form onSubmit={approve}>
        <header className="review-editor-header">
          <div><span className="type-chip">{proposal.type}</span><span className="status-chip"><CircleDot size={11} /> Proposed</span></div>
          <span className="source-reference"><FileText size={15} /> {proposal.source_title}</span>
        </header>
        <div className="editor-body">
          <section className="canonical-editor">
            <div className="field-heading"><label htmlFor={`statement-${proposal.id}`}>Canonical statement</label><span>Editable before approval</span></div>
            <textarea id={`statement-${proposal.id}`} value={statement} onChange={(event) => setStatement(event.target.value)} rows={5} required minLength={3} />
            <div className="field-heading"><label htmlFor={`rationale-${proposal.id}`}>Why we believe this</label><span>Internal reasoning</span></div>
            <textarea id={`rationale-${proposal.id}`} value={rationale} onChange={(event) => setRationale(event.target.value)} rows={4} />
          </section>
          <aside className="evidence-panel">
            <div className="evidence-heading"><span><Fingerprint size={15} /> Exact evidence</span><ShieldCheck size={16} /></div>
            <blockquote>{proposal.source_excerpt}</blockquote>
            <dl>
              <div><dt>Source</dt><dd>{proposal.source_title}</dd></div>
              <div><dt>Captured</dt><dd>{timeAgo(proposal.created_at)}</dd></div>
              <div><dt>Integrity</dt><dd><span className="verified-dot" /> Original preserved</dd></div>
            </dl>
          </aside>
        </div>
        {rejectMode && (
          <div className="reject-panel">
            <div><label htmlFor={`reject-reason-${proposal.id}`}>Why should this proposal be rejected?</label><span id={`reject-help-${proposal.id}`}>The source remains unchanged and the reason is kept in the audit trail.</span></div>
            <input id={`reject-reason-${proposal.id}`} value={rejectReason} onChange={(event) => setRejectReason(event.target.value)} minLength={3} required autoFocus aria-describedby={`reject-help-${proposal.id}`} placeholder="Not useful, duplicate, or inaccurate…" />
            <button className="danger-button" type="button" disabled={busy || rejectReason.trim().length < 3} onClick={reject}>Confirm reject</button>
            <button className="secondary-button" type="button" disabled={busy} onClick={() => { setRejectMode(false); setRejectReason(""); }}>Cancel</button>
          </div>
        )}
        <footer className="review-actions">
          <p><ShieldCheck size={15} /> Approval creates an immutable first revision.</p>
          <div><button className="danger-button" type="button" disabled={busy} onClick={() => setRejectMode(true)}>Reject</button><button className="primary-button" type="submit" disabled={busy}><Check size={17} /> {busy ? "Saving…" : "Approve to Brain"}</button></div>
        </footer>
      </form>
    </article>
  );
}

function BrainView({ initial, onChanged, onNotice, onError }: { initial: Knowledge[]; onChanged: () => Promise<void>; onNotice: (value: string) => void; onError: (value: string) => void }) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "attention">("all");
  const [sort, setSort] = useState<BrainSort>("recent");
  const filtered = useMemo(() => {
    const needle = query.toLowerCase().trim();
    const rows = initial.filter((item) => {
      const matchesText = !needle || `${item.statement} ${item.rationale} ${item.type} ${item.source_title}`.toLowerCase().includes(needle);
      const matchesFilter = filter === "all" || item.stale || item.conflict_ids.length > 0;
      return matchesText && matchesFilter;
    });
    return rows.sort(BRAIN_SORTS[sort].compare);
  }, [initial, query, filter, sort]);

  return (
    <section className="brain-workspace panel-card">
      <div className="brain-toolbar">
        <search><form action="/" method="get" onSubmit={(event) => event.preventDefault()}><label className="sr-only" htmlFor="brain-search">Search approved knowledge</label><div className="search-field"><Search size={18} aria-hidden="true" /><input id="brain-search" name="q" type="search" placeholder="Search claims, decisions, stories, language…" value={query} onChange={(event) => setQuery(event.target.value)} /></div></form></search>
        <div className="filter-tabs" aria-label="Knowledge filters">
          <button className={filter === "all" ? "active" : ""} onClick={() => setFilter("all")}>All knowledge <span>{initial.length}</span></button>
          <button className={filter === "attention" ? "active" : ""} onClick={() => setFilter("attention")}>Needs attention <span>{initial.filter((item) => item.stale || item.conflict_ids.length).length}</span></button>
        </div>
        <div className="segmented segmented--sort" role="group" aria-label="Sort approved knowledge">
          {BRAIN_SORT_ORDER.map((key) => (
            <button key={key} type="button" aria-pressed={sort === key} onClick={() => setSort(key)}>{BRAIN_SORTS[key].label}</button>
          ))}
        </div>
      </div>
      <div className="brain-list-heading"><span>{filtered.length} canonical {filtered.length === 1 ? "item" : "items"}</span><span><ShieldCheck size={14} /> Approved revisions only</span></div>
      <div className="knowledge-list">
        {filtered.map((item) => <KnowledgeCard key={item.id} item={item} onChanged={onChanged} onNotice={onNotice} onError={onError} />)}
        {filtered.length === 0 && <EmptyState icon={<Search />} title="No approved matches">Try a broader phrase or change the current filter.</EmptyState>}
      </div>
    </section>
  );
}

function KnowledgeCard({ item, onChanged, onNotice, onError }: { item: Knowledge; onChanged: () => Promise<void>; onNotice: (value: string) => void; onError: (value: string) => void }) {
  const [revisions, setRevisions] = useState<KnowledgeRevision[]>([]);
  const [statement, setStatement] = useState(item.statement);
  const [rationale, setRationale] = useState(item.rationale);
  const [changeNote, setChangeNote] = useState("");
  const [saving, setSaving] = useState(false);

  async function loadHistory() {
    if (revisions.length) return;
    try { setRevisions(await api.knowledgeRevisions(item.id)); }
    catch (requestError) { onError(requestError instanceof Error ? requestError.message : "Could not load revision history."); }
  }

  async function supersede(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    try {
      await api.supersedeKnowledge(item.id, statement, rationale, changeNote);
      onNotice("A new immutable knowledge revision is now canonical.");
      setChangeNote("");
      setRevisions([]);
      await onChanged();
    } catch (requestError) {
      onError(requestError instanceof Error ? requestError.message : "Could not create revision.");
    } finally { setSaving(false); }
  }

  const attention = item.stale || item.conflict_ids.length > 0;
  return (
    <article className={`knowledge-card ${attention ? "knowledge-card--attention" : ""}`}>
      <div className="knowledge-card-icon">{attention ? <TriangleAlert size={18} /> : <BookOpen size={18} />}</div>
      <div className="knowledge-card-main">
        <div className="knowledge-card-meta"><span className="type-chip">{item.type}</span><span>v{item.version}</span><span>·</span><span>{item.source_title}</span>{item.stale && <span className="warning-chip">Source updated</span>}{item.conflict_ids.length > 0 && <span className="warning-chip">Possible conflict</span>}</div>
        <h2>{item.statement}</h2><p>{item.rationale}</p>
        <details className="history-disclosure" onToggle={(event) => { if (event.currentTarget.open) void loadHistory(); }}>
          <summary><History size={15} aria-hidden="true" /> {item.revision_count} {item.revision_count === 1 ? "revision" : "revisions"} · inspect or supersede</summary>
          <div className="history-layout">
            <ol className="revision-list">
              {revisions.map((revision) => <li key={revision.id}><div><strong>Revision {revision.revision}</strong><time dateTime={revision.approved_at}>{timeAgo(revision.approved_at)}</time></div><p>{revision.statement}</p><small>{revision.change_note}</small></li>)}
            </ol>
            <form className="revision-form" onSubmit={supersede}>
              <div className="form-field"><label htmlFor={`revision-statement-${item.id}`}>New canonical wording</label><textarea id={`revision-statement-${item.id}`} value={statement} onChange={(event) => setStatement(event.target.value)} rows={3} minLength={3} required /></div>
              <div className="form-field"><label htmlFor={`revision-rationale-${item.id}`}>Rationale</label><textarea id={`revision-rationale-${item.id}`} value={rationale} onChange={(event) => setRationale(event.target.value)} rows={2} /></div>
              <div className="form-field"><label htmlFor={`revision-note-${item.id}`}>Revision note</label><input id={`revision-note-${item.id}`} value={changeNote} onChange={(event) => setChangeNote(event.target.value)} minLength={3} required placeholder="What changed, and why?" /></div>
              <button className="primary-button" type="submit" disabled={saving || (statement === item.statement && rationale === item.rationale)}>{saving ? "Saving…" : "Approve new revision"}</button>
            </form>
          </div>
        </details>
      </div>
      <span className={attention ? "attention-icon" : "verified-icon"}>{attention ? <TriangleAlert size={17} /> : <CheckCircle2 size={17} />}</span>
    </article>
  );
}

type SourceSort = "recent" | "versions" | "proposals" | "title";

const SOURCE_SORTS: Record<SourceSort, { label: string; compare: (a: Source, b: Source) => number }> = {
  recent: {
    label: "Newest",
    compare: (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  },
  versions: {
    label: "Most versions",
    compare: (a, b) =>
      b.current_version - a.current_version ||
      new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  },
  proposals: {
    label: "Most proposals",
    compare: (a, b) =>
      b.proposal_count - a.proposal_count ||
      new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  },
  title: { label: "A–Z", compare: (a, b) => a.title.localeCompare(b.title) },
};

const SOURCE_SORT_ORDER = Object.keys(SOURCE_SORTS) as SourceSort[];

function SourcesView({ sources, onChanged, onNotice, onError }: { sources: Source[]; onChanged: () => Promise<void>; onNotice: (value: string) => void; onError: (value: string) => void }) {
  const [kind, setKind] = useState<string>("all");
  const [sort, setSort] = useState<SourceSort>("recent");

  const kinds = useMemo(() => {
    const counts = new Map<string, number>();
    sources.forEach((source) => counts.set(source.kind, (counts.get(source.kind) ?? 0) + 1));
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [sources]);

  const visible = useMemo(() => {
    const rows = kind === "all" ? sources : sources.filter((source) => source.kind === kind);
    return [...rows].sort(SOURCE_SORTS[sort].compare);
  }, [sources, kind, sort]);

  return (
    <section className="source-workspace">
      <div className="library-summary panel-card">
        <div><span className="metric-icon metric-icon--blue"><Archive size={20} /></span><span><small>Source library</small><strong>{sources.length} immutable originals</strong></span></div>
        <p>Every change creates a new hashed version. Approved knowledge keeps pointing to the exact evidence it came from.</p>
      </div>
      {sources.length === 0 ? <section className="panel-card"><EmptyState icon={<Archive />} title="No sources yet">Capture a project note, interview, decision, or piece of research.</EmptyState></section> : (
        <>
          <div className="source-toolbar">
            <div className="filter-tabs" aria-label="Filter sources by kind">
              <button className={kind === "all" ? "active" : ""} onClick={() => setKind("all")}>All kinds <span>{sources.length}</span></button>
              {kinds.map(([name, count]) => (
                <button key={name} className={kind === name ? "active" : ""} onClick={() => setKind(name)}>{name} <span>{count}</span></button>
              ))}
            </div>
            <div className="segmented segmented--sort" role="group" aria-label="Sort sources">
              {SOURCE_SORT_ORDER.map((key) => (
                <button key={key} type="button" aria-pressed={sort === key} onClick={() => setSort(key)}>{SOURCE_SORTS[key].label}</button>
              ))}
            </div>
          </div>
          <div className="source-grid">
            {visible.map((source) => <SourceCard key={source.id} source={source} onChanged={onChanged} onNotice={onNotice} onError={onError} />)}
            {visible.length === 0 && <section className="panel-card"><EmptyState icon={<Archive />} title="No sources of this kind">Pick another kind, or reset the filter to all kinds.</EmptyState></section>}
          </div>
        </>
      )}
    </section>
  );
}

function SourceCard({ source, onChanged, onNotice, onError }: { source: Source; onChanged: () => Promise<void>; onNotice: (value: string) => void; onError: (value: string) => void }) {
  const [content, setContent] = useState(source.content);
  const [changeNote, setChangeNote] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    try {
      await api.addSourceVersion(source.id, content, changeNote);
      onNotice("Immutable source version created and new proposals added for review.");
      setChangeNote("");
      await onChanged();
    } catch (requestError) {
      onError(requestError instanceof Error ? requestError.message : "Could not add source version.");
    } finally { setSaving(false); }
  }

  return (
    <article className="source-card">
      <header><span className="source-icon"><FileText size={18} /></span><div className="source-meta"><span>{source.kind}</span><span>·</span><span>{source.sensitivity}</span></div><span className="version-chip">v{source.current_version}</span></header>
      <h2>{source.title}</h2><p>{source.content}</p>
      <div className="source-integrity"><span><Fingerprint size={14} /><code>{source.content_hash.slice(0, 12)}</code></span><span>SHA-256 verified</span></div>
      <footer><span>{source.proposal_count} proposals</span><time dateTime={source.created_at}>{timeAgo(source.created_at)}</time></footer>
      <details className="version-disclosure">
        <summary><Plus size={14} /> Add immutable version</summary>
        <form onSubmit={submit}>
          <div className="form-field"><label htmlFor={`version-content-${source.id}`}>Revised source content</label><textarea id={`version-content-${source.id}`} value={content} onChange={(event) => setContent(event.target.value)} rows={6} minLength={20} required /></div>
          <div className="form-field"><label htmlFor={`change-note-${source.id}`}>What changed?</label><input id={`change-note-${source.id}`} value={changeNote} onChange={(event) => setChangeNote(event.target.value)} minLength={3} required aria-describedby={`change-help-${source.id}`} /><span className="field-help" id={`change-help-${source.id}`}>The current version remains immutable.</span></div>
          <button className="primary-button" type="submit" disabled={saving || content === source.content}>{saving ? "Creating…" : "Create next version"}</button>
        </form>
      </details>
    </article>
  );
}

function AskView() {
  const [question, setQuestion] = useState("What do we believe makes AI-generated output valuable?");
  const [result, setResult] = useState<ChatResult | null>(null);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");
  const suggestions = ["What position do we hold most strongly?", "Which lessons are supported by evidence?", "What has changed recently?"];

  async function submit(event: FormEvent) {
    event.preventDefault();
    setAsking(true); setError("");
    try { setResult(await api.chat(question)); }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : "The question failed."); }
    finally { setAsking(false); }
  }

  return (
    <div className="ask-workspace">
      <section className="ask-composer panel-card">
        <div className="ask-intro"><span className="ask-brain"><Brain size={24} /></span><div><h2>Ask across approved intelligence</h2><p>The Brain will abstain when the canon does not contain enough evidence.</p></div></div>
        <form action="/api/v1/chat" method="post" onSubmit={submit}>
          <label className="sr-only" htmlFor="question">Question</label>
          <textarea id="question" name="question" value={question} onChange={(event) => setQuestion(event.target.value)} rows={4} required minLength={3} placeholder="Ask about an approved position, lesson, or decision…" />
          <div className="ask-actions"><span><ShieldCheck size={16} /> Canonical knowledge only</span><button className="primary-button" type="submit" disabled={asking}>{asking ? "Searching…" : "Ask the Brain"}<ArrowRight size={17} /></button></div>
        </form>
        <div className="suggestion-row"><span>Try asking</span>{suggestions.map((suggestion) => <button key={suggestion} onClick={() => setQuestion(suggestion)}>{suggestion}</button>)}</div>
      </section>
      {error && <div className="alert alert--error" role="alert">{error}</div>}
      {result && (
        <section className="answer-card panel-card">
          <header><span className={result.grounded ? "grounded-badge" : "ungrounded-badge"}>{result.grounded ? <ShieldCheck size={15} /> : <CircleDot size={15} />}{result.grounded ? "Grounded answer" : "Not enough approved knowledge"}</span></header>
          <p className="answer-text">{result.answer}</p>
          {result.citations.length > 0 && <div className="citations"><h2>Evidence used</h2>{result.citations.map((citation, index) => <details key={`${citation.knowledge_id}-${index}`}><summary><span>{index + 1}</span>{citation.source_title}</summary><blockquote>{citation.excerpt}</blockquote><code>{citation.knowledge_id}</code></details>)}</div>}
        </section>
      )}
    </div>
  );
}

function PreviewNotice({ children }: { children: ReactNode }) {
  return <div className="preview-notice"><CircleDot size={15} /><span>{children}</span></div>;
}

function StudioPreview({ onCapture }: { onCapture: () => void }) {
  return (
    <div className="future-layout">
      <PreviewNotice>This is an honest interface preview. Guided interview APIs arrive in milestone M3; no session is being recorded yet.</PreviewNotice>
      <section className="studio-preview panel-card">
        <div className="preview-hero-icon"><Mic2 size={28} /></div>
        <span className="section-kicker">Founder interview workflow</span>
        <h2>Capture the thinking that has never been written down.</h2>
        <p>The Studio will guide an expert through a focused conversation, surface useful follow-ups, and send every extracted idea into the same human review boundary.</p>
        <ol className="workflow-steps">
          <li className="active"><span>1</span><div><strong>Define the interview</strong><small>Person, topic, audience, and intended outcome</small></div></li>
          <li><span>2</span><div><strong>Record and follow up</strong><small>Conversation with targeted questions and timestamps</small></div></li>
          <li><span>3</span><div><strong>Review extracted intelligence</strong><small>Theses, stories, lessons, frameworks, and evidence</small></div></li>
        </ol>
        <button className="secondary-button" onClick={onCapture}><FileText size={17} /> Import an interview transcript now</button>
      </section>
    </div>
  );
}

const PACK_INTENTS = [
  { id: "brief", label: "Draft brief", note: "Argument outline with every claim mapped to a source" },
  { id: "article", label: "Point-of-view article", note: "Long-form narrative built from approved positions" },
  { id: "agent", label: "Agent context", note: "Scoped package for Codex, Claude, Hermes or Grok" },
  { id: "questions", label: "Interview questions", note: "Follow-ups grounded in what is already known" },
] as const;

type PackIntentId = (typeof PACK_INTENTS)[number]["id"];

type Pack = { text: string; atoms: number; sources: number; tokens: number };

function buildPack(intent: PackIntentId, audience: string, cited: boolean, atoms: Knowledge[]): Pack {
  const meta = PACK_INTENTS.find((option) => option.id === intent) ?? PACK_INTENTS[0];
  const sourceCount = new Set(atoms.map((item) => item.source_title)).size;
  const lines = [
    `# Context pack — ${meta.label}`,
    `Audience: ${audience.trim() || "not specified"}`,
    `Scope: ${atoms.length} approved ${atoms.length === 1 ? "atom" : "atoms"} from ${sourceCount} ${sourceCount === 1 ? "source" : "sources"}`,
    `Evidence policy: ${cited ? "canonical statement + source excerpt" : "canonical statement only"}`,
    "",
    "## Canonical knowledge",
    "",
  ];
  atoms.forEach((item, index) => {
    lines.push(`[K${index + 1}] ${item.statement}`);
    lines.push(`      type: ${item.type} · source: "${item.source_title}" · v${item.version}`);
    if (cited && item.source_excerpt.trim()) {
      lines.push(`      evidence: "${item.source_excerpt.trim().replace(/\s+/g, " ")}"`);
    }
    lines.push("");
  });
  const text = lines.join("\n");
  return { text, atoms: atoms.length, sources: sourceCount, tokens: Math.ceil(text.length / 4) };
}

function ActivateView({ knowledge, onNavigate, onNotice }: {
  knowledge: Knowledge[];
  onNavigate: (view: View) => void;
  onNotice: (message: string) => void;
}) {
  const [intent, setIntent] = useState<PackIntentId>("brief");
  const [audience, setAudience] = useState("Enterprise technology leaders");
  const [cited, setCited] = useState(true);
  const [query, setQuery] = useState("");
  const [excluded, setExcluded] = useState<string[]>([]);
  const [copied, setCopied] = useState(false);

  const usable = useMemo(() => knowledge.filter((item) => !item.stale), [knowledge]);
  const included = useMemo(() => usable.filter((item) => !excluded.includes(item.id)), [usable, excluded]);
  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return usable;
    return usable.filter((item) =>
      `${item.statement} ${item.source_title} ${item.type}`.toLowerCase().includes(needle));
  }, [usable, query]);
  const pack = useMemo(() => buildPack(intent, audience, cited, included), [intent, audience, cited, included]);
  const heldBack = knowledge.length - usable.length;

  function toggle(id: string) {
    setExcluded((previous) => (previous.includes(id) ? previous.filter((value) => value !== id) : [...previous, id]));
  }

  async function copyPack() {
    try {
      await navigator.clipboard.writeText(pack.text);
      setCopied(true);
      onNotice("Context pack copied to the clipboard.");
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      onNotice("The browser blocked clipboard access — download the pack instead.");
    }
  }

  function downloadPack() {
    const blob = new Blob([pack.text], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `context-pack-${intent}.md`;
    link.click();
    URL.revokeObjectURL(url);
    onNotice("Context pack downloaded as markdown.");
  }

  return (
    <div className="activate-layout">
      <section className="composer-card panel-card">
        <header className="composer-head">
          <span className="section-kicker">Context builder</span>
          <h2>Assemble the right intelligence for the job.</h2>
          <p className="composer-sub">Choose an outcome, then select the approved atoms it may draw on. The pack is assembled from stored records with their citations intact — no text is generated.</p>
        </header>

        {knowledge.length === 0 ? (
          <div className="activate-empty">
            <span className="preview-hero-icon"><Layers3 size={24} /></span>
            <h3>No approved knowledge yet</h3>
            <p>A context pack can only draw on approved atoms. Capture a source, review the proposals it produces, and approve the ones worth keeping — then come back and assemble the pack.</p>
            <div className="hero-actions">
              <button className="primary-button btn--pill" onClick={() => onNavigate("sources")}><Plus size={17} /> Capture your first source</button>
              <button className="secondary-button btn--pill" onClick={() => onNavigate("inbox")}><Inbox size={17} /> Open the review inbox</button>
            </div>
          </div>
        ) : null}

        <div className="intent-grid" role="radiogroup" aria-label="Output intent">
          {PACK_INTENTS.map((option) => (
            <button key={option.id} type="button" role="radio" aria-checked={intent === option.id}
              className={intent === option.id ? "intent-card is-on" : "intent-card"}
              onClick={() => setIntent(option.id)}>
              <strong>{option.label}</strong>
              <small>{option.note}</small>
              <span className="intent-mark" aria-hidden="true">{intent === option.id && <Check size={13} />}</span>
            </button>
          ))}
        </div>

        <div className="composer-fields">
          <div className="form-field">
            <label htmlFor="pack-audience">Who is this for?</label>
            <input id="pack-audience" className="input" value={audience} maxLength={120}
              onChange={(event) => setAudience(event.target.value)} placeholder="e.g. Series A investors" />
          </div>
          <div className="form-field">
            <label>Evidence policy</label>
            <div className="policy-row" role="radiogroup" aria-label="Evidence policy">
              <button type="button" role="radio" aria-checked={cited}
                className={cited ? "policy-chip is-on" : "policy-chip"} onClick={() => setCited(true)}>Canonical + excerpt</button>
              <button type="button" role="radio" aria-checked={!cited}
                className={cited ? "policy-chip" : "policy-chip is-on"} onClick={() => setCited(false)}>Canonical only</button>
            </div>
            <span className="field-help">{cited ? "Every claim carries the exact source excerpt it came from." : "Quotes are dropped — claims keep their source title and version."}</span>
          </div>
        </div>

        <div className="evidence-block">
          <div className="evidence-toolbar">
            <div className="search-field">
              <Search size={17} aria-hidden="true" />
              <input className="input" type="search" value={query} placeholder="Filter approved atoms…"
                aria-label="Filter approved knowledge" onChange={(event) => setQuery(event.target.value)} />
            </div>
            <span className="evidence-count"><strong>{included.length}</strong> of {usable.length} included{heldBack > 0 ? ` · ${heldBack} stale held back` : ""}</span>
          </div>
          <ul className="evidence-list">
            {matches.map((item) => {
              const on = !excluded.includes(item.id);
              return (
                <li key={item.id}>
                  <button type="button" className={on ? "evidence-row" : "evidence-row is-off"} aria-pressed={on} onClick={() => toggle(item.id)}>
                    <span className="evidence-box" aria-hidden="true">{on && <Check size={12} />}</span>
                    <span className="evidence-copy">
                      <strong>{item.statement}</strong>
                      <small><span className="type-chip">{item.type}</span> v{item.version} · {item.source_title}</small>
                    </span>
                  </button>
                </li>
              );
            })}
            {matches.length === 0 ? <li className="evidence-empty">No approved atom matches that filter.</li> : null}
          </ul>
        </div>
      </section>

      <aside className="activate-rail">
        <div className="pack-panel panel-card">
          <div className="context-pack-header">
            <span><Layers3 size={19} /> Context pack</span>
            <span className="pack-chip">{PACK_INTENTS.find((option) => option.id === intent)?.label}</span>
          </div>
          <div className="pack-stats">
            <div><strong>{pack.atoms}</strong><span>atoms</span></div>
            <div><strong>{pack.sources}</strong><span>sources</span></div>
            <div><strong>≈{pack.tokens.toLocaleString()}</strong><span>tokens</span></div>
          </div>
          <pre className="context-lines">{pack.text}</pre>
          <div className="pack-actions">
            <button className="primary-button" onClick={copyPack}><Copy size={16} /> {copied ? "Copied" : "Copy pack"}</button>
            <button className="secondary-button" onClick={downloadPack}><Download size={16} /> Markdown</button>
          </div>
          <p className="pack-note"><ShieldCheck size={15} /> Assembled from {included.length} approved {included.length === 1 ? "atom" : "atoms"} with citation links intact. Text generation and publishing are not wired yet.</p>
        </div>
      </aside>
    </div>
  );
}

function AnalyticsPreview({ overview, knowledge, integrity }: { overview: Overview | null; knowledge: Knowledge[]; integrity: Integrity | null }) {
  const attentionCount = (integrity?.stale_count ?? 0) + (integrity?.conflict_count ?? 0);
  const revisionTotal = knowledge.reduce((total, item) => total + (item.revision_count ?? 0), 0);
  const revisionDepth = knowledge.length ? revisionTotal / knowledge.length : 0;
  const canon = overview?.canonical ?? 0;

  const byType = Object.entries(
    knowledge.reduce<Record<string, number>>((counts, item) => {
      const key = item.type || "unclassified";
      counts[key] = (counts[key] ?? 0) + 1;
      return counts;
    }, {}),
  ).map(([type, atoms]) => ({ type, atoms }));

  const stages = [
    { label: "Sources captured", value: overview?.sources ?? 0, tone: "", note: "Immutable originals" },
    { label: "Waiting for review", value: overview?.pending_reviews ?? 0, tone: "bar--attention", note: "Needs judgement" },
    { label: "Canonical atoms", value: canon, tone: "bar--accent", note: "Approved and reusable" },
    { label: "Integrity signals", value: attentionCount, tone: "bar--attention", note: "Stale or conflicting" },
  ];
  const peak = Math.max(...stages.map((stage) => stage.value), 1);
  const extracted = canon + (overview?.pending_reviews ?? 0);
  const stageRows = useSortedRows(stages, "value");
  const typeRows = useSortedRows(byType, "atoms");

  return (
    <div className="analytics-layout">
      <section className="metric-strip" aria-label="Intelligence analytics summary">
        <Metric label="Canonical atoms" value={canon} detail="Approved and reusable" icon={<CheckCircle2 />} tone="green" share={extracted ? canon / extracted : 0} shareNote={`${extracted ? Math.round((canon / extracted) * 100) : 0}% of ${extracted} extracted claims`} />
        <Metric label="Waiting for review" value={overview?.pending_reviews ?? 0} detail="Proposals needing judgement" icon={<Clock3 />} tone="amber" share={extracted ? (overview?.pending_reviews ?? 0) / extracted : 0} shareNote={`${extracted ? Math.round(((overview?.pending_reviews ?? 0) / extracted) * 100) : 0}% still unreviewed`} />
        <Metric label="Revisions per atom" value={Number(revisionDepth.toFixed(1))} detail={`${revisionTotal} revisions recorded`} icon={<Activity />} tone="blue" />
        <Metric label="Integrity signals" value={attentionCount} detail={attentionCount ? "Stale or conflicting" : "All checks pass"} icon={<ShieldCheck />} tone="violet" />
      </section>

      <section className="analytics-grid">
        <article className="panel-card coverage-card">
          <div className="card-heading"><div><span className="section-kicker">Source to canon</span><h2>Knowledge coverage</h2><p className="section-sub">How much captured material has passed human review, by stage.</p></div></div>
          <table className="table">
            <thead><tr>
              <SortHeader label="Stage" sortKey="label" sort={stageRows.sort} onSort={stageRows.toggle} />
              <SortHeader label="Count" sortKey="value" sort={stageRows.sort} onSort={stageRows.toggle} numeric />
              <th scope="col" className="share-col">Relative</th>
            </tr></thead>
            <tbody>
              {stageRows.sorted.map((stage) => {
                const pct = Math.round((stage.value / peak) * 100);
                return (
                  <tr key={stage.label}>
                    <td className="strong">{stage.label}<span className="stage-note">{stage.note}</span></td>
                    <td className="num">{stage.value.toLocaleString()}</td>
                    <td className="share-col">
                      <span className="share-cell">
                        <span className={`bar ${stage.tone}`} role="img" aria-label={`${stage.value} of ${peak} — largest stage`}><span style={{ width: `${pct}%` }} /></span>
                        <span className="share-value">{pct}%</span>
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </article>

        <article className="panel-card">
          <div className="card-heading"><div><span className="section-kicker">Approved knowledge</span><h2>Canon by type</h2><p className="section-sub">Counted from the live canon, not projected.</p></div></div>
          {byType.length ? (
            <table className="table">
              <thead><tr>
                <SortHeader label="Type" sortKey="type" sort={typeRows.sort} onSort={typeRows.toggle} />
                <SortHeader label="Atoms" sortKey="atoms" sort={typeRows.sort} onSort={typeRows.toggle} numeric />
                <th scope="col" className="share-col">Share of canon</th>
              </tr></thead>
              <tbody>
                {typeRows.sorted.map((row) => {
                  const pct = canon ? Math.round((row.atoms / canon) * 100) : 0;
                  return (
                    <tr key={row.type}>
                      <td className="strong">{row.type}</td>
                      <td className="num">{row.atoms.toLocaleString()}</td>
                      <td className="share-col">
                        <span className="share-cell">
                          <span className="bar" role="img" aria-label={`${row.atoms} of ${canon} canonical atoms`}><span style={{ width: `${pct}%` }} /></span>
                          <span className="share-value">{pct}%</span>
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : <p className="muted-line">No approved knowledge yet. Approve a proposal and the breakdown appears here.</p>}
        </article>
      </section>

      <p className="preview-footnote">Reuse and outcome attribution are not measured yet: the Brain records provenance and revisions, not downstream usage. Every figure on this page is counted from stored records — none are estimated.</p>
    </div>
  );
}

function AuditView({ overview, integrity }: { overview: Overview; integrity: Integrity | null }) {
  const [period, setPeriod] = useState<Period>("all");
  const events = useMemo(() => filterByPeriod(overview.recent_activity, period), [overview.recent_activity, period]);
  return (
    <div className="audit-layout">
      <section className="integrity-card panel-card">
        <div className="card-heading"><div><span className="section-kicker">Integrity monitor</span><h2>Current signals</h2></div><ShieldCheck size={21} /></div>
        <div className="integrity-metrics"><div><strong>{integrity?.stale_count ?? 0}</strong><span>stale sources</span></div><div><strong>{integrity?.conflict_count ?? 0}</strong><span>possible conflicts</span></div></div>
        {integrity?.issues.length ? <ul className="issue-list">{integrity.issues.map((issue, index) => <li key={`${issue.knowledge_id}-${index}`}><TriangleAlert size={16} /><span><strong>{issue.kind.replaceAll("_", " ")}</strong>{issue.detail}</span></li>)}</ul> : <div className="all-clear"><CheckCircle2 size={18} className="verified-icon" /><span><strong>All clear</strong>No stale or conflicting knowledge detected.</span></div>}
      </section>
      <section className="timeline-card panel-card">
        <div className="card-heading">
          <div>
            <span className="section-kicker">Domain events</span>
            <h2>Recent activity</h2>
            <p className="section-sub">{events.length} of {overview.recent_activity.length} recorded events</p>
          </div>
          <PeriodFilter period={period} onChange={setPeriod} />
        </div>
        <ol className="audit-timeline">
          {events.map((event) => <li key={event.id}><span className="timeline-dot" /><div><strong>{event.action.replaceAll(".", " ")}</strong><p>{event.detail}</p></div><time dateTime={event.created_at}>{timeAgo(event.created_at)}</time></li>)}
          {overview.recent_activity.length === 0 && <li className="timeline-empty"><Inbox size={16} aria-hidden="true" /><div><strong>No events yet</strong><p>New workspace events will appear here.</p></div></li>}
          {overview.recent_activity.length > 0 && events.length === 0 && <li className="timeline-empty"><Clock3 size={16} aria-hidden="true" /><div><strong>Nothing in this window</strong><p>Choose All to see older activity.</p></div></li>}
        </ol>
      </section>
    </div>
  );
}

function CaptureDialog({ onClose, onCreated, onError }: { onClose: () => void; onCreated: () => Promise<void>; onError: (value: string) => void }) {
  const [saving, setSaving] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    return () => { if (dialog.open && typeof dialog.close === "function") dialog.close(); };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setSaving(true);
    try {
      await api.createSource({
        title: String(data.get("title")),
        kind: String(data.get("kind")),
        sensitivity: String(data.get("sensitivity")),
        content: String(data.get("content")),
      });
      await onCreated();
    } catch (requestError) {
      onError(requestError instanceof Error ? requestError.message : "Source import failed.");
      setSaving(false);
    }
  }

  return (
    <dialog ref={dialogRef} className="capture-dialog" aria-labelledby="capture-title" onCancel={(event) => { event.preventDefault(); onClose(); }}>
      <header><div><span className="eyebrow">New source</span><h1 id="capture-title">Capture original material</h1><p>Original content is preserved before extraction begins.</p></div><button className="ghost-icon" type="button" onClick={onClose} aria-label="Close capture form"><X size={20} /></button></header>
      <form action="/api/v1/sources" method="post" onSubmit={submit}>
        <div className="form-field"><label htmlFor="source-title">Title</label><input id="source-title" name="title" required minLength={3} maxLength={240} autoFocus placeholder="e.g. Founder interview — September" /></div>
        <div className="form-row">
          <div className="form-field"><label htmlFor="source-kind">Source type</label><select id="source-kind" name="kind" defaultValue="note"><option value="note">Note</option><option value="research">Research</option><option value="interview">Interview</option><option value="decision">Decision</option></select></div>
          <div className="form-field"><label htmlFor="source-sensitivity">Visibility</label><select id="source-sensitivity" name="sensitivity" defaultValue="private"><option value="private">Private</option><option value="internal">Internal</option><option value="public">Public</option></select></div>
        </div>
        <div className="form-field"><label htmlFor="source-content">Source content</label><textarea id="source-content" name="content" rows={10} required minLength={20} maxLength={100000} placeholder="Paste a project lesson, interview transcript, research note, or decision…" aria-describedby="content-help" /><span id="content-help" className="field-help">The original stays unchanged. Extracted ideas enter your review inbox.</span></div>
        <footer><button className="secondary-button" type="button" onClick={onClose}>Cancel</button><button className="primary-button" type="submit" disabled={saving}><Sparkles size={17} />{saving ? "Extracting…" : "Capture and extract"}</button></footer>
      </form>
    </dialog>
  );
}
