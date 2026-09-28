"""Intelligence Studio API — interview sessions and draft builder.

Interviews let an expert walk through a structured conversation. Each response
is captured as source material, and proposals are extracted for the same human
review every other source gets.

Drafts are assembled from approved knowledge atoms. Each section cites the
knowledge it draws on, so every claim in the output is traceable.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .access import AccessDenied, ReadScope, WorkspaceAccess, resolve_workspace
from .database import get_db
from .models import Knowledge, new_id
from .schemas import SourceCreate
from .services import audit, create_source_with_proposals
from .studio import (
    Draft,
    DraftCitation,
    DraftSection,
    InterviewQuestion,
    InterviewSession,
)
from .studio_schemas import (
    DraftAssembleRequest,
    DraftCitationRead,
    DraftCreate,
    DraftDetail,
    DraftRead,
    DraftSectionCreate,
    DraftSectionRead,
    DraftSectionUpdate,
    InterviewQuestionCreate,
    InterviewQuestionRead,
    InterviewResponseSubmit,
    InterviewSessionCreate,
    InterviewSessionDetail,
    InterviewSessionRead,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/studio", tags=["Studio"])


def _resolve_access(
    x_brain_token: str = Header(default=""),
    x_brain_workspace: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> WorkspaceAccess:
    try:
        return resolve_workspace(db, x_brain_token, x_brain_workspace)
    except AccessDenied as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def _read_scope(access: WorkspaceAccess = Depends(_resolve_access)) -> ReadScope:
    return ReadScope.of(access)


# --- Interview endpoints ---


@router.get("/interviews", response_model=list[InterviewSessionRead])
def list_interviews(
    access: WorkspaceAccess = Depends(_resolve_access),
    db: Session = Depends(get_db),
):
    """List interview sessions in the workspace."""
    sessions = list(
        db.scalars(
            select(InterviewSession)
            .where(InterviewSession.workspace_id == access.workspace_id)
            .order_by(InterviewSession.created_at.desc())
        ).all()
    )
    result = []
    for s in sessions:
        questions = list(
            db.scalars(select(InterviewQuestion).where(InterviewQuestion.session_id == s.id)).all()
        )
        result.append(
            InterviewSessionRead(
                id=s.id,
                workspace_id=s.workspace_id,
                title=s.title,
                topic=s.topic,
                person=s.person,
                audience=s.audience,
                outcome=s.outcome,
                status=s.status,
                source_id=s.source_id,
                created_at=s.created_at,
                completed_at=s.completed_at,
                question_count=len(questions),
                response_count=sum(1 for q in questions if q.response_text.strip()),
                extracted_count=sum(1 for q in questions if q.extracted),
            )
        )
    return result


@router.post("/interviews", response_model=InterviewSessionRead, status_code=201)
def create_interview(
    payload: InterviewSessionCreate,
    access: WorkspaceAccess = Depends(_resolve_access),
    db: Session = Depends(get_db),
):
    """Create a new interview session."""
    session = InterviewSession(
        id=new_id("intv"),
        workspace_id=access.workspace_id,
        title=payload.title,
        topic=payload.topic,
        person=payload.person,
        audience=payload.audience,
        outcome=payload.outcome,
    )
    db.add(session)
    audit(db, access.workspace_id, "interview.created", "interview", session.id, payload.title)
    db.commit()
    db.refresh(session)
    return InterviewSessionRead(
        id=session.id,
        workspace_id=session.workspace_id,
        title=session.title,
        topic=session.topic,
        person=session.person,
        audience=session.audience,
        outcome=session.outcome,
        status=session.status,
        source_id=session.source_id,
        created_at=session.created_at,
        completed_at=session.completed_at,
    )


@router.get("/interviews/{session_id}", response_model=InterviewSessionDetail)
def get_interview(
    session_id: str,
    access: WorkspaceAccess = Depends(_resolve_access),
    db: Session = Depends(get_db),
):
    """Get an interview session with all questions and responses."""
    session = db.get(InterviewSession, session_id)
    if session is None or session.workspace_id != access.workspace_id:
        raise HTTPException(status_code=404, detail="Interview not found")
    questions = list(
        db.scalars(
            select(InterviewQuestion)
            .where(InterviewQuestion.session_id == session_id)
            .order_by(InterviewQuestion.ordinal)
        ).all()
    )
    return InterviewSessionDetail(
        id=session.id,
        workspace_id=session.workspace_id,
        title=session.title,
        topic=session.topic,
        person=session.person,
        audience=session.audience,
        outcome=session.outcome,
        status=session.status,
        source_id=session.source_id,
        created_at=session.created_at,
        completed_at=session.completed_at,
        question_count=len(questions),
        response_count=sum(1 for q in questions if q.response_text.strip()),
        extracted_count=sum(1 for q in questions if q.extracted),
        questions=[InterviewQuestionRead.model_validate(q) for q in questions],
    )


@router.post(
    "/interviews/{session_id}/questions", response_model=InterviewQuestionRead, status_code=201
)
def add_question(
    session_id: str,
    payload: InterviewQuestionCreate,
    access: WorkspaceAccess = Depends(_resolve_access),
    db: Session = Depends(get_db),
):
    """Add a question to an interview session."""
    session = db.get(InterviewSession, session_id)
    if session is None or session.workspace_id != access.workspace_id:
        raise HTTPException(status_code=404, detail="Interview not found")
    if session.status == "completed":
        raise HTTPException(status_code=409, detail="Cannot add questions to a completed interview")
    max_ordinal = (
        db.scalar(
            select(func.max(InterviewQuestion.ordinal)).where(
                InterviewQuestion.session_id == session_id
            )
        )
        or 0
    )
    question = InterviewQuestion(
        id=new_id("iq"),
        session_id=session_id,
        ordinal=max_ordinal + 1,
        question_text=payload.question_text,
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    return InterviewQuestionRead.model_validate(question)


@router.post(
    "/interviews/{session_id}/questions/{question_id}/respond", response_model=InterviewQuestionRead
)
def submit_response(
    session_id: str,
    question_id: str,
    payload: InterviewResponseSubmit,
    access: WorkspaceAccess = Depends(_resolve_access),
    db: Session = Depends(get_db),
):
    """Submit a response to an interview question."""
    session = db.get(InterviewSession, session_id)
    if session is None or session.workspace_id != access.workspace_id:
        raise HTTPException(status_code=404, detail="Interview not found")
    question = db.get(InterviewQuestion, question_id)
    if question is None or question.session_id != session_id:
        raise HTTPException(status_code=404, detail="Question not found")
    question.response_text = payload.response_text
    db.commit()
    db.refresh(question)
    return InterviewQuestionRead.model_validate(question)


@router.post("/interviews/{session_id}/complete", response_model=InterviewSessionRead)
def complete_interview(
    session_id: str,
    access: WorkspaceAccess = Depends(_resolve_access),
    db: Session = Depends(get_db),
):
    """Complete an interview and extract proposals from all responses.

    Creates a source from the full interview transcript, then extracts
    proposals from each response. All proposals enter the normal review
    queue — nothing becomes canonical without human approval.
    """
    session = db.get(InterviewSession, session_id)
    if session is None or session.workspace_id != access.workspace_id:
        raise HTTPException(status_code=404, detail="Interview not found")
    if session.status == "completed":
        raise HTTPException(status_code=409, detail="Interview already completed")

    questions = list(
        db.scalars(
            select(InterviewQuestion)
            .where(InterviewQuestion.session_id == session_id)
            .order_by(InterviewQuestion.ordinal)
        ).all()
    )
    responded = [q for q in questions if q.response_text.strip()]
    if not responded:
        raise HTTPException(status_code=409, detail="No responses to extract from")

    # Build transcript as source content
    lines = [
        f"Interview: {session.title}",
        f"Person: {session.person}" if session.person else "",
        f"Topic: {session.topic}" if session.topic else "",
        f"Audience: {session.audience}" if session.audience else "",
        "",
    ]
    for q in responded:
        lines.append(f"Q: {q.question_text}")
        lines.append(f"A: {q.response_text}")
        lines.append("")
    transcript = "\n".join(line for line in lines if line is not None)

    # Create source from transcript
    source = create_source_with_proposals(
        db,
        SourceCreate(
            title=f"Interview: {session.title}",
            kind="interview",
            sensitivity="private",
            content=transcript,
        ),
        access.workspace_id,
    )
    session.source_id = source.id
    session.status = "completed"
    session.completed_at = datetime.now(UTC)

    # Mark all questions as extracted
    for q in responded:
        q.extracted = True

    audit(
        db,
        access.workspace_id,
        "interview.completed",
        "interview",
        session.id,
        f"Completed with {len(responded)} responses",
    )
    db.commit()
    db.refresh(session)
    return InterviewSessionRead(
        id=session.id,
        workspace_id=session.workspace_id,
        title=session.title,
        topic=session.topic,
        person=session.person,
        audience=session.audience,
        outcome=session.outcome,
        status=session.status,
        source_id=session.source_id,
        created_at=session.created_at,
        completed_at=session.completed_at,
        question_count=len(questions),
        response_count=len(responded),
        extracted_count=len(responded),
    )


# --- Draft endpoints ---


@router.get("/drafts", response_model=list[DraftRead])
def list_drafts(
    access: WorkspaceAccess = Depends(_resolve_access),
    db: Session = Depends(get_db),
):
    """List drafts in the workspace."""
    drafts = list(
        db.scalars(
            select(Draft)
            .where(Draft.workspace_id == access.workspace_id)
            .order_by(Draft.updated_at.desc())
        ).all()
    )
    result = []
    for d in drafts:
        sections = list(db.scalars(select(DraftSection).where(DraftSection.draft_id == d.id)).all())
        citations = 0
        for s in sections:
            citations += (
                db.scalar(
                    select(func.count(DraftCitation.id)).where(DraftCitation.section_id == s.id)
                )
                or 0
            )
        result.append(
            DraftRead(
                id=d.id,
                workspace_id=d.workspace_id,
                title=d.title,
                intent=d.intent,
                audience=d.audience,
                status=d.status,
                created_at=d.created_at,
                updated_at=d.updated_at,
                section_count=len(sections),
                citation_count=citations,
            )
        )
    return result


@router.post("/drafts", response_model=DraftRead, status_code=201)
def create_draft(
    payload: DraftCreate,
    access: WorkspaceAccess = Depends(_resolve_access),
    db: Session = Depends(get_db),
):
    """Create a new draft document."""
    draft = Draft(
        id=new_id("draft"),
        workspace_id=access.workspace_id,
        title=payload.title,
        intent=payload.intent,
        audience=payload.audience,
    )
    db.add(draft)
    audit(db, access.workspace_id, "draft.created", "draft", draft.id, payload.title)
    db.commit()
    db.refresh(draft)
    return DraftRead(
        id=draft.id,
        workspace_id=draft.workspace_id,
        title=draft.title,
        intent=draft.intent,
        audience=draft.audience,
        status=draft.status,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )


@router.get("/drafts/{draft_id}", response_model=DraftDetail)
def get_draft(
    draft_id: str,
    access: WorkspaceAccess = Depends(_resolve_access),
    db: Session = Depends(get_db),
):
    """Get a draft with all sections and citations."""
    draft = db.get(Draft, draft_id)
    if draft is None or draft.workspace_id != access.workspace_id:
        raise HTTPException(status_code=404, detail="Draft not found")
    sections = list(
        db.scalars(
            select(DraftSection)
            .where(DraftSection.draft_id == draft_id)
            .order_by(DraftSection.ordinal)
        ).all()
    )
    section_reads = []
    total_citations = 0
    for s in sections:
        citations = list(
            db.scalars(select(DraftCitation).where(DraftCitation.section_id == s.id)).all()
        )
        total_citations += len(citations)
        # Load knowledge items for each citation
        knowledge_items = []
        for c in citations:
            k = db.get(Knowledge, c.knowledge_id)
            if k:
                knowledge_items.append(
                    {
                        "id": k.id,
                        "statement": k.statement,
                        "type": k.type,
                        "source_excerpt": k.source_excerpt,
                    }
                )
        section_reads.append(
            DraftSectionRead(
                id=s.id,
                draft_id=s.draft_id,
                ordinal=s.ordinal,
                title=s.title,
                content=s.content,
                created_at=s.created_at,
                citations=[DraftCitationRead.model_validate(c) for c in citations],
                knowledge_items=knowledge_items,
            )
        )
    return DraftDetail(
        id=draft.id,
        workspace_id=draft.workspace_id,
        title=draft.title,
        intent=draft.intent,
        audience=draft.audience,
        status=draft.status,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
        section_count=len(sections),
        citation_count=total_citations,
        sections=section_reads,
    )


@router.post("/drafts/{draft_id}/sections", response_model=DraftSectionRead, status_code=201)
def add_section(
    draft_id: str,
    payload: DraftSectionCreate,
    access: WorkspaceAccess = Depends(_resolve_access),
    db: Session = Depends(get_db),
):
    """Add a section to a draft with optional knowledge citations."""
    draft = db.get(Draft, draft_id)
    if draft is None or draft.workspace_id != access.workspace_id:
        raise HTTPException(status_code=404, detail="Draft not found")
    max_ordinal = (
        db.scalar(select(func.max(DraftSection.ordinal)).where(DraftSection.draft_id == draft_id))
        or 0
    )
    section = DraftSection(
        id=new_id("dsec"),
        draft_id=draft_id,
        ordinal=max_ordinal + 1,
        title=payload.title,
        content=payload.content,
    )
    db.add(section)
    db.flush()

    # Add citations
    citations = []
    for kid in payload.knowledge_ids:
        k = db.get(Knowledge, kid)
        if k and k.workspace_id == access.workspace_id:
            citation = DraftCitation(
                id=new_id("dcit"),
                section_id=section.id,
                knowledge_id=kid,
            )
            db.add(citation)
            citations.append(citation)

    db.commit()
    db.refresh(section)
    return DraftSectionRead(
        id=section.id,
        draft_id=section.draft_id,
        ordinal=section.ordinal,
        title=section.title,
        content=section.content,
        created_at=section.created_at,
        citations=[DraftCitationRead.model_validate(c) for c in citations],
    )


@router.put("/drafts/{draft_id}/sections/{section_id}", response_model=DraftSectionRead)
def update_section(
    draft_id: str,
    section_id: str,
    payload: DraftSectionUpdate,
    access: WorkspaceAccess = Depends(_resolve_access),
    db: Session = Depends(get_db),
):
    """Update a draft section's content and citations."""
    draft = db.get(Draft, draft_id)
    if draft is None or draft.workspace_id != access.workspace_id:
        raise HTTPException(status_code=404, detail="Draft not found")
    section = db.get(DraftSection, section_id)
    if section is None or section.draft_id != draft_id:
        raise HTTPException(status_code=404, detail="Section not found")

    if payload.title is not None:
        section.title = payload.title
    if payload.content is not None:
        section.content = payload.content

    # Replace citations if provided
    if payload.knowledge_ids is not None:
        # Remove existing
        for old in db.scalars(
            select(DraftCitation).where(DraftCitation.section_id == section_id)
        ).all():
            db.delete(old)
        # Add new
        for kid in payload.knowledge_ids:
            k = db.get(Knowledge, kid)
            if k and k.workspace_id == access.workspace_id:
                db.add(DraftCitation(id=new_id("dcit"), section_id=section_id, knowledge_id=kid))

    db.commit()
    db.refresh(section)
    citations = list(
        db.scalars(select(DraftCitation).where(DraftCitation.section_id == section_id)).all()
    )
    knowledge_items = []
    for c in citations:
        k = db.get(Knowledge, c.knowledge_id)
        if k:
            knowledge_items.append({"id": k.id, "statement": k.statement, "type": k.type})
    return DraftSectionRead(
        id=section.id,
        draft_id=section.draft_id,
        ordinal=section.ordinal,
        title=section.title,
        content=section.content,
        created_at=section.created_at,
        citations=[DraftCitationRead.model_validate(c) for c in citations],
        knowledge_items=knowledge_items,
    )


@router.delete("/drafts/{draft_id}/sections/{section_id}", status_code=204)
def delete_section(
    draft_id: str,
    section_id: str,
    access: WorkspaceAccess = Depends(_resolve_access),
    db: Session = Depends(get_db),
):
    """Delete a draft section."""
    draft = db.get(Draft, draft_id)
    if draft is None or draft.workspace_id != access.workspace_id:
        raise HTTPException(status_code=404, detail="Draft not found")
    section = db.get(DraftSection, section_id)
    if section is None or section.draft_id != draft_id:
        raise HTTPException(status_code=404, detail="Section not found")
    # Delete citations first
    for c in db.scalars(select(DraftCitation).where(DraftCitation.section_id == section_id)).all():
        db.delete(c)
    db.delete(section)
    db.commit()


@router.post("/drafts/assemble", response_model=DraftDetail, status_code=201)
def assemble_draft(
    payload: DraftAssembleRequest,
    access: WorkspaceAccess = Depends(_resolve_access),
    db: Session = Depends(get_db),
):
    """Assemble a draft from approved knowledge atoms.

    Groups knowledge by type and creates one section per type. Each section
    lists the approved statements and optionally their source excerpts.
    """
    # Validate all knowledge IDs belong to this workspace
    items = []
    for kid in payload.knowledge_ids:
        k = db.get(Knowledge, kid)
        if k is None or k.workspace_id != access.workspace_id:
            raise HTTPException(status_code=404, detail=f"Knowledge item {kid} not found")
        if k.status != "canonical":
            raise HTTPException(status_code=409, detail=f"Item {kid} is not canonical")
        items.append(k)

    # Create draft
    draft = Draft(
        id=new_id("draft"),
        workspace_id=access.workspace_id,
        title=payload.title,
        intent=payload.intent,
        audience=payload.audience,
    )
    db.add(draft)
    db.flush()

    # Group by type
    by_type: dict[str, list[Knowledge]] = {}
    for item in items:
        by_type.setdefault(item.type, []).append(item)

    # Create one section per type
    for ordinal, (type_name, type_items) in enumerate(by_type.items(), start=1):
        lines = [f"## {type_name.title()}s", ""]
        for item in type_items:
            lines.append(f"- {item.statement}")
            if payload.include_excerpts and item.source_excerpt.strip():
                lines.append(f'  > "{item.source_excerpt.strip()}"')
            lines.append("")

        section = DraftSection(
            id=new_id("dsec"),
            draft_id=draft.id,
            ordinal=ordinal,
            title=f"{type_name.title()}s",
            content="\n".join(lines),
        )
        db.add(section)
        db.flush()

        # Add citations
        for item in items:
            if item.type == type_name:
                db.add(
                    DraftCitation(id=new_id("dcit"), section_id=section.id, knowledge_id=item.id)
                )

    audit(
        db,
        access.workspace_id,
        "draft.assembled",
        "draft",
        draft.id,
        f"Assembled {len(items)} atoms into {len(by_type)} sections",
    )
    db.commit()
    db.refresh(draft)

    # Return full detail
    sections = list(
        db.scalars(
            select(DraftSection)
            .where(DraftSection.draft_id == draft.id)
            .order_by(DraftSection.ordinal)
        ).all()
    )
    section_reads = []
    total_citations = 0
    for s in sections:
        citations = list(
            db.scalars(select(DraftCitation).where(DraftCitation.section_id == s.id)).all()
        )
        total_citations += len(citations)
        knowledge_items = []
        for c in citations:
            k = db.get(Knowledge, c.knowledge_id)
            if k:
                knowledge_items.append({"id": k.id, "statement": k.statement, "type": k.type})
        section_reads.append(
            DraftSectionRead(
                id=s.id,
                draft_id=s.draft_id,
                ordinal=s.ordinal,
                title=s.title,
                content=s.content,
                created_at=s.created_at,
                citations=[DraftCitationRead.model_validate(c) for c in citations],
                knowledge_items=knowledge_items,
            )
        )
    return DraftDetail(
        id=draft.id,
        workspace_id=draft.workspace_id,
        title=draft.title,
        intent=draft.intent,
        audience=draft.audience,
        status=draft.status,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
        section_count=len(sections),
        citation_count=total_citations,
        sections=section_reads,
    )
