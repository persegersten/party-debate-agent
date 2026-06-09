from __future__ import annotations

import argparse
import hashlib
import html.parser
import json
import logging
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import requests

try:
    from bs4 import BeautifulSoup
except ModuleNotFoundError:
    BeautifulSoup = None

try:
    import trafilatura
except ModuleNotFoundError:
    def _missing_trafilatura_extract(*_args, **_kwargs) -> str:
        raise RuntimeError("trafilatura is required for HTML extraction. Install with `pip install -e .`.")

    trafilatura = SimpleNamespace(extract=_missing_trafilatura_extract)

try:
    from pypdf import PdfReader
except ModuleNotFoundError:
    PdfReader = None

from debate.models import RawDocument, SourceConfig, load_project_config

LOGGER = logging.getLogger(__name__)
DEFAULT_CONFIG_DIR = Path("data/config")
DEFAULT_OUTPUT_PATH = Path("data/processed/party_sources.jsonl")
SHORT_TEXT_WARNING_LIMIT = 500


def fetch_url(url: str) -> tuple[bytes, str]:
    response = requests.get(url, timeout=30, headers={"User-Agent": "party-debate-agent/0.1"})
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    return response.content, content_type


def _ensure_text(content: bytes | str) -> str:
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    return content


def _normalize_text(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _extract_with_trafilatura(html: str, url: str) -> str | None:
    LOGGER.info("Extracting HTML with trafilatura: %s", url)
    try:
        extracted = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=False,
            output_format="txt",
            favor_recall=True,
        )
    except Exception as exc:
        LOGGER.warning("Trafilatura extraction failed for %s: %s", url, exc)
        return None
    normalized = _normalize_text(extracted or "")
    return normalized or None


class _ReadableTextParser(html.parser.HTMLParser):
    """Fallback parser used only when beautifulsoup4 is unavailable."""

    _skip_tags = {"script", "style", "noscript", "nav", "footer", "header", "svg"}
    _block_tags = {"article", "aside", "br", "div", "h1", "h2", "h3", "h4", "li", "main", "p", "section"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, _attrs) -> None:
        if tag in self._skip_tags:
            self._skip_depth += 1
        elif tag in self._block_tags:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._skip_tags and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._block_tags:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


def _extract_with_beautifulsoup(html: str) -> str:
    if BeautifulSoup is None:
        LOGGER.warning("beautifulsoup4 is not installed; using stdlib HTML fallback parser")
        parser = _ReadableTextParser()
        parser.feed(html)
        return _normalize_text(parser.text())

    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style", "noscript", "nav", "footer", "header", "svg"]):
        element.decompose()
    return _normalize_text(soup.get_text(separator="\n"))


def extract_html(content: bytes | str, url: str) -> str:
    html = _ensure_text(content)
    text = _extract_with_trafilatura(html, url)
    if not text:
        LOGGER.warning("Using BeautifulSoup fallback for %s", url)
        text = _extract_with_beautifulsoup(html)

    if not text:
        raise ValueError(f"Could not extract readable text from HTML at {url}")

    if len(text) < SHORT_TEXT_WARNING_LIMIT:
        LOGGER.warning("Extracted short HTML text for %s: %s characters", url, len(text))
    return text


def extract_pdf(content: bytes) -> str:
    if PdfReader is None:
        raise RuntimeError("pypdf is required for PDF extraction. Install with `pip install -e .`.")
    reader = PdfReader(BytesIO(content))
    pages = []
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            pages.append(page.extract_text() or "")
        except Exception as exc:  # pragma: no cover - pypdf failures are file-specific
            LOGGER.warning("Could not extract text from PDF page %s: %s", page_number, exc)
    return "\n\n".join(page.strip() for page in pages if page.strip())


def _doc_id(source: SourceConfig) -> str:
    key = f"{source.party}:{source.source_kind}:{source.url}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _extract_text(content: bytes, content_type: str, url: str) -> str:
    if "pdf" in content_type or url.lower().endswith(".pdf"):
        return extract_pdf(content)
    return extract_html(content, url)


def _write_jsonl(documents: list[RawDocument], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        for document in documents:
            file.write(json.dumps(document.model_dump(mode="json"), ensure_ascii=False) + "\n")


def ingest_party_sources(
    config_path: Path | str = DEFAULT_CONFIG_DIR,
    output_path: Path | str = DEFAULT_OUTPUT_PATH,
) -> list[RawDocument]:
    config = load_project_config(config_path)
    party_by_id = config.party_by_id()
    documents: list[RawDocument] = []

    for source in config.sources:
        LOGGER.info("Fetching %s source for %s: %s", source.source_kind, source.party, source.url)
        content, content_type = fetch_url(str(source.url))
        try:
            text = _extract_text(content, content_type, str(source.url))
        except ValueError as exc:
            LOGGER.warning("Skipping source after extraction failure: %s", exc)
            text = ""
        content_hash = hashlib.sha256(content).hexdigest()
        party = party_by_id[source.party]
        documents.append(
            RawDocument(
                doc_id=_doc_id(source),
                party=source.party,
                source_owner=party.name,
                source_kind=source.source_kind,
                title=source.title,
                url=source.url,
                fetched_at=datetime.now(timezone.utc),
                content_hash=content_hash,
                text=text,
                metadata={"official_source": True, "source_system": "party_website"},
            )
        )
        if not text:
            LOGGER.warning("No extracted text for %s", source.url)

    _write_jsonl(documents, Path(output_path))
    LOGGER.info("Wrote %s party source documents to %s", len(documents), output_path)
    return documents


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch official party sources and write JSONL.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ingest_party_sources(args.config, args.output)


if __name__ == "__main__":
    main()
