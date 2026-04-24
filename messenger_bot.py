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

PROCESSING_MESSAGE = "ရွာဖွေနေပါတယ်... ခဏစောင့်ပါ။"
GENERIC_ERROR_MESSAGE = "တောင်းပန်ပါတယ်။ အမှားတစ်ခု ဖြစ်ပွားသွားပါတယ်။ နောက်မှ ထပ်စမ်းကြည့်ပါ။"


def clean_for_messenger(text: str) -> str:
    """
    Strip Markdown formatting that Messenger renders as raw characters,
    and remove any inline CTA link block (we'll send it as a button instead).
    """
    # Remove bold/italic markers
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    # Remove markdown horizontal rules
    text = re.sub(r"\n---+\n?", "\n", text)
    # Remove the CTA block that contains the admission link
    # (we will send it as a separate button message)
    text = re.sub(
        r"🚀.*?" + re.escape(ADMISSION_LINK) + r"\s*",
        "",
        text,
        flags=re.DOTALL,
    )
    # Remove any remaining bare admission link
    text = text.replace(ADMISSION_LINK, "").strip()
    return text.strip()


def send_text(recipient_id: str, text: str) -> None:
    """Send a plain-text message (max 2000 chars per Messenger limit)."""
    if not PAGE_TOKEN:
        logger.error("META_PAGE_TOKEN is not configured.")
        return

    # Messenger hard limit is 2000 chars per message
    MAX = 2000
    chunks = [text[i:i + MAX] for i in range(0, len(text), MAX)]
    for chunk in chunks:
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": chunk},
            "messaging_type": "RESPONSE",
        }
        _post_message(payload)


def send_cta_button(recipient_id: str) -> None:
    """Send a Messenger Button Template with a clickable Apply Now button."""
    if not PAGE_TOKEN:
        return

    payload = {
        "recipient": {"id": recipient_id},
        "messaging_type": "RESPONSE",
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "button",
                    "text": "🎓 GEU မှာ သင့်အနာဂတ်ကို စတင်ပါ!\nScholarship နဲ့ India မှာ တက္ကသိုလ်ပညာသင်ကြားဖို့ ဒီနေ့ပဲ Admission Form ဖြည့်လိုက်ပါ။",
                    "buttons": [
                        {
                            "type": "web_url",
                            "url": ADMISSION_LINK,
                            "title": "Apply Now 🎓",
                        }
                    ],
                },
            }
        },
    }
    _post_message(payload)


def _post_message(payload: dict) -> None:
    params = {"access_token": PAGE_TOKEN}
    try:
        response = requests.post(
            "https://graph.facebook.com/v19.0/me/messages",
            json=payload,
            params=params,
            timeout=20,
        )
        logger.info("Send message status: %s | %s", response.status_code, response.text)
    except requests.RequestException:
        logger.exception("Failed to send message to Messenger")


def process_and_reply(sender_id: str, question: str) -> None:
    try:
        send_text(sender_id, PROCESSING_MESSAGE)
        raw_answer = ask(question)

        # Clean Markdown and remove inline CTA (we send button separately)
        clean_answer = clean_for_messenger(raw_answer)
        send_text(sender_id, clean_answer)

        # Send a proper clickable button for the CTA
        send_cta_button(sender_id)

    except Exception:
        logger.exception("Error processing reply")
        send_text(sender_id, GENERIC_ERROR_MESSAGE)


@app.route("/", methods=["GET"])
def index():
    return jsonify(
        {
            "status": "ok",
            "service": "University Messenger bot",
            "message": "Use /health for a health check and /webhook for Meta webhook verification/events.",
            "endpoints": {
                "/": "This status page",
                "/health": "Application health check",
                "/webhook": "Messenger webhook endpoint",
            },
        }
    ), 200


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
    logger.info("Incoming POST: %s", data)

    if data.get("object") != "page":
        logger.warning("Unexpected object type: %s", data.get("object"))
        return "OK", 200

    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):
            sender_id = event.get("sender", {}).get("id")

            # Ignore messages sent by the page itself.
            page_id = entry.get("id")
            if sender_id == page_id:
                logger.info("Ignoring echo from page itself")
                continue

            if "message" not in event:
                continue

            msg = event["message"]
            if msg.get("is_echo"):
                logger.info("Skipping echo message")
                continue

            text = msg.get("text", "").strip()
            if not text:
                continue

            logger.info("Received from %s: %s", sender_id, text)
            thread = threading.Thread(
                target=process_and_reply,
                args=(sender_id, text),
                daemon=True,
            )
            thread.start()

    return "OK", 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify(
        {
            "status": "ok",
            "page_token_configured": bool(PAGE_TOKEN),
            "verify_token_configured": bool(VERIFY_TOKEN),
        }
    ), 200


if __name__ == "__main__":
    if not PAGE_TOKEN:
        logger.error("META_PAGE_TOKEN not found in .env!")
    if not VERIFY_TOKEN:
        logger.error("META_VERIFY_TOKEN not found in .env!")

    logger.info("PAGE_TOKEN set: %s", "YES" if PAGE_TOKEN else "NO")
    logger.info("VERIFY_TOKEN set: %s", "YES" if VERIFY_TOKEN else "NO")
    print("Messenger bot running on 0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
