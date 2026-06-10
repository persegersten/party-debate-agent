from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class PartyConfig(BaseModel):
    id: str = Field(min_length=1, pattern=r"^[A-ZÅÄÖ0-9_-]+$")
    name: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    color_hint: str | None = None


class SourceConfig(BaseModel):
    party: str = Field(min_length=1)
    source_kind: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: HttpUrl


class RawDocument(BaseModel):
    doc_id: str = Field(min_length=1)
    party: str
    source_owner: str | None = None
    source_kind: str
    title: str
    url: HttpUrl
    content_hash: str | None = None
    text: str
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentChunk(BaseModel):
    chunk_id: str
    doc_id: str
    party: str
    source_kind: str
    title: str
    url: HttpUrl
    text: str
    chunk_index: int = Field(ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.chunk_id


class Evidence(BaseModel):
    source_title: str
    url: HttpUrl
    quote: str = Field(min_length=1)
    relevance: float = Field(ge=0.0, le=1.0, default=1.0)


class Claim(BaseModel):
    text: str = Field(min_length=1)
    topic: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class PartyResponse(BaseModel):
    party: str
    answer: str = Field(min_length=1)
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class FactCheckResult(BaseModel):
    claim: Claim
    verdict: Literal["supported", "partly_supported", "unsupported", "unclear"]
    explanation: str
    evidence: list[Evidence] = Field(default_factory=list)


class VoterVoiceProfile(BaseModel):
    tone: str = ""
    sentence_style: str = ""
    favorite_phrases: list[str] = Field(default_factory=list)
    skepticism_phrases: list[str] = Field(default_factory=list)
    metaphor_domains: list[str] = Field(default_factory=list)


class VoterPersona(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    priorities: list[str] = Field(default_factory=list)
    description: str = ""
    voice: VoterVoiceProfile = Field(default_factory=VoterVoiceProfile)


class VoterDecision(BaseModel):
    persona_id: str
    selected_party: str
    score_by_party: dict[str, float]
    strongest_reason: str
    biggest_concern: str
    evidence_quality: Literal["weak", "medium", "strong"]


class VoterReaction(BaseModel):
    persona_id: str
    persona_name: str
    selected_party: str
    one_liner: str
    reasoning: str
    concern: str

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_shape(cls, data: Any) -> Any:
        if not isinstance(data, dict) or "selected_party" in data:
            return data
        voter = data.get("voter")
        if isinstance(voter, VoterPersona):
            persona_id = voter.id
            persona_name = voter.name
        elif isinstance(voter, dict):
            persona_id = voter.get("id", "")
            persona_name = voter.get("name", "")
        else:
            persona_id = data.get("persona_id", "")
            persona_name = data.get("persona_name", "")
        reaction = data.get("reaction", "")
        return {
            "persona_id": persona_id,
            "persona_name": persona_name,
            "selected_party": data.get("party", ""),
            "one_liner": reaction,
            "reasoning": "",
            "concern": "",
        }

    @property
    def voter(self) -> VoterPersona:
        return VoterPersona(id=self.persona_id, name=self.persona_name)

    @property
    def party(self) -> str:
        return self.selected_party

    @property
    def reaction(self) -> str:
        parts = [self.one_liner, self.reasoning, self.concern]
        return " ".join(part.strip() for part in parts if part.strip())

    @property
    def score(self) -> int:
        return 3


class DebateState(BaseModel):
    topic: str
    question: str
    active_parties: list[str] = Field(default_factory=list)
    responses: list[PartyResponse] = Field(default_factory=list)
    rebuttals: list[PartyResponse] = Field(default_factory=list)
    fact_checks: list[FactCheckResult] = Field(default_factory=list)
    voter_reactions: list[VoterReaction] = Field(default_factory=list)
    summary: str | None = None


class PartiesConfig(BaseModel):
    parties: list[PartyConfig]

    @field_validator("parties")
    @classmethod
    def party_ids_must_be_unique(cls, parties: list[PartyConfig]) -> list[PartyConfig]:
        ids = [party.id for party in parties]
        duplicates = sorted({party_id for party_id in ids if ids.count(party_id) > 1})
        if duplicates:
            raise ValueError(f"Duplicate party ids in parties.yaml: {', '.join(duplicates)}")
        return parties

    @property
    def party_ids(self) -> set[str]:
        return {party.id for party in self.parties}


class SourcesConfig(BaseModel):
    sources: list[SourceConfig]


class ProjectConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    parties: list[PartyConfig]
    sources: list[SourceConfig]

    @model_validator(mode="after")
    def sources_must_reference_known_parties(self) -> ProjectConfig:
        party_ids = {party.id for party in self.parties}
        unknown = sorted({source.party for source in self.sources if source.party not in party_ids})
        if unknown:
            raise ValueError(f"Sources reference unknown parties: {', '.join(unknown)}")
        return self

    def party_by_id(self) -> dict[str, PartyConfig]:
        return {party.id: party for party in self.parties}

    def sources_for_party(self, party_id: str) -> list[SourceConfig]:
        return [source for source in self.sources if source.party == party_id]


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return data


def load_project_config(config_dir: Path | str = Path("data/config")) -> ProjectConfig:
    config_path = Path(config_dir)
    parties_config = PartiesConfig.model_validate(load_yaml(config_path / "parties.yaml"))
    sources_config = SourcesConfig.model_validate(load_yaml(config_path / "sources.yaml"))
    return ProjectConfig(parties=parties_config.parties, sources=sources_config.sources)
