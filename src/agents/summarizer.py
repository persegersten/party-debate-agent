from __future__ import annotations

from debate.models import DebateState


class Summarizer:
    def summarize(self, state: DebateState) -> str:
        parties = ", ".join(response.party for response in state.responses) or "inga partier"
        return f"Debatt om {state.topic}. Svar inkom från: {parties}."
