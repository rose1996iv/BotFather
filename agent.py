import logging
import os
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv

_IMPORT_ERROR = None

try:
    from groq import Groq
    from langchain_chroma import Chroma
    from langchain_huggingface import HuggingFaceEmbeddings
    from duckduckgo_search import DDGS
except ImportError as exc:
    Groq = None
    Chroma = None
    HuggingFaceEmbeddings = None
    DDGS = None
    _IMPORT_ERROR = exc

load_dotenv()

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
CHROMA_DIR = BASE_DIR / "chroma_db"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
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
- Use the provided PDF context + web search results as your knowledge base
- If web results are included, you may reference them but do not fabricate URLs
- If still unsure, say: "ဒီအချက်အတွက် www.geu.ac.in ကို တိုက်ရိုက် ဆက်သွယ်မေးကြည့်ပါ"
- Never invent facts

CALL TO ACTION (MANDATORY — end EVERY response with this):
Always finish with a motivational CTA block like this example:
---
🚀 GEU မှာ သင့်အနာဂတ်ကို စတင်ပါ! Scholarship နဲ့ India မှာ တက္ကသိုလ်ပညာသင်ကြားဖို့ ဒီနေ့ပဲ Admission Form ဖြည့်လိုက်ပါ:
👉 {ADMISSION_LINK}
---
"""

_runtime = None
_runtime_lock = Lock()


def _web_search(question: str, max_results: int = 3) -> str:
    """Search DuckDuckGo for GEU-related info when local context is insufficient."""
    if DDGS is None:
        return ""
    try:
        search_query = f"Graphic Era University GEU {question}"
        with DDGS() as ddgs:
            results = list(ddgs.text(search_query, max_results=max_results))
        if not results:
            return ""
        snippets = "\n\n".join(
            f"[Web] {r.get('title', '')}: {r.get('body', '')}"
            for r in results
        )
        logger.info("Web search returned %d results for: %s", len(results), question)
        return snippets
    except Exception:
        logger.warning("Web search failed", exc_info=True)
        return ""


def _initialize_runtime():
    if _IMPORT_ERROR is not None:
        raise RuntimeError(
            "Missing project dependencies. Activate the virtual environment "
            "or run `pip install -r requirements.txt` before starting the bot."
        ) from _IMPORT_ERROR

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not found in environment")

    if not CHROMA_DIR.exists() or not any(CHROMA_DIR.iterdir()):
        raise RuntimeError(
            f"Knowledge base not found in {CHROMA_DIR}. "
            "Run `python ingest.py` first to build the vector database."
        )

    logger.info("Loading retrieval and chat runtime...")
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    vectordb = Chroma(
        persist_directory=str(CHROMA_DIR),
        embedding_function=embeddings,
    )
    client = Groq(api_key=api_key)
    return {"vectordb": vectordb, "client": client}


def _get_runtime():
    global _runtime

    if _runtime is None:
        with _runtime_lock:
            if _runtime is None:
                _runtime = _initialize_runtime()
    return _runtime


def ask(question: str) -> str:
    try:
        runtime = _get_runtime()

        # Step 1: Search local PDF knowledge base
        docs = runtime["vectordb"].similarity_search(question, k=4)
        local_context = "\n\n".join(doc.page_content for doc in docs)

        # Step 2: If local context is thin, augment with web search
        web_context = ""
        if not local_context or len(local_context) < 150:
            logger.info("Local context insufficient — running web search")
            web_context = _web_search(question)

        # Combine contexts
        context_parts = []
        if local_context:
            context_parts.append(f"[From GEU Knowledge Base]\n{local_context}")
        if web_context:
            context_parts.append(f"[From Web Search]\n{web_context}")
        context = "\n\n".join(context_parts) or "No context found."

        response = runtime["client"].chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Context:\n{context}\n\nQuestion: {question}",
                },
            ],
            max_tokens=1024,
            temperature=0.7,
        )
        message = response.choices[0].message.content
        return message.strip() if message else "Sorry, I could not generate a response."
    except RuntimeError as exc:
        logger.error("Failed to answer question: %s", exc)
        return f"Sorry, something went wrong: {exc}"
    except Exception as exc:
        logger.exception("Failed to answer question")
        return f"Sorry, something went wrong: {exc}"
