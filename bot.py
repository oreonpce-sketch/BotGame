import asyncio
import aiohttp
import sqlite3
import time
import random
import os
import logging
from datetime import datetime, timedelta
from typing import Any, Dict

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, TelegramObject, PreCheckoutQuery, LabeledPrice,
    InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
)

logging.basicConfig(level=logging.INFO)

# ⚙️ НАСТРОЙКИ
TOKEN = os.getenv("TOKEN", "9299858779:AAGTG2vjcBYXo0ypX04TEiUu09AqUrMW")
RAWG_KEY = os.getenv("RAWG_KEY", "fe3a305eb58d4cc8a84977c835cc7149")
ADMIN_ID = int(os.getenv("ADMIN_ID", 7977913545))
BOT_LINK = os.getenv("BOT_LINK", "https://t.me/твой_бот")
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/твой_канал")
CHANNEL_ID = os.getenv("CHANNEL_ID", ) # ID канала для проверки (если нужно)
SECRET_PAYLOAD = os.getenv("SECRET_PAYLOAD",)
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", )

bot = Bot(TOKEN)
dp = Dispatcher()

# ==========================================
# 🗄️ БАЗА ДАННЫХ
# ==========================================
def get_db():
    return sqlite3.connect("users.db", timeout=10)

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, joined_at TEXT, is_vip INTEGER DEFAULT 0, vip_until TEXT DEFAULT NULL, daily_searches INTEGER DEFAULT 0, last_search_date TEXT, ref_by INTEGER DEFAULT NULL, ref_count INTEGER DEFAULT 0, bonus_searches INTEGER DEFAULT 0, recs_enabled INTEGER DEFAULT 1, is_helper INTEGER DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS favorites (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, game_name TEXT, game_url TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT, text TEXT, date TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('maintenance_until', '0')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('break_mode', '0')")
    conn.commit()
    conn.close()

init_db()

def get_setting(key):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def set_setting(key, value):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE settings SET value = ? WHERE key = ?", (value, key))
    conn.commit()
    conn.close()

def is_user_vip(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT is_vip, vip_until FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if not row: return False
    if row[0] == 1: return True
    if row[1]:
        try:
            until = datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S")
            if until > datetime.now(): return True
        except: pass
    return False

def is_user_helper(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT is_helper FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row and row[0] == 1

# ==========================================
# 🛡️ БЕЗОПАСНОСТЬ
# ==========================================
class SecurityMiddleware(BaseMiddleware):
    def __init__(self):
        self.users: Dict[int, float] = {}
        self.blocked: Dict[int, float] = {}
        super().__init__()

    async def __call__(self, handler, event: TelegramObject, data: Dict[str, Any]) -> Any:
        user = data.get("event_from_user")
        if not user: return await handler(event, data)
        
        maint_until = int(get_setting("maintenance_until") or 0)
        if maint_until > time.time():
            if user.id == ADMIN_ID:
                if isinstance(event, Message) and event.text and event.text.startswith("/admin"):
                    return await handler(event, data)
                elif isinstance(event, Message): 
                    await event.answer("🛠 <b>На тех. обслуживании.</b> (Админ, доступна только /admin)", parse_mode="HTML")
                    return
            else:
                if isinstance(event, Message): await event.answer("🛠 <b>Бот на тех. обслуживании.</b>\nЗайди позже!", parse_mode="HTML")
                elif isinstance(event, CallbackQuery): await event.answer("🛠 На тех. обслуживании.", show_alert=True)
                return

        break_mode = int(get_setting("break_mode") or 0)
        if break_mode == 1 and user.id != ADMIN_ID:
            if isinstance(event, Message): await event.answer("☕ <b>Перерыв!</b>\nСкоро вернусь.", parse_mode="HTML")
            return

        if user.is_bot or user.id == ADMIN_ID or is_user_helper(user.id): return await handler(event, data)
        now = time.time()
        if user.id in self.blocked and now < self.blocked[user.id]: return 
        if now - self.users.get(user.id, 0) < 0.5:
            self.blocked[user.id] = now + 30
            try:
                if isinstance(event, Message): await event.answer("🚫 Блок на 30 сек за спам.")
            except: pass
            return 
        self.users[user.id] = now
        return await handler(event, data)

dp.message.middleware(SecurityMiddleware())
dp.callback_query.middleware(SecurityMiddleware())

# ==========================================
# 🎮 ЖАНРЫ И КОМАНДЫ
# ==========================================
GENRES = {
    "action": "⚔️ Экшен", "rpg": "🧙 РПГ", "shooter": "🔫 Шутер", "horror": "👻 Хоррор",
    "adventure": "🗺️ Приключения", "strategy": "♟️ Стратегия", "indie": "💎 Инди",
    "puzzle": "🧩 Головоломки", "racing": "🏎️ Гонки", "sports": "⚽ Спорт",
    "simulation": "🌾 Симулятор", "fighting": "🥊 Файтинг", "arcade": "🕹️ Аркада",
    "platformer": "🏃 Платформер", "family": "👨‍👩‍👧 Семейная", "massively-multiplayer": "🌐 MMO"
}

async def set_commands():
    await bot.set_my_commands([
        BotCommand(command="start", description="🏠 Меню"),
        BotCommand(command="find", description="🔍 Поиск"),
        BotCommand(command="top", description="🏆 Топы"),
        BotCommand(command="game", description="🧩 Игра"),
        BotCommand(command="random", description="🎲 Рулетка"),
        BotCommand(command="settings", description="⚙️ Настройки"),
        BotCommand(command="shop", description="🛒 VIP"),
    ])

# ==========================================
# 🚀 СТАРТ
# ==========================================
@dp.message(Command("start"))
async def start(m: Message):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (m.from_user.id,))
    if not cursor.fetchone():
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("INSERT INTO users (user_id, username, first_name, joined_at) VALUES (?, ?, ?, ?)", (m.from_user.id, m.from_user.username, m.from_user.first_name, now))
        conn.commit()
    conn.close()
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📢 Наш канал", url=CHANNEL_LINK)]])
    await m.answer("🎮 <b>Привет!</b>\n➖➖➖➖➖➖➖➖\n🔍 /find — Поиск\n🏆 /top — Топы\n🧩 /game — Викторина\n🎲 /random — Рулетка\n⚙️ /settings — Настройки\n🛒 /shop — VIP", reply_markup=kb, parse_mode="HTML")

# ==========================================
# 🛒 МАГАЗИН И ОПЛАТА
# ==========================================
@dp.message(Command("shop"))
async def shop(m: Message):
    if is_user_vip(m.from_user.id): return await m.answer("⭐ У тебя уже есть VIP!")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Купить за 20 ⭐", callback_data="buy_vip")], [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]])
    await m.answer("🛒 <b>VIP:</b> безлимит, рулетка, избранное.\nЦена: <b>20 ⭐</b>", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "buy_vip")
async def send_invoice(cb: CallbackQuery):
    prices = [LabeledPrice(label="VIP", amount=20)]
    await cb.message.answer_invoice(title="VIP", description="Безлимит", payload=SECRET_PAYLOAD, provider_token="", currency="XTR", prices=prices)
    await cb.answer()

@dp.pre_checkout_query()
async def process_pre_checkout(q: PreCheckoutQuery): await q.answer(ok=True)

@dp.message(F.successful_payment)
async def success_payment(m: Message):
    if m.successful_payment.invoice_payload != SECRET_PAYLOAD: return await m.answer("❌ Ошибка.")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (m.from_user.id,))
    conn.commit()
    conn.close()
    await m.answer("🎉 <b>Оплата прошла! VIP активирован.</b>", parse_mode="HTML")

# ==========================================
# ❤️ ИЗБРАННОЕ
# ==========================================
@dp.callback_query(F.data.startswith("fav:"))
async def add_to_fav(cb: CallbackQuery):
    if not is_user_vip(cb.from_user.id): return await cb.answer("❌ Только для VIP!", show_alert=True)
    name, url = cb.data.split(":")[1].split("|")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO favorites (user_id, game_name, game_url) VALUES (?, ?, ?)", (cb.from_user.id, name, url))
    conn.commit()
    conn.close()
    await cb.answer("❤️ Добавлено!")

@dp.message(Command("favorites"))
async def show_favorites(m: Message):
    if not is_user_vip(m.from_user.id): return await m.answer("❌ Только для VIP.")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT game_name, game_url FROM favorites WHERE user_id = ?", (m.from_user.id,))
    favs = cursor.fetchall()
    conn.close()
    text = "❤️ <b>Избранное:</b>\n" + "\n".join([f"• <a href='{f[1]}'>{f[0]}</a>" for f in favs])
    await m.answer(text if favs else "Пусто.", parse_mode="HTML", disable_web_page_preview=True)

# ==========================================
# 🎲 РУЛЕТКА
# ==========================================
@dp.message(Command("random"))
async def random_game(m: Message):
    conn = get_db()
    cursor = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("SELECT daily_searches, last_search_date FROM users WHERE user_id = ?", (m.from_user.id,))
    searches, last_date = cursor.fetchone()
    if not is_user_vip(m.from_user.id) and last_date == today and searches >= 5:
        await m.answer("❌ Лимит (5 раз).")
        conn.close()
        return
    cursor.execute("UPDATE users SET daily_searches = CASE WHEN last_search_date = ? THEN daily_searches + 1 ELSE 1 END, last_search_date = ? WHERE user_id = ?", (today, today, m.from_user.id))
    conn.commit()
    conn.close()
    await m.answer("🎲 Крутим...")
    params = {"key": RAWG_KEY, "page_size": 10, "page": random.randint(1, 50), "ordering": "-rating", "exclude_adult": "true"}
    async with aiohttp.ClientSession() as s:
        async with s.get("https://api.rawg.io/api/games", params=params) as r:
            data = await r.json()
    games = data.get("results", [])
    if not games: return await m.answer("Ошибка.")
    g = random.choice(games)
    name, year = g.get("name"), (g.get("released") or "?")[:4]
    url, img = f"https://rawg.io/games/{g.get('slug')}", g.get("background_image")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❤️", callback_data=f"fav:{name}|{url}")]]) if is_user_vip(m.from_user.id) else None
    caption = f"🎮 <b>{name}</b> ({year})\n🔗 <a href='{url}'>Ссылка</a>"
    if img: await m.answer_photo(img, caption=caption, reply_markup=kb, parse_mode="HTML")
    else: await m.answer(caption, reply_markup=kb, parse_mode="HTML")

# ==========================================
# 🏆 ТОП И ПОИСК (С ОТМЕНОЙ)
# ==========================================
@dp.message(Command("top"))
async def top(m: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🌎 Общий", callback_data="top:all")], [InlineKeyboardButton(text="🎯 Жанр", callback_data="top:choose_genre")], [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]])
    await m.answer("🏆 <b>Топ:</b>", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "top:choose_genre")
async def top_genre_list(cb: CallbackQuery):
    items = list(GENRES.items())
    rows = [[InlineKeyboardButton(text=items[i][1], callback_data=f"top_genre:{items[i][0]}")] + ([InlineKeyboardButton(text=items[i+1][1], callback_data=f"top_genre:{items[i+1][0]}")] if i + 1 < len(items) else []) for i in range(0, len(items), 2)]
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    await cb.message.edit_text("🏆 <b>Жанр:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")
    await cb.answer()

@dp.callback_query(F.data.startswith("top_genre:"))
async def on_top_genre(cb: CallbackQuery):
    genre = cb.data.split(":")[1]
    await cb.message.edit_text("🏆 Гружу...")
    await cb.answer()
    params = {"key": RAWG_KEY, "page_size": 30, "ordering": "-rating", "exclude_adult": "true"}
    if genre == "horror": params["tags"] = "horror"
    else: params["genres"] = genre
    await send_top_list(cb.message, params, f"🏆 <b>Топ «{GENRES[genre]}»:</b>")

@dp.callback_query(F.data == "top:all")
async def on_top_all(cb: CallbackQuery):
    await cb.message.edit_text("🌎 Гружу...")
    await cb.answer()
    params = {"key": RAWG_KEY, "page_size": 10, "ordering": "-rating", "dates": "2000-01-01,2026-12-31", "exclude_adult": "true"}
    await send_top_list(cb.message, params, "🌎 <b>Топ-10:</b>")

async def send_top_list(message: Message, params: dict, title: str):
    async with aiohttp.ClientSession() as s:
        async with s.get("https://api.rawg.io/api/games", params=params) as r:
            data = await r.json()
    text = f"{title}\n" + "\n".join([f"{i}. <a href='https://rawg.io/games/{g.get('slug')}'>{g.get('name')}</a>" for i, g in enumerate(data.get("results", [])[:10], 1)])
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)

@dp.message(Command("find"))
async def find(m: Message):
    items = list(GENRES.items())
    rows = [[InlineKeyboardButton(text=items[i][1], callback_data=f"genre:{items[i][0]}")] + ([InlineKeyboardButton(text=items[i+1][1], callback_data=f"genre:{items[i+1][0]}")] if i + 1 < len(items) else []) for i in range(0, len(items), 2)]
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    await m.answer("1️⃣ <b>Жанр:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")

@dp.callback_query(F.data.startswith("genre:"))
async def on_genre(cb: CallbackQuery):
    key = cb.data.split(":")[1]
    await cb.message.edit_text(f"Жанр: {GENRES[key]} ✅")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="2010-2015", callback_data=f"year:{key}:2010-2015")], [InlineKeyboardButton(text="2021-2026", callback_data=f"year:{key}:2021-2026")], [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]])
    await cb.message.answer("2️⃣ <b>Годы:</b>", reply_markup=kb, parse_mode="HTML")
    await cb.answer()

@dp.callback_query(F.data.startswith("year:"))
async def on_year(cb: CallbackQuery):
    _, genre, years = cb.data.split(":")
    await cb.message.edit_text("⏳ Ищу...")
    await cb.answer()
    params = {"key": RAWG_KEY, "dates": "2010-01-01,2026-12-31" if years == "2010-2015" else "2021-01-01,2026-12-31", "page_size": 5, "ordering": "-rating", "exclude_adult": "true"}
    if genre == "horror": params["tags"] = "horror"
    else: params["genres"] = genre
    async with aiohttp.ClientSession() as s:
        async with s.get("https://api.rawg.io/api/games", params=params) as r:
            data = await r.json()
    for g in data.get("results", []):
        name, year = g.get("name"), (g.get("released") or "?")[:4]
        url, img = f"https://rawg.io/games/{g.get('slug')}", g.get("background_image")
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❤️", callback_data=f"fav:{name}|{url}")]]) if is_user_vip(cb.from_user.id) else None
        if img: await bot.send_photo(cb.message.chat.id, img, caption=f"🎮 <b>{name}</b> ({year})", reply_markup=kb, parse_mode="HTML")
        else: await bot.send_message(cb.message.chat.id, f"🎮 {name}", reply_markup=kb)

# ==========================================
# 🧩 ИГРА
# ==========================================
active_games = {}
@dp.message(Command("game"))
async def start_game(m: Message):
    params = {"key": RAWG_KEY, "page_size": 10, "page": random.randint(1, 10), "ordering": "-rating", "exclude_adult": "true"}
    async with aiohttp.ClientSession() as s:
        async with s.get("https://api.rawg.io/api/games", params=params) as r:
            data = await r.json()
    games = data.get("results", [])
    if not games: return await m.answer("Ошибка.")
    g = random.choice(games)
    active_games[m.from_user.id] = {"name": g.get("name"), "genre": g.get("genres", [{}])[0].get("name", "?"), "year": (g.get("released") or "?")[:4]}
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💡 Жанр", callback_data="hint:1")], [InlineKeyboardButton(text="💡 Год", callback_data="hint:2")], [InlineKeyboardButton(text="❌ Сдаться", callback_data="cancel")]])
    await m.answer(f"🧩 <b>Угадай игру!</b>\nПиши в чат!", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("hint:"))
async def game_hint(cb: CallbackQuery):
    gd = active_games.get(cb.from_user.id)
    if not gd: return await cb.answer("Начни заново: /game", show_alert=True)
    await cb.answer(f"Жанр: {gd['genre']}" if cb.data == "hint:1" else f"Год: {gd['year']}", show_alert=True)

@dp.callback_query(F.data == "cancel")
async def cancel_action(cb: CallbackQuery):
    await cb.message.edit_text("❌ Действие отменено. Возвращайся в меню /start")
    await cb.answer()

@dp.callback_query(F.data == "give_up")
async def give_up(cb: CallbackQuery):
    gd = active_games.pop(cb.from_user.id, None)
    if gd: await cb.message.edit_text(f"🏳️ Это была: <b>{gd['name']}</b>", parse_mode="HTML")
    await cb.answer()

# ==========================================
# ⚙️ НАСТРОЙКИ И АДМИНКА
# ==========================================
@dp.message(Command("settings"))
async def settings(m: Message):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT recs_enabled FROM users WHERE user_id = ?", (m.from_user.id,))
    status = "Вкл ✅" if cursor.fetchone()[0] else "Выкл ❌"
    conn.close()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"Рекомендации: {status}", callback_data="set_recs")], [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]])
    await m.answer("⚙️ <b>Настройки</b>", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "set_recs")
async def toggle_recs(cb: CallbackQuery):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT recs_enabled FROM users WHERE user_id = ?", (cb.from_user.id,))
    val = 0 if cursor.fetchone()[0] else 1
    cursor.execute("UPDATE users SET recs_enabled = ? WHERE user_id = ?", (val, cb.from_user.id))
    conn.commit()
    conn.close()
    await cb.answer("Ок!")
    await settings(cb.message)

active_feedback = set()
admin_authorized = {}
admin_states = {}

@dp.message(Command("support"))
async def support(m: Message):
    active_feedback.add(m.from_user.id)
    await m.answer("✍️ <b>Напиши отзыв (или /cancel для отмены):</b>", parse_mode="HTML")

@dp.message(Command("admin"))
async def admin_login(m: Message):
    if m.from_user.id != ADMIN_ID: return
    if m.from_user.id in admin_authorized and time.time() - admin_authorized[m.from_user.id] < 900:
        await show_admin_panel(m)
    else:
        await m.answer("🔐 <b>Пароль:</b>", parse_mode="HTML")
        admin_authorized[m.from_user.id] = "waiting"

@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text(m: Message):
    if m.from_user.id == ADMIN_ID and admin_authorized.get(m.from_user.id) == "waiting":
        if m.text == ADMIN_PASSWORD:
            admin_authorized[m.from_user.id] = time.time()
            await m.answer("✅ Верно!")
            await show_admin_panel(m)
        else:
            await m.answer("❌ Неверно. /admin")
            admin_authorized[m.from_user.id] = None
        return

    if m.from_user.id == ADMIN_ID and admin_states.get(ADMIN_ID) == "waiting_helper_id":
        try:
            helper_id = int(m.text)
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET is_helper = 1 WHERE user_id = ?", (helper_id,))
            conn.commit()
            conn.close()
            await m.answer(f"✅ {helper_id} - хэлпер!")
            admin_states[ADMIN_ID] = None
        except: await m.answer("❌ Нужен ID (цифры).")
        return

    if m.from_user.id in active_feedback:
        conn = get_db()
        cursor = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        cursor.execute("INSERT INTO feedback (user_id, username, text, date) VALUES (?, ?, ?, ?)", (m.from_user.id, m.from_user.username, m.text, now))
        conn.commit()
        conn.close()
        active_feedback.remove(m.from_user.id)
        await m.answer("✅ Спасибо!")
        try: await bot.send_message(ADMIN_ID, f"📬 От @{m.from_user.username}:\n{m.text}")
        except: pass

async def show_admin_panel(m: Message):
    maint = int(get_setting("maintenance_until") or 0)
    brk = int(get_setting("break_mode") or 0)
    ms = "Выкл ✅" if maint < time.time() else "Вкл 🛠"
    bs = "Выкл ✅" if brk == 0 else "Вкл ☕"
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    total = cursor.fetchone()[0]
    conn.close()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🛠 ТО: {ms}", callback_data="admin_maint_menu")],
        [InlineKeyboardButton(text=f"☕ Перерыв: {bs}", callback_data="admin_break_menu")],
        [InlineKeyboardButton(text="📬 Отзывы", callback_data="admin_feedback")],
        [InlineKeyboardButton(text="👑 Хэлперы", callback_data="admin_helpers_menu")],
        [InlineKeyboardButton(text="⭐ Выдать VIP", callback_data="admin_give_vip")],
        [InlineKeyboardButton(text="❌ Выйти", callback_data="cancel")]
    ])
    await m.answer(f"📊 <b>АДМИНКА</b>\n👥 Юзеров: {total}", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "admin_maint_menu")
async def admin_maint_menu(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🟢 Выкл", callback_data="maint_0")], [InlineKeyboardButton(text="🔴 1 час", callback_data="maint_1")], [InlineKeyboardButton(text="🔴 1 день", callback_data="maint_24")], [InlineKeyboardButton(text="⬅ Назад", callback_data="admin_back")]])
    await cb.message.edit_text("🛠 <b>Режим ТО:</b>", reply_markup=kb, parse_mode="HTML")
    await cb.answer()

@dp.callback_query(F.data.startswith("maint_"))
async def set_maintenance(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    hours = int(cb.data.split("_")[1])
    if hours == 0: set_setting("maintenance_until", "0")
    else: set_setting("maintenance_until", str(int(time.time()) + (hours * 3600)))
    await cb.answer("Ок!")
    await show_admin_panel(cb.message)

@dp.callback_query(F.data == "admin_break_menu")
async def admin_break_menu(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🟢 Выкл", callback_data="break_0")], [InlineKeyboardButton(text="🟠 Вкл", callback_data="break_1")], [InlineKeyboardButton(text="⬅ Назад", callback_data="admin_back")]])
    await cb.message.edit_text("☕ <b>Перерыв:</b>", reply_markup=kb, parse_mode="HTML")
    await cb.answer()

@dp.callback_query(F.data.startswith("break_"))
async def set_break(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    set_setting("break_mode", cb.data.split("_")[1])
    await cb.answer("Ок!")
    await show_admin_panel(cb.message)

@dp.callback_query(F.data == "admin_give_vip")
async def admin_vip(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (cb.from_user.id,))
    conn.commit()
    conn.close()
    await cb.answer("✅ VIP выдан!", show_alert=True)

@dp.callback_query(F.data == "admin_helpers_menu")
async def admin_helpers_menu(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username FROM users WHERE is_helper = 1")
    helpers = cursor.fetchall()
    conn.close()
    text = "👑 <b>Хэлперы:</b>\n" + "\n".join([f"@{h[1]} - <code>{h[0]}</code>" for h in helpers]) if helpers else "Пусто."
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить", callback_data="admin_add_helper")], [InlineKeyboardButton(text="⬅ Назад", callback_data="admin_back")]])
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()

@dp.callback_query(F.data == "admin_add_helper")
async def admin_add_helper(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    admin_states[cb.from_user.id] = "waiting_helper_id"
    await cb.message.answer("Отправь ID:")
    await cb.answer()

@dp.callback_query(F.data == "admin_back")
async def admin_back(cb: CallbackQuery):
    await show_admin_panel(cb.message)
    await cb.answer()

@dp.callback_query(F.data == "admin_feedback")
async def admin_feedback(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT username, text FROM feedback ORDER BY id DESC LIMIT 5")
    fb = cursor.fetchall()
    conn.close()
    await cb.message.answer("📬 <b>Отзывы:</b>\n" + "\n".join([f"@{f[0]}: {f[1]}" for f in fb]) if fb else "Пусто.", parse_mode="HTML")
    await cb.answer()

@dp.message(Command("helper"))
async def helper_panel(m: Message):
    if not is_user_helper(m.from_user.id) and m.from_user.id != ADMIN_ID: return
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT username, text FROM feedback ORDER BY id DESC LIMIT 5")
    fb = cursor.fetchall()
    conn.close()
    await m.answer("👑 <b>Хэлпер:</b>\n" + "\n".join([f"@{f[0]}: {f[1]}" for f in fb]) if fb else "Нет отзывов.", parse_mode="HTML")

async def main():
    await set_commands()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
