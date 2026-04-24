"""Extract all document chunks from ChromaDB into a plain JSON file.
Run once: python extract_chunks.py
"""
import chromadb
import json
from pathlib import Path

client = chromadb.PersistentClient(path="./chroma_db")
cols = client.list_collections()
print(f"Collections found: {len(cols)}")

if not cols:
    print("ERROR: No collections in chroma_db")
    raise SystemExit(1)

col = cols[0]
data = col.get(include=["documents", "metadatas"])

chunks = []
for id_, doc, meta in zip(data["ids"], data["documents"], data["metadatas"]):
    chunks.append({
        "id": id_,
        "text": doc,
        "source": (meta or {}).get("source", ""),
    })

out_path = Path("chunks.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(chunks, f, ensure_ascii=False)

size_kb = out_path.stat().st_size // 1024
print(f"Saved {len(chunks)} chunks to chunks.json ({size_kb} KB)")
