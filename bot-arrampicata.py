import re
import os
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

# Stato in memoria: nessun database
pending = {}   # user_id -> dati uscita in costruzione
events = {}    # event_id -> dati uscita

LUOGO, REGIONE, DATA, TIPO, LIVELLO, POSTI = range(6)

# ---------------- TASTIERE ---------------- #

REGIONI_KEYBOARD = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("Trentino-Alto Adige", callback_data="reg_Trentino-Alto Adige"),
        InlineKeyboardButton("Lombardia",           callback_data="reg_Lombardia"),
    ],
    [
        InlineKeyboardButton("Veneto",    callback_data="reg_Veneto"),
        InlineKeyboardButton("Piemonte",  callback_data="reg_Piemonte"),
    ],
    [
        InlineKeyboardButton("Toscana",   callback_data="reg_Toscana"),
        InlineKeyboardButton("Lazio",     callback_data="reg_Lazio"),
    ],
    [
        InlineKeyboardButton("Campania",  callback_data="reg_Campania"),
        InlineKeyboardButton("Sicilia",   callback_data="reg_Sicilia"),
    ],
    [
        InlineKeyboardButton("Sardegna",  callback_data="reg_Sardegna"),
        InlineKeyboardButton("Liguria",   callback_data="reg_Liguria"),
    ],
])

TIPO_KEYBOARD = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("🪨 Falesia",    callback_data="tip_Falesia"),
        InlineKeyboardButton("🏔 Multipitch", callback_data="tip_Multipitch"),
    ],
    [
        InlineKeyboardButton("🟤 Boulder",    callback_data="tip_Boulder"),
        InlineKeyboardButton("🏠 Indoor",     callback_data="tip_Indoor"),
    ],
    [
        InlineKeyboardButton("🧊 Ghiaccio",   callback_data="tip_Ghiaccio"),
        InlineKeyboardButton("🪢 Via Ferrata", callback_data="tip_ViaFerrata"),
    ],
])

# ---------------- TESTO MESSAGGIO ---------------- #

def build_text(e):
    partecipanti_list = ""
    for i, p in enumerate(e["partecipanti"], 1):
        nome = p.get("name", "Sconosciuto")
        username = p.get("username")
        if username:
            partecipanti_list += f"\n  {i}. {nome} (@{username})"
        else:
            partecipanti_list += f"\n  {i}. {nome}"

    posti_liberi = e["posti_totali"] - len(e["partecipanti"])
    stato = "🔴 PIENO" if posti_liberi == 0 else f"🟢 {posti_liberi} posti liberi"

    return (
        f"🧗 NUOVA USCITA\n\n"
        f"📍 {e['luogo']}\n"
        f"🌍 #{e['regione'].replace(' ', '').replace('-', '')}\n"
        f"🧗 #{e['tipo']}\n\n"
        f"📅 {e['data']}\n"
        f"📈 Livello: {e['livello']}\n\n"
        f"👥 Partecipanti: {len(e['partecipanti'])}/{e['posti_totali']} — {stato}"
        f"{partecipanti_list}\n\n"
        f"👤 Organizzatore: {e['creator_name']}"
    )

# ---------------- TASTIERA USCITA ---------------- #

def keyboard(event_id, creator_username=None, creator_id=None):
    # Link diretto all'organizzatore: preferisce username pubblico, altrimenti deep link per ID
    if creator_username:
        contact_url = f"https://t.me/{creator_username}"
    else:
        contact_url = f"tg://user?id={creator_id}"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👋 Partecipa", callback_data=f"join_{event_id}"),
            InlineKeyboardButton("❌ Esci",      callback_data=f"leave_{event_id}"),
        ],
        [
            InlineKeyboardButton("💬 Contatta organizzatore", url=contact_url),
            InlineKeyboardButton("🗑 Cancella uscita",        callback_data=f"delete_{event_id}"),
        ],
        [
            InlineKeyboardButton("👥 Gestisci partecipanti", callback_data=f"manage_{event_id}"),
        ],
    ])

# ---------------- AGGIORNA MESSAGGIO ---------------- #

async def refresh_message(context, event_id):
    e = events[event_id]
    try:
        await context.bot.edit_message_text(
            chat_id=GROUP_ID,
            message_id=e["message_id"],
            text=build_text(e),
            reply_markup=keyboard(event_id, e['creator_username'], e['creator_id']),
        )
    except Exception:
        pass  # messaggio già aggiornato o cancellato

# ---------------- FLOW CREAZIONE USCITA ---------------- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Ciao! Usa /uscita per pubblicare una nuova uscita.\n"
        "Usa /mieuscite per gestire le tue uscite."
    )

async def uscita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending[update.effective_user.id] = {}
    await update.message.reply_text("📍 Dove andate? (nome della falesia/zona)")
    return LUOGO

async def luogo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending[update.effective_user.id]["luogo"] = update.message.text.strip()
    await update.message.reply_text("🌍 Seleziona la regione:", reply_markup=REGIONI_KEYBOARD)
    return REGIONE

async def regione(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pending[q.from_user.id]["regione"] = q.data.removeprefix("reg_")
    await q.message.reply_text("📅 Data dell'uscita (GG/MM/AAAA):")
    return DATA

async def data_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    testo = update.message.text.strip()
    if not re.match(r"^\d{2}/\d{2}/\d{4}$", testo):
        await update.message.reply_text("⚠️ Formato errato. Usa GG/MM/AAAA (es. 15/07/2025):")
        return DATA
    pending[update.effective_user.id]["data"] = testo
    await update.message.reply_text("🧗 Tipo di arrampicata:", reply_markup=TIPO_KEYBOARD)
    return TIPO

async def tipo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pending[q.from_user.id]["tipo"] = q.data.removeprefix("tip_")
    await q.message.reply_text(
        "📈 Livello richiesto?\n"
        "(es. 5c-6b, principianti OK, avanzato, 7a+…)"
    )
    return LIVELLO

async def livello(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending[update.effective_user.id]["livello"] = update.message.text.strip()
    await update.message.reply_text("👥 Quanti posti disponibili (incluso te)?")
    return POSTI

async def posti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    testo = update.message.text.strip()

    if not testo.isdigit() or int(testo) < 1:
        await update.message.reply_text("⚠️ Inserisci un numero valido maggiore di 0:")
        return POSTI

    dati = pending.get(user.id, {})
    dati["posti_totali"] = int(testo)
    dati["partecipanti"] = []
    dati["creator_id"] = user.id
    dati["creator_name"] = user.first_name
    dati["creator_username"] = user.username or ""

    # ID progressivo semplice
    event_id = str(len(events) + 1)

    msg = await context.bot.send_message(
        chat_id=GROUP_ID,
        text=build_text(dati),
        reply_markup=keyboard(event_id, dati['creator_username'], dati['creator_id']),
    )

    dati["message_id"] = msg.message_id
    events[event_id] = dati
    pending.pop(user.id, None)

    await update.message.reply_text(
        f"✅ Uscita pubblicata! ID: #{event_id}\n"
        f"Usa /mieuscite per gestirla."
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending.pop(update.effective_user.id, None)
    await update.message.reply_text("❌ Creazione uscita annullata.")
    return ConversationHandler.END

# ---------------- LE MIE USCITE ---------------- #

async def mie_uscite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    mie = [(eid, e) for eid, e in events.items() if e["creator_id"] == user_id]

    if not mie:
        await update.message.reply_text("Non hai uscite attive.")
        return

    for eid, e in mie:
        testo = (
            f"📍 {e['luogo']} — {e['data']}\n"
            f"🧗 {e['tipo']} | 📈 {e['livello']}\n"
            f"👥 {len(e['partecipanti'])}/{e['posti_totali']} partecipanti"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑 Cancella questa uscita", callback_data=f"confirmdelete_{eid}")]
        ])
        await update.message.reply_text(testo, reply_markup=kb)

# ---------------- CALLBACK BOTTONI ---------------- #

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    data_str = q.data
    user = q.from_user

    # Separazione azione e ID (supporta prefissi multi-parola come confirmdelete)
    parts = data_str.split("_", 1)
    if len(parts) != 2:
        return
    action, event_id = parts
    event = events.get(event_id)

    # Conferma cancellazione (da /mieuscite)
    if action == "confirmdelete":
        if not event:
            await q.edit_message_text("Uscita non trovata.")
            return
        if user.id != event["creator_id"]:
            await q.answer("Solo il creatore può cancellare.", show_alert=True)
            return
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Sì, cancella", callback_data=f"realdelete_{event_id}"),
                InlineKeyboardButton("↩️ Annulla",     callback_data=f"nodeletemie_{event_id}"),
            ]
        ])
        await q.edit_message_text(
            f"Sei sicuro di voler cancellare l'uscita a {event['luogo']} del {event['data']}?",
            reply_markup=kb,
        )
        return

    if action == "nodeletemie":
        await q.edit_message_text("Operazione annullata.")
        return

    if action == "realdelete":
        if not event:
            await q.edit_message_text("Uscita non trovata.")
            return
        if user.id != event["creator_id"]:
            await q.answer("Solo il creatore può cancellare.", show_alert=True)
            return
        try:
            await context.bot.delete_message(chat_id=GROUP_ID, message_id=event["message_id"])
        except Exception:
            pass
        del events[event_id]
        await q.edit_message_text("🗑 Uscita cancellata.")
        return

    # Da qui in poi serve l'evento
    if not event:
        await q.answer("Uscita non trovata.", show_alert=True)
        return

    # JOIN
    if action == "join":
        if any(p["id"] == user.id for p in event["partecipanti"]):
            await q.answer("Sei già iscritto a questa uscita!", show_alert=True)
            return
        if len(event["partecipanti"]) >= event["posti_totali"]:
            await q.answer("Spiacente, non ci sono più posti liberi.", show_alert=True)
            return

        event["partecipanti"].append({
            "id": user.id,
            "name": user.first_name,
            "username": user.username or "",
        })

        # Notifica al creator
        if user.id != event["creator_id"]:
            nome = f"{user.first_name}" + (f" (@{user.username})" if user.username else "")
            try:
                await context.bot.send_message(
                    chat_id=event["creator_id"],
                    text=f"👋 {nome} si è iscritto alla tua uscita a {event['luogo']} ({event['data']}).",
                )
            except Exception:
                pass

        await refresh_message(context, event_id)

    # LEAVE
    elif action == "leave":
        prima = len(event["partecipanti"])
        event["partecipanti"] = [p for p in event["partecipanti"] if p["id"] != user.id]
        if len(event["partecipanti"]) == prima:
            await q.answer("Non sei iscritto a questa uscita.", show_alert=True)
            return

        # Notifica al creator
        if user.id != event["creator_id"]:
            nome = f"{user.first_name}" + (f" (@{user.username})" if user.username else "")
            try:
                await context.bot.send_message(
                    chat_id=event["creator_id"],
                    text=f"❌ {nome} ha abbandonato la tua uscita a {event['luogo']} ({event['data']}).",
                )
            except Exception:
                pass

        await refresh_message(context, event_id)

    # DELETE (dal messaggio nel gruppo, solo creator)
    elif action == "delete":
        if user.id != event["creator_id"]:
            await q.answer("Solo il creatore può cancellare l'uscita.", show_alert=True)
            return
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Sì, cancella", callback_data=f"realdelete_{event_id}"),
                InlineKeyboardButton("↩️ Annulla",     callback_data=f"nodelete_{event_id}"),
            ]
        ])
        await q.message.reply_text(
            f"⚠️ Sei sicuro di voler cancellare l'uscita a {event['luogo']} del {event['data']}?",
            reply_markup=kb,
        )

    elif action == "nodelete":
        await q.message.reply_text("Operazione annullata.")

    # GESTISCI PARTECIPANTI (solo creator, in privato)
    elif action == "manage":
        if user.id != event["creator_id"]:
            await q.answer("Solo il creatore può gestire i partecipanti.", show_alert=True)
            return

        if not event["partecipanti"]:
            await q.answer("Nessun partecipante da rimuovere.", show_alert=True)
            return

        righe = []
        for p in event["partecipanti"]:
            nome = p["name"] + (f" (@{p['username']})" if p["username"] else "")
            righe.append([
                InlineKeyboardButton(
                    f"🚫 Rimuovi {p['name']}",
                    callback_data=f"kick_{event_id}_{p['id']}"
                )
            ])

        kb = InlineKeyboardMarkup(righe)
        try:
            await context.bot.send_message(
                chat_id=user.id,
                text=f"👥 Partecipanti uscita {event['luogo']} ({event['data']}):\nScegli chi rimuovere:",
                reply_markup=kb,
            )
            await q.answer("Ti ho inviato la lista in privato.", show_alert=True)
        except Exception:
            await q.answer(
                "Non riesco a scriverti in privato. Avvia prima una chat con me.",
                show_alert=True
            )

# ---------------- KICK PARTECIPANTE ---------------- #

async def kick_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gestisce kick_{event_id}_{target_id}, confirmkick_{event_id}_{target_id}, cancelkick_{...}"""
    q = update.callback_query
    await q.answer()

    raw = q.data  # es. "kick_3_456789"
    parts = raw.split("_", 2)  # ["kick", "3", "456789"]
    if len(parts) != 3:
        return

    action, event_id, target_id_str = parts
    target_id = int(target_id_str)
    event = events.get(event_id)

    if not event:
        await q.edit_message_text("Uscita non trovata o già cancellata.")
        return

    if q.from_user.id != event["creator_id"]:
        await q.answer("Solo il creatore può rimuovere partecipanti.", show_alert=True)
        return

    target = next((p for p in event["partecipanti"] if p["id"] == target_id), None)

    if action == "kick":
        if not target:
            await q.edit_message_text("Partecipante non trovato (forse si è già tolto).")
            return
        nome = target["name"] + (f" (@{target['username']})" if target["username"] else "")
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Sì, rimuovi", callback_data=f"confirmkick_{event_id}_{target_id}"),
            InlineKeyboardButton("↩️ Annulla",    callback_data=f"cancelkick_{event_id}_{target_id}"),
        ]])
        await q.edit_message_text(
            f"Vuoi rimuovere {nome} dall'uscita a {event['luogo']} ({event['data']})?",
            reply_markup=kb,
        )

    elif action == "confirmkick":
        if not target:
            await q.edit_message_text("Partecipante non trovato (forse si è già tolto).")
            return
        nome = target["name"] + (f" (@{target['username']})" if target["username"] else "")
        event["partecipanti"] = [p for p in event["partecipanti"] if p["id"] != target_id]

        # Aggiorna messaggio nel gruppo
        await refresh_message(context, event_id)

        # Notifica all'utente rimosso
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=(
                    f"⚠️ Sei stato rimosso dall'uscita a {event['luogo']} ({event['data']}) "
                    f"dall'organizzatore."
                ),
            )
        except Exception:
            pass

        await q.edit_message_text(f"✅ {nome} rimosso dall'uscita.")

    elif action == "cancelkick":
        await q.edit_message_text("Operazione annullata.")

# ---------------- MAIN ---------------- #

def main():
    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("uscita", uscita)],
        states={
            LUOGO:   [MessageHandler(filters.TEXT & ~filters.COMMAND, luogo)],
            REGIONE: [CallbackQueryHandler(regione, pattern=r"^reg_")],
            DATA:    [MessageHandler(filters.TEXT & ~filters.COMMAND, data_step)],
            TIPO:    [CallbackQueryHandler(tipo, pattern=r"^tip_")],
            LIVELLO: [MessageHandler(filters.TEXT & ~filters.COMMAND, livello)],
            POSTI:   [MessageHandler(filters.TEXT & ~filters.COMMAND, posti)],
        },
        fallbacks=[CommandHandler("annulla", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("mieuscite", mie_uscite))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(kick_buttons, pattern=r"^(kick|confirmkick|cancelkick)_"))
    app.add_handler(CallbackQueryHandler(buttons))

    print("BOT RUNNING")
    app.run_polling()

if __name__ == "__main__":
    main()