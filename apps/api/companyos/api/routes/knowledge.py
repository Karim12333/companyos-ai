import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, UploadFile, status
from sqlalchemy import select

from companyos.api.deps import Org, OrgSession
from companyos.api.schemas import (
    DocumentCreate,
    DocumentOut,
    FeedbackOut,
    MemoryCreate,
    MemoryOut,
    PreferenceCreate,
    PreferenceOut,
    PromoteFeedback,
)
from companyos.config import get_settings
from companyos.events import record_activity
from companyos.models import AgentFeedback, CompanyMemory, Document, OrganizationPreference
from companyos.models.enums import ActorType, FeedbackStatus, MemoryCategory
from companyos.rbac import Permission
from companyos.services import knowledge as knowledge_service
from companyos.services.integrations import resolve_ai

router = APIRouter(prefix="/orgs/{org_id}/knowledge", tags=["knowledge"])

ALLOWED_UPLOAD_TYPES = {"text/plain", "text/markdown", "text/csv", "application/json"}
ALLOWED_UPLOAD_SUFFIXES = (".txt", ".md", ".markdown", ".csv", ".json")


# ---------- company memory ----------


@router.get("/memory", response_model=list[MemoryOut])
async def list_memory(org: Org, session: OrgSession) -> list[CompanyMemory]:
    query = select(CompanyMemory).where(CompanyMemory.organization_id == org.organization_id)
    return list(
        (await session.scalars(query.order_by(CompanyMemory.category, CompanyMemory.created_at))).all()
    )


@router.post("/memory", response_model=MemoryOut, status_code=status.HTTP_201_CREATED)
async def create_memory(body: MemoryCreate, org: Org, session: OrgSession) -> CompanyMemory:
    org.require(Permission.MANAGE_KNOWLEDGE)
    memory = CompanyMemory(
        organization_id=org.organization_id,
        category=MemoryCategory(body.category),
        title=body.title,
        content=body.content,
    )
    session.add(memory)
    await session.flush()
    return memory


@router.delete("/memory/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_memory(memory_id: uuid.UUID, org: Org, session: OrgSession) -> None:
    org.require(Permission.MANAGE_KNOWLEDGE)
    memory = await session.scalar(
        select(CompanyMemory).where(
            CompanyMemory.id == memory_id, CompanyMemory.organization_id == org.organization_id
        )
    )
    if memory is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Memory not found")
    memory.is_active = False


# ---------- documents ----------


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    org: Org, session: OrgSession, project_id: uuid.UUID | None = None
) -> list[Document]:
    query = select(Document).where(Document.organization_id == org.organization_id)
    if project_id:
        query = query.where(Document.project_id == project_id)
    return list((await session.scalars(query.order_by(Document.created_at.desc()))).all())


async def _store_document(
    org: Org,
    session: OrgSession,
    title: str,
    content: str,
    source: str,
    mime: str,
    project_id: uuid.UUID | None,
    trusted: bool,
) -> Document:
    document = Document(
        organization_id=org.organization_id,
        project_id=project_id,
        title=title,
        source=source,
        mime_type=mime,
        content=content,
        is_untrusted=not trusted,
        created_by_user_id=org.user.id,
    )
    session.add(document)
    await session.flush()
    ai = await resolve_ai(session, org.organization_id)
    await knowledge_service.index_document(session, document, ai.provider, ai.embedding_model)
    await record_activity(
        session,
        organization_id=org.organization_id,
        event_type="knowledge.document_added",
        summary=f"CEO added document: {title}",
        project_id=project_id,
        actor_type=ActorType.USER,
        actor_user_id=org.user.id,
    )
    return document


@router.post("/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def create_document(body: DocumentCreate, org: Org, session: OrgSession) -> Document:
    org.require(Permission.MANAGE_KNOWLEDGE)
    return await _store_document(
        org, session, body.title, body.content, "manual", "text/markdown", body.project_id, body.trusted
    )


@router.post("/documents/upload", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(file: UploadFile, org: Org, session: OrgSession) -> Document:
    org.require(Permission.MANAGE_KNOWLEDGE)
    filename = (file.filename or "document.txt")[:200]
    if not filename.lower().endswith(ALLOWED_UPLOAD_SUFFIXES):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only .txt, .md, .csv and .json files are supported"
        )
    data = await file.read(get_settings().max_upload_bytes + 1)
    if len(data) > get_settings().max_upload_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "File must be UTF-8 text") from error
    mime = file.content_type if file.content_type in ALLOWED_UPLOAD_TYPES else "text/plain"
    return await _store_document(org, session, filename, text, "upload", mime, None, trusted=False)


@router.get("/documents/{document_id}")
async def get_document(document_id: uuid.UUID, org: Org, session: OrgSession) -> dict[str, Any]:
    document = await session.scalar(
        select(Document).where(Document.id == document_id, Document.organization_id == org.organization_id)
    )
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return {**DocumentOut.model_validate(document).model_dump(mode="json"), "content": document.content}


@router.get("/search")
async def search_knowledge(
    org: Org, session: OrgSession, q: str = Query(min_length=2, max_length=500)
) -> dict[str, Any]:
    ai = await resolve_ai(session, org.organization_id)
    results = await knowledge_service.search(
        session,
        organization_id=org.organization_id,
        query=q,
        llm=ai.provider,
        embedding_model=ai.embedding_model,
    )
    return {
        "facts": [MemoryOut.model_validate(item).model_dump(mode="json") for item in results.facts],
        "chunks": [
            {
                "document_title": hit.document_title,
                "content": hit.content,
                "score": round(1 - hit.distance, 4),
            }
            for hit in results.chunks
        ],
    }


# ---------- feedback & preferences ----------


@router.get("/feedback", response_model=list[FeedbackOut])
async def list_feedback(org: Org, session: OrgSession) -> list[AgentFeedback]:
    query = select(AgentFeedback).where(AgentFeedback.organization_id == org.organization_id)
    return list((await session.scalars(query.order_by(AgentFeedback.created_at.desc()).limit(200))).all())


@router.post("/feedback/{feedback_id}/promote", response_model=PreferenceOut)
async def promote_feedback(
    feedback_id: uuid.UUID, body: PromoteFeedback, org: Org, session: OrgSession
) -> OrganizationPreference:
    org.require(Permission.MANAGE_KNOWLEDGE)
    feedback = await session.scalar(
        select(AgentFeedback).where(
            AgentFeedback.id == feedback_id, AgentFeedback.organization_id == org.organization_id
        )
    )
    if feedback is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Feedback not found")
    if body.scope == "agent" and feedback.agent_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Feedback is not linked to an agent")
    preference = OrganizationPreference(
        organization_id=org.organization_id,
        scope=body.scope,
        agent_id=feedback.agent_id if body.scope == "agent" else None,
        content=body.content or feedback.comment,
        source_feedback_id=feedback.id,
    )
    feedback.status = FeedbackStatus.PROMOTED
    session.add(preference)
    await record_activity(
        session,
        organization_id=org.organization_id,
        event_type="knowledge.preference_added",
        summary=f"CEO promoted feedback to a {body.scope} preference",
        agent_id=preference.agent_id,
        actor_type=ActorType.USER,
        actor_user_id=org.user.id,
    )
    await session.flush()
    return preference


@router.post("/feedback/{feedback_id}/dismiss", response_model=FeedbackOut)
async def dismiss_feedback(feedback_id: uuid.UUID, org: Org, session: OrgSession) -> AgentFeedback:
    feedback = await session.scalar(
        select(AgentFeedback).where(
            AgentFeedback.id == feedback_id, AgentFeedback.organization_id == org.organization_id
        )
    )
    if feedback is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Feedback not found")
    feedback.status = FeedbackStatus.DISMISSED
    return feedback


@router.get("/preferences", response_model=list[PreferenceOut])
async def list_preferences(org: Org, session: OrgSession) -> list[OrganizationPreference]:
    query = select(OrganizationPreference).where(
        OrganizationPreference.organization_id == org.organization_id
    )
    return list((await session.scalars(query.order_by(OrganizationPreference.created_at.desc()))).all())


@router.post("/preferences", response_model=PreferenceOut, status_code=status.HTTP_201_CREATED)
async def create_preference(body: PreferenceCreate, org: Org, session: OrgSession) -> OrganizationPreference:
    org.require(Permission.MANAGE_KNOWLEDGE)
    preference = OrganizationPreference(
        organization_id=org.organization_id,
        scope=body.scope,
        agent_id=body.agent_id if body.scope == "agent" else None,
        content=body.content,
    )
    session.add(preference)
    await session.flush()
    return preference


@router.post("/preferences/{preference_id}/toggle", response_model=PreferenceOut)
async def toggle_preference(
    preference_id: uuid.UUID, org: Org, session: OrgSession
) -> OrganizationPreference:
    org.require(Permission.MANAGE_KNOWLEDGE)
    preference = await session.scalar(
        select(OrganizationPreference).where(
            OrganizationPreference.id == preference_id,
            OrganizationPreference.organization_id == org.organization_id,
        )
    )
    if preference is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Preference not found")
    preference.is_active = not preference.is_active
    return preference
