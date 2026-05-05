import json
import os
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv
from google import genai
from pinecone import Pinecone

load_dotenv()

EMBEDDING_MODEL_NAME = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-2")
DEFAULT_COLLECTION_NAME = os.getenv("PINECONE_NAMESPACE", "finsight_docs")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "finsight")
STORAGE_DIR = Path(os.getenv("FINSIGHT_STORAGE_DIR", "/tmp/finsight_storage"))

_pinecone_index = None


def get_gemini_client():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    return genai.Client(api_key=api_key) if api_key else genai.Client()


def get_pinecone_index():
    global _pinecone_index
    if _pinecone_index is not None:
        return _pinecone_index

    api_key = os.getenv("PINECONE_API_KEY")
    if not api_key:
        raise RuntimeError("PINECONE_API_KEY is required")

    pc = Pinecone(api_key=api_key)
    index_host = os.getenv("PINECONE_INDEX_HOST")
    _pinecone_index = pc.Index(host=index_host) if index_host else pc.Index(PINECONE_INDEX_NAME)
    return _pinecone_index


def _embedding_values(embedding) -> list[float]:
    if hasattr(embedding, "values"):
        return list(embedding.values)
    if isinstance(embedding, dict):
        return list(embedding.get("values") or embedding.get("embedding") or [])
    return list(embedding)


def embed_text(text: str) -> list[float]:
    client = get_gemini_client()
    result = client.models.embed_content(
        model=EMBEDDING_MODEL_NAME,
        contents=text,
    )
    embedding = result.embeddings[0] if getattr(result, "embeddings", None) else result.embedding
    return _embedding_values(embedding)


def manifest_path(namespace: str) -> Path:
    safe_namespace = namespace.replace("/", "_")
    return STORAGE_DIR / f"{safe_namespace}.jsonl"


def write_manifest(namespace: str, records: list[dict]) -> None:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    path = manifest_path(namespace)
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=True) + "\n")


def load_manifest(namespace: str) -> list[dict]:
    path = manifest_path(namespace)
    if not path.exists():
        return []

    records = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _clean_documents(documents: Iterable, document_name: str | None) -> list[tuple[str, str, dict]]:
    cleaned = []
    for index, doc in enumerate(documents):
        text = getattr(doc, "page_content", "")
        if not isinstance(text, str) or not text.strip():
            continue

        metadata = dict(getattr(doc, "metadata", {}) or {})
        metadata.setdefault("chunk_id", index)
        if document_name:
            metadata.setdefault("document_name", document_name)

        chunk_id = str(index)
        metadata["chunk_id"] = index
        cleaned.append((chunk_id, text.strip(), metadata))
    return cleaned


def store_embeddings(
    documents,
    collection_name: str = DEFAULT_COLLECTION_NAME,
    document_name: str | None = None,
    replace_collection: bool = True,
):
    cleaned = _clean_documents(documents, document_name)
    if not cleaned:
        print("[embedder] No non-empty chunks to embed.")
        return {"namespace": collection_name, "chunk_count": 0}

    index = get_pinecone_index()
    if replace_collection:
        try:
            index.delete(delete_all=True, namespace=collection_name)
        except Exception:
            pass

    vectors = []
    manifest_records = []
    for chunk_id, text, metadata in cleaned:
        record_id = f"{collection_name}-{chunk_id}"
        metadata = {
            **metadata,
            "text": text,
            "document_name": document_name or metadata.get("document_name", ""),
        }
        vectors.append({
            "id": record_id,
            "values": embed_text(text),
            "metadata": metadata,
        })
        manifest_records.append({
            "id": record_id,
            "text": text,
            "metadata": metadata,
        })

    index.upsert(vectors=vectors, namespace=collection_name)
    write_manifest(collection_name, manifest_records)

    print(f"[embedder] Stored {len(vectors)} Gemini embeddings in Pinecone namespace '{collection_name}'")
    return {"namespace": collection_name, "chunk_count": len(vectors)}


if __name__ == "__main__":
    from parser import parse_document
    from chunker import chunk_markdown

    pdf_path = Path("/Users/madhavkapoor/Desktop/Fin_sight/finsight/a9d54579-0232-4812-8945-1304fffa8bea.pdf")
    markdown = parse_document(str(pdf_path))
    docs = chunk_markdown(markdown, document_name=pdf_path.name)
    print(store_embeddings(docs, document_name=pdf_path.name))
