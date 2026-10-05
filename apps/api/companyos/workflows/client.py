from temporalio.client import Client

from companyos.config import get_settings

_client: Client | None = None


async def get_temporal_client() -> Client:
    global _client
    if _client is None:
        settings = get_settings()
        _client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    return _client


def set_temporal_client(client: Client | None) -> None:
    global _client
    _client = client
