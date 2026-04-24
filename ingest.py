"""
ingest.py — Build the knowledge base from PDFs + data/ markdown files.

Usage:
    python ingest.py           # Process pdfs/ + data/ → chunks.json
    python ingest.py --pdfs    # Process pdfs/ only
    python ingest.py --data    # Process data/ only (fast, no PDF deps needed)

After running, chunks.json is updated. Commit and push it to GitHub.
Render will auto-redeploy and the bot will use the new knowledge base.
"""
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PDF_DIR  = BASE_DIR / "pdfs"
DATA_DIR = BASE_DIR / "data"
OUT_FILE = BASE_DIR / "chunks.json"

CHUNK_SIZE    = 500   # characters per chunk
CHUNK_OVERLAP = 60    # overlap between consecutive chunks

# ─── Flags ────────────────────────────────────────────────────────────────────
args = sys.argv[1:]
do_pdfs = "--data" not in args   # default: process PDFs unless --data only
do_data = "--pdfs" not in args   # default: process data/ unless --pdfs only


def chunk_text(text: str, source: str) -> list[dict]:
    """Split a long text into overlapping chunks."""
    chunks = []
    start = 0
    idx = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunk = text[start:end].strip()
        if chunk:
            chunks.append({"id": f"{source}_{idx}", "text": chunk, "source": source})
            idx += 1
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


# ─── Load existing chunks (to merge, not overwrite) ───────────────────────────
existing: list[dict] = []
if OUT_FILE.exists():
    with open(OUT_FILE, encoding="utf-8") as f:
        existing = json.load(f)
    print(f"Loaded {len(existing)} existing chunks from {OUT_FILE.name}")


def remove_source(chunks: list[dict], source_prefix: str) -> list[dict]:
    """Remove all chunks from a given source so we can replace them."""
    return [c for c in chunks if not c.get("source", "").startswith(source_prefix)]


all_chunks = list(existing)
total_new = 0


# ─── Process PDF files ────────────────────────────────────────────────────────
if do_pdfs:
    if not PDF_DIR.exists():
        print("pdfs/ folder not found — skipping PDFs")
    else:
        try:
            from langchain_community.document_loaders import PyPDFLoader
            from langchain_text_splitters import RecursiveCharacterTextSplitter

            splitter = RecursiveCharacterTextSplitter(
                chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
            )
            pdf_files = sorted(PDF_DIR.glob("*.pdf"))
            if not pdf_files:
                print("No PDFs found in pdfs/")
            else:
                print(f"\nProcessing {len(pdf_files)} PDFs...")
                for pdf_path in pdf_files:
                    print(f"  Reading: {pdf_path.name}")
                    loader = PyPDFLoader(str(pdf_path))
                    docs = loader.load()
                    splits = splitter.split_documents(docs)
                    source_key = f"pdf:{pdf_path.name}"
                    all_chunks = remove_source(all_chunks, source_key)
                    for i, doc in enumerate(splits):
                        all_chunks.append({
                            "id": f"{source_key}_{i}",
                            "text": doc.page_content,
                            "source": source_key,
                        })
                        total_new += 1
                    print(f"    -> {len(splits)} chunks")
        except ImportError:
            print("langchain / pypdf not installed. Run with venv or install locally.")
            print("Skipping PDFs.")


# ─── Process data/ markdown & text files ─────────────────────────────────────
if do_data:
    DATA_DIR.mkdir(exist_ok=True)
    md_files = sorted(DATA_DIR.glob("*.md")) + sorted(DATA_DIR.glob("*.txt"))
    if not md_files:
        print("\nNo .md or .txt files found in data/ — skipping")
    else:
        print(f"\nProcessing {len(md_files)} data files...")
        for fpath in md_files:
            print(f"  Reading: {fpath.name}")
            text = fpath.read_text(encoding="utf-8")
            source_key = f"data:{fpath.name}"
            all_chunks = remove_source(all_chunks, source_key)  # replace old version
            new_chunks = chunk_text(text, source_key)
            all_chunks.extend(new_chunks)
            total_new += len(new_chunks)
            print(f"    -> {len(new_chunks)} chunks")


# ─── Save ─────────────────────────────────────────────────────────────────────
with open(OUT_FILE, "w", encoding="utf-8") as f:
    json.dump(all_chunks, f, ensure_ascii=False)

size_kb = OUT_FILE.stat().st_size // 1024
print(f"\n✅ Done! {len(all_chunks)} total chunks ({size_kb} KB) saved to {OUT_FILE.name}")
print(f"   New/updated chunks this run: {total_new}")
print(f"\nNext step: git add chunks.json && git commit -m 'update knowledge base' && git push")