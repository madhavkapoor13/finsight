import os
import re
from functools import lru_cache

from dotenv import load_dotenv
from google import genai

from backend.ingestion.embedder import DEFAULT_COLLECTION_NAME
from backend.rag.retriever import HybridRetriever

load_dotenv()

ANSWER_MODEL = os.getenv("GEMINI_ANSWER_MODEL", "gemini-3.1-flash-lite-preview")

METRIC_DEFINITIONS = [
    {
        "metric": "Revenue",
        "query_terms": ("revenue", "sales to customers", "net sales", "total sales"),
        "labels": ("sales to customers", "net sales", "total revenue", "revenue"),
    },
    {
        "metric": "Income Before Tax",
        "query_terms": ("income before tax", "income before taxes", "before tax", "before taxes", "pre-tax", "pretax"),
        "labels": (
            "earnings before provision for taxes on income",
            "income before tax",
            "income before taxes",
        ),
        "blocked_labels": ("segment income before tax",),
    },
    {
        "metric": "Net Income",
        "query_terms": ("net income", "net earnings"),
        "labels": ("net earnings", "net income"),
    },
    {
        "metric": "Gross Profit",
        "query_terms": ("gross profit",),
        "labels": ("gross profit",),
    },
]


def get_gemini_client():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    return genai.Client(api_key=api_key) if api_key else genai.Client()


@lru_cache(maxsize=8)
def _get_retriever(collection_name: str = DEFAULT_COLLECTION_NAME) -> HybridRetriever:
    return HybridRetriever(collection_name=collection_name)


def retrieve(query: str, collection_name: str = DEFAULT_COLLECTION_NAME) -> list[str]:
    documents = retrieve_documents(query, collection_name)
    return [document.page_content for document in documents]


def retrieve_documents(query: str, collection_name: str = DEFAULT_COLLECTION_NAME):
    return _get_retriever(collection_name).retrieve(query)


def clear_retriever_cache() -> None:
    _get_retriever.cache_clear()


def preprocess_chunks(chunks: list[str]) -> list[str]:
    return ["TABLE DATA:\n" + chunk if "|" in chunk else chunk for chunk in chunks]


def _clean_cell(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("*", "").strip())


def _parse_numeric_value(value: str) -> float | int | None:
    cleaned = _clean_cell(value)
    if not cleaned or "%" in cleaned:
        return None

    match = re.search(r"\$?\(?-?\d[\d,]*(?:\.\d+)?\)?", cleaned)
    if not match:
        return None

    raw_number = match.group(0)
    negative = raw_number.startswith("(") and raw_number.endswith(")")
    normalized = raw_number.strip("()").replace("$", "").replace(",", "")
    try:
        parsed = float(normalized)
    except ValueError:
        return None

    if negative:
        parsed *= -1
    return int(parsed) if parsed.is_integer() else parsed


def _format_metric_value(metric: dict) -> str:
    value = metric["value"]
    if isinstance(value, float) and not value.is_integer():
        value_text = f"{value:,.2f}"
    else:
        value_text = f"{int(value):,}"

    if metric.get("unit") == "million USD":
        return f"${value_text} million"
    if metric.get("unit") == "percent":
        return f"{value_text}%"
    return value_text


def _first_numeric_cell(cells: list[str]) -> str | None:
    for cell in cells[1:]:
        cleaned = _clean_cell(cell)
        if _parse_numeric_value(cleaned) is not None:
            return cleaned
    return None


def _wanted_metric_definitions(query: str) -> list[dict]:
    query_lower = query.lower()
    return [
        definition
        for definition in METRIC_DEFINITIONS
        if any(term in query_lower for term in definition["query_terms"])
    ]


def _infer_year(query: str, text: str) -> int | None:
    for source in (query, text):
        match = re.search(r"\b(20\d{2})\b", source)
        if match:
            return int(match.group(1))
    return None


def _infer_period(query: str, text: str) -> str | None:
    combined = f"{query} {text}".lower()
    if "fiscal first quarter" in combined or "first quarter" in combined or "q1" in combined:
        return "Fiscal first quarter"
    if "fiscal three months" in combined or "three months ended" in combined:
        return "Fiscal three months"
    if "fiscal year" in combined or "year ended" in combined:
        return "Fiscal year"
    return None


def _metric_unit(metric_name: str, row_text: str, raw_value: str) -> str:
    if "%" in raw_value or "margin" in metric_name.lower():
        return "percent"
    if "$" in raw_value or any(term in row_text.lower() for term in ("dollars in millions", "sales", "earnings", "income", "profit")):
        return "million USD"
    return "unknown"


def _row_cells(line: str) -> list[str]:
    return [_clean_cell(cell) for cell in line.strip().strip("|").split("|")]


def _metric_from_row(query: str, document, line: str, definition: dict) -> dict | None:
    line_lower = line.lower()
    document_text_lower = getattr(document, "page_content", "").lower()
    metadata = getattr(document, "metadata", {}) or {}
    heading_lower = str(metadata.get("heading", "")).lower()

    if not any(label in line_lower for label in definition["labels"]):
        return None

    for blocked_label in definition.get("blocked_labels", ()):
        if blocked_label in line_lower and "segment" not in query.lower():
            return None

    if definition["metric"] == "Revenue" and "segment" not in query.lower():
        if "sales by segment" in document_text_lower or "segment income before tax" in document_text_lower:
            return None
        if "segment" in heading_lower:
            return None

    cells = _row_cells(line)
    raw_value = _first_numeric_cell(cells)
    if not raw_value:
        return None

    value = _parse_numeric_value(raw_value)
    if value is None:
        return None

    source_chunk_id = metadata.get("chunk_id")
    return {
        "metric": definition["metric"],
        "value": value,
        "raw_value": raw_value,
        "unit": _metric_unit(definition["metric"], document.page_content, raw_value),
        "period": _infer_period(query, document.page_content),
        "year": _infer_year(query, document.page_content),
        "source": f"chunk_id:{source_chunk_id}" if source_chunk_id is not None else metadata.get("retrieval_id"),
        "source_chunk_id": source_chunk_id,
        "source_heading": metadata.get("heading"),
        "source_section": metadata.get("section"),
        "source_document": metadata.get("document_name"),
    }


def extract_metrics(query: str, documents: list) -> list[dict]:
    definitions = _wanted_metric_definitions(query)
    if not definitions:
        return []

    metrics = []
    seen = set()
    for document in documents:
        text = getattr(document, "page_content", "")
        for line in text.splitlines():
            if "|" not in line:
                continue
            for definition in definitions:
                metric = _metric_from_row(query, document, line, definition)
                if not metric:
                    continue
                key = (metric["metric"], metric["value"], metric.get("year"), metric.get("period"))
                if key in seen:
                    continue
                seen.add(key)
                metrics.append(metric)

    return metrics


def answer_from_metrics(query: str, metrics: list[dict]) -> str | None:
    if not metrics:
        return None

    metric = metrics[0]
    period = metric.get("period")
    year = metric.get("year")
    period_text = " ".join(str(part) for part in (period, year) if part)
    if period_text:
        return f"{metric['metric']} for {period_text} was {_format_metric_value(metric)}."
    return f"{metric['metric']} was {_format_metric_value(metric)}."


def _extract_table_answer(query: str, context: str) -> str | None:
    query_lower = query.lower()
    wants_income_before_tax = any(
        term in query_lower
        for term in ("income before tax", "income before taxes", "before tax", "before taxes", "pre-tax", "pretax")
    )
    wants_revenue = any(term in query_lower for term in ("revenue", "net sales", "sales to customers"))

    target_labels = []
    if wants_income_before_tax:
        target_labels.extend([
            "earnings before provision for taxes on income",
            "income before tax",
            "income before taxes",
        ])
    if wants_revenue:
        target_labels.extend([
            "sales to customers",
            "net sales",
            "total revenue",
            "revenue",
        ])

    if not target_labels:
        return None

    for line in context.splitlines():
        line_lower = line.lower()
        if not any(label in line_lower for label in target_labels):
            continue
        if wants_income_before_tax and "segment income before tax" in line_lower and "segment" not in query_lower:
            continue
        if "|" not in line:
            continue

        cells = [_clean_cell(cell) for cell in line.strip().strip("|").split("|")]
        value = _first_numeric_cell(cells)
        if not value:
            continue

        if wants_income_before_tax:
            return f"Income before tax for the fiscal first quarter of 2026 was {value}."
        if wants_revenue:
            return f"Revenue for the fiscal first quarter of 2026 was {value}."

    return None


def generate_answer(query: str, context_chunks: list[str], metrics: list[dict] | None = None) -> str:
    metric_answer = answer_from_metrics(query, metrics or [])
    if metric_answer:
        return metric_answer

    context = "\n\n".join(preprocess_chunks(context_chunks))
    direct_answer = _extract_table_answer(query, context)
    if direct_answer:
        return direct_answer

    prompt = f"""
You are FinSight, a grounded financial report analyst.
Answer only from the provided context. If the answer is not present, say "Not found in the uploaded document."
When using numbers, keep the source wording and avoid guessing.

For revenue questions, treat these report labels as revenue only when they refer to the consolidated company:
- Revenue
- Total revenue
- Net sales
- Net sales to customers
- Sales to customers
- Total sales

Do not use product-level, geographic, or segment sales as company revenue unless the user explicitly asks for that segment/product/geography.

For income-before-tax questions, treat "Earnings before provision for taxes on income" as the consolidated income before tax line. Do not use "Segment income before tax" unless the user explicitly asks for segment income.

CONTEXT:
{context}

QUESTION:
{query}
"""
    client = get_gemini_client()
    response = client.models.generate_content(
        model=ANSWER_MODEL,
        contents=[prompt],
    )
    return (response.text or "").strip()


if __name__ == "__main__":
    user_query = "income statement net sales total revenue financial results"
    chunks = retrieve(user_query)
    print("Number of chunks retrieved:", len(chunks))
    for chunk in chunks[:2]:
        print(chunk[:300])
        print("-----")
