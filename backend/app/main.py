from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.errors import error_body
from app.partners.router import router as partners_router

app = FastAPI(title="BizPartnerCheck API", version="0.1.0")


@app.exception_handler(RequestValidationError)
def invalid_request(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """Missing or wrongly typed fields use the same error format as all other errors."""
    first = exc.errors()[0] if exc.errors() else {}
    # loc looks like ("body", "vat_number"); numbers are positions, not field names.
    location = [
        part
        for part in first.get("loc", ())
        if isinstance(part, str) and part != "body"
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


app.include_router(partners_router, prefix="/api/v1")


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}
