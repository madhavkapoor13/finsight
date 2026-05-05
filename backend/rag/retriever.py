import math
import re
from collections import Counter
from dataclasses import dataclass

from langchain_core.documents import Document

from backend.ingestion.embedder import (
    DEFAULT_COLLECTION_NAME,
    embed_text,
    get_pinecone_index,
    load_manifest,
)

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9%$.-]+")
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "for", "from", "in", "is",
    "it", "of", "on", "or", "the", "to", "was", "were", "what", "which"
}
REVENUE_TERMS = ("revenue", "sales", "net sales", "total revenue")
REVENUE_EXPANSION = (
    " sales to customers net sales total sales total revenue consolidated "
    "statement of earnings consolidated statements of earnings income statement "
)
SEGMENT_TERMS = ("segment", "product", "geographic", "region", "division")
INCOME_BEFORE_TAX_TERMS = (
    "income before tax",
    "income before taxes",
    "before tax",
    "before taxes",
    "pre-tax",
    "pretax",
)
INCOME_BEFORE_TAX_EXPANSION = (
    " earnings before provision for taxes on income income before tax "
    "income before taxes provision for taxes income statement "
)


@dataclass(frozen=True)
class HybridSearchConfig:
    top_k: int = 8
    vector_k: int = 12
    bm25_k: int = 16
    vector_weight: float = 0.45
    bm25_weight: float = 0.55
    rank_constant: int = 60


def tokenize(text: str) -> list[str]:
    return [
        token
        for token in TOKEN_PATTERN.findall((text or "").lower())
        if token not in STOPWORDS
    ]


def document_key(document: Document) -> str:
    return str(document.metadata.get("retrieval_id") or document.page_content)


def is_revenue_query(query: str) -> bool:
    query_lower = (query or "").lower()
    return any(term in query_lower for term in REVENUE_TERMS)


def expand_query(query: str) -> str:
    expanded = query
    query_lower = (query or "").lower()
    if is_revenue_query(query):
        expanded += REVENUE_EXPANSION
    if any(term in query_lower for term in INCOME_BEFORE_TAX_TERMS):
        expanded += INCOME_BEFORE_TAX_EXPANSION
    return expanded


def metadata_boost(document: Document, query: str) -> float:
    metadata = document.metadata or {}
    heading = str(metadata.get("heading", "")).lower()
    section = str(metadata.get("section", "")).lower()
    text = document.page_content.lower()
    query_lower = (query or "").lower()

    score = 0.0
    if is_revenue_query(query):
        if section == "income_statement":
            score += 0.02
        if "consolidated statement" in heading or "statement of earnings" in heading:
            score += 0.05
        if "sales to customers" in text or "net sales" in text or "total revenue" in text:
            score += 0.04
        if "segment" in heading and not any(term in query_lower for term in SEGMENT_TERMS):
            score -= 0.05
        if "sales by segment" in text and not any(term in query_lower for term in SEGMENT_TERMS):
            score -= 0.04

    if any(term in query_lower for term in INCOME_BEFORE_TAX_TERMS):
        if section == "income_statement":
            score += 0.03
        if "earnings before provision for taxes on income" in text:
            score += 0.09
        if "segment income before tax" in text and "segment" not in query_lower:
            score -= 0.06

    return score


class BM25Index:
    def __init__(self, documents: list[Document], k1: float = 1.5, b: float = 0.75):
        self.documents = documents
        self.k1 = k1
        self.b = b
        self.doc_tokens = [tokenize(self._search_text(document)) for document in documents]
        self.doc_lengths = [len(tokens) for tokens in self.doc_tokens]
        self.avg_doc_length = sum(self.doc_lengths) / len(self.doc_lengths) if self.doc_lengths else 0.0
        self.term_frequencies = [Counter(tokens) for tokens in self.doc_tokens]
        self.idf = self._build_idf()

    def search(self, query: str, top_k: int) -> list[Document]:
        query_terms = tokenize(query)
        if not query_terms:
            return []

        scored = []
        for index, frequencies in enumerate(self.term_frequencies):
            score = self._score(query_terms, frequencies, self.doc_lengths[index])
            if score > 0:
                scored.append((score, self.documents[index]))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [document for _, document in scored[:top_k]]

    def _search_text(self, document: Document) -> str:
        metadata = document.metadata or {}
        return " ".join([
            str(metadata.get("heading", "")),
            str(metadata.get("section", "")),
            document.page_content,
        ])

    def _build_idf(self) -> dict[str, float]:
        document_count = len(self.doc_tokens)
        document_frequency = Counter()
        for tokens in self.doc_tokens:
            document_frequency.update(set(tokens))

        return {
            term: math.log(1 + (document_count - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in document_frequency.items()
        }

    def _score(self, query_terms: list[str], frequencies: Counter, doc_length: int) -> float:
        if not self.avg_doc_length:
            return 0.0

        score = 0.0
        for term in query_terms:
            term_frequency = frequencies.get(term, 0)
            if term_frequency == 0:
                continue

            denominator = term_frequency + self.k1 * (
                1 - self.b + self.b * doc_length / self.avg_doc_length
            )
            score += self.idf.get(term, 0.0) * (
                term_frequency * (self.k1 + 1) / denominator
            )
        return score


class HybridRetriever:
    """Hybrid retrieval over Pinecone vectors plus local BM25 over the same uploaded chunks."""

    def __init__(
        self,
        collection_name: str = DEFAULT_COLLECTION_NAME,
        config: HybridSearchConfig | None = None,
    ):
        self.collection_name = collection_name
        self.config = config or HybridSearchConfig()
        self._bm25_index: BM25Index | None = None

    def retrieve(self, query: str) -> list[Document]:
        if not query or not query.strip():
            return []

        search_query = expand_query(query)
        ranked: dict[str, tuple[Document, float]] = {}
        self._merge_ranked(ranked, self._vector_search(search_query), self.config.vector_weight)
        self._merge_ranked(ranked, self._bm25_search(search_query), self.config.bm25_weight)

        return [
            document
            for document, _ in sorted(
                ranked.values(),
                key=lambda item: item[1] + metadata_boost(item[0], query),
                reverse=True,
            )
        ][: self.config.top_k]

    def _merge_ranked(
        self,
        ranked: dict[str, tuple[Document, float]],
        documents: list[Document],
        weight: float,
    ) -> None:
        for rank, document in enumerate(documents, start=1):
            key = document_key(document)
            score = weight / (self.config.rank_constant + rank)
            existing_document, existing_score = ranked.get(key, (document, 0.0))
            ranked[key] = (existing_document, existing_score + score)

    def _vector_search(self, query: str) -> list[Document]:
        results = get_pinecone_index().query(
            vector=embed_text(query),
            top_k=self.config.vector_k,
            include_metadata=True,
            namespace=self.collection_name,
        )
        matches = getattr(results, "matches", None) or results.get("matches", [])

        documents = []
        for match in matches:
            metadata = getattr(match, "metadata", None) or match.get("metadata", {}) or {}
            text = metadata.get("text", "")
            if not text:
                continue
            retrieval_id = getattr(match, "id", None) or match.get("id")
            documents.append(Document(
                page_content=text,
                metadata={**metadata, "retrieval_id": retrieval_id},
            ))
        return documents

    def _bm25_search(self, query: str) -> list[Document]:
        index = self._get_bm25_index()
        return index.search(query, self.config.bm25_k) if index else []

    def _get_bm25_index(self) -> BM25Index | None:
        if self._bm25_index is not None:
            return self._bm25_index

        records = load_manifest(self.collection_name)
        documents = [
            Document(
                page_content=record["text"],
                metadata={**record.get("metadata", {}), "retrieval_id": f"{record.get('id', 'record')}-{index}"},
            )
            for index, record in enumerate(records)
        ]
        if not documents:
            return None

        self._bm25_index = BM25Index(documents)
        return self._bm25_index
