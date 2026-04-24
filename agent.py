"""
agent.py — Low-memory RAG agent using BM25 keyword retrieval + Groq LLaMA.

Memory footprint:
  OLD: sentence-transformers + ChromaDB  → >512 MB ❌ Render free tier crash
  NEW: BM25 + chunks.json + Groq API     → ~100 MB ✅ stable
"""
import json
import logging
import os
import urllib.parse
import urllib.request
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv

_IMPORT_ERROR = None
try:
    from groq import Groq
    from rank_bm25 import BM25Okapi
except ImportError as exc:
    Groq = None
    BM25Okapi = None
    _IMPORT_ERROR = exc

load_dotenv()
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
CHUNKS_FILE = BASE_DIR / "chunks.json"
CHAT_MODEL = "llama-3.3-70b-versatile"
ADMISSION_LINK = "https://tinyurl.com/2dj2jefy"  # Short link → globalarcus.com/apply-now

SYSTEM_PROMPT = f"""You are a passionate Global Arcus Ambassador for Graphic Era University (GEU), India.
Your mission: Help Myanmar students discover their dream of studying in India at GEU and INSPIRE them to apply.
Always reply in Myanmar (Burmese) language using Unicode Myanmar (not Zawgyi).

PERSONALITY & TONE:
- Be warm, enthusiastic, and encouraging — like a trusted older sibling who studied there
- Use friendly Myanmar conversational style (not formal/stiff)
- Show genuine excitement about GEU opportunities
- Use emojis sparingly but effectively (🎓 💡 🌟 ✅)

CRITICAL RULE — DO NOT TRANSLATE THESE ENGLISH TERMS:
These words must ALWAYS appear in English. Never substitute with Myanmar words:
  - "Uniform" → NEVER "ထဘီ" or "ယူနီဖောင်း"
  - "Tuition" → NEVER "ကျောင်းလခ" or "ပညာသင်ကြေး"
  - "Scholarship" → NEVER "ပညာသင်ဆု"
  - "Hostel" → NEVER "အဆောင်"
  - "Semester" → NEVER "နှစ်ဝက်"
  - "Campus" → NEVER "ကျောင်းဝင်းထဲ"
  - "Department" → NEVER "ဌာန"
  - "Admission" → NEVER "ဝင်ခွင့်"

CORRECT response style:
Q: CSE ကျောင်းကြေး ဘယ်လောက်လဲ?
A: 🎓 CSE Department ကတော့ မြန်မာကျောင်းသားတွေကြားမှာ အရမ်းပြိုင်ဆိုင်မှုမြင့်တဲ့ Program တစ်ခုပါ!

💰 ကြေးနှုန်းအချက်အလက် —
• Tuition fee: USD 2,310 per year
• Uniform fee: USD 250 (ပထမနှစ်တစ်ကြိမ်သာ)
• Scholarship ရရင် Hostel, food, living expenses အကုန် FREE ပါ 🌟

VERIFIED FACTS (always accurate):
- Tuition: USD 2,310 per year
- Uniform fee: USD 250 (first year only, one-time)
- Scholarship students: Hostel + food + living expenses = FREE
- Admission deadline: end of July (approximately)

CONTEXT RULE:
- Use the provided context as your knowledge base
- If web results are included, you may reference them
- If still unsure, say: "ဒီအချက်အတွက် www.geu.ac.in ကို တိုက်ရိုက် ဆက်သွယ်မေးကြည့်ပါ"
- Never invent facts

CALL TO ACTION (MANDATORY — end EVERY response with this block):
---
🚀 GEU မှာ သင့်အနာဂတ်ကို စတင်ပါ! Scholarship နဲ့ India မှာ တက္ကသိုလ်ပညာသင်ကြားဖို့ ဒီနေ့ပဲ Admission Form ဖြည့်လိုက်ပါ:
👉 {ADMISSION_LINK}
---
"""

_runtime = None
_runtime_lock = Lock()


def _tokenize(text: str) -> list[str]:
    """Simple whitespace tokenizer that handles both English and Myanmar text."""
    return text.lower().split()


def _initialize_runtime():
    if _IMPORT_ERROR is not None:
        raise RuntimeError(
            "Missing dependencies. Run `pip install -r requirements.txt`."
        ) from _IMPORT_ERROR

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not found in environment")

    if not CHUNKS_FILE.exists():
        raise RuntimeError(
            f"Knowledge base not found: {CHUNKS_FILE}. "
            "Run `python extract_chunks.py` to build it."
        )

    logger.info("Loading BM25 knowledge base from %s ...", CHUNKS_FILE)
    with open(CHUNKS_FILE, encoding="utf-8") as f:
        chunks: list[dict] = json.load(f)

    texts = [c["text"] for c in chunks]
    tokenized = [_tokenize(t) for t in texts]
    bm25 = BM25Okapi(tokenized)
    logger.info("BM25 index built: %d chunks", len(chunks))

    client = Groq(api_key=api_key)
    return {"bm25": bm25, "texts": texts, "client": client}


def _get_runtime():
    global _runtime
    if _runtime is None:
        with _runtime_lock:
            if _runtime is None:
                _runtime = _initialize_runtime()
    return _runtime


def _bm25_search(question: str, k: int = 5) -> str:
    """Retrieve top-k chunks from the knowledge base via BM25."""
    runtime = _get_runtime()
    scores = runtime["bm25"].get_scores(_tokenize(question))
    top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
    top_texts = [runtime["texts"][i] for i in top_indices if scores[i] > 0]
    return "\n\n".join(top_texts)


def _web_search(question: str) -> str:
    """DuckDuckGo Instant Answers API — stdlib only, no extra library."""
    try:
        q = urllib.parse.quote(f"Graphic Era University GEU {question}")
        url = f"https://api.duckduckgo.com/?q={q}&format=json&no_html=1&skip_disambig=1"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        texts = []
        if data.get("AbstractText"):
            texts.append(data["AbstractText"])
        for r in data.get("RelatedTopics", [])[:4]:
            if isinstance(r, dict) and r.get("Text"):
                texts.append(r["Text"])
        result = "\n\n".join(texts)
        if result:
            logger.info("Web search returned %d snippets", len(texts))
        return result
    except Exception:
        logger.warning("Web search failed", exc_info=True)
        return ""


def ask(question: str) -> str:
    try:
        # Step 1: BM25 retrieval from knowledge base
        local_context = _bm25_search(question)

        # Step 2: Web search fallback if context is thin
        web_context = ""
        if len(local_context) < 200:
            logger.info("Local context thin — running web search")
            web_context = _web_search(question)

        context_parts = []
        if local_context:
            context_parts.append(f"[From GEU Knowledge Base]\n{local_context}")
        if web_context:
            context_parts.append(f"[From Web Search]\n{web_context}")
        context = "\n\n".join(context_parts) or "No context found."

        runtime = _get_runtime()
        response = runtime["client"].chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
            ],
            max_tokens=1024,
            temperature=0.7,
        )
        message = response.choices[0].message.content
        return message.strip() if message else "Sorry, I could not generate a response."

    except RuntimeError as exc:
        logger.error("Failed to answer: %s", exc)
        return f"Sorry, something went wrong: {exc}"
    except Exception as exc:
        logger.exception("Failed to answer question")
        return f"Sorry, something went wrong: {exc}"
