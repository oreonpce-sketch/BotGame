import asyncio
import aiohttp
import sqlite3
import time
import random
from datetime import datetime
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
)

# ==========================================
# ⚙️ НАСТРОЙКИ (ОБЯЗАТЕЛЬНО ЗАПОЛНИ)
# ==========================================
TOKEN = "9299858779:AAGTG2vjcBYXo0ypXO4TEiUuO9d43AqUrMQ"
RAWG_KEY = "fe3a305eb58d4cc8a84977c835cc7149"
ADMIN_ID = 7977913545  # <--- ТВОЙ ID ЦИФРАМИ
BOT_LINK = "https://t.me/finders001_bot"  # <--- ССЫЛКА НА ТВОЕГО БОТА (для рефералки)
# ==========================================

bot = Bot(TOKEN)
dp = Dispatcher()


# ==========================================
# 🛡️ АНТИ-СПАМ (Anti-Flood)
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
        # Админа и ботов не ограничиваем
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
# 🗄️ БАЗА ДАННЫХ
# ==========================================
def init_db():
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_at TEXT,
            is_vip INTEGER DEFAULT 0,
            daily_searches INTEGER DEFAULT 0,
            last_search_date TEXT,
            ref_by INTEGER DEFAULT NULL,
            bonus_searches INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            game_name TEXT,
            game_url TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS search_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            genre TEXT,
            years TEXT,
            tag TEXT,
            searched_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def add_user(user_id, username, first_name, ref_by=None):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "INSERT INTO users (user_id, username, first_name, joined_at, ref_by) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, first_name, now, ref_by),
        )
        if ref_by:
            cursor.execute(
                "UPDATE users SET bonus_searches = bonus_searches + 10 WHERE user_id = ?",
                (ref_by,),
            )
            asyncio.create_task(
                bot.send_message(
                    ref_by,
                    "🎁 По твоей ссылке зашел друг! Тебе начислено +10 бонусных поисков.",
                )
            )
        conn.commit()
    conn.close()

    def is_user_vip(user_id):
        conn = sqlite3.connect("users.db")

    cursor = conn.cursor()
    cursor.execute("SELECT is_vip FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row and row[0] == 1


def set_user_vip(user_id):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def check_limit(user_id):
    if is_user_vip(user_id):
        return True, 999
    conn = sqlite3.connect("users.db")
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


def add_favorite(user_id, game_name, game_url):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO favorites (user_id, game_name, game_url) VALUES (?, ?, ?)",
        (user_id, game_name, game_url),
    )
    conn.commit()
    conn.close()


def get_favorites(user_id):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT game_name, game_url FROM favorites WHERE user_id = ?", (user_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def log_search(user_id, genre, years, tag):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "INSERT INTO search_logs (user_id, genre, years, tag, searched_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, genre, years, tag, now),
    )
    conn.commit()
    conn.close()


init_db()


# ==========================================
# 💳 ОПЛАТА ЗВЕЗДАМИ
# ==========================================
@dp.message(Command("shop"))
async def shop(m: Message):
    if is_user_vip(m.from_user.id):
        await m.answer(
            "⭐ У тебя уже есть VIP-статус! Тебе доступны: безлимит, рулетка и избранное."
        )
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Купить VIP за 50 ⭐", callback_data="buy_vip")]
        ]
    )
    await m.answer(
        "🛒 <b>VIP-Магазин</b>\n\n"
        "Что даёт VIP:\n"
        "✅ Безлимитные поиски (обычные: 15 в день)\n"
        "🎲 Режим «Рулетка» (/random)\n"
        "❤️ Сохранение в Избранное\n\n"
        "Цена: <b>50 Звёзд</b>",
        reply_markup=kb,
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "buy_vip")
async def send_invoice(cb: CallbackQuery):
    prices = [LabeledPrice(label="VIP Доступ", amount=50)]
    await cb.message.answer_invoice(
        title="VIP Доступ",
        description="Безлимит, Рулетка, Избранное",
        payload=f"vip_purchase_{cb.from_user.id}",
        provider_token="",  # Для звезд оставляем пустым
        currency="XTR",
        prices=prices,
    )
    await cb.answer()


@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)


@dp.message(F.successful_payment)
async def process_successful_payment(m: Message):
    set_user_vip(m.from_user.id)
    await m.answer(
        "🎉 <b>Оплата прошла успешно!</b>\nТвой VIP активирован. Попробуй /random!",
        parse_mode="HTML",
    )


# ==========================================
# 🎁 РЕФЕРАЛЬНАЯ СИСТЕМА
# ==========================================
@dp.message(Command("invite"))
async def invite(m: Message):
    user_id = m.from_user.id
    link = f"{BOT_LINK}?start=ref_{user_id}"
    await m.answer(
        f"🎁 <b>Пригласи друга и получи бонусы!</b>\n\n"
        f"Твоя ссылка:\n<code>{link}</code>\n\n"
        f"За каждого друга, который зайдет по ссылке, ты получишь <b>+10 бесплатных поисков</b>!",
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "invite_btn")
async def invite_btn(cb: CallbackQuery):
    await invite(cb.message)
    await cb.answer()


# ==========================================
# 🎮 ГЛАВНЫЙ СТАРТ
# ==========================================
@dp.message(Command("start"))
async def start(m: Message):
    args = m.text.split()
    ref_by = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            ref_by = int(args[1].split("_")[1])
        except:
            pass

    add_user(m.from_user.id, m.from_user.username, m.from_user.first_name, ref_by)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔍 Найти игру", callback_data="start_find"),
                InlineKeyboardButton(text="🏆 Топ игр", callback_data="top_genres"),
            ],
            [
                InlineKeyboardButton(text="🛒 Купить VIP", callback_data="shop_btn"),
                InlineKeyboardButton(
                    text="🎁 Пригласить друга", callback_data="invite_btn"
                ),
            ],
        ]
    )

    await m.answer(
        "🎮 <b>Привет! Я помогу найти игры.</b>\n\n"
        "🔍 /find — Поиск по фильтрам\n"
        "🔎 /search Название — Поиск по названию\n"
        "🏆 /top — Топ игр\n"
        "🎁 /invite — Пригласить друга (+10 поисков)\n"
        "❤️ /favorites — Избранное (VIP)\n"
        "🎲 /random — Рулетка (VIP)\n"
        "🛒 /shop — Купить VIP",
        reply_markup=kb,
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "start_find")
async def cb_start_find(cb: CallbackQuery):
    await cb.message.answer("Напиши /find чтобы начать поиск.")
    await cb.answer()


@dp.callback_query(F.data == "shop_btn")
async def cb_shop(cb: CallbackQuery):
    await shop(cb.message)
    await cb.answer()


# ==========================================
# 👑 VIP ФУНКЦИИ
# ==========================================
@dp.message(Command("random"))
async def random_game(m: Message):
    if not is_user_vip(m.from_user.id):
        await m.answer("❌ Эта функция доступна только VIP. Купи доступ в /shop.")
        return
    await m.answer("🎲 Крутим рулетку...")
    random_page = random.randint(1, 50)
    params = {
        "key": RAWG_KEY,
        "page_size": 10,
        "page": random_page,
        "ordering": "-rating",
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
    add_favorite(cb.from_user.id, name, url)
    await cb.answer("❤️ Добавлено в избранное!")


@dp.message(Command("favorites"))
async def show_favorites(m: Message):
    if not is_user_vip(m.from_user.id):
        await m.answer("❌ Только для VIP. Купи в /shop.")
        return
    favs = get_favorites(m.from_user.id)
    if not favs:
        await m.answer("Твой список избранного пуст.")
        return
    text = "❤️ <b>Твои избранные игры:</b>\n\n"
    for i, (name, url) in enumerate(favs, 1):
        text += f"{i}. <a href='{url}'>{name}</a>\n"
    await m.answer(text, parse_mode="HTML", disable_web_page_preview=True)


# ==========================================
# 🔍 ПОИСК ПО НАЗВАНИЮ
# ==========================================
@dp.message(Command("search"))
async def search_by_name(m: Message):
    args = m.text.split(maxsplit=1)
    if len(args) < 2:
        await m.answer(
            "🔎 Напиши название игры. Пример: <code>/search GTA</code>",
            parse_mode="HTML",
        )
        return

    query = args[1]
    params = {"key": RAWG_KEY, "search": query, "page_size": 5}
    async with aiohttp.ClientSession() as s:
        async with s.get("https://api.rawg.io/api/games", params=params) as r:
            data = await r.json()

    games = data.get("results", [])
    if not games:
        await m.answer("😕 По этому названию ничего не нашлось.")
        return

    for g in games:
        name, year, rating = (
            g.get("name"),
            (g.get("released") or "?")[:4],
            g.get("rating", 0),
        )
        raw_genres = [x["name"] for x in g.get("genres", [])[:3]]
        genres_ru = ", ".join(GENRE_RU.get(x, x) for x in raw_genres) or "—"
        url, img = f"https://rawg.io/games/{g.get('slug')}", g.get("background_image")

        kb = None
        if is_user_vip(m.from_user.id):
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="❤️ В избранное", callback_data=f"fav:{name}|{url}"
                        )
                    ]
                ]
            )

        caption = f"🎮 <b>{name}</b> ({year})\n⭐ Рейтинг: {rating}\n🎯 Жанры: {genres_ru}\n🔗 <a href='{url}'>Страница игры</a>"
        if img:
            await m.answer_photo(
                img, caption=caption, reply_markup=kb, parse_mode="HTML"
            )
        else:
            await m.answer(caption, reply_markup=kb, parse_mode="HTML")


# ==========================================
# 🏆 ТОП ИГР (Общий и по жанрам)
# ==========================================
@dp.message(Command("top"))
async def top_games(m: Message):
    # Кнопки: Общий топ + выбор жанра
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🌎 Общий Топ-10 (Все времена)", callback_data="top:all"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎯 Топ по жанру", callback_data="top:choose_genre"
                )
            ],
        ]
    )
    await m.answer("🏆 Выбери, какой Топ ты хочешь увидеть:", reply_markup=kb)


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
    rows.append([InlineKeyboardButton(text="⬅ Назад", callback_data="top_back")])
    await cb.message.edit_text(
        "🏆 Выбери жанр для Топ-10:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await cb.answer()


@dp.callback_query(F.data == "top_back")
async def top_back(cb: CallbackQuery):
    await top_games(cb.message)
    await cb.answer()


@dp.callback_query(F.data.startswith("top_genre:"))
async def on_top_genre(cb: CallbackQuery):
    genre = cb.data.split(":")[1]
    await cb.message.edit_text("🏆 Загружаю Топ-10...")
    await cb.answer()

    params = {"key": RAWG_KEY, "genres": genre, "page_size": 10, "ordering": "-rating"}
    await send_top_list(
        cb.message, params, f"🏆 <b>Топ-10 в жанре «{GENRES[genre]}»:</b>"
    )


@dp.callback_query(F.data == "top:all")
async def on_top_all(cb: CallbackQuery):
    await cb.message.edit_text("🌎 Загружаю Общий Топ-10...")
    await cb.answer()

    # Берем игры с наивысшим рейтингом (без фильтра по жанру)
    params = {
        "key": RAWG_KEY,
        "page_size": 10,
        "ordering": "-rating",
        "dates": "2000-01-01,2026-12-31",
    }
    await send_top_list(cb.message, params, "🌎 <b>Общий Топ-10 лучших игр:</b>")


async def send_top_list(message: Message, params: dict, title: str):
    async with aiohttp.ClientSession() as s:
        async with s.get("https://api.rawg.io/api/games", params=params) as r:
            data = await r.json()

    games = data.get("results", [])
    if not games:
        await message.answer("😕 Ничего не нашлось.")
        return

    text = f"{title}\n\n"
    for i, g in enumerate(games, 1):
        name, year, url = (
            g.get("name"),
            (g.get("released") or "?")[:4],
            f"https://rawg.io/games/{g.get('slug')}",
        )
        text += f"{i}. <a href='{url}'>{name}</a> ({year})\n"

    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)


@dp.callback_query(F.data == "top_genres")
async def cb_top_genres(cb: CallbackQuery):
    await top_games(cb.message)
    await cb.answer()


# ==========================================
# 📊 АДМИН-ПАНЕЛЬ
# ==========================================
@dp.message(Command("admin"))
async def admin_panel(m: Message):
    if m.from_user.id != ADMIN_ID:
        return
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_vip = 1")
    vip_users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE ref_by IS NOT NULL")
    ref_users = cursor.fetchone()[0]
    conn.close()
    await m.answer(
        f"📊 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        f"👥 Юзеров: <b>{total_users}</b>\n"
        f"⭐ VIP: <b>{vip_users}</b>\n"
        f"🎁 Пришло по рефке: <b>{ref_users}</b>",
        parse_mode="HTML",
    )


# ==========================================
# 🔍 ПОИСК ПО ФИЛЬТРАМ
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
YEARS = {
    "1990-1999": ("1990-01-01", "1999-12-31"),
    "2000-2009": ("2000-01-01", "2009-12-31"),
    "2010-2015": ("2010-01-01", "2015-12-31"),
    "2016-2020": ("2016-01-01", "2020-12-31"),
    "2021-2026": ("2021-01-01", "2026-12-31"),
}
TAG_GROUPS = {
    "🎯 Режим игры": {
        "singleplayer": "Одиночная",
        "multiplayer": "Мультиплеер",
        "co-op": "Кооператив",
        "pvp": "PvP",
    },
    "🌍 Мир": {
        "open-world": "Открытый мир",
        "sandbox": "Песочница",
        "sci-fi": "Sci-fi",
        "fantasy": "Фэнтези",
        "survival": "Выживание",
    },
    "🎭 Стиль": {
        "story-rich": "Сюжетная",
        "atmospheric": "Атмосферная",
        "dark": "Мрачная",
    },
    "⚙️ Механики": {
        "crafting": "Крафт",
        "stealth": "Стелс",
        "roguelike": "Рогалик",
        "souls-like": "Souls-like",
    },
}
GENRE_RU = {
    "Action": "Экшен",
    "RPG": "РПГ",
    "Shooter": "Шутер",
    "Horror": "Хоррор",
    "Adventure": "Приключения",
    "Strategy": "Стратегия",
    "Indie": "Инди",
    "Puzzle": "Головоломки",
    "Racing": "Гонки",
    "Sports": "Спорт",
    "Simulation": "Симулятор",
    "Fighting": "Файтинг",
    "Platformer": "Платформер",
    "Arcade": "Аркада",
}

user_state = {}


@dp.message(Command("find"))
async def find(m: Message):
    allowed, left = check_limit(m.from_user.id)
    if not allowed:
        await m.answer(
            "❌ Лимит (15 в день) исчерпан. Купи VIP в /shop или позови друга в /invite (+10 поисков)!"
        )
        return

    if left < 900:  # Если не VIP
        await m.answer(f"🔍 Осталось поисков на сегодня: {left}")

    user_state[m.from_user.id] = {"genre": None, "years": None, "tag": None}
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


async def ask_years(chat_id: int):
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"years:{label}")]
        for label in YEARS
    ]
    await bot.send_message(
        chat_id,
        "2️⃣ Выбери годы:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


async def ask_tag_group(chat_id: int):
    rows = [
        [InlineKeyboardButton(text=name, callback_data=f"group:{name}")]
        for name in TAG_GROUPS
    ]
    rows.append([InlineKeyboardButton(text="⏭ Пропустить", callback_data="group:skip")])
    await bot.send_message(
        chat_id,
        "3️⃣ Особенности:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


async def ask_tag(chat_id: int, group: str):
    items = list(TAG_GROUPS[group].items())
    rows = [
        [InlineKeyboardButton(text=items[i][1], callback_data=f"tag:{items[i][0]}")]
        + (
            [
                InlineKeyboardButton(
                    text=items[i + 1][1], callback_data=f"tag:{items[i+1][0]}"
                )
            ]
            if i + 1 < len(items)
            else []
        )
        for i in range(0, len(items), 2)
    ]
    rows.append([InlineKeyboardButton(text="⏭ Без тега", callback_data="tag:skip")])
    rows.append([InlineKeyboardButton(text="⬅ Назад", callback_data="group:back")])
    await bot.send_message(
        chat_id,
        f"4️⃣ Тег из «{group}»:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@dp.callback_query(F.data.startswith("genre:"))
async def on_genre(cb: CallbackQuery):
    key = cb.data.split(":")[1]
    user_state[cb.from_user.id]["genre"] = key
    await cb.message.edit_text(f"Жанр: {GENRES[key]} ✅")
    await ask_years(cb.message.chat.id)
    await cb.answer()


@dp.callback_query(F.data.startswith("years:"))
async def on_years(cb: CallbackQuery):
    label = cb.data.split(":")[1]
    user_state[cb.from_user.id]["years"] = label
    await cb.message.edit_text(f"Годы: {label} ✅")
    await ask_tag_group(cb.message.chat.id)
    await cb.answer()


@dp.callback_query(F.data.startswith("group:"))
async def on_group(cb: CallbackQuery):
    val = cb.data.split(":", 1)[1]
    if val == "skip":
        user_state[cb.from_user.id]["tag"] = None
        await cb.message.edit_text("Ищу… ⏳")
        await cb.answer()
        await search_games(cb.message.chat.id, user_state[cb.from_user.id])
        return
    if val == "back":
        await cb.message.edit_text("Возврат")
        await ask_tag_group(cb.message.chat.id)
        await cb.answer()
        return
    await cb.message.edit_text(f"Категория: {val}")
    await ask_tag(cb.message.chat.id, val)
    await cb.answer()


@dp.callback_query(F.data.startswith("tag:"))
async def on_tag(cb: CallbackQuery):
    key = cb.data.split(":", 1)[1]
    user_state[cb.from_user.id]["tag"] = None if key == "skip" else key
    await cb.message.edit_text("Ищу… ⏳")
    await cb.answer()
    await search_games(cb.message.chat.id, user_state[cb.from_user.id])


async def search_games(chat_id: int, state: dict):
    log_search(chat_id, state["genre"], state["years"], state["tag"] or "skip")
    params = {
        "key": RAWG_KEY,
        "genres": state["genre"],
        "dates": ",".join(YEARS[state["years"]]),
        "page_size": 5,
        "ordering": "-rating",
    }
    if state["tag"]:
        params["tags"] = state["tag"]

    async with aiohttp.ClientSession() as s:
        async with s.get("https://api.rawg.io/api/games", params=params) as r:
            data = await r.json()

    games = data.get("results", [])
    if not games:
        await bot.send_message(chat_id, "😕 Ничего не нашлось.")
        return

    for g in games:
        name, year, rating = (
            g.get("name"),
            (g.get("released") or "?")[:4],
            g.get("rating", 0),
        )
        raw_genres = [x["name"] for x in g.get("genres", [])[:3]]
        genres_ru = ", ".join(GENRE_RU.get(x, x) for x in raw_genres) or "—"
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

        caption = f"🎮 <b>{name}</b> ({year})\n⭐ Рейтинг: {rating}\n🎯 Жанры: {genres_ru}\n🔗 <a href='{url}'>Страница игры</a>"
        if img:
            await bot.send_photo(
                chat_id, img, caption=caption, reply_markup=kb, parse_mode="HTML"
            )
        else:
            await bot.send_message(chat_id, caption, reply_markup=kb, parse_mode="HTML")

    await bot.send_message(chat_id, "Хочешь ещё? /find")


async def main():
    print("Бот запускается...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
