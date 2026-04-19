#!/bin/bash
# Index the knowledge base into ChromaDB (run after docker-compose up)
echo "Indexing medical knowledge base..."
docker compose run --rm embed-kb
echo "Done!"
