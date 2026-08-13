import asyncio
import html
import os
import secrets
import sqlite3
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

try:
    OWNER_ID = int(os.getenv("OWNER_ID", "0"))
except ValueError:
    OWNER_ID = 0

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не установлен")

if OWNER_ID == 0:
    raise RuntimeError("OWNER_ID не установлен")


# =========================================================
# BOT
# =========================================================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher(
    storage=MemoryStorage()
)


# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(
    "bot.db",
    check_same_thread=False
)

db.row_factory = sqlite3.Row

db.executescript("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    balance INTEGER DEFAULT 0,
    purchases INTEGER DEFAULT 0,
    joined_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS gifts (
    gift_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    price INTEGER NOT NULL,
    enabled INTEGER DEFAULT 1,
    available INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    gift_id TEXT,
    gift_title TEXT,
    price INTEGER,
    text TEXT,
    status TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount INTEGER,
    payment_type TEXT,
    payload TEXT UNIQUE,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS free_spin (
    user_id INTEGER PRIMARY KEY,
    text TEXT DEFAULT '',
    spins INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS emojis (
    name TEXT PRIMARY KEY,
    emoji_id TEXT
);
""")

db.commit()


# =========================================================
# DATABASE HELPERS
# =========================================================

def execute(sql, params=()):
    cur = db.cursor()
    cur.execute(sql, params)
    db.commit()
    return cur.lastrowid


def one(sql, params=()):
    cur = db.cursor()
    cur.execute(sql, params)
    return cur.fetchone()


def rows(sql, params=()):
    cur = db.cursor()
    cur.execute(sql, params)
    return cur.fetchall()


# =========================================================
# USERS
# =========================================================

def save_user(user):

    execute(
        """
        INSERT INTO users(
            user_id,
            username,
            first_name
        )
        VALUES(?,?,?)

        ON CONFLICT(user_id)
        DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name
        """,
        (
            user.id,
            user.username,
            user.first_name
        )
    )


def get_balance(user_id):

    row = one(
        """
        SELECT balance
        FROM users
        WHERE user_id=?
        """,
        (user_id,)
    )

    return row["balance"] if row else 0


def add_balance(user_id, amount):

    execute(
        """
        UPDATE users
        SET balance=balance+?
        WHERE user_id=?
        """,
        (amount, user_id)
    )


def take_balance(user_id, amount):

    cur = db.cursor()

    cur.execute(
        """
        UPDATE users
        SET balance=balance-?
        WHERE user_id=?
        AND balance>=?
        """,
        (
            amount,
            user_id,
            amount
        )
    )

    db.commit()

    return cur.rowcount > 0


# =========================================================
# PREMIUM EMOJI
# =========================================================

EMOJI_NAMES = {
    "gifts": "Подарки",
    "topup": "Пополнить баланс",
    "free": "Получить бесплатно",
    "donate": "Пожертвовать",
    "gift": "Подарок",
    "write": "Написать текст",
    "no_text": "Без текста",
    "confirm": "Отправить",
    "back": "Назад",
    "users": "Пользователи",
    "add": "Добавить подарок",
    "withdraw": "Вывести подарок",
    "roulette": "Поехали",
    "admin": "Админ"
}


def get_emoji(name):

    row = one(
        """
        SELECT emoji_id
        FROM emojis
        WHERE name=?
        """,
        (name,)
    )

    return row["emoji_id"] if row else None


def set_emoji(name, emoji_id):

    execute(
        """
        INSERT INTO emojis(
            name,
            emoji_id
        )
        VALUES(?,?)

        ON CONFLICT(name)
        DO UPDATE SET
            emoji_id=excluded.emoji_id
        """,
        (
            name,
            emoji_id
        )
    )


def button(text, callback, emoji_name=None):

    kwargs = {
        "text": text,
        "callback_data": callback
    }

    if emoji_name:

        emoji_id = get_emoji(
            emoji_name
        )

        if emoji_id:
            kwargs[
                "icon_custom_emoji_id"
            ] = emoji_id

    return InlineKeyboardButton(
        **kwargs
    )


def text_emoji(name, fallback):

    emoji_id = get_emoji(name)

    if not emoji_id:
        return fallback

    return (
        f'<tg-emoji emoji-id="{emoji_id}">'
        f'{fallback}'
        f'</tg-emoji>'
    )


# =========================================================
# MAIN MENU
# =========================================================

def main_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                button(
                    "Подарки",
                    "gifts",
                    "gifts"
                )
            ],
            [
                button(
                    "Пополнить баланс",
                    "topup",
                    "topup"
                )
            ],
            [
                button(
                    "Получить бесплатно",
                    "free_gift",
                    "free"
                )
            ],
            [
                button(
                    "Пожертвовать",
                    "donate",
                    "donate"
                )
            ]
        ]
    )


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start(message: Message):

    save_user(
        message.from_user
    )

    await message.answer(
        (
            f"{text_emoji('gifts', '🎁')} "
            "<b>Подарки</b>\n\n"
            "Покупайте Telegram-подарки "
            "за Stars.\n\n"
            f"💰 Баланс: "
            f"<b>{get_balance(message.from_user.id)} ⭐</b>"
        ),
        reply_markup=main_menu()
    )


@dp.message(Command("balance"))
async def balance_command(message: Message):

    save_user(
        message.from_user
    )

    await message.answer(
        f"💰 Ваш баланс: "
        f"<b>{get_balance(message.from_user.id)} ⭐</b>"
    )


# =========================================================
# TELEGRAM GIFTS
# =========================================================

def get_gift_title(gift):

    old = one(
        """
        SELECT title
        FROM gifts
        WHERE gift_id=?
        """,
        (str(gift.id),)
    )

    if old:
        return old["title"]

    sticker = getattr(
        gift,
        "sticker",
        None
    )

    if sticker:

        emoji = getattr(
            sticker,
            "emoji",
            None
        )

        if emoji:
            return f"Подарок {emoji}"

    return "Подарок"


async def sync_gifts():

    try:

        result = await bot.get_available_gifts()

    except Exception as error:

        print(
            "Ошибка getAvailableGifts:",
            error
        )

        return

    for gift in result.gifts:

        gift_id = str(gift.id)

        title = get_gift_title(
            gift
        )

        price = int(
            gift.star_count
        )

        execute(
            """
            INSERT INTO gifts(
                gift_id,
                title,
                price,
                enabled,
                available
            )
            VALUES(?,?,?,?,?)

            ON CONFLICT(gift_id)
            DO UPDATE SET
                price=excluded.price,
                available=1
            """,
            (
                gift_id,
                title,
                price,
                1,
                1
            )
        )


# =========================================================
# GIFTS
# =========================================================

@dp.callback_query(F.data == "gifts")
async def gifts_menu(
    call: CallbackQuery
):

    await call.answer()

    await sync_gifts()

    gifts = rows(
        """
        SELECT *
        FROM gifts
        WHERE enabled=1
        AND available=1
        ORDER BY price ASC
        """
    )

    if not gifts:

        await call.message.answer(
            "🎁 Сейчас подарков нет."
        )

        return

    keyboard = []

    for gift in gifts:

        keyboard.append([
            button(
                (
                    f"{gift['title']} — "
                    f"{gift['price']} ⭐"
                ),
                f"gift:{gift['gift_id']}",
                "gift"
            )
        ])

    keyboard.append([
        button(
            "Пополнить баланс",
            "topup",
            "topup"
        )
    ])

    await call.message.answer(
        "<b>🎁 Подарки</b>\n\n"
        "Выберите подарок:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=keyboard
        )
    )


# =========================================================
# GIFT STATES
# =========================================================

class GiftState(StatesGroup):

    text = State()


# =========================================================
# CHOOSE GIFT
# =========================================================

@dp.callback_query(
    F.data.startswith("gift:")
)
async def choose_gift(
    call: CallbackQuery,
    state: FSMContext
):

    await call.answer()

    gift_id = call.data.split(
        ":",
        1
    )[1]

    gift = one(
        """
        SELECT *
        FROM gifts
        WHERE gift_id=?
        AND enabled=1
        """,
        (gift_id,)
    )

    if not gift:

        await call.message.answer(
            "❌ Подарок не найден."
        )

        return

    await state.update_data(
        gift_id=gift["gift_id"],
        title=gift["title"],
        price=gift["price"]
    )

    await call.message.answer(
        (
            f"<b>{html.escape(gift['title'])}</b>\n\n"
            f"Цена: <b>{gift['price']} ⭐</b>\n\n"
            "Добавить текст?"
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    button(
                        "Написать текст",
                        "gift_add_text",
                        "write"
                    )
                ],
                [
                    button(
                        "Без текста",
                        "gift_no_text",
                        "no_text"
                    )
                ]
            ]
        )
    )


# =========================================================
# GIFT TEXT
# =========================================================

@dp.callback_query(
    F.data == "gift_add_text"
)
async def gift_add_text(
    call: CallbackQuery,
    state: FSMContext
):

    await call.answer()

    data = await state.get_data()

    if not data.get("gift_id"):

        await call.message.answer(
            "❌ Сначала выберите подарок."
        )

        return

    await state.set_state(
        GiftState.text
    )

    await call.message.answer(
        "✍️ Напишите текст для подарка.\n\n"
        "Максимум 128 символов."
    )


@dp.message(
    GiftState.text,
    F.text
)
async def receive_gift_text(
    message: Message,
    state: FSMContext
):

    text = message.text.strip()

    if len(text) > 128:

        await message.answer(
            "❌ Максимум 128 символов."
        )

        return

    data = await state.get_data()

    await state.clear()

    await create_pending_order(
        message.chat.id,
        data,
        text
    )


# =========================================================
# WITHOUT TEXT
# =========================================================

@dp.callback_query(
    F.data == "gift_no_text"
)
async def gift_no_text(
    call: CallbackQuery,
    state: FSMContext
):

    await call.answer()

    data = await state.get_data()

    await state.clear()

    if not data.get("gift_id"):

        await call.message.answer(
            "❌ Сначала выберите подарок."
        )

        return

    await create_pending_order(
        call.from_user.id,
        data,
        ""
    )


async def create_pending_order(
    user_id,
    data,
    text
):

    execute(
        """
        DELETE FROM orders
        WHERE user_id=?
        AND status='pending'
        """,
        (user_id,)
    )

    execute(
        """
        INSERT INTO orders(
            user_id,
            gift_id,
            gift_title,
            price,
            text,
            status
        )
        VALUES(?,?,?,?,?,?)
        """,
        (
            user_id,
            data["gift_id"],
            data["title"],
            data["price"],
            text,
            "pending"
        )
    )

    text_part = (
        f"\n\nТекст:\n"
        f"<i>{html.escape(text)}</i>"
        if text
        else
        "\n\nТекст: без текста"
    )

    await bot.send_message(
        user_id,
        (
            "<b>Подтверждение</b>\n\n"
            f"🎁 {html.escape(data['title'])}\n"
            f"💰 Цена: <b>{data['price']} ⭐</b>\n"
            f"💳 Баланс: "
            f"<b>{get_balance(user_id)} ⭐</b>"
            f"{text_part}"
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    button(
                        "Отправить",
                        "send_pending_gift",
                        "confirm"
                    )
                ],
                [
                    button(
                        "Пополнить баланс",
                        "topup",
                        "topup"
                    )
                ],
                [
                    button(
                        "Подарки",
                        "gifts",
                        "back"
                    )
                ]
            ]
        )
    )


# =========================================================
# SEND GIFT
# =========================================================

@dp.callback_query(
    F.data == "send_pending_gift"
)
async def send_pending_gift(
    call: CallbackQuery
):

    await call.answer()

    user_id = call.from_user.id

    order = one(
        """
        SELECT *
        FROM orders
        WHERE user_id=?
        AND status='pending'
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id,)
    )

    if not order:

        await call.message.answer(
            "❌ Заказ не найден."
        )

        return

    price = int(
        order["price"]
    )

    if get_balance(user_id) < price:

        await call.message.answer(
            (
                "❌ Недостаточно Stars.\n\n"
                f"Нужно: <b>{price} ⭐</b>\n"
                f"Есть: <b>{get_balance(user_id)} ⭐</b>"
            ),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        button(
                            "Пополнить баланс",
                            "topup",
                            "topup"
                        )
                    ]
                ]
            )
        )

        return

    try:

        kwargs = {
            "user_id": user_id,
            "gift_id": str(
                order["gift_id"]
            )
        }

        if order["text"]:

            kwargs["text"] = (
                order["text"]
            )

        result = await bot.send_gift(
            **kwargs
        )

        if not result:

            raise RuntimeError(
                "Telegram вернул False"
            )

    except Exception as error:

        await call.message.answer(
            (
                "❌ Не удалось отправить подарок.\n\n"
                f"<code>"
                f"{html.escape(str(error))}"
                f"</code>"
            )
        )

        return

    if not take_balance(
        user_id,
        price
    ):

        await call.message.answer(
            (
                "⚠️ Подарок отправлен, "
                "но внутренний баланс "
                "не удалось списать."
            )
        )

        return

    execute(
        """
        UPDATE orders
        SET status='completed'
        WHERE id=?
        """,
        (order["id"],)
    )

    execute(
        """
        UPDATE users
        SET purchases=purchases+1
        WHERE user_id=?
        """,
        (user_id,)
    )

    await call.message.answer(
        (
            "<b>🎁 Подарок отправлен!</b>\n\n"
            f"{html.escape(order['gift_title'])}\n"
            f"Списано: <b>{price} ⭐</b>\n"
            f"Баланс: "
            f"<b>{get_balance(user_id)} ⭐</b>"
        ),
        reply_markup=main_menu()
    )


# =========================================================
# TOP UP
# =========================================================

class TopUpState(StatesGroup):

    amount = State()


@dp.callback_query(
    F.data == "topup"
)
async def topup(
    call: CallbackQuery,
    state: FSMContext
):

    await call.answer()

    await state.set_state(
        TopUpState.amount
    )

    await call.message.answer(
        "<b>💰 Пополнение баланса</b>\n\n"
        "Введите количество Stars.\n\n"
        "Например: <code>50</code>"
    )


@dp.message(
    TopUpState.amount,
    F.text
)
async def topup_amount(
    message: Message,
    state: FSMContext
):

    try:

        amount = int(
            message.text.strip()
        )

    except ValueError:

        await message.answer(
            "❌ Введите число."
        )

        return

    if amount < 1:

        await message.answer(
            "❌ Минимум 1 ⭐."
        )

        return

    if amount > 10000:

        await message.answer(
            "❌ Максимум 10000 ⭐."
        )

        return

    await state.clear()

    payload = (
        f"topup:"
        f"{message.from_user.id}:"
        f"{amount}:"
        f"{secrets.token_hex(12)}"
    )

    await bot.send_invoice(
        chat_id=message.from_user.id,
        title="Пополнение баланса",
        description=(
            f"Пополнение на {amount} Stars."
        ),
        payload=payload,
        currency="XTR",
        prices=[
            LabeledPrice(
                label="Пополнение",
                amount=amount
            )
        ],
        provider_token=""
    )


# =========================================================
# DONATE
# =========================================================

class DonateState(StatesGroup):

    amount = State()


@dp.callback_query(
    F.data == "donate"
)
async def donate(
    call: CallbackQuery,
    state: FSMContext
):

    await call.answer()

    await state.set_state(
        DonateState.amount
    )

    await call.message.answer(
        "<b>💎 Пожертвовать проекту</b>\n\n"
        "Введите количество Stars."
    )


@dp.message(
    DonateState.amount,
    F.text
)
async def donate_amount(
    message: Message,
    state: FSMContext
):

    try:

        amount = int(
            message.text.strip()
        )

    except ValueError:

        await message.answer(
            "❌ Введите число."
        )

        return

    if amount < 1:

        await message.answer(
            "❌ Минимум 1 ⭐."
        )

        return

    if amount > 10000:

        await message.answer(
            "❌ Максимум 10000 ⭐."
        )

        return

    await state.clear()

    payload = (
        f"donate:"
        f"{message.from_user.id}:"
        f"{amount}:"
        f"{secrets.token_hex(12)}"
    )

    await bot.send_invoice(
        chat_id=message.from_user.id,
        title="Пожертвование проекту",
        description=(
            f"Пожертвование {amount} Stars."
        ),
        payload=payload,
        currency="XTR",
        prices=[
            LabeledPrice(
                label="Пожертвование",
                amount=amount
            )
        ],
        provider_token=""
    )


# =========================================================
# PAYMENT
# =========================================================

@dp.pre_checkout_query()
async def pre_checkout(
    query: PreCheckoutQuery
):

    await query.answer(
        ok=True
    )


@dp.message(
    F.successful_payment
)
async def successful_payment(
    message: Message
):

    payment = message.successful_payment

    payload = payment.invoice_payload

    parts = payload.split(":")

    if len(parts) != 4:
        return

    payment_type = parts[0]

    try:

        user_id = int(parts[1])
        amount = int(parts[2])

    except ValueError:

        return

    if user_id != message.from_user.id:
        return

    existing = one(
        """
        SELECT id
        FROM payments
        WHERE payload=?
        """,
        (payload,)
    )

    if existing:
        return

    execute(
        """
        INSERT INTO payments(
            user_id,
            amount,
            payment_type,
            payload
        )
        VALUES(?,?,?,?)
        """,
        (
            user_id,
            amount,
            payment_type,
            payload
        )
    )

    if payment_type == "topup":

        add_balance(
            user_id,
            amount
        )

        await message.answer(
            (
                "<b>✅ Баланс пополнен!</b>\n\n"
                f"+{amount} ⭐\n"
                f"Баланс: "
                f"<b>{get_balance(user_id)} ⭐</b>"
            ),
            reply_markup=main_menu()
        )

        return

    if payment_type == "donate":

        await message.answer(
            (
                "<b>❤️ Спасибо за поддержку!</b>\n\n"
                f"Пожертвовано: "
                f"<b>{amount} ⭐</b>"
            ),
            reply_markup=main_menu()
        )

        return

    if payment_type == "free_spin":

        await send_slot(
            user_id
        )


# =========================================================
# FREE ROULETTE
# =========================================================

class FreeTextState(StatesGroup):

    text = State()


def free_spins(user_id):

    row = one(
        """
        SELECT spins
        FROM free_spin
        WHERE user_id=?
        """,
        (user_id,)
    )

    return row["spins"] if row else 0


def add_free_spin(user_id):

    execute(
        """
        INSERT INTO free_spin(
            user_id,
            spins
        )
        VALUES(?,1)

        ON CONFLICT(user_id)
        DO UPDATE SET
            spins=spins+1
        """,
        (user_id,)
    )


def take_free_spin(user_id):

    cur = db.cursor()

    cur.execute(
        """
        UPDATE free_spin
        SET spins=spins-1
        WHERE user_id=?
        AND spins>0
        """,
        (user_id,)
    )

    db.commit()

    return cur.rowcount > 0


def save_free_text(
    user_id,
    text
):

    execute(
        """
        INSERT INTO free_spin(
            user_id,
            text
        )
        VALUES(?,?)

        ON CONFLICT(user_id)
        DO UPDATE SET
            text=excluded.text
        """,
        (
            user_id,
            text
        )
    )


def get_free_text(user_id):

    row = one(
        """
        SELECT text
        FROM free_spin
        WHERE user_id=?
        """,
        (user_id,)
    )

    return row["text"] if row else ""


@dp.callback_query(
    F.data == "free_gift"
)
async def free_gift(
    call: CallbackQuery,
    state: FSMContext
):

    await call.answer()

    await state.clear()

    await call.message.answer(
        (
            "<b>🎰 Получить бесплатно</b>\n\n"
            "Одна прокрутка — <b>2 ⭐</b>.\n\n"
            "🎰 Три одинаковых символа — "
            "<b>1 бесплатная прокрутка</b>.\n\n"
            "7️⃣7️⃣7️⃣ — "
            "<b>❤️ Сердечко</b> бесплатно.\n\n"
            "Если комбинация не выигрышная — "
            "ничего не выпадает.\n\n"
            f"Бесплатных прокруток: "
            f"<b>{free_spins(call.from_user.id)}</b>"
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    button(
                        "Поехали — 2 ⭐",
                        "free_spin_start",
                        "roulette"
                    )
                ],
                [
                    button(
                        "Добавить текст",
                        "free_text",
                        "write"
                    )
                ]
            ]
        )
    )


# =========================================================
# FREE TEXT
# =========================================================

@dp.callback_query(
    F.data == "free_text"
)
async def free_text(
    call: CallbackQuery,
    state: FSMContext
):

    await call.answer()

    await state.set_state(
        FreeTextState.text
    )

    await call.message.answer(
        "✍️ Напишите текст.\n\n"
        "Если выпадет 777, он будет "
        "добавлен к сердечку.\n\n"
        "Максимум 128 символов."
    )


@dp.message(
    FreeTextState.text,
    F.text
)
async def receive_free_text(
    message: Message,
    state: FSMContext
):

    text = message.text.strip()

    if len(text) > 128:

        await message.answer(
            "❌ Максимум 128 символов."
        )

        return

    save_free_text(
        message.from_user.id,
        text
    )

    await state.clear()

    await message.answer(
        (
            "<b>✅ Текст сохранён!</b>\n\n"
            "Теперь нажмите "
            "«Получить бесплатно»."
        )
    )


# =========================================================
# START SPIN
# =========================================================

@dp.callback_query(
    F.data == "free_spin_start"
)
async def free_spin_start(
    call: CallbackQuery
):

    await call.answer()

    user_id = call.from_user.id

    # Сначала используем бесплатную прокрутку.

    if take_free_spin(user_id):

        await call.message.answer(
            "🎰 Используется бесплатная прокрутка!"
        )

        await send_slot(
            user_id
        )

        return

    # Обычная прокрутка стоит 2 Stars.

    payload = (
        f"free_spin:"
        f"{user_id}:"
        f"2:"
        f"{secrets.token_hex(12)}"
    )

    await bot.send_invoice(
        chat_id=user_id,
        title="🎰 Прокрутка",
        description=(
            "Одна прокрутка рулетки — 2 Stars."
        ),
        payload=payload,
        currency="XTR",
        prices=[
            LabeledPrice(
                label="Прокрутка",
                amount=2
            )
        ],
        provider_token=""
    )


# =========================================================
# SLOT
# =========================================================

async def send_slot(user_id):

    await bot.send_message(
        user_id,
        "<b>🎰 Рулетка запускается...</b>"
    )

    dice = await bot.send_dice(
        chat_id=user_id,
        emoji="🎰"
    )

    await asyncio.sleep(3)

    await process_slot(
        user_id,
        dice.dice.value
    )


def decode_slot(value):

    if value == 64:

        return (
            "7",
            "7",
            "7"
        )

    n = value - 1

    return (
        n & 3,
        (n >> 2) & 3,
        (n >> 4) & 3
    )


async def process_slot(
    user_id,
    value
):

    symbols = decode_slot(
        value
    )

    # 777

    if value == 64:

        await bot.send_message(
            user_id,
            "<b>🎉 777!</b>\n\n"
            "Вы выиграли ❤️ Сердечко!"
        )

        heart = one(
            """
            SELECT gift_id
            FROM gifts
            WHERE LOWER(title)
            IN ('сердце', 'сердечко')
            AND enabled=1
            LIMIT 1
            """
        )

        if not heart:

            await bot.send_message(
                user_id,
                (
                    "⚠️ Подарок «Сердечко» "
                    "ещё не настроен в каталоге."
                )
            )

            return

        text = get_free_text(
            user_id
        )

        try:

            kwargs = {
                "user_id": user_id,
                "gift_id": str(
                    heart["gift_id"]
                )
            }

            if text:
                kwargs["text"] = text

            await bot.send_gift(
                **kwargs
            )

        except Exception as error:

            await bot.send_message(
                user_id,
                (
                    "❌ Не удалось отправить "
                    "сердечко.\n\n"
                    f"<code>"
                    f"{html.escape(str(error))}"
                    f"</code>"
                )
            )

            return

        await bot.send_message(
            user_id,
            "<b>❤️ Сердечко отправлено "
            "в ваш профиль!</b>"
        )

        return

    # Три одинаковых

    if (
        symbols[0]
        == symbols[1]
        == symbols[2]
    ):

        add_free_spin(
            user_id
        )

        await bot.send_message(
            user_id,
            (
                "<b>🎉 Три одинаковых!</b>\n\n"
                "Вам начислена "
                "<b>1 бесплатная прокрутка</b> 🎰"
            )
        )

        return

    # Проигрыш

    await bot.send_message(
        user_id,
        "<b>😔 Ничего не выпало.</b>"
    )


# =========================================================
# ADMIN
# =========================================================

def is_owner(user_id):

    return user_id == OWNER_ID


def admin_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                button(
                    "Пользователи",
                    "admin_users",
                    "users"
                )
            ],
            [
                button(
                    "Подарки",
                    "admin_gifts",
                    "gift"
                )
            ],
            [
                button(
                    "Добавить подарок",
                    "admin_add",
                    "add"
                )
            ],
            [
                button(
                    "Вывести подарок",
                    "admin_withdraw",
                    "withdraw"
                )
            ],
            [
                button(
                    "Premium Emoji",
                    "admin_emojis",
                    "gifts"
                )
            ],
            [
                button(
                    "Баланс бота",
                    "admin_balance",
                    "topup"
                )
            ]
        ]
    )


@dp.message(Command("admin"))
async def admin(
    message: Message
):

    if not is_owner(
        message.from_user.id
    ):
        return

    await message.answer(
        "<b>⚙️ Панель владельца</b>",
        reply_markup=admin_menu()
    )


# =========================================================
# ADMIN USERS
# =========================================================

@dp.callback_query(
    F.data == "admin_users"
)
async def admin_users(
    call: CallbackQuery
):

    if not is_owner(
        call.from_user.id
    ):
        return

    await call.answer()

    users = rows(
        """
        SELECT *
        FROM users
        ORDER BY joined_at DESC
        LIMIT 100
        """
    )

    if not users:

        await call.message.answer(
            "Пользователей пока нет."
        )

        return

    keyboard = []

    for user in users:

        username = (
            "@"
            + user["username"]
            if user["username"]
            else "без username"
        )

        keyboard.append([
            InlineKeyboardButton(
                text=(
                    f"{username} | "
                    f"{user['user_id']}"
                ),
                callback_data=(
                    f"admin_user:"
                    f"{user['user_id']}"
                )
            )
        ])

    await call.message.answer(
        "<b>👥 Пользователи</b>\n\n"
        "Выберите пользователя:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=keyboard
        )
    )


@dp.callback_query(
    F.data.startswith("admin_user:")
)
async def admin_user(
    call: CallbackQuery
):

    if not is_owner(
        call.from_user.id
    ):
        return

    await call.answer()

    user_id = int(
        call.data.split(
            ":",
            1
        )[1]
    )

    user = one(
        """
        SELECT *
        FROM users
        WHERE user_id=?
        """,
        (user_id,)
    )

    if not user:
        return

    username = (
        "@"
        + user["username"]
        if user["username"]
        else "нет username"
    )

    await call.message.answer(
        (
            "<b>👤 Пользователь</b>\n\n"
            f"Username: "
            f"{html.escape(username)}\n"
            f"ID: <code>{user_id}</code>\n"
            f"Баланс: "
            f"<b>{user['balance']} ⭐</b>\n"
            f"Покупок: {user['purchases']}\n"
            f"Бесплатных прокруток: "
            f"{free_spins(user_id)}"
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    button(
                        "Прокрутить бесплатно",
                        f"admin_spin:{user_id}",
                        "roulette"
                    )
                ],
                [
                    button(
                        "Пользователи",
                        "admin_users",
                        "back"
                    )
                ]
            ]
        )
    )


# =========================================================
# ADMIN FREE SPIN
# =========================================================

@dp.callback_query(
    F.data.startswith("admin_spin:")
)
async def admin_spin(
    call: CallbackQuery
):

    if not is_owner(
        call.from_user.id
    ):
        return

    await call.answer(
        "Добавлено!"
    )

    user_id = int(
        call.data.split(
            ":",
            1
        )[1]
    )

    add_free_spin(
        user_id
    )

    await call.message.answer(
        (
            "🎰 Пользователю "
            f"<code>{user_id}</code> "
            "добавлена бесплатная прокрутка."
        )
    )

    try:

        await bot.send_message(
            user_id,
            (
                "<b>🎰 Вам выдали "
                "бесплатную прокрутку!</b>"
            )
        )

    except Exception:
        pass


# =========================================================
# ADMIN GIFTS
# =========================================================

@dp.callback_query(
    F.data == "admin_gifts"
)
async def admin_gifts(
    call: CallbackQuery
):

    if not is_owner(
        call.from_user.id
    ):
        return

    await call.answer()

    await sync_gifts()

    gifts = rows(
        """
        SELECT *
        FROM gifts
        ORDER BY price ASC
        """
    )

    keyboard = []

    for gift in gifts:

        status = (
            "🟢"
            if gift["enabled"]
            else "🔴"
        )

        keyboard.append([
            InlineKeyboardButton(
                text=(
                    f"{status} "
                    f"{gift['title']} — "
                    f"{gift['price']} ⭐"
                ),
                callback_data=(
                    f"toggle:"
                    f"{gift['gift_id']}"
                )
            )
        ])

    await call.message.answer(
        "<b>🎁 Каталог подарков</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=keyboard
        )
    )


@dp.callback_query(
    F.data.startswith("toggle:")
)
async def toggle_gift(
    call: CallbackQuery
):

    if not is_owner(
        call.from_user.id
    ):
        return

    gift_id = call.data.split(
        ":",
        1
    )[1]

    gift = one(
        """
        SELECT enabled
        FROM gifts
        WHERE gift_id=?
        """,
        (gift_id,)
    )

    if not gift:
        return

    new_status = (
        0
        if gift["enabled"]
        else 1
    )

    execute(
        """
        UPDATE gifts
        SET enabled=?
        WHERE gift_id=?
        """,
        (
            new_status,
            gift_id
        )
    )

    await call.answer(
        "Изменено."
    )


# =========================================================
# ADMIN ADD GIFT
# =========================================================

class AddGiftState(StatesGroup):

    gift_id = State()
    title = State()
    price = State()


@dp.callback_query(
    F.data == "admin_add"
)
async def admin_add(
    call: CallbackQuery,
    state: FSMContext
):

    if not is_owner(
        call.from_user.id
    ):
        return

    await call.answer()

    await state.set_state(
        AddGiftState.gift_id
    )

    await call.message.answer(
        "<b>Добавление подарка</b>\n\n"
        "Отправьте Gift ID.\n\n"
        "ID нужен только для работы API "
        "и пользователю не показывается."
    )


@dp.message(
    AddGiftState.gift_id,
    F.text
)
async def admin_add_id(
    message: Message,
    state: FSMContext
):

    await state.update_data(
        gift_id=message.text.strip()
    )

    await state.set_state(
        AddGiftState.title
    )

    await message.answer(
        "Введите название.\n\n"
        "Например: <code>Медведь</code>"
    )


@dp.message(
    AddGiftState.title,
    F.text
)
async def admin_add_title(
    message: Message,
    state: FSMContext
):

    title = message.text.strip()

    if len(title) > 64:

        await message.answer(
            "❌ Максимум 64 символа."
        )

        return

    await state.update_data(
        title=title
    )

    await state.set_state(
        AddGiftState.price
    )

    await message.answer(
        "Введите цену в Stars."
    )


@dp.message(
    AddGiftState.price,
    F.text
)
async def admin_add_price(
    message: Message,
    state: FSMContext
):

    try:

        price = int(
            message.text.strip()
        )

    except ValueError:

        await message.answer(
            "❌ Введите число."
        )

        return

    if price < 0:

        await message.answer(
            "❌ Цена не может быть отрицательной."
        )

        return

    data = await state.get_data()

    await state.clear()

    execute(
        """
        INSERT INTO gifts(
            gift_id,
            title,
            price,
            enabled,
            available
        )
        VALUES(?,?,?,?,?)

        ON CONFLICT(gift_id)
        DO UPDATE SET
            title=excluded.title,
            price=excluded.price,
            enabled=1,
            available=1
        """,
        (
            data["gift_id"],
            data["title"],
            price,
            1,
            1
        )
    )

    await message.answer(
        (
            "<b>✅ Подарок сохранён!</b>\n\n"
            f"Название: "
            f"<b>{html.escape(data['title'])}</b>\n"
            f"Цена: <b>{price} ⭐</b>"
        )
    )


# =========================================================
# ADMIN WITHDRAW
# =========================================================

@dp.callback_query(
    F.data == "admin_withdraw"
)
async def admin_withdraw(
    call: CallbackQuery
):

    if not is_owner(
        call.from_user.id
    ):
        return

    await call.answer()

    await sync_gifts()

    gifts = rows(
        """
        SELECT *
        FROM gifts
        WHERE enabled=1
        ORDER BY price ASC
        """
    )

    keyboard = []

    for gift in gifts:

        keyboard.append([
            InlineKeyboardButton(
                text=(
                    f"{gift['title']} — "
                    f"{gift['price']} ⭐"
                ),
                callback_data=(
                    f"withdraw:"
                    f"{gift['gift_id']}"
                )
            )
        ])

    await call.message.answer(
        "<b>📤 Вывод подарка</b>\n\n"
        "Подарок будет отправлен OWNER_ID.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=keyboard
        )
    )


@dp.callback_query(
    F.data.startswith("withdraw:")
)
async def withdraw(
    call: CallbackQuery
):

    if not is_owner(
        call.from_user.id
    ):
        return

    gift_id = call.data.split(
        ":",
        1
    )[1]

    gift = one(
        """
        SELECT *
        FROM gifts
        WHERE gift_id=?
        """,
        (gift_id,)
    )

    if not gift:
        return

    try:

        await bot.send_gift(
            user_id=OWNER_ID,
            gift_id=str(
                gift["gift_id"]
            )
        )

    except Exception as error:

        await call.message.answer(
            (
                "❌ Не удалось вывести подарок.\n\n"
                f"<code>"
                f"{html.escape(str(error))}"
                f"</code>"
            )
        )

        return

    await call.answer(
        "Отправлено!"
    )

    await call.message.answer(
        (
            "<b>✅ Подарок отправлен OWNER_ID.</b>\n\n"
            f"{html.escape(gift['title'])}"
        )
    )


# =========================================================
# ADMIN PREMIUM EMOJI
# =========================================================

class EmojiState(StatesGroup):

    waiting = State()


@dp.callback_query(
    F.data == "admin_emojis"
)
async def admin_emojis(
    call: CallbackQuery
):

    if not is_owner(
        call.from_user.id
    ):
        return

    await call.answer()

    keyboard = []

    for key, title in EMOJI_NAMES.items():

        status = (
            "🟢"
            if get_emoji(key)
            else "⚪"
        )

        keyboard.append([
            InlineKeyboardButton(
                text=(
                    f"{status} {title}"
                ),
                callback_data=(
                    f"emoji:{key}"
                )
            )
        ])

    await call.message.answer(
        (
            "<b>✨ Premium Emoji</b>\n\n"
            "Выберите элемент и отправьте "
            "Premium Emoji отдельным сообщением."
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=keyboard
        )
    )


@dp.callback_query(
    F.data.startswith("emoji:")
)
async def choose_emoji(
    call: CallbackQuery,
    state: FSMContext
):

    if not is_owner(
        call.from_user.id
    ):
        return

    await call.answer()

    key = call.data.split(
        ":",
        1
    )[1]

    await state.update_data(
        emoji_key=key
    )

    await state.set_state(
        EmojiState.waiting
    )

    await call.message.answer(
        (
            f"<b>{EMOJI_NAMES[key]}</b>\n\n"
            "Отправьте Premium Emoji."
        )
    )


@dp.message(
    EmojiState.waiting
)
async def receive_emoji(
    message: Message,
    state: FSMContext
):

    if not is_owner(
        message.from_user.id
    ):
        return

    emoji_id: Optional[str] = None

    if message.entities:

        for entity in message.entities:

            if entity.type == "custom_emoji":

                emoji_id = (
                    entity.custom_emoji_id
                )

                break

    if not emoji_id:

        await message.answer(
            "❌ В сообщении нет Premium Emoji."
        )

        return

    data = await state.get_data()

    await state.clear()

    set_emoji(
        data["emoji_key"],
        emoji_id
    )

    await message.answer(
        (
            "<b>✅ Premium Emoji сохранён!</b>\n\n"
            f"Элемент: "
            f"<b>{EMOJI_NAMES[data['emoji_key']]}</b>"
        )
    )


# =========================================================
# ADMIN BALANCE
# =========================================================

@dp.callback_query(
    F.data == "admin_balance"
)
async def admin_balance(
    call: CallbackQuery
):

    if not is_owner(
        call.from_user.id
    ):
        return

    await call.answer()

    try:

        result = await bot.get_my_star_balance()

        await call.message.answer(
            (
                "<b>⭐ Баланс бота</b>\n\n"
                f"<b>{result.amount} ⭐</b>"
            )
        )

    except Exception as error:

        await call.message.answer(
            (
                "❌ Ошибка:\n\n"
                f"<code>"
                f"{html.escape(str(error))}"
                f"</code>"
            )
        )


# =========================================================
# START BOT
# =========================================================

async def main():

    print(
        "================================"
    )
    print(
        "GIFT BOT STARTED"
    )
    print(
        f"OWNER_ID: {OWNER_ID}"
    )
    print(
        "ROULETTE PRICE: 2 XTR"
    )
    print(
        "================================"
    )

    await sync_gifts()

    await dp.start_polling(
        bot
    )


if __name__ == "__main__":

    asyncio.run(
        main()
    )