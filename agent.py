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
import re
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
FAST_MODEL = "llama-3.1-8b-instant"
ADMISSION_LINK = "https://tinyurl.com/2dj2jefy"
ADMIN_CTA_LINE = "💬 အသေးစိတ်ထပ်မေးချင်ရင် Page Admin / Admin Team ကို တိုက်ရိုက် message ပို့ပြီး ဆက်သွယ်နိုင်ပါတယ်။"

UNIVERSITY_ALIASES = {
    "GEU": (
        "graphic era university",
        "graphic era",
        "geu",
        "graphic era deemed to be university",
    ),
    "GEHU": (
        "graphic era hill university",
        "gehu",
    ),
    "Royal Global University": (
        "royal global university",
        "royal global",
        "rgu",
    ),
    "Rungta International Skills University": (
        "rungta international skills university",
        "rungta university",
        "rungta",
    ),
    "SR University": (
        "sr university",
    ),
    "NIST University": (
        "nist university",
        "nist",
    ),
    "Khalsa College of Engineering & Technology": (
        "khalsa college of engineering",
        "khalsa college",
        "khalsa",
    ),
    "Gulzar Group of Institutes": (
        "gulzar group of institutes",
        "ggi",
        "gulzar",
    ),
    "DBU": (
        "dbu",
    ),
}

SUBJECT_QUERY_TERMS = (
    "\u1018\u102c\u101e\u102c",
    "\u101e\u1004\u103a\u1000\u103c\u102c\u1038",
    "subject",
    "subjects",
    "curriculum",
    "course",
    "courses",
    "module",
    "modules",
    "teach",
    "taught",
)

EXISTENCE_QUERY_TERMS = (
    "\u101b\u103e\u102d\u101c\u102c\u1038",
    "\u101b\u103e\u102d",
    "available",
    "offer",
    "offered",
    "department",
    "program",
    "programs",
)

CURRICULUM_HINTS = (
    "curriculum",
    "curriculum modules",
    "courses offered",
    "specialized courses",
    "topics",
    "subjects",
    "aerodynamics",
    "flight mechanics",
    "drone technology",
)

PROGRAM_HINTS = (
    "programs offered",
    "courses offered",
    "department of",
    "b.tech",
    "ph.d",
    "specializations offered",
)

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

BASE_SYSTEM_PROMPT = """
You are a friendly university admission assistant helping Myanmar students.

LANGUAGE RULE:
Write in BILINGUAL style: Myanmar (Burmese) sentences with English technical terms inline.
NEVER write full Myanmar translations for: Tuition, Scholarship, Hostel, Semester, Campus, Department, Admission, Uniform, CGPA, GPA, Fee, Visa, Passport
Always keep numbers, durations, and proper nouns in English.

TONE:
- Warm and helpful
- Enthusiastic but honest
- Conversational Myanmar (not formal/stiff)
- Emojis: 1-2 max per response

RESPONSE FORMAT:
- Answer directly first
- Use short bullet points for lists
- Keep it concise
- No filler

CONTEXT RULE:
- Use provided context first
- If the context explicitly shows that a Department or Program exists, never say it does not exist
- For "what subjects are taught" questions, prefer curriculum/modules/courses from context over faculty biography details
- If a specific detail is missing, tell the user to check the official website directly
- Never invent facts or numbers
"""

_runtime = None
_runtime_lock = Lock()


# Collapse degree abbreviations so "B.Sc" == "BSc" == "bsc", "Ph.D" == "phd".
# Applied to both the index and the query, so BM25 matching stays consistent.
_DOT_BETWEEN_LETTERS = re.compile(r"(?<=[a-z])\.(?=[a-z])")
_TOKEN_SPLIT = re.compile(r"[^a-z0-9က-႟]+")

# Generic/filler words that must NOT count as the "subject" the user asked about.
# Used to gate the program-existence bonus so an off-topic "Programs Offered"
# chunk (e.g. Paramedical) cannot answer a question about another subject (Nursing).
_GENERIC_TOKENS = {
    "the", "and", "are", "for", "you", "have", "has", "that", "this", "with",
    "can", "get", "about", "please", "tell", "does", "whether", "there", "any",
    "all", "available", "offer", "offered", "offers", "offering", "program",
    "programs", "programme", "programmes", "course", "courses", "subject",
    "subjects", "curriculum", "department", "departments", "university",
    "universities", "college", "colleges", "institute", "study", "studies",
    "degree", "degrees", "bachelor", "bachelors", "master", "masters",
    "science", "sciences", "arts", "technology", "diploma", "year", "years",
    "what", "which", "how", "many", "want", "looking", "studying", "general",
    "medical", "engineering", "management", "health", "hospital", "public",
    # Degree levels are not "subjects" — Nursing != Paramedical just because both grant a B.Sc.
    "bsc", "msc", "btech", "mtech", "phd", "mba", "bba", "mca", "bca", "bphil",
    "mphil", "phil", "basic", "hons", "honours", "honors",
}


def _tokenize(text: str) -> list[str]:
    text = _DOT_BETWEEN_LETTERS.sub("", text.lower())
    return [t for t in _TOKEN_SPLIT.split(text) if t]


def _subject_keywords(search_query: str) -> set[str]:
    """Distinctive subject words from the (expanded+translated) query, e.g. {"nursing"}."""
    return {
        t for t in re.findall(r"[a-z]{3,}", search_query.lower())
        if t not in _GENERIC_TOKENS
    }


def _infer_target_university(text: str) -> str | None:
    text_lower = text.lower()
    for university, aliases in UNIVERSITY_ALIASES.items():
        if any(alias in text_lower for alias in aliases):
            return university
    return None


def should_offer_geu_cta(question: str) -> bool:
    target = _infer_target_university(question)
    return target in (None, "GEU")


def _build_system_prompt(target_university: str | None) -> str:
    if target_university in (None, "GEU"):
        return (
            BASE_SYSTEM_PROMPT
            + f"""

FOCUS:
- Primary focus is Graphic Era University (GEU) unless the user explicitly asks about another university
- If the answer is about GEU, you may use these verified facts exactly:
  - Tuition: USD 2,310 per year
  - Uniform fee: USD 250 (first year only, one-time payment)
  - Scholarship: Hostel + food + living expenses = 100% FREE
  - Admission deadline: end of July each year
  - GEU International contact: internationalaffairs@geu.ac.in
  - Global Arcus contact: +918810366357
- If the answer is about GEU, end with exactly this line:
👉 Apply Now: {ADMISSION_LINK}
"""
        )

    return (
        BASE_SYSTEM_PROMPT
        + f"""

FOCUS:
- The user is asking about {target_university}
- Answer only from provided context about {target_university}
- Do not insert GEU tuition, GEU scholarship, GEU contacts, GEU website, or GEU apply link unless the user explicitly asks to compare with GEU
- Do not add any apply link unless it is explicitly present in the provided context for {target_university}
- If fee, scholarship, hostel, accommodation, contact, or website details are not explicitly present in the context, say they are not found in the current documents and ask the user to check the official website or message Page Admin / Admin Team
- Do not guess tuition, scholarship, free accommodation, or contact details
"""
    )


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
    sources = [c.get("source", "") for c in chunks]
    tokenized = [_tokenize(t) for t in texts]
    bm25 = BM25Okapi(tokenized)
    logger.info("BM25 index built: %d chunks", len(chunks))

    client = Groq(api_key=api_key)
    return {"bm25": bm25, "texts": texts, "sources": sources, "client": client}


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
        return f"{question} {translated}"
    except Exception:
        logger.warning("Query translation failed, using original", exc_info=True)
        return question


def _source_matches_university(source: str, aliases: tuple[str, ...]) -> bool:
    source_lower = source.lower().replace("-", " ").replace("_", " ")
    return any(alias in source_lower for alias in aliases)


def _chunk_matches_target(text: str, source: str, target_university: str) -> bool:
    aliases = UNIVERSITY_ALIASES[target_university]
    text_lower = text.lower()
    return any(alias in text_lower for alias in aliases) or _source_matches_university(source, aliases)


def _rank_chunks(
    question: str,
    texts: list[str],
    sources: list[str],
    scores,
    k: int = 6,
    subject_keywords: set[str] | None = None,
) -> list[str]:
    question_lower = question.lower()
    wants_subjects = any(term in question_lower for term in SUBJECT_QUERY_TERMS)
    asks_existence = any(term in question_lower for term in EXISTENCE_QUERY_TERMS)
    target_university = _infer_target_university(question)
    subject_keywords = subject_keywords or set()

    ranked = []
    for idx, base_score in enumerate(scores):
        if base_score <= 0:
            continue

        text = texts[idx]
        source = sources[idx]
        text_lower = text.lower()
        bonus = 0.0

        # Does this chunk actually talk about the subject the user asked about?
        has_subject = bool(subject_keywords) and any(kw in text_lower for kw in subject_keywords)

        if wants_subjects and any(hint in text_lower for hint in CURRICULUM_HINTS):
            bonus += 3.0
        if asks_existence and any(hint in text_lower for hint in PROGRAM_HINTS):
            # Only reward a "Programs Offered" / department chunk when it is about
            # the asked subject — otherwise another department's program list can
            # hijack the answer and wrongly report the subject as missing.
            if not subject_keywords or has_subject:
                bonus += 4.0
        # Generally float on-topic chunks above unrelated ones.
        if has_subject:
            bonus += 2.0
        if "aerospace" in question_lower and "aerospace" in text_lower:
            bonus += 1.0

        if target_university:
            aliases = UNIVERSITY_ALIASES[target_university]
            if any(alias in text_lower for alias in aliases) or _source_matches_university(source, aliases):
                bonus += 4.0
            if target_university != "GEU":
                geu_aliases = UNIVERSITY_ALIASES["GEU"]
                if any(alias in text_lower for alias in geu_aliases) or _source_matches_university(source, geu_aliases):
                    bonus -= 2.0

        ranked.append((base_score + bonus, idx, text))

    if target_university:
        target_ranked = [
            item for item in ranked
            if _chunk_matches_target(item[2], sources[item[1]], target_university)
        ]
        if target_ranked:
            ranked = target_ranked

    ranked.sort(key=lambda item: item[0], reverse=True)

    unique_texts = []
    seen = set()
    for _, _, text in ranked:
        normalized = " ".join(text.split()).lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_texts.append(text)
        if len(unique_texts) >= k:
            break
    return unique_texts


def _bm25_search(question: str, k: int = 6) -> str:
    """
    Two-stage retrieval pipeline:
      Stage 1: keyword expand  (dictionary, instant)
      Stage 2: LLM translate   (fast model, ~0.3s)
      Stage 3: BM25 search     (in-memory, instant)
    """
    expanded = _keyword_expand(question)
    search_query = _translate_query(expanded)
    subject_keywords = _subject_keywords(search_query)

    runtime = _get_runtime()
    scores = runtime["bm25"].get_scores(_tokenize(search_query))
    top_texts = _rank_chunks(
        question,
        runtime["texts"],
        runtime["sources"],
        scores,
        k=k,
        subject_keywords=subject_keywords,
    )
    logger.info("BM25 retrieved %d chunks", len(top_texts))
    return "\n\n".join(top_texts)


def _web_search(question: str, target_university: str | None = None) -> str:
    """DuckDuckGo Instant Answers API - stdlib only, no extra library."""
    try:
        prefix = target_university or "university admission"
        q = urllib.parse.quote(f"{prefix} {question}")
        url = f"https://api.duckduckgo.com/?q={q}&format=json&no_html=1&skip_disambig=1"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        texts = []
        if data.get("AbstractText"):
            texts.append(data["AbstractText"])
        for result in data.get("RelatedTopics", [])[:4]:
            if isinstance(result, dict) and result.get("Text"):
                texts.append(result["Text"])
        combined = "\n\n".join(texts)
        if combined:
            logger.info("Web search returned %d snippets", len(texts))
        return combined
    except Exception:
        logger.warning("Web search failed", exc_info=True)
        return ""


def _strip_generated_cta(text: str) -> str:
    text = re.sub(r"(?im)^[^\S\r\n]*.*Apply Now:.*(?:\r?\n|$)", "", text)
    text = text.replace(ADMISSION_LINK, "")
    text = re.sub(r"(?im)^[^\S\r\n]*.*Page Admin / Admin Team.*(?:\r?\n|$)", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _finalize_answer(answer: str, target_university: str | None) -> str:
    cleaned = _strip_generated_cta(answer)
    suffix_lines = [ADMIN_CTA_LINE]
    if target_university in (None, "GEU"):
        suffix_lines.append(f"👉 Apply Now: {ADMISSION_LINK}")
    return cleaned + "\n" + "\n".join(suffix_lines)


def ask(question: str) -> str:
    try:
        target_university = _infer_target_university(question)

        local_context = _bm25_search(question)

        web_context = ""
        if len(local_context) < 200:
            logger.info("Local context thin - running web search")
            web_context = _web_search(question, target_university=target_university)

        context_parts = []
        if local_context:
            context_parts.append(f"[From University Knowledge Base]\n{local_context}")
        if web_context:
            context_parts.append(f"[From Web Search]\n{web_context}")
        context = "\n\n".join(context_parts) or "No context found."

        runtime = _get_runtime()
        response = runtime["client"].chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": _build_system_prompt(target_university)},
                {
                    "role": "user",
                    "content": f"Context:\n{context}\n\nQuestion: {question}",
                },
            ],
            max_tokens=600,
            temperature=0.2,
        )
        message = response.choices[0].message.content
        if not message:
            return "Sorry, I could not generate a response."
        return _finalize_answer(message.strip(), target_university)

    except RuntimeError as exc:
        logger.error("Failed to answer: %s", exc)
        return f"Sorry, something went wrong: {exc}"
    except Exception as exc:
        logger.exception("Failed to answer question")
        return f"Sorry, something went wrong: {exc}"
