import json
from pathlib import Path

from debate.models import RawDocument
from ingest.chunking import chunk_document, chunk_jsonl


def test_chunk_document_preserves_metadata() -> None:
    document = RawDocument(
        doc_id="doc-1",
        party="S",
        source_owner="Socialdemokraterna",
        source_kind="party_program",
        title="Program",
        url="https://example.com/program",
        content_hash="abc",
        text="klimat " * 300,
        metadata={"official_source": True, "source_system": "party_website"},
    )

    chunks = chunk_document(document, chunk_size=120, overlap=20)

    assert chunks
    assert chunks[0].doc_id == "doc-1"
    assert chunks[0].metadata["official_source"] is True
    assert chunks[0].party == "S"


def test_chunk_jsonl_writes_expected_shape(tmp_path: Path) -> None:
    input_path = tmp_path / "docs.jsonl"
    output_path = tmp_path / "chunks.jsonl"
    document = RawDocument(
        doc_id="doc-1",
        party="MP",
        source_owner="Miljöpartiet",
        source_kind="policy_index",
        title="Politik",
        url="https://example.com/politik",
        text="miljö " * 100,
        metadata={"official_source": True, "source_system": "party_website"},
    )
    input_path.write_text(json.dumps(document.model_dump(mode="json"), ensure_ascii=False) + "\n", encoding="utf-8")

    chunk_jsonl(input_path, output_path)
    first_chunk = json.loads(output_path.read_text(encoding="utf-8").splitlines()[0])

    assert first_chunk["chunk_id"]
    assert first_chunk["doc_id"] == "doc-1"
    assert first_chunk["metadata"]["source_system"] == "party_website"
