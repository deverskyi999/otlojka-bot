import asyncio
import html
import os
import secrets
import sqlite3
from contextlib import closing

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
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# +2 Stars к цене каждого подарка
PURCHASE_FEE = 2

if not BOT_TOKEN:
    raise RuntimeError("Не указан BOT_TOKEN")

if not OWNER_ID:
    raise RuntimeError("Не указан OWNER_ID")


# =========================================================
# BOT
# =========================================================

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher(storage=MemoryStorage())


# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(
    "gift_bot.db",
    check_same_thread=False
)

db.row_factory = sqlite3.Row

db.execute("PRAGMA journal_mode=WAL")

db.executescript("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS gifts (
    gift_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    price INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    available_now INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    gift_id TEXT NOT NULL,
    gift_title TEXT NOT NULL,
    gift_price INTEGER NOT NULL,
    fee INTEGER NOT NULL,
    description TEXT,
    status TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    amount INTEGER NOT NULL,
    payload TEXT UNIQUE NOT NULL,
    telegram_charge_id TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ui_emoji (
    key TEXT PRIMARY KEY,
    custom_emoji_id TEXT
);
""")

db.commit()


# =========================================================
# DB HELPERS
# =========================================================

def query(sql, params=()):
    with closing(db.cursor()) as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def query_one(sql, params=()):
    with closing(db.cursor()) as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()


def execute(sql, params=()):
    with closing(db.cursor()) as cursor:
        cursor.execute(sql, params)
        db.commit()
        return cursor.lastrowid


def ensure_user(user_id: int):
    execute(
        """
        INSERT OR IGNORE INTO users(user_id)
        VALUES(?)
        """,
        (user_id,)
    )


def get_balance(user_id: int):

    ensure_user(user_id)

    row = query_one(
        """
        SELECT balance
        FROM users
        WHERE user_id=?
        """,
        (user_id,)
    )

    return int(row["balance"])


def add_balance(user_id: int, amount: int):

    ensure_user(user_id)

    execute(
        """
        UPDATE users
        SET balance = balance + ?
        WHERE user_id=?
        """,
        (amount, user_id)
    )


def remove_balance(user_id: int, amount: int):

    ensure_user(user_id)

    cursor = db.cursor()

    cursor.execute(
        """
        UPDATE users
        SET balance = balance - ?
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

    return cursor.rowcount == 1


# =========================================================
# PREMIUM EMOJI
# =========================================================

def get_emoji(key):

    row = query_one(
        """
        SELECT custom_emoji_id
        FROM ui_emoji
        WHERE key=?
        """,
        (key,)
    )

    if row:
        return row["custom_emoji_id"]

    return None


def set_emoji(key, emoji_id):

    execute(
        """
        INSERT INTO ui_emoji(
            key,
            custom_emoji_id
        )
        VALUES(?, ?)

        ON CONFLICT(key)
        DO UPDATE SET
            custom_emoji_id=excluded.custom_emoji_id
        """,
        (
            key,
            emoji_id
        )
    )


def remove_emoji(key):

    execute(
        """
        DELETE FROM ui_emoji
        WHERE key=?
        """,
        (key,)
    )


def button(
    text,
    callback,
    emoji_key=None
):

    kwargs = {
        "text": text,
        "callback_data": callback
    }

    if emoji_key:

        emoji_id = get_emoji(emoji_key)

        if emoji_id:

            kwargs[
                "icon_custom_emoji_id"
            ] = emoji_id

    return InlineKeyboardButton(
        **kwargs
    )


# =========================================================
# KEYBOARDS
# =========================================================

def main_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                button(
                    "Подарок",
                    "gifts",
                    "button_gift"
                )
            ],

            [
                button(
                    "Пополнить баланс",
                    "topup",
                    "button_topup"
                ),

                button(
                    "Пожертвовать проекту",
                    "donate",
                    "button_donate"
                )
            ]

        ]
    )


def confirm_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                button(
                    "Отправить подарок",
                    "gift_confirm",
                    "button_confirm"
                )
            ],

            [
                button(
                    "Изменить текст",
                    "gift_edit",
                    "button_edit"
                )
            ],

            [
                button(
                    "Отмена",
                    "home",
                    "button_cancel"
                )
            ]

        ]
    )


def admin_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                button(
                    "Баланс бота",
                    "admin_balance",
                    "admin_balance"
                )
            ],

            [
                button(
                    "Синхронизировать подарки",
                    "admin_sync",
                    "admin_sync"
                )
            ],

            [
                button(
                    "Управление подарками",
                    "admin_gifts",
                    "admin_gifts"
                )
            ],

            [
                button(
                    "Premium Emoji",
                    "admin_emoji",
                    "admin_emoji"
                )
            ],

            [
                button(
                    "Статистика",
                    "admin_stats",
                    "admin_stats"
                )
            ],

            [
                button(
                    "Закрыть",
                    "home",
                    "button_cancel"
                )
            ]

        ]
    )


# =========================================================
# STATES
# =========================================================

class GiftState(StatesGroup):

    waiting_text = State()


class TopupState(StatesGroup):

    waiting_amount = State()


class DonateState(StatesGroup):

    waiting_amount = State()


class EmojiState(StatesGroup):

    waiting_emoji = State()


# =========================================================
# TEMP GIFT SESSIONS
# =========================================================

gift_sessions = {}


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start(message: Message):

    ensure_user(
        message.from_user.id
    )

    await message.answer(

        "<b>Магазин подарков</b>\n\n"

        f"Ваш баланс: "
        f"<b>{get_balance(message.from_user.id)} ⭐</b>\n\n"

        "Выберите действие:",

        reply_markup=main_keyboard()
    )


# =========================================================
# HOME
# =========================================================

@dp.callback_query(F.data == "home")
async def home(
    call: CallbackQuery,
    state: FSMContext
):

    await call.answer()

    await state.clear()

    gift_sessions.pop(
        call.from_user.id,
        None
    )

    await call.message.answer(

        "<b>Главное меню</b>\n\n"

        f"Баланс: "
        f"<b>{get_balance(call.from_user.id)} ⭐</b>",

        reply_markup=main_keyboard()
    )


# =========================================================
# GET GIFTS
# =========================================================

@dp.callback_query(F.data == "gifts")
async def gifts(call: CallbackQuery):

    await call.answer()

    rows = query(
        """
        SELECT *
        FROM gifts

        WHERE enabled=1
        AND available_now=1

        ORDER BY price ASC
        """
    )

    if not rows:

        await call.message.answer(
            "Сейчас доступных подарков нет.",
            reply_markup=main_keyboard()
        )

        return

    buttons = []

    for gift in rows:

        buttons.append([

            button(

                f"{gift['title']} • "
                f"{gift['price']} ⭐",

                f"gift:{gift['gift_id']}",

                "button_gift_item"
            )

        ])

    buttons.append([

        button(
            "Назад",
            "home",
            "button_back"
        )

    ])

    await call.message.answer(

        "<b>Выберите подарок</b>\n\n"

        f"К цене подарка добавляется "
        f"<b>{PURCHASE_FEE} ⭐</b> комиссии.",

        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


# =========================================================
# CHOOSE GIFT
# =========================================================

@dp.callback_query(
    F.data.startswith("gift:")
)
async def choose_gift(
    call: CallbackQuery
):

    await call.answer()

    gift_id = call.data.split(
        ":",
        1
    )[1]

    gift = query_one(
        """
        SELECT *
        FROM gifts

        WHERE gift_id=?
        AND enabled=1
        AND available_now=1
        """,
        (gift_id,)
    )

    if not gift:

        await call.message.answer(
            "Этот подарок сейчас недоступен.",
            reply_markup=main_keyboard()
        )

        return

    gift_sessions[
        call.from_user.id
    ] = {

        "gift_id":
            gift["gift_id"],

        "title":
            gift["title"],

        "price":
            int(gift["price"]),

        "description":
            None
    }

    total = (
        int(gift["price"])
        +
        PURCHASE_FEE
    )

    await call.message.answer(

        f"<b>{html.escape(gift['title'])}</b>\n\n"

        f"Цена: <b>{gift['price']} ⭐</b>\n"
        f"Комиссия: <b>{PURCHASE_FEE} ⭐</b>\n"
        f"Итого: <b>{total} ⭐</b>\n\n"

        "Напишите текст для подарка "
        "или выберите вариант ниже.",

        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[

                [
                    button(
                        "Написать текст",
                        "gift_write",
                        "button_write"
                    )
                ],

                [
                    button(
                        "Без текста",
                        "gift_no_text",
                        "button_no_text"
                    )
                ],

                [
                    button(
                        "Назад",
                        "gifts",
                        "button_back"
                    )
                ]

            ]
        )
    )


# =========================================================
# WRITE TEXT
# =========================================================

@dp.callback_query(
    F.data == "gift_write"
)
async def gift_write(
    call: CallbackQuery,
    state: FSMContext
):

    await call.answer()

    if call.from_user.id not in gift_sessions:

        await call.message.answer(
            "Сначала выберите подарок."
        )

        return

    await state.set_state(
        GiftState.waiting_text
    )

    await call.message.answer(

        "<b>Введите текст подарка</b>\n\n"

        "Отправьте его обычным сообщением.\n"
        "Максимум: <b>128 символов</b>."
    )


# =========================================================
# RECEIVE TEXT
# =========================================================

@dp.message(
    GiftState.waiting_text,
    F.text
)
async def receive_text(
    message: Message,
    state: FSMContext
):

    text = message.text.strip()

    if len(text) > 128:

        await message.answer(
            "Текст слишком длинный.\n"
            "Максимум 128 символов."
        )

        return

    if not text:

        await message.answer(
            "Текст пустой."
        )

        return

    data = gift_sessions.get(
        message.from_user.id
    )

    if not data:

        await state.clear()

        await message.answer(
            "Сессия покупки закончилась."
        )

        return

    data["description"] = text

    await state.clear()

    total = (
        data["price"]
        +
        PURCHASE_FEE
    )

    await message.answer(

        "<b>Текст принят!</b>\n\n"

        f"Подарок: "
        f"<b>{html.escape(data['title'])}</b>\n"

        f"Цена: "
        f"<b>{data['price']} ⭐</b>\n"

        f"Комиссия: "
        f"<b>{PURCHASE_FEE} ⭐</b>\n"

        f"Итого: "
        f"<b>{total} ⭐</b>\n\n"

        f"Текст:\n"
        f"<i>{html.escape(text)}</i>\n\n"

        f"Ваш баланс: "
        f"<b>{get_balance(message.from_user.id)} ⭐</b>",

        reply_markup=confirm_keyboard()
    )


@dp.message(
    GiftState.waiting_text
)
async def invalid_text(
    message: Message
):

    await message.answer(
        "Отправьте текст обычным сообщением."
    )


# =========================================================
# NO TEXT
# =========================================================

@dp.callback_query(
    F.data == "gift_no_text"
)
async def gift_no_text(
    call: CallbackQuery,
    state: FSMContext
):

    await call.answer()

    await state.clear()

    data = gift_sessions.get(
        call.from_user.id
    )

    if not data:

        await call.message.answer(
            "Сначала выберите подарок."
        )

        return

    data["description"] = None

    total = (
        data["price"]
        +
        PURCHASE_FEE
    )

    await call.message.answer(

        f"<b>{html.escape(data['title'])}</b>\n\n"

        f"Цена: <b>{data['price']} ⭐</b>\n"
        f"Комиссия: <b>{PURCHASE_FEE} ⭐</b>\n"
        f"Итого: <b>{total} ⭐</b>\n\n"

        "Подарок будет отправлен без текста.",

        reply_markup=confirm_keyboard()
    )


# =========================================================
# EDIT TEXT
# =========================================================

@dp.callback_query(
    F.data == "gift_edit"
)
async def gift_edit(
    call: CallbackQuery,
    state: FSMContext
):

    await call.answer()

    await state.set_state(
        GiftState.waiting_text
    )

    await call.message.answer(
        "Отправьте новый текст."
    )


# =========================================================
# SEND GIFT
# =========================================================

@dp.callback_query(
    F.data == "gift_confirm"
)
async def gift_confirm(
    call: CallbackQuery,
    state: FSMContext
):

    await call.answer()

    user_id = call.from_user.id

    data = gift_sessions.get(
        user_id
    )

    if not data:

        await call.message.answer(
            "Сессия покупки закончилась."
        )

        return

    total = (
        data["price"]
        +
        PURCHASE_FEE
    )

    current_balance = get_balance(
        user_id
    )

    if current_balance < total:

        await call.message.answer(

            "<b>Недостаточно Stars.</b>\n\n"

            f"Нужно: <b>{total} ⭐</b>\n"
            f"Есть: <b>{current_balance} ⭐</b>\n\n"

            "Пополните баланс.",

            reply_markup=main_keyboard()
        )

        return

    # Проверяем, существует ли подарок сейчас.
    try:

        available = (
            await bot.get_available_gifts()
        )

        real_gift = next(
            (
                g for g in available.gifts
                if str(g.id)
                ==
                str(data["gift_id"])
            ),
            None
        )

    except Exception as error:

        await call.message.answer(
            "Не удалось проверить доступность подарка."
        )

        print(error)

        return

    if real_gift is None:

        execute(
            """
            UPDATE gifts

            SET available_now=0

            WHERE gift_id=?
            """,
            (data["gift_id"],)
        )

        await call.message.answer(

            "Этот подарок больше нельзя "
            "отправить через Telegram.\n\n"

            "Ваш баланс не изменён.",

            reply_markup=main_keyboard()
        )

        return

    # Сначала отправляем подарок.
    try:

        kwargs = {

            "user_id":
                user_id,

            "gift_id":
                data["gift_id"]
        }

        if data["description"]:

            kwargs["text"] = (
                data["description"]
            )

        await bot.send_gift(
            **kwargs
        )

    except Exception as error:

        await call.message.answer(

            "Подарок не отправлен.\n\n"

            "Ваш внутренний баланс "
            "не изменён.\n\n"

            f"<code>{html.escape(str(error))}</code>"
        )

        return

    # Только после успешной отправки
    # списываем внутренний баланс.

    success = remove_balance(
        user_id,
        total
    )

    if not success:

        execute(

            """
            INSERT INTO orders(

                user_id,
                gift_id,
                gift_title,
                gift_price,
                fee,
                description,
                status

            )
            VALUES(?,?,?,?,?,?,?)
            """,

            (
                user_id,
                data["gift_id"],
                data["title"],
                data["price"],
                PURCHASE_FEE,
                data["description"],
                "sent_balance_error"
            )
        )

        await call.message.answer(
            "Подарок отправлен, "
            "но произошла ошибка списания."
        )

        return

    order_id = execute(

        """
        INSERT INTO orders(

            user_id,
            gift_id,
            gift_title,
            gift_price,
            fee,
            description,
            status

        )
        VALUES(?,?,?,?,?,?,?)
        """,

        (
            user_id,
            data["gift_id"],
            data["title"],
            data["price"],
            PURCHASE_FEE,
            data["description"],
            "completed"
        )
    )

    gift_sessions.pop(
        user_id,
        None
    )

    await state.clear()

    await call.message.answer(

        "<b>Подарок отправлен!</b>\n\n"

        f"Подарок: "
        f"<b>{html.escape(data['title'])}</b>\n"

        f"Списано: "
        f"<b>{total} ⭐</b>\n"

        f"Осталось: "
        f"<b>{get_balance(user_id)} ⭐</b>\n\n"

        f"Заказ: "
        f"<code>#{order_id}</code>",

        reply_markup=main_keyboard()
    )


# =========================================================
# TOP UP
# =========================================================

@dp.callback_query(
    F.data == "topup"
)
async def topup(
    call: CallbackQuery,
    state: FSMContext
):

    await call.answer()

    await state.set_state(
        TopupState.waiting_amount
    )

    await call.message.answer(

        "<b>Пополнение баланса</b>\n\n"

        "Введите количество Stars.\n"
        "Минимум: 2."
    )


@dp.message(
    TopupState.waiting_amount,
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
            "Введите число."
        )

        return

    if amount < 2:

        await message.answer(
            "Минимальная сумма — 2 ⭐."
        )

        return

    if amount > 100000:

        await message.answer(
            "Максимум — 100000 ⭐."
        )

        return

    await state.clear()

    payload = (
        f"topup:"
        f"{message.from_user.id}:"
        f"{amount}:"
        f"{secrets.token_hex(8)}"
    )

    await bot.send_invoice(

        chat_id=
            message.from_user.id,

        title=
            "Пополнение баланса",

        description=
            f"Пополнение внутреннего баланса "
            f"на {amount} Stars.",

        payload=
            payload,

        currency=
            "XTR",

        prices=[
            LabeledPrice(
                label="Stars",
                amount=amount
            )
        ],

        provider_token=""
    )


# =========================================================
# DONATE
# =========================================================

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

        "<b>Пожертвование проекту</b>\n\n"

        "Введите количество Stars.\n"
        "Минимум: 1."
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
            "Минимум — 1 ⭐."
        )

        return

    if amount > 100000:

        await message.answer(
            "Максимум — 100000 ⭐."
        )

        return

    await state.clear()

    payload = (

        f"donate:"
        f"{message.from_user.id}:"
        f"{amount}:"
        f"{secrets.token_hex(8)}"
    )

    await bot.send_invoice(

        chat_id=
            message.from_user.id,

        title=
            "Пожертвование проекту",

        description=
            f"Поддержка проекта на {amount} Stars.",

        payload=
            payload,

        currency=
            "XTR",

        prices=[
            LabeledPrice(
                label="Пожертвование",
                amount=amount
            )
        ],

        provider_token=""
    )


# =========================================================
# PRE-CHECKOUT
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

    payload = payment.invoice_payload

    parts = payload.split(":")

    if len(parts) != 4:

        return

    kind = parts[0]

    try:

        user_id = int(parts[1])
        amount = int(parts[2])

    except ValueError:

        return

    if user_id != message.from_user.id:

        return

    # Защита от повторной обработки.
    exists = query_one(

        """
        SELECT id
        FROM payments
        WHERE payload=?
        """,

        (payload,)
    )

    if exists:

        return

    execute(

        """
        INSERT INTO payments(

            user_id,
            kind,
            amount,
            payload,
            telegram_charge_id

        )
        VALUES(?,?,?,?,?)
        """,

        (
            user_id,
            kind,
            amount,
            payload,
            payment.telegram_payment_charge_id
        )
    )

    if kind == "topup":

        add_balance(
            user_id,
            amount
        )

        await message.answer(

            "<b>Баланс пополнен!</b>\n\n"

            f"+{amount} ⭐\n"

            f"Баланс: "
            f"<b>{get_balance(user_id)} ⭐</b>",

            reply_markup=main_keyboard()
        )

    elif kind == "donate":

        await message.answer(

            "<b>Спасибо за поддержку!</b>\n\n"

            f"Вы пожертвовали "
            f"<b>{amount} ⭐</b>.",

            reply_markup=main_keyboard()
        )


# =========================================================
# ADMIN
# =========================================================

def is_owner(user_id):

    return user_id == OWNER_ID


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

        "<b>Панель владельца</b>\n\n"

        "Доступ разрешён только OWNER_ID.",

        reply_markup=admin_keyboard()
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

        await call.answer(
            "Нет доступа.",
            show_alert=True
        )

        return

    await call.answer()

    try:

        balance_data = (
            await bot.get_my_star_balance()
        )

        stars = balance_data.amount

        await call.message.answer(

            "<b>Баланс бота</b>\n\n"

            f"Telegram Stars: "
            f"<b>{stars} ⭐</b>"
        )

    except Exception as error:

        await call.message.answer(
            f"Ошибка:\n<code>{html.escape(str(error))}</code>"
        )


# =========================================================
# ADMIN SYNC GIFTS
# =========================================================

async def sync_gifts():

    result = (
        await bot.get_available_gifts()
    )

    current_ids = set()

    for gift in result.gifts:

        gift_id = str(
            gift.id
        )

        current_ids.add(
            gift_id
        )

        # Bot API может не дать название.
        # Поэтому используем ID как fallback.

        title = (
            getattr(
                gift,
                "name",
                None
            )
            or
            f"Telegram Gift {gift_id}"
        )

        old = query_one(

            """
            SELECT gift_id
            FROM gifts
            WHERE gift_id=?
            """,

            (gift_id,)
        )

        if old:

            execute(

                """
                UPDATE gifts

                SET price=?,
                    available_now=1

                WHERE gift_id=?
                """,

                (
                    gift.star_count,
                    gift_id
                )
            )

        else:

            execute(

                """
                INSERT INTO gifts(

                    gift_id,
                    title,
                    price,
                    enabled,
                    available_now

                )
                VALUES(?,?,?,?,?)
                """,

                (
                    gift_id,
                    title,
                    gift.star_count,
                    1,
                    1
                )
            )

    # Старые подарки НЕ удаляем.
    # Просто помечаем как временно недоступные.

    if current_ids:

        placeholders = ",".join(
            "?"
            for _ in current_ids
        )

        db.execute(

            f"""
            UPDATE gifts

            SET available_now=0

            WHERE gift_id
            NOT IN ({placeholders})
            """,

            tuple(current_ids)
        )

        db.commit()


@dp.callback_query(
    F.data == "admin_sync"
)
async def admin_sync(
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

    try:

        await sync_gifts()

        count = query_one(

            """
            SELECT COUNT(*)
            c
            FROM gifts
            WHERE available_now=1
            """
        )["c"]

        await call.message.answer(

            "<b>Синхронизация завершена.</b>\n\n"

            f"Доступных подарков: "
            f"<b>{count}</b>"
        )

    except Exception as error:

        await call.message.answer(

            "Ошибка синхронизации:\n\n"

            f"<code>{html.escape(str(error))}</code>"
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

        await call.answer(
            "Нет доступа.",
            show_alert=True
        )

        return

    await call.answer()

    rows = query(

        """
        SELECT *
        FROM gifts
        ORDER BY price ASC
        LIMIT 50
        """
    )

    if not rows:

        await call.message.answer(
            "Каталог пуст."
        )

        return

    buttons = []

    for gift in rows:

        status = (
            "ON"
            if gift["enabled"]
            else "OFF"
        )

        available = (
            "доступен"
            if gift["available_now"]
            else "нет сейчас"
        )

        buttons.append([

            InlineKeyboardButton(

                text=(
                    f"{gift['title']} • "
                    f"{gift['price']} ⭐ • "
                    f"{status}"
                ),

                callback_data=(
                    f"adm_gift:"
                    f"{gift['gift_id']}"
                )
            )

        ])

    await call.message.answer(

        "<b>Управление подарками</b>\n\n"

        "Нажми на подарок, чтобы "
        "включить или выключить его.",

        reply_markup=
        InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


@dp.callback_query(
    F.data.startswith("adm_gift:")
)
async def admin_gift_toggle(
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

    gift_id = call.data.split(
        ":",
        1
    )[1]

    gift = query_one(

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

    await call.message.answer(

        f"<b>{html.escape(gift['title'])}</b>\n\n"

        f"Теперь: "
        f"<b>{'ON' if new_status else 'OFF'}</b>"
    )


# =========================================================
# PREMIUM EMOJI ADMIN
# =========================================================

EMOJI_TARGETS = {

    "button_gift":
        "Кнопка Подарок",

    "button_topup":
        "Кнопка Пополнить баланс",

    "button_donate":
        "Кнопка Пожертвовать",

    "button_gift_item":
        "Кнопки подарков",

    "button_confirm":
        "Кнопка Отправить подарок",

    "button_edit":
        "Кнопка Изменить текст",

    "button_write":
        "Кнопка Написать текст",

    "button_no_text":
        "Кнопка Без текста",

    "button_cancel":
        "Кнопка Отмена",

    "button_back":
        "Кнопка Назад",

    "admin_balance":
        "Кнопка Баланс бота",

    "admin_sync":
        "Кнопка Синхронизация",

    "admin_gifts":
        "Кнопка Управление подарками",

    "admin_emoji":
        "Кнопка Premium Emoji",

    "admin_stats":
        "Кнопка Статистика"
}


@dp.callback_query(
    F.data == "admin_emoji"
)
async def admin_emoji(
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

    buttons = []

    for key, name in EMOJI_TARGETS.items():

        current = get_emoji(
            key
        )

        status = (
            "✓"
            if current
            else "—"
        )

        buttons.append([

            InlineKeyboardButton(

                text=(
                    f"{status} {name}"
                ),

                callback_data=(
                    f"setemoji:"
                    f"{key}"
                )
            )

        ])

    await call.message.answer(

        "<b>Premium Emoji</b>\n\n"

        "Выберите кнопку, затем "
        "отправьте мне один "
        "Premium/Custom Emoji.",

        reply_markup=
        InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


@dp.callback_query(
    F.data.startswith("setemoji:")
)
async def set_emoji_target(
    call: CallbackQuery,
    state: FSMContext
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

    key = call.data.split(
        ":",
        1
    )[1]

    await state.update_data(
        emoji_key=key
    )

    await state.set_state(
        EmojiState.waiting_emoji
    )

    await call.message.answer(

        f"<b>{html.escape(EMOJI_TARGETS[key])}</b>\n\n"

        "Теперь отправь сюда "
        "один Premium/Custom Emoji.\n\n"

        "Я автоматически получу "
        "его custom_emoji_id."
    )


@dp.message(
    EmojiState.waiting_emoji
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

            "Не нашёл Custom Emoji.\n\n"

            "Отправь именно Premium/Custom "
            "Emoji отдельным сообщением."
        )

        return

    data = await state.get_data()

    key = data.get(
        "emoji_key"
    )

    set_emoji(
        key,
        emoji_id
    )

    await state.clear()

    await message.answer(

        "<b>Premium Emoji установлен!</b>\n\n"

        f"Место: "
        f"{html.escape(EMOJI_TARGETS[key])}\n"

        f"ID:\n"
        f"<code>{emoji_id}</code>",

        reply_markup=admin_keyboard()
    )


# =========================================================
# REMOVE EMOJI
# =========================================================

@dp.message(
    Command("removeemoji")
)
async def removeemoji(
    message: Message
):

    if not is_owner(
        message.from_user.id
    ):

        return

    parts = message.text.split()

    if len(parts) != 2:

        await message.answer(

            "Использование:\n"

            "<code>/removeemoji button_gift</code>"
        )

        return

    key = parts[1]

    if key not in EMOJI_TARGETS:

        await message.answer(
            "Такого места нет."
        )

        return

    remove_emoji(
        key
    )

    await message.answer(
        "Premium Emoji удалён."
    )


# =========================================================
# ADMIN STATS
# =========================================================

@dp.callback_query(
    F.data == "admin_stats"
)
async def admin_stats(
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

    users = query_one(
        """
        SELECT COUNT(*) c
        FROM users
        """
    )["c"]

    orders = query_one(
        """
        SELECT COUNT(*) c
        FROM orders
        """
    )["c"]

    completed = query_one(
        """
        SELECT COUNT(*) c
        FROM orders
        WHERE status='completed'
        """
    )["c"]

    payments = query_one(
        """
        SELECT COALESCE(
            SUM(amount),
            0
        ) s
        FROM payments
        """
    )["s"]

    await call.message.answer(

        "<b>Статистика</b>\n\n"

        f"Пользователей: "
        f"<b>{users}</b>\n"

        f"Заказов: "
        f"<b>{orders}</b>\n"

        f"Успешных подарков: "
        f"<b>{completed}</b>\n"

        f"Получено Stars: "
        f"<b>{payments} ⭐</b>"
    )


# =========================================================
# STARTUP
# =========================================================

async def startup():

    try:

        await sync_gifts()

        print(
            "Подарки синхронизированы."
        )

    except Exception as error:

        print(
            "Не удалось синхронизировать подарки:",
            error
        )


async def main():

    await startup()

    print(
        "Gift Bot запущен."
    )

    await dp.start_polling(
        bot
    )


if __name__ == "__main__":

    asyncio.run(
        main()
    )