import asyncio

from temporalio.worker import Worker

from companyos.config import get_settings
from companyos.observability import configure_logging, logger
from companyos.providers.storage import get_storage
from companyos.workflows.activities import ALL_ACTIVITIES
from companyos.workflows.client import get_temporal_client
from companyos.workflows.objective_workflow import ObjectiveWorkflow


def build_worker(client: object, task_queue: str) -> Worker:
    return Worker(
        client,  # type: ignore[arg-type]
        task_queue=task_queue,
        workflows=[ObjectiveWorkflow],
        activities=ALL_ACTIVITIES,
        max_concurrent_activities=20,
    )


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.is_production)
    await get_storage().ensure_bucket()
    client = await get_temporal_client()
    logger.info(
        "worker_starting", task_queue=settings.temporal_task_queue, temporal=settings.temporal_address
    )
    await build_worker(client, settings.temporal_task_queue).run()


if __name__ == "__main__":
    asyncio.run(main())
