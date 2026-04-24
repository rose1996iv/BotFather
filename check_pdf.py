# save as check_pdf.py
from langchain_community.document_loaders import PyPDFLoader

# Check the nursing PDF since that answer was worst
loader = PyPDFLoader("pdfs/Nursing_GEU.pdf")
pages = loader.load()

for i, page in enumerate(pages[:3]):  # first 3 pages
    print(f"\n--- PAGE {i+1} ---")
    print(page.page_content[:500])
    print("...")