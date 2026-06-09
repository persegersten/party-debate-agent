from __future__ import annotations

import hashlib

from debate.models import DocumentChunk, RawDocument


def chunk_document(document: RawDocument, chunk_size: int = 1200, overlap: int = 150) -> list[DocumentChunk]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")

    text = " ".join(document.text.split())
    chunks: list[DocumentChunk] = []
    start = 0
    index = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk_text = text[start:end].strip()
        chunk_id = hashlib.sha256(f"{document.party}:{document.url}:{index}:{chunk_text}".encode()).hexdigest()
        chunks.append(
            DocumentChunk(
                id=chunk_id,
                party=document.party,
                source_kind=document.source_kind,
                title=document.title,
                url=document.url,
                text=chunk_text,
                chunk_index=index,
                metadata=document.metadata,
            )
        )
        if end == len(text):
            break
        start = end - overlap
        index += 1
    return chunks
