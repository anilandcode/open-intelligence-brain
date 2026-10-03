import { EvidenceCitation } from "./Evidence";
import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Activity, Archive, ArrowDown, ArrowLeft, ArrowRight, ArrowUpDown, ArrowUp, BookOpen, Boxes, Brain, Check, CheckCircle2, ChevronRight, CircleDot, Clock3, Copy, Download, FileText, Fingerprint, History, Inbox, Layers3, Maximize2, MessageSquareText, Mic2, Network, Plus, Search, ShieldCheck, Sparkles, TriangleAlert, X, ZoomIn, ZoomOut } from "lucide-react";
import type { ChatResult, Draft, DraftDetail, Graph, Integrity, InterviewSession, InterviewSessionDetail, Knowledge, KnowledgeRevision, McpConnection, Overview, Proposal, Source, SourceVersion } from "./api";
import { useBrainClient } from "./client";
import { Detail } from "./Detail";
import type { View } from "./routes";
import { Button } from "@/components/arc/button/button";
import { MetricCard } from "@/components/arc/metric-card/metric-card";

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

function timeAgo(value: string) {
  const seconds = Math.max(1, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function EmptyState({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <section className="empty-state">
      <div className="empty-icon" aria-hidden="true">{icon}</div>
      <h2>{title}</h2>
      <p>{children}</p>
    </section>
  );
}

export function LoadingState() {
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

export function OverviewView({
  overview, proposals, knowledge, integrity, onNavigate,
}: {
  overview: Overview; proposals: Proposal[]; knowledge: Knowledge[]; integrity: Integrity | null; onNavigate: (view: View) => void;
}) {
  const attentionCount = (integrity?.stale_count ?? 0) + (integrity?.conflict_count ?? 0);
  return (
    <div className="overview-layout">
      <section className="workspace-brief" aria-label="Workspace guide">
        <div className="workspace-brief-copy">
          <span className="section-kicker">Sources → review → knowledge</span>
          <h2>{overview.sources ? "Keep your knowledge moving." : "Build your first memory."}</h2>
          <p>Capture an original source, review the proposed meaning, then reuse approved knowledge with its evidence.</p>
          <div className="hero-actions">
            <Button onClick={() => onNavigate(proposals.length ? "inbox" : "import")}>{proposals.length ? "Review next proposal" : "Capture your first source"}<ArrowRight size={14}/></Button>
            <Button variant="secondary" onClick={() => onNavigate("ask")}><MessageSquareText size={14}/>Ask the Brain</Button>
          </div>
        </div>
        <div className="workspace-steps">
          <button onClick={() => onNavigate("sources")}><span>01</span><div><strong>Capture original material</strong><small>{overview.sources.toLocaleString()} sources · immutable versions</small></div><ChevronRight size={14}/></button>
          <button onClick={() => onNavigate("inbox")}><span>02</span><div><strong>Review the interpretation</strong><small>{overview.pending_reviews.toLocaleString()} waiting · human approval required</small></div><ChevronRight size={14}/></button>
          <button onClick={() => onNavigate("brain")}><span>03</span><div><strong>Recall approved knowledge</strong><small>{overview.canonical.toLocaleString()} approved · citations preserved</small></div><ChevronRight size={14}/></button>
          <div className="workspace-engine" title={overview.engine.detail}><span className="status-dot" aria-hidden="true"/>Engine: {overview.engine.name}{overview.engine.degraded ? " · not learning from new sources" : overview.engine.available ? " · available" : " · unavailable"}</div>
        </div>
      </section>
      <section className="metric-strip" aria-label="Workspace summary">
        <MetricCard label="Approved knowledge" value={overview.canonical} context="Ready to reuse" />
        <MetricCard label="Waiting for review" value={overview.pending_reviews} context="Human approval required" />
        <MetricCard label="Source material" value={overview.sources} context="Originals preserved" />
        <MetricCard label="Integrity signals" value={attentionCount} context={integrity ? attentionCount ? "Needs attention" : "No issues found" : "Status unavailable"} />
      </section>
      <section className="work-grid">
        <div className="panel-card queue-preview">
          <div className="card-heading"><div><span className="section-kicker">Needs judgement</span><h2>Review queue</h2><p className="section-sub">Nothing enters the canon until a person approves the exact wording.</p></div><Button variant="ghost" size="sm" onClick={() => onNavigate("inbox")}>Open inbox <ArrowRight size={15} /></Button></div>
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
                        <Button variant="ghost" size="sm" onClick={() => onNavigate("inbox")} aria-label={`Review proposal: ${proposal.statement}`}>Review<ArrowRight size={14} /></Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <EmptyState icon={<Check />} title="Inbox clear">New extractions will appear here when you capture another source.</EmptyState>}
        </div>

        <div className="panel-card recent-preview">
          <div className="card-heading"><div><span className="section-kicker">Current canon</span><h2>Recently approved</h2><p className="section-sub">The positions your team and agents can safely reuse today.</p></div><Button variant="ghost" size="sm" onClick={() => onNavigate("brain")}>View Brain <ArrowRight size={15} /></Button></div>
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

export function InboxView({ proposals, onChanged, onNotice, onError }: { proposals: Proposal[]; onChanged: () => Promise<void>; onNotice: (value: string) => void; onError: (value: string) => void }) {
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
  const client = useBrainClient();
  const [statement, setStatement] = useState(proposal.statement);
  const [rationale, setRationale] = useState(proposal.rationale);
  const [busy, setBusy] = useState(false);
  const [rejectMode, setRejectMode] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const tags = (() => { try { const parsed = JSON.parse(proposal.tags || "[]"); return Array.isArray(parsed) ? (parsed as string[]) : []; } catch { return []; } })();

  async function approve(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    try {
      await client.approveProposal(proposal.id, statement, rationale);
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
      await client.rejectProposal(proposal.id, rejectReason.trim());
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
              {proposal.summary ? <div><dt>Summary</dt><dd>{proposal.summary}</dd></div> : null}
              {tags.length ? <div><dt>Tags</dt><dd>{tags.join(", ")}</dd></div> : null}
            </dl>
          </aside>
        </div>
        {proposal.critic_notes && (() => {
          try {
            const notes = JSON.parse(proposal.critic_notes);
            if (!Array.isArray(notes) || notes.length === 0) return null;
            return (
              <div className="critic-panel">
                <div className="critic-heading"><span><TriangleAlert size={15} /> Critic assessment</span><span className="critic-badge">{notes.length} note{notes.length !== 1 ? "s" : ""}</span></div>
                <ul>
                  {notes.map((note: {severity: string; category: string; message: string}, i: number) => (
                    <li key={i} className={`critic-note critic-note--${note.severity}`}>
                      <span className="critic-icon">{note.severity === "strong" ? "🔴" : note.severity === "warning" ? "⚠" : "ℹ"}</span>
                      <span>{note.message}</span>
                    </li>
                  ))}
                </ul>
              </div>
            );
          } catch { return null; }
        })()}
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

export function BrainView({ recordId, onSelect, initial, onChanged, onNotice, onError }: { recordId?: string; onSelect: (id: string | null) => void; initial: Knowledge[]; onChanged: () => Promise<void>; onNotice: (value: string) => void; onError: (value: string) => void }) {
  const [query, setQuery] = useState("");
  const selectedId = recordId;
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
      <div className="knowledge-list knowledge-table">
        <div className="knowledge-table-head"><span>APPROVED KNOWLEDGE</span><span>TYPE</span><span>SOURCE</span><span>REVISIONS</span></div>
        {filtered.map((item) => <button className="knowledge-table-row" key={item.id} onClick={() => onSelect(item.id)}><strong>{item.statement}</strong><span>{item.type}</span><span>{item.source_title}</span><span>v{item.version} · {item.revision_count}</span><ChevronRight size={16}/></button>)}
        {filtered.length === 0 && <EmptyState icon={<Search />} title="No approved matches">Try a broader phrase or change the current filter.</EmptyState>}
      </div>
      {selectedId && !initial.some(item => item.id === selectedId) && <Detail title="Knowledge unavailable" onClose={() => onSelect(null)}><p>This record is not available in the current workspace. It may have been removed or you may not have access.</p></Detail>}
      {selectedId && initial.find(item => item.id === selectedId) && <Detail title="Evidence and history" onClose={() => onSelect(null)}><KnowledgeCard item={initial.find(item => item.id === selectedId)!} onChanged={onChanged} onNotice={onNotice} onError={onError}/></Detail>}
    </section>
  );
}

function KnowledgeCard({ item, onChanged, onNotice, onError }: { item: Knowledge; onChanged: () => Promise<void>; onNotice: (value: string) => void; onError: (value: string) => void }) {
  const client = useBrainClient();
  const [revisions, setRevisions] = useState<KnowledgeRevision[]>([]);
  const [statement, setStatement] = useState(item.statement);
  const [rationale, setRationale] = useState(item.rationale);
  const [changeNote, setChangeNote] = useState("");
  const [saving, setSaving] = useState(false);

  async function loadHistory() {
    if (revisions.length) return;
    try { setRevisions(await client.knowledgeRevisions(item.id)); }
    catch (requestError) { onError(requestError instanceof Error ? requestError.message : "Could not load revision history."); }
  }

  async function supersede(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    try {
      await client.supersedeKnowledge(item.id, statement, rationale, changeNote);
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
        <section className="knowledge-evidence" aria-label="Exact source evidence"><h3>Exact source evidence</h3><blockquote>{item.source_excerpt}</blockquote><a href={`#/${window.location.hash.startsWith("#/demo/") ? "demo" : "console"}/sources?record=${encodeURIComponent(item.source_id)}`}>Inspect original source and versions</a></section>
        <details className="history-disclosure" onToggle={(event) => { if (event.currentTarget.open) void loadHistory(); }}>
          <summary><History size={15} aria-hidden="true" /> {item.revision_count} {item.revision_count === 1 ? "revision" : "revisions"} · inspect or supersede</summary>
          <div className="history-layout">
            <ol className="revision-list">
              {revisions.map((revision) => <li key={revision.id}><div><strong>Revision {revision.revision}</strong><time dateTime={revision.approved_at}>{timeAgo(revision.approved_at)}</time></div><p>{revision.statement}</p><small>{revision.change_note}</small><blockquote>{revision.source_excerpt}</blockquote><small>Source version: {revision.source_version_id ?? "Unknown"}</small></li>)}
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

export function SourcesView({ recordId, onSelect, sources, onChanged, onNotice, onError }: { recordId?: string; onSelect: (id: string | null) => void; sources: Source[]; onChanged: () => Promise<void>; onNotice: (value: string) => void; onError: (value: string) => void }) {
  const [kind, setKind] = useState<string>("all");
  const [query, setQuery] = useState("");
  const [sensitivity, setSensitivity] = useState("all");
  const selectedId = recordId;
  const [sort, setSort] = useState<SourceSort>("recent");

  const kinds = useMemo(() => {
    const counts = new Map<string, number>();
    sources.forEach((source) => counts.set(source.kind, (counts.get(source.kind) ?? 0) + 1));
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [sources]);

  const visible = useMemo(() => {
    const rows = sources.filter(source => (kind === "all" || source.kind === kind) && (sensitivity === "all" || source.sensitivity === sensitivity) && `${source.title} ${source.content}`.toLowerCase().includes(query.toLowerCase()));
    return [...rows].sort(SOURCE_SORTS[sort].compare);
  }, [sources, kind, sensitivity, query, sort]);

  return (
    <section className="source-workspace">
      <div className="library-summary panel-card">
        <div><span className="metric-icon metric-icon--blue"><Archive size={20} /></span><span><small>Source library</small><strong>{sources.length} immutable originals</strong></span></div>
        <p>Every change creates a new hashed version. Approved knowledge keeps pointing to the exact evidence it came from.</p>
      </div>
      {sources.length === 0 ? <section className="panel-card"><EmptyState icon={<Archive />} title="No sources yet">Capture a project note, interview, decision, or piece of research.</EmptyState></section> : (
        <>
          <div className="source-toolbar">
            <label className="search-field"><Search size={17}/><input type="search" aria-label="Search sources" placeholder="Search sources" value={query} onChange={event => setQuery(event.target.value)}/></label>
            <select aria-label="Filter source visibility" value={sensitivity} onChange={event => setSensitivity(event.target.value)}><option value="all">All visibility</option><option value="private">Private</option><option value="internal">Internal</option><option value="public">Public</option></select>
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
          <div className="source-grid source-table">
            <div className="source-table-head"><span>SOURCE</span><span>TYPE</span><span>VISIBILITY</span><span>VERSION</span></div>
            {visible.map((source) => <button className="source-table-row" key={source.id} onClick={() => onSelect(source.id)}><strong>{source.title}</strong><span>{source.kind}</span><span>{source.sensitivity}</span><span>v{source.current_version}</span><ChevronRight size={16}/></button>)}
            {visible.length === 0 && <section className="panel-card"><EmptyState icon={<Archive />} title="No sources of this kind">Pick another kind, or reset the filter to all kinds.</EmptyState></section>}
          </div>
          {selectedId && !sources.some(source => source.id === selectedId) && <Detail title="Source unavailable" onClose={() => onSelect(null)}><p>This source is not available in the current workspace. It may have been removed or you may not have access.</p></Detail>}
          {selectedId && sources.find(source => source.id === selectedId) && <Detail title="Source and versions" onClose={() => onSelect(null)}><SourceCard source={sources.find(source => source.id === selectedId)!} onChanged={onChanged} onNotice={onNotice} onError={onError}/></Detail>}
        </>
      )}
    </section>
  );
}

function SourceCard({ source, onChanged, onNotice, onError }: { source: Source; onChanged: () => Promise<void>; onNotice: (value: string) => void; onError: (value: string) => void }) {
  const client = useBrainClient();
  const [content, setContent] = useState(source.content);
  const [changeNote, setChangeNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [versions, setVersions] = useState<SourceVersion[]>([]);
  const [versionsLoading, setVersionsLoading] = useState(false);

  async function loadVersions() {
    if (versions.length || versionsLoading) return;
    setVersionsLoading(true);
    try { setVersions(await client.sourceVersions(source.id)); }
    catch (requestError) { onError(requestError instanceof Error ? requestError.message : "Could not load source versions."); }
    finally { setVersionsLoading(false); }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    try {
      await client.addSourceVersion(source.id, content, changeNote);
      onNotice("Immutable source version created and new proposals added for review.");
      setChangeNote("");
      setVersions([]);
      await onChanged();
    } catch (requestError) {
      onError(requestError instanceof Error ? requestError.message : "Could not add source version.");
    } finally { setSaving(false); }
  }

  return (
    <article className="source-card">
      <header><span className="source-icon"><FileText size={18} /></span><div className="source-meta"><span>{source.kind}</span><span>·</span><span>{source.sensitivity}</span></div><span className="version-chip">v{source.current_version}</span></header>
      <h2>{source.title}</h2><p>{source.content}</p>
      <div className="source-integrity"><span><Fingerprint size={14} /><code>{source.content_hash.slice(0, 12)}</code></span><span>Content hash</span></div>
      <footer><span>{source.proposal_count} proposals</span><time dateTime={source.created_at}>{timeAgo(source.created_at)}</time></footer>
      <details className="version-disclosure" onToggle={event => { if (event.currentTarget.open) void loadVersions(); }}><summary><History size={14}/> Version history</summary>{versionsLoading ? <p>Loading versions…</p> : <ol className="source-version-list">{versions.map(version => <li key={version.id}><strong>Version {version.version}</strong><span>{version.change_note || "Original"}</span><details><summary>Inspect original</summary><p>{version.content}</p><code>{version.content_hash}</code></details></li>)}</ol>}</details>
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

export function AskView() {
  const client = useBrainClient();
  const [question, setQuestion] = useState("What do we believe makes AI-generated output valuable?");
  const [result, setResult] = useState<ChatResult | null>(null);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");
  const suggestions = ["What position do we hold most strongly?", "Which lessons are supported by evidence?", "What has changed recently?"];

  async function submit(event: FormEvent) {
    event.preventDefault();
    setAsking(true); setError("");
    try { setResult(await client.chat(question)); }
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
          {result.citations.length > 0 && <div className="citations"><h2>Evidence used</h2>{result.citations.map((citation, index) => <EvidenceCitation key={`${citation.knowledge_id}-${index}`} index={index+1} title={citation.source_title} excerpt={citation.excerpt} knowledgeId={citation.knowledge_id} href={`#/${window.location.hash.startsWith("#/demo/") ? "demo" : "console"}/sources?record=${encodeURIComponent(citation.source_id)}`}/>)}</div>}
        </section>
      )}
    </div>
  );
}

export function StudioView({
  interviews, drafts, knowledge, onChanged, onNotice, onError,
}: {
  interviews: InterviewSession[]; drafts: Draft[]; knowledge: Knowledge[];
  onChanged: () => Promise<void>; onNotice: (v: string) => void; onError: (v: string) => void;
}) {
  const [tab, setTab] = useState<"interviews" | "drafts">("interviews");
  const [showNewInterview, setShowNewInterview] = useState(false);
  const [showAssemble, setShowAssemble] = useState(false);
  const [selectedInterview, setSelectedInterview] = useState<string | null>(null);
  const [selectedDraft, setSelectedDraft] = useState<string | null>(null);

  if (selectedInterview) {
    return <InterviewDetailView sessionId={selectedInterview} onBack={() => setSelectedInterview(null)} onChanged={onChanged} onNotice={onNotice} onError={onError} />;
  }
  if (selectedDraft) {
    return <DraftDetailView draftId={selectedDraft} onBack={() => setSelectedDraft(null)} onNotice={onNotice} onError={onError} />;
  }

  return (
    <div className="studio-layout">
      <div className="studio-tabs" role="tablist">
        <button role="tab" aria-selected={tab === "interviews"} className={tab === "interviews" ? "active" : ""} onClick={() => setTab("interviews")}>
          <Mic2 size={16} /> Interviews <span>{interviews.length}</span>
        </button>
        <button role="tab" aria-selected={tab === "drafts"} className={tab === "drafts" ? "active" : ""} onClick={() => setTab("drafts")}>
          <FileText size={16} /> Drafts <span>{drafts.length}</span>
        </button>
      </div>

      {tab === "interviews" && (
        <section className="panel-card">
          <div className="card-heading">
            <div><span className="section-kicker">Guided interviews</span><h2>Capture expert knowledge</h2><p className="section-sub">Walk someone through a structured conversation. Responses become source material for the review queue.</p></div>
            <button className="primary-button btn--pill" onClick={() => setShowNewInterview(true)}><Plus size={17} /> New interview</button>
          </div>
          {interviews.length === 0 ? (
            <EmptyState icon={<Mic2 />} title="No interviews yet">Create an interview to capture expert knowledge through a guided conversation.</EmptyState>
          ) : (
            <div className="studio-grid">
              {interviews.map((s) => (
                <article key={s.id} className="panel-card studio-card" role="button" tabIndex={0} onKeyDown={e=>{if(e.key === "Enter" || e.key === " "){e.preventDefault();setSelectedInterview(s.id);}}} onClick={() => setSelectedInterview(s.id)}>
                  <header><span className={`status-chip status-chip--${s.status}`}>{s.status}</span><span>{s.question_count} questions</span></header>
                  <h3>{s.title}</h3>
                  {s.person && <p className="studio-meta">{s.person}{s.topic && ` · ${s.topic}`}</p>}
                  <footer>
                    <span>{s.response_count} responses</span>
                    {s.extracted_count > 0 && <span>{s.extracted_count} extracted</span>}
                    <time>{timeAgo(s.created_at)}</time>
                  </footer>
                </article>
              ))}
            </div>
          )}
        </section>
      )}

      {tab === "drafts" && (
        <section className="panel-card">
          <div className="card-heading">
            <div><span className="section-kicker">Draft builder</span><h2>Assemble intelligence into output</h2><p className="section-sub">Build articles, briefs, and agent context from approved knowledge atoms.</p></div>
            <button className="primary-button btn--pill" onClick={() => setShowAssemble(true)}><Sparkles size={17} /> Assemble draft</button>
          </div>
          {drafts.length === 0 ? (
            <EmptyState icon={<FileText />} title="No drafts yet">Assemble a draft from approved knowledge to create articles, briefs, or agent context.</EmptyState>
          ) : (
            <div className="studio-grid">
              {drafts.map((d) => (
                <article key={d.id} className="panel-card studio-card" role="button" tabIndex={0} onKeyDown={e=>{if(e.key === "Enter" || e.key === " "){e.preventDefault();setSelectedDraft(d.id);}}} onClick={() => setSelectedDraft(d.id)}>
                  <header><span className="type-chip">{d.intent}</span><span>{d.section_count} sections</span></header>
                  <h3>{d.title}</h3>
                  {d.audience && <p className="studio-meta">For: {d.audience}</p>}
                  <footer>
                    <span>{d.citation_count} citations</span>
                    <time>{timeAgo(d.updated_at)}</time>
                  </footer>
                </article>
              ))}
            </div>
          )}
        </section>
      )}

      {showNewInterview && <NewInterviewDialog onClose={() => setShowNewInterview(false)} onCreated={async () => { setShowNewInterview(false); await onChanged(); }} onError={onError} />}
      {showAssemble && <AssembleDraftDialog knowledge={knowledge} onClose={() => setShowAssemble(false)} onCreated={async () => { setShowAssemble(false); await onChanged(); }} onError={onError} />}
    </div>
  );
}

function NewInterviewDialog({ onClose, onCreated, onError }: { onClose: () => void; onCreated: () => Promise<void>; onError: (v: string) => void }) {
  const client = useBrainClient();
  const [saving, setSaving] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = dialogRef.current; if (!d) return;
    if (typeof d.showModal === "function") d.showModal(); else d.setAttribute("open", "");
    return () => { if (d.open && typeof d.close === "function") d.close(); };
  }, []);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); setSaving(true);
    const data = new FormData(e.currentTarget);
    try {
      await client.createInterview({
        title: String(data.get("title")),
        topic: String(data.get("topic") || ""),
        person: String(data.get("person") || ""),
        audience: String(data.get("audience") || ""),
      });
      await onCreated();
    } catch (err) { onError(err instanceof Error ? err.message : "Failed to create interview"); setSaving(false); }
  }

  return (
    <dialog ref={dialogRef} className="capture-dialog" onCancel={(e) => { e.preventDefault(); onClose(); }}>
      <header><div><span className="eyebrow">New interview</span><h1>Start a guided conversation</h1></div><button className="ghost-icon" aria-label="Close dialog" onClick={onClose}><X size={20} /></button></header>
      <form onSubmit={submit}>
        <div className="form-field"><label htmlFor="int-title">Title</label><input id="int-title" name="title" required minLength={3} maxLength={240} autoFocus placeholder="e.g. Founder interview — product vision" /></div>
        <div className="form-field"><label htmlFor="int-topic">Topic</label><input id="int-topic" name="topic" maxLength={2000} placeholder="What area to explore" /></div>
        <div className="form-row">
          <div className="form-field"><label htmlFor="int-person">Person</label><input id="int-person" name="person" maxLength={160} placeholder="Who is being interviewed" /></div>
          <div className="form-field"><label htmlFor="int-audience">Audience</label><input id="int-audience" name="audience" maxLength={160} placeholder="Who will read the output" /></div>
        </div>
        <footer><button className="secondary-button" type="button" onClick={onClose}>Cancel</button><button className="primary-button" type="submit" disabled={saving}>{saving ? "Creating…" : "Create interview"}</button></footer>
      </form>
    </dialog>
  );
}

function InterviewDetailView({ sessionId, onBack, onChanged, onNotice, onError }: { sessionId: string; onBack: () => void; onChanged: () => Promise<void>; onNotice: (v: string) => void; onError: (v: string) => void }) {
  const client = useBrainClient();
  const [session, setSession] = useState<InterviewSessionDetail | null>(null);
  const [newQuestion, setNewQuestion] = useState("");
  const [responding, setResponding] = useState<string | null>(null);
  const [responseText, setResponseText] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setSession(await client.interview(sessionId)); }
    catch (err) { onError(err instanceof Error ? err.message : "Failed to load interview"); }
  }, [client, sessionId, onError]);
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); }, [load]);

  async function addQ() {
    if (!newQuestion.trim() || !session) return;
    setBusy(true);
    try {
      await client.addQuestion(session.id, newQuestion.trim());
      setNewQuestion("");
      await load();
    } catch (err) { onError(err instanceof Error ? err.message : "Failed to add question"); }
    finally { setBusy(false); }
  }

  async function submitR() {
    if (!responseText.trim() || !responding || !session) return;
    setBusy(true);
    try {
      await client.submitResponse(session.id, responding, responseText.trim());
      setResponding(null); setResponseText("");
      await load();
    } catch (err) { onError(err instanceof Error ? err.message : "Failed to submit response"); }
    finally { setBusy(false); }
  }

  async function complete() {
    if (!session) return;
    setBusy(true);
    try {
      await client.completeInterview(session.id);
      onNotice("Interview completed. Proposals added to review queue.");
      await onChanged();
      onBack();
    } catch (err) { onError(err instanceof Error ? err.message : "Failed to complete interview"); }
    finally { setBusy(false); }
  }

  if (!session) return <div className="panel-card"><EmptyState icon={<Clock3 />} title="Loading…">Fetching interview details.</EmptyState></div>;

  return (
    <div className="studio-detail">
      <button className="text-button" onClick={onBack}><ArrowRight size={15} style={{ transform: "rotate(180deg)" }} /> Back to interviews</button>
      <section className="panel-card">
        <div className="card-heading">
          <div><span className={`status-chip status-chip--${session.status}`}>{session.status}</span><h2>{session.title}</h2>{session.person && <p className="studio-meta">{session.person}{session.topic && ` · ${session.topic}`}</p>}</div>
        </div>
        <div className="interview-questions">
          {session.questions.map((q) => (
            <div key={q.id} className="interview-q">
              <div className="interview-q-label"><strong>Q{q.ordinal}:</strong> {q.question_text}</div>
              {q.response_text ? (
                <div className="interview-a"><strong>A:</strong> {q.response_text}{q.extracted && <span className="type-chip" style={{ marginLeft: 8 }}>extracted</span>}</div>
              ) : (
                <div className="interview-a interview-a--empty">
                  {responding === q.id ? (
                    <div className="respond-form">
                      <textarea value={responseText} onChange={(e) => setResponseText(e.target.value)} rows={3} placeholder="Type the response…" autoFocus />
                      <div><button className="primary-button" onClick={submitR} disabled={busy || !responseText.trim()}>Save response</button><button className="secondary-button" onClick={() => { setResponding(null); setResponseText(""); }}>Cancel</button></div>
                    </div>
                  ) : (
                    <button className="secondary-button" onClick={() => setResponding(q.id)} disabled={session.status === "completed"}>Respond</button>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
        {session.status !== "completed" && (
          <div className="interview-add">
            <input value={newQuestion} onChange={(e) => setNewQuestion(e.target.value)} placeholder="Add a follow-up question…" onKeyDown={(e) => { if (e.key === "Enter") void addQ(); }} />
            <button className="secondary-button" onClick={addQ} disabled={busy || !newQuestion.trim()}><Plus size={15} /> Add</button>
          </div>
        )}
        {session.status !== "completed" && session.questions.some((q) => q.response_text.trim()) && (
          <div className="interview-complete">
            <button className="primary-button" onClick={complete} disabled={busy}><Check size={17} /> {busy ? "Completing…" : "Complete & extract proposals"}</button>
            <p>All responses will become source material. Proposals enter the normal review queue.</p>
          </div>
        )}
      </section>
    </div>
  );
}

function AssembleDraftDialog({ knowledge, onClose, onCreated, onError }: { knowledge: Knowledge[]; onClose: () => void; onCreated: () => Promise<void>; onError: (v: string) => void }) {
  const client = useBrainClient();
  const [selected, setSelected] = useState<string[]>(knowledge.filter((k) => !k.stale).map((k) => k.id));
  const [title, setTitle] = useState("");
  const [intent, setIntent] = useState("brief");
  const [audience, setAudience] = useState("");
  const [busy, setBusy] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = dialogRef.current; if (!d) return;
    if (typeof d.showModal === "function") d.showModal(); else d.setAttribute("open", "");
    return () => { if (d.open && typeof d.close === "function") d.close(); };
  }, []);

  function toggle(id: string) { setSelected((p) => p.includes(id) ? p.filter((x) => x !== id) : [...p, id]); }

  async function submit() {
    if (!title.trim() || selected.length === 0) return;
    setBusy(true);
    try {
      await client.assembleDraft({ title: title.trim(), intent, audience, knowledge_ids: selected, include_excerpts: true });
      await onCreated();
    } catch (err) { onError(err instanceof Error ? err.message : "Failed to assemble draft"); setBusy(false); }
  }

  const usable = knowledge.filter((k) => !k.stale);

  return (
    <dialog ref={dialogRef} className="capture-dialog" onCancel={(e) => { e.preventDefault(); onClose(); }}>
      <header><div><span className="eyebrow">Assemble draft</span><h1>Build from approved knowledge</h1></div><button className="ghost-icon" aria-label="Close dialog" onClick={onClose}><X size={20} /></button></header>
      <div className="form-field"><label htmlFor="draft-title">Title</label><input id="draft-title" value={title} onChange={(e) => setTitle(e.target.value)} required minLength={3} maxLength={240} autoFocus placeholder="e.g. Q4 investor brief" /></div>
      <div className="form-row">
        <div className="form-field"><label htmlFor="draft-intent">Intent</label><select id="draft-intent" value={intent} onChange={(e) => setIntent(e.target.value)}><option value="brief">Brief</option><option value="article">Article</option><option value="agent">Agent context</option><option value="questions">Questions</option></select></div>
        <div className="form-field"><label htmlFor="draft-audience">Audience</label><input id="draft-audience" value={audience} onChange={(e) => setAudience(e.target.value)} maxLength={160} placeholder="e.g. Enterprise leaders" /></div>
      </div>
      <div className="form-field"><label>Knowledge atoms ({selected.length} of {usable.length} selected)</label>
        <ul className="evidence-list" style={{ maxHeight: 200, overflow: "auto" }}>
          {usable.map((k) => (
            <li key={k.id}><button type="button" className={selected.includes(k.id) ? "evidence-row" : "evidence-row is-off"} onClick={() => toggle(k.id)}>
              <span className="evidence-box">{selected.includes(k.id) && <Check size={12} />}</span>
              <span className="evidence-copy"><strong>{k.statement}</strong><small><span className="type-chip">{k.type}</span> v{k.version}</small></span>
            </button></li>
          ))}
        </ul>
      </div>
      <footer><button className="secondary-button" onClick={onClose}>Cancel</button><button className="primary-button" onClick={submit} disabled={busy || !title.trim() || selected.length === 0}>{busy ? "Assembling…" : `Assemble ${selected.length} atoms`}</button></footer>
    </dialog>
  );
}

function DraftDetailView({ draftId, onBack, onNotice, onError }: { draftId: string; onBack: () => void; onNotice: (v: string) => void; onError: (v: string) => void }) {
  const client = useBrainClient();
  const [draft, setDraft] = useState<DraftDetail | null>(null);

  const load = useCallback(async () => {
    try { setDraft(await client.draft(draftId)); }
    catch (err) { onError(err instanceof Error ? err.message : "Failed to load draft"); }
  }, [client, draftId, onError]);
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); }, [load]);

  async function downloadMarkdown() {
    if (!draft) return;
    const lines = [`# ${draft.title}`, `Audience: ${draft.audience || "not specified"}`, `Intent: ${draft.intent}`, ""];
    for (const section of draft.sections) {
      if (section.title) lines.push(`## ${section.title}`);
      lines.push(section.content, "");
      if (section.knowledge_items.length > 0) {
        lines.push("**Sources:**");
        for (const k of section.knowledge_items) {
          lines.push(`- [${k.type}] ${k.statement}`);
        }
        lines.push("");
      }
    }
    const blob = new Blob([lines.join("\n")], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = `draft-${draft.title.toLowerCase().replace(/\s+/g, "-")}.md`; a.click();
    URL.revokeObjectURL(url);
    onNotice("Draft downloaded as markdown.");
  }

  if (!draft) return <div className="panel-card"><EmptyState icon={<Clock3 />} title="Loading…">Fetching draft.</EmptyState></div>;

  return (
    <div className="studio-detail">
      <button className="text-button" onClick={onBack}><ArrowRight size={15} style={{ transform: "rotate(180deg)" }} /> Back to drafts</button>
      <section className="panel-card">
        <div className="card-heading">
          <div><span className="type-chip">{draft.intent}</span><h2>{draft.title}</h2>{draft.audience && <p className="studio-meta">For: {draft.audience}</p>}</div>
          <div><button className="secondary-button" onClick={downloadMarkdown}><Download size={16} /> Markdown</button></div>
        </div>
        {draft.sections.map((section) => (
          <div key={section.id} className="draft-section">
            {section.title && <h3>{section.title}</h3>}
            <div className="draft-content">{section.content}</div>
            {section.knowledge_items.length > 0 && (
              <div className="draft-citations"><strong>Cited knowledge:</strong>
                <ul>{section.knowledge_items.map((k) => <li key={k.id}><span className="type-chip">{k.type}</span> {k.statement}</li>)}</ul>
              </div>
            )}
          </div>
        ))}
        {draft.sections.length === 0 && <EmptyState icon={<FileText />} title="Empty draft">This draft has no sections yet.</EmptyState>}
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

export function ActivateView({ knowledge, onNavigate, onNotice }: {
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

export function AnalyticsPreview({ overview, knowledge, integrity }: { overview: Overview | null; knowledge: Knowledge[]; integrity: Integrity | null }) {
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
        <Metric label="Canonical atoms" value={canon} detail="Approved and reusable" icon={<CheckCircle2 />} tone="green" share={extracted ? canon / extracted : 0} shareNote={`${extracted ? Math.round((canon / extracted) * 100) : 0}% of ${extracted} approved and pending claims`} />
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
              <th scope="col" className="share-col">Of largest stage ({peak})</th>
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
                        <span className="share-value">{stage.value} / {peak}</span>
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

export function AuditView({ overview, integrity }: { overview: Overview; integrity: Integrity | null }) {
  const [period, setPeriod] = useState<Period>("all");
  const [action, setAction] = useState("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const actions = [...new Set(overview.recent_activity.map(event => event.action))];
  const events = useMemo(() => filterByPeriod(overview.recent_activity, period).filter(event => action === "all" || event.action === action), [overview.recent_activity, period, action]);
  const selectedEvent = overview.recent_activity.find(event => event.id === selectedId);
  return (
    <div className="audit-layout">
      <section className="integrity-card panel-card">
        <div className="card-heading"><div><span className="section-kicker">Integrity monitor</span><h2>Current signals</h2></div><ShieldCheck size={21} /></div>
        <div className="integrity-metrics"><div><strong>{integrity?.stale_count ?? 0}</strong><span>stale sources</span></div><div><strong>{integrity?.conflict_count ?? 0}</strong><span>possible conflicts</span></div></div>
        {integrity?.issues.length ? <ul className="issue-list">{integrity.issues.map((issue, index) => <li key={`${issue.knowledge_id}-${index}`}><TriangleAlert size={16} /><span><strong>{issue.kind.replaceAll("_", " ")}</strong>{issue.detail}<a href={`#/${window.location.hash.startsWith("#/demo/") ? "demo" : "console"}/brain?record=${encodeURIComponent(issue.knowledge_id)}`}>Inspect knowledge</a></span></li>)}</ul> : <div className="all-clear"><CheckCircle2 size={18} className="verified-icon" /><span><strong>All clear</strong>No stale or conflicting knowledge detected.</span></div>}
      </section>
      <section className="timeline-card panel-card">
        <div className="card-heading">
          <div>
            <span className="section-kicker">Domain events</span>
            <h2>Recent activity</h2>
            <p className="section-sub">{events.length} of {overview.recent_activity.length} recorded events</p>
          </div>
          <div className="audit-filters"><select aria-label="Filter event action" value={action} onChange={event => setAction(event.target.value)}><option value="all">All actions</option>{actions.map(value => <option key={value} value={value}>{value.replaceAll(".", " ")}</option>)}</select><PeriodFilter period={period} onChange={setPeriod} /></div>
        </div>
        <ol className="audit-timeline">
          {events.map((event) => <li key={event.id}><span className="timeline-dot" /><div><button className="audit-event-button" onClick={() => setSelectedId(event.id)}>{event.action.replaceAll(".", " ")}</button><p>{event.detail}</p></div><time dateTime={event.created_at}>{timeAgo(event.created_at)}</time></li>)}
          {overview.recent_activity.length === 0 && <li className="timeline-empty"><Inbox size={16} aria-hidden="true" /><div><strong>No events yet</strong><p>New workspace events will appear here.</p></div></li>}
          {overview.recent_activity.length > 0 && events.length === 0 && <li className="timeline-empty"><Clock3 size={16} aria-hidden="true" /><div><strong>Nothing in this window</strong><p>Choose All to see older activity.</p></div></li>}
        </ol>
      </section>
      {selectedEvent && <Detail title={selectedEvent.action.replaceAll(".", " ")} onClose={() => setSelectedId(null)}><p>{selectedEvent.detail}</p><div className="detail-stat"><span>Recorded</span><strong>{new Date(selectedEvent.created_at).toLocaleString()}</strong></div><div className="detail-stat"><span>Event ID</span><code>{selectedEvent.id}</code></div></Detail>}
    </div>
  );
}

export function ConnectorsView({ onChanged, onNotice, onError }: { onChanged: () => Promise<void>; onNotice: (value: string) => void; onError: (value: string) => void }) {
  const client = useBrainClient();
  const [provider, setProvider] = useState("google-drive");
  const [documentId, setDocumentId] = useState("");
  const [accessToken, setAccessToken] = useState("");
  const [busy, setBusy] = useState(false);

  async function ingest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    try {
      await client.connectorIngest(provider, { document_id: documentId, access_token: accessToken });
      onNotice("Document ingested. Its proposals are in the Inbox for review — not yet canonical.");
      setDocumentId("");
      setAccessToken("");
      await onChanged();
    } catch (requestError) {
      onError(requestError instanceof Error ? requestError.message : "Connector fetch failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel-card">
      <h2>Ingest from a provider</h2>
      <p>Fetch one document from Google Drive, Notion, or OneDrive and bring it into the review queue. The provider token is used for the read only and never stored.</p>
      <form onSubmit={ingest} className="ask-composer">
        <div className="field-heading"><label htmlFor="connector-provider">Provider</label></div>
        <select id="connector-provider" value={provider} onChange={(e) => setProvider(e.target.value)}>
          <option value="google-drive">Google Drive</option>
          <option value="notion">Notion</option>
          <option value="onedrive">OneDrive</option>
        </select>
        <div className="field-heading"><label htmlFor="connector-doc">Document ID</label></div>
        <input id="connector-doc" value={documentId} onChange={(e) => setDocumentId(e.target.value)} required placeholder="Drive file id / Notion page id / OneDrive item id" />
        <div className="field-heading"><label htmlFor="connector-token">Provider access token</label></div>
        <input id="connector-token" type="password" value={accessToken} onChange={(e) => setAccessToken(e.target.value)} required placeholder="OAuth access token (read only, not stored)" />
        <button className="primary-button" disabled={busy}>{busy ? "Fetching…" : "Fetch & ingest for review"}</button>
      </form>
    </div>
  );
}

export function GraphView() {
  const client = useBrainClient();
  const [data, setData] = useState<Graph | null>(null);
  const [failed, setFailed] = useState(false);
  const [filter, setFilter] = useState("All");
  const [list, setList] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [selected, setSelected] = useState<string | null>(null);
  const drag = useRef<{ x: number; y: number; originX: number; originY: number } | null>(null);
  useEffect(() => {
    client.graph().then(setData).catch(() => setFailed(true));
  }, [client]);

  // Sources are hubs; their approved knowledge fans out around them.
  const nodes: { id: string; x: number; y: number; label: string; type: string; detail: string }[] = [];
  const documents = data?.documents ?? [];
  const cx = 380, cy = 215, hubR = 150, memR = 58;
  documents.forEach((doc, i) => {
    const angle = (i / Math.max(documents.length, 1)) * Math.PI * 2 - Math.PI / 2;
    const hx = cx + hubR * Math.cos(angle), hy = cy + hubR * Math.sin(angle);
    nodes.push({ id: doc.id, x: hx, y: hy, label: doc.title || "Source", type: "Source", detail: doc.summary || doc.documentType });
    doc.memories.forEach((m, j) => {
      const count = doc.memories.length;
      const ma = angle + (j - (count - 1) / 2) * 0.55;
      nodes.push({ id: m.id, x: hx + memR * Math.cos(ma), y: hy + memR * Math.sin(ma), label: m.memory.length > 34 ? `${m.memory.slice(0, 34)}…` : m.memory, type: "Approved", detail: m.memory });
    });
  });
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const edges = (data?.edges ?? []).filter((e) => byId.has(e.source) && byId.has(e.target));
  const visible = nodes.filter((n) => filter === "All" || n.type === filter);
  const selectedNode = nodes.find((n) => n.id === selected);
  const move = (x: number, y: number) => setPan((p) => ({ x: p.x + x, y: p.y + y }));
  const edgeColor = (t: string) => (t === "derives" ? "var(--amber)" : t === "extends" ? "var(--accent)" : "var(--line-strong)");

  if (failed) return <EmptyState icon={<Network />} title="Graph unavailable">Loading failed. Retry from the header. No sample graph has replaced your workspace.</EmptyState>;
  if (!data) return <LoadingState />;
  if (!nodes.length) return <EmptyState icon={<Network />} title="Nothing to map yet">Approve knowledge and it appears here, linked to its source.</EmptyState>;

  return <>
    <div className="preview-toolbar">
      <div className="tabs" role="group" aria-label="Filter graph nodes">{["All", "Source", "Approved"].map((x) => <button key={x} aria-pressed={filter === x} className={filter === x ? "active" : ""} onClick={() => setFilter(x)}>{x}</button>)}</div>
      <button className="secondary-button" onClick={() => setList(!list)}>{list ? "Graph view" : "Accessible list"}</button>
    </div>
    <div className="graph-canvas" onPointerDown={(e) => { if ((e.target as HTMLElement).closest("button")) return; drag.current = { x: e.clientX, y: e.clientY, originX: pan.x, originY: pan.y }; e.currentTarget.setPointerCapture(e.pointerId); }} onPointerMove={(e) => { if (drag.current) setPan({ x: drag.current.originX + e.clientX - drag.current.x, y: drag.current.originY + e.clientY - drag.current.y }); }} onPointerUp={() => (drag.current = null)} onPointerCancel={() => (drag.current = null)}>
      <div className="graph-controls">
        <button aria-label="Zoom in" onClick={() => setZoom((z) => Math.min(2, z + 0.15))}><ZoomIn size={17} /></button>
        <button aria-label="Zoom out" onClick={() => setZoom((z) => Math.max(0.5, z - 0.15))}><ZoomOut size={17} /></button>
        <button aria-label="Reset graph" onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }}><Maximize2 size={17} /></button>
        <button aria-label="Pan left" onClick={() => move(-40, 0)}><ArrowLeft size={17} /></button>
        <button aria-label="Pan right" onClick={() => move(40, 0)}><ArrowRight size={17} /></button>
        <button aria-label="Pan up" onClick={() => move(0, -40)}><ArrowUp size={17} /></button>
        <button aria-label="Pan down" onClick={() => move(0, 40)}><ArrowDown size={17} /></button>
      </div>
      {list ? (
        <div className="graph-list"><h2>Knowledge relationships</h2>{visible.map((n) => <button className="preview-row" key={n.id} onClick={() => setSelected(n.id)}><strong>{n.label}</strong><span>{n.type}</span><ArrowRight size={16} /></button>)}</div>
      ) : (
        <div className="graph-inner" style={{ transform: `translate(${pan.x}px,${pan.y}px) scale(${zoom})` }}>
          <svg viewBox="0 0 760 430" preserveAspectRatio="none" aria-hidden="true">{edges.filter((e) => visible.some((n) => n.id === e.source) && visible.some((n) => n.id === e.target)).map((e) => { const a = byId.get(e.source)!, b = byId.get(e.target)!; return <line key={e.source + e.target} x1={a.x} y1={a.y} x2={b.x} y2={b.y} style={{ stroke: edgeColor(e.edgeType) }} />; })}</svg>
          {visible.map((n) => <button key={n.id} className={`graph-node node-${n.type.toLowerCase()}`} style={{ left: `${(n.x / 760) * 100}%`, top: `${(n.y / 430) * 100}%` }} onClick={() => setSelected(n.id)} aria-label={`${n.label}, ${n.type}`}>{n.label}</button>)}
        </div>
      )}
      <div className="graph-legend"><strong>Legend</strong>{["Source", "Approved"].map((x) => <span key={x}><i />{x}</span>)}</div>
    </div>
    {selectedNode && <Detail title={selectedNode.label} onClose={() => setSelected(null)}><span className="status-pill">{selectedNode.type}</span><p>{selectedNode.detail}</p><h3>Connected records</h3>{edges.filter((e) => e.source === selectedNode.id || e.target === selectedNode.id).map((e) => byId.get(e.source === selectedNode.id ? e.target : e.source)!).map((n) => <button key={n.id} className="preview-row" onClick={() => setSelected(n.id)}><span>{n.label}</span><ArrowRight size={16} /></button>)}</Detail>}
  </>;
}

export function AgentsView({ connections }: { connections: McpConnection[] }) {
  return (
    <div className="panel-card">
      <div className="card-heading">
        <div>
          <span className="section-kicker">Connected apps</span>
          <h2>MCP clients</h2>
          <p className="section-sub">Agents that have reached this Brain. Tools are read-only — approval stays here in the console.</p>
        </div>
        <Brain size={21} />
      </div>
      {connections.length ? (
        <div className="overview-table-scroll">
          <table className="overview-table">
            <thead>
              <tr>
                <th scope="col">Client</th>
                <th scope="col">Auth</th>
                <th scope="col">Principal</th>
                <th scope="col">Role</th>
                <th scope="col" className="num">Calls</th>
                <th scope="col">Last seen</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {connections.map((c) => {
                const label =
                  c.client_name ||
                  (c.user_agent ? c.user_agent.split(" ")[0] : "") ||
                  (c.source_kind === "oauth" ? "OAuth client" : "Direct bearer");
                return (
                  <tr key={c.id}>
                    <td>
                      <strong>{label}</strong>
                      {c.user_agent ? <small style={{ display: "block", color: "var(--muted-foreground)" }}>{c.user_agent}</small> : null}
                    </td>
                    <td>{c.source_kind === "oauth" ? "OAuth" : "API key"}</td>
                    <td><code>{c.principal_preview}</code></td>
                    <td>{c.role}</td>
                    <td className="num">{c.access_count}</td>
                    <td>{timeAgo(c.last_seen)}</td>
                    <td>{c.status}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState icon={<Brain size={26} />} title="No MCP clients yet">
          Add this Brain’s <code>/mcp</code> URL to an agent (Antigravity, Cursor, Claude) and call a tool. A connection appears here the first time a client authenticates.
        </EmptyState>
      )}
    </div>
  );
}

export function CaptureDialog({ onClose, onCreated, onError }: { onClose: () => void; onCreated: () => Promise<void>; onError: (value: string) => void }) {
  const client = useBrainClient();
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
      await client.createSource({
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
