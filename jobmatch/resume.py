"""Resume (CV) parsing: PDF → text → skills."""

import pdfplumber

from . import extract


def pdf_to_text(pdf_path):
    """Extract plain text from a PDF resume."""
    parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text(layout=True)
            if text:
                parts.append(text.strip())
    combined = "\n\n".join(parts).replace("• ", "- ")
    return "\n".join(line.strip() for line in combined.splitlines() if line.strip())


def skills_from_text(resume_text):
    """Lowercase skill tokens detected in resume text."""
    return extract.extract_skills(resume_text)
