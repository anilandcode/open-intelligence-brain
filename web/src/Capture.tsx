import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Bookmark, Copy, FolderSync, Mic, MicOff, RefreshCw, Send, Smartphone, Trash2 } from "lucide-react";
import type { Watch, WatchProvider } from "./api";
import { bookmarklet, readSharedCapture, speechRecognition } from "./captureLinks";
import { useBrainClient } from "./client";

const message = (error: unknown, fallback: string) => (error instanceof Error ? error.message : fallback);
const PROVIDERS: Record<WatchProvider, string> = { "google-drive": "Google Drive", notion: "Notion", onedrive: "OneDrive" };

/** One place to drop anything: typed or dictated notes, shared pages, clipped text, transcripts. */
export function CaptureView({ onChanged, onNotice, onError }: { onChanged: () => Promise<void>; onNotice: (value: string) => void; onError: (value: string) => void }) {
  const client = useBrainClient();
  const [shared] = useState(() => readSharedCapture());
  const [text, setText] = useState(shared?.text ?? "");
  const [title, setTitle] = useState(shared?.title ?? "");
  const [url, setUrl] = useState(shared?.url ?? "");
  const [kind, setKind] = useState("note");
  const [sensitivity, setSensitivity] = useState("private");
  const [saving, setSaving] = useState(false);
  const [listening, setListening] = useState(false);
  const [dictated, setDictated] = useState(false);
  const [copied, setCopied] = useState(false);
  const recognition = useRef<{ stop: () => void } | null>(null);
  const Recognition = speechRecognition();
  const clip = bookmarklet(window.location.origin);

  useEffect(() => () => recognition.current?.stop(), []);

  function dictate() {
    if (listening) { recognition.current?.stop(); return; }
    if (!Recognition) return;
    const session = new Recognition();
    session.lang = navigator.language || "en-US";
    session.continuous = true;
    session.interimResults = false;
    session.onresult = (event) => {
      let heard = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        if (event.results[index].isFinal) heard += event.results[index][0].transcript;
      }
      if (heard.trim()) { setText((current) => `${current}${current && !current.endsWith(" ") ? " " : ""}${heard.trim()}`); setDictated(true); }
    };
    session.onerror = (event) => { if (event.error !== "aborted" && event.error !== "no-speech") onError(`Dictation stopped: ${event.error}.`); };
    session.onend = () => { setListening(false); recognition.current = null; };
    recognition.current = session;
    session.start();
    setListening(true);
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    recognition.current?.stop();
    setSaving(true);
    try {
      const source = await client.capture({ text, title, url, kind, sensitivity, via: shared ? shared.via : dictated ? "voice" : "console" });
      onNotice(`Saved “${source.title}”. ${source.proposal_count} ${source.proposal_count === 1 ? "suggestion is" : "suggestions are"} in the Inbox for review. Nothing is approved yet.`);
      setText(""); setTitle(""); setUrl(""); setDictated(false);
      if (window.location.search || window.location.hash.includes("?")) window.history.replaceState(null, "", `${window.location.pathname}#/console/capture`);
      await onChanged();
    } catch (requestError) {
      onError(message(requestError, "Could not save the capture."));
    } finally {
      setSaving(false);
    }
  }

  async function copyClipper() {
    try { await navigator.clipboard.writeText(clip); setCopied(true); } catch { setCopied(false); }
  }

  return (
    <div className="capture-view">
      <section className="panel-card capture-card" aria-labelledby="quick-capture-heading">
        <h2 id="quick-capture-heading">New capture</h2>
        <p className="section-sub">Type, paste or dictate anything worth keeping. It is saved as a source and its sentences go to the Inbox for review. Nothing is approved automatically.</p>
        {shared?.question ? <p className="capture-shared" role="status">The Brain couldn’t answer <strong>“{shared.question}”</strong>. Write what you know; once the answer is approved, the question closes on its own.</p> : shared && <p className="capture-shared" role="status">Shared from {shared.url ? <strong>{shared.url}</strong> : "another app"}. Check it and save.</p>}
        <form onSubmit={save} className="capture-form">
          <div className="form-field">
            <div className="capture-text-heading"><label htmlFor="capture-text">What to capture</label>{Recognition && <button type="button" className={`secondary-button${listening ? " is-listening" : ""}`} onClick={dictate} aria-pressed={listening}>{listening ? <MicOff size={15} aria-hidden="true" /> : <Mic size={15} aria-hidden="true" />}{listening ? "Stop dictating" : "Dictate"}</button>}</div>
            <textarea id="capture-text" value={text} onChange={(event) => setText(event.target.value)} rows={8} maxLength={100000} placeholder="A thought, a decision, a quote from a call, or a whole meeting transcript…" />
            {listening && <span className="field-help" role="status">Listening… speak, then press Stop. Your browser turns speech into text; no audio is sent to the Brain.</span>}
          </div>
          <div className="form-row">
            <div className="form-field"><label htmlFor="capture-title">Title <small>(optional)</small></label><input id="capture-title" value={title} onChange={(event) => setTitle(event.target.value)} maxLength={240} placeholder="Made from the first line if empty" /></div>
            <div className="form-field"><label htmlFor="capture-url">Link <small>(optional)</small></label><input id="capture-url" type="url" value={url} onChange={(event) => setUrl(event.target.value)} maxLength={2000} placeholder="https://…" /></div>
          </div>
          <div className="form-row">
            <div className="form-field"><label htmlFor="capture-kind">Type</label><select id="capture-kind" value={kind} onChange={(event) => setKind(event.target.value)}><option value="note">Note</option><option value="research">Research or article</option><option value="transcript">Meeting transcript</option><option value="decision">Decision</option><option value="interview">Interview</option></select></div>
            <div className="form-field"><label htmlFor="capture-sensitivity">Visibility</label><select id="capture-sensitivity" value={sensitivity} onChange={(event) => setSensitivity(event.target.value)}><option value="private">Private</option><option value="internal">Internal</option><option value="public">Public</option></select></div>
          </div>
          {kind === "transcript" && <p className="field-help">Paste a Zoom, Teams or Meet caption file (.vtt or .srt), an Otter export, or “Name: what they said” lines. Timings are dropped and each suggestion notes who said it.</p>}
          <footer><button className="primary-button" type="submit" disabled={saving || (!text.trim() && !url.trim())}><Send size={15} aria-hidden="true" />{saving ? "Saving…" : "Save for review"}</button></footer>
        </form>
      </section>

      <section className="panel-card capture-card" aria-labelledby="capture-anywhere-heading">
        <h2 id="capture-anywhere-heading">Send from anywhere</h2>
        <div className="capture-ways">
          <div>
            <h3><Bookmark size={15} aria-hidden="true" /> Browser clipper</h3>
            <p>Make a bookmark and paste this as its address. On any page, select text if you like, then click the bookmark: this page opens with the title, link and selection filled in.</p>
            <div className="capture-copy"><label className="sr-only" htmlFor="capture-clipper">Clipper bookmark address</label><input id="capture-clipper" readOnly value={clip} onFocus={(event) => event.currentTarget.select()} /><button type="button" className="secondary-button" onClick={copyClipper}><Copy size={15} aria-hidden="true" />{copied ? "Copied" : "Copy"}</button></div>
          </div>
          <div>
            <h3><Smartphone size={15} aria-hidden="true" /> Phone share sheet</h3>
            <p>On Android, open the console in Chrome and choose “Add to Home screen”. Open Brain then appears when you share a page or text. On iPhone, a Shortcut can send text to <code>POST /api/v1/capture</code> with an API key that has <code>sources:write</code>.</p>
          </div>
          <div>
            <h3><Mic size={15} aria-hidden="true" /> Voice notes</h3>
            <p>Use Dictate above, or your phone keyboard’s microphone. Speech becomes text on your device; the Brain keeps only the text.</p>
          </div>
        </div>
      </section>
    </div>
  );
}

/** Folders whose documents flow in as sources and stay current through new versions. */
export function WatchesPanel({ onChanged, onNotice, onError }: { onChanged: () => Promise<void>; onNotice: (value: string) => void; onError: (value: string) => void }) {
  const client = useBrainClient();
  const [watches, setWatches] = useState<Watch[] | null>(null);
  const [reload, setReload] = useState(0);
  const [provider, setProvider] = useState<WatchProvider>("google-drive");
  const [folderId, setFolderId] = useState("");
  const [label, setLabel] = useState("");
  const [kind, setKind] = useState("research");
  const [sensitivity, setSensitivity] = useState("private");
  const [tokens, setTokens] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");

  useEffect(() => {
    let live = true;
    client.watches()
      .then((rows) => { if (live) setWatches(Array.isArray(rows) ? rows : []); })
      .catch(() => { if (live) setWatches([]); });
    return () => { live = false; };
  }, [client, reload]);
  const refresh = useCallback(() => setReload((value) => value + 1), []);

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("add");
    try {
      await client.createWatch({ provider, folder_id: folderId.trim(), label: label.trim(), kind, sensitivity });
      onNotice("Folder watched. Sync it with a provider token to bring its documents in for review.");
      setFolderId(""); setLabel(""); refresh();
    } catch (requestError) { onError(message(requestError, "Could not watch that folder.")); }
    finally { setBusy(""); }
  }

  async function sync(watch: Watch) {
    setBusy(watch.id);
    try {
      const result = await client.syncWatch(watch.id, tokens[watch.id] ?? "");
      setTokens((current) => ({ ...current, [watch.id]: "" }));
      onNotice(`${watch.label || PROVIDERS[watch.provider]}: ${result.summary}.${result.added.length || result.updated.length ? " New suggestions are in the Inbox." : ""}${result.errors.length ? ` Failed: ${result.errors.join("; ")}` : ""}`);
      refresh();
      await onChanged();
    } catch (requestError) { onError(message(requestError, "The sync failed.")); refresh(); }
    finally { setBusy(""); }
  }

  async function remove(watch: Watch) {
    setBusy(watch.id);
    try { await client.deleteWatch(watch.id); onNotice("Stopped watching. Documents already brought in stay."); refresh(); }
    catch (requestError) { onError(message(requestError, "Could not stop watching.")); }
    finally { setBusy(""); }
  }

  if (!watches) return null;
  return (
    <section className="panel-card watches-panel" aria-labelledby="watches-heading">
      <h2 id="watches-heading"><FolderSync size={17} aria-hidden="true" /> Watched folders</h2>
      <p className="section-sub">Each sync brings new documents in for review and adds a new version when a document changes, so only new sentences are suggested. Google Meet saves transcripts to a Drive folder: watch it as “Meeting transcript”. Tokens are used once and never stored.</p>
      {watches.length > 0 && (
        <ul className="watch-list">
          {watches.map((watch) => (
            <li key={watch.id}>
              <div className="watch-meta">
                <strong>{watch.label || watch.folder_id}</strong>
                <small>{PROVIDERS[watch.provider]} · {watch.kind === "transcript" ? "meeting transcripts" : watch.kind} · {watch.sensitivity} · {watch.document_count} {watch.document_count === 1 ? "document" : "documents"}</small>
                <small>{watch.last_synced_at ? `Last sync ${new Date(watch.last_synced_at).toLocaleString()}: ${watch.last_result}` : "Not synced yet"}</small>
              </div>
              <form className="watch-sync" onSubmit={(event) => { event.preventDefault(); void sync(watch); }}>
                <label className="sr-only" htmlFor={`watch-token-${watch.id}`}>{PROVIDERS[watch.provider]} access token for {watch.label || watch.folder_id}</label>
                <input id={`watch-token-${watch.id}`} type="password" required value={tokens[watch.id] ?? ""} onChange={(event) => setTokens((current) => ({ ...current, [watch.id]: event.target.value }))} placeholder="Access token" />
                <button className="secondary-button" disabled={busy === watch.id}><RefreshCw size={15} aria-hidden="true" />{busy === watch.id ? "Syncing…" : "Sync"}</button>
                <button type="button" className="ghost-icon" aria-label={`Stop watching ${watch.label || watch.folder_id}`} onClick={() => remove(watch)} disabled={busy === watch.id}><Trash2 size={15} /></button>
              </form>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={add} className="watch-add">
        <div className="form-row">
          <div className="form-field"><label htmlFor="watch-provider">Provider</label><select id="watch-provider" value={provider} onChange={(event) => setProvider(event.target.value as WatchProvider)}>{Object.entries(PROVIDERS).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></div>
          <div className="form-field"><label htmlFor="watch-folder">Folder ID</label><input id="watch-folder" required value={folderId} onChange={(event) => setFolderId(event.target.value)} placeholder="Drive folder id / Notion page id / OneDrive folder id" /></div>
        </div>
        <div className="form-row">
          <div className="form-field"><label htmlFor="watch-label">Name</label><input id="watch-label" value={label} onChange={(event) => setLabel(event.target.value)} maxLength={160} placeholder="e.g. Meeting notes" /></div>
          <div className="form-field"><label htmlFor="watch-kind">Documents are</label><select id="watch-kind" value={kind} onChange={(event) => setKind(event.target.value)}><option value="research">Research and docs</option><option value="note">Notes</option><option value="transcript">Meeting transcripts</option><option value="decision">Decisions</option></select></div>
          <div className="form-field"><label htmlFor="watch-sensitivity">Visibility</label><select id="watch-sensitivity" value={sensitivity} onChange={(event) => setSensitivity(event.target.value)}><option value="private">Private</option><option value="internal">Internal</option><option value="public">Public</option></select></div>
        </div>
        <button className="primary-button" disabled={busy === "add"}>{busy === "add" ? "Adding…" : "Watch folder"}</button>
      </form>
      <p className="field-help">To sync on a schedule, run <code>python -m brain.watches &lt;workspace&gt;</code> from cron with <code>BRAIN_SYNC_TOKEN_GOOGLE_DRIVE</code>, <code>BRAIN_SYNC_TOKEN_NOTION</code> or <code>BRAIN_SYNC_TOKEN_ONEDRIVE</code> set.</p>
    </section>
  );
}
