# party-debate-agent

Svensk partiledardebatt-simulator där parti-agenter skapas dynamiskt från YAML-konfiguration och svarar utifrån officiella källor.

## Projektmål

- Läsa partier och källor från `data/config`.
- Skapa en agent per parti utan hårdkodad partilogik.
- Indexera officiella källor lokalt i en vector store.
- Låta moderator, parti-agenter, faktagranskare, väljarpanel och summerare kopplas ihop med LangGraph.
- Börja med CLI och hålla vägen öppen för Streamlit.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
pytest
```

Kör CLI-stommen:

```bash
python app.py "Vad vill ni göra åt klimatet?" --party S --party MP
```

## Lägga till ett parti

1. Lägg till partiet i `data/config/parties.yaml`.
2. Lägg till en eller flera officiella källor i `data/config/sources.yaml` med samma parti-id.
3. Kör `pytest`.

Exempel:

```yaml
parties:
  - id: C
    name: Centerpartiet
    display_name: Centerpartiet
    color_hint: green
```

Ingen agentkod behöver ändras eftersom `build_party_agents` skapar agenter från config.

## Hackaton-scope

Första versionen fokuserar på:

- robust config och validering
- Pydantic-scheman för debatt, påståenden och evidens
- dynamiskt skapade parti-agenter
- CLI som lokal körbar yta
- testbar grund för senare RAG och LangGraph-flöden

## Kända begränsningar

- Ingestion hämtar inte webbsidor ännu.
- Chroma-gränssnittet är en stub och gör ingen embedding-sökning ännu.
- Parti-svaren är placeholders tills officiella källor har indexerats.
- Faktagranskning, väljarpanel och summering är förenklade för hackaton.
- Streamlit UI är inte påbörjat.
