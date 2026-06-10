from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

import pytest

from ingest import ingest_riksdag


LONG_TEXT = "Detta är fulltext från Riksdagen. " * 20


class FakeResponse:
    def __init__(
        self,
        url: str,
        status_code: int = 200,
        json_payload: Any | None = None,
        text: str = "",
        content_type: str = "application/json",
    ) -> None:
        self.url = url
        self.status_code = status_code
        self._json_payload = json_payload
        self.text = text
        self.headers = {"content-type": content_type}

    def json(self) -> Any:
        return self._json_payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses: dict[str, FakeResponse]) -> None:
        self.responses = responses
        self.headers: dict[str, str] = {}
        self.calls: list[str] = []

    def get(self, url: str, params: dict[str, str] | None = None, timeout: int | None = None) -> FakeResponse:
        full_url = url
        if params:
            query = "&".join(f"{key}={value}" for key, value in params.items())
            full_url = f"{url}?{query}"
        self.calls.append(full_url)
        response = self.responses.get(full_url) or self.responses.get(url)
        if response is None:
            return FakeResponse(full_url, status_code=404, text="Not found", content_type="text/plain")
        response.url = full_url
        return response


def test_normalize_riksdag_records_accepts_dokument_dict() -> None:
    payload = {"dokumentlista": {"dokument": {"dok_id": "H8011", "titel": "En träff"}}}

    assert ingest_riksdag.normalize_riksdag_records(payload) == [{"dok_id": "H8011", "titel": "En träff"}]


def test_normalize_riksdag_records_accepts_dokument_list() -> None:
    payload = {"dokumentstatus": {"dokument": [{"dok_id": "H8011"}, {"dok_id": "H8012"}]}}

    assert ingest_riksdag.normalize_riksdag_records(payload) == [{"dok_id": "H8011"}, {"dok_id": "H8012"}]


def test_fetch_document_text_uses_substantive_inline_text() -> None:
    session = FakeSession({})
    record = {"dok_id": "H8011", "anforandetext": LONG_TEXT}

    assert ingest_riksdag.fetch_document_text(record, session) == ingest_riksdag.clean_text(LONG_TEXT)
    assert session.calls == []


def test_fetch_document_text_fetches_txt_by_dok_id() -> None:
    session = FakeSession(
        {
            "https://data.riksdagen.se/dokument/H8011.txt": FakeResponse(
                "https://data.riksdagen.se/dokument/H8011.txt",
                text=LONG_TEXT,
                content_type="text/plain",
            )
        }
    )
    record = {"dok_id": "H8011", "titel": "Dokument utan inline-text"}

    assert ingest_riksdag.fetch_document_text(record, session) == ingest_riksdag.clean_text(LONG_TEXT)
    assert "https://data.riksdagen.se/dokument/H8011.txt" in session.calls


def test_fetch_document_text_extracts_escaped_html_from_xml_txt_response() -> None:
    embedded_html = f"<div><style>.x{{display:none}}</style><h1>Debatt</h1><p>{LONG_TEXT}</p></div>"
    xml = f"<dokumentstatus><dokument><html>{escape(embedded_html)}</html></dokument></dokumentstatus>"
    session = FakeSession(
        {
            "https://data.riksdagen.se/dokument/H8011.txt": FakeResponse(
                "https://data.riksdagen.se/dokument/H8011.txt",
                text=xml,
                content_type="text/xml",
            )
        }
    )

    text = ingest_riksdag.fetch_document_text({"dok_id": "H8011"}, session)

    assert text is not None
    assert text.startswith("Debatt")
    assert "Detta är fulltext från Riksdagen." in text
    assert "dokumentstatus" not in text
    assert "display:none" not in text


def test_fetch_riksdag_records_requests_speeches_not_replies() -> None:
    list_url = "https://data.riksdagen.se/anforandelista/?rm=2025/26&parti=S&anftyp=Nej&utformat=json"
    session = FakeSession(
        {
            list_url: FakeResponse(
                list_url,
                json_payload={
                    "anforandelista": {
                        "anforande": [
                            {"dok_id": "speech-1"},
                        ]
                    }
                },
            )
        }
    )

    records = ingest_riksdag.fetch_riksdag_records("S", "2025/26", limit=2, session=session)

    assert records == [{"dok_id": "speech-1"}]
    assert session.calls == [list_url]


def test_fetch_document_text_falls_back_to_html_when_txt_fails() -> None:
    html = f"<html><body><main><h1>Titel</h1><p>{LONG_TEXT}</p></main></body></html>"
    session = FakeSession(
        {
            "https://data.riksdagen.se/dokument/H8011.txt": FakeResponse(
                "https://data.riksdagen.se/dokument/H8011.txt",
                status_code=404,
                text="Not found",
                content_type="text/plain",
            ),
            "https://data.riksdagen.se/dokument/H8011.html": FakeResponse(
                "https://data.riksdagen.se/dokument/H8011.html",
                text=html,
                content_type="text/html",
            ),
        }
    )
    record = {"dok_id": "H8011", "titel": "HTML-dokument"}

    text = ingest_riksdag.fetch_document_text(record, session)

    assert text is not None
    assert "Titel" in text
    assert "Detta är fulltext från Riksdagen." in text


def test_ingest_riksdag_sources_raises_when_records_write_zero_documents(tmp_path: Path) -> None:
    list_url = "https://data.riksdagen.se/anforandelista/?rm=2025/26&parti=S&anftyp=Nej&utformat=json"
    session = FakeSession(
        {
            list_url: FakeResponse(
                list_url,
                json_payload={"dokumentlista": {"dokument": {"dok_id": "H8011", "titel": "Kort dokument"}}},
            )
        }
    )

    with pytest.raises(RuntimeError, match="wrote 0 documents"):
        ingest_riksdag.ingest_riksdag_sources("S", "2025/26", output_path=tmp_path / "riksdag.jsonl", session=session)


def test_ingest_riksdag_sources_writes_jsonl_with_fulltext(tmp_path: Path) -> None:
    list_url = "https://data.riksdagen.se/anforandelista/?rm=2025/26&parti=S&anftyp=Nej&utformat=json"
    output_path = tmp_path / "riksdag.jsonl"
    session = FakeSession(
        {
            list_url: FakeResponse(
                list_url,
                json_payload={
                    "dokumentlista": {
                        "dokument": [
                            {
                                "dok_id": "H8011",
                                "titel": "Välfärdsdebatt",
                                "parti": "S",
                                "doktyp": "prot",
                                "rm": "2025/26",
                            }
                        ]
                    }
                },
            ),
            "https://data.riksdagen.se/dokument/H8011.txt": FakeResponse(
                "https://data.riksdagen.se/dokument/H8011.txt",
                text=LONG_TEXT,
                content_type="text/plain",
            ),
        }
    )

    documents = ingest_riksdag.ingest_riksdag_sources("S", "2025/26", output_path=output_path, session=session)

    assert len(documents) == 1
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert row["doc_id"] == "riksdag-H8011"
    assert row["source_kind"] == "riksdag_speech"
    assert row["title"] == "Välfärdsdebatt"
    assert "Detta är fulltext från Riksdagen." in row["text"]
    assert len(row["text"]) >= ingest_riksdag.MIN_TEXT_LENGTH
    assert row["metadata"]["dok_id"] == "H8011"
    assert row["metadata"]["dokumenttyp"] == "prot"
    assert row["metadata"]["riksmote"] == "2025/26"
    assert row["metadata"]["parti"] == "S"
