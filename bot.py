import asyncio
import aiohttp
import sqlite3
import time
import random
import os
import logging
from datetime import datetime
from typing import Any, Dict

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, TelegramObject, PreCheckoutQuery, LabeledPrice,
    InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
)

logging.basicConfig(level=logging.INFO)

# ⚙️ НАСТРОЙКИ
TOKEN = os.getenv("9299858779:AAGTG2vjcBYXo0ypXO4TEiUuO9d43AqUrMQ")
RAWG_KEY = os.getenv("fe3a305eb58d4cc8a84977c835cc7149")
ADMIN_ID = int(os.getenv("ADMIN_ID", 7977913545)) # Твой ID
BOT_LINK = os.getenv("BOT_LINK", "https://t.me/finders001_bot")

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
    cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, joined_at TEXT, is_vip INTEGER DEFAULT 0, daily_searches INTEGER DEFAULT 0, last_search_date TEXT, ref_by INTEGER DEFAULT NULL, bonus_searches INTEGER DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS favorites (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, game_name TEXT, game_url TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS search_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, genre TEXT, years TEXT, tag TEXT, searched_at TEXT)")
    conn.commit()
    conn.close()

init_db()

def is_user_vip(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT is_vip FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row and row[0] == 1

def check_limit(user_id):
    if is_user_vip(user_id): return True, 999
    conn = get_db()
    cursor = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("SELECT daily_searches, last_search_date, bonus_searches FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return True, 15

    searches, last_date, bonuses = row
    if last_date != today:
        cursor.execute("UPDATE users SET daily_searches = 0, last_search_date = ? WHERE user_id = ?", (today, user_id))
        conn.commit()
        searches = 0

    total_available = 15 + bonuses - searches
    if total_available <= 0:
        conn.close()
        return False, 0

    cursor.execute("UPDATE users SET daily_searches = daily_searches + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return True, total_available - 1

# ==========================================
# 🛡️ АНТИ-СПАМ
# ==========================================
class AntiFloodMiddleware(BaseMiddleware):
    def __init__(self, limit: float = 1.5):
        self.limit = limit
        self.users: Dict[int, float] = {}
        super().__init__()

    async def __call__(self, handler, event: TelegramObject, data: Dict[str, Any]) -> Any:
        user = data.get("event_from_user")
        if not user or user.is_bot or user.id == ADMIN_ID:
            return await handler(event, data)
        now = time.time()
        if now - self.users.get(user.id, 0) < self.limit:
            return 
        self.users[user.id] = now
        return await handler(event, data)

dp.message.middleware(AntiFloodMiddleware())
dp.callback_query.middleware(AntiFloodMiddleware())

# ==========================================
# 🎮 КОМАНДЫ И СТАРТ
# ==========================================
@dp.message(Command("start"))
async def start(m: Message):
    try:
        ref_by = None
        args = m.text.split()
        if len(args) > 1 and args[1].startswith("ref_"):
            ref_by = int(args[1].split("_")[1])
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (m.from_user.id,))
        if not cursor.fetchone():
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("INSERT INTO users (user_id, username, first_name, joined_at, ref_by) VALUES (?, ?, ?, ?, ?)", (m.from_user.id, m.from_user.username, m.from_user.first_name, now, ref_by))
            conn.commit()
            if ref_by:
                cursor.execute("UPDATE users SET bonus_searches = bonus_searches + 10 WHERE user_id = ?", (ref_by,))
                conn.commit()
                try:
                    asyncio.create_task(bot.send_message(ref_by, "🎁 По твоей ссылке зашел друг! +10 поисков."))
                except: pass
        conn.close()

        await m.answer("🎮 Привет! Я помогу найти игры.\n\n🔍 /find — Поиск\n🏆 /top — Топы\n🛒 /shop — VIP за 20⭐\n🎁 /invite — Друзья")
    except Exception as e:
        logging.error(f"Ошибка в start: {e}")

# ==========================================
# 🎯 УМНОЕ МЕНЮ (Выпадает при вводе /)
# ==========================================
async def set_commands():
    commands = [
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="find", description="🔍 Найти игру"),
        BotCommand(command="top", description="🏆 Топ игр"),
        BotCommand(command="shop", description="🛒 Купить VIP"),
        BotCommand(command="invite", description="🎁 Пригласить друга"),
    ]
    await bot.set_my_commands(commands)

# ==========================================
# 📩 ЕЖЕДНЕВНАЯ РАССЫЛКА (Удержание)
# ==========================================
async def daily_reminder():
    while True:
        # Ждем до 18:00 (или можно поменять на любой час)
        now = datetime.now()
        target_time = now.replace(hour=18, minute=0, second=0, microsecond=0)
        if now >= target_time:
            target_time += asyncio.timedelta(days=1)
            
        wait_seconds = (target_time - now).total_seconds()
        await asyncio.sleep(wait_seconds)

        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users")
            users = cursor.fetchall()
            conn.close()

            for u in users:
                try:
                    await bot.send_message(u[0], "🎮 Хочешь найти ещё? Я тут! Напиши /find или загляни в /top")
                    await asyncio.sleep(0.1) # Пауза, чтобы Telegram не забанил за спам
                except: pass
        except Exception as e:
            logging.error(f"Ошибка рассылки: {e}")

# ==========================================
# 💳 ОПЛАТА И VIP (Цена 20)
# ==========================================
@dp.message(Command("shop"))
async def shop(m: Message):
    if is_user_vip(m.from_user.id):
        await m.answer("⭐ У тебя уже есть VIP! Доступно: безлимит, рулетка и избранное.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Купить VIP за 20 ⭐", callback_data="buy_vip")]])
    await m.answer("🛒 <b>VIP-Магазин</b>\n\n✅ Безлимит поисков (обычные: 15 в день)\n🎲 Рулетка\n❤️ Избранное\n\nЦена: <b>20 Звёзд</b>", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "buy_vip")
async def send_invoice(cb: CallbackQuery):
    prices = [LabeledPrice(label="VIP Доступ", amount=20)]
    await cb.message.answer_invoice(title="VIP Доступ", description="Безлимит, Рулетка, Избранное", payload="vip", provider_token="", currency="XTR", prices=prices)
    await cb.answer()

@dp.pre_checkout_query()
async def process_pre_checkout(q: PreCheckoutQuery):
    await q.answer(ok=True)

@dp.message(F.successful_payment)
async def success_payment(m: Message):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (m.from_user.id,))
    conn.commit()
    conn.close()
    await m.answer("🎉 Оплата прошла! VIP активирован. Попробуй /random")

# ==========================================
# 👑 VIP И ПОИСК ПО ФИЛЬТРАМ
# ==========================================
@dp.message(Command("find"))
async def find(m: Message):
    allowed, left = check_limit(m.from_user.id)
    if not allowed:
        await m.answer("❌ Лимит исчерпан. Купи VIP в /shop или позови друга в /invite!")
        return
    if left < 900: await m.answer(f"🔍 Осталось поисков: {left}")
    await ask_genre(m.chat.id)

async def ask_genre(chat_id: int):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Хоррор", callback_data="genre:horror"), InlineKeyboardButton(text="Экшен", callback_data="genre:action")],
        [InlineKeyboardButton(text="РПГ", callback_data="genre:rpg"), InlineKeyboardButton(text="Шутер", callback_data="genre:shooter")]
    ])
    await bot.send_message(chat_id, "1️⃣ Выбери жанр:", reply_markup=kb)

@dp.callback_query(F.data.startswith("genre:"))
async def on_genre(cb: CallbackQuery):
    key = cb.data.split(":")[1]
    await cb.message.edit_text(f"Жанр: {key} ✅")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="2010-2015", callback_data=f"year:{key}:2010-2015"), InlineKeyboardButton(text="2016-2020", callback_data=f"year:{key}:2016-2020")],
        [InlineKeyboardButton(text="2021-2026", callback_data=f"year:{key}:2021-2026")]
    ])
    await cb.message.answer("2️⃣ Выбери годы:", reply_markup=kb)
    await cb.answer()

@dp.callback_query(F.data.startswith("year:"))
async def on_year(cb: CallbackQuery):
    _, genre, years = cb.data.split(":")
    await cb.message.edit_text(f"Ищу игры в жанре {genre} за {years}... ⏳")
    await cb.answer()
    await search_games(cb.message.chat.id, genre, years)

async def search_games(chat_id: int, genre: str, years: str):
    dates = "2010-01-01,2026-12-31"
    if years == "2010-2015": dates = "2010-01-01,2015-12-31"
    elif years == "2016-2020": dates = "2016-01-01,2020-12-31"
    
    params = {"key": RAWG_KEY, "genres": genre, "dates": dates, "page_size": 5, "ordering": "-rating", "exclude_adult": "true"}
    async with aiohttp.ClientSession() as s:
        async with s.get("https://api.rawg.io/api/games", params=params) as r:
            data = await r.json()
            
    games = data.get("results", [])
    if not games:
        await bot.send_message(chat_id, "😕 Ничего не нашлось.")
        return
        
    for g in games:
        name, year = g.get("name"), (g.get("released") or "?")[:4]
        url, img = f"https://rawg.io/games/{g.get('slug')}", g.get("background_image")
        caption = f"🎮 <b>{name}</b> ({year})\n🔗 <a href='{url}'>Страница игры</a>"
        if img: await bot.send_photo(chat_id, img, caption=caption, parse_mode="HTML")
        else: await bot.send_message(chat_id, caption, parse_mode="HTML")

# ==========================================
# 🏆 ТОП ИГР
# ==========================================
@dp.message(Command("top"))
async def top(m: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌎 Общий Топ-10", callback_data="top:all")],
        [InlineKeyboardButton(text="🎯 Топ по жанру", callback_data="top:choose_genre")]
    ])
    await m.answer("🏆 Какой Топ показать?", reply_markup=kb)

@dp.callback_query(F.data == "top:choose_genre")
async def top_genre_list(cb: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Хоррор", callback_data="top_genre:horror"), InlineKeyboardButton(text="Экшен", callback_data="top_genre:action")],
        [InlineKeyboardButton(text="РПГ", callback_data="top_genre:rpg"), InlineKeyboardButton(text="Шутер", callback_data="top_genre:shooter")]
    ])
    await cb.message.edit_text("Выбери жанр:", reply_markup=kb)
    await cb.answer()

@dp.callback_query(F.data.startswith("top_genre:"))
async def on_top_genre(cb: CallbackQuery):
    genre = cb.data.split(":")[1]
    await cb.message.edit_text("🏆 Загружаю...")
    await cb.answer()
    params = {"key": RAWG_KEY, "genres": genre, "page_size": 30, "ordering": "-rating", "exclude_adult": "true"}
    await send_top_list(cb.message, params, f"🏆 <b>Топ-10 в жанре «{genre}»:</b>")

@dp.callback_query(F.data == "top:all")
async def on_top_all(cb: CallbackQuery):
    await cb.message.edit_text("🌎 Загружаю...")
    await cb.answer()
    params = {"key": RAWG_KEY, "page_size": 10, "ordering": "-rating", "dates": "2000-01-01,2026-12-31", "exclude_adult": "true"}
    await send_top_list(cb.message, params, "🌎 <b>Общий Топ-10:</b>")

async def send_top_list(message: Message, params: dict, title: str):
    async with aiohttp.ClientSession() as s:
        async with s.get("https://api.rawg.io/api/games", params=params) as r:
            data = await r.json()
    games = data.get("results", [])
    if not games: return await message.answer("😕 Ничего не нашлось.")
    
    bad_words = ["hentai", "sex", "adult", "erotic", "nsfw", "porn"]
    good_games = []
    for g in games:
        if any(w in g.get("name", "").lower() for w in bad_words): continue
        if g.get("background_image"): good_games.append(g)
        if len(good_games) == 10: break
            
    text = f"{title}\n\n"
    for i, g in enumerate(good_games, 1):
        text += f"{i}. <a href='https://rawg.io/games/{g.get('slug')}'>{g.get('name')}</a> ({(g.get('released') or '?')[:4]})\n"
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)

# ==========================================
# ⚙️ УЛЬТИМАТИВНАЯ АДМИН-ПАНЕЛЬ
# ==========================================
@dp.message(Command("admin"))
async def admin(m: Message):
    if m.from_user.id != ADMIN_ID: return
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_vip = 1")
    vips = cursor.fetchone()[0]
    conn.close()
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Выдать себе VIP", callback_data="admin_give_vip")],
        [InlineKeyboardButton(text="📢 Сделать рассылку", callback_data="admin_broadcast")]
    ])
    await m.answer(f"📊 <b>АДМИН-ПАНЕЛЬ</b>\n\n👥 Юзеров: <b>{total}</b>\n⭐ VIP: <b>{vips}</b>", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "admin_give_vip")
async def admin_vip(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (cb.from_user.id,))
    conn.commit()
    conn.close()
    await cb.answer("✅ Тебе выдан VIP!", show_alert=True)

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    await cb.message.answer("Напиши текст для рассылки (или напиши 'отмена'):")
    await cb.answer()

@dp.message(F.text & ~F.text.startswith("/"))
async def handle_broadcast(m: Message):
    if m.from_user.id != ADMIN_ID or m.text == "отмена": return
    
    # Простая проверка, что админ хочет сделать рассылку (можно усложнить, но пока так)
    if "привет" in m.text.lower() or len(m.text) > 5:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        users = cursor.fetchall()
        conn.close()
        
        await m.answer(f"🚀 Рассылаю {len(users)} пользователям...")
        count = 0
        for u in users:
            try:
                await bot.send_message(u[0], m.text)
                count += 1
                await asyncio.sleep(0.05)
            except: pass
        await m.answer(f"✅ Отправлено: {count} чел.")

# ==========================================
# 🚀 ЗАПУСК
# ==========================================
async def main():
    logging.info("Бот запускается...")
    await set_commands() # Включаем умное меню
    asyncio.create_task(daily_reminder()) # Запускаем фоновую рассылку
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
