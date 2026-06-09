from __future__ import annotations

from pathlib import Path
from typing import Iterable

from debate.models import DocumentChunk


class LocalVectorStore:
    def __init__(self, persist_dir: Path | str = Path("data/index/chroma")) -> None:
        self.persist_dir = Path(persist_dir)

    def add_chunks(self, chunks: Iterable[DocumentChunk]) -> int:
        # TODO: Wire Chroma embeddings. Keep interface stable for agents and tests.
        return sum(1 for _ in chunks)

    def search(self, query: str, party: str | None = None, k: int = 5) -> list[DocumentChunk]:
        # TODO: Implement semantic search with party metadata filtering.
        return []
