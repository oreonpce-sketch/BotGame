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
    Message,
    CallbackQuery,
    TelegramObject,
    PreCheckoutQuery,
    LabeledPrice,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand,
)

logging.basicConfig(level=logging.INFO)

# ⚙️ НАСТРОЙКИ
TOKEN = os.getenv("TOKEN", "9299858779:AAGTG2vjcBYXo0ypXO4TEiUuO9d43AqUrMQ")
RAWG_KEY = os.getenv("RAWG_KEY", "fe3a305eb58d4cc8a84977c835cc7149")
ADMIN_ID = int(os.getenv("ADMIN_ID", 7977913545))
BOT_LINK = os.getenv("BOT_LINK", "https://t.me/finders001_bot")
SECRET_PAYLOAD = os.getenv("SECRET_PAYLOAD", "BER22PLL100RTk$$Errrtt")

bot = Bot(TOKEN)
dp = Dispatcher()


# ==========================================
# 🗄️ БАЗА ДАННЫХ (ЗАЩИЩЕННАЯ)
# ==========================================
def get_db():
    return sqlite3.connect("users.db", timeout=10)


def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, joined_at TEXT, is_vip INTEGER DEFAULT 0, vip_until TEXT DEFAULT NULL, daily_searches INTEGER DEFAULT 0, last_search_date TEXT, ref_by INTEGER DEFAULT NULL, ref_count INTEGER DEFAULT 0, bonus_searches INTEGER DEFAULT 0, lang TEXT DEFAULT 'ru', recs_enabled INTEGER DEFAULT 1)"
    )
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS favorites (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, game_name TEXT, game_url TEXT)"
    )
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS search_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, genre TEXT, searched_at TEXT)"
    )
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT, text TEXT, date TEXT)"
    )
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)"
    )
    cursor.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('maintenance_until', '0')"
    )
    cursor.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('break_mode', '0')"
    )
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
    if not row:
        return False
    if row[0] == 1:
        return True
    if row[1]:
        try:
            until = datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S")
            if until > datetime.now():
                return True
        except:
            pass
    return False


# ==========================================
# 🛡️ БЕЗОПАСНОСТЬ И ПЕРЕРЫВЫ
# ==========================================
class SecurityMiddleware(BaseMiddleware):
    def __init__(self):
        self.users: Dict[int, float] = {}
        self.blocked: Dict[int, float] = {}
        super().__init__()

    async def __call__(
        self, handler, event: TelegramObject, data: Dict[str, Any]
    ) -> Any:
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        # 1. Тех. обслуживание
        maint_until = int(get_setting("maintenance_until") or 0)
        if maint_until > time.time() and user.id != ADMIN_ID:
            if isinstance(event, Message):
                await event.answer(
                    "🛠 <b>Бот на тех. обслуживании.</b>\nЗайди позже!",
                    parse_mode="HTML",
                )
            elif isinstance(event, CallbackQuery):
                await event.answer("🛠 На тех. обслуживании.", show_alert=True)
            return

        # 2. Обычный перерыв
        break_mode = int(get_setting("break_mode") or 0)
        if break_mode == 1 and user.id != ADMIN_ID:
            if isinstance(event, Message):
                await event.answer(
                    "☕ <b>Я ушел на перерыв!</b>\nСкоро вернусь.", parse_mode="HTML"
                )
            return

        # 3. Анти-спам
        if user.is_bot or user.id == ADMIN_ID:
            return await handler(event, data)
        now = time.time()
        if user.id in self.blocked and now < self.blocked[user.id]:
            return
        if now - self.users.get(user.id, 0) < 0.5:
            self.blocked[user.id] = now + 30
            try:
                if isinstance(event, Message):
                    await event.answer("🚫 Ты заблокирован на 30 секунд за спам.")
            except:
                pass
            return
        self.users[user.id] = now
        return await handler(event, data)


dp.message.middleware(SecurityMiddleware())
dp.callback_query.middleware(SecurityMiddleware())

# ==========================================
# 🎮 ЖАНРЫ
# ==========================================
GENRES = {
    "action": "Экшен",
    "rpg": "РПГ",
    "shooter": "Шутер",
    "horror": "Хоррор",
    "adventure": "Приключения",
    "strategy": "Стратегия",
    "indie": "Инди",
    "puzzle": "Головоломки",
    "racing": "Гонки",
    "sports": "Спорт",
    "simulation": "Симулятор",
    "fighting": "Файтинг",
    "arcade": "Аркада",
    "platformer": "Платформер",
    "family": "Семейная",
    "massively-multiplayer": "MMO",
}


async def set_commands():
    commands = [
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="find", description="🔍 Найти игру"),
        BotCommand(command="top", description="🏆 Топ игр"),
        BotCommand(command="game", description="🧩 Угадай игру"),
        BotCommand(command="random", description="🎲 Рулетка"),
        BotCommand(command="settings", description="⚙️ Настройки"),
        BotCommand(command="shop", description="🛒 VIP"),
        BotCommand(command="support", description="💬 Поддержка"),
    ]
    await bot.set_my_commands(commands)


# ==========================================
# 🚀 СТАРТ И РЕКОМЕНДАЦИИ
# ==========================================
@dp.message(Command("start"))
async def start(m: Message):
    ref_by = None
    args = m.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            ref_by = int(args[1].split("_")[1])
        except:
            pass

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT user_id, recs_enabled FROM users WHERE user_id = ?", (m.from_user.id,)
    )
    user = cursor.fetchone()

    if not user:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "INSERT INTO users (user_id, username, first_name, joined_at, ref_by) VALUES (?, ?, ?, ?, ?)",
            (m.from_user.id, m.from_user.username, m.from_user.first_name, now, ref_by),
        )
        conn.commit()
        if ref_by:
            cursor.execute(
                "UPDATE users SET ref_count = ref_count + 1 WHERE user_id = ?",
                (ref_by,),
            )
            cursor.execute("SELECT ref_count FROM users WHERE user_id = ?", (ref_by,))
            ref_count = cursor.fetchone()[0]
            if ref_count % 3 == 0:
                vip_until = (datetime.now() + timedelta(days=3)).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                cursor.execute(
                    "UPDATE users SET vip_until = ? WHERE user_id = ?",
                    (vip_until, ref_by),
                )
                try:
                    asyncio.create_task(
                        bot.send_message(
                            ref_by, "🎁 Ты пригласил 3 друзей! Тебе выдан VIP на 3 дня!"
                        )
                    )
                except:
                    pass
            else:
                try:
                    asyncio.create_task(
                        bot.send_message(
                            ref_by, "🎁 По твоей ссылке зашел друг! +10 поисков."
                        )
                    )
                except:
                    pass
            conn.commit()
    conn.close()
    await m.answer(
        "🎮 <b>Привет!</b> Я помогу найти игры.\n➖➖➖➖➖\n🔍 /find — Поиск\n🏆 /top — Топы\n🧩 /game — Викторина\n🎲 /random — Рулетка\n⚙️ /settings — Настройки\n🛒 /shop — VIP\n➖➖➖➖➖",
        parse_mode="HTML",
    )

    # Умная рекомендация
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT recs_enabled FROM users WHERE user_id = ?", (m.from_user.id,)
    )
    if cursor.fetchone()[0] == 1:
        cursor.execute(
            "SELECT genre FROM search_logs WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (m.from_user.id,),
        )
        last_search = cursor.fetchone()
        if last_search:
            genre = last_search[0]
            await m.answer(
                f"👋 С возвращением! В прошлый раз ты искал {GENRES.get(genre, genre)}. Вот игра для тебя:"
            )
            await send_random_by_genre(m.chat.id, genre)
    conn.close()


# ==========================================
# ⚙️ НАСТРОЙКИ
# ==========================================
@dp.message(Command("settings"))
async def settings(m: Message):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT recs_enabled, lang FROM users WHERE user_id = ?", (m.from_user.id,)
    )
    row = cursor.fetchone()
    conn.close()
    status = "Вкл ✅" if row[0] else "Выкл ❌"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"Рекомендации: {status}", callback_data="set_recs"
                )
            ]
        ]
    )
    await m.answer(
        "⚙️ <b>Настройки</b>\n➖➖➖➖➖\nЗдесь ты можешь отключить умные рекомендации.",
        reply_markup=kb,
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "set_recs")
async def toggle_recs(cb: CallbackQuery):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT recs_enabled FROM users WHERE user_id = ?", (cb.from_user.id,)
    )
    val = 0 if cursor.fetchone()[0] else 1
    cursor.execute(
        "UPDATE users SET recs_enabled = ? WHERE user_id = ?", (val, cb.from_user.id)
    )
    conn.commit()
    conn.close()
    await cb.answer("Сохранено!")
    await settings(cb.message)


# ==========================================
# 🧩 ИГРА "УГАДАЙ ИГРУ"
# ==========================================
active_games = {}


@dp.message(Command("game"))
async def start_game(m: Message):
    await m.answer("🧩 <b>Загружаю случайную игру...</b>", parse_mode="HTML")
    random_page = random.randint(1, 10)
    params = {
        "key": RAWG_KEY,
        "page_size": 10,
        "page": random_page,
        "ordering": "-rating",
        "exclude_adult": "true",
    }
    async with aiohttp.ClientSession() as s:
        async with s.get("https://api.rawg.io/api/games", params=params) as r:
            data = await r.json()

    games = data.get("results", [])
    if not games:
        return await m.answer("Ошибка загрузки. Попробуй позже.")

    target = random.choice(games)
    name = target.get("name")
    year = (target.get("released") or "?")[:4]
    genre = target.get("genres", [{}])[0].get("name", "Неизвестно")

    active_games[m.from_user.id] = {
        "name": name,
        "tries": 0,
        "genre": genre,
        "year": year,
    }

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💡 Подсказка 1 (Жанр)", callback_data="hint:1"
                )
            ],
            [InlineKeyboardButton(text="💡 Подсказка 2 (Год)", callback_data="hint:2")],
            [
                InlineKeyboardButton(
                    text="💡 Подсказка 3 (Буква)", callback_data="hint:3"
                )
            ],
            [InlineKeyboardButton(text="❌ Сдаться", callback_data="give_up")],
        ]
    )

    await m.answer(
        f"🧩 <b>Угадай игру!</b>\n\nЯ загадал известную игру. Напиши её название в чат!\n➖➖➖➖➖\n<i>Используй кнопки ниже, если нужна подсказка.</i>",
        reply_markup=kb,
        parse_mode="HTML",
    )


@dp.callback_query(F.data.startswith("hint:"))
async def game_hint(cb: CallbackQuery):
    level = int(cb.data.split(":")[1])
    game_data = active_games.get(cb.from_user.id)
    if not game_data:
        return await cb.answer("Игра не найдена. Начни заново: /game", show_alert=True)

    if level == 1:
        await cb.answer(
            f"Подсказка: Жанр этой игры - {game_data['genre']}", show_alert=True
        )
    elif level == 2:
        await cb.answer(
            f"Подсказка: Игра вышла в {game_data['year']} году.", show_alert=True
        )
    elif level == 3:
        await cb.answer(
            f"Подсказка: Название начинается на '{game_data['name'][0]}'",
            show_alert=True,
        )


@dp.callback_query(F.data == "give_up")
async def give_up(cb: CallbackQuery):
    game_data = active_games.pop(cb.from_user.id, None)
    if game_data:
        await cb.message.edit_text(
            f"🏳️ Ты сдался. Это была игра: <b>{game_data['name']}</b>",
            parse_mode="HTML",
        )
    await cb.answer()


# ==========================================
# 🎲 РУЛЕТКА
# ==========================================
@dp.message(Command("random"))
async def random_game(m: Message):
    conn = get_db()
    cursor = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute(
        "SELECT daily_searches, last_search_date FROM users WHERE user_id = ?",
        (m.from_user.id,),
    )
    searches, last_date = cursor.fetchone()

    if not is_user_vip(m.from_user.id):
        if last_date == today and searches >= 5:
            await m.answer(
                "❌ Лимит рулетки (5 раз в день) исчерпан. Купи VIP в /shop!"
            )
            conn.close()
            return

    if last_date != today:
        cursor.execute(
            "UPDATE users SET daily_searches = 1, last_search_date = ? WHERE user_id = ?",
            (today, m.from_user.id),
        )
    else:
        cursor.execute(
            "UPDATE users SET daily_searches = daily_searches + 1 WHERE user_id = ?",
            (m.from_user.id,),
        )
    conn.commit()
    conn.close()

    await m.answer("🎲 Крутим рулетку...")
    random_page = random.randint(1, 50)
    params = {
        "key": RAWG_KEY,
        "page_size": 10,
        "page": random_page,
        "ordering": "-rating",
        "exclude_adult": "true",
    }
    async with aiohttp.ClientSession() as s:
        async with s.get("https://api.rawg.io/api/games", params=params) as r:
            data = await r.json()
    games = data.get("results", [])
    if not games:
        return await m.answer("Рулетка заела.")

    g = random.choice(games)
    name, year = g.get("name"), (g.get("released") or "?")[:4]
    url, img = f"https://rawg.io/games/{g.get('slug')}", g.get("background_image")
    caption = f"🎲 <b>Твоя игра:</b>\n➖➖➖➖➖\n🎮 <b>{name}</b> ({year})\n🔗 <a href='{url}'>Страница</a>"
    if img:
        await m.answer_photo(img, caption=caption, parse_mode="HTML")
    else:
        await m.answer(caption, parse_mode="HTML")


async def send_random_by_genre(chat_id: int, genre: str):
    params = {
        "key": RAWG_KEY,
        "genres": genre,
        "page_size": 10,
        "ordering": "-rating",
        "exclude_adult": "true",
    }
    async with aiohttp.ClientSession() as s:
        async with s.get("https://api.rawg.io/api/games", params=params) as r:
            data = await r.json()
    games = data.get("results", [])
    if games:
        g = random.choice(games)
        url, img = f"https://rawg.io/games/{g.get('slug')}", g.get("background_image")
        caption = f"🎮 <b>{g.get('name')}</b> ({(g.get('released') or '?')[:4]})\n🔗 <a href='{url}'>Страница</a>"
        if img:
            await bot.send_photo(chat_id, img, caption=caption, parse_mode="HTML")
        else:
            await bot.send_message(chat_id, caption, parse_mode="HTML")


# ==========================================
# 🔍 ПОИСК
# ==========================================
@dp.message(Command("find"))
async def find(m: Message):
    await ask_genre(m.chat.id)


async def ask_genre(chat_id: int):
    items = list(GENRES.items())
    rows = []
    for i in range(0, len(items), 2):
        row = [
            InlineKeyboardButton(text=items[i][1], callback_data=f"genre:{items[i][0]}")
        ]
        if i + 1 < len(items):
            row.append(
                InlineKeyboardButton(
                    text=items[i + 1][1], callback_data=f"genre:{items[i+1][0]}"
                )
            )
        rows.append(row)
    await bot.send_message(
        chat_id,
        "1️⃣ Выбери жанр:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@dp.callback_query(F.data.startswith("genre:"))
async def on_genre(cb: CallbackQuery):
    key = cb.data.split(":")[1]
    await cb.message.edit_text(f"Жанр: {GENRES[key]} ✅")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="2010-2015", callback_data=f"year:{key}:2010-2015"
                ),
                InlineKeyboardButton(
                    text="2016-2020", callback_data=f"year:{key}:2016-2020"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="2021-2026", callback_data=f"year:{key}:2021-2026"
                )
            ],
        ]
    )
    await cb.message.answer("2️⃣ Выбери годы:", reply_markup=kb)
    await cb.answer()


@dp.callback_query(F.data.startswith("year:"))
async def on_year(cb: CallbackQuery):
    _, genre, years = cb.data.split(":")
    await cb.message.edit_text(f"Ищу... ⏳")
    await cb.answer()
    await search_games(cb.message.chat.id, genre, years)


async def search_games(chat_id: int, genre: str, years: str):
    dates = "2010-01-01,2026-12-31"
    if years == "2010-2015":
        dates = "2010-01-01,2015-12-31"
    elif years == "2016-2020":
        dates = "2016-01-01,2020-12-31"

    params = {
        "key": RAWG_KEY,
        "genres": genre,
        "dates": dates,
        "page_size": 5,
        "ordering": "-rating",
        "exclude_adult": "true",
    }
    async with aiohttp.ClientSession() as s:
        async with s.get("https://api.rawg.io/api/games", params=params) as r:
            data = await r.json()

    games = data.get("results", [])
    if not games:
        return await bot.send_message(chat_id, "😕 Ничего не нашлось.")

    for g in games:
        name, year = g.get("name"), (g.get("released") or "?")[:4]
        url, img = f"https://rawg.io/games/{g.get('slug')}", g.get("background_image")
        caption = f"🎮 <b>{name}</b> ({year})\n🔗 <a href='{url}'>Страница игры</a>"
        if img:
            await bot.send_photo(chat_id, img, caption=caption, parse_mode="HTML")
        else:
            await bot.send_message(chat_id, caption, parse_mode="HTML")


# ==========================================
# ⚙️ АДМИН-ПАНЕЛЬ
# ==========================================
@dp.message(Command("admin"))
async def admin(m: Message):
    if m.from_user.id != ADMIN_ID:
        return

    maint_until = int(get_setting("maintenance_until") or 0)
    break_mode = int(get_setting("break_mode") or 0)

    maint_status = "Выкл ✅" if maint_until < time.time() else "Вкл 🛠"
    break_status = "Выкл ✅" if break_mode == 0 else "Вкл ☕"

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    total = cursor.fetchone()[0]
    conn.close()

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🛠 Тех. обслуживание: {maint_status}",
                    callback_data="admin_maint_menu",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"☕ Перерыв: {break_status}", callback_data="admin_break_menu"
                )
            ],
            [InlineKeyboardButton(text="📬 Отзывы", callback_data="admin_feedback")],
            [
                InlineKeyboardButton(
                    text="⭐ Выдать себе VIP", callback_data="admin_give_vip"
                )
            ],
        ]
    )
    await m.answer(
        f"📊 <b>АДМИН-ПАНЕЛЬ</b>\n➖➖➖➖➖\n👥 Юзеров: <b>{total}</b>",
        reply_markup=kb,
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "admin_maint_menu")
async def admin_maint_menu(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🟢 Выключить ТО", callback_data="maint_0")],
            [InlineKeyboardButton(text="🔴 На 1 час", callback_data="maint_1")],
            [InlineKeyboardButton(text="🔴 На 1 день", callback_data="maint_24")],
        ]
    )
    await cb.message.edit_text(
        "🛠 <b>Режим тех. обслуживания:</b>", reply_markup=kb, parse_mode="HTML"
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("maint_"))
async def set_maintenance(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    hours = int(cb.data.split("_")[1])
    if hours == 0:
        set_setting("maintenance_until", "0")
    else:
        set_setting("maintenance_until", str(int(time.time()) + (hours * 3600)))
    await cb.answer("Обновлено!")
    await admin(cb.message)


@dp.callback_query(F.data == "admin_break_menu")
async def admin_break_menu(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🟢 Выключить перерыв", callback_data="break_0"
                )
            ],
            [InlineKeyboardButton(text="🟠 Включить перерыв", callback_data="break_1")],
        ]
    )
    await cb.message.edit_text(
        "☕ <b>Режим перерыва:</b>", reply_markup=kb, parse_mode="HTML"
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("break_"))
async def set_break(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    val = cb.data.split("_")[1]
    set_setting("break_mode", val)
    await cb.answer("Обновлено!")
    await admin(cb.message)


@dp.callback_query(F.data == "admin_give_vip")
async def admin_vip(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (cb.from_user.id,))
    conn.commit()
    conn.close()
    await cb.answer("✅ VIP выдан!", show_alert=True)


# ==========================================
# 🚀 ЗАПУСК
# ==========================================
async def main():
    logging.info("Бот запускается...")
    await set_commands()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
