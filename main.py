import asyncio
import html
import os
import secrets
import sqlite3

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    PreCheckoutQuery,
)


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

OWNER_ID = int(
    os.getenv("OWNER_ID", "0")
)

# Реальный Telegram Gift ID сердечка.
# В Railway Variables:
#
# HEART_GIFT_ID=123456789
#
HEART_GIFT_ID = os.getenv(
    "HEART_GIFT_ID",
    ""
).strip()


if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не установлен"
    )

if OWNER_ID == 0:
    raise RuntimeError(
        "OWNER_ID не установлен"
    )


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

db.execute(
    "PRAGMA journal_mode=WAL"
)

db.executescript(
    """

    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        balance INTEGER NOT NULL DEFAULT 0,
        purchases INTEGER NOT NULL DEFAULT 0,
        joined_at TEXT DEFAULT CURRENT_TIMESTAMP
    );


    CREATE TABLE IF NOT EXISTS gifts (
        gift_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        price INTEGER NOT NULL DEFAULT 0,
        enabled INTEGER NOT NULL DEFAULT 1,
        available INTEGER NOT NULL DEFAULT 1
    );


    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        user_id INTEGER NOT NULL,

        gift_id TEXT NOT NULL,

        gift_title TEXT NOT NULL,

        price INTEGER NOT NULL,

        text TEXT,

        status TEXT NOT NULL,

        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );


    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        user_id INTEGER NOT NULL,

        amount INTEGER NOT NULL,

        payment_type TEXT NOT NULL,

        payload TEXT UNIQUE NOT NULL,

        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );


    CREATE TABLE IF NOT EXISTS free_spin_data (
        user_id INTEGER PRIMARY KEY,

        text TEXT DEFAULT '',

        spins INTEGER NOT NULL DEFAULT 0
    );


    CREATE TABLE IF NOT EXISTS emojis (
        name TEXT PRIMARY KEY,

        emoji_id TEXT
    );

    """
)

db.commit()


# =========================================================
# DATABASE HELPERS
# =========================================================

def execute(
    sql,
    params=()
):
    cur = db.cursor()

    cur.execute(
        sql,
        params
    )

    db.commit()

    return cur.lastrowid


def one(
    sql,
    params=()
):
    cur = db.cursor()

    cur.execute(
        sql,
        params
    )

    return cur.fetchone()


def all_rows(
    sql,
    params=()
):
    cur = db.cursor()

    cur.execute(
        sql,
        params
    )

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


def get_balance(
    user_id
):

    row = one(
        """
        SELECT balance

        FROM users

        WHERE user_id=?
        """,
        (user_id,)
    )

    if not row:
        return 0

    return row["balance"]


def add_balance(
    user_id,
    amount
):

    execute(
        """
        UPDATE users

        SET balance =
            balance + ?

        WHERE user_id=?
        """,
        (
            amount,
            user_id
        )
    )


def take_balance(
    user_id,
    amount
):

    cur = db.cursor()

    cur.execute(
        """
        UPDATE users

        SET balance =
            balance - ?

        WHERE user_id=?

        AND balance >= ?
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

def get_emoji(
    name
):

    row = one(
        """
        SELECT emoji_id

        FROM emojis

        WHERE name=?
        """,
        (name,)
    )

    if not row:
        return None

    return row["emoji_id"]


def set_emoji(
    name,
    emoji_id
):

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


def button(
    text,
    callback_data,
    emoji_name=None
):

    kwargs = {
        "text": text,
        "callback_data": callback_data
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
# /START
# =========================================================

@dp.message(
    CommandStart()
)
async def start(
    message: Message
):

    save_user(
        message.from_user
    )

    await message.answer(

        "<b>🎁 Добро пожаловать!</b>\n\n"

        "Здесь можно покупать Telegram-подарки "
        "за внутренние Stars.\n\n"

        f"Ваш баланс: "
        f"<b>{get_balance(message.from_user.id)} ⭐</b>",

        reply_markup=main_menu()
    )


# =========================================================
# BALANCE COMMAND
# =========================================================

@dp.message(
    Command("balance")
)
async def balance_command(
    message: Message
):

    save_user(
        message.from_user
    )

    await message.answer(

        "💰 Ваш баланс:\n\n"

        f"<b>{get_balance(message.from_user.id)} ⭐</b>"
    )


# =========================================================
# GIFTS
# =========================================================

@dp.callback_query(
    F.data == "gifts"
)
async def gifts(
    call: CallbackQuery
):

    await call.answer()

    rows = all_rows(
        """
        SELECT *

        FROM gifts

        WHERE enabled=1

        AND available=1

        ORDER BY price ASC
        """
    )

    if not rows:

        await call.message.answer(
            "🎁 Сейчас подарков нет."
        )

        return

    keyboard = []

    for gift in rows:

        keyboard.append([

            button(
                f"{gift['title']} — "
                f"{gift['price']} ⭐",

                f"gift:{gift['gift_id']}",

                "gift_item"
            )

        ])

    keyboard.append([

        button(
            "Назад",
            "back_main",
            "back"
        )

    ])

    await call.message.answer(

        "<b>🎁 Подарки</b>\n\n"
        "Выберите подарок:",

        reply_markup=
        InlineKeyboardMarkup(
            inline_keyboard=keyboard
        )
    )


# =========================================================
# GIFT SESSION
# =========================================================

class GiftState(
    StatesGroup
):

    waiting_text = State()


# =========================================================
# SELECT GIFT
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

        AND available=1
        """,
        (gift_id,)
    )

    if not gift:

        await call.message.answer(
            "❌ Этот подарок недоступен."
        )

        return

    await state.update_data(

        gift_id=
            gift["gift_id"],

        title=
            gift["title"],

        price=
            gift["price"],

        text=""
    )

    await state.clear()

    await call.message.answer(

        f"<b>🎁 {html.escape(gift['title'])}</b>\n\n"

        f"Цена: "
        f"<b>{gift['price']} ⭐</b>\n\n"

        "Добавить свой текст?",

        reply_markup=
        InlineKeyboardMarkup(
            inline_keyboard=[

                [
                    button(
                        "Написать текст",
                        f"gift_text:{gift_id}",
                        "write"
                    )
                ],

                [
                    button(
                        "Без текста",
                        f"gift_no_text:{gift_id}",
                        "no_text"
                    )
                ],

                [
                    button(
                        "Назад",
                        "gifts",
                        "back"
                    )
                ]

            ]
        )
    )


# =========================================================
# WRITE GIFT TEXT
# =========================================================

@dp.callback_query(
    F.data.startswith("gift_text:")
)
async def ask_gift_text(
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
        """,
        (gift_id,)
    )

    if not gift:
        return

    await state.update_data(

        gift_id=
            gift["gift_id"],

        title=
            gift["title"],

        price=
            gift["price"]
    )

    await state.set_state(
        GiftState.waiting_text
    )

    await call.message.answer(

        "<b>✍️ Напишите текст</b>\n\n"

        "Текст будет добавлен к подарку.\n"
        "Максимум 128 символов."
    )


@dp.message(
    GiftState.waiting_text,
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

    await confirm_gift(
        message,
        data,
        text
    )


# =========================================================
# NO TEXT
# =========================================================

@dp.callback_query(
    F.data.startswith("gift_no_text:")
)
async def gift_without_text(
    call: CallbackQuery
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

        AND available=1
        """,
        (gift_id,)
    )

    if not gift:
        return

    await confirm_gift(
        call.message,
        {
            "gift_id":
                gift["gift_id"],

            "title":
                gift["title"],

            "price":
                gift["price"]
        },
        ""
    )


# =========================================================
# CONFIRM GIFT
# =========================================================

async def confirm_gift(
    message,
    data,
    text
):

    user_id = message.chat.id

    price = int(
        data["price"]
    )

    current_balance = get_balance(
        user_id
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[

            [
                button(
                    "🎁 Отправить",
                    "confirm_gift_send",
                    "confirm"
                )
            ],

            [
                button(
                    "Назад",
                    "gifts",
                    "back"
                )
            ]

        ]
    )

    # сохраняем заказ в FSM нельзя,
    # поэтому используем БД pending order

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
            price,
            text,
            "pending"
        )
    )

    await message.answer(

        "<b>Проверка заказа</b>\n\n"

        f"🎁 Подарок: "
        f"<b>{html.escape(data['title'])}</b>\n"

        f"Цена: <b>{price} ⭐</b>\n"

        f"Ваш баланс: "
        f"<b>{current_balance} ⭐</b>\n\n"

        + (
            f"Текст:\n"
            f"<i>{html.escape(text)}</i>"
            if text
            else
            "Текст: нет"
        ),

        reply_markup=keyboard
    )


# =========================================================
# SEND PAID GIFT
# =========================================================

@dp.callback_query(
    F.data == "confirm_gift_send"
)
async def confirm_gift_send(
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

            "❌ Недостаточно Stars.\n\n"

            f"Нужно: <b>{price} ⭐</b>\n"

            f"Есть: "
            f"<b>{get_balance(user_id)} ⭐</b>"
        )

        return

    # Сначала пытаемся отправить подарок.
    # Деньги списываем только после успеха.

    try:

        kwargs = {

            "user_id":
                user_id,

            "gift_id":
                str(order["gift_id"])
        }

        if order["text"]:

            kwargs["text"] = (
                order["text"]
            )

        await bot.send_gift(
            **kwargs
        )

    except Exception as error:

        await call.message.answer(

            "❌ Telegram не разрешил "
            "отправить этот подарок.\n\n"

            f"<code>"
            f"{html.escape(str(error))}"
            f"</code>"
        )

        return

    if not take_balance(
        user_id,
        price
    ):

        await call.message.answer(
            "❌ Подарок отправлен, "
            "но не удалось списать "
            "внутренний баланс."
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

        SET purchases =
            purchases + 1

        WHERE user_id=?
        """,
        (user_id,)
    )

    await call.message.answer(

        "<b>🎁 Подарок отправлен!</b>\n\n"

        f"{html.escape(order['gift_title'])}\n"

        f"Списано: <b>{price} ⭐</b>\n"

        f"Баланс: "
        f"<b>{get_balance(user_id)} ⭐</b>",

        reply_markup=main_menu()
    )


# =========================================================
# TOP UP
# =========================================================

class TopUpState(
    StatesGroup
):

    waiting_amount = State()


@dp.callback_query(
    F.data == "topup"
)
async def topup(
    call: CallbackQuery,
    state: FSMContext
):

    await call.answer()

    await state.set_state(
        TopUpState.waiting_amount
    )

    await call.message.answer(
        "<b>💰 Пополнение баланса</b>\n\n"
        "Введите количество Stars:"
    )


@dp.message(
    TopUpState.waiting_amount,
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
            "❌ Введите целое число."
        )

        return

    if amount < 1:

        await message.answer(
            "❌ Минимум 1 ⭐."
        )

        return

    if amount > 10000:

        await message.answer(
            "❌ Максимум 10000 ⭐ за один платёж."
        )

        return

    await state.clear()

    payload = (
        f"topup:"
        f"{message.from_user.id}:"
        f"{amount}:"
        f"{secrets.token_hex(10)}"
    )

    await bot.send_invoice(

        chat_id=
            message.from_user.id,

        title=
            "Пополнение баланса",

        description=
            f"Пополнение внутреннего баланса "
            f"на {amount} Telegram Stars.",

        payload=
            payload,

        currency=
            "XTR",

        prices=[
            LabeledPrice(
                label=
                    "Пополнение",
                amount=
                    amount
            )
        ],

        provider_token=""
    )


# =========================================================
# DONATE
# =========================================================

class DonateState(
    StatesGroup
):

    waiting_amount = State()


@dp.callback_query(
    F.data == "donate"
)
async def donate(
    call: CallbackQuery,
    state: FSMContext
):

    await call.answer()

    await state.set_state(
        DonateState.waiting_amount
    )

    await call.message.answer(

        "<b>💎 Пожертвовать проекту</b>\n\n"

        "Введите количество Stars:"
    )


@dp.message(
    DonateState.waiting_amount,
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
            "Введите число."
        )

        return

    if amount < 1:

        await message.answer(
            "Минимум 1 ⭐."
        )

        return

    if amount > 10000:

        await message.answer(
            "Максимум 10000 ⭐."
        )

        return

    await state.clear()

    payload = (
        f"donate:"
        f"{message.from_user.id}:"
        f"{amount}:"
        f"{secrets.token_hex(10)}"
    )

    await bot.send_invoice(

        chat_id=
            message.from_user.id,

        title=
            "Пожертвование проекту",

        description=
            f"Пожертвование "
            f"{amount} Telegram Stars.",

        payload=
            payload,

        currency=
            "XTR",

        prices=[
            LabeledPrice(
                label=
                    "Пожертвование",
                amount=
                    amount
            )
        ],

        provider_token=""
    )


# =========================================================
# PAYMENT CHECK
# =========================================================

@dp.pre_checkout_query()
async def pre_checkout(
    query: PreCheckoutQuery
):

    await query.answer(
        ok=True
    )


# =========================================================
# SUCCESSFUL PAYMENT
# =========================================================

@dp.message(
    F.successful_payment
)
async def successful_payment(
    message: Message
):

    payment = (
        message.successful_payment
    )

    payload = (
        payment.invoice_payload
    )

    parts = payload.split(
        ":"
    )

    if len(parts) != 4:
        return

    payment_type = parts[0]

    try:

        user_id = int(
            parts[1]
        )

        amount = int(
            parts[2]
        )

    except ValueError:

        return

    if user_id != message.from_user.id:
        return

    # Защита от повторной обработки

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

    # Пополнение внутреннего баланса

    if payment_type == "topup":

        add_balance(
            user_id,
            amount
        )

        await message.answer(

            "<b>✅ Баланс пополнен!</b>\n\n"

            f"+{amount} ⭐\n"

            f"Баланс: "
            f"<b>{get_balance(user_id)} ⭐</b>",

            reply_markup=main_menu()
        )

        return

    # Пожертвование

    if payment_type == "donate":

        await message.answer(

            "<b>❤️ Спасибо за поддержку!</b>\n\n"

            f"Пожертвовано: "
            f"<b>{amount} ⭐</b>",

            reply_markup=main_menu()
        )

        return

    # Бесплатная рулетка

    if payment_type == "free_spin":

        await run_free_spin(
            message
        )

        return


# =========================================================
# FREE SPIN
# =========================================================

class FreeGiftState(
    StatesGroup
):

    waiting_text = State()


def save_free_text(
    user_id,
    text
):

    execute(
        """
        INSERT INTO free_spin_data(
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


def get_free_text(
    user_id
):

    row = one(
        """
        SELECT text

        FROM free_spin_data

        WHERE user_id=?
        """,
        (user_id,)
    )

    if not row:
        return ""

    return row["text"] or ""


def get_free_spins(
    user_id
):

    row = one(
        """
        SELECT spins

        FROM free_spin_data

        WHERE user_id=?
        """,
        (user_id,)
    )

    if not row:
        return 0

    return row["spins"]


def add_free_spin(
    user_id
):

    execute(
        """
        INSERT INTO free_spin_data(
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


def take_free_spin(
    user_id
):

    cur = db.cursor()

    cur.execute(
        """
        UPDATE free_spin_data

        SET spins=spins-1

        WHERE user_id=?

        AND spins>0
        """,
        (user_id,)
    )

    db.commit()

    return cur.rowcount > 0


# =========================================================
# FREE GIFT BUTTON
# =========================================================

@dp.callback_query(
    F.data == "free_gift"
)
async def free_gift(
    call: CallbackQuery,
    state: FSMContext
):

    await call.answer()

    spins = get_free_spins(
        call.from_user.id
    )

    await state.clear()

    await call.message.answer(

        "<b>🎰 Получить подарок бесплатно</b>\n\n"

        "Стоимость одной попытки — "
        "<b>5 ⭐</b>.\n\n"

        "Правила:\n"

        "🎰 Три одинаковых символа → "
        "<b>+1 бесплатная прокрутка</b>\n"

        "💖 777 → "
        "<b>бесплатное Сердечко</b>\n"

        "❌ Остальные результаты → "
        "<b>ничего</b>\n\n"

        f"Бесплатных прокруток: "
        f"<b>{spins}</b>",

        reply_markup=
        InlineKeyboardMarkup(
            inline_keyboard=[

                [
                    button(
                        "🎰 Поехали!",
                        "free_spin_start",
                        "free"
                    )
                ],

                [
                    button(
                        "Назад",
                        "back_main",
                        "back"
                    )
                ]

            ]
        )
    )


# =========================================================
# FREE SPIN START
# =========================================================

@dp.callback_query(
    F.data == "free_spin_start"
)
async def free_spin_start(
    call: CallbackQuery,
    state: FSMContext
):

    await call.answer()

    await state.clear()

    user_id = call.from_user.id

    # Есть бесплатная прокрутка

    if take_free_spin(user_id):

        await call.message.answer(
            "🎰 Использована бесплатная прокрутка."
        )

        await send_slot(
            user_id
        )

        return

    # Нет бесплатной —
    # создаём оплату 5 Stars

    payload = (
        f"free_spin:"
        f"{user_id}:"
        f"5:"
        f"{secrets.token_hex(10)}"
    )

    await bot.send_invoice(

        chat_id=user_id,

        title="🎰 Прокрутка рулетки",

        description=(
            "Одна попытка рулетки — 5 Telegram Stars."
        ),

        payload=payload,

        currency="XTR",

        prices=[
            LabeledPrice(
                label="Прокрутка",
                amount=5
            )
        ],

        provider_token=""
    )


# =========================================================
# SEND SLOT
# =========================================================

async def send_slot(
    user_id
):

    await bot.send_message(
        user_id,

        "<b>🎰 Рулетка запущена!</b>\n\n"
        "Смотрим результат..."
    )

    dice_message = await bot.send_dice(
        chat_id=user_id,
        emoji="🎰"
    )

    value = (
        dice_message.dice.value
    )

    # Telegram генерирует результат
    # на своей стороне.

    await asyncio.sleep(2)

    await process_slot_result(
        user_id,
        value
    )


# =========================================================
# SLOT RESULT
# =========================================================

def slot_symbols(
    value
):

    if value == 64:

        return (
            "7",
            "7",
            "7"
        )

    # Согласно алгоритму Telegram:
    # три 2-bit значения.

    a = (
        (value - 1)
        & 3
    )

    b = (
        ((value - 1) >> 2)
        & 3
    )

    c = (
        ((value - 1) >> 4)
        & 3
    )

    return (
        a,
        b,
        c
    )


async def process_slot_result(
    user_id,
    value
):

    symbols = slot_symbols(
        value
    )

    # 777

    if value == 64:

        await bot.send_message(
            user_id,

            "<b>🎉 777!</b>\n\n"
            "Вы выиграли "
            "<b>❤️ Сердечко</b> бесплатно!"
        )

        if not HEART_GIFT_ID:

            await bot.send_message(
                user_id,

                "⚠️ HEART_GIFT_ID не установлен "
                "в Railway Variables.\n\n"
                "Подарок не отправлен."
            )

            return

        text = get_free_text(
            user_id
        )

        try:

            kwargs = {

                "user_id":
                    user_id,

                "gift_id":
                    HEART_GIFT_ID
            }

            if text:

                kwargs["text"] = text

            await bot.send_gift(
                **kwargs
            )

        except Exception as error:

            await bot.send_message(

                user_id,

                "❌ Telegram не разрешил "
                "отправить сердечко.\n\n"

                f"<code>"
                f"{html.escape(str(error))}"
                f"</code>"
            )

            return

        await bot.send_message(

            user_id,

            "<b>❤️ Сердечко отправлено!</b>\n\n"

            + (
                f"Текст: "
                f"<i>{html.escape(text)}</i>"
                if text
                else
                "Без текста."
            )
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

            "<b>🎉 Три одинаковых!</b>\n\n"

            "Вы выиграли "
            "<b>1 бесплатную прокрутку</b> 🎰"
        )

        return

    # Проигрыш

    await bot.send_message(

        user_id,

        "<b>😔 Ничего не выпало.</b>\n\n"

        "Попробуйте ещё раз."
    )


# =========================================================
# FREE GIFT TEXT
# =========================================================

@dp.callback_query(
    F.data == "free_text"
)
async def free_text_button(
    call: CallbackQuery,
    state: FSMContext
):

    await call.answer()

    await state.set_state(
        FreeGiftState.waiting_text
    )

    await call.message.answer(
        "✍️ Напишите текст для "
        "возможного Сердечка.\n\n"
        "Максимум 128 символов.\n"
        "Чтобы отправить без текста — напишите <code>-</code>."
    )


@dp.message(
    FreeGiftState.waiting_text,
    F.text
)
async def receive_free_text(
    message: Message,
    state: FSMContext
):

    text = message.text.strip()

    if text == "-":
        text = ""

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

        "<b>✅ Текст сохранён!</b>\n\n"

        "Теперь нажмите «Получить бесплатно» "
        "и запустите рулетку."
    )


# =========================================================
# BACK
# =========================================================

@dp.callback_query(
    F.data == "back_main"
)
async def back_main(
    call: CallbackQuery,
    state: FSMContext
):

    await call.answer()

    await state.clear()

    await call.message.answer(

        "<b>Главное меню</b>",

        reply_markup=main_menu()
    )


# =========================================================
# ADMIN
# =========================================================

def is_owner(
    user_id
):

    return user_id == OWNER_ID


def admin_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                button(
                    "Пользователи",
                    "admin_users"
                )
            ],

            [
                button(
                    "Подарки",
                    "admin_gifts"
                )
            ],

            [
                button(
                    "Добавить подарок",
                    "admin_add_gift"
                )
            ],

            [
                button(
                    "Вывести подарок",
                    "admin_withdraw"
                )
            ],

            [
                button(
                    "Premium Emoji",
                    "admin_emojis"
                )
            ],

            [
                button(
                    "Баланс бота",
                    "admin_balance"
                )
            ]

        ]
    )


@dp.message(
    Command("admin")
)
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

        await call.answer(
            "Нет доступа.",
            show_alert=True
        )

        return

    await call.answer()

    users = all_rows(
        """
        SELECT *

        FROM users

        ORDER BY joined_at DESC

        LIMIT 100
        """
    )

    if not users:

        await call.message.answer(
            "Пользователей нет."
        )

        return

    text = (
        "<b>👥 Пользователи</b>\n\n"
    )

    buttons = []

    for user in users:

        username = (
            "@"
            + user["username"]
            if user["username"]
            else "без username"
        )

        text += (

            f"{html.escape(username)}\n"

            f"ID: "
            f"<code>{user['user_id']}</code>\n"

            f"Баланс: "
            f"<b>{user['balance']} ⭐</b>\n"

            f"Покупок: "
            f"{user['purchases']}\n\n"
        )

        buttons.append([

            InlineKeyboardButton(

                text=(
                    f"{username} "
                    f"({user['user_id']})"
                ),

                callback_data=(
                    f"admin_user:"
                    f"{user['user_id']}"
                )
            )

        ])

    await call.message.answer(

        text,

        reply_markup=
        InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


# =========================================================
# ADMIN USER DETAILS
# =========================================================

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

        await call.message.answer(
            "Пользователь не найден."
        )

        return

    username = (
        "@"
        + user["username"]
        if user["username"]
        else "нет username"
    )

    await call.message.answer(

        "<b>👤 Пользователь</b>\n\n"

        f"Username: "
        f"{html.escape(username)}\n"

        f"Имя: "
        f"{html.escape(user['first_name'] or '')}\n"

        f"Telegram ID: "
        f"<code>{user['user_id']}</code>\n"

        f"Баланс: "
        f"<b>{user['balance']} ⭐</b>\n"

        f"Покупок: "
        f"{user['purchases']}\n"

        f"В боте с: "
        f"{user['joined_at']}"
    )


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

    gifts = all_rows(
        """
        SELECT *

        FROM gifts

        ORDER BY price ASC
        """
    )

    if not gifts:

        await call.message.answer(
            "Подарков пока нет."
        )

        return

    text = (
        "<b>🎁 Каталог подарков</b>\n\n"
    )

    buttons = []

    for gift in gifts:

        status = (
            "🟢"
            if gift["enabled"]
            else "🔴"
        )

        text += (

            f"{status} "
            f"<b>{html.escape(gift['title'])}</b> — "
            f"{gift['price']} ⭐\n"
        )

        buttons.append([

            InlineKeyboardButton(

                text=(
                    f"{status} "
                    f"{gift['title']}"
                ),

                callback_data=(
                    f"toggle_gift:"
                    f"{gift['gift_id']}"
                )
            )

        ])

    await call.message.answer(

        text,

        reply_markup=
        InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


# =========================================================
# TOGGLE GIFT
# =========================================================

@dp.callback_query(
    F.data.startswith("toggle_gift:")
)
async def toggle_gift(
    call: CallbackQuery
):

    if not is_owner(
        call.from_user.id
    ):

        return

    await call.answer()

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

    new_value = (
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
            new_value,
            gift_id
        )
    )

    await call.message.answer(
        "✅ Статус подарка изменён."
    )


# =========================================================
# ADD GIFT
# =========================================================

class AddGiftState(
    StatesGroup
):

    title = State()

    gift_id = State()

    price = State()


@dp.callback_query(
    F.data == "admin_add_gift"
)
async def admin_add_gift(
    call: CallbackQuery,
    state: FSMContext
):

    if not is_owner(
        call.from_user.id
    ):

        return

    await call.answer()

    await state.set_state(
        AddGiftState.title
    )

    await call.message.answer(
        "<b>Добавление подарка</b>\n\n"
        "Введите название.\n\n"
        "Например:\n"
        "<code>Медведь</code>"
    )


@dp.message(
    AddGiftState.title,
    F.text
)
async def add_gift_title(
    message: Message,
    state: FSMContext
):

    title = message.text.strip()

    if len(title) > 64:

        await message.answer(
            "Максимум 64 символа."
        )

        return

    await state.update_data(
        title=title
    )

    await state.set_state(
        AddGiftState.gift_id
    )

    await message.answer(
        "Теперь отправьте "
        "<b>Telegram Gift ID</b>.\n\n"
        "Он нужен боту технически, "
        "пользователь его видеть не будет."
    )


@dp.message(
    AddGiftState.gift_id,
    F.text
)
async def add_gift_id(
    message: Message,
    state: FSMContext
):

    gift_id = message.text.strip()

    if not gift_id.isdigit():

        await message.answer(
            "Gift ID должен быть числом."
        )

        return

    await state.update_data(
        gift_id=gift_id
    )

    await state.set_state(
        AddGiftState.price
    )

    await message.answer(
        "Введите цену в Stars.\n\n"
        "Например: <code>15</code>"
    )


@dp.message(
    AddGiftState.price,
    F.text
)
async def add_gift_price(
    message: Message,
    state: FSMContext
):

    try:

        price = int(
            message.text.strip()
        )

    except ValueError:

        await message.answer(
            "Введите число."
        )

        return

    if price < 1:

        await message.answer(
            "Цена должна быть больше 0."
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

        "<b>✅ Подарок добавлен!</b>\n\n"

        f"Название: "
        f"<b>{html.escape(data['title'])}</b>\n"

        f"Цена: <b>{price} ⭐</b>"
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

    gifts = all_rows(
        """
        SELECT *

        FROM gifts

        WHERE available=1

        ORDER BY price ASC
        """
    )

    if not gifts:

        await call.message.answer(
            "Нет подарков для вывода."
        )

        return

    buttons = []

    for gift in gifts:

        buttons.append([

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

        "Подарок будет отправлен "
        "на профиль OWNER_ID.\n\n"

        "Списания с внутреннего "
        "пользовательского баланса нет.",

        reply_markup=
        InlineKeyboardMarkup(
            inline_keyboard=buttons
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
        """,
        (gift_id,)
    )

    if not gift:

        await call.message.answer(
            "Подарок не найден."
        )

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

            "❌ Telegram не разрешил "
            "вывести подарок.\n\n"

            f"<code>"
            f"{html.escape(str(error))}"
            f"</code>"
        )

        return

    await call.message.answer(

        "<b>✅ Подарок отправлен OWNER_ID!</b>\n\n"

        f"Подарок: "
        f"<b>{html.escape(gift['title'])}</b>"
    )


# =========================================================
# ADMIN PREMIUM EMOJI
# =========================================================

EMOJI_NAMES = {

    "gifts":
        "Подарки",

    "free":
        "Получить бесплатно",

    "donate":
        "Пожертвовать",

    "gift_item":
        "Подарки каталога",

    "write":
        "Написать текст",

    "no_text":
        "Без текста",

    "confirm":
        "Отправить",

    "back":
        "Назад"

}


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

    buttons = []

    for key, title in EMOJI_NAMES.items():

        status = (
            "🟢"
            if get_emoji(key)
            else "⚪"
        )

        buttons.append([

            InlineKeyboardButton(

                text=(
                    f"{status} {title}"
                ),

                callback_data=(
                    f"setemoji:"
                    f"{key}"
                )
            )

        ])

    await call.message.answer(

        "<b>✨ Premium Emoji</b>\n\n"

        "Выберите кнопку.\n"
        "После этого отправьте "
        "Premium Emoji отдельным сообщением.",

        reply_markup=
        InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


class EmojiState(
    StatesGroup
):

    waiting = State()


@dp.callback_query(
    F.data.startswith("setemoji:")
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

        f"<b>{EMOJI_NAMES[key]}</b>\n\n"

        "Отправьте Premium Emoji "
        "отдельным сообщением."
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

    emoji_id = None

    if message.entities:

        for entity in message.entities:

            if entity.type == "custom_emoji":

                emoji_id = (
                    entity.custom_emoji_id
                )

                break

    if not emoji_id:

        await message.answer(
            "❌ Я не нашёл Custom Emoji "
            "в этом сообщении."
        )

        return

    data = await state.get_data()

    await state.clear()

    set_emoji(
        data["emoji_key"],
        emoji_id
    )

    await message.answer(

        "<b>✅ Premium Emoji установлен!</b>\n\n"

        f"Кнопка: "
        f"<b>{EMOJI_NAMES[data['emoji_key']]}</b>\n"

        f"ID: <code>{emoji_id}</code>"
    )


# =========================================================
# ADMIN BOT BALANCE
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

        result = (
            await bot.get_my_star_balance()
        )

        await call.message.answer(

            "<b>⭐ Баланс бота</b>\n\n"

            f"<b>{result.amount} ⭐</b>"
        )

    except Exception as error:

        await call.message.answer(

            "❌ Не удалось получить баланс.\n\n"

            f"<code>"
            f"{html.escape(str(error))}"
            f"</code>"
        )


# =========================================================
# RUN
# =========================================================

async def main():

    print(
        "================================="
    )

    print(
        "Gift Bot started"
    )

    print(
        f"OWNER_ID: {OWNER_ID}"
    )

    print(
        "================================="
    )

    await dp.start_polling(
        bot
    )


if __name__ == "__main__":

    asyncio.run(
        main()
    )