import os
import logging
import asyncio
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from cerebras.cloud.sdk import Cerebras

# ──────────────────────────────────────────────────────────────
# SOZLAMALAR — muhit o'zgaruvchilaridan o'qiladi (Render env vars)
# ──────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "")
CEREBRAS_API_KEY = os.environ.get("CEREBRAS_API_KEY", "")
WEBHOOK_URL      = os.environ.get("WEBHOOK_URL",      "")   # https://your-app.onrender.com
PORT             = int(os.environ.get("PORT", 8080))
# ──────────────────────────────────────────────────────────────

MODEL   = "llama3.1-8b"   # bepul va eng tez model
MAX_CTX = 20               # xotiraga saqlanadigan xabarlar soni

SYSTEM_PROMPT = (
    "Siz aqlli va do'stona AI yordamchisiz. "
    "Foydalanuvchi o'zbek tilida yozsa – o'zbek tilida javob bering, "
    "boshqa tillarda yozsa – shu tilda javob bering. "
    "Javoblaringiz aniq, foydali va qisqa bo'lsin."
)

# ─── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Cerebras client ───────────────────────────────────────────
cerebras_client = Cerebras(api_key=CEREBRAS_API_KEY)

# Har bir foydalanuvchi uchun suhbat tarixi: {user_id: [messages]}
conversation_history: dict[int, list[dict]] = {}


# ─── Yordamchi funksiyalar ─────────────────────────────────────

def get_history(user_id: int) -> list[dict]:
    return conversation_history.setdefault(user_id, [])


def trim_history(history: list[dict]) -> None:
    while len(history) > MAX_CTX:
        history.pop(0)


async def ask_cerebras(user_id: int, user_text: str) -> str:
    history = get_history(user_id)
    history.append({"role": "user", "content": user_text})
    trim_history(history)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history

    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: cerebras_client.chat.completions.create(
                model=MODEL,
                messages=messages,
                max_completion_tokens=1024,
                temperature=0.7,
            ),
        )
        answer = response.choices[0].message.content
        history.append({"role": "assistant", "content": answer})
        trim_history(history)
        return answer
    except Exception as e:
        logger.error(f"Cerebras xatosi: {e}")
        return "⚠️ Xatolik yuz berdi. Iltimos, keyinroq qayta urinib ko'ring."


# ─── Komanda handlerlari ───────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Salom, {user.first_name}!\n\n"
        "Men *Cerebras AI* bilan ishlaydigan aqlli chatbotman 🤖\n\n"
        "Menga istalgan savolingizni yuboring — javob beraman!\n\n"
        "📌 *Komandalar:*\n"
        "/start — Botni qayta ishga tushirish\n"
        "/clear — Suhbat tarixini tozalash\n"
        "/help  — Yordam",
        parse_mode="Markdown",
    )


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    conversation_history.pop(user_id, None)
    await update.message.reply_text(
        "🗑️ Suhbat tarixi tozalandi! Yangi suhbat boshlashingiz mumkin."
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 *Cerebras AI Telegram Bot*\n\n"
        "Bu bot Cerebras bulutidagi LLM modelidan foydalanadi.\n\n"
        "✅ *Imkoniyatlar:*\n"
        "• O'zbek, rus, ingliz va boshqa tillarda suhbat\n"
        "• Suhbat tarixini eslab qolish (oxirgi 20 xabar)\n"
        "• Tez va bepul javoblar\n\n"
        "📌 *Komandalar:*\n"
        "/start — Salomlashish\n"
        "/clear — Tarixni o'chirish\n"
        "/help  — Yordam\n\n"
        "💡 Faqat menga xabar yuboring — javob beraman!",
        parse_mode="Markdown",
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id   = update.effective_user.id
    user_text = update.message.text

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )

    answer = await ask_cerebras(user_id, user_text)

    max_len = 4096
    if len(answer) <= max_len:
        await update.message.reply_text(answer)
    else:
        for i in range(0, len(answer), max_len):
            await update.message.reply_text(answer[i : i + max_len])


# ─── Bot ro'yxati ──────────────────────────────────────────────

async def post_init(application: Application) -> None:
    commands = [
        BotCommand("start", "Botni ishga tushirish"),
        BotCommand("clear", "Suhbat tarixini tozalash"),
        BotCommand("help",  "Yordam"),
    ]
    await application.bot.set_my_commands(commands)


async def main() -> None:
    logger.info("Bot ishga tushmoqda...")

    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    # Render da WEBHOOK_URL bo'lsa — webhook, bo'lmasa — polling
    if WEBHOOK_URL:
        logger.info(f"Webhook rejimi: {WEBHOOK_URL}/webhook")
        async with app:
            await app.start()
            await app.updater.start_webhook(
                listen="0.0.0.0",
                port=PORT,
                url_path="/webhook",
                webhook_url=f"{WEBHOOK_URL}/webhook",
            )
            await asyncio.Event().wait()
    else:
        logger.info("Polling rejimi (lokal ishga tushirish)")
        async with app:
            await app.start()
            await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
            await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
