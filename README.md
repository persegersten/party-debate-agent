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

## Ingest och RAG

Pipeline för lokala partikällor:

```bash
python -m src.ingest.ingest_party_sources
python -m src.ingest.chunking
python -m src.rag.vector_store --rebuild
```

Detta läser explicita URL:er från `data/config/sources.yaml`, extraherar text från HTML/PDF, skriver normaliserad JSONL till `data/processed/party_sources.jsonl`, chunkar till `data/processed/chunks.jsonl` och bygger ett lokalt Chroma-index i `data/index`.

Kör indexsteget med `--rebuild` efter ny ingest/chunking. Utan `--rebuild` vägrar indexbyggaren att skriva till ett befintligt icke-tomt index, eftersom append kan ge stale retrieval-resultat.

Riksdagens öppna data är valfritt och ska ses som extra material:

```bash
python -m src.ingest.ingest_riksdag --party S --riksmote 2025/26 --limit 20
```

Om Riksdagen-API:t ändrar struktur eller inte svarar loggas en varning. Partidebatten ska fortfarande fungera med bara partikällorna.

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
- ingest av explicita officiella URL:er
- lokal chunking och Chroma-baserat vector index
- CLI som lokal körbar yta
- testbar grund för senare RAG och LangGraph-flöden

## Kända begränsningar

- Ingestion är inte en crawler och följer inte länkar automatiskt.
- HTML/PDF-extraktion är bäst-försök och kan behöva per-källa-justering.
- Vector store använder en enkel lokal hash-embedding för demo; byt till riktiga embeddings för bättre semantisk träffsäkerhet.
- Parti-svaren är fortfarande förenklade tills LLM-svar kopplas hårdare till evidens.
- Faktagranskning, väljarpanel och summering är förenklade för hackaton.
- Streamlit UI är inte påbörjat.
