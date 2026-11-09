import contextlib
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.adapters import vies
from app.adapters.fake import check_adapter_settings
from app.auth import AuthenticatedUser, get_current_user
from app.errors import error_body
from app.partners.router import router as partners_router
from app.security.background import security_event_sync
from app.security.router import router as security_router

# Every external source; their {SOURCE}_ADAPTER settings are checked at startup.
SOURCES = (vies.SOURCE,)


@contextlib.asynccontextmanager
async def lifespan(app_: FastAPI) -> AsyncIterator[None]:
    # Stops the start on a wrong {SOURCE}_ADAPTER value instead of failing every check.
    check_adapter_settings(SOURCES)
    async with security_event_sync(app_):
        yield


app = FastAPI(title="BizPartnerCheck API", version="0.1.0", lifespan=lifespan)

REQUEST_PARTS = {"body", "path", "query", "header", "cookie"}
API_PREFIX = "/api/v1"


@app.middleware("http")
async def require_bearer_token(request: Request, call_next):
    """No token, no API: 401 before routing, so unknown paths, wrong methods and broken
    request bodies reveal nothing to callers who are not signed in.
    The token itself is checked by get_current_user on every route."""
    path = request.url.path
    if (
        path == API_PREFIX or path.startswith(API_PREFIX + "/")
    ) and request.method != "OPTIONS":
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return JSONResponse(
                status_code=401,
                content=error_body("not_authenticated", "Please sign in."),
                headers={"WWW-Authenticate": "Bearer"},
            )
    return await call_next(request)


@app.exception_handler(StarletteHTTPException)
def http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """404, 405 and our own errors all use the uniform error format."""
    if isinstance(exc.detail, dict):
        content = {"detail": exc.detail}
    else:
        codes = {404: "not_found", 405: "method_not_allowed"}
        code = codes.get(exc.status_code, f"http_{exc.status_code}")
        content = error_body(code, str(exc.detail))
    return JSONResponse(
        status_code=exc.status_code, content=content, headers=exc.headers
    )


@app.exception_handler(RequestValidationError)
def invalid_request(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """Missing or wrongly typed fields use the same error format as all other errors."""
    first = exc.errors()[0] if exc.errors() else {}
    # loc looks like ("body", "vat_number") or ("path", "partner_id");
    # numbers are positions, not field names.
    location = [
        part
        for part in first.get("loc", ())
        if isinstance(part, str) and part not in REQUEST_PARTS
    ]
    field = ".".join(location) or None
    reason = first.get("msg", "Invalid request.")
    message = f"{field}: {reason}" if field else reason
    return JSONResponse(
        status_code=422, content=error_body("invalid_request", message, field)
    )


@app.exception_handler(OperationalError)
def database_unavailable(_request: Request, _exc: OperationalError) -> JSONResponse:
    """The database cannot be reached: answer quickly with a clear message."""
    return JSONResponse(
        status_code=503,
        content=error_body(
            "database_unavailable",
            "The database is not available. Please try again in a moment.",
        ),
    )


# Everything under /api/v1 needs a valid sign-in token (secure by default:
# new routers added here are protected automatically).
api = APIRouter(prefix="/api/v1", dependencies=[Depends(get_current_user)])
api.include_router(partners_router)
api.include_router(security_router)


@api.get("/me", tags=["account"])
def me(user: AuthenticatedUser) -> dict[str, str | None | list[str]]:
    """The signed-in user, as seen by the API (roles decide which pages the app shows)."""
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "roles": sorted(user.roles),
    }


app.include_router(api)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}
