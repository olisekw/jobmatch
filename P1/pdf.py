# extract_pdf_text.py
# Simple script to extract ALL readable text from a PDF file

import fitz  # this is PyMuPDF
import sys

def extract_text_from_pdf(pdf_path):
    try:
        doc = fitz.open(pdf_path)
        full_text = ""

        for page_num, page in enumerate(doc, 1):
            # Extract plain text from this page
            text = page.get_text("text")  # "text" mode = clean, readable text
            
            # Add page separator so you know where pages break
            full_text += f"\n\n--- Page {page_num} ---\n"
            full_text += text + "\n"

        doc.close()
        return full_text.strip()

    except Exception as e:
        return f"Error reading PDF: {str(e)}"

if __name__ == "__main__":
    # Change this to your PDF file path
    pdf_file = "oliver bujdos CV.pdf"  # ← put your actual PDF name/path here
    
    # Example: if your PDF is in the same folder as this script
    # pdf_file = "my_job_offer.pdf"
    
    # Or full path example (Windows):
    # pdf_file = r"C:\Users\Oliver\Downloads\job_description.pdf"
    
    # Or macOS/Linux:
    # pdf_file = "/Users/oliver/Documents/invoice.pdf"

    print("Extracting text from:", pdf_file)
    text = extract_text_from_pdf(pdf_file)

    # Save to a text file
    output_file = "resume.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(text)

    print(f"\nDone! Text saved to: {output_file}")
    print("\nFirst 500 characters of extracted text:\n")
    print(text[:500])
    print("\n... (full text is in the file)")