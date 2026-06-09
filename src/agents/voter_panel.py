from __future__ import annotations

from debate.models import PartyResponse, VoterPersona, VoterReaction


class VoterPanel:
    def __init__(self, voters: list[VoterPersona]) -> None:
        self.voters = voters

    def react(self, response: PartyResponse) -> list[VoterReaction]:
        # TODO: Let personas evaluate responses based on priorities and evidence quality.
        return [
            VoterReaction(voter=voter, party=response.party, reaction="Ingen bedömning ännu.", score=3)
            for voter in self.voters
        ]
