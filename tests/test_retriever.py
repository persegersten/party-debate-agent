from debate.models import DocumentChunk
from rag.retriever import PartyRetriever
from rag.vector_store import LocalVectorStore


def test_retriever_filters_by_party(tmp_path) -> None:
    store = LocalVectorStore(persist_dir=tmp_path / "index")
    store._collection = None
    store.add_chunks(
        [
            DocumentChunk(
                chunk_id="s-1",
                doc_id="doc-s",
                party="S",
                source_kind="policy_index",
                title="S politik",
                url="https://example.com/s",
                text="klimat jobb välfärd",
                chunk_index=0,
                metadata={"official_source": True},
            ),
            DocumentChunk(
                chunk_id="m-1",
                doc_id="doc-m",
                party="M",
                source_kind="policy_index",
                title="M politik",
                url="https://example.com/m",
                text="klimat skatter företag",
                chunk_index=0,
                metadata={"official_source": True},
            ),
        ]
    )
    retriever = PartyRetriever(vector_store=store)

    evidence = retriever.retrieve_for_party("M", "klimat", k=5)

    assert len(evidence) == 1
    assert evidence[0].source_title == "M politik"
