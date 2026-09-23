import { FormEvent, ReactNode, useEffect, useMemo, useState } from "react";
import {
  Activity,
  Archive,
  ArrowRight,
  BookOpen,
  Brain,
  Check,
  CircleDot,
  Download,
  FileText,
  Home,
  Inbox,
  Menu,
  MessageSquareText,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { api, ChatResult, Knowledge, Overview, Proposal, Source } from "./api";

type View = "home" | "sources" | "inbox" | "brain" | "ask";

const navItems: Array<{ id: View; label: string; icon: typeof Home }> = [
  { id: "home", label: "Home", icon: Home },
  { id: "inbox", label: "Review inbox", icon: Inbox },
  { id: "brain", label: "Brain", icon: Brain },
  { id: "sources", label: "Sources", icon: Archive },
  { id: "ask", label: "Ask", icon: MessageSquareText },
];

const titleMap: Record<View, { eyebrow: string; title: string; description: string }> = {
  home: {
    eyebrow: "Personal intelligence workspace",
    title: "Make your thinking compound.",
    description: "Capture source material, review what the system finds, and reuse only the knowledge you have approved.",
  },
  inbox: {
    eyebrow: "Human judgment",
    title: "Review inbox",
    description: "Nothing becomes canonical until you inspect the exact wording and its source.",
  },
  brain: {
    eyebrow: "Approved knowledge",
    title: "Your Brain",
    description: "Search the current positions, decisions, lessons, and evidence you have accepted.",
  },
  sources: {
    eyebrow: "Original material",
    title: "Sources",
    description: "Import interviews, research, notes, and decisions without confusing raw material with truth.",
  },
  ask: {
    eyebrow: "Grounded answers",
    title: "Ask your Brain",
    description: "Answers use canonical knowledge and show the original evidence behind every result.",
  },
};

function EmptyState({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <section className="empty-state">
      <div className="empty-icon" aria-hidden="true">{icon}</div>
      <h2>{title}</h2>
      <p>{children}</p>
    </section>
  );
}

function MetricCard({ label, value, note, accent }: { label: string; value: number; note: string; accent?: boolean }) {
  return (
    <article className={`metric-card ${accent ? "metric-card--accent" : ""}`}>
      <span className="metric-label">{label}</span>
      <strong>{value}</strong>
      <p>{note}</p>
    </article>
  );
}

function timeAgo(value: string) {
  const seconds = Math.max(1, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export default function App() {
  const [view, setView] = useState<View>("home");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [knowledge, setKnowledge] = useState<Knowledge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [showCapture, setShowCapture] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  async function refresh() {
    try {
      setError("");
      const [overviewData, sourceData, proposalData, knowledgeData] = await Promise.all([
        api.overview(), api.sources(), api.proposals(), api.knowledge(),
      ]);
      setOverview(overviewData);
      setSources(sourceData);
      setProposals(proposalData);
      setKnowledge(knowledgeData);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not load the workspace.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let active = true;

    Promise.all([api.overview(), api.sources(), api.proposals(), api.knowledge()])
      .then(([overviewData, sourceData, proposalData, knowledgeData]) => {
        if (!active) return;
        setOverview(overviewData);
        setSources(sourceData);
        setProposals(proposalData);
        setKnowledge(knowledgeData);
      })
      .catch((requestError: unknown) => {
        if (!active) return;
        setError(requestError instanceof Error ? requestError.message : "Could not load the workspace.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  function navigate(next: View) {
    setView(next);
    setMenuOpen(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
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

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <aside className={`sidebar ${menuOpen ? "sidebar--open" : ""}`}>
        <div className="brand">
          <div className="brand-mark" aria-hidden="true"><Brain size={20} strokeWidth={2.2} /></div>
          <div><strong>Open Brain</strong><span>Local intelligence</span></div>
        </div>

        <nav aria-label="Primary navigation">
          <ul>
            {navItems.map((item) => {
              const Icon = item.icon;
              return (
                <li key={item.id}>
                  <button className={view === item.id ? "active" : ""} onClick={() => navigate(item.id)} aria-current={view === item.id ? "page" : undefined}>
                    <Icon size={18} aria-hidden="true" />
                    <span>{item.label}</span>
                    {item.id === "inbox" && proposals.length > 0 && <span className="nav-count">{proposals.length}</span>}
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="sidebar-footer">
          <div className="privacy-status"><ShieldCheck size={16} /><span><strong>Local mode</strong>Hosted AI off</span></div>
          <button className="export-button" onClick={handleExport}><Download size={16} /> Export Brain</button>
        </div>
      </aside>

      {menuOpen && <button className="scrim" aria-label="Close navigation" onClick={() => setMenuOpen(false)} />}

      <div className="main-column">
        <header className="topbar">
          <button className="menu-button" onClick={() => setMenuOpen(true)} aria-label="Open navigation"><Menu size={20} /></button>
          <span className="workspace-name"><CircleDot size={15} /> Personal workspace</span>
          <button className="capture-button" onClick={() => setShowCapture(true)}><Plus size={17} /> Capture source</button>
        </header>

        <main id="main-content">
          <header className="page-heading">
            <span className="eyebrow">{current.eyebrow}</span>
            <h1>{current.title}</h1>
            <p>{current.description}</p>
          </header>

          {error && <div className="alert alert--error" role="alert"><X size={18} />{error}<button onClick={() => setError("")}>Dismiss</button></div>}
          {notice && <div className="alert alert--success" role="status"><Check size={18} />{notice}<button onClick={() => setNotice("")}>Dismiss</button></div>}

          {loading ? <LoadingState /> : (
            <>
              {view === "home" && overview && <HomeView overview={overview} proposals={proposals} knowledge={knowledge} onNavigate={navigate} />}
              {view === "sources" && <SourcesView sources={sources} onCapture={() => setShowCapture(true)} />}
              {view === "inbox" && <InboxView proposals={proposals} onChanged={refresh} onNotice={setNotice} onError={setError} />}
              {view === "brain" && <BrainView initial={knowledge} />}
              {view === "ask" && <AskView />}
            </>
          )}
        </main>
      </div>

      {showCapture && <CaptureDialog onClose={() => setShowCapture(false)} onCreated={async () => { setShowCapture(false); setNotice("Source captured and proposals added to your inbox."); await refresh(); navigate("inbox"); }} onError={setError} />}
    </div>
  );
}

function LoadingState() {
  return <div className="loading-state" role="status"><span className="spinner" /> Loading your Brain…</div>;
}

function HomeView({ overview, proposals, knowledge, onNavigate }: { overview: Overview; proposals: Proposal[]; knowledge: Knowledge[]; onNavigate: (view: View) => void }) {
  return (
    <div className="dashboard-grid">
      <section className="metrics" aria-label="Workspace summary">
        <MetricCard label="Canonical knowledge" value={overview.canonical} note="Approved and reusable" accent />
        <MetricCard label="Pending review" value={overview.pending_reviews} note="Waiting for judgment" />
        <MetricCard label="Sources" value={overview.sources} note="Original material" />
      </section>

      <section className="focus-card">
        <div className="section-heading"><div><span className="eyebrow">Next best action</span><h2>Strengthen the Brain</h2></div><Sparkles size={22} aria-hidden="true" /></div>
        {proposals.length ? (
          <div className="focus-content">
            <div><span className="type-chip">{proposals[0].type}</span><h3>{proposals[0].statement}</h3><p>Review this extraction against <strong>{proposals[0].source_title}</strong>.</p></div>
            <button onClick={() => onNavigate("inbox")}>Review proposal <ArrowRight size={17} /></button>
          </div>
        ) : (
          <div className="focus-content"><div><h3>Your review queue is clear.</h3><p>Capture another interview, decision, or lesson when you are ready.</p></div><button onClick={() => onNavigate("sources")}>View sources <ArrowRight size={17} /></button></div>
        )}
      </section>

      <section className="recent-knowledge panel">
        <div className="section-heading"><div><span className="eyebrow">Reusable intelligence</span><h2>Recently approved</h2></div><button className="text-button" onClick={() => onNavigate("brain")}>View all</button></div>
        <div className="knowledge-list compact">
          {knowledge.slice(0, 4).map((item) => <KnowledgeRow key={item.id} item={item} />)}
        </div>
      </section>

      <section className="activity-panel panel">
        <div className="section-heading"><div><span className="eyebrow">Audit trail</span><h2>Recent activity</h2></div><Activity size={20} aria-hidden="true" /></div>
        <ol className="activity-list">
          {overview.recent_activity.map((event) => <li key={event.id}><span className="activity-dot" /><div><strong>{event.action.replaceAll(".", " ")}</strong><p>{event.detail}</p></div><time dateTime={event.created_at}>{timeAgo(event.created_at)}</time></li>)}
        </ol>
      </section>
    </div>
  );
}

function SourcesView({ sources, onCapture }: { sources: Source[]; onCapture: () => void }) {
  return (
    <section className="panel source-panel">
      <div className="toolbar"><div><strong>{sources.length} sources</strong><span>Each original stays separate from interpreted knowledge.</span></div><button className="primary-button" onClick={onCapture}><Plus size={17} /> Add source</button></div>
      {sources.length === 0 ? <EmptyState icon={<Archive />} title="No sources yet">Capture a project note, interview, decision, or piece of research.</EmptyState> : (
        <div className="source-grid">
          {sources.map((source) => <article className="source-card" key={source.id}><div className="source-icon"><FileText size={19} /></div><div className="source-main"><div className="source-meta"><span>{source.kind}</span><span>·</span><span>{source.sensitivity}</span></div><h2>{source.title}</h2><p>{source.content}</p><footer><span>{source.proposal_count} proposals</span><time dateTime={source.created_at}>{timeAgo(source.created_at)}</time></footer></div></article>)}
        </div>
      )}
    </section>
  );
}

function InboxView({ proposals, onChanged, onNotice, onError }: { proposals: Proposal[]; onChanged: () => Promise<void>; onNotice: (value: string) => void; onError: (value: string) => void }) {
  if (proposals.length === 0) return <EmptyState icon={<Check />} title="Inbox clear">Every current proposal has been reviewed. New extractions will appear here.</EmptyState>;
  return <div className="review-stack">{proposals.map((proposal) => <ReviewCard key={proposal.id} proposal={proposal} onChanged={onChanged} onNotice={onNotice} onError={onError} />)}</div>;
}

function ReviewCard({ proposal, onChanged, onNotice, onError }: { proposal: Proposal; onChanged: () => Promise<void>; onNotice: (value: string) => void; onError: (value: string) => void }) {
  const [statement, setStatement] = useState(proposal.statement);
  const [rationale, setRationale] = useState(proposal.rationale);
  const [saving, setSaving] = useState(false);

  async function approve() {
    setSaving(true);
    try { await api.approveProposal(proposal.id, statement, rationale); onNotice("Knowledge approved and added to your Brain."); await onChanged(); }
    catch (error) { onError(error instanceof Error ? error.message : "Approval failed."); }
    finally { setSaving(false); }
  }

  async function reject() {
    setSaving(true);
    try { await api.rejectProposal(proposal.id, "Rejected during human review"); onNotice("Proposal rejected. The original source was preserved."); await onChanged(); }
    catch (error) { onError(error instanceof Error ? error.message : "Rejection failed."); }
    finally { setSaving(false); }
  }

  return (
    <article className="review-card">
      <header><div><span className="type-chip">{proposal.type}</span><span className="status-chip">Proposed</span></div><span className="source-link"><BookOpen size={15} /> {proposal.source_title}</span></header>
      <div className="review-columns">
        <section>
          <label htmlFor={`statement-${proposal.id}`}>Canonical wording</label>
          <textarea id={`statement-${proposal.id}`} name="statement" value={statement} onChange={(event) => setStatement(event.target.value)} rows={4} minLength={3} required />
          <label htmlFor={`rationale-${proposal.id}`}>Reason and qualification</label>
          <textarea id={`rationale-${proposal.id}`} name="rationale" value={rationale} onChange={(event) => setRationale(event.target.value)} rows={3} />
        </section>
        <aside><span className="evidence-label">Exact source evidence</span><blockquote>{proposal.source_excerpt}</blockquote><p>Imported {timeAgo(proposal.created_at)}</p></aside>
      </div>
      <footer><button className="secondary-button danger" onClick={reject} disabled={saving}><X size={17} /> Reject</button><button className="primary-button" onClick={approve} disabled={saving || statement.trim().length < 3}><Check size={17} /> {saving ? "Saving…" : "Approve exact wording"}</button></footer>
    </article>
  );
}

function KnowledgeRow({ item }: { item: Knowledge }) {
  return <article className="knowledge-row"><div className="knowledge-mark"><ShieldCheck size={17} /></div><div><div className="source-meta"><span>{item.type}</span><span>·</span><span>v{item.version}</span><span>·</span><span>{item.source_title}</span></div><h3>{item.statement}</h3><p>{item.rationale}</p></div></article>;
}

function BrainView({ initial }: { initial: Knowledge[] }) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    const needle = query.toLowerCase().trim();
    if (!needle) return initial;
    return initial.filter((item) => `${item.statement} ${item.rationale} ${item.type} ${item.source_title}`.toLowerCase().includes(needle));
  }, [initial, query]);
  return (
    <section className="panel brain-panel">
      <search><form action="/" method="get" onSubmit={(event) => event.preventDefault()}><label htmlFor="brain-search">Search approved knowledge</label><div className="search-field"><Search size={18} aria-hidden="true" /><input id="brain-search" name="q" type="search" placeholder="Search positions, decisions, lessons…" value={query} onChange={(event) => setQuery(event.target.value)} /></div></form></search>
      <div className="toolbar compact-toolbar"><strong>{filtered.length} canonical items</strong><span>Showing approved revisions only</span></div>
      <div className="knowledge-list">{filtered.map((item) => <KnowledgeRow key={item.id} item={item} />)}{filtered.length === 0 && <EmptyState icon={<Search />} title="No approved matches">Try broader language, or review pending proposals first.</EmptyState>}</div>
    </section>
  );
}

function AskView() {
  const [question, setQuestion] = useState("What do we believe makes AI-generated output valuable?");
  const [result, setResult] = useState<ChatResult | null>(null);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setAsking(true); setError("");
    try { setResult(await api.chat(question)); }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : "The question failed."); }
    finally { setAsking(false); }
  }

  return (
    <div className="ask-layout">
      <section className="ask-card panel">
        <form action="/api/v1/chat" method="post" onSubmit={submit}>
          <label htmlFor="question">Question</label>
          <textarea id="question" name="question" value={question} onChange={(event) => setQuestion(event.target.value)} rows={4} required minLength={3} placeholder="Ask about an approved position, project lesson, or decision…" />
          <div className="ask-actions"><span><ShieldCheck size={16} /> Canonical knowledge only</span><button className="primary-button" type="submit" disabled={asking}>{asking ? "Searching…" : "Ask the Brain"}<ArrowRight size={17} /></button></div>
        </form>
      </section>
      {error && <div className="alert alert--error" role="alert">{error}</div>}
      {result && <section className="answer-card panel"><header><span className={result.grounded ? "grounded-badge" : "ungrounded-badge"}>{result.grounded ? <ShieldCheck size={15} /> : <CircleDot size={15} />}{result.grounded ? "Grounded answer" : "Not enough approved knowledge"}</span></header><p className="answer-text">{result.answer}</p>{result.citations.length > 0 && <div className="citations"><h2>Evidence</h2>{result.citations.map((citation, index) => <details key={`${citation.knowledge_id}-${index}`}><summary><span>{index + 1}</span>{citation.source_title}</summary><blockquote>{citation.excerpt}</blockquote><code>{citation.knowledge_id}</code></details>)}</div>}</section>}
    </div>
  );
}

function CaptureDialog({ onClose, onCreated, onError }: { onClose: () => void; onCreated: () => Promise<void>; onError: (value: string) => void }) {
  const [saving, setSaving] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setSaving(true);
    try {
      await api.createSource({ title: String(data.get("title")), kind: String(data.get("kind")), sensitivity: String(data.get("sensitivity")), content: String(data.get("content")) });
      await onCreated();
    } catch (requestError) { onError(requestError instanceof Error ? requestError.message : "Source import failed."); setSaving(false); }
  }
  return (
    <div className="dialog-backdrop" role="presentation">
      <section className="capture-dialog" role="dialog" aria-modal="true" aria-labelledby="capture-title">
        <header><div><span className="eyebrow">New source</span><h1 id="capture-title">Capture original material</h1></div><button className="icon-button" type="button" onClick={onClose} aria-label="Close capture form"><X size={20} /></button></header>
        <form action="/api/v1/sources" method="post" onSubmit={submit}>
          <div className="form-field"><label htmlFor="source-title">Title</label><input id="source-title" name="title" required minLength={3} maxLength={240} autoFocus placeholder="e.g. Founder interview — September" /></div>
          <div className="form-row"><div className="form-field"><label htmlFor="source-kind">Source type</label><select id="source-kind" name="kind" defaultValue="note"><option value="note">Note</option><option value="research">Research</option><option value="interview">Interview</option><option value="decision">Decision</option></select></div><div className="form-field"><label htmlFor="source-sensitivity">Visibility</label><select id="source-sensitivity" name="sensitivity" defaultValue="private"><option value="private">Private</option><option value="internal">Internal</option><option value="public">Public</option></select></div></div>
          <div className="form-field"><label htmlFor="source-content">Source content</label><textarea id="source-content" name="content" rows={10} required minLength={20} maxLength={100000} placeholder="Paste a project lesson, interview transcript, research note, or decision…" aria-describedby="content-help" /><span id="content-help" className="field-help">The original stays unchanged. Extracted ideas enter your review inbox.</span></div>
          <footer><button className="secondary-button" type="button" onClick={onClose}>Cancel</button><button className="primary-button" type="submit" disabled={saving}><Sparkles size={17} />{saving ? "Extracting…" : "Capture and extract"}</button></footer>
        </form>
      </section>
    </div>
  );
}
