from __future__ import annotations

import argparse
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)
DEFAULT_OUTPUT_PATH = Path("data/processed/riksdag_sources.jsonl")
RIKSDAG_ANFORANDE_URL = "https://data.riksdagen.se/anforandelista/"


def _as_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _extract_speeches(payload: dict[str, Any]) -> list[dict[str, Any]]:
    speeches = payload.get("anforandelista", {}).get("anforande")
    items = _as_list(speeches)
    if not items:
        LOGGER.warning("Riksdagen API did not return expected anforandelista.anforande structure")
    return items


def fetch_riksdag_speeches(party_id: str, riksmote: str, limit: int = 20) -> list[dict[str, Any]]:
    params = {"rm": riksmote, "parti": party_id, "anftyp": "Nej", "utformat": "json"}
    response = requests.get(RIKSDAG_ANFORANDE_URL, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        LOGGER.warning("Riksdagen API returned non-object JSON")
        return []
    return _extract_speeches(payload)[:limit]


def _document_from_speech(speech: dict[str, Any], party_id: str, riksmote: str) -> dict[str, Any]:
    speech_id = str(speech.get("anforande_id") or speech.get("dok_id") or hashlib.sha256(json.dumps(speech).encode()).hexdigest())
    text = str(speech.get("anforandetext") or speech.get("anf_text") or speech.get("text") or "").strip()
    title = str(speech.get("avsnittsrubrik") or speech.get("dok_titel") or "Riksdagsanförande")
    url = str(speech.get("anf_url") or speech.get("dokument_url_html") or speech.get("debatt_url") or "https://www.riksdagen.se/")
    fetched_at = datetime.now(timezone.utc).isoformat()
    return {
        "doc_id": f"riksdag-{speech_id}",
        "party": party_id,
        "source_owner": "Sveriges riksdag",
        "source_kind": "riksdag_speech",
        "title": title,
        "url": url,
        "fetched_at": fetched_at,
        "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "text": text,
        "metadata": {
            "official_source": True,
            "source_system": "riksdagen_open_data",
            "riksmote": riksmote,
        },
    }


def ingest_riksdag_sources(
    party_id: str,
    riksmote: str,
    limit: int = 20,
    output_path: Path | str = DEFAULT_OUTPUT_PATH,
) -> list[dict[str, Any]]:
    try:
        speeches = fetch_riksdag_speeches(party_id=party_id, riksmote=riksmote, limit=limit)
    except requests.RequestException as exc:
        LOGGER.warning("Could not fetch Riksdagen data: %s", exc)
        return []
    except ValueError as exc:
        LOGGER.warning("Could not decode Riksdagen JSON: %s", exc)
        return []

    documents = [_document_from_speech(speech, party_id, riksmote) for speech in speeches]
    documents = [document for document in documents if document["text"]]
    if len(documents) < len(speeches):
        LOGGER.warning("Skipped %s Riksdagen records without text", len(speeches) - len(documents))

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for document in documents:
            file.write(json.dumps(document, ensure_ascii=False) + "\n")
    LOGGER.info("Wrote %s Riksdagen documents to %s", len(documents), path)
    return documents


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch optional Riksdagen source material.")
    parser.add_argument("--party", required=True, help="Party id, for example S")
    parser.add_argument("--riksmote", default="2025/26")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ingest_riksdag_sources(args.party, args.riksmote, args.limit, args.output)


if __name__ == "__main__":
    main()
