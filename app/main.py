from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from app.api.routes.lesson import router as lesson_router
from app.api.routes.teacher import router as teacher_router
from app.api.routes.webhook import router as webhook_router
from app.core.config import get_settings
from app.core.logging import configure_logging, log_event
from app.db.base import Base
from app.db.session import engine
import app.models
from app.api.routes.library import router as library_router

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log_event(logger, "app_startup", reset_db_on_start=settings.reset_db_on_start)
    if settings.reset_db_on_start:
        log_event(logger, "database_reset_requested")
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    log_event(logger, "database_ready")
    yield
    log_event(logger, "app_shutdown")


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allow_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook_router)
app.include_router(teacher_router)
app.include_router(lesson_router)
app.include_router(library_router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    log_event(
        logger,
        "http_exception",
        path=str(request.url.path),
        status_code=exc.status_code,
        detail=exc.detail,
    )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log_event(logger, "unhandled_exception", path=str(request.url.path), error=str(exc))
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


@app.get("/health")
def health() -> dict[str, str]:
    log_event(logger, "health_check")
    return {"status": "ok"}
