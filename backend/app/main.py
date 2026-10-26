import hashlib
import logging
import math
import mimetypes
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

from . import config, docstore, mailer
from .auth import bootstrap_admin_from_env
from .ollama_client import ai_server_configured
from .routers import ai, auth, boreholes, dashboard, export, records, reports, summaries, users, workflow, worksheets, erp_ops, erp_commercial
from .storage import AmbiguousReportError, SchemaMismatchError


logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
# Not in every system's MIME table (slim images); the PWA manifest needs the right type.
mimetypes.add_type("application/manifest+json", ".webmanifest")

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
    if docstore.ON_VERCEL and not docstore.USE_DATABASE:
        logging.getLogger(__name__).warning(
            "DATABASE_URL is not set: data is kept in %s and will be lost; add a Postgres database.",
            docstore.DATA_PATH,
        )
    bootstrap_admin_from_env()
    yield
    docstore.close_pool()


app = FastAPI(title="Soil Boring Ops API", lifespan=lifespan)


def _json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


@app.exception_handler(RequestValidationError)
async def _validation_error(_request: Request, exc: RequestValidationError):
    # Same answer as FastAPI's default, but NaN/Infinity in the echoed input become text
    # instead of crashing the JSON encoder (500).
    return JSONResponse(status_code=422, content={"detail": _json_safe(jsonable_encoder(exc.errors(), custom_encoder={float: _json_safe}))})


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


# Same policy as frontend/nginx.conf, used when this app also serves the built UI.
# The on-device AI (Geo AI "Qwen on this device") downloads its model from Hugging Face
# and its engine from jsDelivr, compiles WebAssembly and runs it in blob: workers.
_CSP = (
    "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self' blob:; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https://tile.openstreetmap.org; "
    "connect-src 'self' blob: https://huggingface.co https://*.huggingface.co https://*.hf.co "
    "https://cdn.jsdelivr.net; frame-ancestors 'none'; base-uri 'self'"
)


_API_DOC_PATHS = {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if path.startswith("/api/") or path == "/api":
        response.headers.setdefault("Cache-Control", "no-store")
    elif path.startswith("/assets/"):
        # Hashed build files never change.
        response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
    elif path not in _API_DOC_PATHS:
        # The web UI. (Swagger UI at /docs loads its files from a CDN, so it is skipped.)
        response.headers.setdefault("Cache-Control", "no-cache")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Content-Security-Policy", _CSP)
        # Cross-origin isolation lets the on-device AI use several CPU threads.
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Embedder-Policy", "require-corp")
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
app.include_router(export.router)
app.include_router(boreholes.router)
app.include_router(records.router)
app.include_router(worksheets.router)
app.include_router(workflow.router)
app.include_router(erp_ops.router)
app.include_router(erp_commercial.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/config")
def public_config():
    """Non-secret settings the UI needs before sign-in (shown on the login page)."""
    return {
        "org_name": config.ORG_NAME,
        "app_name": config.APP_NAME,
        "ai_server": ai_server_configured(),
        "email_reset": mailer.email_enabled(),
    }


# Single-service deployments (root Dockerfile, e.g. on Render) serve the built UI from
# FRONTEND_DIST; with docker-compose nginx serves it and FRONTEND_DIST stays unset.
# On Vercel the build command writes the UI to frontend/dist next to the backend.
_FRONTEND_ENV = os.environ.get("FRONTEND_DIST", "").strip()
if not _FRONTEND_ENV and docstore.ON_VERCEL:
    _FRONTEND_ENV = str(Path(__file__).resolve().parents[2] / "frontend" / "dist")
_FRONTEND: Optional[Path] = Path(_FRONTEND_ENV).resolve() if _FRONTEND_ENV else None

if _FRONTEND is not None and (_FRONTEND / "index.html").is_file():
    _UI_DIR: Path = _FRONTEND

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def frontend(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        try:
            candidate = (_UI_DIR / full_path).resolve()
            found = bool(full_path) and candidate.is_file() and _UI_DIR in candidate.parents
        except (ValueError, OSError):  # NUL bytes, over-long names ...
            found = False
        if found:
            return candidate_response(candidate)
        if full_path.startswith("assets/"):
            # A missing build file must not be answered with the app shell (and cached for a year).
            raise HTTPException(status_code=404, detail="Not Found")
        # Client-side routes all load the app shell.
        return candidate_response(_UI_DIR / "index.html")

    def candidate_response(path: Path):
        if _UI_DIR / "assets" in path.parents:
            return FileResponse(path)
        # index.html, sw.js, the manifest: their ETag must follow the content. FileResponse
        # derives it from mtime + size, and deployments reset mtimes, so a new release of the
        # same size was answered "not modified" and browsers kept the previous app.
        data = path.read_bytes()
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        etag = '"' + hashlib.sha256(data).hexdigest()[:32] + '"'
        return Response(content=data, media_type=media_type, headers={"ETag": etag})

else:

    @app.get("/")
    def root():
        return {"status": "ok", "service": "soilboring-ops"}
