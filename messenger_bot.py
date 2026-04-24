"""
University Chatbot — Messenger + Telegram unified entry point.
Flask handles Messenger webhooks; Telegram polling runs in a background thread.
"""
import logging
import os
import re
import threading

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
logging.getLogger("huggingface_hub").setLevel(logging.WARNING)

from agent import ask, ADMISSION_LINK

app = Flask(__name__)

PAGE_TOKEN = os.getenv("META_PAGE_TOKEN")
VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

PROCESSING_MESSAGE = "ရွာဖွေနေပါတယ်... ခဏစောင့်ပါ။"
GENERIC_ERROR_MESSAGE = "တောင်းပန်ပါတယ်။ အမှားတစ်ခု ဖြစ်ပွားသွားပါတယ်။ နောက်မှ ထပ်စမ်းကြည့်ပါ။"


# ─── Messenger helpers ────────────────────────────────────────────────────────

def clean_for_messenger(text: str) -> str:
    """Strip Markdown that Messenger renders as raw chars; remove inline CTA."""
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"\n---+\n?", "\n", text)
    text = re.sub(
        r"🚀.*?" + re.escape(ADMISSION_LINK) + r"\s*",
        "",
        text,
        flags=re.DOTALL,
    )
    text = text.replace(ADMISSION_LINK, "")
    return text.strip()


def send_text(recipient_id: str, text: str) -> None:
    if not PAGE_TOKEN:
        logger.error("META_PAGE_TOKEN not configured.")
        return
    MAX = 2000
    for chunk in [text[i:i + MAX] for i in range(0, len(text), MAX)]:
        _post_message({
            "recipient": {"id": recipient_id},
            "message": {"text": chunk},
            "messaging_type": "RESPONSE",
        })


def send_cta_button(recipient_id: str) -> None:
    if not PAGE_TOKEN:
        return
    _post_message({
        "recipient": {"id": recipient_id},
        "messaging_type": "RESPONSE",
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "button",
                    "text": "🎓 GEU မှာ သင့်အနာဂတ်ကို စတင်ပါ!\nScholarship နဲ့ India မှာ တက္ကသိုလ်ပညာသင်ကြားဖို့ ဒီနေ့ပဲ Admission Form ဖြည့်လိုက်ပါ။",
                    "buttons": [{
                        "type": "web_url",
                        "url": ADMISSION_LINK,
                        "title": "Apply Now 🎓",
                    }],
                },
            }
        },
    })


def _post_message(payload: dict) -> None:
    try:
        r = requests.post(
            "https://graph.facebook.com/v19.0/me/messages",
            json=payload,
            params={"access_token": PAGE_TOKEN},
            timeout=20,
        )
        logger.info("Messenger send: %s | %s", r.status_code, r.text)
    except requests.RequestException:
        logger.exception("Failed to send Messenger message")


def process_and_reply(sender_id: str, question: str) -> None:
    try:
        send_text(sender_id, PROCESSING_MESSAGE)
        raw = ask(question)
        send_text(sender_id, clean_for_messenger(raw))
        send_cta_button(sender_id)
    except Exception:
        logger.exception("Error processing Messenger reply")
        send_text(sender_id, GENERIC_ERROR_MESSAGE)


# ─── Flask routes ─────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "status": "ok",
        "service": "GEU University Bot",
        "bots": {
            "messenger": "active" if PAGE_TOKEN else "not configured",
            "telegram": "active" if TELEGRAM_TOKEN else "not configured",
        },
        "endpoints": {"/": "status", "/health": "health check", "/webhook": "Messenger webhook"},
    }), 200


@app.route("/favicon.ico", methods=["GET"])
def favicon():
    return "", 204


@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    logger.info("Verify attempt: mode=%s token_match=%s", mode, token == VERIFY_TOKEN)
    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("Webhook verified OK")
        return challenge or "", 200
    logger.warning("Webhook verification FAILED")
    return "Forbidden", 403


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    if data.get("object") != "page":
        return "OK", 200
    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):
            sender_id = event.get("sender", {}).get("id")
            if sender_id == entry.get("id"):
                continue
            if "message" not in event:
                continue
            msg = event["message"]
            if msg.get("is_echo"):
                continue
            text = msg.get("text", "").strip()
            if not text:
                continue
            logger.info("Messenger msg from %s: %s", sender_id, text)
            threading.Thread(
                target=process_and_reply, args=(sender_id, text), daemon=True
            ).start()
    return "OK", 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "page_token_configured": bool(PAGE_TOKEN),
        "verify_token_configured": bool(VERIFY_TOKEN),
        "telegram_configured": bool(TELEGRAM_TOKEN),
    }), 200


# ─── Telegram background thread ───────────────────────────────────────────────

def _start_telegram_bot():
    """Run Telegram polling in a background daemon thread."""
    if not TELEGRAM_TOKEN:
        logger.warning("TELEGRAM_TOKEN not set — Telegram bot disabled.")
        return
    try:
        import asyncio
        from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
        from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

        WELCOME = (
            "မင်္ဂလာပါ! 🎓 ကျွန်တော်က *Graphic Era University (GEU)* Admission Ambassador Bot ဖြစ်ပါတယ်။\n\n"
            "✅ Admission အကြောင်း\n✅ Tuition & Scholarship\n✅ Department & Program များ\n✅ Campus Life\n\n"
            "မည်သည့်မေးခွန်းမဆို မြန်မာဘာသာဖြင့် မေးနိုင်ပါတယ်! 👇"
        )

        async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            kb = [[InlineKeyboardButton("Apply Now 🎓", url=ADMISSION_LINK)]]
            await update.message.reply_text(WELCOME, parse_mode="Markdown",
                                            reply_markup=InlineKeyboardMarkup(kb))

        async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            q = update.message.text
            logger.info("Telegram msg: %s", q)
            await update.message.reply_text("🔍 ရွာဖွေနေပါတယ်... ခဏစောင့်ပါ။")
            ans = ask(q)
            kb = [[InlineKeyboardButton("Apply Now 🎓", url=ADMISSION_LINK)]]
            try:
                await update.message.reply_text(ans, parse_mode="Markdown",
                                                reply_markup=InlineKeyboardMarkup(kb),
                                                disable_web_page_preview=True)
            except Exception:
                await update.message.reply_text(ans, reply_markup=InlineKeyboardMarkup(kb))

        tg_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        tg_app.add_handler(CommandHandler("start", start))
        tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

        logger.info("Starting Telegram bot polling...")
        tg_app.run_polling(close_loop=False)
    except Exception:
        logger.exception("Telegram bot failed to start")


# ─── App startup ──────────────────────────────────────────────────────────────

def start_telegram_thread():
    t = threading.Thread(target=_start_telegram_bot, daemon=True, name="telegram-polling")
    t.start()
    logger.info("Telegram thread started: %s", t.name)


# Start Telegram when app loads (works with gunicorn --preload or direct)
start_telegram_thread()

if __name__ == "__main__":
    logger.info("PAGE_TOKEN set: %s", "YES" if PAGE_TOKEN else "NO")
    logger.info("VERIFY_TOKEN set: %s", "YES" if VERIFY_TOKEN else "NO")
    logger.info("TELEGRAM_TOKEN set: %s", "YES" if TELEGRAM_TOKEN else "NO")
    print("Bot server running on 0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
