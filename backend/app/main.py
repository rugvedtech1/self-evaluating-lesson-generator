"""FastAPI application entry point."""

import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.api.auth import router as auth_router
from app.api.chats import router as chats_router
from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.exceptions import (
    InvalidOperationError, LLMConfigurationError, LLMResponseError, LLMUnavailableError, NotFoundError,
)
from app.core.logging import configure_logging
from app.workflows import runtime as workflow_runtime

logger = logging.getLogger(__name__)


def _handler(status_code: int):
    async def handle(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})
    return handle


def create_app() -> FastAPI:
    """Build and configure a FastAPI application instance."""
    settings = get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("Application startup", extra={"context": {"environment": settings.app_env}})
        if settings.recover_runs_on_startup:
            threading.Thread(target=workflow_runtime.recover_in_background,
                             name="lesson-run-recovery", daemon=True).start()
        yield
        workflow_runtime.shutdown()  # close the checkpointer connection pool
        logger.info("Application shutdown")

    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
    app.add_exception_handler(NotFoundError, _handler(status.HTTP_404_NOT_FOUND))
    app.add_exception_handler(InvalidOperationError, _handler(status.HTTP_409_CONFLICT))
    # LLM problems are technical failures (503/502), never content verdicts.
    app.add_exception_handler(LLMUnavailableError, _handler(status.HTTP_503_SERVICE_UNAVAILABLE))
    app.add_exception_handler(LLMConfigurationError, _handler(status.HTTP_503_SERVICE_UNAVAILABLE))
    app.add_exception_handler(LLMResponseError, _handler(status.HTTP_502_BAD_GATEWAY))
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(chats_router)
    return app


app = create_app()
