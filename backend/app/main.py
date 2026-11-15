"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Build and configure a FastAPI application instance."""
    settings = get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Startup work (e.g. DB connections in Step 2) goes before `yield`.
        logger.info("Application startup", extra={"context": {"environment": settings.app_env}})
        yield
        # Shutdown/cleanup work goes after `yield`.
        logger.info("Application shutdown")

    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
    app.include_router(health_router)
    return app


app = create_app()
