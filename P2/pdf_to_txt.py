# pdf_to_resume_txt.py
# Converts your PDF resume → clean resume.txt
# Recommended: pdfplumber handles resumes very well

import pdfplumber
from pathlib import Path

def pdf_to_text(pdf_path: str, output_txt: str = "resume.txt"):
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        print(f"Error: File not found → {pdf_path}")
        return

    full_text = []

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text(layout=True)  # layout=True keeps better spacing
                if text:
                    full_text.append(text.strip())
        
        combined = "\n\n".join(full_text)  # double newline between pages
        # Optional: clean up common artifacts
        combined = combined.replace("• ", "- ")  # bullets
        combined = "\n".join(line.strip() for line in combined.splitlines() if line.strip())

        Path(output_txt).write_text(combined, encoding="utf-8")
        print(f"Success! Saved to: {Path(output_txt).resolve()}")
        print(f"Total characters: {len(combined)}")
        print("\nPreview (first 300 chars):")
        print(combined[:300] + "...")

    except Exception as e:
        print(f"Error during extraction: {e}")
        print("Try another library or check if PDF is scanned (needs OCR).")

# ── Usage ──
if __name__ == "__main__":
    # Change this to your PDF filename
    pdf_to_text("oliver bujdos CV.pdf")   # ← put your PDF name here