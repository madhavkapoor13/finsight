from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document


def classify_section(text: str) -> str:
    """Classify a chunk's content into a coarse section label.

    Returns one of: 'income_statement', 'balance_sheet', 'other'
    """
    text_lower = (text or "").lower()

    if any(x in text_lower for x in [
        "consolidated statements of earnings",
        "statement of earnings",
        "net sales",
        "sales to customers",
        "total revenue",
        "income before tax",
        "gross profit",
        "% of sales"
    ]):
        return "income_statement"

    if any(x in text_lower for x in [
        "risk factors",
        "risks related",
        "market risk",
        "regulatory risk",
        "operational risk"
    ]):
        return "risk_factors"

    if any(x in text_lower for x in [
        "assets",
        "liabilities",
        "equity",
        "cash and cash equivalents"
    ]):
        return "balance_sheet"

    return "other"


def is_table_chunk(text: str) -> bool:
    lines = [line.strip() for line in (text or "").splitlines()]
    table_lines = [line for line in lines if line.startswith("|") and line.endswith("|")]
    return len(table_lines) >= 2


def chunk_markdown(markdown_text: str, document_name: str | None = None):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=100
    )

    sections = []
    current_section = "unknown"
    current_text = []

    for line in markdown_text.split("\n"):
        if line.startswith("##"):
            # save previous section
            if current_text:
                sections.append((current_section, "\n".join(current_text)))
                current_text = []
            
            current_section = line.lower()
        else:
            current_text.append(line)

    # add last section
    if current_text:
        sections.append((current_section, "\n".join(current_text)))

    documents = []
    global_chunk_id = 0

    for section, text in sections:
        chunks = splitter.split_text(text)

        for chunk in chunks:
            s = chunk.strip()
            if not s:
                continue

            # classify section by content (semantic section classification)
            classified = classify_section(s)
            documents.append(
                Document(
                    page_content=s,
                    metadata={
                        "document_name": document_name or "",
                        "heading": section.lstrip("# ").strip() or "unknown",
                        "section": classified,
                        "is_table": is_table_chunk(s),
                        "chunk_id": global_chunk_id
                    }
                )
            )
            global_chunk_id += 1

    print(f"[chunker] Total sections: {len(sections)}")
    print(f"[chunker] Total chunks: {len(documents)}")

    return documents


if __name__ == "__main__":
    from parser import parse_pdf
    
    md = parse_pdf("finsight/a9d54579-0232-4812-8945-1304fffa8bea.pdf")  
    docs = chunk_markdown(md)
    
    print(f"Total chunks: {len(docs)}\n")
    print("Sample chunk:\n")
    print(docs[10].page_content)
    print(f"\nSample chunk section: {docs[10].metadata.get('section', 'Unknown')}")
