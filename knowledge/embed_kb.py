"""
Script to index medical guidelines into ChromaDB.
Run: python knowledge/embed_kb.py
"""
import sys
import os
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Silence noisy third-party output before importing them.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY", "False")
logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)
logging.getLogger("llama_index").setLevel(logging.ERROR)

import chromadb
from chromadb.config import Settings as ChromaSettings
from llama_index.core import Document, VectorStoreIndex, StorageContext
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.embeddings.fastembed import FastEmbedEmbedding
from llama_index.core import Settings
from llama_index.core.llms import MockLLM
from core.config import get_settings

config = get_settings()

_EMBED_MODEL_ALIAS = {
    "small": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "base": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
    "large": "intfloat/multilingual-e5-large",
}


def _resolve_embed_model_name(value: str) -> str:
    return _EMBED_MODEL_ALIAS.get(value.lower(), value)

SUPPORTED_EXTENSIONS = {".txt", ".md"}


def load_documents(docs_path: str) -> list[Document]:
    """Read text files directly — no llama-index-readers-file needed."""
    docs = []
    for fname in sorted(os.listdir(docs_path)):
        ext = os.path.splitext(fname)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue
        fpath = os.path.join(docs_path, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            text = f.read()
        if text.strip():
            docs.append(Document(text=text, metadata={"filename": fname}))
            print(f"  Loaded: {fname} ({len(text)} chars)")
    return docs


def main():
    print("Loading documents...")
    docs_path = os.path.join(os.path.dirname(__file__), "medical_guidelines")
    documents = load_documents(docs_path)
    if not documents:
        print("No documents found in medical_guidelines/")
        return
    print(f"Loaded {len(documents)} document(s)")

    print("Connecting to ChromaDB...")
    client = chromadb.HttpClient(
        host=config.CHROMA_HOST,
        port=config.CHROMA_PORT,
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    collection = client.get_or_create_collection("medical_kb")

    model_name = _resolve_embed_model_name(config.EMBED_MODEL)
    print(f"Setting up embedding model ({model_name})...")
    Settings.embed_model = FastEmbedEmbedding(model_name=model_name)
    Settings.llm = MockLLM()

    vector_store = ChromaVectorStore(chroma_collection=collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    print("Indexing documents...")
    VectorStoreIndex.from_documents(documents, storage_context=storage_context)
    print("✅ Knowledge base indexed successfully!")


if __name__ == "__main__":
    main()
