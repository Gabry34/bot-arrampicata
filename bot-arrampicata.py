import re
import os
import string
import random

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

print("BOT START")

TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    print("NO TOKEN")
    exit()

GROUP_ID = -1004213527185

pending = {}
events = {}

LUOGO, REGIONE, DATA, TIPO, LIVELLO, POSTI = range(6)

# ---------------- REGIONI ---------------- #

REGIONI_KEYBOARD = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("Trentino-Alto Adige", callback_data="Trentino-Alto Adige"),
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

# ---------------- TEXT ---------------- #

def build_text(e):
    return (
        f"🧗 NUOVA USCITA\n\n"
        f"📍 {e['luogo']}\n"
        f"🌍 #{e['regione'].replace(' ', '')}\n"
        f"🧗 #{e['tipo']}\n\n"
        f"📅 {e['data']}\n"
        f"📈 {e['livello']}\n\n"
        f"👥 {len(e['partecipanti'])}/{e['posti_totali']} partecipanti\n\n"
        f"👤 {e['creator_name']}\n\n"
        f"⚠️ Clicca per partecipare"
    )

# ---------------- KEYBOARD ---------------- #

def keyboard(event_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👋 Partecipa", callback_data=f"join_{event_id}"),
            InlineKeyboardButton("❌ Esci", callback_data=f"leave_{event_id}")
        ],
        [
            InlineKeyboardButton("✏️ Aggiorna posti", callback_data=f"update_{event_id}")
        ]
    ])

# ---------------- FLOW ---------------- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Usa /uscita")

async def uscita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending[update.effective_user.id] = {}
    await update.message.reply_text("📍 Dove vai?")
    return LUOGO

async def luogo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending[update.effective_user.id]["luogo"] = update.message.text

    await update.message.reply_text(
        "🌍 Regione:",
        reply_markup=REGIONI_KEYBOARD
    )
    return REGIONE

async def regione(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    pending[q.from_user.id]["regione"] = q.data

    await q.message.reply_text("📅 Data (GG/MM/AAAA)?")
    return DATA

async def data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not re.match(r"\d{2}/\d{2}/\d{4}", update.message.text):
        await update.message.reply_text("Formato errato")
        return DATA

    pending[update.effective_user.id]["data"] = update.message.text

    kb = [
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
        "🧗 Tipo:",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return TIPO

async def tipo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    pending[q.from_user.id]["tipo"] = q.data

    await q.message.reply_text("📈 Livello?")
    return LIVELLO

async def livello(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending[update.effective_user.id]["livello"] = update.message.text
    await update.message.reply_text("👥 Posti?")
    return POSTI

async def posti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = pending[user.id]

    data["posti_totali"] = int(data["posti"])
    data["partecipanti"] = []

    data["creator_id"] = user.id
    data["creator_name"] = user.first_name
    data["creator_username"] = user.username or "no_username"

    event_id = str(len(events) + 1)

    msg = await context.bot.send_message(
        chat_id=GROUP_ID,
        text=build_text(data),
        reply_markup=keyboard(event_id)
    )

    data["message_id"] = msg.message_id
    events[event_id] = data

    del pending[user.id]

    await update.message.reply_text("✅ Pubblicato")
    return ConversationHandler.END

# ---------------- UPDATE SYSTEM ---------------- #

async def update_event(context, query, event_id):
    e = events[event_id]

    await context.bot.edit_message_text(
        chat_id=GROUP_ID,
        message_id=e["message_id"],
        text=build_text(e),
        reply_markup=keyboard(event_id)
    )

# ---------------- CALLBACK ---------------- #

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    action, event_id = q.data.split("_")
    event = events.get(event_id)

    if not event:
        return

    user_id = q.from_user.id

    # JOIN
    if action == "join":
        if user_id in event["partecipanti"]:
            await q.answer("Sei già dentro", show_alert=True)
            return

        if len(event["partecipanti"]) >= event["posti_totali"]:
            await q.answer("Evento pieno", show_alert=True)
            return

        event["partecipanti"].append(user_id)

    # LEAVE
    elif action == "leave":
        if user_id in event["partecipanti"]:
            event["partecipanti"].remove(user_id)

    # UPDATE POSTI
    elif action == "update":
        if user_id != event["creator_id"]:
            await q.answer("Solo creator", show_alert=True)
            return

        context.user_data["update_event"] = event_id
        await q.message.reply_text("✏️ Nuovo numero posti:")
        return

    await update_event(context, q, event_id)

# ---------------- UPDATE POSTI ---------------- #

async def update_posti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    event_id = context.user_data.get("update_event")
    if not event_id:
        return

    if not update.message.text.isdigit():
        await update.message.reply_text("Numero non valido")
        return

    event = events[event_id]
    event["posti_totali"] = int(update.message.text)

    await context.bot.edit_message_text(
        chat_id=GROUP_ID,
        message_id=event["message_id"],
        text=build_text(event),
        reply_markup=keyboard(event_id)
    )

    context.user_data.pop("update_event")

    await update.message.reply_text("✅ Aggiornato")

# ---------------- MAIN ---------------- #

def main():
    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("uscita", uscita)],
        states={
            LUOGO: [MessageHandler(filters.TEXT, luogo)],
            REGIONE: [CallbackQueryHandler(regione)],
            DATA: [MessageHandler(filters.TEXT, data)],
            TIPO: [CallbackQueryHandler(tipo)],
            LIVELLO: [MessageHandler(filters.TEXT, livello)],
            POSTI: [MessageHandler(filters.TEXT, posti)],
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, update_posti))

    print("BOT RUNNING")
    app.run_polling()

if __name__ == "__main__":
    main()