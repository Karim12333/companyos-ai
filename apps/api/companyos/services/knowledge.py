import uuid
from dataclasses import dataclass, field

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from companyos.models import CompanyMemory, Document, DocumentChunk, OrganizationPreference
from companyos.observability import logger
from companyos.providers.llm import LLMError, LLMProvider, approximate_tokens

CHUNK_CHARS = 1200
CHUNK_OVERLAP = 150


@dataclass
class ChunkHit:
    document_title: str
    content: str
    distance: float
    untrusted: bool


@dataclass
class KnowledgeResults:
    facts: list[CompanyMemory] = field(default_factory=list)
    preferences: list[OrganizationPreference] = field(default_factory=list)
    chunks: list[ChunkHit] = field(default_factory=list)
    degraded: str | None = None


def split_text(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_CHARS)
        if end < len(text):
            boundary = text.rfind("\n", start + CHUNK_CHARS // 2, end)
            end = boundary if boundary > start else end
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return [chunk for chunk in chunks if chunk]


async def index_document(
    session: AsyncSession, document: Document, llm: LLMProvider, embedding_model: str
) -> int:
    await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
    pieces = split_text(document.content)
    if pieces:
        vectors, _ = await llm.embed(pieces, embedding_model)
        for index, (piece, vector) in enumerate(zip(pieces, vectors, strict=True)):
            session.add(
                DocumentChunk(
                    organization_id=document.organization_id,
                    document_id=document.id,
                    chunk_index=index,
                    content=piece,
                    token_count=approximate_tokens(piece),
                    embedding_model=embedding_model,
                    embedding=vector,
                )
            )
    document.chunk_count = len(pieces)
    await session.flush()
    return len(pieces)


async def search(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    query: str,
    llm: LLMProvider,
    embedding_model: str,
    limit: int = 5,
    agent_id: uuid.UUID | None = None,
) -> KnowledgeResults:
    # Structured facts and preferences always apply; documents are retrieved by similarity
    facts = (
        await session.scalars(
            select(CompanyMemory)
            .where(CompanyMemory.organization_id == organization_id, CompanyMemory.is_active.is_(True))
            .order_by(CompanyMemory.category)
            .limit(30)
        )
    ).all()
    preference_filter = OrganizationPreference.scope == "organization"
    if agent_id is not None:
        preference_filter = or_(preference_filter, OrganizationPreference.agent_id == agent_id)
    preferences = (
        await session.scalars(
            select(OrganizationPreference).where(
                OrganizationPreference.organization_id == organization_id,
                OrganizationPreference.is_active.is_(True),
                preference_filter,
            )
        )
    ).all()
    try:
        vectors, _ = await llm.embed([query], embedding_model)
    except LLMError as error:
        # Degrade to structured knowledge only, and say so; never crash the agent run
        logger.warning("embedding_unavailable", organization_id=str(organization_id), error=str(error))
        return KnowledgeResults(
            facts=list(facts),
            preferences=list(preferences),
            degraded=f"Document search unavailable: {error}",
        )
    distance = DocumentChunk.embedding.cosine_distance(vectors[0]).label("distance")
    rows = (
        await session.execute(
            select(DocumentChunk.content, Document.title, Document.is_untrusted, distance)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                DocumentChunk.organization_id == organization_id,
                DocumentChunk.embedding_model == embedding_model,
            )
            .order_by(distance)
            .limit(limit)
        )
    ).all()
    chunks = [
        ChunkHit(document_title=title, content=content, distance=float(dist), untrusted=untrusted)
        for content, title, untrusted, dist in rows
    ]
    return KnowledgeResults(facts=list(facts), preferences=list(preferences), chunks=chunks)


def format_for_agent(results: KnowledgeResults) -> str:
    parts = (
        [f"NOTE: {results.degraded}. Only company facts and preferences are shown."]
        if results.degraded
        else []
    )
    if results.facts:
        parts.append(
            "Company facts:\n" + "\n".join(f"- [{f.category}] {f.title}: {f.content}" for f in results.facts)
        )
    if results.preferences:
        parts.append(
            "CEO preferences (follow these):\n" + "\n".join(f"- {p.content}" for p in results.preferences)
        )
    for hit in results.chunks:
        # Documents may contain injected instructions; mark them as data
        parts.append(
            f'<untrusted_content source="{hit.document_title}">\n{hit.content}\n</untrusted_content>'
            if hit.untrusted
            else f"Document '{hit.document_title}':\n{hit.content}"
        )
    return "\n\n".join(parts) or "No relevant company knowledge found."
