import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from .auth import bootstrap_admin_from_env
from .routers import ai, auth, dashboard, reports, summaries, users
from .storage import AmbiguousReportError, SchemaMismatchError


logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

# Comma-separated list of browser origins allowed to call the API cross-origin.
# The Docker setup serves UI and API from one origin, so no CORS is needed there.
DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",")
    if origin.strip() and origin.strip() != "*"
]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    bootstrap_admin_from_env()
    yield


app = FastAPI(title="Soil Boring Ops API", lifespan=lifespan)


@app.exception_handler(SchemaMismatchError)
async def _schema_mismatch(_request: Request, exc: SchemaMismatchError):
    # Same answer on every endpoint that reads reports.csv (not a bare 500).
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(AmbiguousReportError)
async def _ambiguous_report(_request: Request, exc: AmbiguousReportError):
    return JSONResponse(
        status_code=409,
        content={
            "detail": f"Several logs match '{exc}' when ignoring upper/lower case; "
            "use the exact BoreholeID or fix reports.csv."
        },
    )

# Authentication uses bearer tokens (no cookies), so credentials are not needed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.middleware("http")
async def _dedupe_api_prefix(request: Request, call_next):
    # Some clients may still call /api/api/...; redirect them to the correct path.
    if request.url.path.startswith("/api/api/"):
        new_path = request.url.path.replace("/api/api", "/api", 1)
        if request.url.query:
            new_path = f"{new_path}?{request.url.query}"
        return RedirectResponse(new_path, status_code=307)
    return await call_next(request)


app.include_router(reports.router)
app.include_router(ai.router)
app.include_router(summaries.router)
app.include_router(dashboard.router)
app.include_router(auth.router)
app.include_router(users.router)


@app.get("/")
def root():
    return {"status": "ok", "service": "soilboring-ops"}


@app.get("/api/health")
def health():
    return {"status": "ok"}
