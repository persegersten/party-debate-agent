from pathlib import Path

from debate.graph import build_party_agents
from debate.models import load_project_config


def test_new_party_can_be_added_without_code_change(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "parties.yaml").write_text(
        """
parties:
  - id: S
    name: Socialdemokraterna
    display_name: Socialdemokraterna
    color_hint: red
  - id: C
    name: Centerpartiet
    display_name: Centerpartiet
    color_hint: green
""",
        encoding="utf-8",
    )
    (config_dir / "sources.yaml").write_text(
        """
sources:
  - party: C
    source_kind: policy_index
    title: Centerpartiets politik
    url: "https://www.centerpartiet.se/var-politik"
""",
        encoding="utf-8",
    )

    config = load_project_config(config_dir)
    agents = build_party_agents(config)

    assert "C" in agents
    assert agents["C"].party.display_name == "Centerpartiet"


def test_built_party_agents_share_llm_client(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DISABLE_LLM", "true")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "parties.yaml").write_text(
        """
parties:
  - id: S
    name: Socialdemokraterna
    display_name: Socialdemokraterna
  - id: M
    name: Moderaterna
    display_name: Moderaterna
""",
        encoding="utf-8",
    )
    (config_dir / "sources.yaml").write_text(
        """
sources: []
""",
        encoding="utf-8",
    )

    config = load_project_config(config_dir)
    agents = build_party_agents(config)

    assert agents["S"].llm_client is agents["M"].llm_client
