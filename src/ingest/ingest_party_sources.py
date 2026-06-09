from __future__ import annotations

from pathlib import Path

from debate.models import RawDocument, load_project_config
from ingest.chunking import chunk_document


def ingest_party_sources(config_dir: Path | str = Path("data/config")) -> list[RawDocument]:
    config = load_project_config(config_dir)
    # TODO: Fetch and parse HTML/PDF content. Hackaton stub keeps ingestion offline-testable.
    return [
        RawDocument(
            party=source.party,
            source_kind=source.source_kind,
            title=source.title,
            url=source.url,
            text="",
            metadata={"source_kind": source.source_kind},
        )
        for source in config.sources
    ]


def main() -> None:
    documents = ingest_party_sources()
    chunks = [chunk for document in documents for chunk in chunk_document(document) if chunk.text]
    print(f"Loaded {len(documents)} configured sources and created {len(chunks)} chunks.")


if __name__ == "__main__":
    main()
