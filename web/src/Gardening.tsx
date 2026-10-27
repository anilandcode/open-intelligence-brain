import { useEffect, useState } from "react";
import { Send, Sprout } from "lucide-react";
import type { Gardening, GardenSection } from "./api";
import { useBrainClient } from "./client";

const SECTIONS: { key: GardenSection; label: string }[] = [
  { key: "due_for_review", label: "Due for review" },
  { key: "expired", label: "Expired" },
  { key: "source_changed", label: "Source changed" },
  { key: "conflicts", label: "Possible conflicts" },
  { key: "duplicates", label: "Possible duplicates" },
  { key: "unused", label: "Not used lately" },
];

/** Approved knowledge that needs a person, the same list the weekly digest sends. */
export function GardeningPanel() {
  const client = useBrainClient();
  const [report, setReport] = useState<Gardening | null>(null);
  const [failed, setFailed] = useState(false);
  const [sending, setSending] = useState(false);
  const [status, setStatus] = useState("");

  useEffect(() => {
    let live = true;
    client.gardening()
      .then((value) => { if (live) setReport(Array.isArray(value?.due_for_review) ? value : null); })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
  }, [client]);

  async function send() {
    setSending(true);
    try {
      const result = await client.sendGardening();
      setStatus(result.sent ? "Sent through Hermes." : result.reason);
    } catch (error) { setStatus(error instanceof Error ? error.message : "Could not send."); }
    finally { setSending(false); }
  }

  if (failed || !report) return null;
  const demo = window.location.hash.startsWith("#/demo/");
  const link = (id: string) => `#/${demo ? "demo" : "console"}/brain?record=${encodeURIComponent(id)}`;
  return (
    <section className="panel-card gardening-panel" aria-labelledby="gardening-heading">
      <div className="card-heading">
        <div><span className="section-kicker">Keep it current</span><h2 id="gardening-heading"><Sprout size={16} aria-hidden="true" /> Gardening</h2><p className="section-sub">{report.total ? `${report.total} approved ${report.total === 1 ? "item needs" : "items need"} a look. The weekly digest sends this list.` : "Nothing needs attention. Dates, conflicts and unused items are checked weekly."}</p></div>
        <div className="gardening-send"><button className="secondary-button" type="button" onClick={send} disabled={sending}><Send size={14} aria-hidden="true" />{sending ? "Sending…" : "Send digest now"}</button>{status && <small role="status">{status}</small>}</div>
      </div>
      {SECTIONS.filter(({ key }) => report[key].length > 0).map(({ key, label }) => (
        <div className="gardening-section" key={key}>
          <h3>{label} <span>{report.counts[key]}</span></h3>
          <ul>{report[key].map((entry) => <li key={`${key}-${entry.knowledge_id}-${entry.related_id ?? ""}`}><a href={link(entry.knowledge_id)}>{entry.statement}</a><small>{entry.detail}</small></li>)}</ul>
        </div>
      ))}
    </section>
  );
}
