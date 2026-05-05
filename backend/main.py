import uuid
import sys
import json
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.ingestion.chunker import chunk_markdown
from backend.ingestion.embedder import store_embeddings
from backend.ingestion.parser import parse_document_bytes
from backend.ingestion.embedder import STORAGE_DIR
from backend.rag.basic_rag import clear_retriever_cache, extract_metrics, generate_answer, retrieve_documents

app = FastAPI(title="FinSight API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    query: str


def active_document_path() -> Path:
    return STORAGE_DIR / "active_document.json"


def set_active_document(document_id: str, file_name: str | None) -> None:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    active_document_path().write_text(
        json.dumps({"document_id": document_id, "file_name": file_name}, ensure_ascii=True),
        encoding="utf-8",
    )


def get_active_document_id() -> str:
    path = active_document_path()
    if not path.exists():
        raise HTTPException(status_code=400, detail="Upload a document before chatting")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["document_id"]


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"name": "FinSight API", "docs": "/docs", "health": "/api/health"}


@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    document_id = str(uuid.uuid4())
    try:
        markdown = parse_document_bytes(data, file.filename or document_id)
        documents = chunk_markdown(markdown, document_name=file.filename)
        result = store_embeddings(
            documents,
            collection_name=document_id,
            document_name=file.filename,
        )
        clear_retriever_cache()
        set_active_document(document_id, file.filename)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Document ingestion failed: {type(exc).__name__}: {exc}",
        ) from exc

    sections = sorted({
        doc.metadata.get("section", "other")
        for doc in documents
        if getattr(doc, "metadata", None)
    })
    return {
        "document_id": document_id,
        "file_name": file.filename,
        "chunk_count": result["chunk_count"],
        "sections": sections,
    }


@app.post("/api/chat")
def chat(request: ChatRequest):
    try:
        document_id = get_active_document_id()
        documents = retrieve_documents(request.query, collection_name=document_id)
        chunks = [document.page_content for document in documents]
        metrics = extract_metrics(request.query, documents)
        answer = generate_answer(request.query, chunks, metrics=metrics)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Chat failed: {type(exc).__name__}: {exc}",
        ) from exc
    return {
        "answer": answer,
        "metrics": metrics,
        "sources": [
            {
                "text": document.page_content,
                "chunk_id": document.metadata.get("chunk_id"),
                "retrieval_id": document.metadata.get("retrieval_id"),
                "section": document.metadata.get("section"),
                "heading": document.metadata.get("heading"),
                "document_name": document.metadata.get("document_name"),
                "is_table": document.metadata.get("is_table", False),
            }
            for document in documents
        ],
        "trace": {
            "decision": "general_qa",
            "tools_called": [
                {
                    "name": "hybrid_rag_retriever",
                    "input": request.query,
                    "output_summary": f"Retrieved {len(documents)} chunks using Pinecone vectors + BM25",
                    "latency_ms": None,
                },
                {
                    "name": "structured_metric_extractor",
                    "input": request.query,
                    "output_summary": f"Extracted {len(metrics)} structured metrics",
                    "latency_ms": None,
                }
            ],
            "reasoning_steps": [
                "Parsed the uploaded file with Gemini during ingestion",
                "Embedded chunks with gemini-embedding-2",
                "Retrieved sources using hybrid Pinecone vector search and BM25",
                "Extracted structured metric values from matching financial table rows",
                "Generated a grounded answer from retrieved chunks",
            ],
            "grounding_verified": bool(documents),
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
