# 🎓 GEU University Chatbot — BotFather

> AI-powered university admission assistant for **Graphic Era University (GEU)**, built specifically for Myanmar students. Responds in bilingual Myanmar+English style across **Messenger** and **Telegram** using RAG with multilingual query translation.

[![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.1-green?logo=flask)](https://flask.palletsprojects.com)
[![Groq](https://img.shields.io/badge/LLM-Groq%20LLaMA%203.3-orange)](https://groq.com)
[![Render](https://img.shields.io/badge/Hosted%20on-Render.com-purple)](https://render.com)
[![UptimeRobot](https://img.shields.io/badge/Monitored-UptimeRobot-brightgreen)](https://uptimerobot.com)

---

## ✨ Features

| Feature | Details |
|---|---|
| 🇲🇲 Bilingual Responses | Myanmar sentences + English technical terms inline |
| 🔄 Query Translation | Myanmar → English before BM25 retrieval (llama-3.1-8b-instant) |
| 📚 Knowledge Base | GEU PDFs + Visa guide + Myanmar student case studies (3000+ chunks) |
| 🔍 BM25 Retrieval | Keyword search, ~10 MB RAM (vs 470 MB for sentence-transformers) |
| 🌐 Web Search Fallback | DuckDuckGo via stdlib `urllib` — no extra library needed |
| 🤖 Dual Platform | Facebook Messenger webhook + Telegram webhook (no polling thread) |
| 🎯 CTA Button | Every response ends with clickable "Apply Now" |
| 👤 Human Handoff | Admin can take over conversation; bot auto-pauses/resumes |
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
        ├─ Stage 3: BM25 Search (chunks.json, instant, top-6 chunks)
        │
        ├─ Stage 4: Web Search fallback (if context < 200 chars)
        │
        └─ Stage 5: llama-3.3-70b-versatile → Bilingual response + CTA
                    Messenger: clean text + Button Template
                    Telegram:  Markdown + InlineKeyboard button
```

---

## 👤 Human Handoff (Admin Takeover)

Admin can take over any Messenger conversation directly from the Facebook Page inbox.

### Auto Flow

```
1. User sends message → Bot replies normally ✅

2. Admin types manually in Facebook Page inbox
        ↓ (webhook detects: is_echo=True, no app_id)
3. Bot AUTO-PAUSES for that user (30 minutes) ⏸️

4. User sends another message while paused:
   "Admin နဲ့ ဆက်သွယ်ဆဲ ဖြစ်ပါတယ်။ ခဏစောင့်ပါ..."

5. After 30 minutes → Bot AUTO-RESUMES ✅
```

### Manual Admin Control (REST API)

All endpoints secured by `ADMIN_SECRET` env var.

| Action | Method + URL |
|---|---|
| View paused users | `GET /admin/status?token=YOUR_SECRET` |
| Pause bot for user | `POST /admin/pause?token=YOUR_SECRET&user_id=XXX&minutes=30` |
| Resume bot immediately | `POST /admin/resume?token=YOUR_SECRET&user_id=XXX` |

> **Find user_id**: Check Render logs → `Messenger ← 12345678901234: ...`

---

## 📚 Knowledge Base Contents

| Source | Content |
|---|---|
| `pdfs/` | 22 GEU Department Brochures (CSE, ECE, MBA, Law, Nursing, Design, etc.) |
| `data/visa_and_travel.md` | Student Visa documents, Embassy contacts, Myanmar→India travel guide, FRRO registration |
| `data/global_arcus_case_studies.md` | Real student case studies (Ko Peter, Ko Peng, Ko Thang, Ma Ngun), Batch stats, FAQ |

> PDFs are not committed to GitHub (too large). Only `chunks.json` is committed.

---

## 💾 Updating the Knowledge Base

### Add or Edit Content (No PDFs Needed — Fastest)

```bash
# 1. Edit a file in data/ folder (Markdown or plain text)
#    e.g. add a new FAQ, update contact info, add a case study
notepad data\global_arcus_case_studies.md

# 2. Re-ingest data/ only (seconds, no ML dependencies)
python ingest.py --data

# 3. Push → Render auto-redeploys in ~2 minutes
git add chunks.json data\
git commit -m "update: describe what you changed"
git push
```

### Add New PDFs

```bash
# 1. Add PDFs to pdfs/ folder
# 2. Install local ingest dependencies
pip install langchain-community langchain-text-splitters pypdf

# 3. Run full ingest
python ingest.py

# 4. Push
git add chunks.json
git commit -m "update: add new PDF brochures"
git push
```

---

## 🚀 Local Development

```bash
git clone https://github.com/rose1996iv/BotFather.git
cd BotFather
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

### `.env` file

```env
GROQ_API_KEY=gsk_...
TELEGRAM_TOKEN=your_telegram_bot_token
META_PAGE_TOKEN=your_facebook_page_token
META_VERIFY_TOKEN=univ_bot_verify_2024
META_PAGE_ID=your_page_id
APP_URL=https://geu-university-bot.onrender.com
ADMIN_SECRET=your_custom_secret_here
```

### Run Locally

```bash
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

### Environment Variables (Render Dashboard → Environment)

| Key | Value / Description |
|---|---|
| `GROQ_API_KEY` | Groq API key (free at groq.com) |
| `META_PAGE_TOKEN` | Facebook Page Access Token |
| `META_VERIFY_TOKEN` | `univ_bot_verify_2024` |
| `META_PAGE_ID` | Facebook Page ID |
| `TELEGRAM_TOKEN` | Telegram Bot Token from @BotFather |
| `APP_URL` | `https://geu-university-bot.onrender.com` |
| `ADMIN_SECRET` | Your custom secret for admin API |

### Meta Webhook Settings

```
Callback URL:  https://geu-university-bot.onrender.com/webhook
Verify Token:  univ_bot_verify_2024
```

### Messenger Public Reply Checklist

If Messenger replies only work for the Page admin, the most likely issue is **Meta App configuration**, not Python code.

- Switch the Meta app from **Development** to **Live** mode
- Make sure the app has the required Messenger / Page permissions reviewed for public users, especially `pages_messaging`
- Re-subscribe the Page to the webhook after token / permission changes if needed
- Test again with a normal Facebook user account that does **not** have an app role

While the app is still in Development mode, only app-role users such as admins, developers, or testers can usually talk to the bot.

### Telegram Webhook

Auto-registered at startup using `APP_URL`. No manual setup needed.

---

## ⏰ UptimeRobot Keep-Alive

Render free tier sleeps after 15 min of inactivity.

- **URL**: `https://geu-university-bot.onrender.com/health`
- **Type**: HTTP(s)
- **Interval**: 5 minutes

---

## 📁 Project Structure

```
BotFather/
├── agent.py                        # Core: BM25 + query translation + Groq
├── messenger_bot.py                # Flask: Messenger + Telegram webhooks + Human Handoff
├── ingest.py                       # Knowledge base builder (PDFs + data/ files)
├── extract_chunks.py               # One-time ChromaDB → chunks.json migration
├── chunks.json                     # Pre-built knowledge base (committed to repo)
├── data/                           # Editable text knowledge files
│   ├── visa_and_travel.md          # Visa process, Embassy, Myanmar→India guide
│   └── global_arcus_case_studies.md # Student stories, batch stats, FAQ
├── pdfs/                           # Source PDFs (NOT committed — too large)
├── Procfile                        # Render start command
├── requirements.txt                # Lightweight production dependencies
└── .env                            # Local secrets (never commit)
```

---

## 📦 Dependencies

```
Flask==3.1.3          # Web framework
groq==1.2.0           # LLM API (LLaMA 3.3 70b + 3.1 8b-instant)
gunicorn==23.0.0      # Production WSGI server
python-dotenv==1.2.2  # .env loading
requests==2.33.1      # HTTP client (Messenger + Telegram API calls)
rank-bm25==0.2.2      # BM25 retrieval (pure Python, ~1 MB)
```

> **RAM**: ~100 MB total (vs 600+ MB with sentence-transformers which crashed Render free tier)

> **Token usage**: ~700 tokens/question → ~142 questions/day on Groq free tier (100K tokens/day)

---

## 🌐 API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Service status |
| `/health` | GET | Health check (used by UptimeRobot) |
| `/webhook` | GET/POST | Facebook Messenger webhook |
| `/telegram-webhook` | POST | Telegram webhook |
| `/admin/status` | GET | View paused users (requires token) |
| `/admin/pause` | POST | Pause bot for a user (requires token) |
| `/admin/resume` | POST | Resume bot for a user (requires token) |

---

## 🤖 Bot Platforms

| Platform | Mode | Status |
|---|---|---|
| **Messenger** | Webhook (Meta Graph API v19) | ✅ Active |
| **Telegram** | Webhook (Telegram Bot API) | ✅ Active |
| **WhatsApp** | Pending Meta Business Verification | 🔜 Planned |

---

## 📋 Changelog

| Date | Change |
|---|---|
| 2026-04-24 | Initial deployment on Render.com |
| 2026-04-24 | Fixed OOM crash: replaced sentence-transformers with BM25 (500MB → 100MB) |
| 2026-04-24 | Added Telegram webhook (replaced polling thread — fixed signal handler crash) |
| 2026-04-24 | Added 2-stage retrieval: keyword expand + LLM query translation |
| 2026-04-24 | Added `data/` folder: Visa guide + Myanmar student case studies |
| 2026-04-24 | Improved response: bilingual format, concise (halved token usage) |
| 2026-04-24 | Added Human Handoff: auto-pause on admin reply, admin REST API |

---

## 📞 Apply Now

🔗 **Admission Form**: https://tinyurl.com/2dj2jefy

Built for **Global Arcus** — Myanmar student admission program at Graphic Era University, Dehradun, India.
- GEU International: internationalaffairs@geu.ac.in
- Global Arcus Contact: +918810366357
