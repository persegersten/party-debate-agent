from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from debate.models import DocumentChunk
from pipeline_stats import count_by

LOGGER = logging.getLogger(__name__)
DEFAULT_CHUNKS_PATH = Path("data/processed/chunks.jsonl")
DEFAULT_INDEX_DIR = Path("data/index")


class ExistingIndexError(RuntimeError):
    """Raised when an index build would append to an existing persistent index."""


class HashEmbeddingFunction:
    """Small local embedding function for demos; avoids external model downloads."""

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    def __call__(self, input: str | list[str]) -> list[list[float]]:  # noqa: A002 - Chroma expects this name.
        return self._embed_many(input)

    def embed_query(self, input: str | list[str]) -> list[list[float]]:  # noqa: A002 - Chroma-compatible API.
        return self._embed_many(input)

    def embed_documents(self, input: str | list[str]) -> list[list[float]]:  # noqa: A002 - Chroma-compatible API.
        return self._embed_many(input)

    def name(self) -> str:
        return "default"

    def is_legacy(self) -> bool:
        return True

    def _embed_many(self, input: str | list[str]) -> list[list[float]]:  # noqa: A002 - keeps Chroma naming.
        texts = [input] if isinstance(input, str) else input
        return [self.embed(text) for text in texts]

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


def read_chunks(path: Path | str) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    with Path(path).open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                payload.setdefault("chunk_index", len(chunks))
                chunks.append(DocumentChunk.model_validate(payload))
            except (json.JSONDecodeError, ValueError) as exc:
                LOGGER.warning("Skipping invalid chunk on line %s in %s: %s", line_number, path, exc)
    return chunks


class LocalVectorStore:
    def __init__(self, persist_dir: Path | str = DEFAULT_INDEX_DIR, collection_name: str = "party_sources") -> None:
        self.persist_dir = Path(persist_dir)
        self.collection_name = collection_name
        self.embedding_function = HashEmbeddingFunction()
        self._fallback_chunks: list[DocumentChunk] = []
        self._client = None
        self._collection = None
        self._init_chroma()

    def _init_chroma(self) -> None:
        try:
            import chromadb
        except ModuleNotFoundError:
            LOGGER.warning("chromadb is not installed; using in-memory keyword fallback")
            return

        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self.persist_dir))
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=self.embedding_function,
            metadata={"description": "Official Swedish party sources"},
        )

    def add_chunks(self, chunks: Iterable[DocumentChunk]) -> int:
        chunk_list = list(chunks)
        if not chunk_list:
            return 0
        if self._collection is None:
            self._fallback_chunks.extend(chunk_list)
            return len(chunk_list)

        existing_ids = set(self._collection.get(ids=[chunk.chunk_id for chunk in chunk_list]).get("ids", []))
        new_chunks = [chunk for chunk in chunk_list if chunk.chunk_id not in existing_ids]
        if not new_chunks:
            LOGGER.info("Index already contains all %s chunks", len(chunk_list))
            return 0

        self._collection.add(
            ids=[chunk.chunk_id for chunk in new_chunks],
            documents=[chunk.text for chunk in new_chunks],
            metadatas=[self._metadata(chunk) for chunk in new_chunks],
        )
        LOGGER.info("Added %s chunks to Chroma index at %s", len(new_chunks), self.persist_dir)
        return len(new_chunks)

    def build_from_jsonl(self, chunks_path: Path | str = DEFAULT_CHUNKS_PATH, rebuild: bool = False) -> int:
        chunks = read_chunks(chunks_path)
        LOGGER.info(
            "Building Chroma index from %s into %s; chunks=%s rebuild=%s",
            chunks_path,
            self.persist_dir,
            len(chunks),
            rebuild,
        )
        LOGGER.info("Index input chunks by source_kind: %s", count_by(chunks, lambda chunk: chunk.source_kind))
        LOGGER.info("Index input chunks by party: %s", count_by(chunks, lambda chunk: chunk.party))

        existing_count = self._record_count()
        if existing_count > 0 and not rebuild:
            raise ExistingIndexError(
                f"Index at {self.persist_dir} already contains existing records. "
                "Refusing to append because this can create stale retrieval results. "
                "Re-run the index build with --rebuild to clear and rebuild the index from the current chunks.jsonl."
            )

        if rebuild:
            LOGGER.info("Rebuilding Chroma index at %s; clearing %s existing records", self.persist_dir, existing_count)
            self._clear_index()

        written = self.add_chunks(chunks)
        LOGGER.info(
            "Index build complete for %s; vectors_written=%s final_records=%s rebuild=%s",
            self.persist_dir,
            written,
            self._record_count(),
            rebuild,
        )
        return written

    def _record_count(self) -> int:
        if self._collection is None:
            return len(self._fallback_chunks)
        return self._collection.count()

    def _clear_index(self) -> None:
        if self._collection is None:
            self._fallback_chunks.clear()
            return
        if self._client is None:
            self._init_chroma()
        if self._client is None:
            raise RuntimeError("Could not initialize Chroma client for index rebuild")
        self._client.delete_collection(self.collection_name)
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=self.embedding_function,
            metadata={"description": "Official Swedish party sources"},
        )

    def search(self, query: str, party: str | None = None, k: int = 5) -> list[DocumentChunk]:
        if k <= 0:
            return []
        if self._collection is None:
            return self._fallback_search(query, party, k)

        where = {"party": party} if party else None
        result = self._collection.query(query_texts=[query], n_results=k, where=where)
        return self._chunks_from_query_result(result)

    def _fallback_search(self, query: str, party: str | None, k: int) -> list[DocumentChunk]:
        query_terms = Counter(query.lower().split())
        candidates = [chunk for chunk in self._fallback_chunks if party is None or chunk.party == party]
        scored = []
        for chunk in candidates:
            text_terms = Counter(chunk.text.lower().split())
            score = sum(text_terms[term] for term in query_terms)
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [chunk for _, chunk in scored[:k]]

    def _metadata(self, chunk: DocumentChunk) -> dict[str, Any]:
        metadata = {key: value for key, value in chunk.metadata.items() if value is not None}
        metadata.update(
            {
                "chunk_id": chunk.chunk_id,
                "doc_id": chunk.doc_id,
                "party": chunk.party,
                "source_kind": chunk.source_kind,
                "title": chunk.title,
                "url": str(chunk.url),
            }
        )
        return metadata

    def _chunks_from_query_result(self, result: dict[str, Any]) -> list[DocumentChunk]:
        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        chunks: list[DocumentChunk] = []
        for chunk_id, text, metadata in zip(ids, documents, metadatas, strict=False):
            if not metadata:
                continue
            chunk_metadata = dict(metadata)
            chunks.append(
                DocumentChunk(
                    chunk_id=str(chunk_id),
                    doc_id=str(chunk_metadata.pop("doc_id")),
                    party=str(chunk_metadata.pop("party")),
                    source_kind=str(chunk_metadata.pop("source_kind")),
                    title=str(chunk_metadata.pop("title")),
                    url=str(chunk_metadata.pop("url")),
                    text=text or "",
                    chunk_index=0,
                    metadata=chunk_metadata,
                )
            )
        return chunks


def build_index(
    chunks_path: Path | str = DEFAULT_CHUNKS_PATH,
    persist_dir: Path | str = DEFAULT_INDEX_DIR,
    rebuild: bool = False,
) -> int:
    store = LocalVectorStore(persist_dir=persist_dir)
    return store.build_from_jsonl(chunks_path, rebuild=rebuild)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the local Chroma vector index.")
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS_PATH)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Clear any existing index records before building from the current chunks JSONL.",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()

    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(levelname)s %(name)s: %(message)s")
    try:
        added = build_index(args.chunks, args.index, rebuild=args.rebuild)
    except ExistingIndexError as exc:
        raise SystemExit(str(exc)) from exc
    LOGGER.info("Index build complete; added %s new chunks", added)


if __name__ == "__main__":
    main()
