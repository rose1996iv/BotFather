import os
from pathlib import Path
from dotenv import load_dotenv

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

load_dotenv()

PDF_DIR = Path("pdfs")
DB_DIR  = "./chroma_db"

print("Loading PDFs...")
docs = []
for pdf_file in PDF_DIR.glob("*.pdf"):
    print(f"  Reading: {pdf_file.name}")
    loader = PyPDFLoader(str(pdf_file))
    docs.extend(loader.load())

if not docs:
    print("No PDFs found in pdfs/ folder. Add your PDF files and retry.")
    exit(1)

print(f"Splitting {len(docs)} pages into chunks...")
splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
chunks = splitter.split_documents(docs)

print("Loading multilingual embedding model...")
embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)

print("Building vector database...")
vectordb = Chroma.from_documents(
    chunks,
    embeddings,
    persist_directory=DB_DIR
)
print(f"\nDone! Stored {len(chunks)} chunks from {len(docs)} pages into {DB_DIR}")