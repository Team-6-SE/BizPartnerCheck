"""Read the BMF list of fake companies from its RSS feed.

    https://service.bmf.gv.at/service/allg/lsu/rss_lsu.asp

The feed holds the whole list (about 1,700 entries since 2016), ISO-8859-1 encoded.
The details of each entry sit as HTML inside <description>, for example:

    Anschrift: <strong>8731 Gaal, Puchschachen 50</strong>,   Veröffentlichung: <u>09.11.2026</u>,
    Zeitpunkt als Scheinunternehmen: 04.08.2025 ,   Rechtskraft Bescheid: 27.10.2026 ,
    <br />Firmenbuch-Nr: 342859f , <em>UID-NR:</em> ATU65643716, <em>Kennziffer des UR:</em> ATU65643716

Individuals have "Geb.Datum" (date of birth) and often no Firmenbuch number or UID.
Every field except name and publication date can be missing.
"""

import hashlib
import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime

from app.bmf.names import normalize_name
from app.partners.register import (
    normalize_register_number as _normalize_partner_register_number,
)

FEED_URL = "https://service.bmf.gv.at/service/allg/lsu/rss_lsu.asp"


class FeedError(ValueError):
    """The feed could not be read; the import must not change the stored list."""


@dataclass(frozen=True)
class FeedEntry:
    name: str
    address: str | None
    published_on: date
    fake_since: date | None
    decision_final_on: date | None
    birth_date: date | None
    register_number: str | None
    vat_number: str | None
    ur_number: str | None
    link: str | None

    @property
    def normalized_name(self) -> str:
        return normalize_name(self.name)

    @property
    def key(self) -> str:
        """Same entry in the next import -> same key (the name alone is not unique)."""
        parts = (
            self.name,
            self.address or "",
            self.published_on.isoformat(),
            self.birth_date.isoformat() if self.birth_date else "",
            self.register_number or "",
            self.vat_number or "",
        )
        return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def _date(text: str | None) -> date | None:
    if not text:
        return None
    try:
        return datetime.strptime(text.strip(), "%d.%m.%Y").date()
    except ValueError:
        return None


def _field(text: str, label: str) -> str | None:
    """Value after "label:" up to the next comma (HTML tags already removed)."""
    match = re.search(re.escape(label) + r":\s*([^,]*)", text)
    if not match:
        return None
    value = " ".join(match.group(1).split())
    return value or None


def normalize_vat(value: str | None) -> str | None:
    """'ATU 6953 9948-B' -> 'ATU69539948' (same form as partners.vat_number)."""
    if not value:
        return None
    compact = re.sub(r"\s", "", value).upper()
    match = re.match(r"[A-Z]{2}[A-Z0-9]{2,13}", compact)
    # Words such as "nicht bekannt" are not a number: a VAT number has digits.
    if not match or sum(c.isdigit() for c in match.group(0)) < 2:
        return None
    return match.group(0)


def normalize_register_number(value: str | None) -> str | None:
    """'FN 042859 f' -> '42859f': the same stored form as partners (app/partners/register.py)."""
    if not value:
        return None
    compact = _normalize_partner_register_number(value)
    return compact if re.fullmatch(r"[1-9]\d{0,5}[a-z]", compact, flags=re.ASCII) else None


def _address(description: str) -> str | None:
    """The address contains commas, so it is read from its own <strong> tag."""
    match = re.search(r"Anschrift:\s*<strong>(.*?)</strong>", description, re.S)
    if not match:
        return None
    return " ".join(html.unescape(match.group(1)).split()) or None


def parse_item(item: ET.Element) -> FeedEntry | None:
    name = " ".join((item.findtext("title") or "").split())
    description = item.findtext("description") or ""
    # Tags out, entities (&amp;) decoded: what is left reads "Label: value, Label: value".
    text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", description)).split())
    published_on = _date(_field(text, "Veröffentlichung"))
    if not name or published_on is None:
        return None
    return FeedEntry(
        name=name,
        address=_address(description) or _field(text, "Anschrift"),
        published_on=published_on,
        fake_since=_date(_field(text, "Zeitpunkt als Scheinunternehmen")),
        decision_final_on=_date(_field(text, "Rechtskraft Bescheid")),
        birth_date=_date(_field(text, "Geb.Datum")),
        register_number=normalize_register_number(_field(text, "Firmenbuch-Nr")),
        vat_number=normalize_vat(_field(text, "UID-NR")),
        ur_number=normalize_vat(_field(text, "Kennziffer des UR")),
        link=(item.findtext("link") or "").strip() or None,
    )


@dataclass(frozen=True)
class Feed:
    entries: list[FeedEntry]
    # Items we could not read (no name or no publication date); logged by the importer.
    skipped: int
    last_build: str | None


def parse_feed(content: bytes) -> Feed:
    """Parse the raw feed bytes (the XML declaration names the encoding)."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise FeedError(f"The BMF feed is not valid XML: {exc}") from exc
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise FeedError("The BMF feed has an unknown format (no RSS channel).")

    entries: list[FeedEntry] = []
    skipped = 0
    for item in channel.findall("item"):
        entry = parse_item(item)
        if entry is None:
            skipped += 1
        else:
            entries.append(entry)
    return Feed(entries, skipped, (channel.findtext("lastBuildDate") or "").strip() or None)
