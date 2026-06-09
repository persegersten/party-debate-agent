from pathlib import Path

from debate.models import load_project_config


def test_config_can_be_loaded() -> None:
    config = load_project_config(Path("data/config"))

    assert {party.id for party in config.parties} == {"S", "M", "MP"}
    assert len(config.sources) == 6


def test_all_sources_reference_valid_party() -> None:
    config = load_project_config(Path("data/config"))
    party_ids = {party.id for party in config.parties}

    assert all(source.party in party_ids for source in config.sources)
