from __future__ import annotations

import logging

from agents.llm_client import OpenAIPartyAnswerClient, PartyAnswerLLM, format_llm_error
from debate.models import Claim, DocumentChunk, Evidence, PartyConfig, PartyResponse
from rag.retriever import PartyRetriever

LOGGER = logging.getLogger(__name__)


def _snippet(text: str, max_length: int = 500) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 1].rstrip() + "..."


def _evidence_from_chunks(chunks: list[DocumentChunk]) -> list[Evidence]:
    return [
        Evidence(
            source_title=chunk.title,
            url=chunk.url,
            quote=_snippet(chunk.text),
            relevance=1.0,
        )
        for chunk in chunks
    ]


def _evidence_context(chunks: list[DocumentChunk]) -> str:
    lines = []
    for index, chunk in enumerate(chunks, start=1):
        lines.append(f"{index}. {chunk.title}: {_snippet(chunk.text, max_length=900)}")
    return "\n".join(lines)


def _fallback_answer(party_name: str, question: str, evidence: list[Evidence]) -> str:
    if not evidence:
        return (
            f"{party_name}: Jag behöver indexerade officiella källor "
            "innan jag kan ge ett källbelagt svar."
        )

    first = evidence[0]
    return (
        f"{party_name}: Utifrån de officiella källor som finns indexerade kan jag svara på frågan "
        f"'{question}' med stöd i {first.source_title}. {first.quote}"
    )


class PartyAgent:
    def __init__(
        self,
        party: PartyConfig,
        retriever: PartyRetriever | None = None,
        llm_client: PartyAnswerLLM | None = None,
    ) -> None:
        self.party = party
        self._retriever = retriever
        self.llm_client = llm_client or OpenAIPartyAnswerClient()

    @property
    def retriever(self) -> PartyRetriever:
        if self._retriever is None:
            self._retriever = PartyRetriever()
        return self._retriever

    def answer(self, question: str) -> PartyResponse:
        chunks = self.retriever.retrieve(question, party=self.party.id)
        if not chunks:
            return PartyResponse(
                party=self.party.id,
                answer=_fallback_answer(self.party.display_name, question, evidence=[]),
                claims=[],
                evidence=[],
            )

        evidence = _evidence_from_chunks(chunks)
        try:
            answer = self.llm_client.generate_party_answer(
                party_name=self.party.display_name,
                question=question,
                evidence_context=_evidence_context(chunks),
            )
        except Exception as exc:
            LOGGER.warning("LLM answer generation failed; using deterministic fallback: %s", format_llm_error(exc))
            answer = None
        if not answer:
            answer = _fallback_answer(self.party.display_name, question, evidence)

        claim = Claim(text=answer, topic=question, evidence=evidence)
        return PartyResponse(party=self.party.id, answer=answer, claims=[claim], evidence=evidence)
