from __future__ import annotations

from debate import graph as debate_graph
from debate.models import DebateState, PartyConfig, PartyResponse, ProjectConfig


class FakePartyAgent:
    def __init__(self, party_id: str, calls: list[str]) -> None:
        self.party_id = party_id
        self.calls = calls

    def answer(self, question: str) -> PartyResponse:
        self.calls.append(f"answer:{self.party_id}:{question}")
        return PartyResponse(party=self.party_id, answer=f"{self.party_id} opening")

    def reply(self, question: str, previous_responses: list[PartyResponse]) -> PartyResponse:
        previous = ",".join(response.party for response in previous_responses)
        self.calls.append(f"reply:{self.party_id}:{question}:{previous}")
        return PartyResponse(party=self.party_id, answer=f"{self.party_id} rebuttal")


def test_debate_graph_runs_opening_rebuttal_and_summary(monkeypatch) -> None:
    calls: list[str] = []
    config = ProjectConfig(
        parties=[
            PartyConfig(id="S", name="Socialdemokraterna", display_name="Socialdemokraterna"),
            PartyConfig(id="M", name="Moderaterna", display_name="Moderaterna"),
        ],
        sources=[],
    )

    def fake_build_party_agents(config: ProjectConfig) -> dict[str, FakePartyAgent]:
        return {party.id: FakePartyAgent(party.id, calls) for party in config.parties}

    monkeypatch.setattr(debate_graph, "build_party_agents", fake_build_party_agents)
    compiled_graph = debate_graph.build_debate_graph(config)

    result = compiled_graph.invoke(
        DebateState(topic="klimat", question="Vad vill ni göra?", active_parties=["S", "M"])
    )

    state = DebateState.model_validate(result)
    assert [response.party for response in state.responses] == ["S", "M"]
    assert [response.answer for response in state.responses] == ["S opening", "M opening"]
    assert [response.party for response in state.rebuttals] == ["S", "M"]
    assert [response.answer for response in state.rebuttals] == ["S rebuttal", "M rebuttal"]
    assert state.summary
    assert "Moderator:" in state.summary
    assert calls == [
        "answer:S:Vad vill ni göra?",
        "answer:M:Vad vill ni göra?",
        "reply:S:Vad vill ni göra?:S,M",
        "reply:M:Vad vill ni göra?:S,M",
    ]


def test_moderator_summary_uses_question_when_topic_is_neutral(monkeypatch) -> None:
    calls: list[str] = []
    config = ProjectConfig(
        parties=[
            PartyConfig(id="M", name="Moderaterna", display_name="Moderaterna"),
            PartyConfig(id="S", name="Socialdemokraterna", display_name="Socialdemokraterna"),
        ],
        sources=[],
    )

    def fake_build_party_agents(config: ProjectConfig) -> dict[str, FakePartyAgent]:
        return {party.id: FakePartyAgent(party.id, calls) for party in config.parties}

    monkeypatch.setattr(debate_graph, "build_party_agents", fake_build_party_agents)
    compiled_graph = debate_graph.build_debate_graph(config)

    result = compiled_graph.invoke(
        DebateState(topic="frågan", question="Vad vill ni göra åt välfärden?", active_parties=["M", "S"])
    )

    state = DebateState.model_validate(result)
    assert state.summary
    assert "klimat" not in state.summary.lower()
    assert 'frågan "Vad vill ni göra åt välfärden?"' in state.summary


def test_moderator_summary_can_include_explicit_topic(monkeypatch) -> None:
    calls: list[str] = []
    config = ProjectConfig(
        parties=[
            PartyConfig(id="M", name="Moderaterna", display_name="Moderaterna"),
            PartyConfig(id="S", name="Socialdemokraterna", display_name="Socialdemokraterna"),
        ],
        sources=[],
    )

    def fake_build_party_agents(config: ProjectConfig) -> dict[str, FakePartyAgent]:
        return {party.id: FakePartyAgent(party.id, calls) for party in config.parties}

    monkeypatch.setattr(debate_graph, "build_party_agents", fake_build_party_agents)
    compiled_graph = debate_graph.build_debate_graph(config)

    result = compiled_graph.invoke(
        DebateState(topic="välfärd", question="Vad vill ni göra åt välfärden?", active_parties=["M", "S"])
    )

    state = DebateState.model_validate(result)
    assert state.summary
    assert 'frågan "Vad vill ni göra åt välfärden?"' in state.summary
    assert "Ämnet angavs som välfärd." in state.summary
