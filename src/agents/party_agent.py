from __future__ import annotations

from debate.models import Claim, PartyConfig, PartyResponse
from rag.retriever import PartyRetriever


class PartyAgent:
    def __init__(self, party: PartyConfig, retriever: PartyRetriever | None = None) -> None:
        self.party = party
        self.retriever = retriever or PartyRetriever()

    def answer(self, question: str) -> PartyResponse:
        chunks = self.retriever.retrieve(question, party=self.party.id)
        if not chunks:
            # TODO: Replace with LLM-generated response grounded in retrieved official sources.
            return PartyResponse(
                party=self.party.id,
                answer=(
                    f"{self.party.display_name}: Jag behöver indexerade officiella källor "
                    "innan jag kan ge ett källbelagt svar."
                ),
                claims=[],
            )

        claim = Claim(text=chunks[0].text, topic=question)
        return PartyResponse(party=self.party.id, answer=chunks[0].text, claims=[claim])
