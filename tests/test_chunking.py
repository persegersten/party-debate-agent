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


def test_chunk_jsonl_accepts_multiple_inputs_and_mixed_source_kinds(tmp_path: Path) -> None:
    party_path = tmp_path / "party_sources.jsonl"
    riksdag_path = tmp_path / "riksdag_sources.jsonl"
    output_path = tmp_path / "chunks.jsonl"
    party_document = RawDocument(
        doc_id="party-1",
        party="M",
        source_owner="Moderaterna",
        source_kind="policy_index",
        title="Politik",
        url="https://example.com/m",
        text="politik " * 100,
        metadata={},
    )
    riksdag_document = RawDocument(
        doc_id="riksdag-1",
        party="S",
        source_owner="Sveriges riksdag",
        source_kind="riksdag_speech",
        title="Anförande",
        url="https://data.riksdagen.se/dokument/H8011",
        text="anförande " * 100,
        metadata={"dok_id": "H8011"},
    )
    party_path.write_text(json.dumps(party_document.model_dump(mode="json"), ensure_ascii=False) + "\n", encoding="utf-8")
    riksdag_path.write_text(json.dumps(riksdag_document.model_dump(mode="json"), ensure_ascii=False) + "\n", encoding="utf-8")

    chunk_jsonl([party_path, riksdag_path], output_path)

    chunks = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert {chunk["source_kind"] for chunk in chunks} == {"policy_index", "riksdag_speech"}
    assert {chunk["party"] for chunk in chunks} == {"M", "S"}


def test_chunk_jsonl_keeps_riksdag_documents_for_multiple_parties(tmp_path: Path) -> None:
    riksdag_path = tmp_path / "riksdag_sources.jsonl"
    output_path = tmp_path / "chunks.jsonl"
    documents = [
        RawDocument(
            doc_id="riksdag_speech:S:s-1",
            party="S",
            source_owner="Sveriges riksdag",
            source_kind="riksdag_speech",
            title="S anförande",
            url="https://data.riksdagen.se/anforande/s-1",
            text="anförande socialdemokraterna " * 80,
            metadata={"anforande_id": "s-1"},
        ),
        RawDocument(
            doc_id="riksdag_speech:M:m-1",
            party="M",
            source_owner="Sveriges riksdag",
            source_kind="riksdag_speech",
            title="M anförande",
            url="https://data.riksdagen.se/anforande/m-1",
            text="anförande moderaterna " * 80,
            metadata={"anforande_id": "m-1"},
        ),
    ]
    riksdag_path.write_text(
        "".join(json.dumps(document.model_dump(mode="json"), ensure_ascii=False) + "\n" for document in documents),
        encoding="utf-8",
    )

    chunk_jsonl([riksdag_path], output_path)

    chunks = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert {chunk["source_kind"] for chunk in chunks} == {"riksdag_speech"}
    assert {chunk["party"] for chunk in chunks} == {"S", "M"}
