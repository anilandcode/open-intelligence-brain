"""People, companies, projects and topics that approved knowledge is about.

An entity is a name, not a statement, so it is not canon by itself. It gains
meaning only through links to approved knowledge, and those links are made by
the same human approval that makes the knowledge: intake suggests entity names
on the proposal (from the chat model, and by matching names the workspace
already knows), the reviewer edits them, and approval creates the links.

Visibility follows the knowledge. A caller sees an entity only when it is
linked to an approved item they may read, so a name that appears only in
private material never reaches a member. An entity with no links at all (one
someone created by hand, or whose items were all superseded) is visible only
to roles that may read everything in the workspace.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import delete, exists, func, select
from sqlalchemy.orm import Session

from .access import SENSITIVITY_RANK, ReadScope, WorkspaceAccess
from .models import Entity, Knowledge, KnowledgeEntity, new_id

ENTITY_KINDS = ("person", "company", "project", "topic")
MAX_ENTITIES_PER_ITEM = 12
_MIN_MATCH_CHARS = 3


@dataclass(frozen=True)
class EntityRef:
    """A suggested or chosen entity: a display name and a kind."""

    name: str
    kind: str


def entity_key(name: str) -> str:
    """The comparison form of a name: case, spacing and edge punctuation ignored."""
    text = re.sub(r"\s+", " ", name).strip().strip(".,;:!?\"'()[]").strip()
    return text.lower()


def clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", str(name)).strip().strip(".,;:!?\"'()[]").strip()


def clean_refs(raw: object) -> list[EntityRef]:
    """Entity suggestions from untrusted input (model output, JSON, a form).

    Accepts a JSON string, a list of {"name", "kind"} objects, or a list of
    names. Unknown kinds become "topic"; duplicates by key keep the first.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except ValueError:
            return []
    if not isinstance(raw, list):
        return []
    refs: list[EntityRef] = []
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, EntityRef):
            name, kind = item.name, item.kind
        elif isinstance(item, dict):
            name, kind = str(item.get("name", "")), str(item.get("kind", ""))
        elif isinstance(item, str):
            name, kind = item, "topic"
        else:
            continue
        name = clean_name(name)
        key = entity_key(name)
        if not 2 <= len(name) <= 80 or key in seen:
            continue
        kind = kind.strip().lower()
        refs.append(EntityRef(name=name, kind=kind if kind in ENTITY_KINDS else "topic"))
        seen.add(key)
        if len(refs) >= MAX_ENTITIES_PER_ITEM:
            break
    return refs


def refs_json(refs: list[EntityRef]) -> str:
    return json.dumps([{"name": ref.name, "kind": ref.kind} for ref in refs], ensure_ascii=False)


def parse_aliases(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except ValueError:
        return []
    return (
        [str(item) for item in parsed if isinstance(item, str)] if isinstance(parsed, list) else []
    )


def _clean_aliases(aliases: list[str], name: str) -> list[str]:
    out: list[str] = []
    seen = {entity_key(name)}
    for alias in aliases:
        alias = clean_name(alias)
        key = entity_key(alias)
        if 2 <= len(alias) <= 80 and key not in seen:
            out.append(alias)
            seen.add(key)
    return out[:20]


class EntityIndex:
    """The workspace's known entity names and aliases, for matching text."""

    def __init__(self, entities: list[Entity]) -> None:
        self.by_key: dict[str, Entity] = {}
        for entity in entities:
            self.by_key.setdefault(entity.key, entity)
        for entity in entities:
            for alias in parse_aliases(entity.aliases):
                self.by_key.setdefault(entity_key(alias), entity)
        names = sorted(
            (key for key in self.by_key if len(key) >= _MIN_MATCH_CHARS), key=len, reverse=True
        )
        self.pattern = (
            re.compile(r"(?<!\w)(" + "|".join(re.escape(key) for key in names) + r")(?!\w)", re.I)
            if names
            else None
        )

    @classmethod
    def load(cls, db: Session, workspace_id: str) -> EntityIndex:
        return cls(list(db.scalars(select(Entity).where(Entity.workspace_id == workspace_id))))

    def resolve(self, ref: EntityRef) -> EntityRef:
        """A known entity's own name and kind for a suggested name or alias."""
        entity = self.by_key.get(entity_key(ref.name))
        return EntityRef(entity.name, entity.kind) if entity else ref

    def mentions(self, text: str) -> list[EntityRef]:
        if self.pattern is None:
            return []
        found: list[EntityRef] = []
        for match in self.pattern.finditer(text):
            entity = self.by_key.get(entity_key(match.group(1)))
            if entity is not None:
                found.append(EntityRef(entity.name, entity.kind))
        return clean_refs(found)

    def suggest(self, statement: str, suggested: list[EntityRef]) -> list[EntityRef]:
        """Model suggestions mapped onto known names, plus known names mentioned."""
        return clean_refs([*(self.resolve(ref) for ref in suggested), *self.mentions(statement)])


# --- writes (only reached through approval or a reviewer's own action) --------


def _audit(db: Session, workspace_id: str, action: str, entity_id: str, detail: str, actor):
    from .services import audit  # avoid an import cycle

    audit(db, workspace_id, action, "entity", entity_id, detail, actor=actor)


def find_by_name(db: Session, workspace_id: str, name: str) -> Entity | None:
    key = entity_key(name)
    if not key:
        return None
    entity = db.scalar(select(Entity).where(Entity.workspace_id == workspace_id, Entity.key == key))
    if entity is not None:
        return entity
    # Aliases are a short JSON list, so match them in Python on a narrowed set.
    for candidate in db.scalars(
        select(Entity).where(
            Entity.workspace_id == workspace_id, Entity.aliases.ilike(f"%{name.strip()}%")
        )
    ):
        if key in {entity_key(alias) for alias in parse_aliases(candidate.aliases)}:
            return candidate
    return None


def ensure_entity(
    db: Session, workspace_id: str, ref: EntityRef, actor: WorkspaceAccess | None
) -> Entity:
    entity = find_by_name(db, workspace_id, ref.name)
    if entity is not None:
        return entity
    entity = Entity(
        id=new_id("ent"),
        workspace_id=workspace_id,
        kind=ref.kind,
        name=ref.name,
        key=entity_key(ref.name),
        aliases="[]",
    )
    db.add(entity)
    db.flush()
    _audit(db, workspace_id, "entity.created", entity.id, f"{ref.kind}: {ref.name}", actor)
    return entity


def link_entities(
    db: Session, item: Knowledge, refs: list[EntityRef], actor: WorkspaceAccess | None
) -> list[Entity]:
    """Link an approved item to these entities, creating names the workspace lacks."""
    linked: list[Entity] = []
    existing = set(
        db.scalars(select(KnowledgeEntity.entity_id).where(KnowledgeEntity.knowledge_id == item.id))
    )
    for ref in clean_refs(refs):
        entity = ensure_entity(db, item.workspace_id, ref, actor)
        if entity.id not in existing:
            db.add(KnowledgeEntity(knowledge_id=item.id, entity_id=entity.id))
            existing.add(entity.id)
        linked.append(entity)
    db.flush()
    return linked


def create_entity(
    db: Session,
    workspace_id: str,
    name: str,
    kind: str,
    aliases: list[str],
    *,
    link_existing: bool,
    actor: WorkspaceAccess | None,
) -> tuple[Entity, int]:
    """A reviewer adds a name by hand, optionally linking items that mention it."""
    refs = clean_refs([{"name": name, "kind": kind}])
    if not refs:
        raise ValueError("A name of 2 to 80 characters is required")
    clean_aliases = _clean_aliases(aliases, refs[0].name)
    for candidate in [refs[0].name, *clean_aliases]:
        if find_by_name(db, workspace_id, candidate) is not None:
            raise ValueError(f"{candidate} is already a name or alias in this workspace")
    entity = ensure_entity(db, workspace_id, refs[0], actor)
    entity.aliases = json.dumps(clean_aliases, ensure_ascii=False)
    linked = _link_mentions(db, entity) if link_existing else 0
    db.commit()
    db.refresh(entity)
    return entity, linked


def _link_mentions(db: Session, entity: Entity) -> int:
    index = EntityIndex([entity])
    if index.pattern is None:
        return 0
    already = set(
        db.scalars(
            select(KnowledgeEntity.knowledge_id).where(KnowledgeEntity.entity_id == entity.id)
        )
    )
    count = 0
    for item in db.scalars(
        select(Knowledge).where(
            Knowledge.workspace_id == entity.workspace_id, Knowledge.status == "canonical"
        )
    ):
        if item.id not in already and index.pattern.search(item.statement):
            db.add(KnowledgeEntity(knowledge_id=item.id, entity_id=entity.id))
            count += 1
    db.flush()
    return count


def update_entity(
    db: Session,
    entity: Entity,
    *,
    name: str | None,
    kind: str | None,
    aliases: list[str] | None,
    actor: WorkspaceAccess | None,
) -> Entity:
    changes: list[str] = []
    if name is not None:
        cleaned = clean_name(name)
        if not 2 <= len(cleaned) <= 80:
            raise ValueError("A name of 2 to 80 characters is required")
        other = find_by_name(db, entity.workspace_id, cleaned)
        if other is not None and other.id != entity.id:
            raise ValueError(f"{cleaned} is already used; merge the two instead")
        if cleaned != entity.name:
            # Keep the old name findable: notes written before the rename use it.
            old_aliases = parse_aliases(entity.aliases)
            entity.aliases = json.dumps(
                _clean_aliases([*old_aliases, entity.name], cleaned), ensure_ascii=False
            )
            changes.append(f"renamed {entity.name} to {cleaned}")
            entity.name = cleaned
            entity.key = entity_key(cleaned)
    if kind is not None:
        kind = kind.strip().lower()
        if kind not in ENTITY_KINDS:
            raise ValueError(f"Kind must be one of: {', '.join(ENTITY_KINDS)}")
        if kind != entity.kind:
            changes.append(f"kind {entity.kind} to {kind}")
            entity.kind = kind
    if aliases is not None:
        cleaned_aliases = _clean_aliases(aliases, entity.name)
        for alias in cleaned_aliases:
            other = find_by_name(db, entity.workspace_id, alias)
            if other is not None and other.id != entity.id:
                raise ValueError(f"{alias} already names another entity; merge them instead")
        entity.aliases = json.dumps(cleaned_aliases, ensure_ascii=False)
        changes.append("aliases updated")
    if changes:
        _audit(db, entity.workspace_id, "entity.updated", entity.id, "; ".join(changes), actor)
    db.commit()
    db.refresh(entity)
    return entity


def merge_entities(
    db: Session, duplicate: Entity, keep: Entity, actor: WorkspaceAccess | None
) -> Entity:
    """Fold `duplicate` into `keep`: links move, its names become aliases."""
    if duplicate.id == keep.id:
        raise ValueError("An entity cannot be merged into itself")
    if duplicate.workspace_id != keep.workspace_id:
        raise ValueError("Entities belong to different workspaces")
    kept_links = set(
        db.scalars(select(KnowledgeEntity.knowledge_id).where(KnowledgeEntity.entity_id == keep.id))
    )
    for link in db.scalars(
        select(KnowledgeEntity).where(KnowledgeEntity.entity_id == duplicate.id)
    ):
        if link.knowledge_id not in kept_links:
            db.add(KnowledgeEntity(knowledge_id=link.knowledge_id, entity_id=keep.id))
    db.execute(delete(KnowledgeEntity).where(KnowledgeEntity.entity_id == duplicate.id))
    keep.aliases = json.dumps(
        _clean_aliases(
            [*parse_aliases(keep.aliases), duplicate.name, *parse_aliases(duplicate.aliases)],
            keep.name,
        ),
        ensure_ascii=False,
    )
    _audit(
        db,
        keep.workspace_id,
        "entity.merged",
        keep.id,
        f"Merged {duplicate.name} ({duplicate.id}) into {keep.name}",
        actor,
    )
    db.delete(duplicate)
    db.commit()
    db.refresh(keep)
    return keep


# --- reads (always through a ReadScope) ---------------------------------------


def _readable_items(scope: ReadScope):
    return scope.apply(select(Knowledge.id).where(Knowledge.status == "canonical"), Knowledge)


def _sees_everything(scope: ReadScope) -> bool:
    return set(SENSITIVITY_RANK) <= scope.permitted


def visible_entity_ids(scope: ReadScope):
    """Subquery of the entity ids this scope may see (see module docstring)."""
    linked = select(KnowledgeEntity.entity_id).where(
        KnowledgeEntity.knowledge_id.in_(_readable_items(scope))
    )
    if not _sees_everything(scope):
        return linked
    unlinked = select(Entity.id).where(
        Entity.workspace_id == scope.workspace_id,
        ~exists().where(KnowledgeEntity.entity_id == Entity.id),
    )
    return linked.union(unlinked)


def readable_entity(db: Session, scope: ReadScope, entity_id: str) -> Entity | None:
    entity = db.get(Entity, entity_id)
    if entity is None or entity.workspace_id != scope.workspace_id:
        return None
    visible = db.scalar(
        select(Entity.id).where(Entity.id == entity_id, Entity.id.in_(visible_entity_ids(scope)))
    )
    return entity if visible else None


def find_readable(db: Session, scope: ReadScope, name: str) -> Entity | None:
    entity = find_by_name(db, scope.workspace_id, name)
    return readable_entity(db, scope, entity.id) if entity is not None else None


def item_counts(db: Session, scope: ReadScope, entity_ids: list[str]) -> Counter[str]:
    if not entity_ids:
        return Counter()
    rows = db.execute(
        select(KnowledgeEntity.entity_id, func.count())
        .where(
            KnowledgeEntity.entity_id.in_(entity_ids),
            KnowledgeEntity.knowledge_id.in_(_readable_items(scope)),
        )
        .group_by(KnowledgeEntity.entity_id)
    ).all()
    return Counter({entity_id: count for entity_id, count in rows})


def list_entities(
    db: Session, scope: ReadScope, *, kind: str | None = None, q: str = "", limit: int = 200
) -> list[tuple[Entity, int]]:
    stmt = select(Entity).where(
        Entity.workspace_id == scope.workspace_id, Entity.id.in_(visible_entity_ids(scope))
    )
    if kind:
        stmt = stmt.where(Entity.kind == kind)
    if q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(Entity.name.ilike(pattern) | Entity.aliases.ilike(pattern))
    entities = list(db.scalars(stmt))
    counts = item_counts(db, scope, [entity.id for entity in entities])
    ranked = sorted(entities, key=lambda entity: (-counts[entity.id], entity.name.lower()))
    return [(entity, counts[entity.id]) for entity in ranked[:limit]]


def entities_for_items(
    db: Session, scope: ReadScope, knowledge_ids: list[str]
) -> dict[str, list[Entity]]:
    """Visible entities per approved item, in name order."""
    if not knowledge_ids:
        return {}
    rows = db.execute(
        select(KnowledgeEntity.knowledge_id, Entity)
        .join(Entity, Entity.id == KnowledgeEntity.entity_id)
        .where(
            KnowledgeEntity.knowledge_id.in_(knowledge_ids),
            Entity.id.in_(visible_entity_ids(scope)),
        )
        .order_by(Entity.name)
    ).all()
    out: dict[str, list[Entity]] = {}
    for knowledge_id, entity in rows:
        out.setdefault(knowledge_id, []).append(entity)
    return out


def entity_items(
    db: Session, scope: ReadScope, entity_id: str, limit: int = 100
) -> list[Knowledge]:
    return list(
        db.scalars(
            scope.apply(
                select(Knowledge).where(
                    Knowledge.status == "canonical",
                    Knowledge.id.in_(
                        select(KnowledgeEntity.knowledge_id).where(
                            KnowledgeEntity.entity_id == entity_id
                        )
                    ),
                ),
                Knowledge,
            )
            .order_by(Knowledge.approved_at.desc())
            .limit(limit)
        )
    )


def co_mentioned(
    db: Session, scope: ReadScope, entity_id: str, item_ids: list[str], limit: int = 12
) -> list[tuple[Entity, int]]:
    """Other entities that share approved items with this one, most shared first."""
    if not item_ids:
        return []
    rows = db.execute(
        select(Entity, func.count())
        .join(KnowledgeEntity, KnowledgeEntity.entity_id == Entity.id)
        .where(
            KnowledgeEntity.knowledge_id.in_(item_ids),
            Entity.id != entity_id,
            Entity.id.in_(visible_entity_ids(scope)),
        )
        .group_by(Entity.id)
        .order_by(func.count().desc(), Entity.name)
        .limit(limit)
    ).all()
    return [(entity, count) for entity, count in rows]
