from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from debate.models import DocumentChunk

LOGGER = logging.getLogger(__name__)
DEFAULT_CHUNKS_PATH = Path("data/processed/chunks.jsonl")
DEFAULT_INDEX_DIR = Path("data/index")


class HashEmbeddingFunction:
    """Small local embedding function for demos; avoids external model downloads."""

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002 - Chroma expects this name.
        return [self.embed(text) for text in input]

    def name(self) -> str:
        return "default"

    def is_legacy(self) -> bool:
        return True

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
        self._collection = None
        self._init_chroma()

    def _init_chroma(self) -> None:
        try:
            import chromadb
        except ModuleNotFoundError:
            LOGGER.warning("chromadb is not installed; using in-memory keyword fallback")
            return

        self.persist_dir.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(self.persist_dir))
        self._collection = client.get_or_create_collection(
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

    def build_from_jsonl(self, chunks_path: Path | str = DEFAULT_CHUNKS_PATH) -> int:
        chunks = read_chunks(chunks_path)
        if self._collection is not None and self._collection.count() > 0:
            LOGGER.info("Reusing existing Chroma index at %s with %s records", self.persist_dir, self._collection.count())
            return 0
        return self.add_chunks(chunks)

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
        metadata = dict(chunk.metadata)
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
) -> int:
    store = LocalVectorStore(persist_dir=persist_dir)
    return store.build_from_jsonl(chunks_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or reuse the local Chroma vector index.")
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS_PATH)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX_DIR)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    added = build_index(args.chunks, args.index)
    LOGGER.info("Index build complete; added %s new chunks", added)


if __name__ == "__main__":
    main()
