from __future__ import annotations

import argparse
import hashlib
import html
import json
import logging
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup
from pipeline_stats import text_stats

LOGGER = logging.getLogger(__name__)
DEFAULT_OUTPUT_PATH = Path("data/processed/riksdag_sources.jsonl")
RIKSDAG_ANFORANDE_URL = "https://data.riksdagen.se/anforandelista/"
RIKSDAG_DOCUMENT_URL = "https://data.riksdagen.se/dokument"
USER_AGENT = "party-debate-agent/0.1 hackathon"
REQUEST_TIMEOUT = 30
MIN_TEXT_LENGTH = 200
SUSPICIOUS_TEXT_LENGTH = 50_000


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


def extract_anforande_id(record: dict[str, Any]) -> str | None:
    return _first_string(record, ("anforande_id", "anförande_id", "anf_id"))


def extract_anforandetext(record: dict[str, Any]) -> str | None:
    text = _first_string(record, ("anforandetext", "anf_text"))
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
    speech_text = soup.find("anforandetext")
    if speech_text:
        unescaped = html.unescape(speech_text.get_text("\n"))
        return _html_to_text(unescaped)
    embedded_html = soup.find("html")
    if embedded_html:
        unescaped = html.unescape(embedded_html.get_text("\n"))
        return _html_to_text(unescaped)
    return _html_to_text(text)


def _urls_from_record(record: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    candidates = []
    for key in keys:
        value = _first_string(record, (key,))
        if value:
            candidates.append(value)
    return list(dict.fromkeys(candidates))


def _fetch_document_text_with_source(record: dict[str, Any], session: requests.Session) -> tuple[str | None, str]:
    inline_text = extract_anforandetext(record)
    if inline_text:
        return inline_text, "inline_anforandetext"

    dok_id = extract_dok_id(record)
    attempted: list[str] = []
    speech_url_groups = [
        ("anforande_url_xml", _urls_from_record(record, ("anforande_url_xml",))),
        ("anforande_url_html", _urls_from_record(record, ("anforande_url_html",))),
    ]
    for source, urls in speech_url_groups:
        for url in urls:
            attempted.append(url)
            text, error, content_type = _fetch_url_text(session, url)
            if error:
                LOGGER.debug("Could not fetch Riksdagen %s for dok_id=%s url=%s: %s", source, dok_id, url, error)
                continue
            cleaned = _response_text_to_document_text(text or "", content_type)
            if len(cleaned) >= MIN_TEXT_LENGTH:
                return cleaned, source
            LOGGER.debug("Skipped short Riksdagen %s for dok_id=%s url=%s length=%s", source, dok_id, url, len(cleaned))

    if dok_id:
        document_urls = _urls_from_record(record, ("dokument_url_text", "dokument_url_txt", "text_url", "url_text"))
        document_urls.append(f"{RIKSDAG_DOCUMENT_URL}/{dok_id}.txt")
        document_urls.append(f"{RIKSDAG_DOCUMENT_URL}/{dok_id}.html")
        for url in list(dict.fromkeys(document_urls)):
            attempted.append(url)
            text, error, content_type = _fetch_url_text(session, url)
            if error:
                LOGGER.debug("Could not fetch Riksdagen document fallback for dok_id=%s url=%s: %s", dok_id, url, error)
                continue
            cleaned = _response_text_to_document_text(text or "", content_type)
            if len(cleaned) >= MIN_TEXT_LENGTH:
                return cleaned, "document_fallback"
            LOGGER.debug("Skipped short Riksdagen document fallback for dok_id=%s url=%s length=%s", dok_id, url, len(cleaned))

    LOGGER.warning(
        "Skipping Riksdagen record without fulltext: dok_id=%s title=%r url=%s attempted=%s",
        dok_id,
        extract_title(record),
        extract_document_url(record),
        attempted,
    )
    return None, "missing_or_short_text"


def fetch_document_text(record: dict[str, Any], session: requests.Session) -> str | None:
    text, _source = _fetch_document_text_with_source(record, session)
    return text


def _text_snippet(text: str, max_length: int = 120) -> str:
    snippet = " ".join((text or "").split())
    if len(snippet) <= max_length:
        return snippet
    return snippet[: max_length - 3].rstrip() + "..."


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
    LOGGER.info("Riksdagen API records returned: %s", len(records))
    if records:
        LOGGER.info("Riksdagen first record keys: %s", sorted(records[0]))
    LOGGER.info("Riksdagen records selected after limit=%s: %s", limit, min(len(records), limit))
    return records[:limit]


def _stable_record_id(record: dict[str, Any]) -> str:
    anforande_id = extract_anforande_id(record)
    if anforande_id:
        return anforande_id
    return hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def _document_from_record(
    record: dict[str, Any],
    text: str,
    party_id: str,
    riksmote: str,
) -> dict[str, Any]:
    record_id = _stable_record_id(record)
    dok_id = extract_dok_id(record)
    anforande_id = extract_anforande_id(record)
    party = extract_party(record) or party_id
    url = _first_string(record, ("anforande_url_html",)) or extract_document_url(record) or (
        f"{RIKSDAG_DOCUMENT_URL}/{dok_id}.html" if dok_id else "https://data.riksdagen.se/"
    )
    fetched_at = datetime.now(timezone.utc).isoformat()
    return {
        "doc_id": f"riksdag_speech:{party}:{record_id}",
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
            "anforande_id": anforande_id,
            "anforande_nummer": _first_string(record, ("anforande_nummer",)),
            "talare": _first_string(record, ("talare",)),
            "dokumenttyp": _first_string(record, ("doktyp", "typ", "dokumenttyp")),
            "dok_titel": _first_string(record, ("dok_titel",)),
            "dok_datum": _first_string(record, ("dok_datum",)),
            "riksmote": _first_string(record, ("dok_rm", "rm", "riksmote")) or riksmote,
            "parti": party,
        },
    }


def _write_jsonl(documents: list[dict[str, Any]], output_path: Path, append: bool = False) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with output_path.open(mode, encoding="utf-8") as file:
        for document in documents:
            file.write(json.dumps(document, ensure_ascii=False) + "\n")


def ingest_riksdag_sources(
    party_id: str,
    riksmote: str,
    limit: int = 20,
    output_path: Path | str = DEFAULT_OUTPUT_PATH,
    session: requests.Session | None = None,
    append: bool = False,
) -> list[dict[str, Any]]:
    session = session or _new_session()
    output_mode = "append" if append else "overwrite"
    LOGGER.info(
        "Starting Riksdagen import: party=%s riksmote=%s limit=%s output=%s mode=%s",
        party_id,
        riksmote,
        limit,
        output_path,
        output_mode,
    )
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
    text_source_counts: Counter[str] = Counter()
    for record in records:
        text, text_source = _fetch_document_text_with_source(record, session)
        text_source_counts[text_source] += 1
        if not text:
            skipped_without_text += 1
            LOGGER.debug(
                "Skipped Riksdagen record: dok_id=%s title=%r reason=missing_or_short_text keys=%s",
                extract_dok_id(record),
                extract_title(record),
                sorted(record),
            )
            continue
        document = _document_from_record(record, text, party_id, riksmote)
        documents.append(document)
        if len(document["text"]) > SUSPICIOUS_TEXT_LENGTH:
            LOGGER.warning(
                "Suspiciously large Riksdagen speech text; this may be a whole protocol, not one speech: "
                "dok_id=%s anforande_id=%s chars=%s source=%s",
                document["metadata"].get("dok_id"),
                document["metadata"].get("anforande_id"),
                len(document["text"]),
                text_source,
            )
        LOGGER.debug(
            "Imported Riksdagen record: dok_id=%s anforande_id=%s title=%r party=%s chars=%s source=%s url=%s snippet=%r",
            document["metadata"].get("dok_id"),
            document["metadata"].get("anforande_id"),
            document["title"],
            document["party"],
            len(document["text"]),
            text_source,
            document["url"],
            _text_snippet(document["text"]),
        )

    if skipped_without_text:
        LOGGER.warning("Skipped %s Riksdagen records without text", skipped_without_text)

    if records and not documents:
        first_keys = sorted(records[0]) if records else []
        raise RuntimeError(
            "Riksdagen import wrote 0 documents after finding "
            f"{len(records)} records; skipped_without_text={skipped_without_text}; first_record_keys={first_keys}"
        )

    path = Path(output_path)
    _write_jsonl(documents, path, append=append)
    stats = text_stats(document["text"] for document in documents)
    LOGGER.info(
        "Riksdagen import summary: party=%s riksmote=%s limit=%s records=%s imported=%s skipped=%s "
        "skipped_missing_or_short_text=%s output=%s mode=%s",
        party_id,
        riksmote,
        limit,
        len(records),
        len(documents),
        len(records) - len(documents),
        skipped_without_text,
        path,
        output_mode,
    )
    LOGGER.info(
        "Riksdagen text source counts for party=%s: inline_anforandetext=%s anforande_url_xml=%s "
        "anforande_url_html=%s document_fallback=%s missing_or_short_text=%s",
        party_id,
        text_source_counts["inline_anforandetext"],
        text_source_counts["anforande_url_xml"],
        text_source_counts["anforande_url_html"],
        text_source_counts["document_fallback"],
        text_source_counts["missing_or_short_text"],
    )
    LOGGER.info(
        "Riksdagen text stats for party=%s: documents=%s chars_total=%s chars_min=%s "
        "chars_median=%s chars_max=%s words_total=%s",
        party_id,
        stats["documents"],
        stats["chars_total"],
        stats["chars_min"],
        stats["chars_median"],
        stats["chars_max"],
        stats["words_total"],
    )
    LOGGER.info("Wrote %s Riksdagen documents to %s with mode=%s", len(documents), path, output_mode)
    return documents


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch optional Riksdagen source material.")
    parser.add_argument("--party", required=True, help="Party id, for example S")
    parser.add_argument("--riksmote", default="2025/26")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--append", action="store_true", help="Append to output JSONL instead of overwriting it.")
    args = parser.parse_args()

    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(levelname)s %(name)s: %(message)s")
    ingest_riksdag_sources(args.party, args.riksmote, args.limit, args.output, append=args.append)


if __name__ == "__main__":
    main()
