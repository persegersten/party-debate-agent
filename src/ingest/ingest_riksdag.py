from __future__ import annotations

import argparse
import hashlib
import html
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

LOGGER = logging.getLogger(__name__)
DEFAULT_OUTPUT_PATH = Path("data/processed/riksdag_sources.jsonl")
RIKSDAG_ANFORANDE_URL = "https://data.riksdagen.se/anforandelista/"
RIKSDAG_DOCUMENT_URL = "https://data.riksdagen.se/dokument"
USER_AGENT = "party-debate-agent/0.1 hackathon"
REQUEST_TIMEOUT = 30
MIN_TEXT_LENGTH = 200


def clean_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in normalized.splitlines()]
    return "\n".join(line for line in lines if line)


def _as_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def normalize_riksdag_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidate_paths = [
        ("dokumentlista", "dokument"),
        ("dokumentstatus", "dokument"),
        ("anforandelista", "anforande"),
        ("dokument",),
        ("anforande",),
    ]
    for path in candidate_paths:
        value: Any = payload
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        records = _as_records(value)
        if records:
            return records

    for value in payload.values():
        if isinstance(value, dict):
            for key in ("dokument", "anforande"):
                records = _as_records(value.get(key))
                if records:
                    return records
    LOGGER.warning("Riksdagen API did not return a known document list structure")
    return []


def _first_string(record: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = record.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def extract_dok_id(record: dict[str, Any]) -> str | None:
    return _first_string(record, ("dok_id", "dokid", "dokument_id", "id"))


def extract_title(record: dict[str, Any]) -> str:
    return _first_string(record, ("titel", "dok_titel", "title", "avsnittsrubrik", "rubrik")) or "Riksdagsdokument"


def extract_document_url(record: dict[str, Any]) -> str | None:
    return _first_string(
        record,
        (
            "dokument_url_text",
            "dokument_url_txt",
            "text_url",
            "url_text",
            "dokument_url_html",
            "html_url",
            "url_html",
            "anforande_url_html",
            "anforande_url_xml",
            "protokoll_url_www",
            "dokument_url",
            "anf_url",
            "debatt_url",
            "url",
        ),
    )


def extract_party(record: dict[str, Any]) -> str | None:
    return _first_string(record, ("parti", "partibet", "parti_id", "intressent_id"))


def extract_inline_text(record: dict[str, Any]) -> str | None:
    text = _first_string(
        record,
        (
            "anforandetext",
            "anf_text",
            "text",
            "dokument_text",
            "dokumenttext",
            "html",
            "content",
        ),
    )
    if not text:
        return None
    cleaned = clean_text(text)
    return cleaned if len(cleaned) >= MIN_TEXT_LENGTH else None


def _new_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _log_response(response: requests.Response) -> None:
    LOGGER.info(
        "Riksdagen request url=%s status=%s content-type=%s",
        response.url,
        response.status_code,
        response.headers.get("content-type", ""),
    )


def _fetch_url_text(session: requests.Session, url: str) -> tuple[str | None, str, str]:
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        return None, f"request failed: {exc}", ""
    _log_response(response)
    if response.status_code != 200:
        return None, f"HTTP {response.status_code}", response.headers.get("content-type", "")
    return response.text, "", response.headers.get("content-type", "")


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style", "noscript", "nav", "footer", "header", "svg"]):
        element.decompose()
    return clean_text(soup.get_text(separator="\n"))


def _response_text_to_document_text(text: str, content_type: str) -> str:
    lowered_content_type = content_type.lower()
    stripped = text.lstrip()
    if "html" not in lowered_content_type and "xml" not in lowered_content_type and not stripped.startswith("<"):
        return clean_text(text)

    soup = BeautifulSoup(text, "html.parser")
    embedded_html = soup.find("html")
    if embedded_html:
        unescaped = html.unescape(embedded_html.get_text("\n"))
        return _html_to_text(unescaped)
    return _html_to_text(text)


def _text_urls_from_record(record: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for key in ("dokument_url_text", "dokument_url_txt", "text_url", "url_text"):
        value = _first_string(record, (key,))
        if value:
            candidates.append(value)
    generic_url = extract_document_url(record)
    if generic_url and generic_url.lower().endswith(".txt"):
        candidates.append(generic_url)
    return list(dict.fromkeys(candidates))


def fetch_document_text(record: dict[str, Any], session: requests.Session) -> str | None:
    inline_text = extract_inline_text(record)
    if inline_text:
        return inline_text

    dok_id = extract_dok_id(record)
    attempted: list[str] = []
    for url in _text_urls_from_record(record):
        attempted.append(url)
        text, error, content_type = _fetch_url_text(session, url)
        if error:
            LOGGER.debug("Could not fetch Riksdagen text URL for dok_id=%s url=%s: %s", dok_id, url, error)
            continue
        cleaned = _response_text_to_document_text(text or "", content_type)
        if len(cleaned) >= MIN_TEXT_LENGTH:
            return cleaned
        LOGGER.debug("Skipped short Riksdagen text URL for dok_id=%s url=%s length=%s", dok_id, url, len(cleaned))

    if dok_id:
        txt_url = f"{RIKSDAG_DOCUMENT_URL}/{dok_id}.txt"
        attempted.append(txt_url)
        text, error, content_type = _fetch_url_text(session, txt_url)
        if not error:
            cleaned = _response_text_to_document_text(text or "", content_type)
            if len(cleaned) >= MIN_TEXT_LENGTH:
                return cleaned
            LOGGER.debug("Skipped short Riksdagen txt document for dok_id=%s length=%s", dok_id, len(cleaned))
        else:
            LOGGER.debug("Could not fetch Riksdagen txt document for dok_id=%s: %s", dok_id, error)

        html_url = f"{RIKSDAG_DOCUMENT_URL}/{dok_id}.html"
        attempted.append(html_url)
        html_text, error, content_type = _fetch_url_text(session, html_url)
        if not error:
            cleaned = _response_text_to_document_text(html_text or "", content_type)
            if len(cleaned) >= MIN_TEXT_LENGTH:
                return cleaned
            LOGGER.debug("Skipped short Riksdagen html document for dok_id=%s length=%s", dok_id, len(cleaned))
        else:
            LOGGER.debug("Could not fetch Riksdagen html document for dok_id=%s: %s", dok_id, error)

    LOGGER.warning(
        "Skipping Riksdagen record without fulltext: dok_id=%s title=%r url=%s attempted=%s",
        dok_id,
        extract_title(record),
        extract_document_url(record),
        attempted,
    )
    return None


def _fetch_riksdag_payload(
    party_id: str,
    riksmote: str,
    session: requests.Session,
) -> dict[str, Any]:
    params = {"rm": riksmote, "parti": party_id, "anftyp": "Nej", "utformat": "json"}
    response = session.get(RIKSDAG_ANFORANDE_URL, params=params, timeout=REQUEST_TIMEOUT)
    _log_response(response)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Riksdagen API returned non-object JSON")
    LOGGER.info("Riksdagen top-level JSON keys: %s", sorted(payload))
    return payload


def fetch_riksdag_records(
    party_id: str,
    riksmote: str,
    limit: int = 20,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    session = session or _new_session()
    payload = _fetch_riksdag_payload(party_id=party_id, riksmote=riksmote, session=session)
    records = normalize_riksdag_records(payload)
    LOGGER.info("Riksdagen records found: %s", len(records))
    if records:
        LOGGER.info("Riksdagen first record keys: %s", sorted(records[0]))
    return records[:limit]


def _stable_record_id(record: dict[str, Any]) -> str:
    dok_id = extract_dok_id(record)
    if dok_id:
        return dok_id
    return hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def _document_from_record(
    record: dict[str, Any],
    text: str,
    party_id: str,
    riksmote: str,
) -> dict[str, Any]:
    record_id = _stable_record_id(record)
    dok_id = extract_dok_id(record)
    party = extract_party(record) or party_id
    url = extract_document_url(record) or (f"{RIKSDAG_DOCUMENT_URL}/{dok_id}.html" if dok_id else "https://data.riksdagen.se/")
    fetched_at = datetime.now(timezone.utc).isoformat()
    return {
        "doc_id": f"riksdag-{record_id}",
        "party": party,
        "source_owner": "Sveriges riksdag",
        "source_kind": "riksdag_speech",
        "title": extract_title(record),
        "url": url,
        "fetched_at": fetched_at,
        "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "text": text,
        "metadata": {
            "official_source": True,
            "source_system": "riksdagen_open_data",
            "dok_id": dok_id,
            "dokumenttyp": _first_string(record, ("doktyp", "typ", "dokumenttyp")),
            "riksmote": _first_string(record, ("rm", "riksmote")) or riksmote,
            "parti": party,
        },
    }


def _write_jsonl(documents: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        for document in documents:
            file.write(json.dumps(document, ensure_ascii=False) + "\n")


def ingest_riksdag_sources(
    party_id: str,
    riksmote: str,
    limit: int = 20,
    output_path: Path | str = DEFAULT_OUTPUT_PATH,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    session = session or _new_session()
    try:
        records = fetch_riksdag_records(party_id=party_id, riksmote=riksmote, limit=limit, session=session)
    except requests.RequestException as exc:
        LOGGER.warning("Could not fetch Riksdagen data: %s", exc)
        return []
    except ValueError as exc:
        LOGGER.warning("Could not decode Riksdagen JSON: %s", exc)
        return []

    documents: list[dict[str, Any]] = []
    skipped_without_text = 0
    for record in records:
        text = fetch_document_text(record, session)
        if not text:
            skipped_without_text += 1
            continue
        documents.append(_document_from_record(record, text, party_id, riksmote))

    if skipped_without_text:
        LOGGER.warning("Skipped %s Riksdagen records without text", skipped_without_text)

    if records and not documents:
        first_keys = sorted(records[0]) if records else []
        raise RuntimeError(
            "Riksdagen import wrote 0 documents after finding "
            f"{len(records)} records; skipped_without_text={skipped_without_text}; first_record_keys={first_keys}"
        )

    path = Path(output_path)
    _write_jsonl(documents, path)
    LOGGER.info("Wrote %s Riksdagen documents to %s", len(documents), path)
    return documents


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch optional Riksdagen source material.")
    parser.add_argument("--party", required=True, help="Party id, for example S")
    parser.add_argument("--riksmote", default="2025/26")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()

    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(levelname)s %(name)s: %(message)s")
    ingest_riksdag_sources(args.party, args.riksmote, args.limit, args.output)


if __name__ == "__main__":
    main()
