import type { EntityChip, EntityKind, EntityRef } from "./api";

export const ENTITY_KINDS: EntityKind[] = ["person", "company", "project", "topic"];

export const KIND_LABEL: Record<EntityKind, string> = {
  person: "People",
  company: "Companies",
  project: "Projects",
  topic: "Topics",
};

/** "Dana Lee (person), Acme (company)" — the editable text form of a proposal's entities. */
export function formatEntityText(chips: EntityChip[] | undefined): string {
  return (chips ?? []).map((chip) => (chip.kind && chip.kind !== "topic" ? `${chip.name} (${chip.kind})` : chip.name)).join(", ");
}

/** Parses the text form back. A name with no "(kind)" is a topic; unknown kinds become topics. */
export function parseEntityText(text: string): EntityRef[] {
  const seen = new Set<string>();
  const refs: EntityRef[] = [];
  for (const part of text.split(",")) {
    const match = part.trim().match(/^(.*?)\s*(?:\(([^)]*)\))?$/);
    const name = (match?.[1] ?? "").trim();
    const kind = (match?.[2] ?? "").trim().toLowerCase() as EntityKind;
    const key = name.toLowerCase();
    if (name.length < 2 || seen.has(key)) continue;
    seen.add(key);
    refs.push({ name, kind: ENTITY_KINDS.includes(kind) ? kind : "topic" });
  }
  return refs.slice(0, 12);
}
