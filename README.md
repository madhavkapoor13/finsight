# FinSight

FinSight is a financial document analysis workspace for uploaded reports, filings, spreadsheets, and scanned documents. It parses documents with Gemini, embeds report chunks with Gemini embeddings, stores vectors in Pinecone, and answers questions with hybrid retrieval plus structured metric extraction.

The system is designed to behave like a financial analyst tool rather than a generic chatbot: answers include source passages, trace metadata, and machine-readable metrics when the question asks for a financial value.

---

## Why FinSight?

Financial documents are complex, table-heavy, and difficult to query. Generic RAG systems often hallucinate, miss key tables, or fail to extract structured financial metrics.

FinSight solves this by combining:

* Hybrid retrieval (semantic + lexical search)
* Deterministic table-based metric extraction
* Source-grounded answers with traceability
* Structured financial outputs for downstream analysis

---

## Key Capability: Structured Financial Extraction

FinSight goes beyond text answers by extracting structured financial metrics directly from documents.

Supported metrics include:

* Revenue / Sales to Customers
* Income Before Tax
* Net Income
* Gross Profit

Each extracted metric includes:

* metric name
* numeric value
* raw value
* unit
* period
* year
* source chunk id
* source document metadata

This enables:

* Accurate financial analysis
* UI metric cards
* Ratio calculations
* Reliable evaluation pipelines

---

## Features

* Upload PDF, image, Word, Excel, or CSV files.
* Parse machine-readable and scanned documents using Gemini multimodal parsing.
* Preserve financial tables as markdown where possible.
* Chunk documents with metadata for section, heading, table status, and chunk id.
* Embed chunks with `gemini-embedding-2`.
* Store vectors in Pinecone by document namespace.
* Retrieve with hybrid search: Pinecone vector search plus local BM25.
* Extract structured metrics such as revenue, income before tax, net income, and gross profit.
* Return answers with `metrics`, `sources`, and `trace`.
* Next.js frontend with upload workflow, chat workspace, metric cards, source inspector, and trace view.

---

## How FinSight is Different

* No hallucination: strict grounding and deterministic extraction
* Financial-aware: understands tables and financial metrics
* Hybrid retrieval: combines vector search with BM25 lexical search
* Traceability: every answer includes sources and reasoning trace
* Structured outputs: returns machine-readable financial data

---

## Architecture

```text
Upload
  -> FastAPI /api/upload
  -> Gemini parser
  -> Markdown chunks
  -> Gemini embeddings
  -> Pinecone namespace
  -> Local BM25 manifest

Chat
  -> FastAPI /api/chat
  -> HybridRetriever
       -> Pinecone semantic search
       -> BM25 lexical search
       -> rank fusion
  -> structured metric extractor
  -> Gemini grounded answer fallback
  -> answer + metrics + sources + trace
```

---

## Tech Stack

### Backend

* Python
* FastAPI
* Google Gen AI SDK
* Gemini `gemini-3.1-flash-lite-preview`
* Gemini `gemini-embedding-2`
* Pinecone
* LangChain document utilities

### Frontend

* Next.js
* React
* CSS
* lucide-react

### Deployment

* Render for FastAPI backend
* Vercel or Netlify for frontend

---

## Repository Structure

```text
backend/
  main.py                    FastAPI app
  ingestion/
    parser.py                Gemini document parser
    chunker.py               Markdown chunking and metadata
    embedder.py              Gemini embeddings + Pinecone upsert
  rag/
    retriever.py             Hybrid Pinecone + BM25 retrieval
    basic_rag.py             Answer generation + structured metric extraction
  agent/
    tools/rag_retriever.py   LangChain tool wrapper

frontend/
  app/page.jsx               Main Next.js workspace UI
  app/globals.css            Styling
  lib/api.js                 API client

requirements.txt
render.yaml
.env.example
```

---

## Environment Variables

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Required:

```bash
GEMINI_API_KEY=
PINECONE_API_KEY=
PINECONE_INDEX_NAME=finsight
```

Optional:

```bash
GEMINI_PARSER_MODEL=gemini-3.1-flash-lite-preview
GEMINI_ANSWER_MODEL=gemini-3.1-flash-lite-preview
GEMINI_EMBEDDING_MODEL=gemini-embedding-2
PINECONE_INDEX_HOST=
PINECONE_NAMESPACE=finsight_docs
FINSIGHT_STORAGE_DIR=/tmp/finsight_storage
```

Frontend environment:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

---

## Local Setup

Create and activate a Python virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Start the backend:

```bash
venv/bin/python backend/main.py
```

Backend runs at:

```text
http://localhost:8000
```

API docs:

```text
http://localhost:8000/docs
```

Start the frontend:

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at:

```text
http://localhost:3000
```

---

## API

### Health

```http
GET /api/health
```

---

### Upload Document

```http
POST /api/upload
Content-Type: multipart/form-data
```

Field:

```text
file=<document>
```

Example response:

```json
{
  "document_id": "uuid",
  "file_name": "report.pdf",
  "chunk_count": 42,
  "sections": ["income_statement", "balance_sheet", "other"]
}
```

The most recently uploaded document becomes the active document for chat.

---

### Chat

```http
POST /api/chat
Content-Type: application/json
```

Request:

```json
{
  "query": "What was the revenue of the company?"
}
```

Example response:

```json
{
  "answer": "Revenue for Fiscal first quarter 2026 was $24,062 million.",
  "metrics": [
    {
      "metric": "Revenue",
      "value": 24062,
      "raw_value": "$24,062",
      "unit": "million USD",
      "period": "Fiscal first quarter",
      "year": 2026,
      "source": "chunk_id:6",
      "source_chunk_id": 6,
      "source_heading": "item 1 — financial statements",
      "source_section": "income_statement",
      "source_document": "report.pdf"
    }
  ],
  "sources": [
    {
      "text": "...",
      "chunk_id": 6,
      "section": "income_statement",
      "heading": "item 1 — financial statements",
      "document_name": "report.pdf",
      "is_table": true
    }
  ],
  "trace": {
    "decision": "general_qa",
    "tools_called": [
      {
        "name": "hybrid_rag_retriever",
        "output_summary": "Retrieved 8 chunks using Pinecone vectors + BM25"
      },
      {
        "name": "structured_metric_extractor",
        "output_summary": "Extracted 1 structured metrics"
      }
    ],
    "grounding_verified": true
  }
}
```

---

## Example Queries

* What was the revenue for Q1 2026?
* What is the income before tax?
* What are the sales to customers values?
* Compare sales between 2025 and 2026

---

## Current Limitations

* Chat operates on the most recently uploaded document.
* Multi-document comparison is not implemented yet.
* BM25 uses local storage (`/tmp/finsight_storage`), which is ephemeral on free hosting tiers.
* Structured extraction covers common financial metrics but is not a full financial statement parser.
* Evaluation benchmarks and automated scoring are not yet implemented.

---

## Roadmap

* Document list and active document selection
* Multi-document comparison
* Expanded structured metric extraction
* Financial ratio calculations
* Evaluation dataset with ground-truth answers
* Improved ingestion error handling
* Streaming responses and trace visualization

---

## Deployment

`render.yaml` deploys the FastAPI backend on Render:

```yaml
startCommand: uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

Set environment variables:

```text
GEMINI_API_KEY
PINECONE_API_KEY
PINECONE_INDEX_NAME=finsight
FINSIGHT_STORAGE_DIR=/tmp/finsight_storage
```

Deploy the frontend on Vercel or Netlify and set:

```text
NEXT_PUBLIC_API_BASE_URL=<your backend URL>
```
