from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from debate.graph import build_debate_graph
from debate.models import DebateState, load_project_config
from agents.voter_panel import SIMULATION_DISCLAIMER


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Svensk partiledardebatt-simulator")
    parser.add_argument("question", nargs="?", default="Vad vill ni göra åt klimatet?")
    parser.add_argument("--topic", default=None)
    parser.add_argument("--party", action="append", dest="party", help="Parti-id att inkludera, kan anges flera gånger.")
    parser.add_argument("--parties", nargs="+", default=None, help="Parti-id:n att inkludera, exempel: --parties S M MP.")
    parser.add_argument(
        "--spice-level",
        choices=["calm", "lively", "wild"],
        default="lively",
        help="Språknivå för väljarpanelen.",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(levelname)s:%(name)s:%(message)s",
    )
    logging.getLogger("openai").setLevel(logging.WARNING)
    args = parse_args()
    config = load_project_config()
    known_parties = config.party_by_id()
    active_parties = args.parties or args.party or list(known_parties)
    unknown = sorted(set(active_parties) - set(known_parties))
    if unknown:
        raise SystemExit(f"Okända partier: {', '.join(unknown)}")

    graph = build_debate_graph(config, spice_level=args.spice_level)
    topic = args.topic or "frågan"
    logging.getLogger(__name__).info("Resolved debate question=%r topic=%r", args.question, topic)
    state = DebateState(topic=topic, question=args.question, active_parties=active_parties)
    result = graph.invoke(state)
    responses = result.responses if isinstance(result, DebateState) else result["responses"]
    rebuttals = result.rebuttals if isinstance(result, DebateState) else result["rebuttals"]
    summary = result.summary if isinstance(result, DebateState) else result.get("summary")
    voter_reactions = result.voter_reactions if isinstance(result, DebateState) else result["voter_reactions"]

    print("\n=== Opening Round ===")
    for response in responses:
        print(f"\n[{response.party}] {response.answer}")

    print("\n=== Rebuttal Round ===")
    for response in rebuttals:
        print(f"\n[{response.party}] {response.answer}")

    print("\n=== Moderator Summary ===")
    print(summary or "Moderator: Ingen summering tillgänglig.")

    print("\n=== Väljarpanel ===")
    print(SIMULATION_DISCLAIMER)
    for reaction in voter_reactions:
        print(f"\n[{reaction.voter.name}] väljer {reaction.party}")
        print(f"Motivering: {reaction.reaction}")


if __name__ == "__main__":
    main()
