import asyncio
import os
import sqlite3

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

# =========================================================
# НАСТРОЙКИ
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "ВСТАВЬ_ТОКЕН_БОТА_СЮДА")

if BOT_TOKEN == "ВСТАВЬ_ТОКЕН_БОТА_СЮДА":
    raise RuntimeError("Укажи BOT_TOKEN")

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher(storage=MemoryStorage())

# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect("gifts.db")
db.row_factory = sqlite3.Row

db.execute("""
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    gift_id TEXT NOT NULL,
    gift_name TEXT,
    price INTEGER,
    description TEXT,
    status TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

db.commit()


# =========================================================
# СОСТОЯНИЯ
# =========================================================

class GiftStates(StatesGroup):
    waiting_text = State()


# =========================================================
# ВРЕМЕННЫЕ ДАННЫЕ
# =========================================================

user_gifts = {}


# =========================================================
# КЛАВИАТУРЫ
# =========================================================

def main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎁 Подарок",
                    callback_data="open_gifts"
                )
            ]
        ]
    )


def text_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Написать свой текст",
                    callback_data="gift_text"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚫 Без текста",
                    callback_data="gift_no_text"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="gift_cancel"
                )
            ]
        ]
    )


def confirm_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Отправить подарок",
                    callback_data="gift_confirm"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="gift_cancel"
                )
            ]
        ]
    )


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🎁 <b>Подарки Telegram</b>\n\n"
        "Выбери подарок, добавь свой текст и отправь его прямо "
        "на Telegram-профиль.",
        reply_markup=main_keyboard()
    )


# =========================================================
# ПОЛУЧАЕМ ДОСТУПНЫЕ ПОДАРКИ
# =========================================================

@dp.callback_query(F.data == "open_gifts")
async def open_gifts(callback: CallbackQuery):

    await callback.answer()

    try:
        gifts = await bot.get_available_gifts()

    except Exception as e:
        await callback.message.answer(
            "❌ Не удалось получить список подарков.\n\n"
            f"<code>{e}</code>"
        )
        return

    if not gifts.gifts:
        await callback.message.answer(
            "😔 Сейчас доступных подарков нет."
        )
        return

    buttons = []

    # Показываем до 20 подарков
    for gift in gifts.gifts[:20]:

        # В Bot API у подарка есть id и star_count
        price = gift.star_count

        name = getattr(gift, "name", None)

        if not name:
            name = "🎁 Telegram Gift"

        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{name} — ⭐ {price}",
                    callback_data=f"gift:{gift.id}"
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="❌ Закрыть",
                callback_data="gift_cancel"
            )
        ]
    )

    await callback.message.answer(
        "🎁 <b>Выберите подарок:</b>\n\n"
        "Стоимость указана в Telegram Stars.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


# =========================================================
# ВЫБОР ПОДАРКА
# =========================================================

@dp.callback_query(F.data.startswith("gift:"))
async def choose_gift(callback: CallbackQuery):

    await callback.answer()

    gift_id = callback.data.split(":", 1)[1]

    try:
        gifts = await bot.get_available_gifts()

    except Exception as e:
        await callback.message.answer(
            f"❌ Ошибка получения подарков:\n<code>{e}</code>"
        )
        return

    selected = None

    for gift in gifts.gifts:
        if gift.id == gift_id:
            selected = gift
            break

    if selected is None:
        await callback.message.answer(
            "❌ Этот подарок больше недоступен."
        )
        return

    price = selected.star_count
    name = getattr(selected, "name", None) or "🎁 Telegram Gift"

    user_gifts[callback.from_user.id] = {
        "gift_id": selected.id,
        "gift_name": name,
        "price": price,
        "description": None
    }

    await callback.message.answer(
        f"🎁 <b>{name}</b>\n"
        f"💰 Цена: <b>{price} ⭐</b>\n\n"
        "Добавить описание к подарку?",
        reply_markup=text_keyboard()
    )


# =========================================================
# ПОЛЬЗОВАТЕЛЬ ХОЧЕТ НАПИСАТЬ ТЕКСТ
# =========================================================

@dp.callback_query(F.data == "gift_text")
async def gift_text(callback: CallbackQuery, state: FSMContext):

    await callback.answer()

    if callback.from_user.id not in user_gifts:
        await callback.message.answer(
            "❌ Сначала выберите подарок."
        )
        return

    await state.set_state(GiftStates.waiting_text)

    await callback.message.answer(
        "✏️ <b>Напишите текст для подарка.</b>\n\n"
        "Максимум — 128 символов.\n\n"
        "Например:\n"
        "<i>С днём рождения! 🎉</i>"
    )


# =========================================================
# ПОЛУЧАЕМ ТЕКСТ
# =========================================================

@dp.message(GiftStates.waiting_text)
async def receive_text(message: Message, state: FSMContext):

    text = message.text or ""

    if not text:
        await message.answer(
            "❌ Отправьте именно текст."
        )
        return

    if len(text) > 128:
        await message.answer(
            "❌ Текст слишком длинный.\n"
            "Максимальная длина — 128 символов."
        )
        return

    data = user_gifts.get(message.from_user.id)

    if not data:
        await state.clear()

        await message.answer(
            "❌ Сессия подарка закончилась. "
            "Выберите подарок заново."
        )
        return

    data["description"] = text

    await state.clear()

    await show_confirmation(message, data)


# =========================================================
# БЕЗ ТЕКСТА
# =========================================================

@dp.callback_query(F.data == "gift_no_text")
async def gift_no_text(callback: CallbackQuery):

    await callback.answer()

    data = user_gifts.get(callback.from_user.id)

    if not data:
        await callback.message.answer(
            "❌ Сначала выберите подарок."
        )
        return

    data["description"] = None

    await show_confirmation(
        callback.message,
        data
    )


# =========================================================
# ПОДТВЕРЖДЕНИЕ
# =========================================================

async def show_confirmation(message: Message, data: dict):

    description = data["description"]

    if description:
        text = (
            f"🎁 <b>{data['gift_name']}</b>\n\n"
            f"💰 Цена: <b>{data['price']} ⭐</b>\n"
            f"📝 Текст:\n"
            f"<i>{description}</i>\n\n"
            "Отправить подарок?"
        )
    else:
        text = (
            f"🎁 <b>{data['gift_name']}</b>\n\n"
            f"💰 Цена: <b>{data['price']} ⭐</b>\n"
            "📝 Без текста\n\n"
            "Отправить подарок?"
        )

    await message.answer(
        text,
        reply_markup=confirm_keyboard()
    )


# =========================================================
# ОТПРАВКА ПОДАРКА
# =========================================================

@dp.callback_query(F.data == "gift_confirm")
async def gift_confirm(
    callback: CallbackQuery,
    state: FSMContext
):

    await callback.answer()

    user_id = callback.from_user.id

    data = user_gifts.get(user_id)

    if not data:
        await callback.message.answer(
            "❌ Подарок не выбран."
        )
        return

    gift_id = data["gift_id"]
    gift_name = data["gift_name"]
    price = data["price"]
    description = data["description"]

    # -----------------------------------------------------
    # 1. Проверяем настоящий баланс Stars бота
    # -----------------------------------------------------

    try:
        balance = await bot.get_my_star_balance()

    except Exception as e:
        await callback.message.answer(
            "❌ Не удалось проверить баланс бота.\n\n"
            f"<code>{e}</code>"
        )
        return

    # В StarAmount Telegram возвращает amount
    bot_stars = balance.amount

    if bot_stars < price:

        await callback.message.answer(
            "❌ <b>Недостаточно Stars у бота.</b>\n\n"
            f"Баланс бота: <b>{bot_stars} ⭐</b>\n"
            f"Цена подарка: <b>{price} ⭐</b>"
        )

        return

    # -----------------------------------------------------
    # 2. Записываем заказ как pending
    # -----------------------------------------------------

    cursor = db.execute(
        """
        INSERT INTO orders
        (
            user_id,
            gift_id,
            gift_name,
            price,
            description,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            gift_id,
            gift_name,
            price,
            description,
            "pending"
        )
    )

    order_id = cursor.lastrowid

    db.commit()

    # -----------------------------------------------------
    # 3. Отправляем настоящий Telegram Gift
    # -----------------------------------------------------

    try:

        await bot.send_gift(
            user_id=user_id,
            gift_id=gift_id,
            text=description
        )

    except Exception as e:

        db.execute(
            """
            UPDATE orders
            SET status = ?
            WHERE id = ?
            """,
            ("failed", order_id)
        )

        db.commit()

        await callback.message.answer(
            "❌ <b>Не удалось отправить подарок.</b>\n\n"
            f"<code>{e}</code>\n\n"
            "Stars при ошибке отправки не должны "
            "списываться Telegram."
        )

        return

    # -----------------------------------------------------
    # 4. Успешно
    # -----------------------------------------------------

    db.execute(
        """
        UPDATE orders
        SET status = ?
        WHERE id = ?
        """,
        ("completed", order_id)
    )

    db.commit()

    # Удаляем временный выбор
    user_gifts.pop(user_id, None)

    await state.clear()

    await callback.message.answer(
        "🎉 <b>Подарок отправлен!</b>\n\n"
        f"🎁 {gift_name}\n"
        f"💰 Потрачено: <b>{price} ⭐</b>\n"
        f"🆔 Заказ: <code>#{order_id}</code>\n\n"
        "Подарок отправлен прямо в ваш Telegram-профиль."
    )


# =========================================================
# ОТМЕНА
# =========================================================

@dp.callback_query(F.data == "gift_cancel")
async def gift_cancel(
    callback: CallbackQuery,
    state: FSMContext
):

    await callback.answer()

    user_gifts.pop(callback.from_user.id, None)

    await state.clear()

    await callback.message.answer(
        "❌ Отправка подарка отменена.",
        reply_markup=main_keyboard()
    )


# =========================================================
# ЗАПУСК
# =========================================================

async def main():

    print("🎁 Gift Bot запущен!")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())