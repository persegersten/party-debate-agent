from __future__ import annotations

from debate.models import DocumentChunk
from rag.vector_store import LocalVectorStore


class PartyRetriever:
    def __init__(self, vector_store: LocalVectorStore | None = None) -> None:
        self.vector_store = vector_store or LocalVectorStore()

    def retrieve(self, query: str, party: str, k: int = 5) -> list[DocumentChunk]:
        return self.vector_store.search(query=query, party=party, k=k)
