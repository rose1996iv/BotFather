# 🎓 GEU University Chatbot — BotFather

> AI-powered university admission assistant for **Graphic Era University (GEU)**, built specifically for Myanmar students. Responds in Myanmar (Burmese) language across **Messenger** and **Telegram** using RAG with multilingual query translation.

[![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.1-green?logo=flask)](https://flask.palletsprojects.com)
[![Groq](https://img.shields.io/badge/LLM-Groq%20LLaMA%203.3-orange)](https://groq.com)
[![Render](https://img.shields.io/badge/Hosted%20on-Render.com-purple)](https://render.com)
[![UptimeRobot](https://img.shields.io/badge/Monitored%20by-UptimeRobot-green)](https://uptimerobot.com)

---

## ✨ Features

| Feature | Details |
|---|---|
| 🇲🇲 Myanmar Language | Responds fully in Myanmar (Unicode), English terms preserved |
| 🔄 Query Translation | Myanmar → English translation before retrieval (llama-3.1-8b-instant) |
| 📚 Knowledge Base | GEU PDFs + Visa guide + Case studies (3000+ chunks) |
| 🔍 BM25 Retrieval | Keyword-based search, ~10 MB RAM (vs 470 MB for embeddings) |
| 🌐 Web Search | DuckDuckGo fallback via stdlib urllib (no library needed) |
| 🤖 Dual Bot | Facebook Messenger + Telegram (webhook, no polling thread) |
| 🎯 CTA Button | Every response ends with clickable "Apply Now" button |
| 🚀 Cloud Deployed | Render.com free tier + UptimeRobot keep-alive |

---

## 🏗️ Architecture

```
User Message (Myanmar)
        │
        ▼
    ask(question)
        │
        ├─ Stage 1: Keyword Expand (MM_EN_MAP dict, instant)
        │   "ကျောင်းကြေး" → "tuition fee"
        │
        ├─ Stage 2: LLM Translate (llama-3.1-8b-instant, ~0.3s)
        │   "CSE ကျောင်းကြေး" → "CSE tuition fee"
        │
        ├─ Stage 3: BM25 Search (chunks.json, instant)
        │   Top-6 relevant chunks from 3000+ GEU documents
        │
        ├─ Stage 4: Web Search (DuckDuckGo, if context thin)
        │
        └─ Stage 5: llama-3.3-70b-versatile → Myanmar response + CTA
                    Messenger: cleaned text + Button Template
                    Telegram:  Markdown + InlineKeyboard button
```

---

## 📚 Knowledge Base Contents

| Source | Content |
|---|---|
| `pdfs/` | 22 GEU Department Brochures (CSE, ECE, MBA, Law, Design, etc.) |
| `data/visa_and_travel.md` | Student Visa process, Myanmar→India travel guide |
| `data/global_arcus_case_studies.md` | Myanmar student case studies, success stories, FAQ |

> **Note**: PDFs are not committed to GitHub (too large). Only `chunks.json` is committed — it contains all pre-processed text chunks ready for BM25 search.

---

## 💾 Updating the Knowledge Base

### Add New Data (No PDF Processing Needed)

```bash
# 1. Edit or create a file in data/ folder
#    Supports: .md, .txt files
notepad data\new_topic.md

# 2. Re-ingest data/ files only (fast, no ML dependencies)
python ingest.py --data

# 3. Push updated chunks.json to GitHub
git add chunks.json data\
git commit -m "update: add new topic to knowledge base"
git push
# → Render auto-redeploys in ~2 minutes
```

### Add New PDFs (Full Re-ingest)

```bash
# 1. Add PDFs to pdfs/ folder
# 2. Install local dependencies (only needed for ingest)
pip install langchain-community langchain-text-splitters pypdf sentence-transformers langchain-huggingface

# 3. Re-ingest PDFs + data
python ingest.py

# 4. Push
git add chunks.json
git commit -m "update: add new PDF brochures"
git push
```

---

## 🚀 Local Development Setup

```bash
git clone https://github.com/rose1996iv/BotFather.git
cd BotFather

python -m venv venv
.\venv\Scripts\activate        # Windows
# source venv/bin/activate     # Mac/Linux

pip install -r requirements.txt
```

### Configure `.env`
```env
GROQ_API_KEY=gsk_...
TELEGRAM_TOKEN=your_telegram_bot_token
META_PAGE_TOKEN=your_facebook_page_token
META_VERIFY_TOKEN=univ_bot_verify_2024
META_PAGE_ID=your_page_id
APP_URL=https://geu-university-bot.onrender.com
```

### Run Locally
```bash
# Bot server (Messenger webhook + Telegram webhook)
python messenger_bot.py

# Tunnel for Messenger webhook testing
.\cloudflared.exe tunnel --url http://localhost:5000
```

---

## ☁️ Render.com Deployment

| Setting | Value |
|---|---|
| Repository | `rose1996iv/BotFather` |
| Branch | `main` |
| Runtime | Python 3 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn messenger_bot:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120 --preload` |
| Instance Type | **Free** |

### Required Environment Variables (Render Dashboard → Environment)

| Key | Description |
|---|---|
| `GROQ_API_KEY` | Groq API key (free at groq.com) |
| `META_PAGE_TOKEN` | Facebook Page Access Token |
| `META_VERIFY_TOKEN` | `univ_bot_verify_2024` |
| `META_PAGE_ID` | Facebook Page ID |
| `TELEGRAM_TOKEN` | Telegram Bot Token from @BotFather |
| `APP_URL` | `https://geu-university-bot.onrender.com` |

### Meta Webhook Settings
```
Callback URL:  https://geu-university-bot.onrender.com/webhook
Verify Token:  univ_bot_verify_2024
```

### Telegram Webhook
Registered automatically at startup using `APP_URL`. No manual setup needed.

---

## ⏰ UptimeRobot Keep-Alive

Render free tier sleeps after 15 min inactivity. Add UptimeRobot monitor:
- **URL**: `https://geu-university-bot.onrender.com/health`
- **Type**: HTTP(s)
- **Interval**: 5 minutes

---

## 📁 Project Structure

```
BotFather/
├── agent.py              # Core: BM25 + query translation + Groq
├── messenger_bot.py      # Flask: Messenger webhook + Telegram webhook
├── ingest.py             # Knowledge base builder (PDFs + data/ files)
├── extract_chunks.py     # One-time ChromaDB → chunks.json migration
├── chunks.json           # Pre-built knowledge base (committed to repo)
├── data/                 # Text-based knowledge files (editable!)
│   ├── visa_and_travel.md          # Visa process, Myanmar→India guide
│   └── global_arcus_case_studies.md # Student stories, FAQ, benefits
├── pdfs/                 # Source PDFs (NOT committed — too large)
├── Procfile              # Render start command
├── requirements.txt      # Production dependencies (lightweight)
└── .env                  # Local secrets (never commit)
```

---

## 📦 Dependencies

```
Flask==3.1.3          # Web framework
groq==1.2.0           # LLM API (LLaMA 3.3 70b + 3.1 8b)
gunicorn==23.0.0      # Production WSGI server
python-dotenv==1.2.2  # .env loading
requests==2.33.1      # HTTP client
rank-bm25==0.2.2      # BM25 retrieval (~1 MB, pure Python)
```

> **RAM Usage**: ~100 MB total (vs 600+ MB with sentence-transformers — which crashed Render free tier)

---

## 🤖 Bot Channels

| Platform | Mode | Status |
|---|---|---|
| **Messenger** | Webhook (Meta Graph API) | ✅ Active |
| **Telegram** | Webhook (Telegram Bot API) | ✅ Active |
| **WhatsApp** | Pending Meta Business Verification | 🔜 Planned |

---

## 📞 Apply Now

🔗 **Admission Form**: https://tinyurl.com/2dj2jefy

Built for **Global Arcus** — Myanmar student admission program at Graphic Era University, India.
