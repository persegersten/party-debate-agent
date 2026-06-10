from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from typing import Any

from pipeline_stats import count_by
from rag.vector_store import DEFAULT_INDEX_DIR, LocalVectorStore

LOGGER = logging.getLogger(__name__)


def _collection_metadatas(store: LocalVectorStore) -> list[dict[str, Any]]:
    if store._collection is None:
        return [store._metadata(chunk) for chunk in store._fallback_chunks]
    result = store._collection.get(include=["metadatas"])
    return [metadata for metadata in result.get("metadatas", []) if isinstance(metadata, dict)]


def inspect_index(index_path: Path | str = DEFAULT_INDEX_DIR) -> dict[str, Any]:
    store = LocalVectorStore(persist_dir=index_path)
    metadatas = _collection_metadatas(store)
    summary = {
        "index_path": str(index_path),
        "count": store._record_count(),
        "by_party": count_by(metadatas, lambda metadata: metadata.get("party")),
        "by_source_kind": count_by(metadatas, lambda metadata: metadata.get("source_kind")),
    }
    LOGGER.info("Index path: %s", summary["index_path"])
    LOGGER.info("Chroma record count: %s", summary["count"])
    LOGGER.info("Index records by party: %s", summary["by_party"])
    LOGGER.info("Index records by source_kind: %s", summary["by_source_kind"])
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect the local Chroma vector index.")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX_DIR)
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(levelname)s %(name)s: %(message)s")
    inspect_index(args.index)


if __name__ == "__main__":
    main()
