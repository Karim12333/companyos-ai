import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from companyos.api.routes import admin, auth, knowledge, objectives, organization, outputs, platform, projects
from companyos.config import get_settings
from companyos.db import dispose_engine
from companyos.events import close_redis
from companyos.observability import configure_logging, logger, report_exception
from companyos.providers.storage import get_storage


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.is_production)
    try:
        await get_storage().ensure_bucket()
    except Exception as error:
        logger.error("storage_unavailable", error=str(error))
    yield
    await close_redis()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="CompanyOS API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Correlation-Id"],
        expose_headers=["X-Correlation-Id"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        correlation_id = request.headers.get("X-Correlation-Id") or uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id, path=request.url.path)
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception as error:
            report_exception(error, correlation_id=correlation_id)
            raise
        response.headers["X-Correlation-Id"] = correlation_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if not request.url.path.endswith("/events/stream"):
            logger.info(
                "request",
                method=request.method,
                status=response.status_code,
                duration_ms=int((time.monotonic() - started) * 1000),
                user_id=getattr(request.state, "user_id", None),
            )
        return response

    prefix = "/api/v1"
    app.include_router(auth.router, prefix=prefix)
    app.include_router(auth.org_router, prefix=prefix)
    app.include_router(organization.router, prefix=prefix)
    app.include_router(objectives.router, prefix=prefix)
    app.include_router(outputs.router, prefix=prefix)
    app.include_router(projects.router, prefix=prefix)
    app.include_router(knowledge.router, prefix=prefix)
    app.include_router(admin.router, prefix=prefix)
    app.include_router(platform.router, prefix=prefix)
    app.include_router(platform.health_router)
    return app


app = create_app()
