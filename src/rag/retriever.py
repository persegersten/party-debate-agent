from __future__ import annotations

from debate.models import DocumentChunk, Evidence
from rag.vector_store import LocalVectorStore


def _snippet(text: str, max_length: int = 500) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 1].rstrip() + "..."


class PartyRetriever:
    def __init__(self, vector_store: LocalVectorStore | None = None) -> None:
        self.vector_store = vector_store or LocalVectorStore()

    def retrieve_chunks(self, query: str, party: str, k: int = 5) -> list[DocumentChunk]:
        return self.vector_store.search(query=query, party=party, k=k)

    def retrieve(self, query: str, party: str, k: int = 5) -> list[DocumentChunk]:
        return self.retrieve_chunks(query=query, party=party, k=k)

    def retrieve_for_party(self, party_id: str, query: str, k: int = 5) -> list[Evidence]:
        chunks = self.retrieve_chunks(query=query, party=party_id, k=k)
        return [
            Evidence(
                source_title=chunk.title,
                url=chunk.url,
                quote=_snippet(chunk.text),
                relevance=1.0,
            )
            for chunk in chunks
        ]


def retrieve_for_party(party_id: str, query: str, k: int = 5) -> list[Evidence]:
    return PartyRetriever().retrieve_for_party(party_id=party_id, query=query, k=k)
