from __future__ import annotations

import argparse

from debate.graph import build_debate_graph
from debate.models import DebateState, load_project_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Svensk partiledardebatt-simulator")
    parser.add_argument("question", nargs="?", default="Vad vill ni göra åt klimatet?")
    parser.add_argument("--topic", default="klimat")
    parser.add_argument("--party", action="append", dest="parties", help="Parti-id att inkludera, kan anges flera gånger.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_project_config()
    known_parties = config.party_by_id()
    active_parties = args.parties or list(known_parties)
    unknown = sorted(set(active_parties) - set(known_parties))
    if unknown:
        raise SystemExit(f"Okända partier: {', '.join(unknown)}")

    graph = build_debate_graph(config)
    state = DebateState(topic=args.topic, question=args.question, active_parties=active_parties)
    result = graph.invoke(state)
    responses = result.responses if isinstance(result, DebateState) else result["responses"]
    for response in responses:
        print(f"\n[{response.party}] {response.answer}")


if __name__ == "__main__":
    main()
