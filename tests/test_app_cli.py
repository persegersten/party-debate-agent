from __future__ import annotations

import sys
from types import SimpleNamespace

import app
from debate.models import DebateState, PartyResponse, VoterPersona, VoterReaction


def test_parse_args_has_no_hardcoded_topic_default(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["app.py", "Vad vill ni göra åt välfärden?"])

    args = app.parse_args()

    assert args.question == "Vad vill ni göra åt välfärden?"
    assert args.topic is None


def test_parse_args_accepts_explicit_topic(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["app.py", "Vad vill ni göra åt välfärden?", "--topic", "välfärd"],
    )

    args = app.parse_args()

    assert args.question == "Vad vill ni göra åt välfärden?"
    assert args.topic == "välfärd"


def test_main_prints_voter_panel_disclaimer(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["app.py", "Vad vill ni göra?", "--party", "S"])
    monkeypatch.setattr(
        app,
        "load_project_config",
        lambda: SimpleNamespace(party_by_id=lambda: {"S": object()}),
    )

    class FakeGraph:
        def invoke(self, state: DebateState) -> DebateState:
            state.responses = [PartyResponse(party="S", answer="Svar")]
            state.rebuttals = [PartyResponse(party="S", answer="Replik")]
            state.summary = "Summering"
            state.voter_reactions = [
                VoterReaction(
                    voter=VoterPersona(id="pensionaren", name="Pensionären", priorities=[]),
                    party="S",
                    reaction="Kort motivering.",
                    score=3,
                )
            ]
            return state

    monkeypatch.setattr(app, "build_debate_graph", lambda _config: FakeGraph())

    app.main()

    output = capsys.readouterr().out
    assert "=== Väljarpanel ===" in output
    assert "Detta är en simulering av fiktiva väljare, inte en prognos." in output
    assert "[Pensionären] väljer S" in output
