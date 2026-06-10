import json
import sys

import pytest

from debate.models import DocumentChunk
from rag import vector_store
from rag.vector_store import ExistingIndexError, LocalVectorStore


def _chunk(chunk_id: str, text: str, party: str = "M") -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        doc_id=f"doc-{chunk_id}",
        party=party,
        source_kind="policy_index",
        title="Testkälla",
        url=f"https://example.com/{chunk_id}",
        text=text,
        chunk_index=0,
        metadata={"official_source": True},
    )


def _write_chunks(path, chunks: list[DocumentChunk]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for chunk in chunks:
            payload = chunk.model_dump(mode="json")
            payload.pop("chunk_index", None)
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def test_building_into_empty_index_succeeds(tmp_path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_path = tmp_path / "index"
    chunks = [_chunk("m-1", "klimat och företag"), _chunk("s-1", "jobb och välfärd", party="S")]
    _write_chunks(chunks_path, chunks)

    written = vector_store.build_index(chunks_path=chunks_path, persist_dir=index_path)

    store = LocalVectorStore(persist_dir=index_path)
    assert written == len(chunks)
    assert store._record_count() == len(chunks)


def test_building_into_non_empty_index_without_rebuild_fails(tmp_path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_path = tmp_path / "index"
    _write_chunks(chunks_path, [_chunk("m-1", "gammal text")])
    vector_store.build_index(chunks_path=chunks_path, persist_dir=index_path)

    _write_chunks(chunks_path, [_chunk("m-2", "ny text")])

    with pytest.raises(ExistingIndexError, match="Re-run the index build with --rebuild"):
        vector_store.build_index(chunks_path=chunks_path, persist_dir=index_path)


def test_rebuild_clears_old_records_and_matches_jsonl_count(tmp_path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_path = tmp_path / "index"
    old_chunk = _chunk("old-stale", "stale template {{ relatedSubjects.name }}")
    _write_chunks(chunks_path, [old_chunk])
    vector_store.build_index(chunks_path=chunks_path, persist_dir=index_path)

    new_chunks = [_chunk("new-1", "aktuell klimatpolitik"), _chunk("new-2", "aktuell skattepolitik")]
    _write_chunks(chunks_path, new_chunks)

    written = vector_store.build_index(chunks_path=chunks_path, persist_dir=index_path, rebuild=True)

    store = LocalVectorStore(persist_dir=index_path)
    assert written == len(new_chunks)
    assert store._record_count() == len(new_chunks)
    assert store._collection.get(ids=[old_chunk.chunk_id])["ids"] == []


def test_cli_parser_accepts_rebuild() -> None:
    args = vector_store.parse_args(["--chunks", "custom/chunks.jsonl", "--index", "custom/index", "--rebuild"])

    assert args.chunks.name == "chunks.jsonl"
    assert args.index.name == "index"
    assert args.rebuild is True


def test_cli_main_passes_rebuild_down(monkeypatch, tmp_path) -> None:
    calls = {}

    def fake_build_index(chunks_path, persist_dir, rebuild=False):
        calls["chunks_path"] = chunks_path
        calls["persist_dir"] = persist_dir
        calls["rebuild"] = rebuild
        return 0

    monkeypatch.setattr(vector_store, "build_index", fake_build_index)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "vector_store",
            "--chunks",
            str(tmp_path / "chunks.jsonl"),
            "--index",
            str(tmp_path / "index"),
            "--rebuild",
        ],
    )

    vector_store.main()

    assert calls["chunks_path"] == tmp_path / "chunks.jsonl"
    assert calls["persist_dir"] == tmp_path / "index"
    assert calls["rebuild"] is True


def test_read_chunks_handles_mixed_source_kinds_and_missing_metadata(tmp_path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    chunks = [
        _chunk("m-policy", "politik", party="M"),
        DocumentChunk(
            chunk_id="s-riksdag",
            doc_id="doc-s-riksdag",
            party="S",
            source_kind="riksdag_speech",
            title="Anförande",
            url="https://data.riksdagen.se/dokument/H8011",
            text="anförande",
            chunk_index=0,
            metadata={},
        ),
    ]
    _write_chunks(chunks_path, chunks)

    loaded = vector_store.read_chunks(chunks_path)

    assert {chunk.source_kind for chunk in loaded} == {"policy_index", "riksdag_speech"}
    assert {chunk.party for chunk in loaded} == {"M", "S"}


def test_vector_store_metadata_omits_none_values(tmp_path) -> None:
    store = LocalVectorStore(persist_dir=tmp_path / "index")
    chunk = DocumentChunk(
        chunk_id="s-riksdag",
        doc_id="doc-s-riksdag",
        party="S",
        source_kind="riksdag_speech",
        title="Anförande",
        url="https://data.riksdagen.se/dokument/H8011",
        text="anförande",
        chunk_index=0,
        metadata={"dok_id": "H8011", "dokumenttyp": None},
    )

    metadata = store._metadata(chunk)

    assert metadata["dok_id"] == "H8011"
    assert "dokumenttyp" not in metadata
