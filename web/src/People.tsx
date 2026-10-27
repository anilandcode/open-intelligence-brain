import { FormEvent, useCallback, useEffect, useState } from "react";
import { ChevronRight, Plus, Search, Users } from "lucide-react";
import type { Entity, EntityDetail, EntityKind } from "./api";
import { useBrainClient } from "./client";
import { Detail } from "./Detail";
import { ENTITY_KINDS, KIND_LABEL } from "./entities";
import { EmptyState, LoadingState } from "./LivePages";

type Props = {
  recordId?: string;
  onSelect: (id: string | null) => void;
  onNotice: (value: string) => void;
  onError: (value: string) => void;
};

const message = (error: unknown, fallback: string) => (error instanceof Error ? error.message : fallback);

/** People, companies, projects and topics that approved knowledge is about. */
export function PeopleView({ recordId, onSelect, onNotice, onError }: Props) {
  const client = useBrainClient();
  const [entities, setEntities] = useState<Entity[] | null>(null);
  const [kind, setKind] = useState<EntityKind | "all">("all");
  const [query, setQuery] = useState("");
  const [name, setName] = useState("");
  const [newKind, setNewKind] = useState<EntityKind>("person");
  const [adding, setAdding] = useState(false);

  const [version, setVersion] = useState(0);
  useEffect(() => {
    let live = true;
    client.entities()
      .then((value) => { if (live) setEntities(value); })
      .catch((error) => { if (!live) return; onError(message(error, "Could not load people and projects.")); setEntities([]); });
    return () => { live = false; };
  }, [client, onError, version]);
  const load = useCallback(async () => { setVersion((value) => value + 1); }, []);

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAdding(true);
    try {
      const created = await client.createEntity({ name: name.trim(), kind: newKind, link_existing: true });
      onNotice(created.item_count ? `${created.name} added and linked to ${created.item_count} approved ${created.item_count === 1 ? "item" : "items"}.` : `${created.name} added. New notes that name it will suggest it.`);
      setName("");
      await load();
    } catch (error) { onError(message(error, "Could not add that name.")); }
    finally { setAdding(false); }
  }

  if (!entities) return <LoadingState />;
  const needle = query.trim().toLowerCase();
  const shown = entities.filter((entity) => (kind === "all" || entity.kind === kind) && (!needle || `${entity.name} ${entity.aliases.join(" ")}`.toLowerCase().includes(needle)));

  return (
    <section className="brain-workspace panel-card">
      <div className="brain-toolbar">
        <search><form onSubmit={(event) => event.preventDefault()}><label className="sr-only" htmlFor="people-search">Search people, companies and projects</label><div className="search-field"><Search size={18} aria-hidden="true" /><input id="people-search" type="search" placeholder="Search names and aliases…" value={query} onChange={(event) => setQuery(event.target.value)} /></div></form></search>
        <div className="filter-tabs" aria-label="Filter by kind">
          <button className={kind === "all" ? "active" : ""} onClick={() => setKind("all")}>All <span>{entities.length}</span></button>
          {ENTITY_KINDS.map((value) => <button key={value} className={kind === value ? "active" : ""} onClick={() => setKind(value)}>{KIND_LABEL[value]} <span>{entities.filter((entity) => entity.kind === value).length}</span></button>)}
        </div>
      </div>
      <form className="entity-add" onSubmit={add}>
        <label className="sr-only" htmlFor="entity-name">Name</label>
        <input id="entity-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Add a person, company, project or topic" minLength={2} maxLength={80} required />
        <label className="sr-only" htmlFor="entity-kind">Kind</label>
        <select id="entity-kind" value={newKind} onChange={(event) => setNewKind(event.target.value as EntityKind)}>{ENTITY_KINDS.map((value) => <option key={value} value={value}>{value}</option>)}</select>
        <button className="primary-button" type="submit" disabled={adding || name.trim().length < 2}><Plus size={15} aria-hidden="true" /> Add</button>
      </form>
      <div className="knowledge-list knowledge-table">
        <div className="knowledge-table-head entity-row"><span>Name</span><span>Kind</span><span>Also known as</span><span>Items</span></div>
        {shown.map((entity) => <button className="knowledge-table-row entity-row" key={entity.id} onClick={() => onSelect(entity.id)}><strong>{entity.name}</strong><span>{entity.kind}</span><span>{entity.aliases.join(", ")}</span><span>{entity.item_count}</span><ChevronRight size={16} /></button>)}
        {shown.length === 0 && <EmptyState icon={<Users />} title={entities.length ? "No matches" : "No people or projects yet"}>{entities.length ? "Try another name or kind." : "Approve knowledge that names people, companies or projects, or add one above."}</EmptyState>}
      </div>
      {recordId && <EntityDrawer key={recordId} id={recordId} others={entities} onSelect={onSelect} onChanged={load} onNotice={onNotice} onError={onError} />}
    </section>
  );
}

function EntityDrawer({ id, others, onSelect, onChanged, onNotice, onError }: { id: string; others: Entity[]; onSelect: (id: string | null) => void; onChanged: () => Promise<void>; onNotice: (value: string) => void; onError: (value: string) => void }) {
  const client = useBrainClient();
  const [detail, setDetail] = useState<EntityDetail | null>(null);
  const [missing, setMissing] = useState(false);
  const [name, setName] = useState("");
  const [aliases, setAliases] = useState("");
  const [mergeInto, setMergeInto] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    client.entity(id).then((value) => { if (!live) return; setDetail(value); setName(value.name); setAliases(value.aliases.join(", ")); }).catch(() => { if (live) setMissing(true); });
    return () => { live = false; };
  }, [client, id]);

  if (missing) return <Detail title="Not available" onClose={() => onSelect(null)}><p>This name is not in the current workspace, or nothing you can read mentions it.</p></Detail>;
  if (!detail) return <Detail title="Loading" onClose={() => onSelect(null)}><LoadingState /></Detail>;

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!detail) return;
    setBusy(true);
    try {
      const updated = await client.updateEntity(detail.id, { name: name.trim(), aliases: aliases.split(",").map((alias) => alias.trim()).filter(Boolean) });
      setDetail({ ...detail, ...updated });
      setAliases(updated.aliases.join(", "));
      onNotice(`${updated.name} saved.`);
      await onChanged();
    } catch (error) { onError(message(error, "Could not save.")); }
    finally { setBusy(false); }
  }

  async function merge() {
    if (!detail || !mergeInto) return;
    setBusy(true);
    try {
      const kept = await client.mergeEntity(detail.id, mergeInto);
      onNotice(`${detail.name} merged into ${kept.name}.`);
      await onChanged();
      onSelect(kept.id);
    } catch (error) { onError(message(error, "Could not merge.")); }
    finally { setBusy(false); }
  }

  const demo = window.location.hash.startsWith("#/demo/");
  return (
    <Detail title={detail.name} onClose={() => onSelect(null)}>
      <div className="entity-detail">
        <p className="knowledge-card-meta"><span className="type-chip">{detail.kind}</span><span>{detail.item_count} approved {detail.item_count === 1 ? "item" : "items"}</span></p>
        <section aria-label="Approved knowledge">
          <h3>What the Brain knows</h3>
          <ul className="entity-items">
            {detail.items.map((item) => <li key={item.id}><a href={`#/${demo ? "demo" : "console"}/brain?record=${encodeURIComponent(item.id)}`}>{item.statement}</a><small>{item.type} · {item.source_title}</small></li>)}
          </ul>
        </section>
        {detail.related.length > 0 && <section aria-label="Often mentioned with"><h3>Often mentioned with</h3><p className="entity-chips">{detail.related.map((other) => <button key={other.id} type="button" className="entity-chip" onClick={() => onSelect(other.id)}>{other.name}<small>{other.item_count} shared</small></button>)}</p></section>}
        <form className="revision-form" onSubmit={save}>
          <div className="form-field"><label htmlFor="entity-edit-name">Name</label><input id="entity-edit-name" value={name} onChange={(event) => setName(event.target.value)} minLength={2} maxLength={80} required /></div>
          <div className="form-field"><label htmlFor="entity-edit-aliases">Also known as</label><input id="entity-edit-aliases" value={aliases} onChange={(event) => setAliases(event.target.value)} placeholder="Comma separated" /></div>
          <button className="primary-button" type="submit" disabled={busy}>Save</button>
        </form>
        {others.length > 1 && (
          <div className="revision-form">
            <div className="form-field"><label htmlFor="entity-merge">Same as another entry?</label><select id="entity-merge" value={mergeInto} onChange={(event) => setMergeInto(event.target.value)}><option value="">Choose one to merge into</option>{others.filter((other) => other.id !== detail.id).map((other) => <option key={other.id} value={other.id}>{other.name} ({other.kind})</option>)}</select></div>
            <button className="secondary-button" type="button" disabled={busy || !mergeInto} onClick={merge}>Merge into it</button>
          </div>
        )}
      </div>
    </Detail>
  );
}
