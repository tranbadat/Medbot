"""
Script to index medical guidelines into ChromaDB.
Run: python knowledge/embed_kb.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import chromadb
from llama_index.core import Document, VectorStoreIndex, StorageContext
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.embeddings.fastembed import FastEmbedEmbedding
from llama_index.core import Settings
from core.config import get_settings

config = get_settings()

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
    client = chromadb.HttpClient(host=config.CHROMA_HOST, port=config.CHROMA_PORT)
    collection = client.get_or_create_collection("medical_kb")

    print("Setting up embedding model (intfloat/multilingual-e5-large)...")
    Settings.embed_model = FastEmbedEmbedding(model_name="intfloat/multilingual-e5-large")
    Settings.llm = None

    vector_store = ChromaVectorStore(chroma_collection=collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    print("Indexing documents...")
    VectorStoreIndex.from_documents(documents, storage_context=storage_context)
    print("✅ Knowledge base indexed successfully!")


if __name__ == "__main__":
    main()
