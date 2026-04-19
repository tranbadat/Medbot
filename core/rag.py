import logging
import chromadb
from llama_index.core import VectorStoreIndex, StorageContext
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.embeddings.fastembed import FastEmbedEmbedding
from llama_index.core import Settings
from core.config import get_settings

logger = logging.getLogger(__name__)
config = get_settings()

_index: VectorStoreIndex | None = None


def _get_chroma_collection():
    client = chromadb.HttpClient(host=config.CHROMA_HOST, port=config.CHROMA_PORT)
    return client, client.get_or_create_collection("medical_kb")


def _setup_embed_model():
    # Suppress LlamaIndex "MockLLM" warning — we only use LlamaIndex for
    # retrieval/embedding, LLM calls go through core/ai_client.py directly.
    logging.getLogger("llama_index.core.llms.utils").setLevel(logging.ERROR)
    logging.getLogger("llama_index.core.settings").setLevel(logging.ERROR)
    Settings.embed_model = FastEmbedEmbedding(model_name="intfloat/multilingual-e5-large")
    Settings.llm = None


async def get_index() -> VectorStoreIndex | None:
    global _index
    if _index is not None:
        return _index
    try:
        _setup_embed_model()
        chroma_client, collection = _get_chroma_collection()
        vector_store = ChromaVectorStore(chroma_collection=collection)
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        _index = VectorStoreIndex.from_vector_store(
            vector_store, storage_context=storage_context
        )
        logger.info("RAG index loaded from ChromaDB")
    except Exception as e:
        logger.warning(f"RAG index not available: {e}")
        _index = None
    return _index


async def retrieve_context(query: str, top_k: int = 3) -> str | None:
    index = await get_index()
    if index is None:
        return None
    try:
        retriever = index.as_retriever(similarity_top_k=top_k)
        nodes = retriever.retrieve(query)
        if not nodes:
            return None
        return "\n\n---\n\n".join(n.get_content() for n in nodes)
    except Exception as e:
        logger.warning(f"RAG retrieval failed: {e}")
        return None
