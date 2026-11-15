"""BMF list of fake companies (Scheinunternehmen, § 8 SBBG) - S4.3.

There is no query API, so the list is imported into our database (app/bmf/importer.py)
and this adapter compares a partner with the local copy (T4.3.3):

- same VAT number (UID or Kennziffer des UR) or Firmenbuch number  -> FINDING
- only the same company name (normalised, app/bmf/names.py)        -> REVIEW
  ("possible match - please review", never OK)
- nothing                                                          -> OK
- list never imported                                              -> ERROR

Every result says how current the list was (data_as_of = time of the last successful
import). If the list is older than 24 hours, the explanation carries a warning (T4.3.4).
Details: docs/bmf.md
"""

import contextlib
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from sqlalchemy import func, or_, select
from fastapi import Depends
from sqlalchemy.orm import Session

from app.adapters.base import (
    CheckStatus,
    CheckSubject,
    Interpretation,
    Scenario,
    SourceAdapter,
)
from app.adapters.fake import with_fake_from_env
from app.bmf.importer import import_status
from app.bmf.names import normalize_name
from app.db.models import BmfListEntry
from app.db.session import SessionLocal, get_db

SOURCE = "BMF"
MAX_LIST_AGE = timedelta(hours=24)

MATCH_VAT_NUMBER = "VAT_NUMBER"
MATCH_REGISTER_NUMBER = "REGISTER_NUMBER"
MATCH_NAME = "NAME"
_IDENTIFIER_MATCHES = (MATCH_VAT_NUMBER, MATCH_REGISTER_NUMBER)
# More than this many name matches would only be noise; the count is kept.
MAX_LISTED_MATCHES = 5


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value else None


def _entry(entry: BmfListEntry) -> dict[str, Any]:
    """What the result stores about a list entry (evidence, shown to people)."""
    return {
        "name": entry.name,
        "address": entry.address,
        "vatNumber": entry.vat_number,
        "urNumber": entry.ur_number,
        "registerNumber": entry.register_number,
        "birthDate": _iso(entry.birth_date),
        "publishedOn": _iso(entry.published_on),
        "fakeSince": _iso(entry.fake_since),
        "decisionFinalOn": _iso(entry.decision_final_on),
        "link": entry.link,
    }


class BmfAdapter(SourceAdapter):
    source = SOURCE

    def __init__(
        self,
        session_factory: Callable[[], AbstractContextManager[Session]] = SessionLocal,
        **options: Any,
    ) -> None:
        super().__init__(**options)
        self._session_factory = session_factory

    def query(self, subject: CheckSubject, timeout: float) -> dict[str, Any]:
        """Compare the partner with the local copy of the BMF list (no network)."""
        with self._session_factory() as db:
            current = import_status(db)
            checked = {
                "vatNumber": subject.vat_number,
                "registerNumber": subject.register_number,
                "name": subject.name,
            }
            answer: dict[str, Any] = {
                "checked": checked,
                "checkedAt": self._now().isoformat(),
                "listImportedAt": _iso(
                    current.last_success.finished_at if current.last_success else None
                ),
                "entriesOnList": current.active_entries,
                "match": None,
                "matches": [],
            }
            if current.last_success is None:
                return answer

            match, entries, total = self._find(db, subject)
            answer.update(
                match=match,
                matches=[_entry(e) for e in entries[:MAX_LISTED_MATCHES]],
                matchCount=total,
            )
            return answer

    def _find(
        self, db: Session, subject: CheckSubject
    ) -> tuple[str | None, list[BmfListEntry], int]:
        active = BmfListEntry.removed_at.is_(None)
        order = (BmfListEntry.published_on.desc(), BmfListEntry.id)

        if subject.vat_number:
            by_vat = db.scalars(
                select(BmfListEntry)
                .where(
                    active,
                    or_(
                        BmfListEntry.vat_number == subject.vat_number,
                        BmfListEntry.ur_number == subject.vat_number,
                    ),
                )
                .order_by(*order)
            ).all()
            if by_vat:
                return MATCH_VAT_NUMBER, list(by_vat), len(by_vat)

        if subject.register_number:
            by_register = db.scalars(
                select(BmfListEntry)
                .where(active, BmfListEntry.register_number == subject.register_number)
                .order_by(*order)
            ).all()
            if by_register:
                return MATCH_REGISTER_NUMBER, list(by_register), len(by_register)

        name = normalize_name(subject.name) if subject.name else ""
        if name:
            condition = (active, BmfListEntry.normalized_name == name)
            total = (
                db.scalar(
                    select(func.count()).select_from(BmfListEntry).where(*condition)
                )
                or 0
            )
            if total:
                by_name = db.scalars(
                    select(BmfListEntry)
                    .where(*condition)
                    .order_by(*order)
                    .limit(MAX_LISTED_MATCHES)
                ).all()
                return MATCH_NAME, list(by_name), total
        return None, [], 0

    def interpret(self, raw: dict[str, Any]) -> Interpretation:
        if not raw.get("listImportedAt") or "match" not in raw:
            return Interpretation(CheckStatus.ERROR)
        match = raw.get("match")
        if match in _IDENTIFIER_MATCHES and raw.get("matches"):
            return Interpretation(CheckStatus.FINDING)
        if match == MATCH_NAME and raw.get("matches"):
            return Interpretation(CheckStatus.REVIEW)
        if match is None:
            return Interpretation(CheckStatus.OK)
        return Interpretation(CheckStatus.ERROR)

    def describe(self, status: CheckStatus, raw: dict[str, Any]) -> str:
        return describe(status, raw)

    def data_as_of(self, raw: dict[str, Any]) -> datetime | None:
        return _datetime(raw.get("listImportedAt"))

    def sample_answer(
        self, scenario: Scenario, subject: CheckSubject
    ) -> dict[str, Any]:
        now = self._now()
        answer: dict[str, Any] = {
            "checked": {
                "vatNumber": subject.vat_number,
                "registerNumber": None,
                "name": None,
            },
            "checkedAt": now.isoformat(),
            "listImportedAt": (now - timedelta(hours=1)).isoformat(),
            "entriesOnList": 1708,
            "match": None,
            "matches": [],
            "matchCount": 0,
        }
        if scenario == Scenario.FINDING:
            answer.update(
                match=MATCH_VAT_NUMBER,
                matchCount=1,
                matches=[
                    {
                        "name": "Muster Scheinbau GmbH (fake BMF entry)",
                        "address": "1010 Wien, Musterstraße 1",
                        "vatNumber": subject.vat_number,
                        "urNumber": subject.vat_number,
                        "registerNumber": "123456a",
                        "birthDate": None,
                        "publishedOn": (now.date() - timedelta(days=30)).isoformat(),
                        "fakeSince": (now.date() - timedelta(days=400)).isoformat(),
                        "decisionFinalOn": (
                            now.date() - timedelta(days=40)
                        ).isoformat(),
                        "link": None,
                    }
                ],
            )
        return answer


def _datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _day(value: Any) -> str | None:
    """'2026-11-09' -> '9 Nov 2026'."""
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value[:10])
    except ValueError:
        return None
    return f"{parsed.day} {parsed:%b %Y}"


def list_is_stale(raw: dict[str, Any]) -> bool:
    imported = _datetime(raw.get("listImportedAt"))
    checked = _datetime(raw.get("checkedAt"))
    if imported is None or checked is None:
        return False
    return checked - imported > MAX_LIST_AGE


def _stale_warning(raw: dict[str, Any]) -> str:
    if not list_is_stale(raw):
        return ""
    imported = _day(raw.get("listImportedAt"))
    return (
        f" Warning: the BMF list is older than 24 hours (last import {imported}), "
        "so the newest entries may be missing."
    )


def _compared(raw: dict[str, Any]) -> str:
    """Which details were compared, e.g. "Compared: VAT number and company name." """
    checked = raw.get("checked") or {}
    parts = [
        label
        for key, label in (
            ("vatNumber", "VAT number"),
            ("registerNumber", "company register number"),
            ("name", "company name"),
        )
        if checked.get(key)
    ]
    if len(parts) > 1:
        listed = ", ".join(parts[:-1]) + " and " + parts[-1]
    else:
        listed = parts[0] if parts else "nothing"
    text = f"Compared: {listed}."
    if not checked.get("name"):
        text += (
            " No company name is known yet, so names were not compared"
            " (run the VIES check first)."
        )
    return text


def describe(status: CheckStatus, raw: dict[str, Any]) -> str:
    """One sentence for people: what the result means and what to do."""
    matches = raw.get("matches") or []
    first = matches[0] if matches and isinstance(matches[0], dict) else {}
    name = first.get("name") or "an entry"
    published = _day(first.get("publishedOn"))
    since = f", published {published}" if published else ""

    if status == CheckStatus.FINDING:
        by = (
            "Firmenbuch number"
            if raw.get("match") == MATCH_REGISTER_NUMBER
            else "VAT number"
        )
        text = (
            f"This partner is on the BMF list of fake companies (Scheinunternehmen): "
            f"{name}{since}, same {by}."
        )
    elif status == CheckStatus.REVIEW:
        address = f" ({first['address']})" if first.get("address") else ""
        others = raw.get("matchCount", len(matches))
        more = (
            f" and {others - 1} more" if isinstance(others, int) and others > 1 else ""
        )
        text = (
            f"Possible match – please review: {name}{address}{more} is on the BMF list "
            f"with the same name, but not with this partner's numbers. "
            "Please check whether it is the same company."
        )
    elif status == CheckStatus.OK:
        text = (
            f"This partner is not on the BMF list of fake companies. {_compared(raw)}"
        )
    elif not raw.get("listImportedAt") and "match" in raw:
        return (
            "The BMF list has not been imported yet, so the partner could not be "
            "checked. The result was not confirmed."
        )
    else:
        text = "The BMF list could not be checked. The result was not confirmed."
    return text + _stale_warning(raw)


def get_bmf_adapter(db: Annotated[Session, Depends(get_db)]) -> SourceAdapter:
    """FastAPI dependency: reads the list with the request's database session.

    BMF_ADAPTER=fake-... uses a fake (app/adapters/fake.py).
    """
    return with_fake_from_env(BmfAdapter(lambda: contextlib.nullcontext(db)))
