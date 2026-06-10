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


def test_fetch_document_text_uses_anforandetext_without_document_fetch() -> None:
    session = FakeSession(
        {
            "https://data.riksdagen.se/dokument/H8011.txt": FakeResponse(
                "https://data.riksdagen.se/dokument/H8011.txt",
                text="Hela protokollet " * 100,
                content_type="text/plain",
            )
        }
    )
    record = {"dok_id": "H8011", "anforande_id": "abc-123", "anforandetext": LONG_TEXT}

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


def test_fetch_document_text_tries_speech_urls_before_document_fallback() -> None:
    xml_url = "https://data.riksdagen.se/anforande/H8011-1.xml"
    session = FakeSession(
        {
            xml_url: FakeResponse(
                xml_url,
                text=f"<anforande><anforandetext>{LONG_TEXT}</anforandetext></anforande>",
                content_type="text/xml",
            ),
            "https://data.riksdagen.se/dokument/H8011.txt": FakeResponse(
                "https://data.riksdagen.se/dokument/H8011.txt",
                text="Hela protokollet " * 100,
                content_type="text/plain",
            ),
        }
    )
    record = {"dok_id": "H8011", "anforande_url_xml": xml_url}

    text = ingest_riksdag.fetch_document_text(record, session)

    assert text is not None
    assert "Detta är fulltext från Riksdagen." in text
    assert "Hela protokollet" not in text
    assert session.calls == [xml_url]


def test_fetch_document_text_extracts_anforandetext_from_speech_xml() -> None:
    xml_url = "https://data.riksdagen.se/anforande/H8011-1.xml"
    xml = (
        "<anforande>"
        "<dok_id>H8011</dok_id>"
        "<talare>Ledamot Test</talare>"
        f"<anforandetext>&lt;p&gt;{LONG_TEXT}&lt;/p&gt;</anforandetext>"
        "</anforande>"
    )
    session = FakeSession({xml_url: FakeResponse(xml_url, text=xml, content_type="text/xml")})

    text = ingest_riksdag.fetch_document_text({"dok_id": "H8011", "anforande_url_xml": xml_url}, session)

    assert text is not None
    assert text.startswith("Detta är fulltext från Riksdagen.")
    assert "Ledamot Test" not in text
    assert "<p>" not in text


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
                                "anforande_id": "anf-1",
                                "anforande_nummer": "1",
                                "dok_id": "H8011",
                                "titel": "Välfärdsdebatt",
                                "dok_titel": "Protokoll",
                                "dok_datum": "2026-06-09",
                                "talare": "Ledamot Test",
                                "parti": "S",
                                "doktyp": "prot",
                                "dok_rm": "2025/26",
                                "anforande_url_html": "https://data.riksdagen.se/anforande/anf-1",
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
    assert row["doc_id"] == "riksdag_speech:S:anf-1"
    assert row["source_kind"] == "riksdag_speech"
    assert row["title"] == "Välfärdsdebatt"
    assert row["url"] == "https://data.riksdagen.se/anforande/anf-1"
    assert "Detta är fulltext från Riksdagen." in row["text"]
    assert len(row["text"]) >= ingest_riksdag.MIN_TEXT_LENGTH
    assert row["metadata"]["dok_id"] == "H8011"
    assert row["metadata"]["anforande_id"] == "anf-1"
    assert row["metadata"]["anforande_nummer"] == "1"
    assert row["metadata"]["talare"] == "Ledamot Test"
    assert row["metadata"]["dok_titel"] == "Protokoll"
    assert row["metadata"]["dok_datum"] == "2026-06-09"
    assert row["metadata"]["dokumenttyp"] == "prot"
    assert row["metadata"]["riksmote"] == "2025/26"
    assert row["metadata"]["parti"] == "S"


def test_ingest_riksdag_sources_appends_multiple_party_imports(tmp_path: Path) -> None:
    output_path = tmp_path / "riksdag.jsonl"
    s_url = "https://data.riksdagen.se/anforandelista/?rm=2025/26&parti=S&anftyp=Nej&utformat=json"
    m_url = "https://data.riksdagen.se/anforandelista/?rm=2025/26&parti=M&anftyp=Nej&utformat=json"
    s_session = FakeSession(
        {
            s_url: FakeResponse(
                s_url,
                json_payload={"anforandelista": {"anforande": {"anforande_id": "s-1", "parti": "S", "anforandetext": LONG_TEXT}}},
            )
        }
    )
    m_session = FakeSession(
        {
            m_url: FakeResponse(
                m_url,
                json_payload={"anforandelista": {"anforande": {"anforande_id": "m-1", "parti": "M", "anforandetext": LONG_TEXT}}},
            )
        }
    )

    ingest_riksdag.ingest_riksdag_sources("S", "2025/26", output_path=output_path, session=s_session)
    ingest_riksdag.ingest_riksdag_sources("M", "2025/26", output_path=output_path, session=m_session, append=True)

    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert [row["doc_id"] for row in rows] == ["riksdag_speech:S:s-1", "riksdag_speech:M:m-1"]


def test_ingest_riksdag_sources_logs_import_summary_and_text_stats(tmp_path: Path, caplog) -> None:
    list_url = "https://data.riksdagen.se/anforandelista/?rm=2025/26&parti=S&anftyp=Nej&utformat=json"
    output_path = tmp_path / "riksdag.jsonl"
    session = FakeSession(
        {
            list_url: FakeResponse(
                list_url,
                json_payload={
                    "anforandelista": {
                        "anforande": [
                            {"dok_id": "H8011", "titel": "Importerat", "anforandetext": LONG_TEXT},
                            {"dok_id": "H8012", "titel": "För kort", "anforandetext": "kort"},
                        ]
                    }
                },
            ),
        }
    )
    caplog.set_level("INFO")

    documents = ingest_riksdag.ingest_riksdag_sources("S", "2025/26", output_path=output_path, session=session)

    assert len(documents) == 1
    assert "Riksdagen import summary: party=S riksmote=2025/26 limit=20 records=2 imported=1 skipped=1" in caplog.text
    assert "skipped_missing_or_short_text=1" in caplog.text
    assert "inline_anforandetext=1" in caplog.text
    assert "Riksdagen text stats for party=S: documents=1" in caplog.text


def test_ingest_riksdag_sources_warns_for_suspiciously_large_fallback_text(tmp_path: Path, caplog) -> None:
    list_url = "https://data.riksdagen.se/anforandelista/?rm=2025/26&parti=S&anftyp=Nej&utformat=json"
    large_text = "Hela protokollet " * 4000
    session = FakeSession(
        {
            list_url: FakeResponse(
                list_url,
                json_payload={"anforandelista": {"anforande": {"anforande_id": "s-1", "dok_id": "H8011", "parti": "S"}}},
            ),
            "https://data.riksdagen.se/dokument/H8011.txt": FakeResponse(
                "https://data.riksdagen.se/dokument/H8011.txt",
                text=large_text,
                content_type="text/plain",
            ),
        }
    )
    caplog.set_level("WARNING")

    ingest_riksdag.ingest_riksdag_sources("S", "2025/26", output_path=tmp_path / "riksdag.jsonl", session=session)

    assert "Suspiciously large Riksdagen speech text" in caplog.text
