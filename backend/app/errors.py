"""One error format for the whole API.

Every error response looks like this:

    {"detail": {"code": "duplicate_partner", "message": "...", "field": "vat_number"}}

- code: stable, for programs (e.g. an ERP) to react to
- message: for people, says what to fix
- field: the request field that is wrong (only when one field is the cause)
"""

from typing import Any

from fastapi import HTTPException


def error_body(code: str, message: str, field: str | None = None) -> dict[str, Any]:
    detail: dict[str, str] = {"code": code, "message": message}
    if field:
        detail["field"] = field
    return {"detail": detail}


def api_error(
    status_code: int, code: str, message: str, field: str | None = None
) -> HTTPException:
    return HTTPException(status_code, detail=error_body(code, message, field)["detail"])
