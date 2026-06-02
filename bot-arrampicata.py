import re
import os
import random
import string
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

print("START OK")

TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    print("❌ BOT_TOKEN non trovato")
    exit()

GROUP_ID = -1004213527185

pending = {}
events = {}

# STATES
LUOGO, REGIONE, DATA, TIPO, LIVELLO, POSTI = range(6)


# ---------------- REGIONE KEYBOARD ---------------- #

REGIONI_KEYBOARD = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("TrentinoAltoAdige", callback_data="TrentinoAltoAdige"),
        InlineKeyboardButton("Lombardia", callback_data="Lombardia"),
    ],
    [
        InlineKeyboardButton("Veneto", callback_data="Veneto"),
        InlineKeyboardButton("Piemonte", callback_data="Piemonte"),
    ],
    [
        InlineKeyboardButton("Toscana", callback_data="Toscana"),
        InlineKeyboardButton("Lazio", callback_data="Lazio"),
    ],
])


# ---------------- UTILS ---------------- #

def check_date(date_str):
    try:
        d = datetime.strptime(date_str, "%d/%m/%Y")
        return d >= datetime.now()
    except:
        return False


def build_text(e):
    return (
        f"ID: {''.join(random.choices(string.digits, k=5))}\n\n"
        f"🧗 NUOVA USCITA\n\n"
        f"📍 {e['luogo']}\n"
        f"🌍 #{e['regione'].replace(' ', '')}\n"
        f"🧗 #{e['tipo']}\n\n"
        f"📅 {e['data']}\n"
        f"📈 {e['livello']}\n"
        f"👥 {e['posti']} posti\n\n"
        f"👤 Organizzatore: {e['creator_name']}\n\n"
        f"⚠️ Contatta l’organizzatore per partecipare"
    )


def keyboard(event_id):
    e = events[event_id]
    username = e["creator_username"]

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📩 Contatta",
                url=f"https://t.me/{username}" if username != "no_username" else "https://t.me"
            )
        ],
        [
            InlineKeyboardButton("✅ Al completo", callback_data=f"full_{event_id}"),
            InlineKeyboardButton("❌ Annulla", callback_data=f"cancel_{event_id}")
        ]
    ])


# ---------------- START ---------------- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Benvenuto 🧗\nUsa /uscita per creare una nuova uscita."
    )


# ---------------- FLOW ---------------- #

async def uscita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending[update.effective_user.id] = {}
    await update.message.reply_text("📍 Dove vuoi arrampicare?")
    return LUOGO


async def luogo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending[update.effective_user.id]["luogo"] = update.message.text

    await update.message.reply_text(
        "🌍 Seleziona la regione:",
        reply_markup=REGIONI_KEYBOARD
    )
    return REGIONE


async def regione(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    pending[query.from_user.id]["regione"] = query.data

    await query.message.reply_text("📅 Data (GG/MM/AAAA)?")
    return DATA


async def data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not re.match(r"\d{2}/\d{2}/\d{4}", update.message.text):
        await update.message.reply_text("❌ Formato GG/MM/AAAA")
        return DATA

    if not check_date(update.message.text):
        await update.message.reply_text("❌ Data non valida")
        return DATA

    pending[update.effective_user.id]["data"] = update.message.text

    keyboard = [
        [
            InlineKeyboardButton("Falesia", callback_data="Falesia"),
            InlineKeyboardButton("Multipitch", callback_data="Multipitch"),
        ],
        [
            InlineKeyboardButton("Boulder", callback_data="Boulder"),
            InlineKeyboardButton("Indoor", callback_data="Indoor"),
        ],
    ]

    await update.message.reply_text(
        "🧗 Seleziona il tipo:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

    return TIPO


async def tipo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    pending[query.from_user.id]["tipo"] = query.data

    await query.message.reply_text("📈 Livello (es. 6a-6b):")
    return LIVELLO


async def livello(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending[update.effective_user.id]["livello"] = update.message.text
    await update.message.reply_text("👥 Quanti posti?")
    return POSTI


async def posti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = pending[user.id]

    data["posti"] = update.message.text
    data["creator_id"] = user.id
    data["creator_name"] = user.first_name
    data["creator_username"] = user.username if user.username else "no_username"

    event_id = str(len(events) + 1)
    events[event_id] = data

    await context.bot.send_message(
        chat_id=GROUP_ID,
        text=build_text(data),
        reply_markup=keyboard(event_id)
    )

    del pending[user.id]

    await update.message.reply_text("✅ Uscita pubblicata!")
    return ConversationHandler.END


# ---------------- CALLBACK BUTTONS ---------------- #

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    action, event_id = q.data.split("_")
    event = events.get(event_id)

    if not event:
        await q.edit_message_text("❌ Evento non trovato")
        return

    user_id = q.from_user.id

    if action == "cancel":
        if user_id != event["creator_id"]:
            await q.answer("Solo creatore", show_alert=True)
            return

        await q.edit_message_text("🚫 ANNULLATO")
        del events[event_id]

    elif action == "full":
        if user_id != event["creator_id"]:
            await q.answer("Solo creatore", show_alert=True)
            return

        await q.edit_message_text("🔴 AL COMPLETO")


# ---------------- MAIN ---------------- #

def main():
    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("uscita", uscita)],
        states={
            LUOGO: [MessageHandler(filters.TEXT & ~filters.COMMAND, luogo)],
            REGIONE: [CallbackQueryHandler(regione)],
            DATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, data)],
            TIPO: [CallbackQueryHandler(tipo)],
            LIVELLO: [MessageHandler(filters.TEXT & ~filters.COMMAND, livello)],
            POSTI: [MessageHandler(filters.TEXT & ~filters.COMMAND, posti)],
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(buttons))

    print("BOT RUNNING...")
    app.run_polling()


if __name__ == "__main__":
    main()