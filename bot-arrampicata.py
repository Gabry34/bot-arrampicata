import re
import os
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

# ---------------- GRUPPI ---------------- #

GROUPS = {
    "arrampicata": {
        "id": -1004213527185,         # <-- sostituisci con l'ID reale
        "label": "🧗 Arrampicata",
        "emoji": "🧗",
        "tipi": ["Falesia", "Multipitch", "Boulder", "Indoor", "Ghiaccio"],
        "tipi_emoji": ["🪨", "🏔", "🟤", "🏠", "🧊"],
    },
    "hiking": {
        "id": -1003960275515,         # <-- sostituisci con l'ID reale
        "label": "🥾 Hiking",
        "emoji": "🥾",
        "tipi": ["Escursione", "Trekking", "Alta Via", "Ciaspolata", "Nordic Walking"],
        "tipi_emoji": ["🌲", "⛰", "🗻", "❄️", "🚶"],
    },
    "ferrata": {
        "id": -5186985733,         # <-- sostituisci con l'ID reale
        "label": "🪢 Via Ferrata",
        "emoji": "🪢",
        "tipi": ["Ferrata Facile (F)", "Ferrata Media (MD)", "Ferrata Difficile (D)", "Ferrata Molto Difficile (ED)"],
        "tipi_emoji": ["🟢", "🟡", "🟠", "🔴"],
    },
}

# ---------------- STATI CONVERSAZIONE ---------------- #

(CAPTCHA, GRUPPO, LUOGO, REGIONE, DATA, TIPO, LIVELLO, POSTI) = range(8)

# ---------------- STATO IN MEMORIA ---------------- #

pending  = {}    # user_id -> dati uscita in costruzione + lista msg_ids da cancellare
events   = {}    # event_id -> dati uscita
verified = set() # user_id verificati (anti-bot)

# ---------------- REGIONI ---------------- #

REGIONI = [
    ["Trentino-Alto Adige", "Lombardia"],
    ["Veneto", "Piemonte"],
    ["Toscana", "Lazio"],
    ["Campania", "Sicilia"],
    ["Sardegna", "Liguria"],
    ["Friuli-Venezia Giulia", "Valle d'Aosta"],
    ["Emilia-Romagna", "Calabria"],
]

def regioni_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(r, callback_data=f"reg_{r}") for r in row]
        for row in REGIONI
    ])

# ---------------- TASTIERE DINAMICHE ---------------- #

def gruppo_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(v["label"], callback_data=f"grp_{k}")]
        for k, v in GROUPS.items()
    ])

def tipo_keyboard(gruppo_key):
    g = GROUPS[gruppo_key]
    rows = []
    tipi = g["tipi"]
    emoji = g["tipi_emoji"]
    for i in range(0, len(tipi), 2):
        row = []
        for j in range(2):
            if i + j < len(tipi):
                row.append(InlineKeyboardButton(
                    f"{emoji[i+j]} {tipi[i+j]}",
                    callback_data=f"tip_{tipi[i+j]}"
                ))
        rows.append(row)
    return InlineKeyboardMarkup(rows)

# ---------------- TESTO MESSAGGIO USCITA ---------------- #

def build_text(e):
    partecipanti_list = ""
    for i, p in enumerate(e["partecipanti"], 1):
        nome = p.get("name", "Sconosciuto")
        username = p.get("username")
        partecipanti_list += f"\n  {i}. {nome}" + (f" (@{username})" if username else "")

    posti_liberi = e["posti_totali"] - len(e["partecipanti"])
    stato = "🔴 PIENO" if posti_liberi == 0 else f"🟢 {posti_liberi} posti liberi"
    g = GROUPS[e["gruppo"]]

    return (
        f"{g['emoji']} NUOVA USCITA — {g['label']}\n\n"
        f"📍 {e['luogo']}\n"
        f"🌍 #{e['regione'].replace(' ', '').replace('-', '').replace(chr(39), '')}\n"
        f"{g['emoji']} #{e['tipo'].replace(' ', '')}\n\n"
        f"📅 {e['data']}\n"
        f"📈 Livello: {e['livello']}\n\n"
        f"👥 Partecipanti: {len(e['partecipanti'])}/{e['posti_totali']} — {stato}"
        f"{partecipanti_list}\n\n"
        f"👤 Organizzatore: {e['creator_name']}"
    )

# ---------------- TASTIERA USCITA ---------------- #

def keyboard(event_id, creator_username=None, creator_id=None):
    contact_url = f"https://t.me/{creator_username}" if creator_username else f"tg://user?id={creator_id}"
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

# ---------------- AGGIORNA MESSAGGIO NEL GRUPPO ---------------- #

async def refresh_message(context, event_id):
    e = events[event_id]
    group_id = GROUPS[e["gruppo"]]["id"]
    try:
        await context.bot.edit_message_text(
            chat_id=group_id,
            message_id=e["message_id"],
            text=build_text(e),
            reply_markup=keyboard(event_id, e["creator_username"], e["creator_id"]),
        )
    except Exception:
        pass

# ---------------- PULIZIA MESSAGGI WIZARD ---------------- #

async def cleanup(context, user_id):
    """Cancella tutti i messaggi del wizard dalla chat privata."""
    msg_ids = pending.get(user_id, {}).get("_msgs", [])
    for mid in msg_ids:
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=mid)
        except Exception:
            pass

def track(user_id, msg):
    """Registra un messaggio da cancellare alla fine del wizard."""
    pending.setdefault(user_id, {}).setdefault("_msgs", []).append(msg.message_id)

# ---------------- /start ---------------- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(
        "👋 Benvenuto!\n\n"
        "Usa /uscita per pubblicare una nuova uscita.\n"
        "Usa /mieuscite per gestire le tue uscite.\n\n"
        "Il bot gestisce i gruppi:\n"
        "🧗 Arrampicata · 🥾 Hiking · 🪢 Via Ferrata"
    )

# ---------------- CAPTCHA ANTI-BOT ---------------- #

def generate_captcha():
    a = random.randint(2, 15)
    b = random.randint(2, 15)
    op = random.choice(["+", "-", "*"])
    if op == "+":
        result = a + b
    elif op == "-":
        result = a - b
    else:
        result = a * b
    question = f"{a} {op} {b}"
    return question, result

async def uscita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # Cancella il comando /uscita
    try:
        await update.message.delete()
    except Exception:
        pass

    # Utente già verificato → salta captcha
    if user.id in verified:
        pending[user.id] = {"_msgs": []}
        msg = await context.bot.send_message(
            chat_id=user.id,
            text="🏔 Per quale gruppo vuoi creare un'uscita?",
            reply_markup=gruppo_keyboard(),
        )
        track(user.id, msg)
        return GRUPPO

    # Genera captcha
    question, answer = generate_captcha()
    pending[user.id] = {"_msgs": [], "_captcha": answer}
    msg = await context.bot.send_message(
        chat_id=user.id,
        text=(
            "🤖 Verifica anti-bot\n\n"
            f"Quanto fa: {question} ?\n\n"
            "Rispondi con il numero."
        ),
    )
    track(user.id, msg)
    return CAPTCHA

async def captcha_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    track(user.id, update.message)
    risposta = update.message.text.strip()

    expected = pending.get(user.id, {}).get("_captcha")

    if not risposta.lstrip("-").isdigit() or int(risposta) != expected:
        msg = await update.message.reply_text(
            "❌ Risposta errata. Riprova con /uscita."
        )
        track(user.id, msg)
        await cleanup(context, user.id)
        pending.pop(user.id, None)
        return ConversationHandler.END

    verified.add(user.id)
    pending[user.id].pop("_captcha", None)

    msg = await update.message.reply_text(
        "✅ Verifica superata!\n\n"
        "🏔 Per quale gruppo vuoi creare un'uscita?",
        reply_markup=gruppo_keyboard(),
    )
    track(user.id, msg)
    return GRUPPO

# ---------------- FLOW CREAZIONE ---------------- #

async def gruppo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    track(q.from_user.id, q.message)

    gruppo_key = q.data.removeprefix("grp_")
    pending[q.from_user.id]["gruppo"] = gruppo_key

    msg = await q.message.reply_text("📍 Dove andate? (nome del posto/zona)")
    track(q.from_user.id, msg)
    return LUOGO

async def luogo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    track(user.id, update.message)
    pending[user.id]["luogo"] = update.message.text.strip()

    msg = await update.message.reply_text("🌍 Seleziona la regione:", reply_markup=regioni_keyboard())
    track(user.id, msg)
    return REGIONE

async def regione(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    track(q.from_user.id, q.message)

    pending[q.from_user.id]["regione"] = q.data.removeprefix("reg_")

    msg = await q.message.reply_text("📅 Data dell'uscita (GG/MM/AAAA):")
    track(q.from_user.id, msg)
    return DATA

async def data_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    track(user.id, update.message)
    testo = update.message.text.strip()

    if not re.match(r"^\d{2}/\d{2}/\d{4}$", testo):
        msg = await update.message.reply_text("⚠️ Formato errato. Usa GG/MM/AAAA (es. 15/07/2025):")
        track(user.id, msg)
        return DATA

    pending[user.id]["data"] = testo
    gruppo_key = pending[user.id]["gruppo"]
    g = GROUPS[gruppo_key]

    msg = await update.message.reply_text(
        f"{g['emoji']} Tipo di attività:",
        reply_markup=tipo_keyboard(gruppo_key),
    )
    track(user.id, msg)
    return TIPO

async def tipo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    track(q.from_user.id, q.message)

    pending[q.from_user.id]["tipo"] = q.data.removeprefix("tip_")

    gruppo_key = pending[q.from_user.id]["gruppo"]
    if gruppo_key == "arrampicata":
        hint = "(es. 5c-6b, principianti OK, avanzato, 7a+…)"
    elif gruppo_key == "hiking":
        hint = "(es. facile, medio, impegnativo, EE…)"
    else:
        hint = "(es. F, MD, D, vedi scala difficoltà ferrate)"

    msg = await q.message.reply_text(f"📈 Livello richiesto?\n{hint}")
    track(q.from_user.id, msg)
    return LIVELLO

async def livello(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    track(user.id, update.message)
    pending[user.id]["livello"] = update.message.text.strip()

    msg = await update.message.reply_text("👥 Quanti posti disponibili (incluso te)?")
    track(user.id, msg)
    return POSTI

async def posti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    track(user.id, update.message)
    testo = update.message.text.strip()

    if not testo.isdigit() or int(testo) < 1:
        msg = await update.message.reply_text("⚠️ Inserisci un numero valido maggiore di 0:")
        track(user.id, msg)
        return POSTI

    dati = pending.get(user.id, {})
    dati["posti_totali"]     = int(testo)
    dati["partecipanti"]     = []
    dati["creator_id"]       = user.id
    dati["creator_name"]     = user.first_name
    dati["creator_username"] = user.username or ""

    event_id = str(len(events) + 1)
    group_id = GROUPS[dati["gruppo"]]["id"]

    msg = await context.bot.send_message(
        chat_id=group_id,
        text=build_text(dati),
        reply_markup=keyboard(event_id, dati["creator_username"], dati["creator_id"]),
    )

    dati["message_id"] = msg.message_id
    events[event_id] = dati

    # Cancella tutto il wizard dalla chat privata
    await cleanup(context, user.id)
    pending.pop(user.id, None)

    g = GROUPS[dati["gruppo"]]
    await context.bot.send_message(
        chat_id=user.id,
        text=f"✅ Uscita pubblicata nel gruppo {g['label']}!\nUsa /mieuscite per gestirla.",
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cleanup(context, update.effective_user.id)
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
        g = GROUPS[e["gruppo"]]
        testo = (
            f"{g['emoji']} {g['label']}\n"
            f"📍 {e['luogo']} — {e['data']}\n"
            f"🏷 {e['tipo']} | 📈 {e['livello']}\n"
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

    parts = q.data.split("_", 1)
    if len(parts) != 2:
        return
    action, event_id = parts
    event = events.get(event_id)
    user  = q.from_user

    # --- /mieuscite: conferma cancellazione ---
    if action == "confirmdelete":
        if not event:
            await q.edit_message_text("Uscita non trovata.")
            return
        if user.id != event["creator_id"]:
            await q.answer("Solo il creatore può cancellare.", show_alert=True)
            return
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Sì, cancella", callback_data=f"realdelete_{event_id}"),
            InlineKeyboardButton("↩️ Annulla",     callback_data=f"nodeletemie_{event_id}"),
        ]])
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
        group_id = GROUPS[event["gruppo"]]["id"]
        try:
            await context.bot.delete_message(chat_id=group_id, message_id=event["message_id"])
        except Exception:
            pass
        del events[event_id]
        await q.edit_message_text("🗑 Uscita cancellata.")
        return

    if not event:
        await q.answer("Uscita non trovata.", show_alert=True)
        return

    # --- JOIN ---
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
        if user.id != event["creator_id"]:
            nome = user.first_name + (f" (@{user.username})" if user.username else "")
            try:
                await context.bot.send_message(
                    chat_id=event["creator_id"],
                    text=f"👋 {nome} si è iscritto alla tua uscita a {event['luogo']} ({event['data']}).",
                )
            except Exception:
                pass
        await refresh_message(context, event_id)

    # --- LEAVE ---
    elif action == "leave":
        prima = len(event["partecipanti"])
        event["partecipanti"] = [p for p in event["partecipanti"] if p["id"] != user.id]
        if len(event["partecipanti"]) == prima:
            await q.answer("Non sei iscritto a questa uscita.", show_alert=True)
            return
        if user.id != event["creator_id"]:
            nome = user.first_name + (f" (@{user.username})" if user.username else "")
            try:
                await context.bot.send_message(
                    chat_id=event["creator_id"],
                    text=f"❌ {nome} ha abbandonato la tua uscita a {event['luogo']} ({event['data']}).",
                )
            except Exception:
                pass
        await refresh_message(context, event_id)

    # --- DELETE (dal gruppo) ---
    elif action == "delete":
        if user.id != event["creator_id"]:
            await q.answer("Solo il creatore può cancellare l'uscita.", show_alert=True)
            return
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Sì, cancella", callback_data=f"realdelete_{event_id}"),
            InlineKeyboardButton("↩️ Annulla",     callback_data=f"nodelete_{event_id}"),
        ]])
        await q.message.reply_text(
            f"⚠️ Sei sicuro di voler cancellare l'uscita a {event['luogo']} del {event['data']}?",
            reply_markup=kb,
        )

    elif action == "nodelete":
        await q.message.reply_text("Operazione annullata.")

    # --- GESTISCI PARTECIPANTI ---
    elif action == "manage":
        if user.id != event["creator_id"]:
            await q.answer("Solo il creatore può gestire i partecipanti.", show_alert=True)
            return
        if not event["partecipanti"]:
            await q.answer("Nessun partecipante da rimuovere.", show_alert=True)
            return
        righe = [
            [InlineKeyboardButton(
                f"🚫 Rimuovi {p['name']}" + (f" (@{p['username']})" if p["username"] else ""),
                callback_data=f"kick_{event_id}_{p['id']}"
            )]
            for p in event["partecipanti"]
        ]
        try:
            await context.bot.send_message(
                chat_id=user.id,
                text=f"👥 Partecipanti — {event['luogo']} ({event['data']}):",
                reply_markup=InlineKeyboardMarkup(righe),
            )
            await q.answer("Lista inviata in privato.", show_alert=True)
        except Exception:
            await q.answer(
                "Non riesco a scriverti in privato. Avvia prima una chat con me.",
                show_alert=True,
            )

# ---------------- KICK ---------------- #

async def kick_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    parts = q.data.split("_", 2)
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
            await q.edit_message_text("Partecipante non trovato.")
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
            await q.edit_message_text("Partecipante non trovato.")
            return
        nome = target["name"] + (f" (@{target['username']})" if target["username"] else "")
        event["partecipanti"] = [p for p in event["partecipanti"] if p["id"] != target_id]
        await refresh_message(context, event_id)
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"⚠️ Sei stato rimosso dall'uscita a {event['luogo']} ({event['data']}) dall'organizzatore.",
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
            CAPTCHA: [MessageHandler(filters.TEXT & ~filters.COMMAND, captcha_check)],
            GRUPPO:  [CallbackQueryHandler(gruppo,    pattern=r"^grp_")],
            LUOGO:   [MessageHandler(filters.TEXT & ~filters.COMMAND, luogo)],
            REGIONE: [CallbackQueryHandler(regione,   pattern=r"^reg_")],
            DATA:    [MessageHandler(filters.TEXT & ~filters.COMMAND, data_step)],
            TIPO:    [CallbackQueryHandler(tipo,      pattern=r"^tip_")],
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