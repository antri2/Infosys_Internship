"""
Turns an uploaded resume file into plain text before the LLM sees it.

PDF -> PyMuPDF (fast, no external system libraries needed).
DOCX -> python-docx.
These are the only two formats this project supports.
"""
import pymupdf
import docx

SUPPORTED_TYPES = {"pdf", "docx"}


def extract_text(file_path: str, file_type: str) -> str:
    if file_type == "pdf":
        return _extract_pdf_text(file_path)
    elif file_type == "docx":
        return _extract_docx_text(file_path)
    raise ValueError(f"Unsupported file type: {file_type}. Only PDF and DOCX are supported.")


def _extract_pdf_text(file_path: str) -> str:
    text_parts = []
    with pymupdf.open(file_path) as pdf:
        for page in pdf:
            page_text = page.get_text()
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts)


def _extract_docx_text(file_path: str) -> str:
    document = docx.Document(file_path)
    return "\n".join(paragraph.text for paragraph in document.paragraphs)
