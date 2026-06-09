from rag.vector_store import HashEmbeddingFunction


def test_hash_embedding_accepts_single_string_input() -> None:
    embeddings = HashEmbeddingFunction()("klimat och jobb")

    assert len(embeddings) == 1
    assert len(embeddings[0]) == 384


def test_hash_embedding_accepts_list_input() -> None:
    embeddings = HashEmbeddingFunction()(["klimat", "jobb"])

    assert len(embeddings) == 2
    assert all(len(vector) == 384 for vector in embeddings)


def test_embed_query_accepts_single_and_list_input() -> None:
    embedding_function = HashEmbeddingFunction()

    single = embedding_function.embed_query("klimat")
    multiple = embedding_function.embed_query(["klimat", "skola"])

    assert len(single) == 1
    assert len(multiple) == 2


def test_embed_documents_accepts_single_and_list_input() -> None:
    embedding_function = HashEmbeddingFunction()

    single = embedding_function.embed_documents("partiprogram")
    multiple = embedding_function.embed_documents(["partiprogram", "valmanifest"])

    assert len(single) == 1
    assert len(multiple) == 2


def test_hash_embedding_is_deterministic_for_same_input() -> None:
    embedding_function = HashEmbeddingFunction()

    assert embedding_function("klimatpolitik") == embedding_function("klimatpolitik")


def test_query_and_document_embeddings_use_same_dimension() -> None:
    embedding_function = HashEmbeddingFunction()

    query_vector = embedding_function.embed_query("klimat")[0]
    document_vector = embedding_function.embed_documents("klimat")[0]

    assert len(query_vector) == len(document_vector) == 384
