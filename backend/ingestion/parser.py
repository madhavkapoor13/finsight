import mimetypes
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

PARSER_MODEL = os.getenv("GEMINI_PARSER_MODEL", "gemini-3.1-flash-lite-preview")

SUPPORTED_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".csv": "text/csv",
}

PARSER_PROMPT = """
You are FinSight's document parser, not a summarizer.

Parse the uploaded financial document into clean markdown for retrieval.
Use OCR/visual understanding when the file is an image or a non-machine-readable PDF.

Rules:
- Preserve tables as markdown tables whenever possible.
- Keep financial statement labels, units, years, notes, and section headings.
- Do not infer or calculate values.
- Do not summarize away details.
- Output only parsed markdown.
"""


def get_gemini_client():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    return genai.Client(api_key=api_key) if api_key else genai.Client()


def detect_mime_type(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower()
    return SUPPORTED_MIME_TYPES.get(
        suffix,
        mimetypes.guess_type(file_name)[0] or "application/octet-stream",
    )


def parse_document_bytes(data: bytes, file_name: str) -> str:
    if not data:
        raise ValueError("Cannot parse an empty file")

    mime_type = detect_mime_type(file_name)
    client = get_gemini_client()
    response = client.models.generate_content(
        model=PARSER_MODEL,
        contents=[
            types.Part.from_bytes(data=data, mime_type=mime_type),
            PARSER_PROMPT,
        ],
    )
    return (response.text or "").strip()


def parse_document(file_path: str) -> str:
    path = Path(file_path)
    return parse_document_bytes(path.read_bytes(), path.name)


def parse_pdf(file_path: str) -> str:
    return parse_document(file_path)


if __name__ == "__main__":
    path = Path("/Users/madhavkapoor/Desktop/Fin_sight/finsight/a9d54579-0232-4812-8945-1304fffa8bea.pdf")
    markdown = parse_document(str(path))
    print("Length of markdown:", len(markdown))
    print(markdown[:2000])
