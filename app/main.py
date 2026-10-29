"""Application factory and ASGI entrypoint."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.api.routes_health import router as health_router
from app.config import get_settings
from app.errors import AppError
from app.logging_setup import request_id_ctx, setup_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.log_level)
    app.state.embedding_provider = None
    app.state.embedding_load_ms = None
    logger.info("app_start env=%s", settings.app_env)

    if settings.embedding_enabled_at_startup:
        from app.embeddings.fastembed_provider import FastEmbedProvider

        t0 = time.perf_counter()
        provider = FastEmbedProvider(model_name=settings.embedding_model)
        # Force one forward pass so ORT allocates working buffers at startup.
        _ = provider.embed_query("startup warmup")
        load_ms = (time.perf_counter() - t0) * 1000
        app.state.embedding_provider = provider
        app.state.embedding_load_ms = round(load_ms, 2)
        logger.info(
            "embedding_loaded model=%s load_ms=%.2f",
            settings.embedding_model,
            load_ms,
        )

    yield
    logger.info("app_stop")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.include_router(health_router)

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next: Callable[..., object]) -> Response:
        rid = request.headers.get("x-request-id", str(uuid.uuid4()))
        token = request_id_ctx.set(rid)
        try:
            response = await call_next(request)  # type: ignore[misc]
            assert isinstance(response, Response)
            response.headers["x-request-id"] = rid
            return response
        finally:
            request_id_ctx.reset(token)

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    return app


app = create_app()


def run() -> None:
    """CLI entry used by `aie-serve` / Docker CMD."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
