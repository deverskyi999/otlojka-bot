import asyncio
import logging
import os
import random
import re
import traceback
from datetime import datetime, timedelta

import aiosqlite
from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ContentType
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, LabeledPrice, PreCheckoutQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# =============================================================================
# КОНФИГ
# =============================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "minigames.db")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("minigames")

# =============================================================================
# НАСТРОЙКИ ПО УМОЛЧАНИЮ (всё это редактируется из админ-панели)
# =============================================================================
DEFAULT_SETTINGS = {
    "currency_name": "лирчики",
    "roulette_double_multiplier": "1.7",
    "roulette_triple_multiplier": "2.0",
    "roulette_777_multiplier": "4.0",
    "mines_bomb_count": "5",
    "mines_step_multiplier": "1.5",
    "daily_amount": "1000000",
    "daily_cooldown_minutes": "60",
    "vip_price_stars": "50",
    "vip_daily_multiplier": "1.5",
    "rocket_max_multiplier": "20.0",
    "start_balance": "1000000",
}

DEFAULT_TEXTS = {
    "welcome": "Привет! Это бот мини-игр.\nНапиши хелп, чтобы увидеть список команд.",
    "help": (
        "Доступные команды:\n\n"
        "рулетка <сумма> — например: рулетка 100кк\n"
        "ракетка <сумма> — например: ракетка 1ккк\n"
        "мины <сумма> — например: мины 50к\n"
        "майн <сумма или макс> — например: майн 200кк, либо майн макс (ставка на весь баланс)\n"
        "пер <сумма> (ответом на сообщение) — перевод игроку\n"
        "кнб <сумма> (ответом на сообщение) — камень-ножницы-бумага с игроком\n"
        "ежедневка — забрать бесплатный бонус\n"
        "баланс — посмотреть баланс\n"
        "/buy — оформить VIP\n\n"
        "Суммы можно писать сокращённо: к = тысяча, кк = миллион, ккк = миллиард."
    ),
    "balance": "Ваш баланс: {balance} {currency}",
    "insufficient_balance": "Недостаточно {currency}. Ваш баланс: {balance} {currency}",
    "bad_amount": "Не понял сумму. Пример: рулетка 100кк",
    "banned": "Вы забанены и не можете пользоваться ботом.",

    "roulette_result_double": "🎰 {symbols}\nДва одинаковых символа {symbol}!\nВыигрыш: {win} {currency} (x{multiplier})",
    "roulette_result_triple": "🎰 {symbols}\nТри одинаковых символа {symbol}!\nВыигрыш: {win} {currency} (x{multiplier})",
    "roulette_result_777": "🎰 {symbols}\nДЖЕКПОТ! Три семёрки!\nВыигрыш: {win} {currency} (x{multiplier})",
    "roulette_lose": "🎰 {symbols}\nНе повезло. Вы проиграли {amount} {currency}",

    "rocket_running": "🚀 Ракетка летит...\nСтавка: {amount} {currency}\nМножитель: x{multiplier}",
    "rocket_cashout": "✅ Забрали на x{multiplier}!\nВыигрыш: {win} {currency}",
    "rocket_crash": "💥 Крашнулось на x{multiplier}!\nВы проиграли {amount} {currency}",

    "mines_board": "💣 Мины\nСтавка: {amount} {currency}\nТекущий множитель: x{multiplier}",
    "mines_boom": "💥 БУМ! Это была мина.\nВы проиграли {amount} {currency}",
    "mines_cashout": "✅ Забрали x{multiplier}!\nВыигрыш: {win} {currency}",

    "mine_board": "⛏️ Майн\nСтавка: {amount} {currency}\nТекущий множитель: x{multiplier}",
    "mine_boom": "💥 Вы наткнулись на бомбу.\nВы проиграли {amount} {currency}",
    "mine_cashout": "✅ Забрали x{multiplier}!\nВыигрыш: {win} {currency}",

    "daily_bonus": "🎁 Вы получили {amount} {currency}!\nСледующий бонус можно будет забрать через {cooldown} мин.",
    "daily_cooldown": "Бонус уже получен. Попробуйте через {remaining}.",

    "transfer_success": "✅ Перевели {amount} {currency} игроку {target}",
    "transfer_fail_balance": "Недостаточно {currency} для перевода.",
    "transfer_fail_self": "Нельзя переводить самому себе.",

    "rps_invite": "{from_user} вызывает {to_user} на камень-ножницы-бумагу на {amount} {currency}!",
    "rps_declined": "{to_user} отклонил(а) игру.",
    "rps_expired": "Игра отменена — истекло время ожидания.",
    "rps_waiting": "Выбор принят, ждём второго игрока...",
    "rps_result_win": "Камень-ножницы-бумага:\n{from_user}: {from_choice}\n{to_user}: {to_choice}\n\nПобедил {winner}! Выигрыш: {amount} {currency}",
    "rps_result_draw": "Камень-ножницы-бумага:\n{from_user}: {from_choice}\n{to_user}: {to_choice}\n\nНичья! Ставки возвращены.",

    "vip_offer": "👑 VIP статус\nЦена: {price} ⭐ Stars\n\nЧто даёт VIP:\n— бейдж 👑 в играх\n— бонус x{multiplier} к ежедневной валюте\n\nОплата ниже:",
    "vip_success": "🎉 Поздравляем! Вы получили VIP статус.",
}

DEFAULT_BUTTONS = {
    "cashout": {"label": "Забрать", "style": "success", "custom_emoji_id": None},
    "accept": {"label": "Принять", "style": "success", "custom_emoji_id": None},
    "decline": {"label": "Отклонить", "style": "danger", "custom_emoji_id": None},
    "pay_stars": {"label": "Оплатить", "style": "primary", "custom_emoji_id": None},
    "rock": {"label": "Камень", "style": None, "custom_emoji_id": None},
    "scissors": {"label": "Ножницы", "style": None, "custom_emoji_id": None},
    "paper": {"label": "Бумага", "style": None, "custom_emoji_id": None},
}

ROULETTE_SYMBOLS = ["🍒", "🍋", "🍇", "⭐", "💎", "7️⃣"]

AMOUNT_SUFFIXES = {
    "к": 1_000, "тыс": 1_000,
    "кк": 1_000_000, "млн": 1_000_000,
    "ккк": 1_000_000_000, "млрд": 1_000_000_000,
    "кккк": 1_000_000_000_000, "трлн": 1_000_000_000_000,
}

RPS_EMOJI = {"rock": "🪨", "scissors": "✂️", "paper": "📄"}
RPS_BEATS = {"rock": "scissors", "scissors": "paper", "paper": "rock"}

# --- игра "Майн" (шахта 5x5) ---
# Типы ячеек. multiplier — во сколько раз умножается текущий множитель выигрыша
# при открытии клетки этого типа. bomb = проигрыш.
MINE_CELL_TYPES = ["bomb", "diamond", "netherite", "iron", "copper", "stone"]

DEFAULT_MINE_CELLS = {
    "bomb":      {"emoji": "💣", "custom_emoji_id": None, "multiplier": "0",    "count": "5"},
    "diamond":   {"emoji": "💎", "custom_emoji_id": None, "multiplier": "5",    "count": "1"},
    "netherite": {"emoji": "🟪", "custom_emoji_id": None, "multiplier": "10",   "count": "1"},
    "iron":      {"emoji": "⛓️", "custom_emoji_id": None, "multiplier": "1.98", "count": "2"},
    "copper":    {"emoji": "🟠", "custom_emoji_id": None, "multiplier": "1.58", "count": "3"},
    # камень — нейтральная клетка (x1, не проигрыш и не выигрыш), count не задаётся,
    # он всегда занимает все оставшиеся клетки поля 5x5 (25 - остальные типы)
    "stone":     {"emoji": "⬜", "custom_emoji_id": None, "multiplier": "1",    "count": "0"},
}

MINE_BOARD_SIZE = 25  # 5x5


# =============================================================================
# БАЗА ДАННЫХ
# =============================================================================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            balance INTEGER NOT NULL DEFAULT 0,
            banned INTEGER NOT NULL DEFAULT 0,
            vip INTEGER NOT NULL DEFAULT 0,
            last_daily TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS texts (
            key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS buttons (
            key TEXT PRIMARY KEY, label TEXT NOT NULL,
            style TEXT, custom_emoji_id TEXT)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS error_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurred_at TEXT DEFAULT CURRENT_TIMESTAMP,
            error_text TEXT)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS mine_cells (
            type TEXT PRIMARY KEY,
            emoji TEXT NOT NULL,
            custom_emoji_id TEXT,
            multiplier TEXT NOT NULL,
            count TEXT NOT NULL)""")
        await db.commit()
        for key, value in DEFAULT_SETTINGS.items():
            await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
        for key, value in DEFAULT_TEXTS.items():
            await db.execute("INSERT OR IGNORE INTO texts (key, value) VALUES (?, ?)", (key, value))
        for key, data in DEFAULT_BUTTONS.items():
            await db.execute(
                "INSERT OR IGNORE INTO buttons (key, label, style, custom_emoji_id) VALUES (?, ?, ?, ?)",
                (key, data["label"], data["style"], data["custom_emoji_id"]))
        for cell_type, data in DEFAULT_MINE_CELLS.items():
            await db.execute(
                "INSERT OR IGNORE INTO mine_cells (type, emoji, custom_emoji_id, multiplier, count) "
                "VALUES (?, ?, ?, ?, ?)",
                (cell_type, data["emoji"], data["custom_emoji_id"], data["multiplier"], data["count"]))
        await db.commit()


# --- настройки ---
_settings_cache = {}


async def get_setting(key: str) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cur.fetchone()
        return row[0] if row else DEFAULT_SETTINGS.get(key, "")


async def get_setting_float(key: str) -> float:
    return float(await get_setting(key))


async def get_setting_int(key: str) -> int:
    return int(float(await get_setting(key)))


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        await db.commit()


async def get_all_settings():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT key, value FROM settings")
        return await cur.fetchall()


# --- тексты ---
async def get_text(key: str, **kwargs) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM texts WHERE key = ?", (key,))
        row = await cur.fetchone()
    template = row[0] if row else DEFAULT_TEXTS.get(key, key)
    currency = kwargs.pop("currency", None) or await get_setting("currency_name")
    try:
        return template.format(currency=currency, **kwargs)
    except Exception:
        return template


async def set_text(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO texts (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        await db.commit()


async def get_all_texts():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT key, value FROM texts")
        return await cur.fetchall()


# --- кнопки (текст + цвет + premium-эмодзи) ---
async def get_button(key: str) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT label, style, custom_emoji_id FROM buttons WHERE key = ?", (key,))
        row = await cur.fetchone()
        if row:
            return {"label": row[0], "style": row[1], "custom_emoji_id": row[2]}
        d = DEFAULT_BUTTONS.get(key, {"label": key, "style": None, "custom_emoji_id": None})
        return dict(d)


async def set_button(key: str, label: str = None, style: str = None, clear_style: bool = False,
                      custom_emoji_id: str = None, clear_emoji: bool = False):
    current = await get_button(key)
    new_label = label if label is not None else current["label"]
    new_style = None if clear_style else (style if style is not None else current["style"])
    new_emoji = None if clear_emoji else (custom_emoji_id if custom_emoji_id is not None else current["custom_emoji_id"])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO buttons (key, label, style, custom_emoji_id) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET label=excluded.label, style=excluded.style, "
            "custom_emoji_id=excluded.custom_emoji_id",
            (key, new_label, new_style, new_emoji))
        await db.commit()


async def get_all_buttons():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT key, label, style, custom_emoji_id FROM buttons")
        return await cur.fetchall()


async def button_kwargs(key: str, **extra) -> dict:
    btn = await get_button(key)
    kwargs = {"text": btn["label"]}
    if btn["style"]:
        kwargs["style"] = btn["style"]
    if btn["custom_emoji_id"]:
        kwargs["icon_custom_emoji_id"] = btn["custom_emoji_id"]
    kwargs.update(extra)
    return kwargs


# --- ячейки игры "Майн" ---
async def get_mine_cell(cell_type: str) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT emoji, custom_emoji_id, multiplier, count FROM mine_cells WHERE type = ?", (cell_type,))
        row = await cur.fetchone()
        if row:
            return {"emoji": row[0], "custom_emoji_id": row[1], "multiplier": float(row[2]), "count": int(row[3])}
        d = DEFAULT_MINE_CELLS[cell_type]
        return {"emoji": d["emoji"], "custom_emoji_id": d["custom_emoji_id"],
                "multiplier": float(d["multiplier"]), "count": int(d["count"])}


async def get_all_mine_cells() -> dict:
    result = {}
    for cell_type in MINE_CELL_TYPES:
        result[cell_type] = await get_mine_cell(cell_type)
    return result


async def set_mine_cell(cell_type: str, emoji: str = None, custom_emoji_id: str = None,
                         clear_emoji: bool = False, multiplier: float = None, count: int = None):
    current = await get_mine_cell(cell_type)
    new_emoji = emoji if emoji is not None else current["emoji"]
    new_custom = None if clear_emoji else (custom_emoji_id if custom_emoji_id is not None else current["custom_emoji_id"])
    new_mult = multiplier if multiplier is not None else current["multiplier"]
    new_count = count if count is not None else current["count"]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO mine_cells (type, emoji, custom_emoji_id, multiplier, count) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(type) DO UPDATE SET emoji=excluded.emoji, custom_emoji_id=excluded.custom_emoji_id, "
            "multiplier=excluded.multiplier, count=excluded.count",
            (cell_type, new_emoji, new_custom, str(new_mult), str(new_count)))
        await db.commit()


async def build_mine_board() -> list:
    """Возвращает список из 25 типов ячеек (перемешанный) согласно текущим настройкам."""
    cells = await get_all_mine_cells()
    board = []
    for cell_type in ["bomb", "diamond", "netherite", "iron", "copper"]:
        board += [cell_type] * cells[cell_type]["count"]
    stone_needed = max(0, MINE_BOARD_SIZE - len(board))
    board += ["stone"] * stone_needed
    board = board[:MINE_BOARD_SIZE]
    random.shuffle(board)
    return board


# --- пользователи / баланс ---
async def ensure_user(user_id: int, username: str, full_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        if not row:
            start_balance = await get_setting_int("start_balance")
            await db.execute(
                "INSERT INTO users (user_id, username, full_name, balance) VALUES (?, ?, ?, ?)",
                (user_id, username, full_name, start_balance))
        else:
            await db.execute(
                "UPDATE users SET username=?, full_name=? WHERE user_id=?",
                (username, full_name, user_id))
        await db.commit()


async def get_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, username, full_name, balance, banned, vip, last_daily FROM users WHERE user_id = ?",
            (user_id,))
        return await cur.fetchone()


async def get_balance(user_id: int) -> int:
    row = await get_user(user_id)
    return row[3] if row else 0


async def change_balance(user_id: int, delta: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (delta, user_id))
        await db.commit()
        cur = await db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else 0


async def set_banned(user_id: int, banned: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET banned = ? WHERE user_id = ?", (1 if banned else 0, user_id))
        await db.commit()


async def is_banned(user_id: int) -> bool:
    row = await get_user(user_id)
    return bool(row[4]) if row else False


async def set_vip(user_id: int, vip: bool = True):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET vip = ? WHERE user_id = ?", (1 if vip else 0, user_id))
        await db.commit()


async def is_vip(user_id: int) -> bool:
    row = await get_user(user_id)
    return bool(row[5]) if row else False


async def set_last_daily(user_id: int, when: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET last_daily = ? WHERE user_id = ?", (when, user_id))
        await db.commit()


async def find_user_by_id(user_id: int):
    return await get_user(user_id)


async def list_all_user_ids():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users")
        return [row[0] for row in await cur.fetchall()]


async def count_users() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users")
        return (await cur.fetchone())[0]


# --- лог ошибок ---
async def log_error(text: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO error_log (error_text) VALUES (?)", (text[:2000],))
        await db.commit()


async def get_recent_errors(limit: int = 15):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT occurred_at, error_text FROM error_log ORDER BY id DESC LIMIT ?", (limit,))
        return await cur.fetchall()


async def clear_errors():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM error_log")
        await db.commit()


# =============================================================================
# УТИЛИТЫ
# =============================================================================
def parse_amount(raw: str):
    """Парсит суммы вида 100кк, 1.5ккк, 500, 2млрд -> int или None."""
    if not raw:
        return None
    raw = raw.strip().lower().replace(",", ".").replace(" ", "")
    m = re.match(r"^(\d+(?:\.\d+)?)([а-я]*)$", raw)
    if not m:
        return None
    number = float(m.group(1))
    suffix = m.group(2)
    mult = 1
    if suffix:
        mult = AMOUNT_SUFFIXES.get(suffix)
        if mult is None:
            return None
    result = int(number * mult)
    return result if result > 0 else None


def format_amount(amount: int) -> str:
    return f"{amount:,}".replace(",", " ")


def display_name(full_name: str, username: str, vip: bool = False) -> str:
    name = f"@{username}" if username else full_name
    return f"👑{name}" if vip else name


# =============================================================================
# ИГРА "МАЙН" (5x5, шахта с разными типами блоков) — доп. настройки
# =============================================================================
MINE_TILE_KEYS = ["mine_hidden", "mine_bomb", "mine_diamond", "mine_netherite", "mine_iron", "mine_copper", "mine_stone"]

DEFAULT_BUTTONS.update({
    "mine_hidden":    {"label": "❔", "style": None, "custom_emoji_id": None},
    "mine_bomb":      {"label": "💣", "style": "danger", "custom_emoji_id": None},
    "mine_diamond":   {"label": "💎", "style": "primary", "custom_emoji_id": None},
    "mine_netherite": {"label": "🔺", "style": "primary", "custom_emoji_id": None},
    "mine_iron":      {"label": "⚙️", "style": None, "custom_emoji_id": None},
    "mine_copper":    {"label": "🟠", "style": None, "custom_emoji_id": None},
    "mine_stone":     {"label": "⬜", "style": None, "custom_emoji_id": None},
})

DEFAULT_SETTINGS.update({
    "mine_grid_size": "5",
    "mine_bomb_count": "5",
    "mine_diamond_count": "1",
    "mine_netherite_count": "1",
    "mine_iron_count": "2",
    "mine_copper_count": "3",
    "mine_diamond_multiplier": "5.0",
    "mine_netherite_multiplier": "10.0",
    "mine_iron_multiplier": "1.98",
    "mine_copper_multiplier": "1.58",
})

DEFAULT_TEXTS.update({
    "mine_board": "⛏️ Майн\nСтавка: {amount} {currency}\nТекущий множитель: x{multiplier}",
    "mine_boom": "💥 Вы вскрыли бомбу!\nВы проиграли {amount} {currency}",
    "mine_cashout": "✅ Забрали x{multiplier}!\nВыигрыш: {win} {currency}",
})


# =============================================================================
# FSM СОСТОЯНИЯ (только админ-панель, игры работают без FSM через словари в памяти)
# =============================================================================
class AdminBalanceState(StatesGroup):
    waiting_user_id = State()
    waiting_amount = State()


class AdminBanState(StatesGroup):
    waiting_user_id = State()


class AdminTextState(StatesGroup):
    waiting_value = State()


class AdminButtonState(StatesGroup):
    waiting_label = State()
    waiting_emoji = State()


class AdminSettingState(StatesGroup):
    waiting_value = State()


# =============================================================================
# АКТИВНЫЕ ИГРЫ В ПАМЯТИ (короткоживущие сессии — бомбы/полёт ракетки/КНБ)
# Хранить в памяти достаточно: игра длится секунды-минуты, при перезапуске
# бота активные раунды просто прерываются (это ок для мини-игр на фантики).
# =============================================================================
ACTIVE_MINES: dict[int, dict] = {}      # message_id -> state ("мины" 6x6)
ACTIVE_MINE_GAME: dict[int, dict] = {}  # message_id -> state ("майн" 5x5)
ACTIVE_ROCKET: dict[int, dict] = {}     # message_id -> state
PENDING_RPS: dict[str, dict] = {}       # request_id -> state
PENDING_RPS_COUNTER = 0
PENDING_TRANSFER_LOCK = asyncio.Lock()
PENDING_BALANCE_LOCK = asyncio.Lock()
PENDING_VIP_INVOICES: dict[str, int] = {}  # payload -> user_id
PROCESSED_PAYMENT_CHARGE_IDS: set[str] = set()


# =============================================================================
# КЛАВИАТУРЫ
# =============================================================================
async def cashout_kb(callback_data: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(**await button_kwargs("cashout", callback_data=callback_data))
    return builder.as_markup()


async def rps_invite_kb(request_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(**await button_kwargs("accept", callback_data=f"rps_accept:{request_id}"))
    builder.button(**await button_kwargs("decline", callback_data=f"rps_decline:{request_id}"))
    builder.adjust(2)
    return builder.as_markup()


async def rps_choice_kb(request_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(**await button_kwargs("rock", callback_data=f"rps_choice:{request_id}:rock"))
    builder.button(**await button_kwargs("scissors", callback_data=f"rps_choice:{request_id}:scissors"))
    builder.button(**await button_kwargs("paper", callback_data=f"rps_choice:{request_id}:paper"))
    builder.adjust(3)
    return builder.as_markup()


async def mines_board_kb(message_id: int) -> InlineKeyboardMarkup:
    state = ACTIVE_MINES[message_id]
    size = state["size"]
    builder = InlineKeyboardBuilder()
    for i in range(size * size):
        if i in state["revealed"]:
            btn_key = "mine_bomb" if i in state["bombs"] else "mine_stone"
            kwargs = await button_kwargs(btn_key, callback_data="noop")
        else:
            kwargs = await button_kwargs("mine_hidden", callback_data=f"mines_click:{message_id}:{i}")
        builder.button(**kwargs)
    builder.adjust(size)
    if state["revealed"]:
        builder.row(InlineKeyboardButton(**await button_kwargs("cashout", callback_data=f"mines_cashout:{message_id}")))
    return builder.as_markup()


TILE_KEY_BY_TYPE = {
    "bomb": "mine_bomb", "diamond": "mine_diamond", "netherite": "mine_netherite",
    "iron": "mine_iron", "copper": "mine_copper", "stone": "mine_stone",
}


async def mine_game_board_kb(message_id: int) -> InlineKeyboardMarkup:
    state = ACTIVE_MINE_GAME[message_id]
    size = state["size"]
    builder = InlineKeyboardBuilder()
    for i in range(size * size):
        if i in state["revealed"]:
            tile_type = state["grid"][i]
            kwargs = await button_kwargs(TILE_KEY_BY_TYPE[tile_type], callback_data="noop")
        else:
            kwargs = await button_kwargs("mine_hidden", callback_data=f"mine_click:{message_id}:{i}")
        builder.button(**kwargs)
    builder.adjust(size)
    if state["revealed"]:
        builder.row(InlineKeyboardButton(**await button_kwargs("cashout", callback_data=f"mine_cashout:{message_id}")))
    return builder.as_markup()


def style_choice_kb(prefix: str, key: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Синий", callback_data=f"{prefix}:style:{key}:primary")
    builder.button(text="Зелёный", callback_data=f"{prefix}:style:{key}:success")
    builder.button(text="Красный", callback_data=f"{prefix}:style:{key}:danger")
    builder.button(text="Без цвета", callback_data=f"{prefix}:style:{key}:none")
    builder.adjust(2)
    return builder.as_markup()


def extract_custom_emoji_id(message: Message):
    entities = message.entities or message.caption_entities or []
    for e in entities:
        if e.type == "custom_emoji" and getattr(e, "custom_emoji_id", None):
            return e.custom_emoji_id
    return None


# =============================================================================
# ИГРОВАЯ ЛОГИКА
# =============================================================================
async def spin_roulette():
    symbols = [random.choice(ROULETTE_SYMBOLS) for _ in range(3)]
    counts = {s: symbols.count(s) for s in set(symbols)}
    top_symbol, top_count = max(counts.items(), key=lambda kv: kv[1])

    if top_count == 3 and top_symbol == "7️⃣":
        mult = await get_setting_float("roulette_777_multiplier")
        return symbols, mult, "777"
    if top_count == 3:
        mult = await get_setting_float("roulette_triple_multiplier")
        return symbols, mult, "triple"
    if top_count == 2:
        mult = await get_setting_float("roulette_double_multiplier")
        return symbols, mult, "double"
    return symbols, 0.0, "lose"


def generate_crash_point(max_multiplier: float) -> float:
    # Экспоненциальное распределение с перекосом в сторону низких множителей —
    # типичная модель для краш-игр. house edge регулируется max_multiplier.
    r = random.random()
    point = 1.0 / (1.0 - r * 0.97)
    return round(min(point, max_multiplier), 2)


def generate_mines_grid(size: int, bomb_count: int) -> set:
    total = size * size
    bomb_count = min(bomb_count, total - 1)
    return set(random.sample(range(total), bomb_count))


def generate_mine_game_grid(size: int, counts: dict) -> list:
    total = size * size
    grid = ["stone"] * total
    positions = list(range(total))
    random.shuffle(positions)
    idx = 0
    for tile_type, count in counts.items():
        for _ in range(count):
            if idx >= total:
                break
            grid[positions[idx]] = tile_type
            idx += 1
    return grid


async def credit_win(user_id: int, amount: int) -> int:
    return await change_balance(user_id, amount)


async def debit_bet(user_id: int, amount: int) -> bool:
    """Атомарно списывает ставку, если хватает средств. True если получилось."""
    async with PENDING_BALANCE_LOCK:
        balance = await get_balance(user_id)
        if balance < amount:
            return False
        await change_balance(user_id, -amount)
        return True


# =============================================================================
# ТРИГГЕРЫ-КОМАНДЫ (слова, на которые реагирует бот в чате)
# Специально не однобуквенные — чтобы не путать со случайным текстом.
# =============================================================================
TRIGGER_ROULETTE = "рулетка"
TRIGGER_ROCKET = "ракетка"
TRIGGER_MINES = "мины"
TRIGGER_MINEGAME = "майн"
TRIGGER_TRANSFER = "пер"       # было "п" -> теперь "пер" (перевод)
TRIGGER_RPS = "кнб"
TRIGGER_DAILY = ("ежедневка", "бонус")
TRIGGER_HELP = ("хелп", "help", "помощь")
TRIGGER_BALANCE = ("баланс", "balance")


# =============================================================================
# РОУТЕР: СТАРТ / ХЕЛП / БАЛАНС
# =============================================================================
common_router = Router()


@common_router.message(CommandStart())
async def cmd_start(message: Message):
    await ensure_user(message.from_user.id, message.from_user.username or "", message.from_user.full_name)
    if await is_banned(message.from_user.id):
        await message.answer(await get_text("banned"))
        return
    await message.answer(await get_text("welcome"))


@common_router.message(F.text.lower().in_(TRIGGER_HELP))
async def cmd_help(message: Message):
    await message.answer(await get_text("help"))


@common_router.message(F.text.lower().in_(TRIGGER_BALANCE))
async def cmd_balance(message: Message):
    await ensure_user(message.from_user.id, message.from_user.username or "", message.from_user.full_name)
    balance = await get_balance(message.from_user.id)
    await message.answer(await get_text("balance", balance=format_amount(balance)))


# =============================================================================
# РОУТЕР: РУЛЕТКА
# =============================================================================
games_router = Router()


@games_router.message(F.text.lower().startswith(TRIGGER_ROULETTE))
async def play_roulette(message: Message):
    user_id = message.from_user.id
    await ensure_user(user_id, message.from_user.username or "", message.from_user.full_name)
    if await is_banned(user_id):
        await message.answer(await get_text("banned"))
        return

    raw = message.text[len(TRIGGER_ROULETTE):].strip()
    amount = parse_amount(raw)
    if amount is None:
        await message.answer(await get_text("bad_amount"))
        return

    ok = await debit_bet(user_id, amount)
    if not ok:
        balance = await get_balance(user_id)
        await message.answer(await get_text("insufficient_balance", balance=format_amount(balance)))
        return

    symbols, mult, kind = await spin_roulette()
    symbols_str = " ".join(symbols)

    if mult <= 0:
        await message.answer(await get_text("roulette_lose", symbols=symbols_str, amount=format_amount(amount)))
        return

    win = int(amount * mult)
    await credit_win(user_id, win)
    key = {"777": "roulette_result_777", "triple": "roulette_result_triple", "double": "roulette_result_double"}[kind]
    await message.answer(await get_text(
        key, symbols=symbols_str, symbol=symbols[0], win=format_amount(win), multiplier=mult))


# =============================================================================
# РОУТЕР: РАКЕТКА (краш-игра)
# =============================================================================
@games_router.message(F.text.lower().startswith(TRIGGER_ROCKET))
async def play_rocket(message: Message, bot: Bot):
    user_id = message.from_user.id
    await ensure_user(user_id, message.from_user.username or "", message.from_user.full_name)
    if await is_banned(user_id):
        await message.answer(await get_text("banned"))
        return

    raw = message.text[len(TRIGGER_ROCKET):].strip()
    amount = parse_amount(raw)
    if amount is None:
        await message.answer(await get_text("bad_amount"))
        return

    ok = await debit_bet(user_id, amount)
    if not ok:
        balance = await get_balance(user_id)
        await message.answer(await get_text("insufficient_balance", balance=format_amount(balance)))
        return

    max_mult = await get_setting_float("rocket_max_multiplier")
    crash_point = generate_crash_point(max_mult)

    sent = await message.answer(
        await get_text("rocket_running", amount=format_amount(amount), multiplier="1.00"),
        reply_markup=await cashout_kb(f"rocket_cashout:{0}"),
    )
    ACTIVE_ROCKET[sent.message_id] = {
        "user_id": user_id, "bet": amount, "current": 1.0,
        "crash_point": crash_point, "cashed": False, "crashed": False,
    }
    kb = await cashout_kb(f"rocket_cashout:{sent.message_id}")
    await bot.edit_message_reply_markup(chat_id=sent.chat.id, message_id=sent.message_id, reply_markup=kb)

    asyncio.create_task(_run_rocket(bot, sent.chat.id, sent.message_id))


async def _run_rocket(bot: Bot, chat_id: int, message_id: int):
    state = ACTIVE_ROCKET.get(message_id)
    if not state:
        return
    try:
        while not state["cashed"] and not state["crashed"]:
            await asyncio.sleep(random.uniform(0.6, 1.1))
            state = ACTIVE_ROCKET.get(message_id)
            if not state or state["cashed"]:
                return
            state["current"] = round(state["current"] + random.uniform(0.03, 0.35) * state["current"], 2)
            if state["current"] >= state["crash_point"]:
                state["crashed"] = True
                amount = state["bet"]
                try:
                    await bot.edit_message_text(
                        await get_text("rocket_crash", multiplier=state["crash_point"], amount=format_amount(amount)),
                        chat_id=chat_id, message_id=message_id,
                    )
                except Exception:
                    pass
                ACTIVE_ROCKET.pop(message_id, None)
                return
            try:
                await bot.edit_message_text(
                    await get_text("rocket_running", amount=format_amount(state["bet"]), multiplier=f"{state['current']:.2f}"),
                    chat_id=chat_id, message_id=message_id,
                    reply_markup=await cashout_kb(f"rocket_cashout:{message_id}"),
                )
            except Exception:
                pass
    except Exception:
        await log_error(f"rocket task error: {traceback.format_exc()}")
        ACTIVE_ROCKET.pop(message_id, None)


@games_router.callback_query(F.data.startswith("rocket_cashout:"))
async def rocket_cashout(call: CallbackQuery):
    message_id = int(call.data.split(":")[1])
    state = ACTIVE_ROCKET.get(message_id)
    if not state:
        await call.answer("Игра уже завершена", show_alert=True)
        return
    if state["user_id"] != call.from_user.id:
        await call.answer("Это не ваша игра", show_alert=True)
        return
    if state["cashed"] or state["crashed"]:
        await call.answer("Уже поздно", show_alert=True)
        return

    state["cashed"] = True
    win = int(state["bet"] * state["current"])
    await credit_win(state["user_id"], win)
    await call.message.edit_text(
        await get_text("rocket_cashout", multiplier=f"{state['current']:.2f}", win=format_amount(win))
    )
    ACTIVE_ROCKET.pop(message_id, None)
    await call.answer()


# =============================================================================
# РОУТЕР: МИНЫ (6x6, только бомбы, x1.5 за безопасную клетку)
# =============================================================================
@games_router.message(F.text.lower().startswith(TRIGGER_MINES + " "))
async def play_mines(message: Message):
    user_id = message.from_user.id
    await ensure_user(user_id, message.from_user.username or "", message.from_user.full_name)
    if await is_banned(user_id):
        await message.answer(await get_text("banned"))
        return

    raw = message.text[len(TRIGGER_MINES):].strip()
    amount = parse_amount(raw)
    if amount is None:
        await message.answer(await get_text("bad_amount"))
        return

    ok = await debit_bet(user_id, amount)
    if not ok:
        balance = await get_balance(user_id)
        await message.answer(await get_text("insufficient_balance", balance=format_amount(balance)))
        return

    size = 6
    bomb_count = 5
    bombs = generate_mines_grid(size, bomb_count)

    sent = await message.answer(await get_text("mines_board", amount=format_amount(amount), multiplier="1.00"))
    ACTIVE_MINES[sent.message_id] = {
        "user_id": user_id, "bet": amount, "size": size, "bombs": bombs,
        "revealed": set(), "multiplier": 1.0, "step": await get_setting_float("mines_step_multiplier"),
    }
    await sent.edit_reply_markup(reply_markup=await mines_board_kb(sent.message_id))


@games_router.callback_query(F.data.startswith("mines_click:"))
async def mines_click(call: CallbackQuery):
    _, message_id_str, idx_str = call.data.split(":")
    message_id, idx = int(message_id_str), int(idx_str)
    state = ACTIVE_MINES.get(message_id)
    if not state:
        await call.answer("Игра уже завершена", show_alert=True)
        return
    if state["user_id"] != call.from_user.id:
        await call.answer("Это не ваша игра", show_alert=True)
        return
    if idx in state["revealed"]:
        await call.answer()
        return

    state["revealed"].add(idx)

    if idx in state["bombs"]:
        amount = state["bet"]
        await call.message.edit_text(await get_text("mines_boom", amount=format_amount(amount)))
        try:
            await call.message.edit_reply_markup(reply_markup=await mines_board_kb(message_id))
        except Exception:
            pass
        ACTIVE_MINES.pop(message_id, None)
        await call.answer()
        return

    state["multiplier"] = round(state["multiplier"] * state["step"], 4)
    await call.message.edit_text(
        await get_text("mines_board", amount=format_amount(state["bet"]), multiplier=f"{state['multiplier']:.2f}")
    )
    await call.message.edit_reply_markup(reply_markup=await mines_board_kb(message_id))
    await call.answer()


@games_router.callback_query(F.data.startswith("mines_cashout:"))
async def mines_cashout(call: CallbackQuery):
    message_id = int(call.data.split(":")[1])
    state = ACTIVE_MINES.get(message_id)
    if not state:
        await call.answer("Игра уже завершена", show_alert=True)
        return
    if state["user_id"] != call.from_user.id:
        await call.answer("Это не ваша игра", show_alert=True)
        return
    if not state["revealed"]:
        await call.answer("Откройте хотя бы одну клетку", show_alert=True)
        return

    win = int(state["bet"] * state["multiplier"])
    await credit_win(state["user_id"], win)
    await call.message.edit_text(await get_text("mines_cashout", multiplier=f"{state['multiplier']:.2f}", win=format_amount(win)))
    ACTIVE_MINES.pop(message_id, None)
    await call.answer()


# =============================================================================
# РОУТЕР: МАЙН (5x5, разные типы блоков, поддержка "майн макс")
# =============================================================================
@games_router.message(F.text.lower().startswith(TRIGGER_MINEGAME + " "))
async def play_minegame(message: Message):
    user_id = message.from_user.id
    await ensure_user(user_id, message.from_user.username or "", message.from_user.full_name)
    if await is_banned(user_id):
        await message.answer(await get_text("banned"))
        return

    raw = message.text[len(TRIGGER_MINEGAME):].strip().lower()
    if raw == "макс":
        amount = await get_balance(user_id)
        if amount <= 0:
            balance = await get_balance(user_id)
            await message.answer(await get_text("insufficient_balance", balance=format_amount(balance)))
            return
    else:
        amount = parse_amount(raw)
        if amount is None:
            await message.answer(await get_text("bad_amount"))
            return

    ok = await debit_bet(user_id, amount)
    if not ok:
        balance = await get_balance(user_id)
        await message.answer(await get_text("insufficient_balance", balance=format_amount(balance)))
        return

    size = await get_setting_int("mine_grid_size")
    counts = {
        "bomb": await get_setting_int("mine_bomb_count"),
        "diamond": await get_setting_int("mine_diamond_count"),
        "netherite": await get_setting_int("mine_netherite_count"),
        "iron": await get_setting_int("mine_iron_count"),
        "copper": await get_setting_int("mine_copper_count"),
    }
    grid = generate_mine_game_grid(size, counts)

    sent = await message.answer(await get_text("mine_board", amount=format_amount(amount), multiplier="1.00"))
    ACTIVE_MINE_GAME[sent.message_id] = {
        "user_id": user_id, "bet": amount, "size": size, "grid": grid,
        "revealed": set(), "multiplier": 1.0,
    }
    await sent.edit_reply_markup(reply_markup=await mine_game_board_kb(sent.message_id))


@games_router.callback_query(F.data.startswith("mine_click:"))
async def mine_click(call: CallbackQuery):
    _, message_id_str, idx_str = call.data.split(":")
    message_id, idx = int(message_id_str), int(idx_str)
    state = ACTIVE_MINE_GAME.get(message_id)
    if not state:
        await call.answer("Игра уже завершена", show_alert=True)
        return
    if state["user_id"] != call.from_user.id:
        await call.answer("Это не ваша игра", show_alert=True)
        return
    if idx in state["revealed"]:
        await call.answer()
        return

    state["revealed"].add(idx)
    tile_type = state["grid"][idx]

    if tile_type == "bomb":
        amount = state["bet"]
        await call.message.edit_text(await get_text("mine_boom", amount=format_amount(amount)))
        try:
            await call.message.edit_reply_markup(reply_markup=await mine_game_board_kb(message_id))
        except Exception:
            pass
        ACTIVE_MINE_GAME.pop(message_id, None)
        await call.answer()
        return

    if tile_type != "stone":
        setting_key = f"mine_{tile_type}_multiplier"
        tile_mult = await get_setting_float(setting_key)
        state["multiplier"] = round(state["multiplier"] * tile_mult, 4)

    await call.message.edit_text(
        await get_text("mine_board", amount=format_amount(state["bet"]), multiplier=f"{state['multiplier']:.2f}")
    )
    await call.message.edit_reply_markup(reply_markup=await mine_game_board_kb(message_id))
    await call.answer()


@games_router.callback_query(F.data.startswith("mine_cashout:"))
async def mine_cashout(call: CallbackQuery):
    message_id = int(call.data.split(":")[1])
    state = ACTIVE_MINE_GAME.get(message_id)
    if not state:
        await call.answer("Игра уже завершена", show_alert=True)
        return
    if state["user_id"] != call.from_user.id:
        await call.answer("Это не ваша игра", show_alert=True)
        return
    if not state["revealed"]:
        await call.answer("Откройте хотя бы одну клетку", show_alert=True)
        return

    win = int(state["bet"] * state["multiplier"])
    await credit_win(state["user_id"], win)
    await call.message.edit_text(await get_text("mine_cashout", multiplier=f"{state['multiplier']:.2f}", win=format_amount(win)))
    ACTIVE_MINE_GAME.pop(message_id, None)
    await call.answer()


@games_router.callback_query(F.data == "noop")
async def noop_callback(call: CallbackQuery):
    await call.answer()


# =============================================================================
# РОУТЕР: ПЕРЕВОДЫ МЕЖДУ ИГРОКАМИ ("пер <сумма>" ответом на сообщение)
# =============================================================================
@games_router.message(F.text.lower().startswith(TRIGGER_TRANSFER + " "), F.reply_to_message)
async def transfer_money(message: Message):
    sender_id = message.from_user.id
    target = message.reply_to_message.from_user
    if not target:
        return
    await ensure_user(sender_id, message.from_user.username or "", message.from_user.full_name)
    await ensure_user(target.id, target.username or "", target.full_name)

    if await is_banned(sender_id):
        await message.answer(await get_text("banned"))
        return

    if target.id == sender_id:
        await message.answer(await get_text("transfer_fail_self"))
        return

    raw = message.text[len(TRIGGER_TRANSFER):].strip()
    amount = parse_amount(raw)
    if amount is None:
        await message.answer(await get_text("bad_amount"))
        return

    async with PENDING_TRANSFER_LOCK:
        ok = await debit_bet(sender_id, amount)
        if not ok:
            await message.answer(await get_text("transfer_fail_balance"))
            return
        await credit_win(target.id, amount)

    target_name = display_name(target.full_name, target.username, await is_vip(target.id))
    await message.answer(await get_text("transfer_success", amount=format_amount(amount), target=target_name))


# =============================================================================
# РОУТЕР: КНБ ("кнб <сумма>" ответом на сообщение)
# =============================================================================
@games_router.message(F.text.lower().startswith(TRIGGER_RPS + " "), F.reply_to_message)
async def rps_invite(message: Message):
    global PENDING_RPS_COUNTER
    from_user = message.from_user
    target = message.reply_to_message.from_user
    if not target or target.id == from_user.id or target.is_bot:
        return

    await ensure_user(from_user.id, from_user.username or "", from_user.full_name)
    await ensure_user(target.id, target.username or "", target.full_name)

    if await is_banned(from_user.id):
        await message.answer(await get_text("banned"))
        return

    raw = message.text[len(TRIGGER_RPS):].strip()
    amount = parse_amount(raw)
    if amount is None:
        await message.answer(await get_text("bad_amount"))
        return

    balance = await get_balance(from_user.id)
    if balance < amount:
        await message.answer(await get_text("insufficient_balance", balance=format_amount(balance)))
        return

    PENDING_RPS_COUNTER += 1
    request_id = str(PENDING_RPS_COUNTER)
    PENDING_RPS[request_id] = {
        "from_id": from_user.id, "to_id": target.id, "amount": amount,
        "from_name": display_name(from_user.full_name, from_user.username, await is_vip(from_user.id)),
        "to_name": display_name(target.full_name, target.username, await is_vip(target.id)),
        "choices": {}, "status": "pending",
    }

    from_name = PENDING_RPS[request_id]["from_name"]
    to_name = PENDING_RPS[request_id]["to_name"]
    await message.answer(
        await get_text("rps_invite", from_user=from_name, to_user=to_name, amount=format_amount(amount)),
        reply_markup=await rps_invite_kb(request_id),
    )


@games_router.callback_query(F.data.startswith("rps_decline:"))
async def rps_decline(call: CallbackQuery):
    request_id = call.data.split(":")[1]
    req = PENDING_RPS.get(request_id)
    if not req or req["status"] != "pending":
        await call.answer("Запрос уже неактуален", show_alert=True)
        return
    if call.from_user.id != req["to_id"]:
        await call.answer("Это не ваш запрос", show_alert=True)
        return
    req["status"] = "declined"
    await call.message.edit_text(await get_text("rps_declined", to_user=req["to_name"]))
    PENDING_RPS.pop(request_id, None)
    await call.answer()


@games_router.callback_query(F.data.startswith("rps_accept:"))
async def rps_accept(call: CallbackQuery):
    request_id = call.data.split(":")[1]
    req = PENDING_RPS.get(request_id)
    if not req or req["status"] != "pending":
        await call.answer("Запрос уже неактуален", show_alert=True)
        return
    if call.from_user.id != req["to_id"]:
        await call.answer("Это не ваш запрос", show_alert=True)
        return

    balance = await get_balance(req["to_id"])
    if balance < req["amount"]:
        await call.answer("Недостаточно средств", show_alert=True)
        return

    req["status"] = "active"
    await call.message.edit_text(
        f"{req['from_name']} vs {req['to_name']}\nСтавка: {format_amount(req['amount'])} {await get_setting('currency_name')}\n\nВыбирайте:",
        reply_markup=await rps_choice_kb(request_id),
    )
    await call.answer()


@games_router.callback_query(F.data.startswith("rps_choice:"))
async def rps_choice(call: CallbackQuery):
    _, request_id, choice = call.data.split(":")
    req = PENDING_RPS.get(request_id)
    if not req or req["status"] != "active":
        await call.answer("Игра уже завершена", show_alert=True)
        return
    if call.from_user.id not in (req["from_id"], req["to_id"]):
        await call.answer("Это не ваша игра", show_alert=True)
        return
    if call.from_user.id in req["choices"]:
        await call.answer("Вы уже выбрали", show_alert=True)
        return

    req["choices"][call.from_user.id] = choice
    await call.answer(f"Вы выбрали: {RPS_EMOJI[choice]}")

    if len(req["choices"]) < 2:
        return

    from_choice = req["choices"][req["from_id"]]
    to_choice = req["choices"][req["to_id"]]
    amount = req["amount"]

    async with PENDING_TRANSFER_LOCK:
        if from_choice == to_choice:
            await call.message.edit_text(await get_text(
                "rps_result_draw", from_user=req["from_name"], to_user=req["to_name"],
                from_choice=RPS_EMOJI[from_choice], to_choice=RPS_EMOJI[to_choice]))
        else:
            from_wins = RPS_BEATS[from_choice] == to_choice
            winner_id = req["from_id"] if from_wins else req["to_id"]
            loser_id = req["to_id"] if from_wins else req["from_id"]
            winner_name = req["from_name"] if from_wins else req["to_name"]

            ok = await debit_bet(loser_id, amount)
            if ok:
                await credit_win(winner_id, amount)
                win_amount = amount
            else:
                loser_balance = await get_balance(loser_id)
                await debit_bet(loser_id, loser_balance)
                await credit_win(winner_id, loser_balance)
                win_amount = loser_balance

            await call.message.edit_text(await get_text(
                "rps_result_win", from_user=req["from_name"], to_user=req["to_name"],
                from_choice=RPS_EMOJI[from_choice], to_choice=RPS_EMOJI[to_choice],
                winner=winner_name, amount=format_amount(win_amount)))

    PENDING_RPS.pop(request_id, None)


# =============================================================================
# РОУТЕР: ЕЖЕДНЕВНЫЙ БОНУС
# =============================================================================
@games_router.message(F.text.lower().in_(TRIGGER_DAILY))
async def daily_bonus(message: Message):
    user_id = message.from_user.id
    await ensure_user(user_id, message.from_user.username or "", message.from_user.full_name)
    if await is_banned(user_id):
        await message.answer(await get_text("banned"))
        return

    row = await get_user(user_id)
    last_daily = row[6]
    cooldown_minutes = await get_setting_int("daily_cooldown_minutes")

    if last_daily:
        last_dt = datetime.fromisoformat(last_daily)
        elapsed = datetime.utcnow() - last_dt
        remaining = timedelta(minutes=cooldown_minutes) - elapsed
        if remaining.total_seconds() > 0:
            minutes = int(remaining.total_seconds() // 60) + 1
            await message.answer(await get_text("daily_cooldown", remaining=f"{minutes} мин"))
            return

    amount = await get_setting_int("daily_amount")
    if await is_vip(user_id):
        vip_mult = await get_setting_float("vip_daily_multiplier")
        amount = int(amount * vip_mult)

    await credit_win(user_id, amount)
    await set_last_daily(user_id, datetime.utcnow().isoformat())
    await message.answer(await get_text("daily_bonus", amount=format_amount(amount), cooldown=cooldown_minutes))


# =============================================================================
# РОУТЕР: VIP ЗА TELEGRAM STARS
# =============================================================================
payments_router = Router()


@payments_router.message(Command("buy"))
async def cmd_buy(message: Message, bot: Bot):
    user_id = message.from_user.id
    await ensure_user(user_id, message.from_user.username or "", message.from_user.full_name)

    if await is_vip(user_id):
        await message.answer("У вас уже есть VIP статус.")
        return

    price = await get_setting_int("vip_price_stars")
    daily_mult = await get_setting_float("vip_daily_multiplier")
    await message.answer(await get_text("vip_offer", price=price, multiplier=daily_mult))

    payload = f"vip:{user_id}:{datetime.utcnow().timestamp()}"
    PENDING_VIP_INVOICES[payload] = user_id

    await bot.send_invoice(
        chat_id=message.chat.id,
        title="VIP статус",
        description=f"VIP статус: бейдж 👑 и бонус x{daily_mult} к ежедневной валюте",
        payload=payload,
        currency="XTR",
        prices=[LabeledPrice(label="VIP статус", amount=price)],
    )


@payments_router.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery, bot: Bot):
    if pre_checkout_query.invoice_payload not in PENDING_VIP_INVOICES:
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="Счёт не найден")
        return
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@payments_router.message(F.content_type == ContentType.SUCCESSFUL_PAYMENT)
async def successful_payment(message: Message):
    payment = message.successful_payment
    charge_id = payment.telegram_payment_charge_id
    if charge_id in PROCESSED_PAYMENT_CHARGE_IDS:
        return
    PROCESSED_PAYMENT_CHARGE_IDS.add(charge_id)

    user_id = PENDING_VIP_INVOICES.pop(payment.invoice_payload, message.from_user.id)
    await set_vip(user_id, True)
    await message.answer(await get_text("vip_success"))


# =============================================================================
# СЕКРЕТНАЯ АДМИН-ПАНЕЛЬ (доступна только OWNER_ID, в личных сообщениях)
# =============================================================================
admin_router = Router()


def owner_only(func):
    async def wrapper(event, *args, **kwargs):
        user_id = event.from_user.id
        if user_id != OWNER_ID:
            if isinstance(event, CallbackQuery):
                await event.answer()
            return
        return await func(event, *args, **kwargs)
    return wrapper


def admin_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Баланс игрока", callback_data="adm:balance")
    builder.button(text="Бан / разбан", callback_data="adm:ban")
    builder.button(text="Тексты", callback_data="adm:texts")
    builder.button(text="Кнопки и цвета", callback_data="adm:buttons")
    builder.button(text="Настройки игр", callback_data="adm:settings")
    builder.button(text="Статистика", callback_data="adm:stats")
    builder.button(text="Логи ошибок", callback_data="adm:errors")
    builder.adjust(1)
    return builder.as_markup()


def back_admin_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад в админ панель", callback_data="adm:menu")
    return builder.as_markup()


@admin_router.message(Command("admin"), F.chat.type == "private")
async def cmd_admin(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user.id != OWNER_ID:
        return  # молча игнорируем — панель секретная
    await message.answer("Секретная админ-панель", reply_markup=admin_menu_kb())


@admin_router.callback_query(F.data == "adm:menu")
@owner_only
async def adm_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Секретная админ-панель", reply_markup=admin_menu_kb())
    await call.answer()


# --- БАЛАНС ---
@admin_router.callback_query(F.data == "adm:balance")
@owner_only
async def adm_balance_start(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("Отправьте Telegram ID игрока:")
    await state.set_state(AdminBalanceState.waiting_user_id)
    await call.answer()


@admin_router.message(AdminBalanceState.waiting_user_id, F.chat.type == "private")
async def adm_balance_id(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    if not message.text.strip().isdigit():
        await message.answer("ID должен быть числом. Попробуйте ещё раз:")
        return
    user_id = int(message.text.strip())
    row = await get_user(user_id)
    if not row:
        await message.answer("Такой пользователь ещё не запускал бота. Попробуйте другой ID:")
        return
    await state.update_data(user_id=user_id)
    currency = await get_setting("currency_name")
    await message.answer(
        f"Текущий баланс: {format_amount(row[3])} {currency}\n\n"
        f"Отправьте число: положительное — выдать, отрицательное — списать (например: 500000 или -200000):"
    )
    await state.set_state(AdminBalanceState.waiting_amount)


@admin_router.message(AdminBalanceState.waiting_amount, F.chat.type == "private")
async def adm_balance_amount(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    try:
        delta = int(message.text.strip().replace(" ", ""))
    except ValueError:
        await message.answer("Нужно целое число. Попробуйте ещё раз:")
        return
    data = await state.get_data()
    new_balance = await change_balance(data["user_id"], delta)
    await message.answer(f"Готово. Новый баланс: {format_amount(new_balance)}", reply_markup=back_admin_kb())
    await state.clear()


# --- БАН ---
@admin_router.callback_query(F.data == "adm:ban")
@owner_only
async def adm_ban_menu(call: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.button(text="Забанить по ID", callback_data="adm:ban_do:1")
    builder.button(text="Разбанить по ID", callback_data="adm:ban_do:0")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="Назад", callback_data="adm:menu"))
    await call.message.edit_text("Бан / разбан", reply_markup=builder.as_markup())
    await call.answer()


@admin_router.callback_query(F.data.startswith("adm:ban_do:"))
@owner_only
async def adm_ban_start(call: CallbackQuery, state: FSMContext):
    banned = call.data.split(":")[2] == "1"
    await state.update_data(banned=banned)
    await call.message.edit_text("Отправьте Telegram ID игрока:")
    await state.set_state(AdminBanState.waiting_user_id)
    await call.answer()


@admin_router.message(AdminBanState.waiting_user_id, F.chat.type == "private")
async def adm_ban_finish(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    if not message.text.strip().isdigit():
        await message.answer("ID должен быть числом. Попробуйте ещё раз:")
        return
    data = await state.get_data()
    user_id = int(message.text.strip())
    await set_banned(user_id, data["banned"])
    action = "забанен" if data["banned"] else "разбанен"
    await message.answer(f"Пользователь {user_id} {action}.", reply_markup=back_admin_kb())
    await state.clear()


# --- ТЕКСТЫ ---
@admin_router.callback_query(F.data == "adm:texts")
@owner_only
async def adm_texts(call: CallbackQuery):
    texts = await get_all_texts()
    builder = InlineKeyboardBuilder()
    for key, _ in texts:
        builder.button(text=key, callback_data=f"adm:text_edit:{key}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="Назад", callback_data="adm:menu"))
    await call.message.edit_text("Выберите текст (доступны плейсхолдеры вида {amount}, {currency} и т.д. — не удаляйте их):", reply_markup=builder.as_markup())
    await call.answer()


@admin_router.callback_query(F.data.startswith("adm:text_edit:"))
@owner_only
async def adm_text_edit_start(call: CallbackQuery, state: FSMContext):
    key = call.data.split(":", 2)[2]
    current = await get_text(key)
    await state.update_data(key=key)
    await call.message.edit_text(f"[{key}]\n\n{current}\n\nОтправьте новый текст (сохраняйте фигурные скобки {{...}}):")
    await state.set_state(AdminTextState.waiting_value)
    await call.answer()


@admin_router.message(AdminTextState.waiting_value, F.chat.type == "private")
async def adm_text_edit_finish(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    data = await state.get_data()
    await set_text(data["key"], message.text)
    await message.answer("Текст обновлён.", reply_markup=back_admin_kb())
    await state.clear()


# --- КНОПКИ И ЦВЕТА ---
@admin_router.callback_query(F.data == "adm:buttons")
@owner_only
async def adm_buttons(call: CallbackQuery):
    buttons = await get_all_buttons()
    builder = InlineKeyboardBuilder()
    for key, label, style, custom_emoji_id in buttons:
        mark = f" [{STYLE_LABELS_ADMIN.get(style, '')}]" if style else ""
        mark += " [premium]" if custom_emoji_id else ""
        builder.button(text=f"{label}{mark} — {key}", callback_data=f"adm:btn_edit:{key}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="Назад", callback_data="adm:menu"))
    await call.message.edit_text(
        "Кнопки и клетки полей. Меняется подпись, цвет и premium-эмодзи "
        "(нужна Telegram Premium у аккаунта бота).\n\nВыберите:",
        reply_markup=builder.as_markup(),
    )
    await call.answer()


STYLE_LABELS_ADMIN = {"primary": "Синий", "success": "Зелёный", "danger": "Красный"}


@admin_router.callback_query(F.data.startswith("adm:btn_edit:"))
@owner_only
async def adm_btn_edit_start(call: CallbackQuery, state: FSMContext):
    key = call.data.split(":", 2)[2]
    await state.update_data(key=key)
    await call.message.edit_text("Отправьте новую подпись/эмодзи-текст для кнопки:")
    await state.set_state(AdminButtonState.waiting_label)
    await call.answer()


@admin_router.message(AdminButtonState.waiting_label, F.chat.type == "private")
async def adm_btn_label(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    data = await state.get_data()
    await set_button(data["key"], label=message.text.strip())
    await message.answer("Подпись обновлена. Выберите цвет:", reply_markup=style_choice_kb("adm", data["key"]))


@admin_router.callback_query(F.data.startswith("adm:style:"))
@owner_only
async def adm_btn_style(call: CallbackQuery, state: FSMContext):
    _, _, key, style = call.data.split(":")
    if style == "none":
        await set_button(key, clear_style=True)
    else:
        await set_button(key, style=style)
    await state.update_data(key=key)
    await call.message.edit_text(
        "Цвет обновлён. Теперь перешлите сообщение с premium-эмодзи, чтобы поставить его на кнопку, "
        "либо отправьте '-' чтобы оставить без иконки."
    )
    await state.set_state(AdminButtonState.waiting_emoji)
    await call.answer()


@admin_router.message(AdminButtonState.waiting_emoji, F.chat.type == "private")
async def adm_btn_emoji(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    data = await state.get_data()
    if message.text and message.text.strip() == "-":
        await set_button(data["key"], clear_emoji=True)
        await message.answer("Иконка убрана.", reply_markup=back_admin_kb())
        await state.clear()
        return
    emoji_id = extract_custom_emoji_id(message)
    if not emoji_id:
        await message.answer("Не нашёл premium-эмодзи в сообщении. Пришлите сообщение с эмодзи, либо '-' чтобы пропустить.")
        return
    await set_button(data["key"], custom_emoji_id=emoji_id)
    await message.answer("Premium-эмодзи установлен.", reply_markup=back_admin_kb())
    await state.clear()


# --- НАСТРОЙКИ ИГР ---
@admin_router.callback_query(F.data == "adm:settings")
@owner_only
async def adm_settings(call: CallbackQuery):
    settings = await get_all_settings()
    builder = InlineKeyboardBuilder()
    for key, value in settings:
        builder.button(text=f"{key} = {value}", callback_data=f"adm:setting_edit:{key}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="Назад", callback_data="adm:menu"))
    await call.message.edit_text("Настройки игр (множители, кулдауны, цена VIP и т.д.):", reply_markup=builder.as_markup())
    await call.answer()


@admin_router.callback_query(F.data.startswith("adm:setting_edit:"))
@owner_only
async def adm_setting_edit_start(call: CallbackQuery, state: FSMContext):
    key = call.data.split(":", 2)[2]
    current = await get_setting(key)
    await state.update_data(key=key)
    await call.message.edit_text(f"[{key}] = {current}\n\nОтправьте новое значение:")
    await state.set_state(AdminSettingState.waiting_value)
    await call.answer()


@admin_router.message(AdminSettingState.waiting_value, F.chat.type == "private")
async def adm_setting_edit_finish(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    data = await state.get_data()
    await set_setting(data["key"], message.text.strip())
    await message.answer("Настройка обновлена.", reply_markup=back_admin_kb())
    await state.clear()


# --- СТАТИСТИКА ---
@admin_router.callback_query(F.data == "adm:stats")
@owner_only
async def adm_stats(call: CallbackQuery):
    total_users = await count_users()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*), COALESCE(SUM(balance),0) FROM users")
        banned_count_row = await db.execute("SELECT COUNT(*) FROM users WHERE banned = 1")
        vip_count_row = await db.execute("SELECT COUNT(*) FROM users WHERE vip = 1")
        _, total_balance = await cur.fetchone()
        banned_count = (await banned_count_row.fetchone())[0]
        vip_count = (await vip_count_row.fetchone())[0]
    currency = await get_setting("currency_name")
    text = (
        f"Статистика\n\n"
        f"Всего игроков: {total_users}\n"
        f"Забанено: {banned_count}\n"
        f"VIP: {vip_count}\n"
        f"Суммарно {currency} на балансах: {format_amount(total_balance)}\n"
        f"Активных раундов сейчас: рулетка мгновенная, "
        f"ракетка: {len(ACTIVE_ROCKET)}, мины: {len(ACTIVE_MINES)}, майн: {len(ACTIVE_MINE_GAME)}, кнб: {len(PENDING_RPS)}"
    )
    await call.message.edit_text(text, reply_markup=back_admin_kb())
    await call.answer()


# --- ЛОГИ ОШИБОК ---
@admin_router.callback_query(F.data == "adm:errors")
@owner_only
async def adm_errors(call: CallbackQuery):
    errors = await get_recent_errors(15)
    if not errors:
        text = "Ошибок пока не было."
    else:
        lines = [f"{when}\n{err[:300]}" for when, err in errors]
        text = "Последние ошибки:\n\n" + "\n\n".join(lines)
        text = text[:3900]
    builder = InlineKeyboardBuilder()
    builder.button(text="Очистить лог", callback_data="adm:errors_clear")
    builder.row(InlineKeyboardButton(text="Назад", callback_data="adm:menu"))
    await call.message.edit_text(text, reply_markup=builder.as_markup())
    await call.answer()


@admin_router.callback_query(F.data == "adm:errors_clear")
@owner_only
async def adm_errors_clear(call: CallbackQuery):
    await clear_errors()
    await call.answer("Лог очищен", show_alert=True)
    await adm_errors(call)


# =============================================================================
# ГЛОБАЛЬНАЯ ОБРАБОТКА ОШИБОК — бот никогда не падает и не зависает,
# любая ошибка в хендлере логируется и видна в админ-панели.
# =============================================================================
error_router = Router()


@error_router.errors()
async def global_error_handler(event, exception=None):
    exc = exception or getattr(event, "exception", None)
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)) if exc else str(event)
    log.error("Unhandled error: %s", tb)
    try:
        await log_error(tb)
    except Exception:
        pass
    return True  # событие считается обработанным, бот продолжает работу


# =============================================================================
# ЗАПУСК
# =============================================================================
async def main():
    if BOT_TOKEN == "PUT_YOUR_TOKEN_HERE" or not BOT_TOKEN:
        raise SystemExit("Укажите токен бота: переменная окружения BOT_TOKEN")
    if OWNER_ID == 0:
        raise SystemExit("Укажите ваш Telegram ID: переменная окружения OWNER_ID")

    await init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # error_router подключается первым (через dp.errors), остальные — по порядку
    dp.include_router(error_router)
    dp.include_router(admin_router)
    dp.include_router(payments_router)
    dp.include_router(common_router)
    dp.include_router(games_router)

    await bot.delete_webhook(drop_pending_updates=True)
    log.info("Бот запущен")

    # Бесконечный цикл с автоперезапуском polling при сетевых сбоях —
    # чтобы бот никогда не "умирал" насовсем при кратковременных проблемах сети.
    while True:
        try:
            await dp.start_polling(bot)
        except Exception:
            log.exception("Polling упал, перезапуск через 5 секунд")
            try:
                await log_error(f"polling crash: {traceback.format_exc()}")
            except Exception:
                pass
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
