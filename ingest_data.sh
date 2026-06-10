#!/usr/bin/env bash
set -euo pipefail

## Ingest och RAG
## Pipeline för lokala partikällor + Riksdagen

echo "Läs partikällor"
python -m src.ingest.ingest_party_sources

echo "Importera riksdagsdata"
rm -f data/processed/riksdag_sources.jsonl
python -m src.ingest.ingest_riksdag --party S --riksmote 2025/26 --limit 20 --append
python -m src.ingest.ingest_riksdag --party M --riksmote 2025/26 --limit 20 --append
python -m src.ingest.ingest_riksdag --party MP --riksmote 2025/26 --limit 20 --append

echo "Stycka upp data"
python -m src.ingest.chunking

echo "Spara vektoriserad data"
python -m src.rag.vector_store --rebuild

echo "Kontrollera index"
python -m src.rag.inspect_index
