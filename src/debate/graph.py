from __future__ import annotations

from collections.abc import Callable

from agents.llm_client import OpenAIPartyAnswerClient
from agents.party_agent import PartyAgent
from debate.models import DebateState, ProjectConfig, load_project_config


def build_party_agents(config: ProjectConfig) -> dict[str, PartyAgent]:
    """Create one party agent per config entry without hardcoded party logic."""
    llm_client = OpenAIPartyAnswerClient()
    return {party.id: PartyAgent(party=party, llm_client=llm_client) for party in config.parties}


def build_debate_graph(config: ProjectConfig | None = None) -> Callable:
    try:
        from langgraph.graph import END, StateGraph
    except ModuleNotFoundError as exc:
        raise RuntimeError("LangGraph is required to build the debate graph. Install with `pip install -e .`.") from exc

    config = config or load_project_config()
    party_agents = build_party_agents(config)

    graph = StateGraph(DebateState)

    def answer_round(state: DebateState) -> DebateState:
        active_parties = state.active_parties or list(party_agents)
        for party_id in active_parties:
            state.responses.append(party_agents[party_id].answer(state.question))
        return state

    graph.add_node("party_round", answer_round)
    graph.set_entry_point("party_round")
    graph.add_edge("party_round", END)
    return graph.compile()
