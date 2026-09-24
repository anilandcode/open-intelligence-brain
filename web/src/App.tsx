import { FormEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, Archive, ArrowRight, BarChart3, BookOpen, Bot, Brain, Check, CheckCircle2,
  ChevronRight, CircleDot, Clock3, Download, FileText, Fingerprint, History, Home,
  Inbox, Layers3, Menu, MessageSquareText, Mic2, Plus, Search,
  ShieldCheck, Sparkles, TriangleAlert, X,
} from "lucide-react";
import {
  api, ChatResult, Integrity, Knowledge, KnowledgeRevision, Overview, Proposal, Source,
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
  { id: "activate", label: "Activate", icon: Sparkles, future: true },
];

const systemNav: NavItem[] = [
  { id: "sources", label: "Sources", icon: Archive },
  { id: "analytics", label: "Analytics", icon: BarChart3, future: true },
  { id: "audit", label: "Audit", icon: Activity },
];

const titleMap: Record<View, { eyebrow: string; title: string; description: string }> = {
  overview: {
    eyebrow: "Intelligence workspace",
    title: "Good thinking should compound.",
    description: "Turn raw expertise into approved, reusable company intelligence—without losing the evidence behind it.",
  },
  inbox: {
    eyebrow: "Judgement queue",
    title: "Review inbox",
    description: "Inspect every proposal beside its original evidence before it becomes part of the Brain.",
  },
  brain: {
    eyebrow: "Canonical knowledge",
    title: "Your Brain",
    description: "Search the positions, lessons, decisions, and language your organisation has explicitly approved.",
  },
  studio: {
    eyebrow: "Intelligence creation · M3 preview",
    title: "Intelligence Studio",
    description: "A guided workspace for turning expert conversations into theses, stories, frameworks, and evidence.",
  },
  activate: {
    eyebrow: "Context into work · M3 preview",
    title: "Activate intelligence",
    description: "Build a trusted context pack and transform it into briefs, articles, sales narratives, and agent context.",
  },
  analytics: {
    eyebrow: "Outcome learning · Preview",
    title: "Intelligence analytics",
    description: "Understand which ideas get reused, where evidence is weak, and what knowledge contributes to outcomes.",
  },
  sources: {
    eyebrow: "Immutable originals",
    title: "Source library",
    description: "Keep interviews, research, notes, and decisions separate from the interpretations built from them.",
  },
  audit: {
    eyebrow: "Trust and provenance",
    title: "Audit trail",
    description: "See why the system believes what it believes, what changed, and which items need attention.",
  },
  ask: {
    eyebrow: "Grounded answers",
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
                {item.future && <span className="nav-preview">Soon</span>}
              </button>
            </li>
          );
        })}
      </ul>
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
      setError(requestError instanceof Error ? requestError.message : "Could not load the workspace.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
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
        setError(requestError instanceof Error ? requestError.message : "Could not load the workspace.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    function handleCommandSearch(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setView("brain");
        setMenuOpen(false);
        window.requestAnimationFrame(() => window.requestAnimationFrame(() => document.getElementById("brain-search")?.focus()));
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

  function openBrainSearch() {
    navigate("brain");
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => document.getElementById("brain-search")?.focus()));
  }

  async function handleExport() {
    try {
      const response = await fetch(api.exportUrl, { headers: { "X-Brain-Token": api.exportToken } });
      if (!response.ok) throw new Error("Export failed");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `brain-export-${new Date().toISOString().slice(0, 10)}.json`;
      link.click();
      URL.revokeObjectURL(url);
      setNotice("Portable Brain export downloaded.");
    } catch {
      setError("The workspace could not be exported.");
    }
  }

  const current = titleMap[view];
  const attentionCount = (integrity?.stale_count ?? 0) + (integrity?.conflict_count ?? 0);

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <aside className={`sidebar ${menuOpen ? "sidebar--open" : ""}`} aria-label="Workspace navigation">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true"><Brain size={21} strokeWidth={2.1} /></div>
          <div><strong>Open Brain</strong><span>Intelligence OS</span></div>
        </div>
        <nav aria-label="Primary navigation">
          <AppNav label="Workspace" items={primaryNav} view={view} proposalCount={proposals.length} onNavigate={navigate} />
          <AppNav label="System" items={systemNav} view={view} proposalCount={proposals.length} onNavigate={navigate} />
        </nav>
        <div className="sidebar-footer">
          <div className="local-card">
            <span className="status-light" aria-hidden="true" />
            <div><strong>Local mode</strong><span>Hosted AI is off</span></div>
            <ShieldCheck size={16} aria-hidden="true" />
          </div>
          <button className="sidebar-action" onClick={handleExport}><Download size={16} /> Export workspace</button>
          <span className="version-label">Open Brain · v0.3 interface</span>
        </div>
      </aside>

      {menuOpen && <button className="scrim" aria-label="Close navigation" onClick={() => setMenuOpen(false)} />}

      <div className="main-column">
        <header className="topbar">
          <div className="topbar-start">
            <button className="menu-button" onClick={() => setMenuOpen(true)} aria-label="Open navigation"><Menu size={20} /></button>
            <div className="workspace-switcher" aria-label="Current workspace: Personal Brain">
              <span className="workspace-avatar">P</span>
              <span><small>Workspace</small><strong>Personal Brain</strong></span>
            </div>
          </div>
          <div className="topbar-actions">
            <button className="command-button" onClick={openBrainSearch}><Search size={16} /><span>Search intelligence</span><kbd>⌘ K</kbd></button>
            <button className="capture-button" onClick={() => setShowCapture(true)}><Plus size={17} /> Capture source</button>
          </div>
        </header>

        <main id="main-content">
          <header className="page-heading">
            <div><span className="eyebrow">{current.eyebrow}</span><h1>{current.title}</h1><p>{current.description}</p></div>
            {view === "brain" && <button className="secondary-button" onClick={() => navigate("ask")}><MessageSquareText size={17} /> Ask the Brain</button>}
            {view === "sources" && <button className="primary-button" onClick={() => setShowCapture(true)}><Plus size={17} /> Add source</button>}
            {view === "audit" && <button className="secondary-button" onClick={handleExport}><Download size={17} /> Export audit data</button>}
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
              {view === "activate" && <ActivatePreview knowledgeCount={knowledge.length} />}
              {view === "analytics" && <AnalyticsPreview overview={overview} knowledge={knowledge} attentionCount={attentionCount} />}
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
    </div>
  );
}

function LoadingState() {
  return (
    <div className="loading-board" role="status" aria-label="Loading workspace">
      <div className="skeleton skeleton--hero" />
      <div className="skeleton-row"><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /></div>
      <span>Loading your Brain…</span>
    </div>
  );
}

function OverviewView({
  overview, proposals, knowledge, integrity, onNavigate,
}: {
  overview: Overview; proposals: Proposal[]; knowledge: Knowledge[]; integrity: Integrity | null; onNavigate: (view: View) => void;
}) {
  const attentionCount = (integrity?.stale_count ?? 0) + (integrity?.conflict_count ?? 0);
  return (
    <div className="overview-layout">
      <section className="hero-card">
        <div className="hero-copy">
          <span className="signal-pill"><span /> {attentionCount ? `${attentionCount} integrity signals` : "Knowledge system healthy"}</span>
          <h2>From raw expertise to<br /><em>trusted intelligence.</em></h2>
          <p>Capture what you know, approve what matters, and give every human or agent the same current source of truth.</p>
          <div className="hero-actions">
            <button className="light-button" onClick={() => onNavigate(proposals.length ? "inbox" : "sources")}>{proposals.length ? "Review next proposal" : "Capture your first source"}<ArrowRight size={17} /></button>
            <button className="dark-ghost-button" onClick={() => onNavigate("ask")}><MessageSquareText size={17} /> Ask the Brain</button>
          </div>
        </div>
        <div className="hero-orbit" aria-hidden="true">
          <div className="orbit-ring orbit-ring--outer" /><div className="orbit-ring orbit-ring--inner" />
          <div className="orbit-core"><Brain size={31} /></div>
          <span className="orbit-node node-a" /><span className="orbit-node node-b" /><span className="orbit-node node-c" />
        </div>
      </section>

      <section className="metric-strip" aria-label="Workspace summary">
        <Metric label="Approved knowledge" value={overview.canonical} detail="Ready to reuse" icon={<CheckCircle2 />} tone="green" />
        <Metric label="Waiting for review" value={overview.pending_reviews} detail="Needs judgement" icon={<Clock3 />} tone="amber" />
        <Metric label="Source material" value={overview.sources} detail="Immutable originals" icon={<Archive />} tone="blue" />
        <Metric label="Integrity signals" value={attentionCount} detail={attentionCount ? "Needs attention" : "No issues found"} icon={<ShieldCheck />} tone="violet" />
      </section>

      <section className="pipeline-card panel-card">
        <div className="card-heading">
          <div><span className="section-kicker">Knowledge pipeline</span><h2>How the Brain gets smarter</h2></div>
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
          <div className="card-heading"><div><span className="section-kicker">Needs judgement</span><h2>Review queue</h2></div><button className="text-button" onClick={() => onNavigate("inbox")}>Open inbox <ArrowRight size={15} /></button></div>
          {proposals.length ? (
            <div className="queue-list">
              {proposals.slice(0, 3).map((proposal, index) => (
                <button key={proposal.id} onClick={() => onNavigate("inbox")}>
                  <span className="queue-index">0{index + 1}</span>
                  <span><small>{proposal.type} · {proposal.source_title}</small><strong>{proposal.statement}</strong></span>
                  <ChevronRight size={17} aria-hidden="true" />
                </button>
              ))}
            </div>
          ) : <EmptyState icon={<Check />} title="Inbox clear">New extractions will appear here when you capture another source.</EmptyState>}
        </div>

        <div className="panel-card recent-preview">
          <div className="card-heading"><div><span className="section-kicker">Current canon</span><h2>Recently approved</h2></div><button className="text-button" onClick={() => onNavigate("brain")}>View Brain <ArrowRight size={15} /></button></div>
          <div className="compact-knowledge-list">
            {knowledge.slice(0, 4).map((item) => (
              <article key={item.id}>
                <span className="knowledge-type-icon"><BookOpen size={15} /></span>
                <div><small>{item.type} · v{item.version}</small><h3>{item.statement}</h3></div>
                {item.stale || item.conflict_ids.length ? <TriangleAlert size={16} className="attention-icon" /> : <CheckCircle2 size={16} className="verified-icon" />}
              </article>
            ))}
            {knowledge.length === 0 && <EmptyState icon={<BookOpen />} title="No canonical knowledge">Approve a proposal to begin building the Brain.</EmptyState>}
          </div>
        </div>
      </section>
    </div>
  );
}

function Metric({ label, value, detail, icon, tone }: { label: string; value: number; detail: string; icon: ReactNode; tone: string }) {
  return (
    <article className="metric-item">
      <span className={`metric-icon metric-icon--${tone}`} aria-hidden="true">{icon}</span>
      <div><small>{label}</small><strong>{value.toLocaleString()}</strong><span>{detail}</span></div>
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
  const filtered = useMemo(() => {
    const needle = query.toLowerCase().trim();
    return initial.filter((item) => {
      const matchesText = !needle || `${item.statement} ${item.rationale} ${item.type} ${item.source_title}`.toLowerCase().includes(needle);
      const matchesFilter = filter === "all" || item.stale || item.conflict_ids.length > 0;
      return matchesText && matchesFilter;
    });
  }, [initial, query, filter]);

  return (
    <section className="brain-workspace panel-card">
      <div className="brain-toolbar">
        <search><form action="/" method="get" onSubmit={(event) => event.preventDefault()}><label className="sr-only" htmlFor="brain-search">Search approved knowledge</label><div className="search-field"><Search size={18} aria-hidden="true" /><input id="brain-search" name="q" type="search" placeholder="Search claims, decisions, stories, language…" value={query} onChange={(event) => setQuery(event.target.value)} /></div></form></search>
        <div className="filter-tabs" aria-label="Knowledge filters">
          <button className={filter === "all" ? "active" : ""} onClick={() => setFilter("all")}>All knowledge <span>{initial.length}</span></button>
          <button className={filter === "attention" ? "active" : ""} onClick={() => setFilter("attention")}>Needs attention <span>{initial.filter((item) => item.stale || item.conflict_ids.length).length}</span></button>
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

function SourcesView({ sources, onChanged, onNotice, onError }: { sources: Source[]; onChanged: () => Promise<void>; onNotice: (value: string) => void; onError: (value: string) => void }) {
  return (
    <section className="source-workspace">
      <div className="library-summary panel-card">
        <div><span className="metric-icon metric-icon--blue"><Archive size={20} /></span><span><small>Source library</small><strong>{sources.length} immutable originals</strong></span></div>
        <p>Every change creates a new hashed version. Approved knowledge keeps pointing to the exact evidence it came from.</p>
      </div>
      {sources.length === 0 ? <section className="panel-card"><EmptyState icon={<Archive />} title="No sources yet">Capture a project note, interview, decision, or piece of research.</EmptyState></section> : (
        <div className="source-grid">{sources.map((source) => <SourceCard key={source.id} source={source} onChanged={onChanged} onNotice={onNotice} onError={onError} />)}</div>
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

function ActivatePreview({ knowledgeCount }: { knowledgeCount: number }) {
  return (
    <div className="future-layout">
      <PreviewNotice>This preview shows the planned context-building flow. Generation and publishing are intentionally inactive until the evidence contract is implemented.</PreviewNotice>
      <section className="activation-preview panel-card">
        <div className="activation-config">
          <span className="section-kicker">Context builder</span><h2>Assemble the right intelligence for the job.</h2>
          <div className="preview-field"><span>Goal</span><strong>Executive point-of-view article</strong></div>
          <div className="preview-field"><span>Audience</span><strong>Enterprise technology leaders</strong></div>
          <div className="preview-field"><span>Knowledge scope</span><strong>{knowledgeCount} approved atoms available</strong></div>
          <div className="preview-field"><span>Evidence policy</span><strong>Canonical + cited only</strong></div>
        </div>
        <div className="context-pack-preview">
          <div className="context-pack-header"><span><Layers3 size={19} /> Context pack preview</span><span className="locked-chip">M3</span></div>
          <div className="context-stat"><strong>{knowledgeCount}</strong><span>approved atoms</span></div>
          <div className="context-lines"><span /><span /><span /><span /></div>
          <div className="context-output"><FileText size={18} /><div><strong>Draft brief</strong><small>Claims mapped back to source evidence</small></div></div>
          <div className="context-output"><Bot size={18} /><div><strong>Agent context</strong><small>Scoped package for Codex, Claude, Hermes, or Grok-style bots</small></div></div>
        </div>
      </section>
    </div>
  );
}

function AnalyticsPreview({ overview, knowledge, attentionCount }: { overview: Overview | null; knowledge: Knowledge[]; attentionCount: number }) {
  const reused = Math.min(knowledge.length, Math.max(0, Math.floor(knowledge.length * 0.65)));
  return (
    <div className="future-layout">
      <PreviewNotice>Workspace health is live. Reuse and revenue attribution remain preview metrics until outcome tracking is implemented.</PreviewNotice>
      <section className="analytics-grid">
        <article className="panel-card"><span className="section-kicker">Canon health</span><strong className="big-number">{overview?.canonical ?? 0}</strong><p>approved knowledge atoms</p><div className="mini-progress"><span style={{ width: `${attentionCount ? 72 : 100}%` }} /></div><small>{attentionCount ? `${attentionCount} integrity signals to review` : "All current checks pass"}</small></article>
        <article className="panel-card preview-metric"><span className="locked-chip">Preview</span><span className="section-kicker">Knowledge reuse</span><strong className="big-number">{reused}</strong><p>atoms used in downstream work</p><div className="bar-placeholder"><span /><span /><span /><span /><span /><span /></div></article>
        <article className="panel-card coverage-card"><span className="section-kicker">Source to canon</span><h2>Knowledge coverage</h2><dl><div><dt>Sources</dt><dd>{overview?.sources ?? 0}</dd></div><div><dt>Pending</dt><dd>{overview?.pending_reviews ?? 0}</dd></div><div><dt>Canonical</dt><dd>{overview?.canonical ?? 0}</dd></div><div><dt>Attention</dt><dd>{attentionCount}</dd></div></dl></article>
      </section>
    </div>
  );
}

function AuditView({ overview, integrity }: { overview: Overview; integrity: Integrity | null }) {
  return (
    <div className="audit-layout">
      <section className="integrity-card panel-card">
        <div className="card-heading"><div><span className="section-kicker">Integrity monitor</span><h2>Current signals</h2></div><ShieldCheck size={21} /></div>
        <div className="integrity-metrics"><div><strong>{integrity?.stale_count ?? 0}</strong><span>stale sources</span></div><div><strong>{integrity?.conflict_count ?? 0}</strong><span>possible conflicts</span></div></div>
        {integrity?.issues.length ? <ul className="issue-list">{integrity.issues.map((issue, index) => <li key={`${issue.knowledge_id}-${index}`}><TriangleAlert size={16} /><span><strong>{issue.kind.replaceAll("_", " ")}</strong>{issue.detail}</span></li>)}</ul> : <div className="all-clear"><CheckCircle2 size={18} /><span><strong>All clear</strong>No stale or conflicting knowledge detected.</span></div>}
      </section>
      <section className="timeline-card panel-card">
        <div className="card-heading"><div><span className="section-kicker">Domain events</span><h2>Recent activity</h2></div><Activity size={20} /></div>
        <ol className="audit-timeline">
          {overview.recent_activity.map((event) => <li key={event.id}><span className="timeline-dot" /><div><strong>{event.action.replaceAll(".", " ")}</strong><p>{event.detail}</p></div><time dateTime={event.created_at}>{timeAgo(event.created_at)}</time></li>)}
          {overview.recent_activity.length === 0 && <li className="timeline-empty">New workspace events will appear here.</li>}
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
