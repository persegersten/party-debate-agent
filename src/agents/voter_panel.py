from __future__ import annotations

import re
from dataclasses import dataclass

from debate.models import DebateState, Evidence, PartyResponse, VoterPersona, VoterReaction

SIMULATION_DISCLAIMER = "Detta är en simulering av fiktiva väljare, inte en prognos."

EVASIVE_PHRASES = (
    "inte tillräckligt",
    "saknar stöd",
    "indexerade källor",
    "kan inte",
    "otydligt",
    "behöver indexerade källor",
)


DEFAULT_PERSONAS = [
    VoterPersona(
        id="pensionaren",
        name="Pensionären",
        priorities=["trygghet", "vård", "pensioner"],
    ),
    VoterPersona(
        id="studenten",
        name="Studenten",
        priorities=["klimat", "bostad", "framtidstro"],
    ),
    VoterPersona(
        id="smaforetagaren",
        name="Småföretagaren",
        priorities=["ekonomi", "regler", "trygghet"],
    ),
    VoterPersona(
        id="offentliganstallda",
        name="Offentliganställda",
        priorities=["välfärd", "arbetsvillkor", "stabilitet"],
    ),
    VoterPersona(
        id="forstagangsvaljaren",
        name="Förstagångsväljaren",
        priorities=["klimat", "jobb", "trovärdighet"],
    ),
]


@dataclass(frozen=True)
class ResponseScore:
    party: str
    total: int
    priority_matches: int
    evidence_score: int
    clarity_score: int
    evasiveness_penalty: int


def _combined_text(response: PartyResponse) -> str:
    parts = [response.answer]
    parts.extend(claim.text for claim in response.claims)
    parts.extend(evidence.quote for evidence in response.evidence)
    for claim in response.claims:
        parts.extend(evidence.quote for evidence in claim.evidence)
    return " ".join(part for part in parts if part).lower()


def _sentence_count(text: str) -> int:
    return len([part for part in re.split(r"[.!?]+", text) if part.strip()])


def _priority_matches(persona: VoterPersona, response: PartyResponse) -> int:
    text = _combined_text(response)
    return sum(1 for priority in persona.priorities if priority.lower() in text)


def _evidence_score(response: PartyResponse) -> int:
    evidence = response.evidence or [evidence for claim in response.claims for evidence in claim.evidence]
    usable_quotes = [item for item in evidence if len(item.quote.strip()) >= 25]
    source_titles = {item.source_title for item in usable_quotes if item.source_title}
    score = min(len(usable_quotes), 2)
    if len(source_titles) > 1:
        score += 1
    return score


def _clarity_score(response: PartyResponse) -> int:
    answer = response.answer.strip()
    if len(answer) < 80:
        return 0
    sentences = _sentence_count(answer)
    if 2 <= sentences <= 8:
        return 2
    return 1


def _evasiveness_penalty(persona: VoterPersona, response: PartyResponse) -> int:
    text = response.answer.lower()
    penalty = sum(1 for phrase in EVASIVE_PHRASES if phrase in text)
    if not response.evidence:
        penalty += 1
    if _priority_matches(persona, response) == 0 and len(response.answer) < 180:
        penalty += 1
    return penalty


def score_response(persona: VoterPersona, response: PartyResponse) -> ResponseScore:
    priority_matches = _priority_matches(persona, response)
    evidence_score = _evidence_score(response)
    clarity_score = _clarity_score(response)
    evasiveness_penalty = _evasiveness_penalty(persona, response)
    total = priority_matches * 3 + evidence_score + clarity_score - evasiveness_penalty
    return ResponseScore(
        party=response.party,
        total=total,
        priority_matches=priority_matches,
        evidence_score=evidence_score,
        clarity_score=clarity_score,
        evasiveness_penalty=evasiveness_penalty,
    )


def _response_by_party(responses: list[PartyResponse]) -> dict[str, PartyResponse]:
    by_party: dict[str, PartyResponse] = {}
    for response in responses:
        by_party[response.party] = response
    return by_party


def _persona_role(persona: VoterPersona) -> str:
    return {
        "Pensionären": "pensionär",
        "Studenten": "student",
        "Småföretagaren": "småföretagare",
        "Offentliganställda": "offentliganställd",
        "Förstagångsväljaren": "förstagångsväljare",
    }.get(persona.name, persona.name.lower())


def _reaction_text(persona: VoterPersona, score: ResponseScore, response: PartyResponse) -> str:
    matched_priorities = [priority for priority in persona.priorities if priority.lower() in _combined_text(response)]
    matched_text = ", ".join(matched_priorities) if matched_priorities else "inga av personans prioriteringar"
    evidence_text = "starkt källstöd" if score.evidence_score >= 2 else "svagare källstöd"
    clarity_text = "tydligt" if score.clarity_score >= 2 else "mindre tydligt"
    evasive_clause = (
        "de andra svaren kändes svagare eller mer undvikande, så det här valet gav mest förtroende"
        if score.evasiveness_penalty or score.priority_matches == 0
        else f"de andra svaren matchade sämre mot {persona.name.lower()}s prioriteringar"
    )
    first_sentence = (
        f"Jag väljer {response.party} eftersom svaret tydligast träffade {matched_text} "
        f"och kändes {clarity_text} i förhållande till mina prioriteringar som {_persona_role(persona)}."
    )
    second_sentence = (
        f"Det fanns {evidence_text}, och {evasive_clause}, vilket gjorde att {response.party} passade bäst för mig."
    )
    return f"{first_sentence} {second_sentence}"


class VoterPanel:
    def __init__(self, voters: list[VoterPersona] | None = None) -> None:
        self.voters = voters or list(DEFAULT_PERSONAS)

    def evaluate(self, state: DebateState) -> list[VoterReaction]:
        active_parties = state.active_parties or sorted({response.party for response in state.responses + state.rebuttals})
        responses_by_party = _response_by_party(state.responses + state.rebuttals)
        available_responses = [
            responses_by_party[party]
            for party in active_parties
            if party in responses_by_party
        ]
        reactions: list[VoterReaction] = []
        for persona in self.voters:
            scored = [score_response(persona, response) for response in available_responses]
            if not scored:
                continue
            best = max(
                scored,
                key=lambda item: (
                    item.total,
                    item.evidence_score,
                    item.clarity_score,
                    -active_parties.index(item.party) if item.party in active_parties else 0,
                ),
            )
            response = responses_by_party[best.party]
            reactions.append(
                VoterReaction(
                    voter=persona,
                    party=best.party,
                    reaction=_reaction_text(persona, best, response),
                    score=max(1, min(5, best.total)),
                )
            )
        return reactions


def evaluate_voter_panel(state: DebateState, panel: VoterPanel | None = None) -> DebateState:
    state.voter_reactions = (panel or VoterPanel()).evaluate(state)
    return state
