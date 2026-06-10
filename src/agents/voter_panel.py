from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from debate.models import (
    DebateState,
    FactCheckResult,
    PartyResponse,
    VoterDecision,
    VoterPersona,
    VoterReaction,
    VoterVoiceProfile,
)

SIMULATION_DISCLAIMER = "Detta är en simulering av fiktiva väljare, inte en prognos."
SpiceLevel = Literal["calm", "lively", "wild"]

EVASIVE_PHRASES = (
    "inte tillräckligt",
    "saknar stöd",
    "indexerade källor",
    "kan inte",
    "otydligt",
    "behöver indexerade källor",
    "återkommer",
    "utreda vidare",
)

FALLBACK_STARTS = {
    "pensionaren": "Jag går på {party} här.",
    "studenten": "{party} får min röst.",
    "smaforetagaren": "{party} vinner hos mig.",
    "offentliganstallda": "Jag landar i {party}.",
    "forstagangsvaljaren": "Min röst hamnar hos {party}.",
}

CALM_STARTS = {
    "pensionaren": "Jag väljer {party} efter att ha vägt tryggheten.",
    "studenten": "Mitt val blir {party}.",
    "smaforetagaren": "För mig blir det {party}.",
    "offentliganstallda": "Jag tycker att {party} höll bäst.",
    "forstagangsvaljaren": "{party} får min röst.",
}

WILD_STARTS = {
    "pensionaren": "{party} tar hem min röst, även om kaffet inte hann kallna av spänning.",
    "studenten": "{party} får rösten, trots ett par mentala suckar på vägen.",
    "smaforetagaren": "{party} går genom kassan hos mig.",
    "offentliganstallda": "{party} klarar måndagsmorgon-testet bäst.",
    "forstagangsvaljaren": "Jag landar hos {party}, med ena ögonbrynet uppe.",
}


DEFAULT_PERSONAS = [
    VoterPersona(
        id="pensionaren",
        name="Pensionären",
        priorities=["trygghet", "vård", "pensioner"],
        voice=VoterVoiceProfile(
            tone="erfaren, jordnära, lite misstänksam",
            sentence_style="kort, tydligt, ibland syrligt",
            favorite_phrases=[
                "Det där lät tryggt.",
                "Jag har hört många löften i mina dagar.",
                "Det fina talet betalar inte hemtjänsten.",
            ],
            skepticism_phrases=[
                "Det där var mer affisch än besked.",
                "Jag vill veta vem som faktiskt gör jobbet.",
            ],
            metaphor_domains=["vardag", "kaffebord", "kommunpolitik"],
        ),
    ),
    VoterPersona(
        id="studenten",
        name="Studenten",
        priorities=["klimat", "bostad", "framtidstro"],
        voice=VoterVoiceProfile(
            tone="snabb, idealistisk, otålig",
            sentence_style="energiskt, värderande",
            favorite_phrases=[
                "Okej, det där kändes faktiskt framtid.",
                "Jag köper riktningen, men inte fluffet.",
                "Det luktar powerpoint utan plan.",
            ],
            skepticism_phrases=[
                "Ni kan inte bara säga 'satsning' och gå hem.",
                "Jag vill höra vad som händer nu, inte 2047.",
            ],
            metaphor_domains=["framtid", "campus", "klimatångest"],
        ),
    ),
    VoterPersona(
        id="smaforetagaren",
        name="Småföretagaren",
        priorities=["ekonomi", "regler", "trygghet"],
        voice=VoterVoiceProfile(
            tone="rak, praktisk, otålig med byråkrati",
            sentence_style="konkret, affärsmässigt",
            favorite_phrases=[
                "Det där går att jobba med.",
                "Mindre snack, mer verkstad.",
                "Jag hörde åtminstone en plan.",
            ],
            skepticism_phrases=[
                "Det där låter som tre blanketter och ett samråd.",
                "Vem ska betala och när?",
            ],
            metaphor_domains=["företag", "kassaapparat", "verkstad"],
        ),
    ),
    VoterPersona(
        id="offentliganstallda",
        name="Offentliganställda",
        priorities=["välfärd", "arbetsvillkor", "stabilitet"],
        voice=VoterVoiceProfile(
            tone="saklig, trött på floskler, ansvarstagande",
            sentence_style="resonerande men ganska rak",
            favorite_phrases=[
                "Det där skulle faktiskt kunna fungera i verkligheten.",
                "Jag lyssnar efter sådant som håller en måndag morgon.",
                "Välfärd byggs inte av slogans.",
            ],
            skepticism_phrases=[
                "Det där lät som ännu en reform utan personal.",
                "Jag saknade svar på vem som ska bära arbetet.",
            ],
            metaphor_domains=["arbetsplats", "schema", "välfärdsmaskineri"],
        ),
    ),
    VoterPersona(
        id="forstagangsvaljaren",
        name="Förstagångsväljaren",
        priorities=["klimat", "jobb", "trovärdighet"],
        voice=VoterVoiceProfile(
            tone="kort, ifrågasättande, snabb i omdömet",
            sentence_style="kortare meningar, tydliga reaktioner",
            favorite_phrases=[
                "Det där landade faktiskt.",
                "Okej, jag fattar poängen.",
                "Det kändes mindre fejk än resten.",
            ],
            skepticism_phrases=[
                "Det där var lite väl kampanjfilm.",
                "Jag vill ha mer än snygga ord.",
            ],
            metaphor_domains=["sociala medier", "framtid", "första jobbet"],
        ),
    ),
]


@dataclass(frozen=True)
class ResponseScore:
    party: str
    total: float
    priority_matches: int
    evidence_score: float
    clarity_score: float
    evasiveness_penalty: float


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


def _response_evidence_score(response: PartyResponse) -> float:
    evidence = response.evidence or [evidence for claim in response.claims for evidence in claim.evidence]
    usable_quotes = [item for item in evidence if len(item.quote.strip()) >= 25]
    source_titles = {item.source_title for item in usable_quotes if item.source_title}
    score = min(len(usable_quotes), 2)
    if len(source_titles) > 1:
        score += 1
    return float(score)


def _fact_check_score(response: PartyResponse, fact_checks: list[FactCheckResult]) -> float:
    claim_texts = {claim.text for claim in response.claims}
    if not claim_texts:
        return 0.0
    score = 0.0
    for check in fact_checks:
        if check.claim.text not in claim_texts:
            continue
        if check.verdict == "supported":
            score += 1.5
        elif check.verdict == "partly_supported":
            score += 0.75
        elif check.verdict == "unsupported":
            score -= 1.5
    return score


def _clarity_score(response: PartyResponse) -> float:
    answer = response.answer.strip()
    if len(answer) < 80:
        return 0.0
    sentences = _sentence_count(answer)
    if 2 <= sentences <= 8:
        return 2.0
    return 1.0


def _evasiveness_penalty(persona: VoterPersona, response: PartyResponse) -> float:
    text = response.answer.lower()
    penalty = float(sum(1 for phrase in EVASIVE_PHRASES if phrase in text))
    if not response.evidence and not any(claim.evidence for claim in response.claims):
        penalty += 1.0
    if _priority_matches(persona, response) == 0 and len(response.answer) < 180:
        penalty += 1.0
    return penalty


def score_response(
    persona: VoterPersona,
    response: PartyResponse,
    fact_checks: list[FactCheckResult] | None = None,
) -> ResponseScore:
    priority_matches = _priority_matches(persona, response)
    evidence_score = _response_evidence_score(response) + _fact_check_score(response, fact_checks or [])
    clarity_score = _clarity_score(response)
    evasiveness_penalty = _evasiveness_penalty(persona, response)
    total = priority_matches * 3.0 + evidence_score + clarity_score - evasiveness_penalty
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


def _evidence_quality(score: ResponseScore) -> Literal["weak", "medium", "strong"]:
    if score.evidence_score >= 2.5:
        return "strong"
    if score.evidence_score >= 1.0:
        return "medium"
    return "weak"


def _matched_priorities(persona: VoterPersona, response: PartyResponse) -> list[str]:
    text = _combined_text(response)
    return [priority for priority in persona.priorities if priority.lower() in text]


def _reason_for(persona: VoterPersona, score: ResponseScore, response: PartyResponse) -> str:
    matched = _matched_priorities(persona, response)
    if matched:
        return f"svaret träffade {', '.join(matched)}"
    if score.clarity_score >= 2:
        return "svaret var tydligare än alternativen"
    return "svaret gav ändå bäst samlad träff bland alternativen"


def _concern_for(score: ResponseScore) -> str:
    if score.evasiveness_penalty >= 2:
        return "vissa delar lät undvikande"
    if score.evidence_score < 1:
        return "källstödet var tunt"
    if score.clarity_score < 2:
        return "tydligheten kunde vara bättre"
    return "det finns fortfarande detaljer som behöver bli skarpare"


def score_voter_decision(
    persona: VoterPersona,
    party_responses: dict[str, PartyResponse],
    fact_checks: list[FactCheckResult],
) -> VoterDecision:
    scored = [score_response(persona, response, fact_checks) for response in party_responses.values()]
    if not scored:
        return VoterDecision(
            persona_id=persona.id,
            selected_party="",
            score_by_party={},
            strongest_reason="inga partisvar fanns att bedöma",
            biggest_concern="inga partisvar fanns att bedöma",
            evidence_quality="weak",
        )

    party_order = list(party_responses)
    best = max(
        scored,
        key=lambda item: (
            item.total,
            item.evidence_score,
            item.clarity_score,
            -party_order.index(item.party),
        ),
    )
    response = party_responses[best.party]
    return VoterDecision(
        persona_id=persona.id,
        selected_party=best.party,
        score_by_party={item.party: item.total for item in scored},
        strongest_reason=_reason_for(persona, best, response),
        biggest_concern=_concern_for(best),
        evidence_quality=_evidence_quality(best),
    )


def _ensure_sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    return text if text[-1] in ".!?" else f"{text}."


def _start_for(persona: VoterPersona, party: str, spice_level: SpiceLevel) -> str:
    starts = {"calm": CALM_STARTS, "lively": FALLBACK_STARTS, "wild": WILD_STARTS}[spice_level]
    return _ensure_sentence(starts.get(persona.id, "{party} får min röst.").format(party=party))


def _favorite_phrase(persona: VoterPersona, spice_level: SpiceLevel) -> str:
    phrases = persona.voice.favorite_phrases
    if not phrases:
        return ""
    offset = {"calm": 0, "lively": 1, "wild": 2}[spice_level]
    return phrases[offset % len(phrases)]


def _skepticism_phrase(persona: VoterPersona, spice_level: SpiceLevel) -> str:
    phrases = persona.voice.skepticism_phrases
    if not phrases:
        return ""
    offset = {"calm": 0, "lively": 1, "wild": 0}[spice_level]
    return phrases[offset % len(phrases)]


def _phrase_fragment(phrase: str) -> str:
    return phrase.strip().rstrip(".!?").strip()


def _reasoning_sentence(persona: VoterPersona, decision: VoterDecision, spice_level: SpiceLevel) -> str:
    phrase = _phrase_fragment(_favorite_phrase(persona, spice_level))
    if spice_level == "calm":
        return _ensure_sentence(f"{decision.strongest_reason.capitalize()}, med {decision.evidence_quality} evidenskvalitet")
    if spice_level == "wild" and phrase:
        return _ensure_sentence(f"{phrase}, framför allt för att {decision.strongest_reason}")
    if phrase:
        return _ensure_sentence(f"{phrase}, och tyngst vägde att {decision.strongest_reason}")
    return _ensure_sentence(f"Det vägde tyngst att {decision.strongest_reason}")


def _concern_sentence(persona: VoterPersona, decision: VoterDecision, spice_level: SpiceLevel) -> str:
    phrase = _phrase_fragment(_skepticism_phrase(persona, spice_level))
    if spice_level == "calm":
        return _ensure_sentence(f"Min invändning är att {decision.biggest_concern}")
    if spice_level == "wild" and phrase:
        return _ensure_sentence(f"Men {decision.biggest_concern}; {phrase.lower()}")
    if phrase:
        return _ensure_sentence(f"Men {decision.biggest_concern}, och {phrase.lower()}")
    return _ensure_sentence(f"Men {decision.biggest_concern}")


def render_voter_reaction(
    persona: VoterPersona,
    decision: VoterDecision,
    party_responses: dict[str, PartyResponse],
    spice_level: SpiceLevel = "lively",
) -> VoterReaction:
    if spice_level not in ("calm", "lively", "wild"):
        raise ValueError("spice_level must be calm, lively or wild")
    return VoterReaction(
        persona_id=persona.id,
        persona_name=persona.name,
        selected_party=decision.selected_party,
        one_liner=_start_for(persona, decision.selected_party, spice_level),
        reasoning=_reasoning_sentence(persona, decision, spice_level),
        concern=_concern_sentence(persona, decision, spice_level),
    )


def _first_two_words(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.lower())[:2])


def _de_template(reactions: list[VoterReaction], decisions: dict[str, VoterDecision]) -> list[VoterReaction]:
    seen_one_liners: set[str] = set()
    seen_starts: set[str] = set()
    updated: list[VoterReaction] = []
    for reaction in reactions:
        one_liner = reaction.one_liner
        start = _first_two_words(one_liner)
        if one_liner in seen_one_liners or (start and start in seen_starts):
            decision = decisions[reaction.persona_id]
            fallback = FALLBACK_STARTS.get(reaction.persona_id, "{party} får min röst.").format(
                party=decision.selected_party
            )
            one_liner = _ensure_sentence(fallback)
        seen_one_liners.add(one_liner)
        if _first_two_words(one_liner):
            seen_starts.add(_first_two_words(one_liner))
        updated.append(reaction.model_copy(update={"one_liner": one_liner}))
    return updated


def run_voter_panel(
    party_responses: dict[str, PartyResponse],
    fact_checks: list[FactCheckResult],
    spice_level: SpiceLevel = "lively",
    personas: list[VoterPersona] | None = None,
) -> list[VoterReaction]:
    voters = personas or list(DEFAULT_PERSONAS)
    decisions: dict[str, VoterDecision] = {}
    reactions: list[VoterReaction] = []
    for persona in voters:
        decision = score_voter_decision(persona, party_responses, fact_checks)
        decisions[persona.id] = decision
        if not decision.selected_party:
            continue
        reactions.append(render_voter_reaction(persona, decision, party_responses, spice_level))
    return _de_template(reactions, decisions)


class VoterPanel:
    def __init__(self, voters: list[VoterPersona] | None = None, spice_level: SpiceLevel = "lively") -> None:
        self.voters = voters or list(DEFAULT_PERSONAS)
        self.spice_level = spice_level

    def evaluate(self, state: DebateState) -> list[VoterReaction]:
        active_parties = state.active_parties or sorted({response.party for response in state.responses + state.rebuttals})
        responses_by_party = _response_by_party(state.responses + state.rebuttals)
        party_responses = {
            party: responses_by_party[party]
            for party in active_parties
            if party in responses_by_party
        }
        return run_voter_panel(
            party_responses=party_responses,
            fact_checks=state.fact_checks,
            spice_level=self.spice_level,
            personas=self.voters,
        )


def evaluate_voter_panel(
    state: DebateState,
    panel: VoterPanel | None = None,
    spice_level: SpiceLevel = "lively",
) -> DebateState:
    state.voter_reactions = (panel or VoterPanel(spice_level=spice_level)).evaluate(state)
    return state
