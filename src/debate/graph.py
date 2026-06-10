from __future__ import annotations

from collections.abc import Callable

from agents.llm_client import OpenAIPartyAnswerClient
from agents.party_agent import PartyAgent
from debate.models import DebateState, ProjectConfig, load_project_config


def build_party_agents(config: ProjectConfig) -> dict[str, PartyAgent]:
    """Create one party agent per config entry without hardcoded party logic."""
    llm_client = OpenAIPartyAnswerClient()
    return {party.id: PartyAgent(party=party, llm_client=llm_client) for party in config.parties}


def _moderator_summary(state: DebateState) -> str:
    opening_parties = ", ".join(response.party for response in state.responses) or "inga partier"
    rebuttal_parties = ", ".join(response.party for response in state.rebuttals) or "inga partier"
    topic_note = "" if state.topic == "frågan" else f" Ämnet angavs som {state.topic}."
    if len(state.responses) <= 1:
        return (
            f'Moderator: I debatten om frågan "{state.question}" hade vi öppningssvar från {opening_parties} '
            f"och replik från {rebuttal_parties}. Med bara ett aktivt parti framgår främst partiets egen linje."
            f"{topic_note}"
        )

    return (
        f'Moderator: I debatten om frågan "{state.question}" syns både gemensamma prioriteringar och skillnader mellan '
        f"{opening_parties}. Öppningsrundan gav partiernas huvudlinjer, och replikrundan från {rebuttal_parties} "
        "förtydligade var partierna håller fast vid sina egna förslag eller markerar skillnader mot andra svar."
        f"{topic_note}"
    )


def build_debate_graph(config: ProjectConfig | None = None) -> Callable:
    try:
        from langgraph.graph import END, StateGraph
    except ModuleNotFoundError as exc:
        raise RuntimeError("LangGraph is required to build the debate graph. Install with `pip install -e .`.") from exc

    config = config or load_project_config()
    party_agents = build_party_agents(config)

    graph = StateGraph(DebateState)

    def opening_round(state: DebateState) -> DebateState:
        active_parties = state.active_parties or list(party_agents)
        for party_id in active_parties:
            state.responses.append(party_agents[party_id].answer(state.question))
        return state

    def rebuttal_round(state: DebateState) -> DebateState:
        active_parties = state.active_parties or list(party_agents)
        previous_responses = list(state.responses)
        for party_id in active_parties:
            state.rebuttals.append(party_agents[party_id].reply(state.question, previous_responses))
        return state

    def moderator_summary(state: DebateState) -> DebateState:
        state.summary = _moderator_summary(state)
        return state

    graph.add_node("opening_round", opening_round)
    graph.add_node("rebuttal_round", rebuttal_round)
    graph.add_node("moderator_summary", moderator_summary)
    graph.set_entry_point("opening_round")
    graph.add_edge("opening_round", "rebuttal_round")
    graph.add_edge("rebuttal_round", "moderator_summary")
    graph.add_edge("moderator_summary", END)
    return graph.compile()
