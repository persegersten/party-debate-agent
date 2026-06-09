from __future__ import annotations

import argparse
import hashlib
import json
import logging
from pathlib import Path

from debate.models import DocumentChunk, RawDocument

LOGGER = logging.getLogger(__name__)
DEFAULT_INPUT_PATH = Path("data/processed/party_sources.jsonl")
DEFAULT_OUTPUT_PATH = Path("data/processed/chunks.jsonl")


def chunk_document(document: RawDocument, chunk_size: int = 1200, overlap: int = 200) -> list[DocumentChunk]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")

    text = " ".join(document.text.split())
    if not text:
        return []

    chunks: list[DocumentChunk] = []
    start = 0
    index = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk_text = text[start:end].strip()
        chunk_id = hashlib.sha256(f"{document.doc_id}:{index}:{chunk_text}".encode("utf-8")).hexdigest()
        chunks.append(
            DocumentChunk(
                chunk_id=chunk_id,
                doc_id=document.doc_id,
                party=document.party,
                source_kind=document.source_kind,
                title=document.title,
                url=document.url,
                text=chunk_text,
                chunk_index=index,
                metadata=dict(document.metadata),
            )
        )
        if end == len(text):
            break
        start = end - overlap
        index += 1
    return chunks


def _read_documents(input_path: Path) -> list[RawDocument]:
    documents: list[RawDocument] = []
    with input_path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                documents.append(RawDocument.model_validate_json(line))
            except ValueError as exc:
                LOGGER.warning("Skipping invalid JSONL document on line %s in %s: %s", line_number, input_path, exc)
    return documents


def chunk_jsonl(input_path: Path | str, output_path: Path | str) -> None:
    input_file = Path(input_path)
    output_file = Path(output_path)
    documents = _read_documents(input_file)
    chunks = [chunk for document in documents for chunk in chunk_document(document)]

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8") as file:
        for chunk in chunks:
            payload = chunk.model_dump(mode="json")
            payload.pop("chunk_index", None)
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")
    LOGGER.info("Wrote %s chunks from %s documents to %s", len(chunks), len(documents), output_file)


def main() -> None:
    parser = argparse.ArgumentParser(description="Chunk processed JSONL documents.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    chunk_jsonl(args.input, args.output)


if __name__ == "__main__":
    main()
