import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from companyos.models.base import Base, TenantMixin, str_enum
from companyos.models.enums import MemoryCategory

EMBEDDING_DIMENSIONS = 1536


class CompanyMemory(TenantMixin, Base):
    __tablename__ = "company_memory"

    category: Mapped[MemoryCategory] = mapped_column(str_enum(MemoryCategory))
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Document(TenantMixin, Base):
    __tablename__ = "documents"

    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    objective_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("objectives.id", ondelete="SET NULL"))
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("artifacts.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(64), default="upload")
    mime_type: Mapped[str] = mapped_column(String(120), default="text/plain")
    content: Mapped[str] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    is_untrusted: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class DocumentChunk(TenantMixin, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        Index(
            "ix_document_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding_model: Mapped[str] = mapped_column(String(120))
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))


class Evidence(TenantMixin, Base):
    """Provenance for important research claims: sourced facts vs assumptions vs conclusions."""

    __tablename__ = "evidence"

    objective_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("objectives.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("artifacts.id", ondelete="SET NULL"))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    ref: Mapped[str] = mapped_column(String(16), unique=True)
    kind: Mapped[str] = mapped_column(String(24))
    claim: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    source_title: Mapped[str | None] = mapped_column(String(300))
    excerpt: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[str] = mapped_column(String(8), default="medium")
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
