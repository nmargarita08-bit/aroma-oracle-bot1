import os
import csv
import random
import sqlite3
import threading
from datetime import date
from pathlib import Path

from flask import Flask
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)

# ============== Flask для Render (порт) ==============
app = Flask(__name__)

@app.get("/")
def health():
    return "Bot is running!"

def run_http():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_http, daemon=True).start()
print("HTTP health server started")

# ============== Настройки ==============
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Переменная окружения BOT_TOKEN не задана")

CONSULT_WHATSAPP_URL = os.getenv("CONSULT_WHATSAPP_URL", "https://wa.me/77000000000")
CONSULT_IG_URL = os.getenv("CONSULT_IG_URL", "https://instagram.com/your_profile")

# Имя CSV по умолчанию под твой файл; можно переопределить переменной окружения OILS_CSV_PATH
CSV_PATH = os.getenv("OILS_CSV_PATH", "aroma_oracle_pack.csv")
DB_PATH = os.getenv("DB_PATH", "aroma_bot.db")

# ============== Поиск CSV (надёжный) ==============
def resolve_csv(path_str: str) -> str:
    """
    Возвращает абсолютный путь к CSV.
    Пробует: как указан, рядом с main.py, типовые варианты имён.
    """
    candidates = []
    p = Path(path_str)
    if p.is_file():
        candidates.append(p)

    base = Path(__file__).parent
    candidates += [
        base / path_str,
        base / "aroma_oracle_pack.csv",
        base / "aroma_oracle_pack_100.csv",
    ]

    for c in candidates:
        if c.is_file():
            return str(c.resolve())

    # Отладочная печать, чтобы в логах было видно, что лежит рядом
    try:
        print("CWD:", os.getcwd())
        print("DIR:", os.listdir("."))
        print("BASE:", base, "BASE_DIR:", os.listdir(base))
    except Exception:
        pass
    raise FileNotFoundError(
        f"CSV not found. Set OILS_CSV_PATH to actual filename. Tried: {path_str}"
    )

# ============== Данные (CSV) ==============
# Ожидаемые колонки: name, description, emotions, mantra (русские названия тоже поддерживаются)
OILS = []  # список словарей с полями: id, name, description, emotions, mantra

def load_oils():
    global OILS
    OILS = []
    csv_file = resolve_csv(CSV_PATH)
    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        i = 0
        for row in reader:
            OILS.append({
                "id": i,
                "name": (row.get("name") or row.get("Название") or "").strip(),
                "description": (row.get("description") or row.get("Описание") or "").strip(),
                "emotions": (row.get("emotions") or row.get("Эмоции") or "").strip(),
                "mantra": (row.get("mantra") or row.get("Мантра") or "").strip(),
            })
            i += 1
    if not OILS:
        raise RuntimeError("CSV с маслами пустой или не найден. Проверь файл и колонки.")
    print(f"Loaded oils: {len(OILS)}")

load_oils()

# ============== БД (SQLite) ==============
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS daily_pick (
    user_id INTEGER NOT NULL,
    pick_date TEXT NOT NULL,
    oil_id INTEGER NOT NULL,
    PRIMARY KEY (user_id, pick_date)
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS favorites (
    user_id INTEGER NOT NULL,
    oil_id INTEGER NOT NULL,
    added_at TEXT,
    PRIMARY KEY (user_id, oil_id)
)
""")
conn.commit()

def get_today():
    return date.today().isoformat()

def get_today_pick(user_id: int):
    cur.execute("SELECT oil_id FROM daily_pick WHERE user_id=? AND pick_date=?", (user_id, get_today()))
    row = cur.fetchone()
    return row[0] if row else None

def set_today_pick(user_id: int, oil_id: int):
    cur.execute("INSERT OR REPLACE INTO daily_pick (user_id, pick_date, oil_id) VALUES (?, ?, ?)",
                (user_id, get_today(), oil_id))
    conn.commit()

def add_favorite(user_id: int, oil_id: int):
    cur.execute("INSERT OR IGNORE INTO favorites (user_id, oil_id, added_at) VALUES (?, ?, datetime('now'))",
                (user_id, oil_id))
    conn.commit()

def remove_favorite(user_id: int, oil_id: int):
    cur.execute("DELETE FROM favorites WHERE user_id=? AND oil_id=?", (user_id, oil_id))
    conn.commit()

def list_favorites(user_id: int):
    cur.execute("SELECT oil_id FROM favorites WHERE user_id=? ORDER BY added_at DESC", (user_id,))
    return [row[0] for row in cur.fetchall()]

# ============== Телеграм-бот ==============
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# Главное меню
main_kb = ReplyKeyboardMarkup(resize_keyboard=True)
main_kb.add(KeyboardButton("✨ Масло дня"))
main_kb.add(KeyboardButton("📦 Мой набор"), KeyboardButton("💬 Консультация"))

# ======= Утилиты форматирования =======
def oil_text(o):
    parts = [f"🌿 *{o['name']}*"]
    if o["emotions"]:
        parts.append(f"🌀 *Эмоции:* {o['emotions']}")
    if o["description"]:
        parts.append(f"📖 *Суть:* {o['description']}")
    if o["mantra"]:
        parts.append(f"🔮 *Мантра:* _{o['mantra']}_")
    return "\n".join(parts)

def oil_card_kb(oil_id: int):
    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("➕ В набор", callback_data=f"fav_add:{oil_id}"),
        InlineKeyboardButton("❌ Убрать", callback_data=f"fav_del:{oil_id}")
    )
    return kb

def consult_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("WhatsApp", url=CONSULT_WHATSAPP_URL))
    kb.add(InlineKeyboardButton("Instagram", url=CONSULT_IG_URL))
    return kb

# ======= Команды =======
@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет 🌿 Я твой Aroma-бот.\nНажимай кнопки ниже или команду /help.",
        reply_markup=main_kb
    )

@dp.message_handler(commands=["help"])
async def cmd_help(message: types.Message):
    await message.answer(
        "Доступно:\n"
        "✨ Масло дня — одно масло в сутки\n"
        "📦 Мой набор — понравившиеся масла\n"
        "💬 Консультация — связь со мной\n\n"
        "Команды: /oil, /myset, /consult",
        reply_markup=main_kb
    )

@dp.message_handler(commands=["consult"])
async def cmd_consult(message: types.Message):
    await message.answer("Выбери удобный способ связи:", reply_markup=consult_kb())

@dp.message_handler(commands=["oil"])
async def cmd_oil(message: types.Message):
    await handle_oil_of_day(message)

@dp.message_handler(commands=["myset"])
async def cmd_myset(message: types.Message):
    await handle_myset(message)

# ======= Кнопки меню =======
@dp.message_handler(lambda m: m.text == "✨ Масло дня")
async def btn_oil_of_day(message: types.Message):
    await handle_oil_of_day(message)

@dp.message_handler(lambda m: m.text == "📦 Мой набор")
async def btn_myset(message: types.Message):
    await handle_myset(message)

@dp.message_handler(lambda m: m.text == "💬 Консультация")
async def btn_consult(message: types.Message):
    await cmd_consult(message)

# ======= Бизнес-логика =======
async def handle_oil_of_day(message: types.Message):
    user_id = message.from_user.id
    oil_id = get_today_pick(user_id)
    if oil_id is None:
        oil_id = random.randint(0, len(OILS) - 1)
        set_today_pick(user_id, oil_id)

    o = OILS[oil_id]
    await message.answer(oil_text(o), parse_mode="Markdown", reply_markup=oil_card_kb(oil_id))

async def handle_myset(message: types.Message):
    favs = list_favorites(message.from_user.id)
    if not favs:
        await message.answer("Твой набор пока пуст. Нажми «✨ Масло дня» и добавь понравившееся.")
        return

    text_lines = ["📦 *Твой набор:*"]
    for oid in favs:
        o = OILS[oid]
        text_lines.append(f"• {o['name']}")

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🗑 Очистить набор", callback_data="fav_clear"))
    await message.answer("\n".join(text_lines), parse_mode="Markdown", reply_markup=kb)

# ======= Callback’и =======
@dp.callback_query_handler(lambda c: c.data.startswith("fav_add:"))
async def cb_fav_add(c: types.CallbackQuery):
    oil_id = int(c.data.split(":")[1])
    add_favorite(c.from_user.id, oil_id)
    await c.answer("Добавлено в набор")
    await c.message.edit_reply_markup(reply_markup=oil_card_kb(oil_id))

@dp.callback_query_handler(lambda c: c.data.startswith("fav_del:"))
async def cb_fav_del(c: types.CallbackQuery):
    oil_id = int(c.data.split(":")[1])
    remove_favorite(c.from_user.id, oil_id)
    await c.answer("Убрано из набора")
    await c.message.edit_reply_markup(reply_markup=oil_card_kb(oil_id))

@dp.callback_query_handler(lambda c: c.data == "fav_clear")
async def cb_fav_clear(c: types.CallbackQuery):
    for oid in list_favorites(c.from_user.id):
        remove_favorite(c.from_user.id, oid)
    await c.answer("Набор очищен")
    await c.message.edit_text("Набор очищен. Добавь новые любимчики через «✨ Масло дня».")

# ======= Запуск =======
if __name__ == "__main__":
    print("Telegram bot starting...")
    executor.start_polling(dp, skip_updates=True)