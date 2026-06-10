#!/bin/bash

## Ingest och RAG
## Pipeline för lokala partikällor
echo "Läs partikällor"
python -m src.ingest.ingest_party_sources
echo "Stycka upp data"
python -m src.ingest.chunking
echo "Spara vektoriserad data"
python -m src.rag.vector_store --rebuild

echo "Importera riksdagsdata"
python -m src.ingest.ingest_riksdag --party S --riksmote 2025/26 --limit 20
python -m src.ingest.ingest_riksdag --party M --riksmote 2025/26 --limit 20
python -m src.ingest.ingest_riksdag --party MP --riksmote 2025/26 --limit 20
