import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from companyos.events import queue_realtime, record_activity
from companyos.models import Agent, Artifact, ArtifactVersion
from companyos.models.enums import ActorType
from companyos.providers.storage import get_storage

PREVIEW_CHARS = 600
TEXT_MIME_PREFIXES = ("text/", "application/json")


def storage_key(organization_id: uuid.UUID, artifact_id: uuid.UUID, version: int, filename: str) -> str:
    return f"org/{organization_id}/artifacts/{artifact_id}/v{version}/{filename}"


async def save_artifact(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    title: str,
    filename: str,
    content: bytes,
    mime_type: str,
    kind: str = "document",
    objective_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    generated_by_mock: bool = False,
    change_note: str = "",
) -> tuple[Artifact, ArtifactVersion]:
    # Same task + filename means a new version of the same artifact
    artifact = None
    if task_id is not None:
        artifact = await session.scalar(
            select(Artifact).where(
                Artifact.organization_id == organization_id,
                Artifact.task_id == task_id,
                Artifact.filename == filename,
            )
        )
    if artifact is None:
        artifact = Artifact(
            organization_id=organization_id,
            objective_id=objective_id,
            project_id=project_id,
            task_id=task_id,
            agent_id=agent_id,
            title=title,
            filename=filename,
            kind=kind,
            mime_type=mime_type,
            current_version=0,
            generated_by_mock=generated_by_mock,
        )
        session.add(artifact)
        await session.flush()
    version_number = artifact.current_version + 1
    key = storage_key(organization_id, artifact.id, version_number, filename)
    await get_storage().put(key, content, mime_type)
    preview = content[: PREVIEW_CHARS * 2].decode("utf-8", errors="ignore")[:PREVIEW_CHARS]
    version = ArtifactVersion(
        organization_id=organization_id,
        artifact_id=artifact.id,
        version=version_number,
        storage_key=key,
        size_bytes=len(content),
        checksum_sha256=hashlib.sha256(content).hexdigest(),
        preview_text=preview if mime_type.startswith(TEXT_MIME_PREFIXES) else "",
        change_note=change_note,
        created_by_agent_id=agent_id,
        created_by_user_id=user_id,
    )
    session.add(version)
    artifact.current_version = version_number
    artifact.title = title
    await session.flush()

    agent_name = None
    if agent_id:
        agent = await session.get(Agent, agent_id)
        agent_name = agent.name if agent else None
    verb = "created" if version_number == 1 else f"revised (v{version_number})"
    await record_activity(
        session,
        organization_id=organization_id,
        event_type="artifact.created" if version_number == 1 else "artifact.revised",
        summary=f"{agent_name or 'CEO'} {verb} {title}",
        objective_id=objective_id,
        agent_id=agent_id,
        task_id=task_id,
        actor_type=ActorType.AGENT if agent_id else ActorType.USER,
        actor_user_id=user_id,
        data={"artifact_id": str(artifact.id), "version": version_number},
    )
    queue_realtime(session, organization_id, "artifact", {"artifact_id": str(artifact.id)})
    return artifact, version


async def get_version(
    session: AsyncSession, artifact: Artifact, version: int | None = None
) -> ArtifactVersion:
    number = version or artifact.current_version
    row = await session.scalar(
        select(ArtifactVersion).where(
            ArtifactVersion.artifact_id == artifact.id,
            ArtifactVersion.organization_id == artifact.organization_id,
            ArtifactVersion.version == number,
        )
    )
    if row is None:
        raise LookupError("Artifact version not found")
    return row


async def read_bytes(session: AsyncSession, artifact: Artifact, version: int | None = None) -> bytes:
    row = await get_version(session, artifact, version)
    return await get_storage().get(row.storage_key)


async def read_text(session: AsyncSession, artifact: Artifact, version: int | None = None) -> str:
    return (await read_bytes(session, artifact, version)).decode("utf-8", errors="replace")
