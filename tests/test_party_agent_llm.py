from __future__ import annotations

import logging

from agents.llm_client import DEFAULT_OPENAI_MODEL, OpenAIPartyAnswerClient
from agents.party_agent import PartyAgent
from debate.models import DocumentChunk, PartyConfig, PartyResponse


class FakeRetriever:
    def __init__(self, chunks: list[DocumentChunk]) -> None:
        self.chunks = chunks
        self.calls: list[tuple[str, str]] = []

    def retrieve(self, query: str, party: str, k: int = 5) -> list[DocumentChunk]:
        self.calls.append((query, party))
        return self.chunks


class FakeLLMClient:
    def __init__(self, answer: str | None = None, raises: bool = False) -> None:
        self.answer = answer
        self.raises = raises
        self.calls: list[dict[str, str]] = []

    def generate_party_answer(self, *, party_name: str, question: str, evidence_context: str) -> str | None:
        self.calls.append(
            {
                "party_name": party_name,
                "question": question,
                "evidence_context": evidence_context,
            }
        )
        if self.raises:
            raise RuntimeError("LLM failed")
        return self.answer

    def generate_party_rebuttal(
        self,
        *,
        party_name: str,
        question: str,
        evidence_context: str,
        previous_responses_context: str,
    ) -> str | None:
        self.calls.append(
            {
                "party_name": party_name,
                "question": question,
                "evidence_context": evidence_context,
                "previous_responses_context": previous_responses_context,
            }
        )
        if self.raises:
            raise RuntimeError("LLM failed")
        return self.answer


def party() -> PartyConfig:
    return PartyConfig(id="S", name="Socialdemokraterna", display_name="Socialdemokraterna")


def chunk(text: str = "Vi vill minska utsläppen och investera i klimatomställning.") -> DocumentChunk:
    return DocumentChunk(
        chunk_id="s-1",
        doc_id="doc-s",
        party="S",
        source_kind="policy_index",
        title="Socialdemokraternas klimatpolitik",
        url="https://example.com/s-klimat",
        text=text,
        chunk_index=0,
    )


def test_answer_falls_back_when_no_chunks() -> None:
    llm = FakeLLMClient(answer="LLM svar")
    agent = PartyAgent(party=party(), retriever=FakeRetriever([]), llm_client=llm)

    response = agent.answer("Vad vill ni göra åt klimatet?")

    assert "behöver indexerade officiella källor" in response.answer
    assert response.claims == []
    assert response.evidence == []
    assert llm.calls == []


def test_answer_falls_back_when_llm_returns_none() -> None:
    agent = PartyAgent(party=party(), retriever=FakeRetriever([chunk()]), llm_client=FakeLLMClient(answer=None))

    response = agent.answer("Vad vill ni göra åt klimatet?")

    assert response.answer.startswith("Socialdemokraterna: Utifrån de officiella källor")
    assert "Socialdemokraternas klimatpolitik" in response.answer
    assert response.evidence[0].quote == "Vi vill minska utsläppen och investera i klimatomställning."
    assert response.claims[0].evidence == response.evidence


def test_answer_falls_back_when_api_key_missing(monkeypatch, caplog) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DISABLE_LLM", raising=False)
    caplog.set_level(logging.INFO)
    agent = PartyAgent(party=party(), retriever=FakeRetriever([chunk()]))

    response = agent.answer("Vad vill ni göra åt klimatet?")

    assert response.answer.startswith("Socialdemokraterna: Utifrån de officiella källor")
    assert response.evidence
    assert "OPENAI_API_KEY is not set; using deterministic fallback instead of LLM." in caplog.text


def test_answer_falls_back_when_disable_llm_true(monkeypatch, caplog) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("DISABLE_LLM", "true")
    caplog.set_level(logging.INFO)
    agent = PartyAgent(party=party(), retriever=FakeRetriever([chunk()]))

    response = agent.answer("Vad vill ni göra åt klimatet?")

    assert response.answer.startswith("Socialdemokraterna: Utifrån de officiella källor")
    assert response.claims[0].evidence == response.evidence
    assert "LLM config: DISABLE_LLM='true' interpreted as True." in caplog.text
    assert "LLM disabled by DISABLE_LLM=true; using deterministic fallback." in caplog.text
    assert "test-key" not in caplog.text


def test_answer_falls_back_when_llm_raises(caplog) -> None:
    caplog.set_level(logging.WARNING)
    agent = PartyAgent(party=party(), retriever=FakeRetriever([chunk()]), llm_client=FakeLLMClient(raises=True))

    response = agent.answer("Vad vill ni göra åt klimatet?")

    assert response.answer.startswith("Socialdemokraterna: Utifrån de officiella källor")
    assert response.evidence
    assert "LLM answer generation failed; using deterministic fallback: RuntimeError: LLM failed" in caplog.text
    assert "Vi vill minska utsläppen" not in caplog.text


def test_llm_client_is_used_when_chunks_exist_and_llm_enabled() -> None:
    llm = FakeLLMClient(answer="Vi prioriterar klimatomställning med stöd i våra officiella källor.")
    agent = PartyAgent(party=party(), retriever=FakeRetriever([chunk()]), llm_client=llm)

    response = agent.answer("Vad vill ni göra åt klimatet?")

    assert response.answer == "Vi prioriterar klimatomställning med stöd i våra officiella källor."
    assert llm.calls == [
        {
            "party_name": "Socialdemokraterna",
            "question": "Vad vill ni göra åt klimatet?",
            "evidence_context": (
                "1. Socialdemokraternas klimatpolitik: "
                "Vi vill minska utsläppen och investera i klimatomställning."
            ),
        }
    ]


def test_evidence_and_claims_are_populated_from_chunks() -> None:
    agent = PartyAgent(party=party(), retriever=FakeRetriever([chunk("  Rad ett.\nRad två.  ")]), llm_client=FakeLLMClient())

    response = agent.answer("Vad vill ni göra åt klimatet?")

    assert len(response.evidence) == 1
    assert response.evidence[0].source_title == "Socialdemokraternas klimatpolitik"
    assert str(response.evidence[0].url) == "https://example.com/s-klimat"
    assert response.evidence[0].quote == "Rad ett. Rad två."
    assert response.evidence[0].relevance == 1.0
    assert len(response.claims) == 1
    assert response.claims[0].topic == "Vad vill ni göra åt klimatet?"
    assert response.claims[0].evidence == response.evidence


def test_reply_uses_own_evidence_and_previous_responses() -> None:
    llm = FakeLLMClient(answer="Vi står fast vid vår linje och bemöter bara det som sagts.")
    previous = [
        PartyResponse(party="M", answer="Moderaterna vill sänka skatten."),
        PartyResponse(party="S", answer="Socialdemokraterna vill investera i klimatomställning."),
    ]
    agent = PartyAgent(party=party(), retriever=FakeRetriever([chunk()]), llm_client=llm)

    response = agent.reply("Vad vill ni göra åt klimatet?", previous)

    assert response.answer == "Vi står fast vid vår linje och bemöter bara det som sagts."
    assert response.claims[0].evidence == response.evidence
    assert llm.calls == [
        {
            "party_name": "Socialdemokraterna",
            "question": "Vad vill ni göra åt klimatet?",
            "evidence_context": (
                "1. Socialdemokraternas klimatpolitik: "
                "Vi vill minska utsläppen och investera i klimatomställning."
            ),
            "previous_responses_context": (
                "M: Moderaterna vill sänka skatten.\n"
                "S: Socialdemokraterna vill investera i klimatomställning."
            ),
        }
    ]


def test_reply_falls_back_when_llm_disabled_style_client_returns_none() -> None:
    agent = PartyAgent(party=party(), retriever=FakeRetriever([chunk()]), llm_client=FakeLLMClient(answer=None))

    response = agent.reply("Vad vill ni göra åt klimatet?", [])

    assert response.answer.startswith("Socialdemokraterna: I replik")
    assert response.evidence[0].source_title == "Socialdemokraternas klimatpolitik"
    assert response.claims[0].evidence == response.evidence


def test_openai_client_logs_model_when_enabled(monkeypatch, caplog) -> None:
    monkeypatch.delenv("DISABLE_LLM", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "secret-test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-mini")
    caplog.set_level(logging.INFO)

    client = OpenAIPartyAnswerClient()

    assert client.model == "gpt-4.1-mini"
    assert "LLM enabled; using OpenAI model: gpt-4.1-mini" in caplog.text
    assert "secret-test-key" not in caplog.text


def test_openai_client_uses_and_logs_default_model(monkeypatch, caplog) -> None:
    monkeypatch.delenv("DISABLE_LLM", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "secret-test-key")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    caplog.set_level(logging.INFO)

    client = OpenAIPartyAnswerClient()

    assert client.model == DEFAULT_OPENAI_MODEL
    assert f"OPENAI_MODEL is not set; using default OpenAI model: {DEFAULT_OPENAI_MODEL}" in caplog.text
    assert f"LLM enabled; using OpenAI model: {DEFAULT_OPENAI_MODEL}" in caplog.text
    assert "secret-test-key" not in caplog.text
