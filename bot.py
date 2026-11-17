import asyncio
import aiohttp
import sqlite3
import time
import random
import os
import logging
import html
from datetime import datetime, timedelta
from typing import Any, Dict

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, TelegramObject, PreCheckoutQuery, LabeledPrice,
    InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
)

logging.basicConfig(level=logging.INFO)

# ⚙️ НАСТРОЙКИ (без дефолтных секретов — задавай через переменные окружения!)
TOKEN = os.getenv("TOKEN", "9299858779:AAGTG2vjcBYXo0ypXO4TEiUuO9d43AqUrMQ")
RAWG_KEY = os.getenv("RAWG_KEY", "fe3a305eb58d4cc8a84977c835cc7149")
ADMIN_ID = int(os.getenv("ADMIN_ID", "7977913545"))
BOT_LINK = os.getenv("BOT_LINK", "https://t.me/finders001_bot")
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/gamefinderoff_330")
SECRET_PAYLOAD = os.getenv("SECRET_PAYLOAD", )
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", )
VIP_DAYS = int(os.getenv("VIP_DAYS", "80"))     # срок покупного VIP
DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", "10"))  # лимит бесплатно в день

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
    cursor.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, joined_at TEXT,
        is_vip INTEGER DEFAULT 0, vip_until TEXT DEFAULT NULL,
        daily_searches INTEGER DEFAULT 0, last_search_date TEXT,
        ref_by INTEGER DEFAULT NULL, ref_count INTEGER DEFAULT 0,
        bonus_searches INTEGER DEFAULT 0, recs_enabled INTEGER DEFAULT 1,
        is_helper INTEGER DEFAULT 0)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS favorites (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        game_name TEXT, game_url TEXT)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        username TEXT, text TEXT, date TEXT)""")
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
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
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
            if datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S") > datetime.now():
                return True
        except ValueError:
            pass
    return False

def is_user_helper(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT is_helper FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return bool(row and row[0] == 1)

def ensure_user(user_id, username, first_name):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO users (user_id, username, first_name, joined_at) VALUES (?, ?, ?, ?)",
            (user_id, username, first_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
    conn.close()

def check_limit(user_id):
    """True — лимит не исчерпан (и увеличен). False — исчерпан."""
    if is_user_vip(user_id):
        return True
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT daily_searches, last_search_date FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return True
    searches, last_date = row
    today = datetime.now().strftime("%Y-%m-%d")
    if last_date != today:
        searches = 0
    if searches >= DAILY_LIMIT:
        return False
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET daily_searches = ?, last_search_date = ? WHERE user_id = ?",
        (searches + 1, today, user_id))
    conn.commit()
    conn.close()
    return True

# ==========================================
# 🛡️ БЕЗОПАСНОСТЬ
# ==========================================
class SecurityMiddleware(BaseMiddleware):
    def __init__(self):
        self.users: Dict[int, float] = {}
        self.blocked: Dict[int, float] = {}
        self.counter = 0
        super().__init__()

    def _cleanup(self):
        now = time.time()
        self.users = {uid: ts for uid, ts in self.users.items() if now - ts < 3600}
        self.blocked = {uid: ts for uid, ts in self.blocked.items() if ts > now}

    async def __call__(self, handler, event: TelegramObject, data: Dict[str, Any]) -> Any:
        self.counter += 1
        if self.counter % 1000 == 0:
            self._cleanup()
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        maint_until = int(get_setting("maintenance_until") or 0)
        if maint_until > time.time():
            if user.id == ADMIN_ID:
                if isinstance(event, Message) and event.text and event.text.startswith("/admin"):
                    return await handler(event, data)
                if isinstance(event, Message):
                    await safe_answer(event, "🛠 <b>На тех. обслуживании.</b> Админ, доступна только /admin")
                return
            if isinstance(event, Message):
                await safe_answer(event, "🛠 <b>Бот на тех. обслуживании.</b>\nЗайди позже!")
            elif isinstance(event, CallbackQuery):
                try:
                    await event.answer("🛠 На тех. обслуживании.", show_alert=True)
                except Exception:
                    pass
            return

        break_mode = int(get_setting("break_mode") or 0)
        if break_mode == 1 and user.id != ADMIN_ID:
            if isinstance(event, Message):
                await safe_answer(event, "☕ <b>Перерыв!</b>\nСкоро вернусь.")
            elif isinstance(event, CallbackQuery):
                try:
                    await event.answer("☕ Перерыв!", show_alert=True)
                except Exception:
                    pass
            return

        if user.is_bot or user.id == ADMIN_ID or is_user_helper(user.id):
            return await handler(event, data)
        now = time.time()
        if user.id in self.blocked and now < self.blocked[user.id]:
            return
        if now - self.users.get(user.id, 0) < 0.5:
            self.blocked[user.id] = now + 30
            if isinstance(event, Message):
                await safe_answer(event, "🚫 Блок на 30 сек за спам.")
            elif isinstance(event, CallbackQuery):
                try:
                    await event.answer("🚫 Блок на 30 сек за спам.", show_alert=True)
                except Exception:
                    pass
            return
        self.users[user.id] = now
        return await handler(event, data)

async def safe_answer(msg: Message, text: str):
    try:
        await msg.answer(text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception:
        logging.exception("Не удалось отправить сообщение")

dp.message.middleware(SecurityMiddleware())
dp.callback_query.middleware(SecurityMiddleware())

# ==========================================
# 🧒 ФИЛЬТР 18+ (RAWG не умеет исключать — фильтруем сами)
# ==========================================
# Теги RAWG, по которым считаем игру взрослой
ADULT_TAGS = {
    "adult", "adult-only", "nsfw", "nudity", "sexual-content", "sex", "sexuality",
    "hentai", "porn", "pornographic", "erotic", "eroge", "explicit", "uncensored"
}
# ESRB-рейтинг «Adults Only» — это и есть официальные 18+
ADULT_ESRB = {"adults-only", "ao"}

def is_adult(game: dict) -> bool:
    if not game:
        return False
    esrb = (game.get("esrb_rating") or {}).get("slug", "") or ""
    if esrb.lower() in ADULT_ESRB:
        return True
    for t in game.get("tags", []) or []:
        slug = (t.get("slug") or "").lower()
        if slug in ADULT_TAGS:
            return True
    return False

async def api_games(params: dict) -> list:
    """Запрос к RAWG + фильтр 18+. Берём с запасом, чтобы после фильтра оставались игры."""
    params = dict(params)
    params["key"] = RAWG_KEY
    params.setdefault("page_size", 20)
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get("https://api.rawg.io/api/games", params=params) as r:
                data = await r.json()
        return [g for g in data.get("results", []) if not is_adult(g)]
    except Exception:
        logging.exception("Ошибка запроса к RAWG")
        return []

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

GAME_CACHE: Dict[str, tuple] = {}  # slug -> (name, url)

async def set_commands():
    await bot.set_my_commands([
        BotCommand(command="start", description="🏠 Меню"),
        BotCommand(command="find", description="🔍 Поиск"),
        BotCommand(command="top", description="🏆 Топы"),
        BotCommand(command="game", description="🧩 Игра"),
        BotCommand(command="random", description="🎲 Рулетка"),
        BotCommand(command="favorites", description="❤️ Избранное"),
        BotCommand(command="settings", description="⚙️ Настройки"),
        BotCommand(command="shop", description="🛒 VIP"),
    ])

# ==========================================
# 🧩 ХЕЛПЕРЫ ДЛЯ ОТПРАВКИ ИГР
# ==========================================
def esc(text: str) -> str:
    return html.escape(str(text or ""))

def game_caption(g: dict) -> str:
    name = esc(g.get("name"))
    year = (g.get("released") or "?")[:4]
    slug = g.get("slug") or ""
    url = f"https://rawg.io/games/{slug}"
    GAME_CACHE[slug] = (g.get("name") or "Игра", url)
    return f"🎮 <b>{name}</b> ({esc(year)})\n🔗 <a href='{url}'>Ссылка</a>"

def fav_kb(g: dict, user_id: int):
    if not is_user_vip(user_id):
        return None
    slug = g.get("slug") or ""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❤️ В избранное", callback_data=f"fav:{slug}")
    ]])

async def send_game(chat_id: int, g: dict, user_id: int):
    caption = game_caption(g)
    kb = fav_kb(g, user_id)
    img = g.get("background_image")
    try:
        if img:
            await bot.send_photo(chat_id, img, caption=caption, reply_markup=kb, parse_mode="HTML")
        else:
            await bot.send_message(chat_id, caption, reply_markup=kb, parse_mode="HTML",
                                   disable_web_page_preview=True)
    except Exception:
        logging.exception("Не удалось отправить игру")

# ==========================================
# 🚀 СТАРТ
# ==========================================
@dp.message(Command("start"))
async def start(m: Message):
    ensure_user(m.from_user.id, m.from_user.username, m.from_user.first_name)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📢 Наш канал", url=CHANNEL_LINK)]])
    vip_note = ""
    if is_user_vip(m.from_user.id):
        vip_note = "⭐ VIP активен\n"
    await safe_answer(m, f"🎮 <b>Привет!</b>\n➖➖➖➖➖➖➖➖\n🔍 /find — Поиск\n🏆 /top — Топы\n🧩 /game — Викторина\n🎲 /random — Рулетка\n❤️ /favorites — Избранное\n⚙️ /settings — Настройки\n🛒 /shop — VIP\n{vip_note}")

# ==========================================
# 🔍 ПОИСК
# ==========================================
find_state: Dict[int, dict] = {}  # user_id -> {"query": str, "offset": int}

@dp.message(Command("find"))
async def find(m: Message):
    items = list(GENRES.items())
    rows = []
    for i in range(0, len(items), 2):
        row = [InlineKeyboardButton(text=items[i][1], callback_data=f"genre:{items[i][0]}")]
        if i + 1 < len(items):
            row.append(InlineKeyboardButton(text=items[i + 1][1], callback_data=f"genre:{items[i + 1][0]}"))
        rows.append(row)
    rows.insert(0, [InlineKeyboardButton(text="🔍 По названию", callback_data="find:search")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    await safe_answer(m, "🔍 <b>Как ищем?</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@dp.callback_query(F.data == "find:search")
async def find_by_name(cb: CallbackQuery):
    find_state[cb.from_user.id] = {"query": None, "offset": 0}
    await cb.message.answer("🔍 <b>Напиши название игры:</b>", parse_mode="HTML")
    await cb.answer()

@dp.callback_query(F.data.startswith("genre:"))
async def on_genre(cb: CallbackQuery):
    key = cb.data.split(":", 1)[1]
    try:
        await cb.message.edit_text(f"Жанр: {GENRES[key]} ✅")
    except Exception:
        pass
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="2010–2015", callback_data=f"year:{key}:2010-2015")],
        [InlineKeyboardButton(text="2021–2026", callback_data=f"year:{key}:2021-2026")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]])
    await cb.message.answer("2️⃣ <b>Годы:</b>", reply_markup=kb, parse_mode="HTML")
    await cb.answer()

@dp.callback_query(F.data.startswith("year:"))
async def on_year(cb: CallbackQuery):
    _, genre, years = cb.data.split(":")
    if not check_limit(cb.from_user.id):
        await cb.answer("❌ Лимит на сегодня исчерпан. VIP — без лимита!", show_alert=True)
        return
    try:
        await cb.message.edit_text("⏳ Ищу...")
    except Exception:
        pass
    await cb.answer()
    if years == "2010-2015":
        dates = "2010-01-01,2015-12-31"
    else:
        dates = "2021-01-01,2026-12-31"
    params = {"dates": dates, "page_size": 5, "ordering": "-rating", "genres": genre}
    if genre == "horror":
        params.pop("genres")
        params["tags"] = "horror"
    games = await api_games(params)
    if not games:
        await safe_answer(cb.message, "😕 Ничего не нашёл.")
        return
    for g in games[:5]:
        await send_game(cb.message.chat.id, g, cb.from_user.id)

@dp.callback_query(F.data == "find:more")
async def find_more(cb: CallbackQuery):
    st = find_state.get(cb.from_user.id)
    if not st or not st.get("query"):
        return await cb.answer("Начни заново: /find", show_alert=True)
    if not check_limit(cb.from_user.id):
        await cb.answer("❌ Лимит на сегодня исчерпан. VIP — без лимита!", show_alert=True)
        return
    await cb.answer("Ищу ещё...")
    await run_search(cb.message, cb.from_user.id, st["query"], st["offset"] + 5)

async def run_search(message: Message, user_id: int, query: str, offset: int = 0):
    games = await api_games({"search": query, "page_size": 20, "ordering": "-rating"})
    games = games[offset:offset + 5]
    if not games:
        await safe_answer(message, "😕 Больше ничего не нашёл. Попробуй другое название: /find")
        find_state.pop(user_id, None)
        return
    kb_rows = []
    for g in games:
        await send_game(message.chat.id, g, user_id)
    if offset + 5 < 20 and games:
        kb_rows.append([InlineKeyboardButton(text="🔄 Ещё", callback_data="find:more")])
    if kb_rows:
        try:
            await message.answer("...", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
        except Exception:
            pass

@dp.message(Command("cancel_find"))
async def cancel_find(m: Message):
    find_state.pop(m.from_user.id, None)
    active_games.pop(m.from_user.id, None)
    await safe_answer(m, "✅ Готово.")

# ==========================================
# 🏆 ТОП
# ==========================================
@dp.message(Command("top"))
async def top(m: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌎 Общий", callback_data="top:all")],
        [InlineKeyboardButton(text="🎯 Жанр", callback_data="top:choose_genre")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]])
    await safe_answer(m, "🏆 <b>Топ:</b>", reply_markup=kb)

@dp.callback_query(F.data == "top:choose_genre")
async def top_genre_list(cb: CallbackQuery):
    items = list(GENRES.items())
    rows = []
    for i in range(0, len(items), 2):
        row = [InlineKeyboardButton(text=items[i][1], callback_data=f"top_genre:{items[i][0]}")]
        if i + 1 < len(items):
            row.append(InlineKeyboardButton(text=items[i + 1][1], callback_data=f"top_genre:{items[i + 1][0]}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    try:
        await cb.message.edit_text("🏆 <b>Жанр:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")
    except Exception:
        pass
    await cb.answer()

@dp.callback_query(F.data.startswith("top_genre:"))
async def on_top_genre(cb: CallbackQuery):
    if not check_limit(cb.from_user.id):
        await cb.answer("❌ Лимит на сегодня исчерпан. VIP — без лимита!", show_alert=True)
        return
    genre = cb.data.split(":", 1)[1]
    try:
        await cb.message.edit_text("🏆 Гружу...")
    except Exception:
        pass
    await cb.answer()
    params = {"page_size": 30, "ordering": "-rating", "genres": genre}
    if genre == "horror":
        params.pop("genres")
        params["tags"] = "horror"
    await send_top_list(cb.message, params, f"🏆 <b>Топ «{GENRES[genre]}»:</b>")

@dp.callback_query(F.data == "top:all")
async def on_top_all(cb: CallbackQuery):
    if not check_limit(cb.from_user.id):
        await cb.answer("❌ Лимит на сегодня исчерпан. VIP — без лимита!", show_alert=True)
        return
    try:
        await cb.message.edit_text("🌎 Гружу...")
    except Exception:
        pass
    await cb.answer()
    params = {"page_size": 10, "ordering": "-rating", "dates": "2000-01-01,2026-12-31"}
    await send_top_list(cb.message, params, "🌎 <b>Топ-10:</b>")

async def send_top_list(message: Message, params: dict, title: str):
    games = await api_games(params)
    lines = [f"{i}. <a href='https://rawg.io/games/{g.get('slug')}'>{esc(g.get('name'))}</a>"
             for i, g in enumerate(games[:10], 1)]
    await safe_answer(message, f"{title}\n" + "\n".join(lines))

# ==========================================
# 🎲 РУЛЕТКА
# ==========================================
@dp.message(Command("random"))
async def random_game(m: Message):
    if not check_limit(m.from_user.id):
        return await safe_answer(m, f"❌ Лимит ({DAILY_LIMIT} раз в день). VIP — без лимита: /shop")
    await safe_answer(m, "🎲 Крутим...")
    games = await api_games({"page": random.randint(1, 50), "ordering": "-rating"})
    if not games:
        return await safe_answer(m, "Ошибка. Попробуй ещё раз.")
    await send_game(m.chat.id, random.choice(games), m.from_user.id)

# ==========================================
# 🛒 МАГАЗИН И ОПЛАТА
# ==========================================
@dp.message(Command("shop"))
async def shop(m: Message):
    if is_user_vip(m.from_user.id):
        return await safe_answer(m, "⭐ У тебя уже есть VIP!")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Купить за 20 ⭐ ({VIP_DAYS} дней)", callback_data="buy_vip")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]])
    await safe_answer(m, "🛒 <b>VIP:</b> безлимитный поиск, рулетка, избранное.\nЦена: <b>20 ⭐</b>", reply_markup=kb)

@dp.callback_query(F.data == "buy_vip")
async def send_invoice(cb: CallbackQuery):
    prices = [LabeledPrice(label="VIP", amount=20)]
    try:
        await cb.message.answer_invoice(title="VIP", description="Безлимитный поиск и избранное",
                                        payload=SECRET_PAYLOAD, provider_token="",
                                        currency="XTR", prices=prices)
    except Exception:
        logging.exception("Ошибка инвойса")
    await cb.answer()

@dp.pre_checkout_query()
async def process_pre_checkout(q: PreCheckoutQuery):
    await q.answer(ok=True)

@dp.message(F.successful_payment)
async def success_payment(m: Message):
    if m.successful_payment.invoice_payload != SECRET_PAYLOAD:
        return await safe_answer(m, "❌ Ошибка.")
    until = (datetime.now() + timedelta(days=VIP_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_vip = 0, vip_until = ? WHERE user_id = ?",
                   (until, m.from_user.id))
    conn.commit()
    conn.close()
    await safe_answer(m, f"🎉 <b>Оплата прошла! VIP активен до {until[:10]}.</b>")

# ==========================================
# ❤️ ИЗБРАННОЕ
# ==========================================
@dp.callback_query(F.data.startswith("fav:"))
async def add_to_fav(cb: CallbackQuery):
    if not is_user_vip(cb.from_user.id):
        return await cb.answer("❌ Только для VIP!", show_alert=True)
    slug = cb.data.split(":", 1)[1]
    name, url = GAME_CACHE.get(slug, (None, None))
    if not name:
        return await cb.answer("Не удалось сохранить, попробуй ещё раз.", show_alert=True)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM favorites WHERE user_id = ? AND game_url = ?", (cb.from_user.id, url))
    if cursor.fetchone():
        conn.close()
        return await cb.answer("Уже в избранном!", show_alert=True)
    cursor.execute("INSERT INTO favorites (user_id, game_name, game_url) VALUES (?, ?, ?)",
                   (cb.from_user.id, name, url))
    conn.commit()
    conn.close()
    await cb.answer("❤️ Добавлено!")

@dp.message(Command("favorites"))
async def show_favorites(m: Message):
    if not is_user_vip(m.from_user.id):
        return await safe_answer(m, "❌ Только для VIP. Оформить: /shop")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT game_name, game_url FROM favorites WHERE user_id = ?", (m.from_user.id,))
    favs = cursor.fetchall()
    conn.close()
    if not favs:
        return await safe_answer(m, "❤️ Пока пусто.")
    text = "❤️ <b>Избранное:</b>\n" + "\n".join(
        [f"• <a href='{esc(f[1])}'>{esc(f[0])}</a>" for f in favs])
    await safe_answer(m, text)

# ==========================================
# 🧩 ВИКТОРИНА
# ==========================================
active_games: Dict[int, dict] = {}

@dp.message(Command("game"))
async def start_game(m: Message):
    if not check_limit(m.from_user.id):
        return await safe_answer(m, f"❌ Лимит ({DAILY_LIMIT} раз в день). VIP — без лимита: /shop")
    games = await api_games({"page": random.randint(1, 10), "ordering": "-rating", "page_size": 20})
    if not games:
        return await safe_answer(m, "Ошибка. Попробуй ещё раз.")
    g = random.choice(games)
    genres = g.get("genres") or [{}]
    active_games[m.from_user.id] = {
        "name": g.get("name") or "?",
        "genre": (genres[0] or {}).get("name", "?"),
        "year": (g.get("released") or "?")[:4]}
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💡 Жанр", callback_data="hint:1"),
         InlineKeyboardButton(text="💡 Год", callback_data="hint:2")],
        [InlineKeyboardButton(text="🏳️ Сдаться", callback_data="give_up")]])
    await safe_answer(m, "🧩 <b>Угадай игру!</b>\nПиши название в чат. Подсказки — кнопками ниже.")

@dp.callback_query(F.data.startswith("hint:"))
async def game_hint(cb: CallbackQuery):
    gd = active_games.get(cb.from_user.id)
    if not gd:
        return await cb.answer("Начни заново: /game", show_alert=True)
    hint = f"Жанр: {gd['genre']}" if cb.data == "hint:1" else f"Год: {gd['year']}"
    await cb.answer(hint, show_alert=True)

@dp.callback_query(F.data == "give_up")
async def give_up(cb: CallbackQuery):
    gd = active_games.pop(cb.from_user.id, None)
    if gd:
        try:
            await cb.message.edit_text(f"🏳️ Это была: <b>{esc(gd['name'])}</b>", parse_mode="HTML")
        except Exception:
            pass
    await cb.answer()

# ==========================================
# ⚙️ НАСТРОЙКИ
# ==========================================
@dp.message(Command("settings"))
async def settings(m: Message):
    ensure_user(m.from_user.id, m.from_user.username, m.from_user.first_name)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT recs_enabled FROM users WHERE user_id = ?", (m.from_user.id,))
    row = cursor.fetchone()
    conn.close()
    status = "Вкл ✅" if (row and row[0]) else "Выкл ❌"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Рекомендации: {status}", callback_data="set_recs")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]])
    await safe_answer(m, "⚙️ <b>Настройки</b>", reply_markup=kb)

@dp.callback_query(F.data == "set_recs")
async def toggle_recs(cb: CallbackQuery):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT recs_enabled FROM users WHERE user_id = ?", (cb.from_user.id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return await cb.answer("Сначала нажми /start", show_alert=True)
    val = 0 if row[0] else 1
    cursor.execute("UPDATE users SET recs_enabled = ? WHERE user_id = ?", (val, cb.from_user.id))
    conn.commit()
    conn.close()
    await cb.answer(f"Рекомендации: {'Вкл' if val else 'Выкл'} ✅")

# ==========================================
# ✉️ ОТЗЫВЫ И АДМИНКА
# ==========================================
active_feedback = set()
admin_authorized = {}
admin_states = {}

@dp.message(Command("support"))
async def support(m: Message):
    active_feedback.add(m.from_user.id)
    await safe_answer(m, "✍️ <b>Напиши отзыв (/cancel_find — отмена):</b>")

@dp.message(Command("admin"))
async def admin_login(m: Message):
    if m.from_user.id != ADMIN_ID:
        return
    auth = admin_authorized.get(m.from_user.id)
    if isinstance(auth, float) and time.time() - auth < 900:
        await show_admin_panel(m)
    else:
        await safe_answer(m, "🔐 <b>Пароль:</b>")
        admin_authorized[m.from_user.id] = "waiting"

@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text(m: Message):
    uid = m.from_user.id

    # 1. Вход в админку
    if uid == ADMIN_ID and admin_authorized.get(uid) == "waiting":
        if m.text == ADMIN_PASSWORD:
            admin_authorized[uid] = time.time()
            await safe_answer(m, "✅ Верно!")
            await show_admin_panel(m)
        else:
            await safe_answer(m, "❌ Неверно. /admin")
            admin_authorized[uid] = None
        return

    # 2. Ожидание ID от админа
    if uid == ADMIN_ID and admin_states.get(uid):
        state = admin_states[uid]
        if state == "waiting_helper_id":
            try:
                helper_id = int(m.text.strip())
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET is_helper = 1 WHERE user_id = ?", (helper_id,))
                conn.commit()
                conn.close()
                await safe_answer(m, f"✅ {helper_id} — хэлпер!")
            except ValueError:
                await safe_answer(m, "❌ Нужен ID (цифры).")
        elif state == "waiting_vip_id":
            try:
                vip_id = int(m.text.strip())
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET is_vip = 1, vip_until = NULL WHERE user_id = ?", (vip_id,))
                conn.commit()
                conn.close()
                await safe_answer(m, f"✅ {vip_id} — вечный VIP!")
            except ValueError:
                await safe_answer(m, "❌ Нужен ID (цифры).")
        admin_states[uid] = None
        return

    # 3. Поиск по названию
    st = find_state.get(uid)
    if st:
        if not check_limit(uid):
            find_state.pop(uid, None)
            return await safe_answer(m, f"❌ Лимит на сегодня исчерпан. VIP — без лимита: /shop")
        await safe_answer(m, "⏳ Ищу...")
        st["query"] = m.text.strip()
        st["offset"] = 0
        await run_search(m, uid, st["query"], 0)
        return

    # 4. Ответ в викторине
    gd = active_games.get(uid)
    if gd:
        if m.text.strip().lower() == gd["name"].strip().lower():
            active_games.pop(uid, None)
            await safe_answer(m, f"✅ <b>Угадал!</b> Это была «{esc(gd['name'])}». Ещё раз: /game")
        else:
            await safe_answer(m, "❌ Не то. Ещё попытку? Или 🏳️ — кнопка под вопросом.")
        return

    # 5. Отзыв
    if uid in active_feedback:
        conn = get_db()
        cursor = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        cursor.execute("INSERT INTO feedback (user_id, username, text, date) VALUES (?, ?, ?, ?)",
                       (uid, m.from_user.username, m.text, now))
        conn.commit()
        conn.close()
        active_feedback.discard(uid)
        await safe_answer(m, "✅ Спасибо за отзыв!")
        try:
            await bot.send_message(ADMIN_ID, f"📬 От @{m.from_user.username}:\n{m.text}")
        except Exception:
            pass

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
        [InlineKeyboardButton(text="❌ Выйти", callback_data="cancel")]])
    await safe_answer(m, f"📊 <b>АДМИНКА</b>\n👥 Юзеров: {total}", reply_markup=kb)

@dp.callback_query(F.data == "admin_maint_menu")
async def admin_maint_menu(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Выкл", callback_data="maint_0")],
        [InlineKeyboardButton(text="🔴 1 час", callback_data="maint_1")],
        [InlineKeyboardButton(text="🔴 1 день", callback_data="maint_24")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="admin_back")]])
    try:
        await cb.message.edit_text("🛠 <b>Режим ТО:</b>", reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass
    await cb.answer()

@dp.callback_query(F.data.startswith("maint_"))
async def set_maintenance(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    hours = int(cb.data.split("_")[1])
    if hours == 0:
        set_setting("maintenance_until", "0")
    else:
        set_setting("maintenance_until", str(int(time.time()) + hours * 3600))
    await cb.answer("Ок!")
    await show_admin_panel(cb.message)

@dp.callback_query(F.data == "admin_break_menu")
async def admin_break_menu(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Выкл", callback_data="break_0")],
        [InlineKeyboardButton(text="🟠 Вкл", callback_data="break_1")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="admin_back")]])
    try:
        await cb.message.edit_text("☕ <b>Перерыв:</b>", reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass
    await cb.answer()

@dp.callback_query(F.data.startswith("break_"))
async def set_break(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    set_setting("break_mode", cb.data.split("_")[1])
    await cb.answer("Ок!")
    await show_admin_panel(cb.message)

@dp.callback_query(F.data == "admin_give_vip")
async def admin_vip(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    admin_states[cb.from_user.id] = "waiting_vip_id"
    await cb.message.answer("Отправь ID юзера для вечного VIP:")
    await cb.answer()

@dp.callback_query(F.data == "admin_helpers_menu")
async def admin_helpers_menu(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username FROM users WHERE is_helper = 1")
    helpers = cursor.fetchall()
    conn.close()
    text = "👑 <b>Хэлперы:</b>\n" + "\n".join(
        [f"@{h[1]} — <code>{h[0]}</code>" for h in helpers]) if helpers else "👑 Пусто."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить", callback_data="admin_add_helper")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="admin_back")]])
    try:
        await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass
    await cb.answer()

@dp.callback_query(F.data == "admin_add_helper")
async def admin_add_helper(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    admin_states[cb.from_user.id] = "waiting_helper_id"
    await cb.message.answer("Отправь ID:")
    await cb.answer()

@dp.callback_query(F.data == "admin_back")
async def admin_back(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    await show_admin_panel(cb.message)
    await cb.answer()

@dp.callback_query(F.data == "admin_feedback")
async def admin_feedback(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT username, text FROM feedback ORDER BY id DESC LIMIT 5")
    fb = cursor.fetchall()
    conn.close()
    text = "📬 <b>Отзывы:</b>\n" + "\n".join([f"@{f[0]}: {esc(f[1])}" for f in fb]) if fb else "📬 Пусто."
    await cb.message.answer(text, parse_mode="HTML", disable_web_page_preview=True)
    await cb.answer()

@dp.callback_query(F.data == "cancel")
async def cancel_action(cb: CallbackQuery):
    try:
        await cb.message.edit_text("❌ Действие отменено. Меню: /start")
    except Exception:
        pass
    await cb.answer()

@dp.message(Command("helper"))
async def helper_panel(m: Message):
    if not is_user_helper(m.from_user.id) and m.from_user.id != ADMIN_ID:
        return
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT username, text FROM feedback ORDER BY id DESC LIMIT 5")
    fb = cursor.fetchall()
    conn.close()
    text = "👑 <b>Хэлпер:</b>\n" + "\n".join([f"@{f[0]}: {esc(f[1])}" for f in fb]) if fb else "Нет отзывов."
    await safe_answer(m, text)

async def main():
    if not TOKEN or not RAWG_KEY:
        raise SystemExit("Задай переменные окружения TOKEN и RAWG_KEY!")
    await set_commands()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
