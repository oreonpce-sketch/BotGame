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
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, joined_at TEXT, is_vip INTEGER DEFAULT 0, daily_searches INTEGER DEFAULT 0, last_search_date TEXT, ref_by INTEGER DEFAULT NULL, bonus_searches INTEGER DEFAULT 0, support_paid INTEGER DEFAULT 0)"
    )
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS favorites (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, game_name TEXT, game_url TEXT)"
    )
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS search_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, genre TEXT, years TEXT, tag TEXT, searched_at TEXT)"
    )
    # Новая таблица для отзывов
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT, text TEXT, date TEXT, is_paid INTEGER DEFAULT 0)"
    )
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
    if is_user_vip(user_id):
        return True, 999
    conn = get_db()
    cursor = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute(
        "SELECT daily_searches, last_search_date, bonus_searches FROM users WHERE user_id = ?",
        (user_id,),
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        return True, 15

    searches, last_date, bonuses = row
    if last_date != today:
        cursor.execute(
            "UPDATE users SET daily_searches = 0, last_search_date = ? WHERE user_id = ?",
            (today, user_id),
        )
        conn.commit()
        searches = 0

    total_available = 15 + bonuses - searches
    if total_available <= 0:
        conn.close()
        return False, 0

    cursor.execute(
        "UPDATE users SET daily_searches = daily_searches + 1 WHERE user_id = ?",
        (user_id,),
    )
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
        self.warnings: Dict[int, float] = {}
        super().__init__()

    async def __call__(
        self, handler, event: TelegramObject, data: Dict[str, Any]
    ) -> Any:
        user = data.get("event_from_user")
        if not user or user.is_bot or user.id == ADMIN_ID:
            return await handler(event, data)

        now = time.time()
        if now - self.users.get(user.id, 0) < self.limit:
            if now - self.warnings.get(user.id, 0) > 5:
                self.warnings[user.id] = now
                try:
                    if isinstance(event, Message):
                        await event.answer("⏳ Не так быстро!")
                    elif isinstance(event, CallbackQuery):
                        await event.answer("⏳ Слишком часто!", show_alert=False)
                except:
                    pass
                return
        self.users[user.id] = now
        return await handler(event, data)


dp.message.middleware(AntiFloodMiddleware(limit=1.5))
dp.callback_query.middleware(AntiFloodMiddleware(limit=1.5))

# ==========================================
# 🎮 ЖАНРЫ И МЕНЮ
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
}


async def set_commands():
    commands = [
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="find", description="🔍 Найти игру"),
        BotCommand(command="top", description="🏆 Топ игр"),
        BotCommand(command="random", description="🎲 Рулетка (VIP)"),
        BotCommand(command="shop", description="🛒 Купить VIP"),
        BotCommand(command="support", description="💬 Поддержка"),
        BotCommand(command="invite", description="🎁 Пригласить друга"),
    ]
    await bot.set_my_commands(commands)


# ==========================================
# 🚀 СТАРТ
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
            cursor.execute(
                "INSERT INTO users (user_id, username, first_name, joined_at, ref_by) VALUES (?, ?, ?, ?, ?)",
                (
                    m.from_user.id,
                    m.from_user.username,
                    m.from_user.first_name,
                    now,
                    ref_by,
                ),
            )
            conn.commit()
            if ref_by:
                cursor.execute(
                    "UPDATE users SET bonus_searches = bonus_searches + 10 WHERE user_id = ?",
                    (ref_by,),
                )
                conn.commit()
                try:
                    asyncio.create_task(
                        bot.send_message(
                            ref_by, "🎁 По твоей ссылке зашел друг! +10 поисков."
                        )
                    )
                except:
                    pass
        conn.close()

        await m.answer(
            "🎮 Привет! Я помогу найти игры.\n\n🔍 /find — Поиск\n🏆 /top — Топы\n🛒 /shop — VIP за 20⭐\n💬 /support — Поддержка"
        )
    except Exception as e:
        logging.error(f"Ошибка в start: {e}")


# ==========================================
# 💳 ОПЛАТА И VIP
# ==========================================
@dp.message(Command("shop"))
async def shop(m: Message):
    if is_user_vip(m.from_user.id):
        await m.answer(
            "⭐ У тебя уже есть VIP! Доступно: безлимит, рулетка и избранное."
        )
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Купить VIP за 20 ⭐", callback_data="buy_vip")]
        ]
    )
    await m.answer(
        "🛒 <b>VIP-Магазин</b>\n\n✅ Безлимит поисков (обычные: 15 в день)\n🎲 Рулетка\n❤️ Избранное\n\nЦена: <b>20 Звёзд</b>",
        reply_markup=kb,
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "buy_vip")
async def send_invoice(cb: CallbackQuery):
    prices = [LabeledPrice(label="VIP Доступ", amount=20)]
    await cb.message.answer_invoice(
        title="VIP Доступ",
        description="Безлимит, Рулетка, Избранное",
        payload="vip",
        provider_token="",
        currency="XTR",
        prices=prices,
    )
    await cb.answer()


@dp.pre_checkout_query()
async def process_pre_checkout(q: PreCheckoutQuery):
    await q.answer(ok=True)


@dp.message(F.successful_payment)
async def success_payment(m: Message):
    payload = m.successful_payment.invoice_payload
    conn = get_db()
    cursor = conn.cursor()

    if payload == "vip":
        cursor.execute(
            "UPDATE users SET is_vip = 1 WHERE user_id = ?", (m.from_user.id,)
        )
        conn.commit()
        await m.answer("🎉 Оплата прошла! VIP активирован. Попробуй /random")
    elif payload == "support":
        cursor.execute(
            "UPDATE users SET support_paid = 1 WHERE user_id = ?", (m.from_user.id,)
        )
        conn.commit()
        await m.answer(
            "✅ Спасибо за поддержку! Теперь напиши свой вопрос или предложение одним сообщением."
        )

    conn.close()


# ==========================================
# 💬 ПОДДЕРЖКА РАЗРАБОТЧИКА (С ОТЗЫВАМИ)
# ==========================================
@dp.message(Command("support"))
async def support(m: Message):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Написать отзыв (Бесплатно)", callback_data="support_free"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⭐ Поддержать и написать (2 ⭐)", callback_data="support_paid"
                )
            ],
        ]
    )
    await m.answer(
        "💬 <b>Поддержка</b>\n\nТы можешь просто написать отзыв, идею или жалобу. А можешь поддержать разработчика на 2 звезды, и твое сообщение будет в приоритете!",
        reply_markup=kb,
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "support_free")
async def support_free(cb: CallbackQuery):
    admin_states[cb.from_user.id] = {"type": "feedback_free"}
    await cb.message.edit_text("Напиши свой отзыв или идею одним сообщением:")
    await cb.answer()


@dp.callback_query(F.data == "support_paid")
async def support_paid(cb: CallbackQuery):
    prices = [LabeledPrice(label="Поддержка", amount=2)]
    await cb.message.answer_invoice(
        title="Поддержка разработчика",
        description="Отправь 2 звезды и напиши свой вопрос/идею.",
        payload="support",
        provider_token="",
        currency="XTR",
        prices=prices,
    )
    await cb.answer()


# ==========================================
# 👑 VIP ФУНКЦИИ (РУЛЕТКА И ИЗБРАННОЕ)
# ==========================================
@dp.message(Command("random"))
async def random_game(m: Message):
    if not is_user_vip(m.from_user.id):
        await m.answer("❌ Только для VIP. Купи доступ в /shop.")
        return
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
        await m.answer("Рулетка заела, попробуй еще раз.")
        return
    g = random.choice(games)
    name, year, rating = (
        g.get("name"),
        (g.get("released") or "?")[:4],
        g.get("rating", 0),
    )
    url, img = f"https://rawg.io/games/{g.get('slug')}", g.get("background_image")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❤️ В избранное", callback_data=f"fav:{name}|{url}"
                )
            ]
        ]
    )
    caption = f"🎲 <b>Твоя случайная игра:</b>\n\n🎮 <b>{name}</b> ({year})\n⭐ Рейтинг: {rating}\n🔗 <a href='{url}'>Страница</a>"
    if img:
        await m.answer_photo(img, caption=caption, reply_markup=kb, parse_mode="HTML")
    else:
        await m.answer(caption, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data.startswith("fav:"))
async def add_to_fav(cb: CallbackQuery):
    if not is_user_vip(cb.from_user.id):
        await cb.answer("❌ Только для VIP!", show_alert=True)
        return
    raw = cb.data.split(":", 1)[1]
    name, url = raw.split("|", 1)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO favorites (user_id, game_name, game_url) VALUES (?, ?, ?)",
        (cb.from_user.id, name, url),
    )
    conn.commit()
    conn.close()
    await cb.answer("❤️ Добавлено в избранное!")


# ==========================================
# 🔍 ПОИСК ПО ФИЛЬТРАМ
# ==========================================
@dp.message(Command("find"))
async def find(m: Message):
    allowed, left = check_limit(m.from_user.id)
    if not allowed:
        await m.answer(
            "❌ Лимит исчерпан. Купи VIP в /shop или позови друга в /invite!"
        )
        return
    if left < 900:
        await m.answer(f"🔍 Осталось поисков: {left}")
    await ask_genre(m.chat.id)

    async def ask_genre(chat_id: int):
        items = list(GENRES.items())

    rows = [
        [InlineKeyboardButton(text=items[i][1], callback_data=f"genre:{items[i][0]}")]
        + (
            [
                InlineKeyboardButton(
                    text=items[i + 1][1], callback_data=f"genre:{items[i+1][0]}"
                )
            ]
            if i + 1 < len(items)
            else []
        )
        for i in range(0, len(items), 2)
    ]
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
    await cb.message.edit_text(f"Ищу игры в жанре {genre} за {years}... ⏳")
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
        await bot.send_message(chat_id, "😕 Ничего не нашлось.")
        return

    for g in games:
        name, year = g.get("name"), (g.get("released") or "?")[:4]
        url, img = f"https://rawg.io/games/{g.get('slug')}", g.get("background_image")

        kb = None
        if is_user_vip(chat_id):
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="❤️ В избранное", callback_data=f"fav:{name}|{url}"
                        )
                    ]
                ]
            )

        caption = f"🎮 <b>{name}</b> ({year})\n🔗 <a href='{url}'>Страница игры</a>"
        if img:
            await bot.send_photo(
                chat_id, img, caption=caption, reply_markup=kb, parse_mode="HTML"
            )
        else:
            await bot.send_message(chat_id, caption, reply_markup=kb, parse_mode="HTML")


# ==========================================
# 🏆 ТОП ИГР
# ==========================================
@dp.message(Command("top"))
async def top(m: Message):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌎 Общий Топ-10", callback_data="top:all")],
            [
                InlineKeyboardButton(
                    text="🎯 Топ по жанру", callback_data="top:choose_genre"
                )
            ],
        ]
    )
    await m.answer("🏆 Какой Топ показать?", reply_markup=kb)


@dp.callback_query(F.data == "top:choose_genre")
async def top_genre_list(cb: CallbackQuery):
    items = list(GENRES.items())
    rows = [
        [
            InlineKeyboardButton(
                text=items[i][1], callback_data=f"top_genre:{items[i][0]}"
            )
        ]
        + (
            [
                InlineKeyboardButton(
                    text=items[i + 1][1], callback_data=f"top_genre:{items[i+1][0]}"
                )
            ]
            if i + 1 < len(items)
            else []
        )
        for i in range(0, len(items), 2)
    ]
    await cb.message.edit_text(
        "🏆 Выбери жанр для Топ-10:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("top_genre:"))
async def on_top_genre(cb: CallbackQuery):
    genre = cb.data.split(":")[1]
    await cb.message.edit_text("🏆 Загружаю...")
    await cb.answer()
    params = {
        "key": RAWG_KEY,
        "genres": genre,
        "page_size": 30,
        "ordering": "-rating",
        "exclude_adult": "true",
    }
    await send_top_list(
        cb.message, params, f"🏆 <b>Топ-10 в жанре «{GENRES[genre]}»:</b>"
    )


@dp.callback_query(F.data == "top:all")
async def on_top_all(cb: CallbackQuery):
    await cb.message.edit_text("🌎 Загружаю...")
    await cb.answer()
    params = {
        "key": RAWG_KEY,
        "page_size": 10,
        "ordering": "-rating",
        "dates": "2000-01-01,2026-12-31",
        "exclude_adult": "true",
    }
    await send_top_list(cb.message, params, "🌎 <b>Общий Топ-10:</b>")


async def send_top_list(message: Message, params: dict, title: str):
    async with aiohttp.ClientSession() as s:
        async with s.get("https://api.rawg.io/api/games", params=params) as r:
            data = await r.json()
    games = data.get("results", [])
    if not games:
        return await message.answer("😕 Ничего не нашлось.")

    bad_words = ["hentai", "sex", "adult", "erotic", "nsfw", "porn"]
    good_games = []
    for g in games:
        if any(w in g.get("name", "").lower() for w in bad_words):
            continue
        if g.get("background_image"):
            good_games.append(g)
        if len(good_games) == 10:
            break

    text = f"{title}\n\n"
    for i, g in enumerate(good_games, 1):
        text += f"{i}. <a href='https://rawg.io/games/{g.get('slug')}'>{g.get('name')}</a> ({(g.get('released') or '?')[:4]})\n"
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)


# ==========================================
# ⚙️ АДМИН-ПАНЕЛЬ И РАССЫЛКА
# ==========================================
admin_states = {}


@dp.message(Command("admin"))
async def admin(m: Message):
    if m.from_user.id != ADMIN_ID:
        return

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_vip = 1")
    vips = cursor.fetchone()[0]
    conn.close()

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⭐ Выдать себе VIP", callback_data="admin_give_vip"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📬 Отзывы и жалобы", callback_data="admin_feedback"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📢 Сделать рассылку", callback_data="admin_broadcast"
                )
            ],
        ]
    )
    await m.answer(
        f"📊 <b>АДМИН-ПАНЕЛЬ</b>\n\n👥 Юзеров: <b>{total}</b>\n⭐ VIP: <b>{vips}</b>",
        reply_markup=kb,
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "admin_give_vip")
async def admin_vip(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (cb.from_user.id,))
    conn.commit()
    conn.close()
    await cb.answer("✅ Тебе выдан VIP!", show_alert=True)


# Кнопка просмотра отзывов
@dp.callback_query(F.data == "admin_feedback")
async def admin_feedback(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT user_id, username, text, date, is_paid FROM feedback ORDER BY id DESC LIMIT 10"
    )
    feedbacks = cursor.fetchall()
    conn.close()

    if not feedbacks:
        await cb.message.answer("📬 Пока нет отзывов.")
        await cb.answer()
        return

    text = "📬 <b>Последние 10 отзывов:</b>\n\n"
    for f in feedbacks:
        icon = "⭐" if f[4] == 1 else "💬"
        text += f"{icon} <a href='tg://user?id={f[0]}'>{f[1] or 'Пользователь'}</a> ({f[3]}):\n{f[2]}\n\n"

    await cb.message.answer(text, parse_mode="HTML", disable_web_page_preview=True)
    await cb.answer()


@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    admin_states[cb.from_user.id] = {"type": "broadcast"}
    await cb.message.answer("Напиши текст для рассылки (или напиши 'отмена'):")
    await cb.answer()


# ==========================================
# 📩 ОБРАБОТКА ТЕКСТА (РАССЫЛКА И ОТЗЫВЫ)
# ==========================================
@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text(m: Message):
    # 1. Логика для Админа (рассылка)
    if (
        m.from_user.id == ADMIN_ID
        and admin_states.get(ADMIN_ID, {}).get("type") == "broadcast"
    ):
        if m.text.lower() == "отмена":
            admin_states[ADMIN_ID] = None
            await m.answer("Рассылка отменена.")
            return

        admin_states[ADMIN_ID] = None
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
            except:
                pass
        await m.answer(f"✅ Отправлено: {count} чел.")
        return

    # 2. Логика для Пользователей (отзывы)
    state = admin_states.get(m.from_user.id, {})
    if state.get("type") == "feedback_free" or state.get("type") == "feedback_paid":
        # Сохраняем отзыв в базу
        conn = get_db()
        cursor = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        is_paid = 1 if state.get("type") == "feedback_paid" else 0
        cursor.execute(
            "INSERT INTO feedback (user_id, username, text, date, is_paid) VALUES (?, ?, ?, ?, ?)",
            (m.from_user.id, m.from_user.username, m.text, now, is_paid),
        )
        conn.commit()
        conn.close()

        # Удаляем состояние
        admin_states[m.from_user.id] = None

        await m.answer("✅ Спасибо! Твой отзыв отправлен разработчику.")

        # Уведомляем тебя
        try:
            icon = "⭐ (Оплачено)" if is_paid else "💬 (Бесплатно)"
            await bot.send_message(
                ADMIN_ID,
                f"📬 <b>Новый отзыв {icon}</b>\n\nОт: {m.from_user.first_name} (@{m.from_user.username})\nТекст:\n{m.text}",
                parse_mode="HTML",
            )
        except:
            pass
        return


# ==========================================
# 🚀 ЗАПУСК
# ==========================================
async def main():
    logging.info("Бот запускается...")
    await set_commands()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
