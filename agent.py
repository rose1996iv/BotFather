"""
agent.py - Low-memory RAG agent: BM25 retrieval + query translation + Groq LLaMA.

Pipeline:
  Myanmar question
       -> keyword expand (dict, instant)
       -> translate to English (llama-3.1-8b-instant, fast)
       -> BM25 search over English PDF chunks
       -> llama-3.3-70b-versatile generates Myanmar answer

Memory: ~100 MB (safe for Render free 512 MB tier)
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
CHAT_MODEL = "llama-3.3-70b-versatile"   # Main response model
FAST_MODEL = "llama-3.1-8b-instant"       # Fast translation model
ADMISSION_LINK = "https://tinyurl.com/2dj2jefy"

# ---------------------------------------------------------------------------
# Myanmar -> English keyword expansion map
# Covers the most common terms Myanmar students use when asking about GEU.
# Zero API calls, zero latency.
# ---------------------------------------------------------------------------
MM_EN_MAP = {
    # Fees
    "\u1001\u103b\u1031\u102c\u1004\u103a\u1000\u103c\u1031\u1038": "tuition fee",
    "\u101e\u1004\u103a\u1000\u103c\u1031\u1038": "tuition fee",
    "\u1001\u103b\u1031\u102c\u1004\u103a\u101c\u1001\u103a": "fee cost",
    "\u1000\u103c\u1031\u1038\u1004\u103a\u1038": "fee cost price",
    # Programs / Departments
    "\u1000\u103d\u1014\u103a\u1015\u103b\u1031\u102c\u1010\u102c": "computer science CSE engineering",
    "\u1021\u1004\u103a\u1002\u103b\u1004\u103a\u1014\u102e\u101a\u102c": "engineering",
    "\u1006\u1031\u1038\u1015\u103d\u102c\u1038\u101b\u1031\u1038": "business management MBA",
    "\u1021\u1015\u102f\u1000\u103a\u1001\u103b\u1031\u102c\u1004\u103a": "law legal studies",
    "\u1012\u1000\u103d\u1031\u1038": "design",
    "\u1014\u100a\u103a\u1038\u1005\u1031\u1038": "nursing health",
    "\u1018\u102d\u102f\u101b\u1031\u1010\u102f": "biotechnology biology",
    "\u1006\u102d\u102f\u1019\u1000\u103c\u1019\u103a": "food science technology",
    "\u1019\u1000\u102c\u101e\u102d\u1015\u100a\u102a": "microbiology science",
    "\u1021\u1031\u101b\u102c\u101e\u102c": "aerospace space engineering",
    "\u1005\u1019\u103a\u101c\u1031\u1010\u1000\u103a\u101e\u102d\u1015\u100a\u102a": "electronics communication ECE",
    "\u1015\u101b\u1019\u1031\u1012\u101b\u102c\u1038\u101e\u102d\u1015\u100a\u102a": "paramedical science",
    "\u101d\u1004\u103a\u1000\u103c\u1031\u102c\u1038\u1001\u103c\u1031\u102c\u1038": "civil engineering",
    "\u101d\u1014\u103a\u1000\u103c\u1031\u102c\u1038": "electrical engineering",
    "\u101e\u100d\u102c": "mechanical engineering",
    # Admission & process
    "\u101d\u1004\u103a\u1001\u103d\u1004\u103a": "admission apply application",
    "\u101d\u1004\u103a\u1001\u103d\u1004\u103a\u101c\u103b\u103e\u1031\u1038": "application form admission form",
    "\u101e\u1019\u1039\u1019\u101c\u1031\u102c": "requirement eligibility criteria",
    "\u1021\u1001\u103a\u1001\u103a\u1021\u101c\u1031\u1015\u103a": "deadline last date",
    # Living & scholarship
    "\u1015\u100a\u102c\u101e\u1004\u103a\u1006\u1030": "scholarship award grant",
    "\u1015\u100a\u102c\u101e\u1004\u103a": "scholarship",
    "\u1021\u1006\u1031\u102c\u1004\u103a": "hostel accommodation dormitory",
    "\u1014\u1031\u1015\u100a\u103a\u1019\u100a\u103a": "living expenses accommodation",
    "\u1005\u102c\u1021\u1005\u102c": "food meal canteen",
    # General
    "\u1000\u103b\u1031\u102c\u1004\u103a\u101e\u102c": "university college",
    "\u1010\u1000\u1039\u1000\u101e\u102d\u1015\u100a\u102a": "university",
    "\u1000\u103b\u1031\u102c\u1004\u103a\u101e\u102c\u103c\u1031\u102c": "student",
    "\u1021\u1004\u103a\u1002\u103b\u1004\u103a\u1014\u102e": "india",
    "\u1014\u103e\u1005\u103a": "year academic year",
    "\u1010\u1014\u103e\u1005\u103a": "first year freshman",
    "\u1010\u1015\u103b\u1014\u103e\u1005\u103a": "second year sophomore",
    "\u1014\u1031\u102c\u1000\u103a\u1000\u103b\u1031\u102c\u1004\u103a\u101e\u102c\u101e\u102c": "international student foreign",
    "\u1015\u1031\u102c\u1004\u103a": "course program",
    "\u1018\u102d\u102f\u101b\u1014\u103a\u1019\u103e\u102f": "subject department",
    "\u1015\u100a\u102c\u101e\u1004\u103a\u101e\u1019\u102c\u1038": "scholarship criteria",
    "\u1006\u1031\u1038\u1015\u103d\u102c\u1038\u1015\u100a\u102c\u101e\u1004\u103a": "business scholarship MBA",
    "\u101b\u1004\u103a\u1014\u103e\u1005\u103a": "how many years duration",
    "\u1018\u102c\u101e\u102c": "language medium instruction",
    "\u101e\u1004\u103a\u101e\u1014\u103a\u1021\u1001\u103a\u1021\u101c\u1031\u1015\u103a": "contact information website",
}

SYSTEM_PROMPT = f"""You are a friendly Global Arcus Ambassador helping Myanmar students join Graphic Era University (GEU), India.

LANGUAGE RULE:
Write in BILINGUAL style: Myanmar (Burmese) sentences with English technical terms inline.
NATURAL pattern: "CSE Department ကတော့ computer science နဲ့ software engineering ကို သင်ကြားပေးပါတယ်"
NEVER write full Myanmar translations for: Tuition, Scholarship, Hostel, Semester, Campus, Department, Admission, Uniform, CGPA, GPA, Fee, Visa, Passport
Always keep numbers, amounts (USD), and proper nouns in English.

TONE:
- Warm, like an older sibling who studied at GEU
- Enthusiastic but honest — never oversell
- Conversational Myanmar (not formal/stiff)
- Emojis: 1-2 max per response (🎓 ✅ 💰 🌟)

RESPONSE FORMAT — BE CONCISE (max 4-6 sentences or bullet points):
- Answer the question directly first
- Use bullet points for lists of info
- Short sentences
- No filler phrases like "ကျွန်တော် ဒီနေ့ ဖြေပေးပါမယ်"

EXAMPLE — Good response:
Q: CSE ကျောင်းကြေး ဘယ်လောက်လဲ?
A: 💰 CSE Tuition fee ကတော့ USD 2,310 per year ပါ။
- Uniform fee: USD 250 (ပထမနှစ်တစ်ကြိမ်သာ)
- Scholarship ရရင် Hostel + food + living expenses FREE
- Global Arcus Program ကတော့ Scholarship ပါတဲ့ Package ဖြင့် Admission လုပ်ပေးပါတယ်

EXAMPLE — Bad response (too long, too formal, avoid this):
"ကျောင်းသားများ အားလုံးကို ကြိုဆိုပါသည်... GEU သည် ကောင်းမွန်သောတက္ကသိုလ်တစ်ခုဖြစ်ပြီး..."

VERIFIED FACTS (use exactly, never change these numbers):
- Tuition: USD 2,310 per year
- Uniform fee: USD 250 (first year only, one-time payment)
- Scholarship: Hostel + food + living expenses = 100% FREE
- Admission deadline: end of July each year
- GEU International contact: internationalaffairs@geu.ac.in
- Global Arcus contact: +918810366357

CONTEXT RULE:
- Use provided context first
- If unsure about something specific: "ဒီအချက်ကို www.geu.ac.in မှာ တိုက်ရိုက် စစ်ဆေးပါ"
- Never invent facts or numbers

MANDATORY CTA (always end response with exactly this, on its own line):
👉 Apply Now: {ADMISSION_LINK}
"""

_runtime = None
_runtime_lock = Lock()


def _tokenize(text: str) -> list:
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
        chunks = json.load(f)

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


def _keyword_expand(question: str) -> str:
    """
    Instant Myanmar->English expansion using MM_EN_MAP dictionary.
    Appends English equivalents so BM25 can match English PDF content.
    Zero API calls, zero latency.
    """
    extra = []
    for mm_term, en_term in MM_EN_MAP.items():
        if mm_term in question:
            extra.append(en_term)
    if extra:
        expanded = question + " " + " ".join(extra)
        logger.info("Keyword expand: +%d terms added", len(extra))
        return expanded
    return question


def _translate_query(question: str) -> str:
    """
    Translate Myanmar question to English using Groq llama-3.1-8b-instant.
    Fast (~0.3s), free tier, dramatically improves BM25 retrieval recall.
    Falls back to original question on any error.
    """
    # Skip translation if question is already mostly English
    myanmar_char_count = sum(1 for c in question if "\u1000" <= c <= "\u109f")
    if myanmar_char_count < 3:
        return question

    try:
        runtime = _get_runtime()
        resp = runtime["client"].chat.completions.create(
            model=FAST_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Translate the following Myanmar/Burmese text to English. "
                        "Output ONLY the English translation. No explanations. "
                        "Focus on university/education terminology."
                    ),
                },
                {"role": "user", "content": question},
            ],
            max_tokens=80,
            temperature=0,
        )
        translated = resp.choices[0].message.content.strip()
        logger.info("Query translated: '%s' -> '%s'", question[:30], translated[:50])
        # Return combined: both Myanmar+English for maximum BM25 coverage
        return f"{question} {translated}"
    except Exception:
        logger.warning("Query translation failed, using original", exc_info=True)
        return question


def _bm25_search(question: str, k: int = 6) -> str:
    """
    Two-stage retrieval pipeline:
      Stage 1: keyword expand  (dictionary, instant)
      Stage 2: LLM translate   (fast model, ~0.3s)
      Stage 3: BM25 search     (in-memory, instant)
    """
    expanded = _keyword_expand(question)
    search_query = _translate_query(expanded)

    runtime = _get_runtime()
    scores = runtime["bm25"].get_scores(_tokenize(search_query))
    top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
    top_texts = [runtime["texts"][i] for i in top_indices if scores[i] > 0]
    logger.info("BM25 retrieved %d chunks", len(top_texts))
    return "\n\n".join(top_texts)


def _web_search(question: str) -> str:
    """DuckDuckGo Instant Answers API - stdlib only, no extra library."""
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
        # Step 1: BM25 retrieval with query translation
        local_context = _bm25_search(question)

        # Step 2: Web search fallback if context is thin
        web_context = ""
        if len(local_context) < 200:
            logger.info("Local context thin - running web search")
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
                {
                    "role": "user",
                    "content": f"Context:\n{context}\n\nQuestion: {question}",
                },
            ],
            max_tokens=600,
            temperature=0.6,
        )
        message = response.choices[0].message.content
        return message.strip() if message else "Sorry, I could not generate a response."

    except RuntimeError as exc:
        logger.error("Failed to answer: %s", exc)
        return f"Sorry, something went wrong: {exc}"
    except Exception as exc:
        logger.exception("Failed to answer question")
        return f"Sorry, something went wrong: {exc}"
