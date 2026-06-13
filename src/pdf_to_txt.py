# Convert CV from PDF to text
# Extracts text from cv.pdf and saves to resume.txt

import sys
import pdfplumber
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

def pdf_to_text(pdf_path: Path, output_txt: Path):
    """Extract text from PDF and save to file."""
    if not pdf_path.is_file():
        print(f"\nERROR: {pdf_path} not found!")
        print("Place your CV (cv.pdf) in the data/ directory")
        sys.exit(1)

    full_text = []

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text(layout=True)
                if text:
                    full_text.append(text.strip())

        combined = "\n\n".join(full_text)
        combined = combined.replace("• ", "- ")
        combined = "\n".join(line.strip() for line in combined.splitlines() if line.strip())

        output_txt.write_text(combined, encoding="utf-8")
        print(f"Success! Saved to: {output_txt.resolve()}")
        print(f"Total characters: {len(combined)}")
        print("\nPreview (first 300 chars):")
        print(combined[:300] + "...")

    except Exception as e:
        print(f"Error during extraction: {e}")
        print("Try another library or check if PDF is scanned (needs OCR).")
        sys.exit(1)

if __name__ == "__main__":
    pdf_to_text(config.RESUME_PDF, config.RESUME_TXT)