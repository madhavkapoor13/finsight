from langchain_core.tools import tool

from backend.ingestion.embedder import DEFAULT_COLLECTION_NAME
from backend.rag.basic_rag import retrieve_documents


def format_source(document) -> dict:
    metadata = document.metadata or {}
    return {
        "text": document.page_content,
        "page": metadata.get("page"),
        "section": metadata.get("section") or metadata.get("heading"),
        "document_name": metadata.get("document_name"),
        "is_table": bool(metadata.get("is_table", False)),
    }


@tool
def rag_retriever(query: str, collection_name: str = DEFAULT_COLLECTION_NAME) -> list[dict]:
    """Retrieve grounded passages from the uploaded report using Pinecone vector search plus BM25."""
    documents = retrieve_documents(query, collection_name=collection_name)
    return [format_source(document) for document in documents]
