# 🎓 GEU University Chatbot — BotFather

> AI-powered university admission assistant for Graphic Era University (GEU), built for Myanmar students. Responds in Myanmar (Burmese) language across **Messenger** and **Telegram** with RAG (Retrieval-Augmented Generation) + web search fallback.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com)

---

## ✨ Features

| Feature | Details |
|---|---|
| 🇲🇲 Myanmar Language | Responds fully in Myanmar (Unicode), English terms preserved |
| 🤖 Dual Bot | Facebook Messenger + Telegram in one deployment |
| 📚 RAG Knowledge Base | 22 GEU department PDFs embedded via ChromaDB |
| 🔍 Web Search Fallback | DuckDuckGo search when PDF context is insufficient |
| 🎯 CTA Button | Every response ends with clickable "Apply Now" button |
| 🚀 Cloud Deployed | Hosted on Render.com (free tier) |

---

## 🏗️ Architecture

```
User (Messenger / Telegram)
        ↓
Flask Webhook / Telegram Polling
        ↓
agent.ask(question)
        ├── ChromaDB similarity search (k=4)
        │       ↓ 22 GEU PDFs embedded
        ├── DuckDuckGo web search (fallback if context < 150 chars)
        └── Groq LLaMA-3.3-70b → Myanmar response + CTA
```

---

## 🚀 Quick Start (Local)

### Prerequisites
- Python 3.10+
- Groq API key (free at groq.com)
- Meta Developer App (for Messenger)
- Telegram Bot Token (from @BotFather)

### Setup

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
GROQ_API_KEY=your_groq_api_key
TELEGRAM_TOKEN=your_telegram_bot_token
META_PAGE_TOKEN=your_facebook_page_token
META_VERIFY_TOKEN=univ_bot_verify_2024
META_PAGE_ID=your_page_id
```

### Build Knowledge Base (first time only)
```bash
# Add your PDF files to pdfs/ folder, then:
python ingest.py
```

### Run Locally
```bash
# Terminal 1 — Bot server (Messenger + Telegram)
python messenger_bot.py

# Terminal 2 — Public URL (for Messenger webhook)
.\cloudflared.exe tunnel --url http://localhost:5000
```

---

## ☁️ Deploy to Render.com (Free)

### 1. Push to GitHub
```bash
git add .
git commit -m "update"
git push
```

### 2. Create Web Service on Render
| Setting | Value |
|---|---|
| Repository | `rose1996iv/BotFather` |
| Branch | `main` |
| Runtime | Python 3 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn messenger_bot:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120 --preload` |
| Instance Type | Free |

### 3. Add Environment Variables
```
GROQ_API_KEY        = gsk_...
META_PAGE_TOKEN     = EAAN...
META_VERIFY_TOKEN   = univ_bot_verify_2024
META_PAGE_ID        = 481917721665599
TELEGRAM_TOKEN      = 8685878466:AAF...
```

### 4. Update Meta Webhook
After deploy, go to Meta Developer Dashboard → Messenger API Settings → Webhooks:
```
Callback URL:  https://university-bot.onrender.com/webhook
Verify Token:  univ_bot_verify_2024
```

### 5. Keep Alive with UptimeRobot (Free)
- Sign up at [uptimerobot.com](https://uptimerobot.com)
- Add HTTP monitor: `https://university-bot.onrender.com/health`
- Interval: **5 minutes**
- This prevents Render free tier cold starts

---

## 📁 Project Structure

```
BotFather/
├── agent.py              # RAG core: ChromaDB + Groq + DuckDuckGo search
├── messenger_bot.py      # Flask webhook (Messenger) + Telegram polling thread
├── telegram_bot.py       # Standalone Telegram runner (local use)
├── ingest.py             # PDF → ChromaDB embedding builder
├── chroma_db/            # Pre-built vector database (committed to repo)
├── pdfs/                 # Source PDFs (not committed — too large)
├── Procfile              # Render start command
├── requirements.txt      # Python dependencies
└── .env                  # Local secrets (never commit)
```

---

## 🤖 Bot Channels

| Platform | Status | Setup |
|---|---|---|
| **Messenger** | ✅ Active | Meta Developer App + Page Token |
| **Telegram** | ✅ Active | @BotFather token |
| **WhatsApp** | 🔜 Planned | Requires Meta Business Verification |

---

## 📱 WhatsApp Integration (Coming Soon)

WhatsApp Business API requires:
1. **Meta Business Account** verified
2. **Dedicated phone number** (not linked to personal WhatsApp)
3. **WhatsApp Business App** approved by Meta

Once approved, add `WHATSAPP_TOKEN` to `.env` and the webhook at `/webhook` already handles WhatsApp events.

---

## 🛠️ Tech Stack

| Component | Technology |
|---|---|
| LLM | Groq — LLaMA-3.3-70b-versatile |
| Embeddings | sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 |
| Vector DB | ChromaDB (local) |
| Web Search | DuckDuckGo (free, no API key) |
| Messenger API | Meta Graph API v19.0 |
| Telegram API | python-telegram-bot v22 |
| Web Server | Flask + Gunicorn |
| Hosting | Render.com (free tier) |
| Uptime | UptimeRobot (free) |

---

## 📞 Contact

Built for **Global Arcus** — Myanmar students admission program at Graphic Era University.

🔗 **Apply Now**: https://tinyurl.com/2dj2jefy
