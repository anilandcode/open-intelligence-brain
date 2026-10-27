import { FormEvent, useCallback, useEffect, useState } from "react";
import { ArrowUpRight, Clock, NotebookPen, Search, Trash2 } from "lucide-react";
import type { AgentNote, SourceHit } from "./api";
import { useBrainClient } from "./client";
import { shortDate } from "./dates";

const message = (error: unknown, fallback: string) => (error instanceof Error ? error.message : fallback);

/** Agents' expiring working notes, and a search through source text nobody has reviewed yet. */
export function WorkingMemoryView({ onOpenKnowledge, onOpenSource, onChanged, onNotice, onError }: { onOpenKnowledge: (id: string) => void; onOpenSource: (id: string) => void; onChanged: () => Promise<void>; onNotice: (value: string) => void; onError: (value: string) => void }) {
  const client = useBrainClient();
  const [notes, setNotes] = useState<AgentNote[] | null>(null);
  const [reload, setReload] = useState(0);
  const [busy, setBusy] = useState("");
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SourceHit[] | null>(null);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    let live = true;
    client.scratchpad()
      .then((rows) => { if (live) setNotes(Array.isArray(rows) ? rows : []); })
      .catch((requestError) => { if (live) { setNotes([]); onError(message(requestError, "Could not load working notes.")); } });
    return () => { live = false; };
  }, [client, reload, onError]);
  const refresh = useCallback(() => setReload((value) => value + 1), []);

  async function promote(note: AgentNote) {
    setBusy(note.id);
    try {
      const source = await client.promoteNote(note.id);
      onNotice(`Filed “${source.title}” for review. ${source.proposal_count} ${source.proposal_count === 1 ? "suggestion is" : "suggestions are"} in the Inbox.`);
      refresh();
      await onChanged();
    } catch (requestError) { onError(message(requestError, "Could not promote the note.")); }
    finally { setBusy(""); }
  }

  async function remove(note: AgentNote) {
    setBusy(note.id);
    try { await client.deleteNote(note.id); refresh(); }
    catch (requestError) { onError(message(requestError, "Could not delete the note.")); }
    finally { setBusy(""); }
  }

  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (query.trim().length < 2) return;
    setSearching(true);
    try { setHits(await client.searchSources(query.trim(), 15)); }
    catch (requestError) { onError(message(requestError, "Search failed.")); }
    finally { setSearching(false); }
  }

  return (
    <div className="memory-view">
      <section className="panel-card memory-card" aria-labelledby="notes-heading">
        <h2 id="notes-heading"><NotebookPen size={17} aria-hidden="true" /> Agent notes</h2>
        <p className="section-sub">Notes agents keep while they work, through the <code>scratch_write</code> tool. They expire on their own and are never used to answer questions. Promote one to file it for review.</p>
        {notes === null ? null : notes.length === 0 ? (
          <p className="section-sub">No working notes right now.</p>
        ) : (
          <ul className="note-list">
            {notes.map((note) => (
              <li key={note.id}>
                <div className="note-body">
                  <p>{note.content}</p>
                  <small>
                    {note.topic && <span className="note-topic">{note.topic}</span>}
                    <span>{note.author}</span>
                    <span><Clock size={12} aria-hidden="true" /> Expires {shortDate(note.expires_at)}</span>
                    {note.promoted_source_id && <button type="button" className="link-button" onClick={() => onOpenSource(note.promoted_source_id!)}>Filed for review</button>}
                  </small>
                </div>
                <div className="note-actions">
                  {!note.promoted_source_id && <button type="button" className="secondary-button" onClick={() => promote(note)} disabled={busy === note.id}><ArrowUpRight size={15} aria-hidden="true" />Promote</button>}
                  <button type="button" className="ghost-icon" aria-label={`Delete note: ${note.content.slice(0, 40)}`} onClick={() => remove(note)} disabled={busy === note.id}><Trash2 size={15} /></button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel-card memory-card" aria-labelledby="unreviewed-heading">
        <h2 id="unreviewed-heading"><Search size={17} aria-hidden="true" /> Search source text</h2>
        <p className="section-sub">Look through everything captured, including sentences nobody has reviewed. Agents use the same search (<code>search_sources</code>); unreviewed text is evidence to check, not an answer.</p>
        <form className="memory-search" onSubmit={search} role="search">
          <label className="sr-only" htmlFor="source-search">Search source text</label>
          <input id="source-search" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="e.g. renewal discount" minLength={2} maxLength={500} />
          <button className="primary-button" disabled={searching || query.trim().length < 2}>{searching ? "Searching…" : "Search"}</button>
        </form>
        {hits && (hits.length === 0 ? <p className="section-sub" role="status">No source text matches.</p> : (
          <ul className="hit-list" aria-live="polite">
            {hits.map((hit, index) => (
              <li key={`${hit.source_id}-${index}`}>
                <span className={`hit-status hit-status--${hit.status}`}>{hit.status === "approved" ? "Approved" : "Unreviewed"}</span>
                <div>
                  <p>{hit.speaker ? <strong>{hit.speaker}: </strong> : null}{hit.excerpt}</p>
                  <small>
                    <button type="button" className="link-button" onClick={() => onOpenSource(hit.source_id)}>{hit.source_title}</button>
                    {hit.version > 1 && <span> · version {hit.version}</span>}
                    {hit.knowledge_id && <> · <button type="button" className="link-button" onClick={() => onOpenKnowledge(hit.knowledge_id!)}>Open approved item</button></>}
                  </small>
                </div>
              </li>
            ))}
          </ul>
        ))}
      </section>
    </div>
  );
}
