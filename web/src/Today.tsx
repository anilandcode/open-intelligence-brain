import { useEffect, useState } from "react";
import { ChevronRight, CircleHelp, Sun } from "lucide-react";
import type { Today, Unanswered } from "./api";
import { useBrainClient } from "./client";
import { shortDate } from "./dates";
import type { View } from "./routes";

const consoleBase = () => (window.location.hash.startsWith("#/demo/") ? "demo" : "console");

/** The first thing on the Overview: what needs a person today, each a link to where it's handled. */
export function TodayPanel({ onNavigate }: { onNavigate: (view: View) => void }) {
  const client = useBrainClient();
  const [today, setToday] = useState<Today | null>(null);

  useEffect(() => {
    let live = true;
    client.today()
      .then((value) => { if (live) setToday(Array.isArray(value?.items) ? value : null); })
      .catch(() => { if (live) setToday(null); });
    return () => { live = false; };
  }, [client]);

  if (!today) return null;
  function open(view: string) {
    if (view === "overview") { document.getElementById("gardening")?.scrollIntoView({ behavior: "smooth", block: "start" }); return; }
    onNavigate(view as View);
  }
  return (
    <section className="panel-card today-panel" aria-labelledby="today-heading">
      <h2 id="today-heading"><Sun size={17} aria-hidden="true" /> Today</h2>
      {today.items.length === 0 ? (
        <p className="section-sub">Nothing needs you right now. New captures, reviews and questions will show up here.</p>
      ) : (
        <ul className="today-list">
          {today.items.map((item) => (
            <li key={item.key}>
              <button type="button" onClick={() => open(item.view)}>
                <span className="today-count">{item.count}</span>
                <span className="today-text"><strong>{item.label.replace(/^\d+ /, "")}</strong>{item.detail && <small>{item.detail}</small>}</span>
                <ChevronRight size={15} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Questions the Brain declined, most asked first, so the gaps get filled. Owners and admins only. */
export function UnansweredPanel({ version }: { version: number }) {
  const client = useBrainClient();
  const [rows, setRows] = useState<Unanswered[] | null>(null);
  const [reload, setReload] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    client.unanswered()
      .then((value) => { if (live) setRows(Array.isArray(value) ? value : null); })
      .catch(() => { if (live) setRows(null); });
    return () => { live = false; };
  }, [client, version, reload]);

  async function dismiss(row: Unanswered) {
    try { await client.dismissUnanswered(row.id); setReload((value) => value + 1); }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : "Could not dismiss."); }
  }

  if (!rows) return null;
  return (
    <section className="panel-card unanswered-panel" aria-labelledby="unanswered-heading">
      <h2 id="unanswered-heading"><CircleHelp size={17} aria-hidden="true" /> Couldn’t answer</h2>
      <p className="section-sub">Questions the Brain declined, from this page and from agents. Capture what you know; once it’s approved and the question is asked again, it leaves this list.</p>
      {error && <div className="alert alert--error" role="alert">{error}</div>}
      {rows.length === 0 ? <p className="section-sub">No open questions.</p> : (
        <ul className="unanswered-list">
          {rows.map((row) => (
            <li key={row.id}>
              <div>
                <strong>{row.question}</strong>
                <small>Asked {row.times_asked} {row.times_asked === 1 ? "time" : "times"}{row.via === "agent" ? " (by an agent)" : ""} · last {shortDate(row.last_asked_at)}</small>
              </div>
              <div className="unanswered-actions">
                <a className="secondary-button" href={`#/${consoleBase()}/capture?${new URLSearchParams({ question: row.question })}`}>Capture an answer</a>
                <button type="button" className="link-button" onClick={() => dismiss(row)} aria-label={`Dismiss: ${row.question}`}>Dismiss</button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
