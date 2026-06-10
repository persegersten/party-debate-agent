from __future__ import annotations

import re

from agents.voter_panel import DEFAULT_PERSONAS, SIMULATION_DISCLAIMER, VoterPanel, score_response
from debate.models import DebateState, Evidence, PartyResponse, VoterPersona


def evidence(title: str = "Källa") -> Evidence:
    return Evidence(
        source_title=title,
        url="https://example.com/kalla",
        quote="Detta är ett längre källcitat som ger stöd åt svaret.",
    )


def response(party: str, answer: str, with_evidence: bool = True) -> PartyResponse:
    return PartyResponse(
        party=party,
        answer=answer,
        evidence=[evidence()] if with_evidence else [],
    )


def _sentence_count(text: str) -> int:
    return len([part for part in re.split(r"[.!?]+", text) if part.strip()])


def test_default_personas_are_exactly_five_with_expected_priorities() -> None:
    assert [persona.name for persona in DEFAULT_PERSONAS] == [
        "Pensionären",
        "Studenten",
        "Småföretagaren",
        "Offentliganställda",
        "Förstagångsväljaren",
    ]
    assert DEFAULT_PERSONAS[0].priorities == ["trygghet", "vård", "pensioner"]
    assert DEFAULT_PERSONAS[1].priorities == ["klimat", "bostad", "framtidstro"]
    assert DEFAULT_PERSONAS[2].priorities == ["ekonomi", "regler", "trygghet"]
    assert DEFAULT_PERSONAS[3].priorities == ["välfärd", "arbetsvillkor", "stabilitet"]
    assert DEFAULT_PERSONAS[4].priorities == ["klimat", "jobb", "trovärdighet"]


def test_priority_matching_affects_choice() -> None:
    panel = VoterPanel([DEFAULT_PERSONAS[1]])
    state = DebateState(
        topic="frågan",
        question="Vad vill ni göra?",
        active_parties=["M", "MP"],
        responses=[
            response("M", "Vi talar om ekonomi och regler med tydliga reformer."),
            response("MP", "Vi prioriterar klimat, bostad och framtidstro med tydliga reformer."),
        ],
    )

    reactions = panel.evaluate(state)

    assert reactions[0].party == "MP"
    assert "klimat" in reactions[0].reaction.lower()


def test_evidence_improves_score_and_missing_evidence_penalizes() -> None:
    persona = VoterPersona(id="test", name="Testväljare", priorities=["välfärd"])
    supported = response("S", "Vi stärker välfärd och stabilitet med konkreta reformer.", with_evidence=True)
    unsupported = response("S", "Vi stärker välfärd och stabilitet med konkreta reformer.", with_evidence=False)

    assert score_response(persona, supported).total > score_response(persona, unsupported).total


def test_evasive_answer_scores_worse() -> None:
    persona = VoterPersona(id="test", name="Testväljare", priorities=["klimat"])
    clear = response("MP", "Vi prioriterar klimat med jobb och trovärdighet i flera konkreta steg.")
    evasive = response("MP", "Vi kan inte svara eftersom vi behöver indexerade källor.", with_evidence=False)

    assert score_response(persona, clear).total > score_response(persona, evasive).total


def test_every_persona_selects_active_party() -> None:
    panel = VoterPanel()
    state = DebateState(
        topic="frågan",
        question="Vad vill ni göra?",
        active_parties=["M", "S"],
        responses=[
            response("M", "Trygghet, ekonomi, regler och klimat är våra prioriteringar i svaret."),
            response("S", "Välfärd, vård, pensioner och arbetsvillkor är våra prioriteringar."),
        ],
    )

    reactions = panel.evaluate(state)

    assert len(reactions) == 5
    assert {reaction.party for reaction in reactions} <= {"M", "S"}
    assert all(reaction.reaction for reaction in reactions)
    assert all(_sentence_count(reaction.reaction) >= 2 for reaction in reactions)
    assert all(reaction.party in reaction.reaction for reaction in reactions)
    assert any("klimat" in reaction.reaction.lower() for reaction in reactions)
    assert any("välfärd" in reaction.reaction.lower() for reaction in reactions)


def test_simulation_disclaimer_text() -> None:
    assert SIMULATION_DISCLAIMER == "Detta är en simulering av fiktiva väljare, inte en prognos."
