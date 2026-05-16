"""
University Chatbot — Messenger + Telegram, single Flask process.

Architecture:
  - Messenger: POST /webhook  (Meta sends events here)
  - Telegram:  POST /telegram-webhook  (Telegram sends events here)

No background threads. No polling. Both platforms handled via HTTP webhooks.
Memory usage: ~100-120 MB (safe for Render free 512 MB tier).
"""
import csv
import json
import logging
import os
import re
import threading
import time
from datetime import datetime

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_file

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

from agent import ask, ADMISSION_LINK, should_offer_geu_cta

app = Flask(__name__)

PAGE_TOKEN          = os.getenv("META_PAGE_TOKEN")
VERIFY_TOKEN        = os.getenv("META_VERIFY_TOKEN")
TELEGRAM_TOKEN      = os.getenv("TELEGRAM_TOKEN")
# Set APP_URL in Render env vars → e.g. https://geu-university-bot.onrender.com
APP_URL             = os.getenv("APP_URL", "").rstrip("/")
ADMIN_SECRET        = os.getenv("ADMIN_SECRET", "geu_admin_2024")  # Set in Render env vars
LOG_CHANNEL_ID      = os.getenv("LOG_CHANNEL_ID", "")             # Telegram admin chat/channel ID for logs
TELEGRAM_BOT_LINK   = "https://t.me/GEU_Admission_bot"
LOG_CSV_PATH        = "logs.csv"

PROCESSING_MSG  = "ရွာဖွေနေပါတယ်... ခဏစောင့်ပါ။"
PAUSED_MSG      = "Admin နဲ့ ဆက်သွယ်ဆဲ ဖြစ်ပါတယ်။ ခဏစောင့်ပါ — bot မကြာမီ ပြန်ဖွင့်မည်။"
ERROR_MSG       = "တောင်းပန်ပါတယ်။ အမှားတစ်ခု ဖြစ်ပွားသွားပါတယ်။ နောက်မှ ထပ်စမ်းကြည့်ပါ။"

TG_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}" if TELEGRAM_TOKEN else ""

# ─── Data Logging ─────────────────────────────────────────────────────────────

_csv_lock = threading.Lock()

def _log_to_csv(platform: str, user_id: str, username: str,
                first_name: str, last_name: str, message: str) -> None:
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    row = [timestamp, platform, user_id, username, first_name, last_name, message]
    try:
        with _csv_lock:
            file_exists = os.path.isfile(LOG_CSV_PATH)
            with open(LOG_CSV_PATH, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow([
                        "timestamp", "platform", "user_id",
                        "username", "first_name", "last_name", "message"
                    ])
                writer.writerow(row)
    except Exception:
        logger.exception("Failed to write CSV log")


def _log_to_admin_channel(platform: str, user_id: str, username: str,
                           first_name: str, message: str) -> None:
    if not LOG_CHANNEL_ID or not TELEGRAM_TOKEN:
        return
    username_str = f"@{username}" if username else "—"
    # Use plain text to avoid MarkdownV2 escape issues with user-generated content
    text = (
        f"📊 [{platform}] New Message\n"
        f"👤 {first_name} ({username_str})\n"
        f"🆔 ID: {user_id}\n"
        f"❓ {message}\n"
        f"🕐 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
    )
    try:
        requests.post(
            f"{TG_API}/sendMessage",
            json={"chat_id": LOG_CHANNEL_ID, "text": text},
            timeout=10,
        )
    except Exception:
        logger.exception("Failed to send log to admin Telegram channel")


def log_message(platform: str, user_id: str, username: str = "",
                first_name: str = "", last_name: str = "", message: str = "") -> None:
    """Log to CSV (sync) and Telegram admin channel (async thread)."""
    _log_to_csv(platform, user_id, username, first_name, last_name, message)
    threading.Thread(
        target=_log_to_admin_channel,
        args=(platform, user_id, username, first_name, message),
        daemon=True,
    ).start()


def tg_send_admin(text: str) -> None:
    """Send a plain-text message to the admin Telegram group/channel."""
    if not LOG_CHANNEL_ID or not TELEGRAM_TOKEN:
        return
    try:
        requests.post(
            f"{TG_API}/sendMessage",
            json={"chat_id": LOG_CHANNEL_ID, "text": text},
            timeout=10,
        )
    except Exception:
        logger.exception("Failed to send admin notification to Telegram")


def _notify_admin_messenger(sender_id: str, message: str) -> None:
    """Forward an incoming Messenger message to the admin Telegram group."""
    text = (
        f"📨 MESSENGER — New Message\n"
        f"🆔 User ID: {sender_id}\n"
        f"💬 {message}\n\n"
        f"↩️ Reply from here:\n"
        f"/reply {sender_id} [your message]"
    )
    threading.Thread(target=tg_send_admin, args=(text,), daemon=True).start()


# ─── Human Handoff — pause registry ──────────────────────────────────────────
# {user_id: expiry_timestamp} — in-memory only, resets on redeploy (acceptable)

PAUSE_DURATION_SEC = 30 * 60   # 30 minutes default

_paused_users: dict = {}
_pause_lock = threading.Lock()


def pause_user(user_id: str, duration: int = PAUSE_DURATION_SEC) -> None:
    with _pause_lock:
        _paused_users[user_id] = time.time() + duration
    logger.info("Bot PAUSED for user %s (%d min)", user_id, duration // 60)


def resume_user(user_id: str) -> None:
    with _pause_lock:
        _paused_users.pop(user_id, None)
    logger.info("Bot RESUMED for user %s", user_id)


def is_paused(user_id: str) -> bool:
    with _pause_lock:
        expiry = _paused_users.get(user_id)
        if expiry is None:
            return False
        if time.time() > expiry:
            _paused_users.pop(user_id, None)
            logger.info("Auto-resumed user %s (30 min timeout)", user_id)
            return False
        return True


def _get_paused_status() -> dict:
    """Return currently active paused users (auto-cleans expired)."""
    now = time.time()
    with _pause_lock:
        expired = [uid for uid, exp in _paused_users.items() if now > exp]
        for uid in expired:
            del _paused_users[uid]
        return {uid: f"{int(exp - now)}s remaining" for uid, exp in _paused_users.items()}


# ─── Telegram helpers (pure requests, no library) ─────────────────────────────

def tg_send(chat_id: str | int, text: str, with_button: bool = False) -> None:
    if not TELEGRAM_TOKEN:
        return
    payload: dict = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if with_button:
        payload["reply_markup"] = {
            "inline_keyboard": [[
                {"text": "Apply GEU 🎓", "url": ADMISSION_LINK}
            ]]
        }
    try:
        requests.post(f"{TG_API}/sendMessage", json=payload, timeout=15)
    except Exception:
        logger.exception("Failed to send Telegram message")


def register_telegram_webhook() -> None:
    """Tell Telegram where to send updates (called once at startup)."""
    if not TELEGRAM_TOKEN or not APP_URL:
        if TELEGRAM_TOKEN and not APP_URL:
            logger.warning("APP_URL not set — Telegram webhook NOT registered. "
                           "Add APP_URL env var on Render.")
        return
    webhook_url = f"{APP_URL}/telegram-webhook"
    try:
        r = requests.post(f"{TG_API}/setWebhook",
                          json={"url": webhook_url, "allowed_updates": ["message"]},
                          timeout=10)
        logger.info("Telegram webhook registered → %s | %s", webhook_url, r.json())
    except Exception:
        logger.exception("Failed to register Telegram webhook")


# ─── Messenger helpers ─────────────────────────────────────────────────────────

def clean_for_messenger(text: str) -> str:
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"\n---+\n?", "\n", text)
    text = re.sub(r"(?im)^[^\S\r\n]*.*Apply Now:.*(?:\r?\n|$)", "", text)
    text = text.replace(ADMISSION_LINK, "")
    text = re.sub(r"(?m)^[^\w\s]{1,4}\s*$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fb_send_text(recipient_id: str, text: str) -> None:
    if not PAGE_TOKEN:
        return
    for chunk in [text[i:i + 2000] for i in range(0, len(text), 2000)]:
        _fb_post({"recipient": {"id": recipient_id},
                  "message": {"text": chunk},
                  "messaging_type": "RESPONSE"})


def fb_send_cta(recipient_id: str) -> None:
    if not PAGE_TOKEN:
        return
    _fb_post({
        "recipient": {"id": recipient_id},
        "messaging_type": "RESPONSE",
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "button",
                    "text": ("🎓 GEU admission form ဖြည့်လိုက်ပါ။\n"
                             "အသေးစိတ်ထပ်မေးချင်ရင် Page Admin ကို တိုက်ရိုက် message ပို့နိုင်ပါတယ်။"),
                    "buttons": [{"type": "web_url", "url": ADMISSION_LINK,
                                 "title": "Apply GEU 🎓"}],
                },
            }
        },
    })


def _fb_post(payload: dict) -> None:
    try:
        r = requests.post("https://graph.facebook.com/v19.0/me/messages",
                          json=payload,
                          params={"access_token": PAGE_TOKEN},
                          timeout=20)
        logger.info("FB send %s | %s", r.status_code, r.text[:120])
    except Exception:
        logger.exception("Failed to send Messenger message")


# ─── Background reply workers ──────────────────────────────────────────────────

def _messenger_reply(sender_id: str, question: str) -> None:
    try:
        fb_send_text(sender_id, PROCESSING_MSG)
        raw = ask(question)
        fb_send_text(sender_id, clean_for_messenger(raw))
        if should_offer_geu_cta(question):
            fb_send_cta(sender_id)
        fb_send_text(
            sender_id,
            f"💬 ပိုမိုကောင်းမွန်တဲ့ experience အတွက် Telegram bot ကို သုံးပါ 👇\n"
            f"👉 {TELEGRAM_BOT_LINK}"
        )
    except Exception:
        logger.exception("Messenger reply error")
        fb_send_text(sender_id, ERROR_MSG)


def _telegram_reply(chat_id: int, question: str) -> None:
    try:
        tg_send(chat_id, "🔍 ရွာဖွေနေပါတယ်... ခဏစောင့်ပါ။")
        raw = ask(question)
        tg_send(chat_id, raw, with_button=should_offer_geu_cta(question))
    except Exception:
        logger.exception("Telegram reply error")
        tg_send(chat_id, ERROR_MSG)


# ─── Flask routes ──────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "status": "ok",
        "service": "University Admission Bot",
        "bots": {
            "messenger": "active" if PAGE_TOKEN else "not configured",
            "telegram": "webhook" if TELEGRAM_TOKEN else "not configured",
        },
    }), 200


@app.route("/favicon.ico")
def favicon():
    return "", 204


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "messenger": bool(PAGE_TOKEN),
        "telegram": bool(TELEGRAM_TOKEN),
        "app_url": APP_URL or "not set",
        "paused_users": len(_get_paused_status()),
    }), 200


# ── Admin control endpoints ────────────────────────────────────────────────────

def _check_admin(req) -> bool:
    token = req.args.get("token")
    if token:
        return token == ADMIN_SECRET
    payload = req.get_json(silent=True) or {}
    token = payload.get("token")
    return token == ADMIN_SECRET


@app.route("/admin/status", methods=["GET"])
def admin_status():
    """GET /admin/status?token=SECRET — list paused users."""
    if request.args.get("token") != ADMIN_SECRET:
        return jsonify({"error": "unauthorized"}), 403
    return jsonify({"paused": _get_paused_status()}), 200


@app.route("/admin/pause", methods=["POST"])
def admin_pause():
    """POST /admin/pause?token=SECRET&user_id=xxx&minutes=30 — pause bot for a user."""
    if request.args.get("token") != ADMIN_SECRET:
        return jsonify({"error": "unauthorized"}), 403
    user_id = request.args.get("user_id") or (request.get_json(silent=True) or {}).get("user_id")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    minutes = int(request.args.get("minutes", 30))
    pause_user(user_id, duration=minutes * 60)
    return jsonify({"paused": user_id, "duration_min": minutes}), 200


@app.route("/admin/resume", methods=["POST"])
def admin_resume():
    """POST /admin/resume?token=SECRET&user_id=xxx — resume bot for a user."""
    if request.args.get("token") != ADMIN_SECRET:
        return jsonify({"error": "unauthorized"}), 403
    user_id = request.args.get("user_id") or (request.get_json(silent=True) or {}).get("user_id")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    resume_user(user_id)
    return jsonify({"resumed": user_id}), 200


@app.route("/admin/logs", methods=["GET"])
def admin_logs():
    """GET /admin/logs?token=SECRET — download logs.csv file."""
    if request.args.get("token") != ADMIN_SECRET:
        return jsonify({"error": "unauthorized"}), 403
    if not os.path.isfile(LOG_CSV_PATH):
        return jsonify({"error": "No logs yet"}), 404
    return send_file(
        LOG_CSV_PATH,
        mimetype="text/csv",
        as_attachment=True,
        download_name="bot_logs.csv",
    )


@app.route("/admin/logs/count", methods=["GET"])
def admin_logs_count():
    """GET /admin/logs/count?token=SECRET — total message count per platform."""
    if request.args.get("token") != ADMIN_SECRET:
        return jsonify({"error": "unauthorized"}), 403
    if not os.path.isfile(LOG_CSV_PATH):
        return jsonify({"total": 0, "telegram": 0, "messenger": 0}), 200
    counts: dict = {"TELEGRAM": 0, "MESSENGER": 0}
    try:
        with open(LOG_CSV_PATH, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                platform = row.get("platform", "").upper()
                counts[platform] = counts.get(platform, 0) + 1
    except Exception:
        logger.exception("Failed to read CSV for count")
    return jsonify({
        "total": sum(counts.values()),
        "telegram": counts.get("TELEGRAM", 0),
        "messenger": counts.get("MESSENGER", 0),
    }), 200


# ── Messenger webhook ──────────────────────────────────────────────────────────

@app.route("/webhook", methods=["GET"])
def fb_verify():
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("Messenger webhook verified ✓")
        return challenge or "", 200
    return "Forbidden", 403


@app.route("/webhook", methods=["POST"])
def fb_webhook():
    data = request.get_json(silent=True) or {}
    if data.get("object") != "page":
        return "OK", 200
    for entry in data.get("entry", []):
        page_id = entry.get("id")
        for event in entry.get("messaging", []):
            sender_id   = event.get("sender", {}).get("id")
            recipient_id = event.get("recipient", {}).get("id")
            msg = event.get("message", {})

            # ── Detect admin manual reply (echo with no app_id) ──────────────
            if msg.get("is_echo"):
                app_id = msg.get("app_id")
                # app_id is absent/null = admin typed manually in Page inbox
                if not app_id:
                    # recipient_id is the actual user being chatted with
                    user_id = recipient_id
                    if user_id and user_id != page_id:
                        pause_user(user_id)
                        logger.info("Admin replied to %s → bot paused 30 min", user_id)
                continue  # never process echo as incoming message

            if not msg or sender_id == page_id:
                continue

            text = msg.get("text", "").strip()
            if not text:
                continue

            logger.info("Messenger ← %s: %s", sender_id, text)
            log_message("MESSENGER", sender_id, "", "", "", text)
            _notify_admin_messenger(sender_id, text)

            # ── Paused: admin is handling this conversation ───────────────────
            if is_paused(sender_id):
                fb_send_text(sender_id, PAUSED_MSG)
                continue

            threading.Thread(
                target=_messenger_reply, args=(sender_id, text), daemon=True
            ).start()
    return "OK", 200


# ── Telegram webhook ───────────────────────────────────────────────────────────

@app.route("/telegram-webhook", methods=["POST"])
def tg_webhook():
    data = request.get_json(silent=True) or {}
    msg  = data.get("message", {})
    text = (msg.get("text") or "").strip()
    chat_id = (msg.get("chat") or {}).get("id")

    if not text or not chat_id:
        return "OK", 200

    # Extract user info for logging
    user        = msg.get("from", {})
    username    = user.get("username", "")
    first_name  = user.get("first_name", "")
    last_name   = user.get("last_name", "")

    logger.info("Telegram ← %s (@%s): %s", chat_id, username or "—", text)

    if text.startswith("/start"):
        welcome = (
            "မင်္ဂလာပါ! 🎓 University Admission Bot ဖြစ်ပါတယ်။\n\n"
            "✅ GEU နဲ့ other university course info\n"
            "✅ Department, Program, Duration\n"
            "✅ Admission guidance\n\n"
            "မြန်မာဘာသာဖြင့် မေးနိုင်ပါတယ်။ အသေးစိတ်ထပ်မေးချင်ရင် Page Admin ကိုလည်း တိုက်ရိုက် message ပို့နိုင်ပါတယ်။"
        )
        tg_send(chat_id, welcome, with_button=False)
        return "OK", 200

    # ── Admin /reply command — send message back to a Messenger user ──────────
    if text.startswith("/reply") and LOG_CHANNEL_ID and str(chat_id) == str(LOG_CHANNEL_ID):
        parts = text.split(" ", 2)
        if len(parts) < 3:
            tg_send(chat_id, "❌ Usage: /reply {fb_user_id} {message}")
            return "OK", 200
        fb_user_id  = parts[1].strip()
        reply_text  = parts[2].strip()
        fb_send_text(fb_user_id, reply_text)
        pause_user(fb_user_id)
        tg_send(chat_id,
                f"✅ Sent to Messenger user {fb_user_id}\n"
                f"🔇 Bot paused 30 min for this user (human handoff active)")
        logger.info("Admin replied to Messenger user %s via Telegram", fb_user_id)
        return "OK", 200

    log_message("TELEGRAM", str(chat_id), username, first_name, last_name, text)

    threading.Thread(
        target=_telegram_reply, args=(chat_id, text), daemon=True
    ).start()
    return "OK", 200


# ─── App startup ───────────────────────────────────────────────────────────────

# Register Telegram webhook when the app loads (gunicorn --preload runs this once)
register_telegram_webhook()

if __name__ == "__main__":
    logger.info("Messenger: %s", "YES" if PAGE_TOKEN else "NO")
    logger.info("Telegram:  %s", "YES" if TELEGRAM_TOKEN else "NO")
    logger.info("APP_URL:   %s", APP_URL or "(not set)")
    app.run(host="0.0.0.0", port=5000, debug=False)
