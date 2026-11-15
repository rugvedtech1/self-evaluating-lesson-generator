"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.api.auth import router as auth_router
from app.api.chats import router as chats_router
from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.exceptions import InvalidOperationError, NotFoundError
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)


async def _not_found_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


async def _conflict_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


def create_app() -> FastAPI:
    """Build and configure a FastAPI application instance."""
    settings = get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("Application startup", extra={"context": {"environment": settings.app_env}})
        yield
        logger.info("Application shutdown")

    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
    app.add_exception_handler(NotFoundError, _not_found_handler)
    app.add_exception_handler(InvalidOperationError, _conflict_handler)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(chats_router)
    return app


app = create_app()
