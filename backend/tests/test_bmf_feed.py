"""Reading the BMF feed and normalising names (T4.3.1, T4.3.3). No internet needed."""

from datetime import date
from pathlib import Path

import pytest

from app.bmf.feed import (
    FeedError,
    normalize_register_number,
    normalize_vat,
    parse_feed,
)
from app.bmf.names import normalize_name

SAMPLE = Path(__file__).parent / "fixtures" / "bmf_feed_sample.xml"


@pytest.fixture(scope="module")
def feed():
    return parse_feed(SAMPLE.read_bytes())


def test_all_readable_entries_are_parsed(feed) -> None:
    assert len(feed.entries) == 6
    assert feed.skipped == 1  # the entry without publication date
    assert feed.last_build == "09 Nov 2026"


def test_company_entry(feed) -> None:
    entry = feed.entries[0]

    assert entry.name == "Muster Scheinbau GmbH"
    assert entry.address == "1100 Wien, Favoritenstraße 1"  # comma kept, umlaut decoded
    assert entry.published_on == date(2026, 11, 3)
    assert entry.fake_since == date(2025, 2, 1)
    assert entry.decision_final_on == date(2026, 10, 20)
    assert entry.register_number == "123456a"
    assert entry.vat_number == "ATU11111111"
    assert entry.ur_number == "ATU11111111"
    assert entry.birth_date is None
    assert entry.link and entry.link.startswith("https://service.bmf.gv.at/")


def test_individual_entry_without_identifiers(feed) -> None:
    entry = feed.entries[1]

    assert entry.name == "NOVÁK Péter"
    assert entry.birth_date == date(1971, 4, 22)
    assert entry.fake_since is None  # empty in the feed
    assert entry.vat_number is None
    assert entry.ur_number is None
    assert entry.register_number is None


def test_uid_suffix_is_removed(feed) -> None:
    assert feed.entries[2].vat_number == "ATU22222222"


def test_kennziffer_without_uid(feed) -> None:
    entry = feed.entries[5]

    assert entry.vat_number is None
    assert entry.ur_number == "ATU33333333"


def test_same_name_twice_gives_two_entries(feed) -> None:
    same = [e for e in feed.entries if e.name == "Glanz Reinigung OG"]

    assert len(same) == 2
    assert same[0].key != same[1].key


def test_key_is_stable(feed) -> None:
    again = parse_feed(SAMPLE.read_bytes())

    assert [e.key for e in again.entries] == [e.key for e in feed.entries]


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"<html><body>Wartungsarbeiten</body></html>",
        b"<rss><item/></rss>",
        b"<rss",
    ],
)
def test_unreadable_feed_is_an_error(content: bytes) -> None:
    with pytest.raises(FeedError):
        parse_feed(content)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ATU12345678", "ATU12345678"),
        ("atu 1234 5678", "ATU12345678"),
        ("ATU12345678-B", "ATU12345678"),
        ("", None),
        ("nicht bekannt", None),
    ],
)
def test_normalize_vat(value: str, expected: str | None) -> None:
    assert normalize_vat(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("342859f", "342859f"), ("FN 342859 F", "342859f"), ("12a", "12a"), ("abc", None)],
)
def test_normalize_register_number(value: str, expected: str | None) -> None:
    assert normalize_register_number(value) == expected


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("MUSTER BAU GMBH", "Muster Bau GmbH"),
        ("Muster-Bau Ges.m.b.H.", "Muster Bau GmbH"),
        ("Müller & Söhne KG", "MUELLER UND SOEHNE KG"),
        ("XY Bau GmbH & Co. KG", "XY Bau"),
        ("Novák s.r.o.", "NOVAK SRO"),
        ("Bau & Söhne Handels GmbH in Liquidation", "BAU UND SOEHNE HANDELS GMBH"),
        ("Bauer e.U.", "Bauer"),
    ],
)
def test_same_company_written_differently(first: str, second: str) -> None:
    assert normalize_name(first) == normalize_name(second)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Muster Bau GmbH", "Muster Bau Wien GmbH"),
        ("Muster Bau GmbH", "Muster Holz GmbH"),
        ("GmbH Holding", "Holding"),  # a legal form inside the name is kept
    ],
)
def test_different_companies_stay_different(first: str, second: str) -> None:
    assert normalize_name(first) != normalize_name(second)
