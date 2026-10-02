"""Knowledge graph over approved knowledge — nodes and edges.

Data model and edge semantics follow the Supermemory `memory-graph` contract
(`GraphApiDocument` / `GraphApiEdge`, edge types `document | updates | extends |
derives`) so a client can render the graph and, later, drop in their
force-directed engine. The derivation logic is **ported** from two Supermemory
sources rather than reinvented:

- `packages/memory-graph` `computeEdges` (edge-logic): document→memory edges
  (source→knowledge) then memory→memory relation edges from `memoryRelations`.
- `packages/lib/similarity.ts`: `cosineSimilarity` / `calculateSemanticSimilarity`
  for the semantic `derives` edges.

Open Brain mapping — nodes are Sources (documents) and approved Knowledge
(memories). Nothing here writes: the graph is a read-only view of canonical
truth, so the governed model is untouched.

- ``document``  : source → each of its approved knowledge (their doc→memory).
- ``extends``   : knowledge → knowledge sharing a source (sibling facts).
- ``derives``   : knowledge → knowledge with high semantic similarity.
- ``updates``   : reserved for cross-node supersession links (Open Brain keeps
  version history in ``KnowledgeRevision``, carried on the node's ``version``,
  so it is not emitted as a cross-node edge today).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import ReadScope
from .models import Knowledge, Source

log = logging.getLogger(__name__)

# A `derives` edge needs this much cosine similarity (0..1) between embeddings.
DERIVES_THRESHOLD = 0.35
# Guard the O(n²) pairwise pass on large brains.
MAX_NODES = 400


# --- similarity (ported from supermemory/packages/lib/similarity.ts) --------


def cosine_similarity(vector_a: list[float], vector_b: list[float]) -> float:
    """Dot product of two vectors. For L2-normalised embeddings this is cosine."""
    if len(vector_a) != len(vector_b):
        return 0.0
    return sum(a * b for a, b in zip(vector_a, vector_b, strict=True))


def calculate_semantic_similarity(
    emb_a: list[float] | None,
    emb_b: list[float] | None,
    relevance_score: float | None = None,
) -> float:
    """Similarity in [0, 1]; 1 is most similar. Ported from similarity.ts.

    Uses cosine when both embeddings exist, else falls back to a stored relevance
    score (0-100 → 0-1), else 0.
    """
    if emb_a and emb_b and len(emb_a) > 0 and len(emb_b) > 0:
        similarity = cosine_similarity(emb_a, emb_b)
        return similarity if similarity >= 0 else 0.0
    if relevance_score is not None:
        return max(0.0, min(1.0, relevance_score / 100.0))
    return 0.0


def _embedding(value: str | None) -> list[float] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except Exception:  # noqa: BLE001 — a corrupt embedding must not 500 a read
        return None
    return parsed if isinstance(parsed, list) else None


def _memory_relations(items: list[Knowledge]) -> dict[str, dict[str, str]]:
    """memoryRelations for every knowledge: {target_id: relationType}.

    `extends` links sibling facts from the same source. `derives` links
    semantically-similar facts (embedding cosine). `updates` links a supersession.
    Mirrors the memory-graph `memoryRelations: Record<targetId, relationType>`.
    """
    by_source: dict[str, list[Knowledge]] = {}
    for item in items:
        by_source.setdefault(item.source_id, []).append(item)

    embeddings = {item.id: _embedding(item.embedding) for item in items}
    relations: dict[str, dict[str, str]] = {item.id: {} for item in items}

    for item in items:
        # extends: siblings captured from the same source
        for sibling in by_source.get(item.source_id, []):
            if sibling.id != item.id:
                relations[item.id][sibling.id] = "extends"

    # derives: semantic similarity (pairwise, capped). Only when both embedded.
    embedded = [item for item in items if embeddings[item.id]]
    if 1 < len(embedded) <= MAX_NODES:
        for i, a in enumerate(embedded):
            for b in embedded[i + 1 :]:
                sim = calculate_semantic_similarity(embeddings[a.id], embeddings[b.id])
                if sim >= DERIVES_THRESHOLD:
                    relations[a.id][b.id] = "derives"
                    relations[b.id][a.id] = "derives"

    return relations


def build_graph(db: Session, scope: ReadScope, limit: int = MAX_NODES) -> dict[str, Any]:
    """Sources + approved knowledge as ``documents`` and their ``edges``.

    Read-only and scope-narrowed exactly like every other read. Returns the
    memory-graph shape: ``documents: GraphApiDocument[]`` and
    ``edges: GraphApiEdge[]``.
    """
    sources = {s.id: s for s in db.scalars(scope.apply(select(Source), Source)).all()}
    knowledge = list(
        db.scalars(
            scope.apply(
                select(Knowledge).where(Knowledge.status == "canonical"),
                Knowledge,
            )
        ).all()
    )[:limit]

    relations = _memory_relations(knowledge)

    by_source: dict[str, list[Knowledge]] = {}
    for item in knowledge:
        by_source.setdefault(item.source_id, []).append(item)

    documents: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for source_id, memories in by_source.items():
        source = sources.get(source_id)
        if source is None:
            continue
        graph_memories = []
        for item in memories:
            graph_memories.append(
                {
                    "id": item.id,
                    "memory": item.statement,
                    "content": item.rationale,
                    "isStatic": False,
                    "spaceId": item.workspace_id,
                    "isLatest": True,
                    "isForgotten": False,
                    "forgetAfter": None,
                    "forgetReason": None,
                    "version": item.version,
                    "parentMemoryId": None,
                    "rootMemoryId": item.id,
                    "createdAt": _iso(item.approved_at),
                    "updatedAt": _iso(item.approved_at),
                    "memoryRelations": relations.get(item.id, {}),
                }
            )
            # document→memory edge (their computeEdges step 1)
            edges.append({"source": source.id, "target": item.id, "edgeType": "document"})
        documents.append(
            {
                "id": source.id,
                "title": source.title,
                "summary": (source.content or "")[:240],
                "documentType": source.kind,
                "createdAt": _iso(source.created_at),
                "updatedAt": _iso(source.created_at),
                "memories": graph_memories,
            }
        )

    # memory→memory edges from memoryRelations (their computeEdges step 2).
    seen: set[frozenset[str]] = set()
    known_ids = {k.id for k in knowledge}
    for item in knowledge:
        for target, relation in relations.get(item.id, {}).items():
            if target not in known_ids:
                continue
            key = frozenset((item.id, target))
            if key in seen:
                continue
            seen.add(key)
            edges.append({"source": item.id, "target": target, "edgeType": relation})

    return {"documents": documents, "edges": edges}


def _iso(value) -> str:
    return value.isoformat() if value is not None else ""
