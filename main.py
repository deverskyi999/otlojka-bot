"""
Бот "Каналы для заработка на отзывах".
/start -> меню (Каналы / Предложить свой канал / Поддержка)
Админка доступна только владельцу (OWNER_ID) через /admin.

Весь код нарочно собран в одном файле для простоты деплоя.

Запуск: python main.py
Обязательные переменные окружения: BOT_TOKEN, OWNER_ID
"""
import asyncio
import logging
import os
import time
from typing import Optional

import aiohttp
import aiosqlite
from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, LabeledPrice, PreCheckoutQuery,
    InlineKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("channels_bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "bot.db")

if not BOT_TOKEN or not OWNER_ID:
    raise RuntimeError("Заполни BOT_TOKEN и OWNER_ID в переменных окружения (.env)")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)


def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


# =========================================================
#                    DATABASE (SQLite)
# =========================================================
DEFAULT_SETTINGS = {
    "welcome_text": "Здравствуйте! 👋\n\nЭто бот, где вы можете найти подходящий канал для заработка на отзывах.",
    "btn_channels_text": "📃 Каналы",
    "btn_propose_text": "➕ Предложить свой канал",
    "btn_support_text": "🛠 Поддержка",
    "propose_prompt": "Отправьте одним сообщением ссылку на ваш канал и краткое описание — мы рассмотрим заявку.",
    "propose_thanks": "Спасибо! Заявка отправлена на рассмотрение ✅",
    "support_username": "",
    "crypto_pay_token": "",
    "crypto_asset": "USDT",
}


async def init_db(db_path: str = DB_PATH):
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                description TEXT,
                subscribers TEXT,
                invite_link TEXT,
                is_free INTEGER DEFAULT 1,
                price_stars INTEGER DEFAULT 0,
                price_crypto REAL DEFAULT 0,
                emoji TEXT DEFAULT '',
                custom_emoji_id TEXT DEFAULT '',
                active INTEGER DEFAULT 1,
                created_at INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                info TEXT,
                status TEXT DEFAULT 'pending',
                created_at INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                channel_id INTEGER,
                method TEXT,
                amount REAL,
                currency TEXT,
                status TEXT DEFAULT 'pending',
                invoice_id TEXT,
                created_at INTEGER
            )
        """)
        await db.commit()

        for k, v in DEFAULT_SETTINGS.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v)
            )
        await db.commit()


# ---------- settings ----------
async def get_setting(key: str, default: str = "") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cur.fetchone()
        return row[0] if row else default


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await db.commit()


async def get_all_settings() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT key, value FROM settings")
        rows = await cur.fetchall()
        return {k: v for k, v in rows}


# ---------- users ----------
async def upsert_user(user_id: int, username: str, first_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO users (user_id, username, first_name, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name",
            (user_id, username, first_name, int(time.time())),
        )
        await db.commit()


async def count_users() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users")
        return (await cur.fetchone())[0]


# ---------- channels ----------
async def add_channel(name, description, subscribers, invite_link, is_free,
                       price_stars, price_crypto, emoji, custom_emoji_id) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO channels (name, description, subscribers, invite_link, is_free, "
            "price_stars, price_crypto, emoji, custom_emoji_id, active, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
            (name, description, subscribers, invite_link, int(is_free),
             price_stars, price_crypto, emoji, custom_emoji_id, int(time.time())),
        )
        await db.commit()
        return cur.lastrowid


async def get_channels(active_only=True) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        q = "SELECT * FROM channels"
        if active_only:
            q += " WHERE active=1"
        q += " ORDER BY id DESC"
        cur = await db.execute(q)
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_channel(channel_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM channels WHERE id=?", (channel_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def update_channel_field(channel_id: int, field: str, value):
    allowed = {"name", "description", "subscribers", "invite_link", "is_free",
               "price_stars", "price_crypto", "emoji", "custom_emoji_id", "active"}
    if field not in allowed:
        raise ValueError("bad field")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE channels SET {field}=? WHERE id=?", (value, channel_id))
        await db.commit()


async def delete_channel(channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM channels WHERE id=?", (channel_id,))
        await db.commit()


# ---------- proposals ----------
async def add_proposal(user_id: int, username: str, info: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO proposals (user_id, username, info, created_at) VALUES (?, ?, ?, ?)",
            (user_id, username, info, int(time.time())),
        )
        await db.commit()
        return cur.lastrowid


async def get_proposals(status: str = "pending") -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM proposals WHERE status=? ORDER BY id DESC", (status,))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_proposal(proposal_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def update_proposal_status(proposal_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE proposals SET status=? WHERE id=?", (status, proposal_id))
        await db.commit()


# ---------- payments ----------
async def add_payment(user_id, channel_id, method, amount, currency, invoice_id="", status="pending") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO payments (user_id, channel_id, method, amount, currency, status, invoice_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, channel_id, method, amount, currency, status, invoice_id, int(time.time())),
        )
        await db.commit()
        return cur.lastrowid


async def get_payment(payment_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM payments WHERE id=?", (payment_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def update_payment_status(payment_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE payments SET status=? WHERE id=?", (status, payment_id))
        await db.commit()


async def payments_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM payments WHERE status='paid' AND currency='XTR'")
        stars_count, stars_sum = await cur.fetchone()
        cur = await db.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM payments WHERE status='paid' AND currency!='XTR'")
        crypto_count, crypto_sum = await cur.fetchone()
        return {
            "stars_count": stars_count, "stars_sum": stars_sum,
            "crypto_count": crypto_count, "crypto_sum": crypto_sum,
        }


# =========================================================
#              CRYPTO PAY API (@CryptoBot)
# =========================================================
CRYPTOPAY_BASE_URL = "https://pay.crypt.bot/api"


async def cryptopay_create_invoice(token: str, amount: float, asset: str, description: str, payload: str):
    url = f"{CRYPTOPAY_BASE_URL}/createInvoice"
    headers = {"Crypto-Pay-API-Token": token}
    data = {
        "asset": asset,
        "amount": str(amount),
        "description": description[:1024],
        "payload": payload[:4000],
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=data) as resp:
            result = await resp.json()
            if not result.get("ok"):
                raise RuntimeError(f"CryptoPay error: {result}")
            return result["result"]


async def cryptopay_get_invoice_status(token: str, invoice_id: str) -> str:
    url = f"{CRYPTOPAY_BASE_URL}/getInvoices"
    headers = {"Crypto-Pay-API-Token": token}
    params = {"invoice_ids": invoice_id}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as resp:
            result = await resp.json()
            if not result.get("ok"):
                raise RuntimeError(f"CryptoPay error: {result}")
            items = result["result"]["items"]
            if not items:
                return "unknown"
            return items[0]["status"]  # active | paid | expired


# =========================================================
#                       KEYBOARDS
# =========================================================
def channel_label(ch: dict) -> str:
    """Название кнопки канала с обычным эмодзи-индикатором (цвет кнопок Telegram не поддерживает)."""
    prefix = f"{ch['emoji']} " if ch.get("emoji") else ""
    return f"{prefix}{ch['name']}"


def main_menu_kb(btn_channels: str, btn_propose: str, btn_support: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=btn_channels, callback_data="menu:channels")
    b.button(text=btn_propose, callback_data="menu:propose")
    b.button(text=btn_support, callback_data="menu:support")
    b.adjust(2, 1)
    return b.as_markup()


def channels_list_kb(channels: list) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for ch in channels:
        b.button(text=channel_label(ch), callback_data=f"channel:{ch['id']}")
    b.button(text="⬅️ Назад", callback_data="back:main")
    b.adjust(1)
    return b.as_markup()


def channel_card_kb(channel_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Вступить", callback_data=f"join:{channel_id}")
    b.button(text="⬅️ К списку каналов", callback_data="menu:channels")
    b.adjust(1)
    return b.as_markup()


def pay_url_kb(pay_url: str, payment_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💳 Оплатить", url=pay_url)
    b.button(text="✅ Я оплатил, проверить", callback_data=f"checkpay:{payment_id}")
    b.adjust(1)
    return b.as_markup()


def back_kb(cb: str = "back:main") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ Назад", callback_data=cb)
    return b.as_markup()


def admin_main_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📃 Каналы", callback_data="admin:channels")
    b.button(text="📝 Тексты", callback_data="admin:texts")
    b.button(text="🛠 Поддержка (юзернейм)", callback_data="admin:support")
    b.button(text="💰 Crypto Pay токен", callback_data="admin:crypto_token")
    b.button(text="📥 Заявки на каналы", callback_data="admin:proposals")
    b.button(text="📊 Статистика", callback_data="admin:stats")
    b.adjust(1)
    return b.as_markup()


def admin_channels_list_kb(channels: list) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for ch in channels:
        mark = "🟢" if ch["active"] else "⚪️"
        b.button(text=f"{mark} {ch['name']}", callback_data=f"admin:edit_channel:{ch['id']}")
    b.button(text="➕ Добавить канал", callback_data="admin:add_channel")
    b.button(text="⬅️ В админ-меню", callback_data="admin:back")
    b.adjust(1)
    return b.as_markup()


def admin_channel_edit_kb(ch: dict) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Название", callback_data=f"admin:editfield:{ch['id']}:name")
    b.button(text="✏️ Описание", callback_data=f"admin:editfield:{ch['id']}:description")
    b.button(text="✏️ Подписчики", callback_data=f"admin:editfield:{ch['id']}:subscribers")
    b.button(text="✏️ Ссылка", callback_data=f"admin:editfield:{ch['id']}:invite_link")
    b.button(text="✏️ Эмодзи кнопки", callback_data=f"admin:editfield:{ch['id']}:emoji")
    b.button(text="✏️ Custom emoji ID", callback_data=f"admin:editfield:{ch['id']}:custom_emoji_id")
    free_text = "💸 Сделать платным" if ch["is_free"] else "🆓 Сделать бесплатным"
    b.button(text=free_text, callback_data=f"admin:togglefree:{ch['id']}")
    if not ch["is_free"]:
        b.button(text="✏️ Цена в звёздах", callback_data=f"admin:editfield:{ch['id']}:price_stars")
        b.button(text="✏️ Цена в крипте (USDT)", callback_data=f"admin:editfield:{ch['id']}:price_crypto")
    active_text = "⛔️ Скрыть канал" if ch["active"] else "✅ Показать канал"
    b.button(text=active_text, callback_data=f"admin:toggleactive:{ch['id']}")
    b.button(text="🗑 Удалить канал", callback_data=f"admin:delete_channel:{ch['id']}")
    b.button(text="⬅️ К списку", callback_data="admin:channels")
    b.adjust(1)
    return b.as_markup()


def confirm_kb(yes_cb: str, no_cb: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Да", callback_data=yes_cb)
    b.button(text="❌ Отмена", callback_data=no_cb)
    b.adjust(2)
    return b.as_markup()


def admin_texts_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    keys = [
        ("welcome_text", "Приветствие (/start)"),
        ("btn_channels_text", "Текст кнопки «Каналы»"),
        ("btn_propose_text", "Текст кнопки «Предложить канал»"),
        ("btn_support_text", "Текст кнопки «Поддержка»"),
        ("propose_prompt", "Текст запроса при предложении канала"),
        ("propose_thanks", "Текст благодарности после заявки"),
    ]
    for key, label in keys:
        b.button(text=label, callback_data=f"admin:edittext:{key}")
    b.button(text="⬅️ В админ-меню", callback_data="admin:back")
    b.adjust(1)
    return b.as_markup()


def admin_proposals_kb(proposals: list) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in proposals:
        b.button(text=f"Заявка #{p['id']} от @{p['username'] or p['user_id']}", callback_data=f"admin:view_prop:{p['id']}")
    b.button(text="⬅️ В админ-меню", callback_data="admin:back")
    b.adjust(1)
    return b.as_markup()


def admin_proposal_card_kb(proposal_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Принять", callback_data=f"admin:prop_approve:{proposal_id}")
    b.button(text="❌ Отклонить", callback_data=f"admin:prop_reject:{proposal_id}")
    b.button(text="⬅️ К заявкам", callback_data="admin:proposals")
    b.adjust(2, 1)
    return b.as_markup()


# =========================================================
#                       FSM STATES
# =========================================================
class AddChannel(StatesGroup):
    name = State()
    description = State()
    subscribers = State()
    link = State()
    is_free = State()
    price_stars = State()
    price_crypto = State()


class EditField(StatesGroup):
    waiting_value = State()


class ProposeChannel(StatesGroup):
    waiting_info = State()


class EditText(StatesGroup):
    waiting_value = State()


class SetSupport(StatesGroup):
    waiting_username = State()


class SetCryptoToken(StatesGroup):
    waiting_token = State()


# =========================================================
#                     USER-SIDE HANDLERS
# =========================================================
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await upsert_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    s = await get_all_settings()
    await message.answer(
        s["welcome_text"],
        reply_markup=main_menu_kb(s["btn_channels_text"], s["btn_propose_text"], s["btn_support_text"]),
    )


@router.callback_query(F.data == "back:main")
async def cb_back_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    s = await get_all_settings()
    await call.message.edit_text(
        s["welcome_text"],
        reply_markup=main_menu_kb(s["btn_channels_text"], s["btn_propose_text"], s["btn_support_text"]),
    )
    await call.answer()


@router.callback_query(F.data == "menu:channels")
async def cb_channels(call: CallbackQuery):
    channels = await get_channels(active_only=True)
    if not channels:
        await call.answer("Пока нет доступных каналов 🙁", show_alert=True)
        return
    await call.message.edit_text("Выберите канал из списка:", reply_markup=channels_list_kb(channels))
    await call.answer()


@router.callback_query(F.data.startswith("channel:"))
async def cb_channel_card(call: CallbackQuery):
    channel_id = int(call.data.split(":")[1])
    ch = await get_channel(channel_id)
    if not ch or not ch["active"]:
        await call.answer("Канал недоступен", show_alert=True)
        return
    if ch["is_free"]:
        price_line = "🆓 Бесплатно"
    else:
        parts = []
        if ch["price_stars"]:
            parts.append(f"⭐ {ch['price_stars']} Stars")
        if ch["price_crypto"]:
            parts.append(f"💎 {ch['price_crypto']} {(await get_setting('crypto_asset', 'USDT'))}")
        price_line = " / ".join(parts) if parts else "Платно"

    text = (
        f"<b>{ch['name']}</b>\n\n"
        f"{ch['description']}\n\n"
        f"👥 Подписчиков: {ch['subscribers']}\n"
        f"💰 Доступ: {price_line}"
    )
    await call.message.edit_text(text, reply_markup=channel_card_kb(channel_id))
    await call.answer()


@router.callback_query(F.data.startswith("join:"))
async def cb_join(call: CallbackQuery):
    channel_id = int(call.data.split(":")[1])
    ch = await get_channel(channel_id)
    if not ch or not ch["active"]:
        await call.answer("Канал недоступен", show_alert=True)
        return

    if ch["is_free"]:
        await call.message.answer(f"Вот ссылка на канал «{ch['name']}»:\n{ch['invite_link']}")
        await call.answer()
        return

    # платный доступ — предложим выбрать способ оплаты, если оба заданы
    options = []
    if ch["price_stars"]:
        options.append(("⭐ Оплатить звёздами Telegram", f"paystars:{channel_id}"))
    if ch["price_crypto"]:
        options.append(("💎 Оплатить в крипте", f"paycrypto:{channel_id}"))

    if not options:
        await call.answer("Цена для этого канала не настроена, обратитесь в поддержку.", show_alert=True)
        return

    if len(options) == 1:
        data = options[0][1]
        if data.startswith("paystars"):
            await start_stars_payment(call, channel_id, ch)
        else:
            await start_crypto_payment(call, channel_id, ch)
        return

    b = InlineKeyboardBuilder()
    for text, data in options:
        b.button(text=text, callback_data=data)
    b.button(text="⬅️ Назад", callback_data=f"channel:{channel_id}")
    b.adjust(1)
    await call.message.edit_text("Выберите способ оплаты:", reply_markup=b.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("paystars:"))
async def cb_pay_stars(call: CallbackQuery):
    channel_id = int(call.data.split(":")[1])
    ch = await get_channel(channel_id)
    await start_stars_payment(call, channel_id, ch)


async def start_stars_payment(call: CallbackQuery, channel_id: int, ch: dict):
    await call.answer()
    await bot.send_invoice(
        chat_id=call.from_user.id,
        title=ch["name"],
        description=ch["description"][:255] or ch["name"],
        payload=f"channel:{channel_id}",
        currency="XTR",
        prices=[LabeledPrice(label=ch["name"], amount=ch["price_stars"])],
    )


@router.callback_query(F.data.startswith("paycrypto:"))
async def cb_pay_crypto(call: CallbackQuery):
    channel_id = int(call.data.split(":")[1])
    ch = await get_channel(channel_id)
    await start_crypto_payment(call, channel_id, ch)


async def start_crypto_payment(call: CallbackQuery, channel_id: int, ch: dict):
    token = await get_setting("crypto_pay_token", "")
    if not token:
        await call.answer("Оплата в крипте временно недоступна (не настроен токен).", show_alert=True)
        return
    asset = await get_setting("crypto_asset", "USDT")
    try:
        invoice = await cryptopay_create_invoice(
            token=token,
            amount=ch["price_crypto"],
            asset=asset,
            description=f"Доступ к каналу {ch['name']}",
            payload=f"channel:{channel_id}:{call.from_user.id}",
        )
    except Exception:
        log.exception("crypto invoice error")
        await call.answer("Ошибка создания счёта, попробуйте позже.", show_alert=True)
        return

    payment_id = await add_payment(
        user_id=call.from_user.id, channel_id=channel_id, method="crypto",
        amount=ch["price_crypto"], currency=asset, invoice_id=str(invoice["invoice_id"]),
    )
    await call.answer()
    await call.message.answer(
        f"Счёт на {ch['price_crypto']} {asset} создан.\nПосле оплаты нажмите «Проверить».",
        reply_markup=pay_url_kb(invoice["pay_url"], payment_id),
    )


@router.callback_query(F.data.startswith("checkpay:"))
async def cb_checkpay(call: CallbackQuery):
    payment_id = int(call.data.split(":")[1])
    payment = await get_payment(payment_id)
    if not payment:
        await call.answer("Платёж не найден", show_alert=True)
        return
    if payment["status"] == "paid":
        ch = await get_channel(payment["channel_id"])
        await call.message.answer(f"Оплата уже подтверждена ✅\nСсылка: {ch['invite_link']}")
        await call.answer()
        return

    token = await get_setting("crypto_pay_token", "")
    status = await cryptopay_get_invoice_status(token, payment["invoice_id"])
    if status == "paid":
        await update_payment_status(payment_id, "paid")
        ch = await get_channel(payment["channel_id"])
        await call.message.answer(f"Оплата подтверждена ✅\nВот ссылка на канал:\n{ch['invite_link']}")
        await call.answer("Оплачено!")
    else:
        await call.answer("Оплата пока не найдена. Попробуйте ещё раз через минуту.", show_alert=True)


@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout_q: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_q.id, ok=True)


@router.message(F.successful_payment)
async def process_successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload  # "channel:{id}"
    channel_id = int(payload.split(":")[1])
    ch = await get_channel(channel_id)
    await add_payment(
        user_id=message.from_user.id, channel_id=channel_id, method="stars",
        amount=message.successful_payment.total_amount, currency="XTR", status="paid",
    )
    if ch:
        await message.answer(f"Оплата прошла успешно ✅\nВот ссылка на канал:\n{ch['invite_link']}")
    else:
        await message.answer("Оплата прошла, но канал не найден — напишите в поддержку.")


@router.callback_query(F.data == "menu:propose")
async def cb_propose(call: CallbackQuery, state: FSMContext):
    prompt = await get_setting("propose_prompt")
    await call.message.edit_text(prompt, reply_markup=back_kb())
    await state.set_state(ProposeChannel.waiting_info)
    await call.answer()


@router.message(ProposeChannel.waiting_info)
async def process_propose(message: Message, state: FSMContext):
    await add_proposal(message.from_user.id, message.from_user.username or "", message.text or "")
    thanks = await get_setting("propose_thanks")
    await state.clear()
    s = await get_all_settings()
    await message.answer(thanks, reply_markup=main_menu_kb(s["btn_channels_text"], s["btn_propose_text"], s["btn_support_text"]))
    try:
        await bot.send_message(
            OWNER_ID,
            f"📥 Новая заявка на канал от @{message.from_user.username or message.from_user.id}:\n\n{message.text}",
        )
    except Exception:
        pass


@router.callback_query(F.data == "menu:support")
async def cb_support(call: CallbackQuery):
    username = await get_setting("support_username", "")
    if not username:
        await call.answer("Поддержка пока не настроена", show_alert=True)
        return
    b = InlineKeyboardBuilder()
    b.button(text="✉️ Написать в поддержку", url=f"https://t.me/{username.lstrip('@')}")
    b.button(text="⬅️ Назад", callback_data="back:main")
    b.adjust(1)
    await call.message.edit_text("По всем вопросам — сюда:", reply_markup=b.as_markup())
    await call.answer()


# =========================================================
#                     ADMIN HANDLERS
# =========================================================
@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    await state.clear()
    await message.answer("🔧 Админ-панель", reply_markup=admin_main_kb())


@router.callback_query(F.data == "admin:back")
async def cb_admin_back(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer()
    await state.clear()
    await call.message.edit_text("🔧 Админ-панель", reply_markup=admin_main_kb())
    await call.answer()


# ---- channels management ----
@router.callback_query(F.data == "admin:channels")
async def cb_admin_channels(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer()
    channels = await get_channels(active_only=False)
    await call.message.edit_text("Список каналов:", reply_markup=admin_channels_list_kb(channels))
    await call.answer()


@router.callback_query(F.data == "admin:add_channel")
async def cb_admin_add_channel(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer()
    await state.set_state(AddChannel.name)
    await call.message.edit_text("Введите название канала (например, GHOST):", reply_markup=back_kb("admin:channels"))
    await call.answer()


@router.message(AddChannel.name)
async def add_channel_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(AddChannel.description)
    await message.answer("Введите описание канала:")


@router.message(AddChannel.description)
async def add_channel_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(AddChannel.subscribers)
    await message.answer("Сколько подписчиков? (например, 12 400)")


@router.message(AddChannel.subscribers)
async def add_channel_subscribers(message: Message, state: FSMContext):
    await state.update_data(subscribers=message.text)
    await state.set_state(AddChannel.link)
    await message.answer("Пришлите ссылку-приглашение на канал:")


@router.message(AddChannel.link)
async def add_channel_link(message: Message, state: FSMContext):
    await state.update_data(link=message.text)
    await state.set_state(AddChannel.is_free)
    b = InlineKeyboardBuilder()
    b.button(text="🆓 Бесплатный", callback_data="newch:free")
    b.button(text="💸 Платный", callback_data="newch:paid")
    b.adjust(2)
    await message.answer("Доступ к каналу бесплатный или платный?", reply_markup=b.as_markup())


@router.callback_query(AddChannel.is_free, F.data.in_(["newch:free", "newch:paid"]))
async def add_channel_is_free(call: CallbackQuery, state: FSMContext):
    is_free = call.data == "newch:free"
    await state.update_data(is_free=is_free, price_stars=0, price_crypto=0)
    if is_free:
        await finish_add_channel(call.message, state)
    else:
        await state.set_state(AddChannel.price_stars)
        await call.message.edit_text("Цена в Telegram Stars (число, 0 — если без звёзд):")
    await call.answer()


@router.message(AddChannel.price_stars)
async def add_channel_price_stars(message: Message, state: FSMContext):
    try:
        price = int(message.text.strip())
    except ValueError:
        await message.answer("Введите целое число, например 150")
        return
    await state.update_data(price_stars=price)
    await state.set_state(AddChannel.price_crypto)
    await message.answer("Цена в крипте, USDT (число, 0 — если без крипты):")


@router.message(AddChannel.price_crypto)
async def add_channel_price_crypto(message: Message, state: FSMContext):
    try:
        price = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("Введите число, например 5.5")
        return
    await state.update_data(price_crypto=price)
    await finish_add_channel(message, state)


async def finish_add_channel(message: Message, state: FSMContext):
    data = await state.get_data()
    channel_id = await add_channel(
        name=data["name"], description=data["description"], subscribers=data["subscribers"],
        invite_link=data["link"], is_free=data["is_free"], price_stars=data.get("price_stars", 0),
        price_crypto=data.get("price_crypto", 0), emoji="", custom_emoji_id="",
    )
    await state.clear()
    await message.answer(f"Канал добавлен ✅ (id {channel_id})", reply_markup=admin_main_kb())


@router.callback_query(F.data.startswith("admin:edit_channel:"))
async def cb_admin_edit_channel(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer()
    channel_id = int(call.data.split(":")[2])
    ch = await get_channel(channel_id)
    if not ch:
        await call.answer("Канал не найден", show_alert=True)
        return
    if ch["is_free"]:
        price_line = "🆓 бесплатно"
    else:
        price_line = f"💸 {ch['price_stars']}⭐ / {ch['price_crypto']}💎"
    text = (
        f"<b>{ch['name']}</b>\n{ch['description']}\n\n"
        f"👥 {ch['subscribers']} | {price_line}\n"
        f"Ссылка: {ch['invite_link']}\n"
        f"Эмодзи: {ch['emoji'] or '—'} | Custom emoji ID: {ch['custom_emoji_id'] or '—'}"
    )
    await call.message.edit_text(text, reply_markup=admin_channel_edit_kb(ch))
    await call.answer()


@router.callback_query(F.data.startswith("admin:togglefree:"))
async def cb_toggle_free(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer()
    channel_id = int(call.data.split(":")[2])
    ch = await get_channel(channel_id)
    await update_channel_field(channel_id, "is_free", 0 if ch["is_free"] else 1)
    ch = await get_channel(channel_id)
    await call.message.edit_text(f"<b>{ch['name']}</b> обновлён.", reply_markup=admin_channel_edit_kb(ch))
    await call.answer()


@router.callback_query(F.data.startswith("admin:toggleactive:"))
async def cb_toggle_active(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer()
    channel_id = int(call.data.split(":")[2])
    ch = await get_channel(channel_id)
    await update_channel_field(channel_id, "active", 0 if ch["active"] else 1)
    ch = await get_channel(channel_id)
    await call.message.edit_text(f"<b>{ch['name']}</b> обновлён.", reply_markup=admin_channel_edit_kb(ch))
    await call.answer()


@router.callback_query(F.data.startswith("admin:editfield:"))
async def cb_admin_editfield(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer()
    _, _, channel_id, field = call.data.split(":")
    await state.set_state(EditField.waiting_value)
    await state.update_data(channel_id=int(channel_id), field=field)
    labels = {
        "name": "новое название", "description": "новое описание", "subscribers": "новое число подписчиков",
        "invite_link": "новую ссылку", "emoji": "эмодзи (например 🔥)",
        "custom_emoji_id": "custom_emoji_id (числовой ID премиум-эмодзи)",
        "price_stars": "новую цену в звёздах (число)", "price_crypto": "новую цену в USDT (число)",
    }
    await call.message.edit_text(f"Введите {labels.get(field, field)}:")
    await call.answer()


@router.message(EditField.waiting_value)
async def process_editfield(message: Message, state: FSMContext):
    data = await state.get_data()
    channel_id, field = data["channel_id"], data["field"]
    value = message.text.strip()
    if field == "price_stars":
        try:
            value = int(value)
        except ValueError:
            await message.answer("Нужно целое число")
            return
    if field == "price_crypto":
        try:
            value = float(value.replace(",", "."))
        except ValueError:
            await message.answer("Нужно число")
            return
    await update_channel_field(channel_id, field, value)
    await state.clear()
    ch = await get_channel(channel_id)
    await message.answer("Обновлено ✅", reply_markup=admin_channel_edit_kb(ch))


@router.callback_query(F.data.startswith("admin:delete_channel:"))
async def cb_admin_delete_channel(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer()
    channel_id = int(call.data.split(":")[2])
    await call.message.edit_text(
        "Точно удалить канал? Это необратимо.",
        reply_markup=confirm_kb(f"admin:confirmdel:{channel_id}", "admin:channels"),
    )
    await call.answer()


@router.callback_query(F.data.startswith("admin:confirmdel:"))
async def cb_admin_confirm_delete(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer()
    channel_id = int(call.data.split(":")[2])
    await delete_channel(channel_id)
    channels = await get_channels(active_only=False)
    await call.message.edit_text("Канал удалён ✅\n\nСписок каналов:", reply_markup=admin_channels_list_kb(channels))
    await call.answer()


# ---- texts ----
@router.callback_query(F.data == "admin:texts")
async def cb_admin_texts(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer()
    await call.message.edit_text(
        "Какой текст изменить?\n\nПодсказка: можно вставлять кастомные премиум-эмодзи через "
        "HTML-тег &lt;tg-emoji emoji-id=\"ID\"&gt;😁&lt;/tg-emoji&gt;.",
        reply_markup=admin_texts_kb(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("admin:edittext:"))
async def cb_admin_edittext(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer()
    key = call.data.split(":")[2]
    current = await get_setting(key)
    await state.set_state(EditText.waiting_value)
    await state.update_data(key=key)
    await call.message.edit_text(f"Текущее значение:\n\n{current}\n\nПришлите новый текст:")
    await call.answer()


@router.message(EditText.waiting_value)
async def process_edittext(message: Message, state: FSMContext):
    data = await state.get_data()
    await set_setting(data["key"], message.html_text or message.text)
    await state.clear()
    await message.answer("Текст обновлён ✅", reply_markup=admin_main_kb())


# ---- support username ----
@router.callback_query(F.data == "admin:support")
async def cb_admin_support(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer()
    current = await get_setting("support_username", "не задан")
    await state.set_state(SetSupport.waiting_username)
    await call.message.edit_text(f"Текущий юзернейм поддержки: @{current}\n\nПришлите новый юзернейм (без @):")
    await call.answer()


@router.message(SetSupport.waiting_username)
async def process_support(message: Message, state: FSMContext):
    await set_setting("support_username", message.text.strip().lstrip("@"))
    await state.clear()
    await message.answer("Юзернейм поддержки обновлён ✅", reply_markup=admin_main_kb())


# ---- crypto token ----
@router.callback_query(F.data == "admin:crypto_token")
async def cb_admin_crypto_token(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer()
    await state.set_state(SetCryptoToken.waiting_token)
    await call.message.edit_text(
        "Пришлите токен Crypto Pay API (получить у @CryptoBot -> Crypto Pay -> Create App):"
    )
    await call.answer()


@router.message(SetCryptoToken.waiting_token)
async def process_crypto_token(message: Message, state: FSMContext):
    await set_setting("crypto_pay_token", message.text.strip())
    await state.clear()
    try:
        await message.delete()  # прячем токен из чата
    except Exception:
        pass
    await message.answer("Токен сохранён ✅", reply_markup=admin_main_kb())


# ---- proposals ----
@router.callback_query(F.data == "admin:proposals")
async def cb_admin_proposals(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer()
    proposals = await get_proposals("pending")
    if not proposals:
        await call.message.edit_text("Новых заявок нет.", reply_markup=admin_main_kb())
    else:
        await call.message.edit_text("Заявки на добавление каналов:", reply_markup=admin_proposals_kb(proposals))
    await call.answer()


@router.callback_query(F.data.startswith("admin:view_prop:"))
async def cb_admin_view_prop(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer()
    proposal_id = int(call.data.split(":")[2])
    p = await get_proposal(proposal_id)
    if not p:
        await call.answer("Заявка не найдена", show_alert=True)
        return
    text = f"Заявка #{p['id']} от @{p['username'] or p['user_id']}:\n\n{p['info']}"
    await call.message.edit_text(text, reply_markup=admin_proposal_card_kb(proposal_id))
    await call.answer()


@router.callback_query(F.data.startswith("admin:prop_approve:"))
async def cb_admin_prop_approve(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer()
    proposal_id = int(call.data.split(":")[2])
    await update_proposal_status(proposal_id, "approved")
    p = await get_proposal(proposal_id)
    try:
        await bot.send_message(p["user_id"], "Ваша заявка на канал одобрена ✅ Мы добавим его в список.")
    except Exception:
        pass
    await call.answer("Заявка одобрена")
    await cb_admin_proposals(call)


@router.callback_query(F.data.startswith("admin:prop_reject:"))
async def cb_admin_prop_reject(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer()
    proposal_id = int(call.data.split(":")[2])
    await update_proposal_status(proposal_id, "rejected")
    p = await get_proposal(proposal_id)
    try:
        await bot.send_message(p["user_id"], "К сожалению, ваша заявка отклонена.")
    except Exception:
        pass
    await call.answer("Заявка отклонена")
    await cb_admin_proposals(call)


# ---- stats ----
@router.callback_query(F.data == "admin:stats")
async def cb_admin_stats(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer()
    users_count = await count_users()
    channels = await get_channels(active_only=False)
    stats = await payments_stats()
    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"👤 Пользователей: {users_count}\n"
        f"📃 Каналов всего: {len(channels)} (активных: {sum(1 for c in channels if c['active'])})\n\n"
        f"⭐ Оплат звёздами: {stats['stars_count']} на {stats['stars_sum']} Stars\n"
        f"💎 Оплат криптой: {stats['crypto_count']} на {stats['crypto_sum']:.2f}"
    )
    await call.message.edit_text(text, reply_markup=back_kb("admin:back"))
    await call.answer()


# =========================================================
#                          MAIN
# =========================================================
async def main():
    await init_db(DB_PATH)
    log.info("Бот запущен")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
