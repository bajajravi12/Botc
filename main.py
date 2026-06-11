import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import json
import io
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 8579552332

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found")

bot = telebot.TeleBot(BOT_TOKEN)

DB_FILE = "thumbs.json"

EXTENSIONS = [
    "dark", "hc", "ehi", "v2", "sip",
    "ssc", "tls", "nm", "hat", "conf", "npvt"
]

waiting_upload = {}

# ---------------- DATABASE ---------------- #

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return json.load(f)
    return {}

def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=2)

thumbs = load_db()

# ---------------- START ---------------- #

@bot.message_handler(commands=['start'])
def start(message):

    if message.from_user.id == ADMIN_ID:

        markup = InlineKeyboardMarkup(row_width=2)

        for ext in EXTENSIONS:
            markup.add(
                InlineKeyboardButton(
                    f"📸 {ext.upper()}",
                    callback_data=f"setthumb_{ext}"
                )
            )

        bot.send_message(
            message.chat.id,
            "Admin Panel\nSelect extension:",
            reply_markup=markup
        )

    else:

        bot.send_message(
            message.chat.id,
            "Send any supported file.\nThumbnail will be added automatically."
        )

# ---------------- ADMIN PANEL ---------------- #

@bot.callback_query_handler(func=lambda c: c.data.startswith("setthumb_"))
def set_thumb(call):

    if call.from_user.id != ADMIN_ID:
        return

    ext = call.data.split("_", 1)[1]

    waiting_upload[call.from_user.id] = ext

    bot.send_message(
        call.message.chat.id,
        f"Send thumbnail image for: {ext}"
    )

# ---------------- SAVE THUMB ---------------- #

@bot.message_handler(content_types=['photo'])
def save_thumbnail(message):

    uid = message.from_user.id

    if uid not in waiting_upload:
        return

    ext = waiting_upload[uid]

    file_id = message.photo[-1].file_id

    thumbs[ext] = file_id
    save_db(thumbs)

    del waiting_upload[uid]

    bot.reply_to(
        message,
        f"✅ Thumbnail saved for .{ext}"
    )

# ---------------- FILE HANDLER ---------------- #

@bot.message_handler(content_types=['document'])
def handle_document(message):

    file_name = message.document.file_name

    if "." not in file_name:
        return

    ext = file_name.split(".")[-1].lower()

    if ext not in thumbs:
        bot.reply_to(
            message,
            f"No thumbnail configured for .{ext}"
        )
        return

    thumb_file_id = thumbs[ext]

    try:

        thumb_info = bot.get_file(thumb_file_id)
        thumb_bytes = bot.download_file(thumb_info.file_path)

        thumb_io = io.BytesIO(thumb_bytes)
        thumb_io.name = "thumb.jpg"

        file_info = bot.get_file(message.document.file_id)
        file_bytes = bot.download_file(file_info.file_path)

        temp_file = f"tmp_{file_name}"

        with open(temp_file, "wb") as f:
            f.write(file_bytes)

        with open(temp_file, "rb") as f:

            bot.send_document(
                message.chat.id,
                document=f,
                thumb=thumb_io
            )

        os.remove(temp_file)

    except Exception as e:

        bot.reply_to(
            message,
            f"Error:\n{e}"
        )

print("Bot Started...")
bot.infinity_polling(skip_pending=True)
