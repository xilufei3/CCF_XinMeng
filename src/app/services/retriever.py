import inspect
from pathlib import Path

from langchain_core.retrievers import BaseRetriever
from langchain_openai import OpenAIEmbeddings

from src.app.config import settings


def _chroma_ready() -> bool:
    persist_path = Path(settings.chroma_persist_dir)
    if not persist_path.exists() or not persist_path.is_dir():
        return False
    return any(persist_path.iterdir())


def _build_embedding_kwargs() -> dict:
    params = inspect.signature(OpenAIEmbeddings).parameters
    kwargs: dict = {}

    if "api_key" in params:
        kwargs["api_key"] = settings.model_api_key
    else:
        kwargs["openai_api_key"] = settings.model_api_key

    if "base_url" in params:
        kwargs["base_url"] = settings.model_api_base
    else:
        kwargs["openai_api_base"] = settings.model_api_base

    return kwargs


def get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=settings.embedding_model_name,
        **_build_embedding_kwargs(),
    )


def get_retriever() -> BaseRetriever:
    if not settings.retrieval_enabled:
        raise RuntimeError("RAG is disabled by RETRIEVAL_ENABLED=false")

    if not _chroma_ready():
        raise RuntimeError(
            "Chroma data is not ready. Run `python -m src.app.scripts.index_documents` first."
        )

    from langchain_chroma import Chroma

    vectorstore = Chroma(
        collection_name=settings.collection_name,
        embedding_function=get_embeddings(),
        persist_directory=settings.chroma_persist_dir,
    )
    return vectorstore.as_retriever(search_kwargs={"k": settings.retrieval_top_k})
