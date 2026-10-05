import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment

from alembic import command
from companyos.config import get_settings
from companyos.db import dispose_engine
from companyos.events import close_redis, get_redis
from companyos.main import create_app
from companyos.providers.email import RecordingEmailProvider, set_email_override
from companyos.providers.storage import MemoryStorage, set_storage_override
from companyos.worker import build_worker
from companyos.workflows.client import set_temporal_client

TEST_ENV = {
    "DATABASE_URL": "postgresql+asyncpg://companyos_app:companyos_app_dev@localhost:5442/companyos_test",
    "MIGRATION_DATABASE_URL": "postgresql+asyncpg://companyos:companyos_dev@localhost:5442/companyos_test",
    "REDIS_URL": "redis://localhost:6379/15",
    "SECRET_KEY": "test-secret-key",
    "ENCRYPTION_KEYS": "Jq7sYd8vCw2h5m0ZqXGJ3fZ4tq0n7f3qk9QxR4m1bG8=",
    "SIGNUP_RATE_LIMIT_PER_MINUTE": "1000",
    "LOGIN_RATE_LIMIT_PER_MINUTE": "1000",
}
for key, value in TEST_ENV.items():
    os.environ.setdefault(key, value)
os.environ["TEMPORAL_TASK_QUEUE"] = f"companyos-test-{uuid.uuid4().hex[:8]}"
# Settings may have been read during import; reload them with the test environment
get_settings.cache_clear()

API_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def _reset_database() -> None:
    engine = create_async_engine(get_settings().migration_database_url)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
        await connection.execute(text("GRANT USAGE ON SCHEMA public TO companyos_app"))
    await engine.dispose()


def _migrate() -> None:
    config = Config(os.path.join(API_DIR, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(API_DIR, "alembic"))
    os.environ["MIGRATION_DATABASE_URL_OVERRIDE"] = get_settings().migration_database_url
    command.upgrade(config, "head")


@pytest.fixture(scope="session", autouse=True)
async def database() -> AsyncIterator[None]:
    await _reset_database()
    # Alembic runs its own event loop, so execute it in a worker thread
    await asyncio.to_thread(_migrate)
    await get_redis().flushdb()
    yield
    await close_redis()
    await dispose_engine()


@pytest.fixture(scope="session")
def storage() -> MemoryStorage:
    store = MemoryStorage()
    set_storage_override(store)
    return store


@pytest.fixture(scope="session")
def mailbox() -> RecordingEmailProvider:
    provider = RecordingEmailProvider()
    set_email_override(provider)
    return provider


@pytest.fixture(scope="session")
def app(storage: MemoryStorage, mailbox: RecordingEmailProvider) -> Any:
    return create_app()


@dataclass
class Tenant:
    client: httpx.AsyncClient
    org_id: str
    user_id: str
    csrf: str
    email: str

    @property
    def headers(self) -> dict[str, str]:
        return {"X-CSRF-Token": self.csrf}

    def url(self, path: str) -> str:
        return f"/api/v1/orgs/{self.org_id}{path}"


async def make_tenant(app: Any, organization: str = "Acme") -> Tenant:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
    email = f"ceo-{uuid.uuid4().hex[:8]}@example.com"
    response = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "password": "correct-horse-battery",
            "full_name": "Test CEO",
            "organization_name": organization,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return Tenant(
        client=client,
        org_id=body["organizations"][0]["id"],
        user_id=body["user"]["id"],
        csrf=body["csrf_token"],
        email=email,
    )


@pytest.fixture
async def tenant(app: Any) -> AsyncIterator[Tenant]:
    created = await make_tenant(app, "Acme Corp")
    yield created
    await created.client.aclose()


@pytest.fixture
async def other_tenant(app: Any) -> AsyncIterator[Tenant]:
    created = await make_tenant(app, "Globex")
    yield created
    await created.client.aclose()


@pytest.fixture(scope="session")
async def temporal() -> AsyncIterator[Client]:
    address = os.environ.get("TEST_TEMPORAL_ADDRESS")
    if address:
        client = await Client.connect(address)
        environment = None
    else:
        environment = await WorkflowEnvironment.start_local()
        client = environment.client
    set_temporal_client(client)
    worker = build_worker(client, get_settings().temporal_task_queue)
    async with worker:
        yield client
    set_temporal_client(None)
    if environment:
        await environment.shutdown()
