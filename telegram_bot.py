import logging
import os

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import after logging setup
from agent import ask, ADMISSION_LINK

WELCOME_MESSAGE = (
    "မင်္ဂလာပါ! 🎓 ကျွန်တော်က *Graphic Era University (GEU)* Admission Ambassador Bot ဖြစ်ပါတယ်။\n\n"
    "✅ Admission အကြောင်း\n"
    "✅ Tuition & Scholarship\n"
    "✅ Department & Program များ\n"
    "✅ Campus Life\n\n"
    "မည်သည့် မေးခွန်းမဆို မြန်မာဘာသာဖြင့် မေးနိုင်ပါတယ်! 👇"
)
PROCESSING_MESSAGE = "🔍 ရွာဖွေနေပါတယ်... ခဏစောင့်ပါ။"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Apply Now 🎓", url=ADMISSION_LINK)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        WELCOME_MESSAGE,
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question = update.message.text
    logger.info("Question: %s", question)

    await update.message.reply_text(PROCESSING_MESSAGE)

    answer = ask(question)

    # Send main answer with Markdown rendering
    # Telegram supports: *bold*, _italic_, `code`, [text](url)
    keyboard = [[InlineKeyboardButton("Apply Now 🎓", url=ADMISSION_LINK)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await update.message.reply_text(
            answer,
            parse_mode="Markdown",
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
    except Exception:
        # Fallback: send without Markdown if parsing fails
        await update.message.reply_text(answer, reply_markup=reply_markup)


def main():
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_TOKEN not found in .env")

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Telegram bot is running... Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
