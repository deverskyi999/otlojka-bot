# -*- coding: utf-8 -*-
"""
mine.py — единый файл Telegram-бота с мини-играми в стиле Minecraft.
Все модули собраны в одном файле для удобства заливки на GitHub / Railway.
Настройки (токен, ADMIN_ID и игровые константы) — в соседнем файле config.py.

Запуск: python mine.py
"""

from aiogram import Bot, Dispatcher
from aiogram import Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, LabeledPrice, PreCheckoutQuery,
    InlineKeyboardMarkup, InlineKeyboardButton, MessageEntity,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import List, Tuple, Optional, Any
import aiosqlite
import asyncio
import json
import logging
import random
import re
import time
import uuid

import config
from config import *


# ==============================================================================
# ------------------------- database.py -------------------------
# ==============================================================================

# -*- coding: utf-8 -*-
"""
Модуль базы данных. SQLite, асинхронный доступ через aiosqlite.
Хранит: пользователей, инвентарь, настройки премиум-эмодзи (по каждому слоту отдельно),
кулдауны, крафт-прогресс брони, настройки цвета кнопок и произвольные тексты.
"""



_db: Optional[aiosqlite.Connection] = None


async def init_db():
    global _db
    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            diamonds INTEGER NOT NULL DEFAULT 0,
            iron INTEGER NOT NULL DEFAULT 0,
            coal INTEGER NOT NULL DEFAULT 0,
            stone INTEGER NOT NULL DEFAULT 0,
            wood INTEGER NOT NULL DEFAULT 0,
            sticks INTEGER NOT NULL DEFAULT 0,
            raw_iron INTEGER NOT NULL DEFAULT 0,
            is_creative INTEGER NOT NULL DEFAULT 0,
            creative_until INTEGER NOT NULL DEFAULT 0,
            pickaxe_level INTEGER NOT NULL DEFAULT 0,
            sword_level INTEGER NOT NULL DEFAULT 0,
            armor_level INTEGER NOT NULL DEFAULT 0,
            last_daily INTEGER NOT NULL DEFAULT 0,
            last_hourly INTEGER NOT NULL DEFAULT 0,
            last_wood INTEGER NOT NULL DEFAULT 0,
            wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL DEFAULT 0,
            is_banned INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS emoji_slots (
            slot_key TEXT PRIMARY KEY,
            custom_emoji_id TEXT,
            fallback_emoji TEXT
        );

        CREATE TABLE IF NOT EXISTS button_colors (
            slot_key TEXT PRIMARY KEY,
            color TEXT
        );

        CREATE TABLE IF NOT EXISTS texts (
            text_key TEXT PRIMARY KEY,
            content TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS active_games (
            game_id TEXT PRIMARY KEY,
            game_type TEXT NOT NULL,
            chat_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pvp_challenges (
            challenge_id TEXT PRIMARY KEY,
            chat_id INTEGER NOT NULL,
            challenger_id INTEGER NOT NULL,
            opponent_id INTEGER NOT NULL,
            bet INTEGER NOT NULL,
            resource TEXT NOT NULL DEFAULT 'diamonds',
            status TEXT NOT NULL DEFAULT 'pending',
            data TEXT,
            created_at INTEGER NOT NULL
        );
        """
    )
    await _db.commit()
    await _seed_defaults()


def get_db() -> aiosqlite.Connection:
    return _db


# ---------- Пользователи ----------

async def ensure_user(user_id: int, username: str = "", first_name: str = ""):
    cur = await _db.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    if row is None:
        await _db.execute(
            "INSERT INTO users (user_id, username, first_name, created_at) VALUES (?,?,?,?)",
            (user_id, username or "", first_name or "", int(time.time())),
        )
        await _db.commit()
    else:
        await _db.execute(
            "UPDATE users SET username=?, first_name=? WHERE user_id=?",
            (username or "", first_name or "", user_id),
        )
        await _db.commit()


async def get_user(user_id: int) -> Optional[aiosqlite.Row]:
    cur = await _db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    return await cur.fetchone()


async def get_user_by_username(username: str) -> Optional[aiosqlite.Row]:
    username = username.lstrip("@")
    cur = await _db.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,))
    return await cur.fetchone()


RESOURCE_COLUMNS = ["diamonds", "iron", "coal", "stone", "wood", "sticks", "raw_iron"]


async def add_resource(user_id: int, resource: str, amount: int):
    if resource not in RESOURCE_COLUMNS:
        raise ValueError("unknown resource")
    await _db.execute(
        f"UPDATE users SET {resource} = {resource} + ? WHERE user_id=?", (amount, user_id)
    )
    await _db.commit()


async def set_resource(user_id: int, resource: str, amount: int):
    if resource not in RESOURCE_COLUMNS:
        raise ValueError("unknown resource")
    await _db.execute(f"UPDATE users SET {resource} = ? WHERE user_id=?", (amount, user_id))
    await _db.commit()


async def try_spend_resource(user_id: int, resource: str, amount: int) -> bool:
    """Атомарно списывает ресурс, если хватает средств. Возвращает True/False."""
    if resource not in RESOURCE_COLUMNS:
        raise ValueError("unknown resource")
    cur = await _db.execute(
        f"UPDATE users SET {resource} = {resource} - ? WHERE user_id=? AND {resource} >= ?",
        (amount, user_id, amount),
    )
    await _db.commit()
    return cur.rowcount > 0


async def set_field(user_id: int, field: str, value: Any):
    await _db.execute(f"UPDATE users SET {field} = ? WHERE user_id=?", (value, user_id))
    await _db.commit()


async def get_field(user_id: int, field: str):
    cur = await _db.execute(f"SELECT {field} FROM users WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    return row[0] if row else None


async def all_users():
    cur = await _db.execute("SELECT * FROM users")
    return await cur.fetchall()


async def stats_summary() -> dict:
    cur = await _db.execute(
        """SELECT
            COUNT(*) as total_users,
            SUM(diamonds) as total_diamonds,
            SUM(iron) as total_iron,
            SUM(coal) as total_coal,
            SUM(stone) as total_stone,
            SUM(wood) as total_wood,
            SUM(is_creative) as creative_count,
            SUM(wins) as total_wins
        FROM users"""
    )
    row = await cur.fetchone()
    return dict(row) if row else {}


async def top_users(by: str = "diamonds", limit: int = 10):
    if by not in RESOURCE_COLUMNS:
        by = "diamonds"
    cur = await _db.execute(f"SELECT * FROM users ORDER BY {by} DESC LIMIT ?", (limit,))
    return await cur.fetchall()


# ---------- Эмодзи-слоты (премиум-эмодзи по каждой кнопке/тексту отдельно) ----------

DEFAULT_EMOJI_SLOTS = {
    "welcome_title": "✨",
    "diamond": "💎",
    "iron": "🔩",
    "coal": "⚫",
    "stone": "🪨",
    "wood": "🪵",
    "stick": "➰",
    "raw_iron": "🟤",
    "dynamite": "🧨",
    "pickaxe": "⛏️",
    "sword": "🗡️",
    "armor": "🛡️",
    "heart": "❤️",
    "star": "⭐",
    "furnace": "🔥",
    "lucky_block": "🎁",
    "btn_daily": "🎁",
    "btn_addgroup": "➕",
    "btn_mine": "⛏️",
    "btn_craft": "🛠️",
    "btn_armor": "🛡️",
    "btn_pvp": "⚔️",
    "btn_shop": "🛒",
    "btn_inventory": "🎒",
    "btn_help": "❓",
    "btn_lucky": "🎰",
    "btn_furnace": "🔥",
    "btn_creative": "👑",
    "btn_accept": "✅",
    "btn_decline": "❌",
}

DEFAULT_BUTTON_COLORS = {
    "btn_daily": "primary",
    "btn_addgroup": "secondary",
    "btn_mine": "primary",
    "btn_craft": "secondary",
    "btn_armor": "secondary",
    "btn_pvp": "destructive",
    "btn_shop": "primary",
    "btn_inventory": "secondary",
    "btn_help": "secondary",
    "btn_lucky": "primary",
    "btn_furnace": "secondary",
    "btn_creative": "primary",
}
# Примечание: у inline-кнопок Telegram нет произвольного RGB цвета — оформление
# определяет клиент. "color" здесь смысловая метка (primary/secondary/destructive),
# используется в админке для группировки и в подписи кнопок эмодзи-акцентом.


async def _seed_defaults():
    for key, val in DEFAULT_EMOJI_SLOTS.items():
        await _db.execute(
            "INSERT OR IGNORE INTO emoji_slots (slot_key, custom_emoji_id, fallback_emoji) VALUES (?,?,?)",
            (key, None, val),
        )
    for key, val in DEFAULT_BUTTON_COLORS.items():
        await _db.execute(
            "INSERT OR IGNORE INTO button_colors (slot_key, color) VALUES (?,?)", (key, val)
        )
    await _db.commit()


async def get_emoji(slot_key: str) -> dict:
    cur = await _db.execute("SELECT * FROM emoji_slots WHERE slot_key=?", (slot_key,))
    row = await cur.fetchone()
    if row is None:
        return {"slot_key": slot_key, "custom_emoji_id": None, "fallback_emoji": "❓"}
    return dict(row)


async def set_emoji(slot_key: str, custom_emoji_id: Optional[str] = None, fallback_emoji: Optional[str] = None):
    existing = await get_emoji(slot_key)
    new_custom = custom_emoji_id if custom_emoji_id is not None else existing.get("custom_emoji_id")
    new_fallback = fallback_emoji if fallback_emoji is not None else existing.get("fallback_emoji")
    await _db.execute(
        "INSERT INTO emoji_slots (slot_key, custom_emoji_id, fallback_emoji) VALUES (?,?,?) "
        "ON CONFLICT(slot_key) DO UPDATE SET custom_emoji_id=excluded.custom_emoji_id, fallback_emoji=excluded.fallback_emoji",
        (slot_key, new_custom, new_fallback),
    )
    await _db.commit()


async def all_emoji_slots():
    cur = await _db.execute("SELECT * FROM emoji_slots ORDER BY slot_key")
    return await cur.fetchall()


async def get_button_color(slot_key: str) -> str:
    cur = await _db.execute("SELECT color FROM button_colors WHERE slot_key=?", (slot_key,))
    row = await cur.fetchone()
    return row[0] if row else "secondary"


async def set_button_color(slot_key: str, color: str):
    await _db.execute(
        "INSERT INTO button_colors (slot_key, color) VALUES (?,?) "
        "ON CONFLICT(slot_key) DO UPDATE SET color=excluded.color",
        (slot_key, color),
    )
    await _db.commit()


async def all_button_colors():
    cur = await _db.execute("SELECT * FROM button_colors ORDER BY slot_key")
    return await cur.fetchall()


# ---------- Тексты (редактируемые из админки) ----------

async def get_text(key: str, default: str = "") -> str:
    cur = await _db.execute("SELECT content FROM texts WHERE text_key=?", (key,))
    row = await cur.fetchone()
    return row[0] if row else default


async def set_text(key: str, content: str):
    await _db.execute(
        "INSERT INTO texts (text_key, content) VALUES (?,?) "
        "ON CONFLICT(text_key) DO UPDATE SET content=excluded.content",
        (key, content),
    )
    await _db.commit()


# ---------- Настройки (произвольные key-value, например курсы обмена) ----------

async def get_setting(key: str, default: Any = None):
    cur = await _db.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = await cur.fetchone()
    if row is None:
        return default
    try:
        return json.loads(row[0])
    except Exception:
        return row[0]


async def set_setting(key: str, value: Any):
    await _db.execute(
        "INSERT INTO settings (key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value, ensure_ascii=False)),
    )
    await _db.commit()


# ---------- Активные игры (шахта-поле, lucky и т.д. хранится как JSON) ----------

async def save_game(game_id: str, game_type: str, chat_id: int, data: dict):
    await _db.execute(
        "INSERT INTO active_games (game_id, game_type, chat_id, data, created_at) VALUES (?,?,?,?,?) "
        "ON CONFLICT(game_id) DO UPDATE SET data=excluded.data",
        (game_id, game_type, chat_id, json.dumps(data, ensure_ascii=False), int(time.time())),
    )
    await _db.commit()


async def load_game(game_id: str) -> Optional[dict]:
    cur = await _db.execute("SELECT data FROM active_games WHERE game_id=?", (game_id,))
    row = await cur.fetchone()
    if not row:
        return None
    return json.loads(row[0])


async def delete_game(game_id: str):
    await _db.execute("DELETE FROM active_games WHERE game_id=?", (game_id,))
    await _db.commit()


# ---------- PVP заявки ----------

async def create_pvp_challenge(challenge_id: str, chat_id: int, challenger_id: int,
                                opponent_id: int, bet: int, resource: str = "diamonds"):
    await _db.execute(
        "INSERT INTO pvp_challenges (challenge_id, chat_id, challenger_id, opponent_id, bet, resource, status, created_at) "
        "VALUES (?,?,?,?,?,?,'pending',?)",
        (challenge_id, chat_id, challenger_id, opponent_id, bet, resource, int(time.time())),
    )
    await _db.commit()


async def get_pvp_challenge(challenge_id: str) -> Optional[aiosqlite.Row]:
    cur = await _db.execute("SELECT * FROM pvp_challenges WHERE challenge_id=?", (challenge_id,))
    return await cur.fetchone()


async def update_pvp_challenge(challenge_id: str, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [challenge_id]
    await _db.execute(f"UPDATE pvp_challenges SET {cols} WHERE challenge_id=?", vals)
    await _db.commit()


async def delete_pvp_challenge(challenge_id: str):
    await _db.execute("DELETE FROM pvp_challenges WHERE challenge_id=?", (challenge_id,))
    await _db.commit()


# ==============================================================================
# ------------------------- emoji_utils.py -------------------------
# ==============================================================================

# -*- coding: utf-8 -*-
"""
Утилиты сборки текста с премиум-эмодзи.

Как это работает в Telegram Bot API:
- Премиум-эмодзи — это обычный текстовый символ-плейсхолдер (например "🔷"),
  поверх которого накладывается MessageEntity типа "custom_emoji" с полем
  custom_emoji_id. Клиент Telegram поверх текста отрисовывает кастомный
  анимированный эмодзи вместо символа-плейсхолдера.
- Чтобы бот мог отправлять custom_emoji entities, у аккаунта бота (или у
  пользователя, если это user-bot) должна быть подписка Telegram Premium.
  Без Premium Telegram просто проигнорирует entity и покажет символ-плейсхолдер.
- custom_emoji_id получают, переслав нужный премиум-стикер/эмодзи через
  бота вроде @like робота получения id, либо через MTProto-инструменты.
  В админ-панели вы вводите этот ID вручную для каждого слота.

Если для слота не задан custom_emoji_id — используется обычный fallback-эмодзи,
чтобы бот не ломался и не показывал пустоту.
"""




async def emoji_piece(slot_key: str) -> Tuple[str, List[MessageEntity]]:
    """
    Возвращает (текст_плейсхолдера, [entities]) для одного эмодзи-слота.
    Entities возвращаются с offset=0, вызывающий код должен пересчитать
    смещение под итоговую позицию в полном тексте (см. build_text).
    """
    row = await get_emoji(slot_key)
    fallback = row.get("fallback_emoji") or "❓"
    custom_id = row.get("custom_emoji_id")

    if custom_id:
        # Длина entity считается в UTF-16 code units, для большинства emoji-плейсхолдеров
        # (одиночный символ) это 1 или 2 юнита. Считаем корректно через len(encode utf-16).
        length = len(fallback.encode("utf-16-le")) // 2
        entity = MessageEntity(type="custom_emoji", offset=0, length=length, custom_emoji_id=custom_id)
        return fallback, [entity]
    return fallback, []


async def build_text(parts: List) -> Tuple[str, List[MessageEntity]]:
    """
    Собирает финальный текст и список entities из списка частей.
    Каждая часть — либо обычная строка, либо tuple ("emoji", slot_key).

    Пример:
        text, entities = await build_text([
            ("emoji", "diamond"), " Баланс: ", str(amount), " алмазов"
        ])
        await message.answer(text, entities=entities)
    """
    result_text = ""
    result_entities: List[MessageEntity] = []
    utf16_offset = 0

    for part in parts:
        if isinstance(part, tuple) and part[0] == "emoji":
            slot_key = part[1]
            piece_text, piece_entities = await emoji_piece(slot_key)
            for e in piece_entities:
                result_entities.append(
                    MessageEntity(
                        type=e.type,
                        offset=utf16_offset,
                        length=e.length,
                        custom_emoji_id=e.custom_emoji_id,
                    )
                )
            result_text += piece_text
            utf16_offset += len(piece_text.encode("utf-16-le")) // 2
        else:
            s = str(part)
            result_text += s
            utf16_offset += len(s.encode("utf-16-le")) // 2

    return result_text, result_entities


async def emoji_str(slot_key: str) -> str:
    """Просто возвращает символ эмодзи (плейсхолдер) без entity — удобно для текста кнопок,
    где custom emoji entities не поддерживаются (только обычный unicode)."""
    row = await get_emoji(slot_key)
    return row.get("fallback_emoji") or "❓"


# ==============================================================================
# ------------------------- emoji_info.py -------------------------
# ==============================================================================

# -*- coding: utf-8 -*-
"""
Человекочитаемые описания эмодзи-слотов для админ-панели.
Каждый слот = один настраиваемый элемент (ресурс, предмет или кнопка).
Показывается в разделе "🎨 Эмодзи и оформление", чтобы было понятно,
за что отвечает каждая настройка и где именно она используется.
"""

EMOJI_SLOT_INFO = {
    # ---------- Ресурсы (используются в тексте: баланс, инвентарь, добыча, шахта, крафт) ----------
    "diamond": {
        "title": "Алмаз",
        "desc": "Основная валюта бота. Показывается в балансе, ежедневном бонусе, "
                "шахте, PVP-ставках, магазине и переводах.",
        "group": "Ресурсы",
    },
    "iron": {
        "title": "Железо (переплавленное)",
        "desc": "Используется в крафте меча, брони и в переводах ресурсов.",
        "group": "Ресурсы",
    },
    "raw_iron": {
        "title": "Железная руда (сырая)",
        "desc": "Добывается в шахте, переплавляется в печке в обычное железо.",
        "group": "Ресурсы",
    },
    "coal": {
        "title": "Уголь",
        "desc": "Добывается в шахте, нужен для переплавки в печке.",
        "group": "Ресурсы",
    },
    "stone": {
        "title": "Камень",
        "desc": "Добывается в шахте, используется в крафте кирки.",
        "group": "Ресурсы",
    },
    "wood": {
        "title": "Дерево",
        "desc": "Добывается командой «добыть» (раз в 20 минут), идёт на палки.",
        "group": "Ресурсы",
    },
    "stick": {
        "title": "Палка",
        "desc": "Крафтится из дерева, нужна для кирки, меча и брони.",
        "group": "Ресурсы",
    },
    "dynamite": {
        "title": "Динамит",
        "desc": "Ячейка-ловушка в шахте и мини-игре «Полоски» — открывший её ничего не получает.",
        "group": "Ресурсы",
    },

    # ---------- Предметы ----------
    "pickaxe": {
        "title": "Кирка",
        "desc": "Иконка на закрытых ячейках поля шахты (пока не открыты).",
        "group": "Предметы",
    },
    "sword": {
        "title": "Меч",
        "desc": "Показывается в PVP: карточка урона и кнопка «Ударить».",
        "group": "Предметы",
    },
    "armor": {
        "title": "Броня",
        "desc": "Показывается в разделе брони и при получении урона в PVP.",
        "group": "Предметы",
    },
    "heart": {
        "title": "Сердечко (HP)",
        "desc": "Полоска здоровья в PVP-бою (10 делений по умолчанию).",
        "group": "Предметы",
    },
    "furnace": {
        "title": "Печка",
        "desc": "Иконка раздела переплавки руды.",
        "group": "Предметы",
    },
    "lucky_block": {
        "title": "Lucky Block",
        "desc": "Иконка мини-игры со случайными наградами за 5 алмазов.",
        "group": "Предметы",
    },
    "star": {
        "title": "Звезда Telegram",
        "desc": "Используется в текстах магазина при оплате Telegram Stars.",
        "group": "Предметы",
    },
    "welcome_title": {
        "title": "Заголовок приветствия",
        "desc": "Эмодзи перед названием бота в самом первом сообщении /start.",
        "group": "Оформление",
    },

    # ---------- Кнопки (только обычный unicode — Telegram не поддерживает премиум-эмодзи в тексте кнопок) ----------
    "btn_daily": {
        "title": "Кнопка «Ежедневный бонус»",
        "desc": "Главное меню. Важно: на кнопках премиум-эмодзи технически не отображаются "
                "(ограничение Telegram Bot API) — здесь можно поставить только обычный emoji.",
        "group": "Кнопки",
    },
    "btn_addgroup": {
        "title": "Кнопка «Добавить в группу»",
        "desc": "Главное меню, открывает диалог добавления бота в группу.",
        "group": "Кнопки",
    },
    "btn_mine": {
        "title": "Кнопка «Шахта»",
        "desc": "Главное меню, открывает мини-игру 5x5.",
        "group": "Кнопки",
    },
    "btn_craft": {
        "title": "Кнопка «Крафт»",
        "desc": "Главное меню, открывает меню крафта.",
        "group": "Кнопки",
    },
    "btn_armor": {
        "title": "Кнопка «Броня»",
        "desc": "Главное меню и меню крафта, открывает раздел брони.",
        "group": "Кнопки",
    },
    "btn_pvp": {
        "title": "Кнопка «PVP»",
        "desc": "Главное меню, показывает инструкцию по вызову на дуэль.",
        "group": "Кнопки",
    },
    "btn_shop": {
        "title": "Кнопка «Магазин»",
        "desc": "Главное меню, открывает покупки за звёзды Telegram.",
        "group": "Кнопки",
    },
    "btn_inventory": {
        "title": "Кнопка «Инвентарь»",
        "desc": "Главное меню, показывает все ресурсы пользователя.",
        "group": "Кнопки",
    },
    "btn_help": {
        "title": "Кнопка «Помощь»",
        "desc": "Главное меню, показывает список всех команд.",
        "group": "Кнопки",
    },
    "btn_lucky": {
        "title": "Кнопка «Lucky Block»",
        "desc": "Главное меню и подтверждение открытия Lucky Block.",
        "group": "Кнопки",
    },
    "btn_furnace": {
        "title": "Кнопка «Печка»",
        "desc": "Главное меню, открывает переплавку руды.",
        "group": "Кнопки",
    },
    "btn_creative": {
        "title": "Кнопка «Creative»",
        "desc": "Магазин, покупка VIP-статуса за 100 звёзд.",
        "group": "Кнопки",
    },
    "btn_accept": {
        "title": "Кнопка «Принять» (PVP)",
        "desc": "Показывается сопернику при вызове на дуэль.",
        "group": "Кнопки",
    },
    "btn_decline": {
        "title": "Кнопка «Отклонить» (PVP)",
        "desc": "Показывается сопернику при вызове на дуэль.",
        "group": "Кнопки",
    },
}

GROUP_ORDER = ["Ресурсы", "Предметы", "Оформление", "Кнопки"]


def grouped_slots():
    """Возвращает {group_name: [slot_key, ...]} в заданном порядке групп."""
    groups = {g: [] for g in GROUP_ORDER}
    for key, info in EMOJI_SLOT_INFO.items():
        groups.setdefault(info["group"], []).append(key)
    return {g: groups[g] for g in GROUP_ORDER if groups.get(g)}


# ==============================================================================
# ------------------------- keyboards.py -------------------------
# ==============================================================================

# -*- coding: utf-8 -*-
"""
Клавиатуры бота. Эмодзи на кнопках берутся из БД (emoji_slots.fallback_emoji),
так как Telegram НЕ поддерживает custom_emoji entities внутри текста inline-кнопок —
это ограничение Bot API, а не этого кода. Премиум-эмодзи используются в текстах
сообщений (см. emoji_utils.py), на кнопках — только обычный unicode-emoji,
который тоже настраивается из админ-панели (тот же слот, поле fallback_emoji).
"""




async def main_menu_kb(bot_username: str) -> InlineKeyboardMarkup:
    daily = await emoji_str("btn_daily")
    addgroup = await emoji_str("btn_addgroup")
    mine = await emoji_str("btn_mine")
    craft = await emoji_str("btn_craft")
    armor = await emoji_str("btn_armor")
    pvp = await emoji_str("btn_pvp")
    shop = await emoji_str("btn_shop")
    inv = await emoji_str("btn_inventory")
    help_ = await emoji_str("btn_help")
    lucky = await emoji_str("btn_lucky")
    furnace = await emoji_str("btn_furnace")

    b = InlineKeyboardBuilder()
    b.button(text=f"{daily} Ежедневный бонус", callback_data="daily")
    b.button(text=f"{addgroup} Добавить в группу",
             url=f"https://t.me/{bot_username}?startgroup=true")
    b.button(text=f"{mine} Шахта", callback_data="open_mine")
    b.button(text=f"{craft} Крафт", callback_data="open_craft")
    b.button(text=f"{armor} Броня", callback_data="open_armor")
    b.button(text=f"{pvp} PVP", callback_data="open_pvp_info")
    b.button(text=f"{shop} Магазин", callback_data="open_shop")
    b.button(text=f"{inv} Инвентарь", callback_data="open_inventory")
    b.button(text=f"{furnace} Печка", callback_data="open_furnace")
    b.button(text=f"{lucky} Lucky Block", callback_data="open_lucky")
    b.button(text=f"{help_} Помощь", callback_data="open_help")
    b.adjust(1, 1, 2, 2, 2, 2, 1)
    return b.as_markup()


async def back_kb(target: str = "main") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ Назад", callback_data=f"back_{target}")
    return b.as_markup()


async def mine_field_kb(field: list, mine_id: str) -> InlineKeyboardMarkup:
    """
    field — список из 25 ячеек (5x5), каждая ячейка dict:
        {"type": "diamond"/"iron"/"coal"/"stone"/"dynamite", "revealed": bool}
    """
    pickaxe = await emoji_str("pickaxe")
    b = InlineKeyboardBuilder()
    for idx, cell in enumerate(field):
        if cell["revealed"]:
            icon = await emoji_str(cell["type"])
            b.button(text=icon, callback_data="noop")
        else:
            b.button(text=pickaxe, callback_data=f"mine_{mine_id}_{idx}")
    b.adjust(5, 5, 5, 5, 5)
    return b.as_markup()


async def craft_menu_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🪵 → 🪄 Палки (2 дерева → 4 палки)", callback_data="craft_sticks")
    b.button(text="⛏️ Кирка (2 палки + 3 камня)", callback_data="craft_pickaxe")
    b.button(text="🗡️ Меч (1 палка + 2 железа)", callback_data="craft_sword")
    b.button(text="🛡️ Открыть раздел брони", callback_data="open_armor")
    b.button(text="⬅️ Назад", callback_data="back_main")
    b.adjust(1)
    return b.as_markup()


async def armor_menu_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🛡️ Скрафтить броню (5 железа + 2 палки)", callback_data="craft_armor")
    b.button(text="⬆️ Улучшить броню (3 железа + 1 алмаз)", callback_data="upgrade_armor")
    b.button(text="⬅️ Назад", callback_data="back_main")
    b.adjust(1)
    return b.as_markup()


async def shop_menu_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💎 Купить алмазы за звёзды", callback_data="shop_diamonds")
    b.button(text="🔩 5 железа — 1 ⭐", callback_data="shop_iron_pack")
    b.button(text="💎 2 переплавленных алмаза — 1 ⭐", callback_data="shop_diamond_pack")
    b.button(text="👑 Creative — 100 ⭐", callback_data="shop_creative")
    b.button(text="⬅️ Назад", callback_data="back_main")
    b.adjust(1)
    return b.as_markup()


async def pvp_offer_kb(challenge_id: str) -> InlineKeyboardMarkup:
    accept = await emoji_str("btn_accept")
    decline = await emoji_str("btn_decline")
    b = InlineKeyboardBuilder()
    b.button(text=f"{accept} Принять", callback_data=f"pvp_accept_{challenge_id}")
    b.button(text=f"{decline} Отклонить", callback_data=f"pvp_decline_{challenge_id}")
    b.adjust(2)
    return b.as_markup()


async def pvp_fight_kb(challenge_id: str) -> InlineKeyboardMarkup:
    sword = await emoji_str("sword")
    b = InlineKeyboardBuilder()
    b.button(text=f"{sword} Ударить", callback_data=f"pvp_hit_{challenge_id}")
    return b.as_markup()


async def lucky_confirm_kb() -> InlineKeyboardMarkup:
    lucky = await emoji_str("btn_lucky")
    b = InlineKeyboardBuilder()
    b.button(text=f"{lucky} Открыть Lucky Block (5 💎)", callback_data="lucky_open")
    b.button(text="⬅️ Назад", callback_data="back_main")
    b.adjust(1)
    return b.as_markup()


async def furnace_menu_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔥 Переплавить руду железа (нужны дрова)", callback_data="furnace_smelt")
    b.button(text="⬅️ Назад", callback_data="back_main")
    b.adjust(1)
    return b.as_markup()


async def strip_field_kb(round_id: str, revealed_row: int = -1) -> InlineKeyboardMarkup:
    """Мини-игра 'полоски': 5 горизонтальных полос, выбираешь одну."""
    dyn = await emoji_str("dynamite")
    b = InlineKeyboardBuilder()
    for i in range(5):
        if i == revealed_row:
            b.button(text="✅", callback_data="noop")
        else:
            b.button(text=f"▬▬▬▬▬ Полоса {i+1} ▬▬▬▬▬", callback_data=f"strip_{round_id}_{i}")
    b.adjust(1)
    return b.as_markup()


# ==============================================================================
# ------------------------- game_logic.py -------------------------
# ==============================================================================

# -*- coding: utf-8 -*-
"""
Игровая логика без привязки к Telegram API — чистые функции и структуры данных.
"""



# ---------- Шахта 5x5 ----------

MINE_LOOT_TABLE = [
    # (тип_ресурса, количество, вес_шанса)
    ("diamond", 1, 5),
    ("iron", 2, 15),
    ("coal", 5, 20),
    ("stone", 7, 30),
]


def generate_mine_field() -> list:
    """Генерирует случайное поле 5x5 (25 ячеек): динамиты + ресурсы, каждый раз в новом порядке."""
    total = MINE_SIZE * MINE_SIZE
    cells = []

    # динамиты
    for _ in range(MINE_DYNAMITE_COUNT):
        cells.append({"type": "dynamite", "amount": 0, "revealed": False})

    # остальное — ресурсы по весам
    resource_types = [t[0] for t in MINE_LOOT_TABLE]
    weights = [t[2] for t in MINE_LOOT_TABLE]
    amounts = {t[0]: t[1] for t in MINE_LOOT_TABLE}

    while len(cells) < total:
        rtype = random.choices(resource_types, weights=weights, k=1)[0]
        # немного варьируем количество вокруг базового значения
        base = amounts[rtype]
        amount = max(1, base + random.randint(-1, 2))
        cells.append({"type": rtype, "amount": amount, "revealed": False})

    random.shuffle(cells)
    return cells


def new_mine_id() -> str:
    return uuid.uuid4().hex[:10]


# ---------- Крафт ----------

CRAFT_RECIPES = {
    "sticks": {
        "name": "Палки",
        "cost": {"wood": 2},
        "gain": {"sticks": 4},
    },
    "pickaxe": {
        "name": "Кирка",
        "cost": {"sticks": 2, "stone": 3},
        "gain": {},  # повышает pickaxe_level, обрабатывается отдельно
    },
    "sword": {
        "name": "Меч",
        "cost": {"sticks": 1, "iron": 2},
        "gain": {},  # повышает sword_level
    },
    "armor": {
        "name": "Броня",
        "cost": {"iron": 5, "sticks": 2},
        "gain": {},  # повышает armor_level
    },
    "armor_upgrade": {
        "name": "Улучшение брони",
        "cost": {"iron": 3, "diamonds": 1},
        "gain": {},
    },
}


# ---------- PVP ----------

def sword_damage(sword_level: int) -> int:
    """Урон меча зависит от уровня. База 2, +2 за уровень (максимум условно 5 уровней)."""
    return 2 + sword_level * 2


def armor_reduction(armor_level: int) -> int:
    """Снижение входящего урона от брони (не может уйти в минус урона)."""
    return armor_level  # 1 очко брони = -1 урон


def apply_hit(attacker_sword_level: int, defender_armor_level: int) -> int:
    dmg = sword_damage(attacker_sword_level) - armor_reduction(defender_armor_level)
    return max(1, dmg)  # минимум 1 урон, чтобы бои не были бесконечными


def hp_hearts_bar(current_hp: int, max_hp: int = PVP_MAX_HP) -> str:
    current_hp = max(0, min(current_hp, max_hp))
    full = "❤️" * current_hp
    empty = "🖤" * (max_hp - current_hp)
    return full + empty


def new_challenge_id() -> str:
    return uuid.uuid4().hex[:10]


# ---------- Lucky Block ----------

LUCKY_LOOT_TABLE = [
    # (ресурс, мин, макс, вес)
    ("dynamite_bonus", 0, 0, 10),   # пусто/неудача (создаёт напряжение)
    ("diamonds", 1, 3, 15),
    ("iron", 3, 8, 25),
    ("coal", 5, 12, 25),
    ("stone", 5, 15, 20),
    ("wood", 3, 10, 20),
]


def open_lucky_block() -> list:
    """Возвращает список из 1-3 наград (может выпасть несколько ресурсов сразу)."""
    resource_types = [t[0] for t in LUCKY_LOOT_TABLE]
    weights = [t[3] for t in LUCKY_LOOT_TABLE]
    ranges = {t[0]: (t[1], t[2]) for t in LUCKY_LOOT_TABLE}

    drop_count = random.choices([1, 2, 3], weights=[50, 35, 15], k=1)[0]
    results = []
    for _ in range(drop_count):
        rtype = random.choices(resource_types, weights=weights, k=1)[0]
        if rtype == "dynamite_bonus":
            continue
        lo, hi = ranges[rtype]
        amount = random.randint(lo, hi)
        if amount > 0:
            results.append((rtype, amount))
    return results


# ---------- Мини-игра "Полоски" ----------

STRIP_LOOT_TABLE = [
    ("dynamite", 0, 0, 20),  # проигрыш
    ("diamonds", 1, 2, 10),
    ("iron", 2, 5, 25),
    ("coal", 3, 8, 25),
    ("stone", 3, 10, 20),
]


def generate_strip_round() -> dict:
    """5 полос, в одной из них — случайный приз (или динамит = проигрыш), остальные не важны."""
    resource_types = [t[0] for t in STRIP_LOOT_TABLE]
    weights = [t[3] for t in STRIP_LOOT_TABLE]
    ranges = {t[0]: (t[1], t[2]) for t in STRIP_LOOT_TABLE}

    winning_row = random.randint(0, 4)
    rtype = random.choices(resource_types, weights=weights, k=1)[0]
    lo, hi = ranges[rtype]
    amount = random.randint(lo, hi) if hi > 0 else 0

    return {
        "winning_row": winning_row,
        "reward_type": rtype,
        "reward_amount": amount,
        "created_at": int(time.time()),
    }


# ---------- Добыча дерева ----------

def chop_wood_amount(wood_min: int, wood_max: int) -> int:
    return random.randint(wood_min, wood_max)


# ==============================================================================
# ------------------------- states.py -------------------------
# ==============================================================================

# -*- coding: utf-8 -*-


class AdminStates(StatesGroup):
    waiting_emoji_value = State()          # ждём custom_emoji_id или обычный emoji для слота
    waiting_button_color = State()         # ждём выбор цвета кнопки (через кнопки, но на всякий случай)
    waiting_text_value = State()           # ждём новый текст для text_key
    waiting_give_resource_amount = State() # ждём количество ресурса для выдачи
    waiting_give_target = State()          # ждём @username или reply для выдачи ресурса
    waiting_broadcast_text = State()       # ждём текст рассылки


class UserStates(StatesGroup):
    waiting_shop_diamond_amount = State()  # сколько алмазов хочет купить пользователь
    waiting_furnace_amount = State()       # сколько руды переплавить


# ==============================================================================
# ------------------------- handlers_start.py -------------------------
# ==============================================================================

# -*- coding: utf-8 -*-
"""
/start и главное меню. Приветствие собирается с премиум-эмодзи через emoji_utils.build_text.
"""



router_start = Router(name="start")


async def welcome_text_parts(user_id: int):
    diamonds = await get_field(user_id, "diamonds") or 0
    custom_greeting = await get_text("welcome_text", "")
    if custom_greeting:
        # Если админ задал собственный текст приветствия — используем его,
        # но всё равно добавляем эмодзи-заголовок и баланс сверху.
        return [
            ("emoji", "welcome_title"), " ", custom_greeting, "\n\n",
            ("emoji", "diamond"), f" Баланс: {diamonds}",
        ]
    return [
        ("emoji", "welcome_title"), " Добро пожаловать в мир Minecraft Bot!\n\n",
        "Здесь можно копать шахты, крафтить снаряжение, устраивать PVP-дуэли ",
        "и находить сокровища в Lucky Block.\n\n",
        ("emoji", "diamond"), f" Ваш баланс: {diamonds}\n\n",
        f"Создатель бота: {CREATOR_USERNAME}",
    ]


@router_start.message(CommandStart())
async def cmd_start(message: Message):
    await ensure_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    parts = await welcome_text_parts(message.from_user.id)
    text, entities = await build_text(parts)
    me = await message.bot.get_me()
    kb = await main_menu_kb(me.username)
    await message.answer(text, entities=entities, reply_markup=kb)


@router_start.callback_query(F.data == "back_main")
async def back_to_main(call: CallbackQuery):
    await ensure_user(call.from_user.id, call.from_user.username or "", call.from_user.first_name or "")
    parts = await welcome_text_parts(call.from_user.id)
    text, entities = await build_text(parts)
    me = await call.bot.get_me()
    kb = await main_menu_kb(me.username)
    try:
        await call.message.edit_text(text, entities=entities, reply_markup=kb)
    except Exception:
        await call.message.answer(text, entities=entities, reply_markup=kb)
    await call.answer()


@router_start.callback_query(F.data == "noop")
async def noop(call: CallbackQuery):
    await call.answer()


# ==============================================================================
# ------------------------- handlers_balance.py -------------------------
# ==============================================================================

# -*- coding: utf-8 -*-
"""
Баланс / инвентарь / ежедневный бонус (в т.ч. часовой бонус для Creative) / помощь.
"""



router_balance = Router(name="balance")

DAY_SECONDS = 24 * 60 * 60
HOUR_SECONDS = 60 * 60


async def send_balance(target, user_id: int, edit: bool = False):
    row = await get_user(user_id)
    parts = [
        ("emoji", "diamond"), f" Алмазы: {row['diamonds']}\n",
        ("emoji", "iron"), f" Железо: {row['iron']}\n",
        ("emoji", "coal"), f" Уголь: {row['coal']}\n",
        ("emoji", "stone"), f" Камень: {row['stone']}\n",
    ]
    text, entities = await build_text(parts)
    if edit and isinstance(target, CallbackQuery):
        await target.message.edit_text(text, entities=entities, reply_markup=await back_kb())
    elif isinstance(target, CallbackQuery):
        await target.message.answer(text, entities=entities)
    else:
        await target.answer(text, entities=entities)


async def send_inventory(target, user_id: int, edit: bool = False):
    row = await get_user(user_id)
    parts = [
        "🎒 Ваш инвентарь:\n\n",
        ("emoji", "diamond"), f" Алмазы: {row['diamonds']}\n",
        ("emoji", "iron"), f" Железо: {row['iron']}\n",
        ("emoji", "raw_iron"), f" Железная руда: {row['raw_iron']}\n",
        ("emoji", "coal"), f" Уголь: {row['coal']}\n",
        ("emoji", "stone"), f" Камень: {row['stone']}\n",
        ("emoji", "wood"), f" Дерево: {row['wood']}\n",
        ("emoji", "stick"), f" Палки: {row['sticks']}\n\n",
        ("emoji", "pickaxe"), f" Уровень кирки: {row['pickaxe_level']}\n",
        ("emoji", "sword"), f" Уровень меча: {row['sword_level']}\n",
        ("emoji", "armor"), f" Уровень брони: {row['armor_level']}\n",
    ]
    if row["is_creative"]:
        parts.append(("emoji", "btn_creative"))
        parts.append(" Статус: Creative\n")
    text, entities = await build_text(parts)
    if edit and isinstance(target, CallbackQuery):
        await target.message.edit_text(text, entities=entities, reply_markup=await back_kb())
    elif isinstance(target, CallbackQuery):
        await target.message.answer(text, entities=entities)
    else:
        await target.answer(text, entities=entities)


async def claim_daily(user_id: int) -> tuple[bool, str]:
    """Возвращает (успех, текст_результата)."""
    row = await get_user(user_id)
    now = int(time.time())
    is_creative = row["is_creative"] and row["creative_until"] > now

    if is_creative:
        # Для Creative — часовой бонус вместо суточного
        if now - row["last_hourly"] < HOUR_SECONDS:
            remain = HOUR_SECONDS - (now - row["last_hourly"])
            mins = remain // 60
            return False, f"⏳ Следующий часовой бонус через {mins} мин."
        await add_resource(user_id, "diamonds", CREATIVE_HOURLY_DIAMONDS)
        await add_resource(user_id, "iron", CREATIVE_HOURLY_IRON)
        await set_field(user_id, "last_hourly", now)
        text, entities = await build_text([
            "👑 Часовой Creative-бонус получен!\n",
            ("emoji", "diamond"), f" +{CREATIVE_HOURLY_DIAMONDS}  ",
            ("emoji", "iron"), f" +{CREATIVE_HOURLY_IRON}",
        ])
        return True, text
    else:
        if now - row["last_daily"] < DAY_SECONDS:
            remain = DAY_SECONDS - (now - row["last_daily"])
            hours = remain // 3600
            mins = (remain % 3600) // 60
            return False, f"⏳ Следующий ежедневный бонус через {hours} ч {mins} мин."
        await add_resource(user_id, "diamonds", DAILY_BONUS_DIAMONDS)
        await set_field(user_id, "last_daily", now)
        return True, f"__DAILY_OK__{DAILY_BONUS_DIAMONDS}"


@router_balance.callback_query(F.data == "daily")
async def cb_daily(call: CallbackQuery):
    ok, msg = await claim_daily(call.from_user.id)
    if msg.startswith("__DAILY_OK__"):
        amount = msg.replace("__DAILY_OK__", "")
        text, entities = await build_text([
            "🎁 Ежедневный бонус получен!\n",
            ("emoji", "diamond"), f" +{amount}",
        ])
        await call.answer()
        await call.message.answer(text, entities=entities)
    else:
        await call.answer(msg, show_alert=True)


@router_balance.callback_query(F.data == "open_inventory")
async def cb_inventory(call: CallbackQuery):
    await send_inventory(call, call.from_user.id, edit=True)
    await call.answer()


HELP_TEXT = """📖 Список команд и игр:

🎁 Ежедневный бонус — кнопка в главном меню (алмаз раз в 24 часа)
⛏️ «копать <сумма|макс>» — открыть шахту 5x5 на ставку
🌳 «добыть» — добыть дерево (раз в 20 минут)
🛠️ «крафт» — открыть меню крафта
🛡️ «броня» — открыть раздел брони
🔥 «печка» — переплавить руду
🎰 «лаки» — открыть Lucky Block за 5 алмазов
💰 «баланс» — показать баланс
🎒 «инвентарь» — показать весь инвентарь
🛒 «магазин» — купить алмазы/ресурсы/Creative за звёзды
🎁 «дать <кол-во> <ресурс>» (ответом на сообщение) — передать ресурсы другому игроку
⚔️ «пп <сумма>» (ответом на сообщение) — вызвать на PVP-дуэль
❓ «хелп» — эта справка
"""


@router_balance.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT)


@router_balance.callback_query(F.data == "open_help")
async def cb_help(call: CallbackQuery):
    await call.message.edit_text(HELP_TEXT, reply_markup=await back_kb())
    await call.answer()


@router_balance.message(F.text.func(lambda t: t and t.lower().strip() in TRIGGER_HELP))
async def text_help(message: Message):
    await message.answer(HELP_TEXT)


@router_balance.message(F.text.func(lambda t: t and t.lower().strip() == TRIGGER_BALANCE))
async def text_balance(message: Message):
    await ensure_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    await send_balance(message, message.from_user.id)


@router_balance.message(F.text.func(lambda t: t and t.lower().strip() == TRIGGER_INVENTORY))
async def text_inventory(message: Message):
    await ensure_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    await send_inventory(message, message.from_user.id)


# ==============================================================================
# ------------------------- handlers_mine.py -------------------------
# ==============================================================================

# -*- coding: utf-8 -*-
"""
Мини-игра "Шахта": пользователь пишет "копать <сумма|макс>",
это списывает ставку алмазов, генерирует поле 5x5 (рандомно каждый раз),
и пользователь по очереди открывает ячейки — либо ресурс, либо динамит (провал).
"""



router_mine = Router(name="mine")

MINE_PATTERN = re.compile(rf"^{TRIGGER_MINE}\s+(макс|\d+)$", re.IGNORECASE)


@router_mine.message(F.text.regexp(MINE_PATTERN))
async def start_mine(message: Message):
    match = MINE_PATTERN.match(message.text.strip())
    await ensure_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    user = await get_user(message.from_user.id)

    raw_amount = match.group(1).lower()
    if raw_amount == "макс":
        bet = user["diamonds"]
    else:
        bet = int(raw_amount)

    if bet <= 0:
        await message.reply("У вас нет алмазов для ставки.")
        return

    ok = await try_spend_resource(message.from_user.id, "diamonds", bet)
    if not ok:
        await message.reply("Недостаточно алмазов для такой ставки.")
        return

    field = generate_mine_field()
    mine_id = new_mine_id()
    await save_game(mine_id, "mine", message.chat.id, {
        "owner_id": message.from_user.id,
        "field": field,
        "bet": bet,
        "opened": 0,
        "won_diamonds": 0,
    })

    text, entities = await build_text([
        ("emoji", "pickaxe"), f" Шахта открыта! Ставка: {bet} ", ("emoji", "diamond"),
        "\nВыбирайте ячейки — под ними ресурсы или динамит.",
    ])
    kb = await mine_field_kb(field, mine_id)
    await message.answer(text, entities=entities, reply_markup=kb)


@router_mine.callback_query(F.data == "open_mine")
async def open_mine_info(call: CallbackQuery):
    from keyboards import back_kb
    text, entities = await build_text([
        ("emoji", "pickaxe"), " Шахта 5×5\n\n",
        "Чтобы начать копать, напишите в чат:\n",
        "«копать <сумма>» — например: копать 5\n",
        "«копать макс» — поставить весь баланс алмазов\n\n",
        "Поле генерируется заново каждую игру. Есть 3 динамита — ",
        "попадёте на один, и ставка сгорит.",
    ])
    await call.message.edit_text(text, entities=entities, reply_markup=await back_kb())
    await call.answer()


@router_mine.callback_query(F.data.startswith("mine_"))
async def click_mine_cell(call: CallbackQuery):
    _, mine_id, idx_str = call.data.split("_")
    idx = int(idx_str)

    game = await load_game(mine_id)
    if game is None:
        await call.answer("Игра уже завершена.", show_alert=True)
        return

    if game["owner_id"] != call.from_user.id:
        await call.answer("Это не ваша игра!", show_alert=True)
        return

    field = game["field"]
    cell = field[idx]
    if cell["revealed"]:
        await call.answer()
        return

    cell["revealed"] = True

    if cell["type"] == "dynamite":
        # Провал — ставка сгорает, показываем всё поле
        for c in field:
            c["revealed"] = True
        await delete_game(mine_id)
        text, entities = await build_text([
            ("emoji", "dynamite"), " БУМ! Вы подорвались на динамите.\n",
            f"Ставка {game['bet']} ", ("emoji", "diamond"), " сгорела.",
        ])
        kb = await mine_field_kb(field, mine_id)
        try:
            await call.message.edit_text(text, entities=entities, reply_markup=kb)
        except Exception:
            pass
        await call.answer("💥 Динамит!", show_alert=True)
        return

    # Ресурс — начисляем
    await add_resource(call.from_user.id, cell["type"], cell["amount"])
    game["opened"] += 1

    all_dynamite_left = all(
        c["revealed"] or c["type"] != "dynamite" for c in field
    )
    remaining_safe = any(not c["revealed"] and c["type"] != "dynamite" for c in field)

    await save_game(mine_id, "mine", call.message.chat.id, game)

    icon_key = cell["type"]
    text, entities = await build_text([
        ("emoji", "pickaxe"), f" Шахта. Ставка: {game['bet']} ", ("emoji", "diamond"), "\n",
        ("emoji", icon_key), f" Найдено: +{cell['amount']}",
    ])
    kb = await mine_field_kb(field, mine_id)
    try:
        await call.message.edit_text(text, entities=entities, reply_markup=kb)
    except Exception:
        pass

    if not remaining_safe:
        # Все безопасные ячейки открыты — игра завершена успешно
        await delete_game(mine_id)
        await call.message.answer("🎉 Все безопасные ячейки открыты! Игра завершена.")

    await call.answer(f"+{cell['amount']}")


# ==============================================================================
# ------------------------- handlers_craft.py -------------------------
# ==============================================================================

# -*- coding: utf-8 -*-
"""
Добыча дерева (кулдаун 20 минут), крафт-меню, броня, печка (переплавка руды).
"""



router_craft = Router(name="craft")


# ---------- Добыча дерева ----------

@router_craft.message(F.text.func(lambda t: t and t.lower().strip() == TRIGGER_CHOP))
async def chop_wood(message: Message):
    await ensure_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    row = await get_user(message.from_user.id)
    now = int(time.time())

    if now - row["last_wood"] < WOOD_COOLDOWN_SECONDS:
        remain = WOOD_COOLDOWN_SECONDS - (now - row["last_wood"])
        mins = remain // 60
        secs = remain % 60
        await message.reply(f"⏳ Дерево ещё не выросло. Подождите {mins} мин {secs} сек.")
        return

    amount = chop_wood_amount(WOOD_MIN, WOOD_MAX)
    await add_resource(message.from_user.id, "wood", amount)
    await set_field(message.from_user.id, "last_wood", now)

    text, entities = await build_text([
        ("emoji", "wood"), f" Вы добыли {amount} дерева!",
    ])
    await message.reply(text, entities=entities)


# ---------- Меню крафта ----------

@router_craft.callback_query(F.data == "open_craft")
async def open_craft(call: CallbackQuery):
    text, entities = await build_text([
        ("emoji", "pickaxe"), " Меню крафта. Выберите, что скрафтить:",
    ])
    await call.message.edit_text(text, entities=entities, reply_markup=await craft_menu_kb())
    await call.answer()


async def _try_craft(user_id: int, recipe_key: str) -> tuple[bool, str]:
    recipe = CRAFT_RECIPES[recipe_key]
    row = await get_user(user_id)

    # проверяем хватает ли ресурсов
    for res, need in recipe["cost"].items():
        if row[res] < need:
            cost_str = ", ".join(f"{v} {k}" for k, v in recipe["cost"].items())
            return False, f"Недостаточно ресурсов. Нужно: {cost_str}"

    for res, need in recipe["cost"].items():
        await try_spend_resource(user_id, res, need)

    for res, gain in recipe.get("gain", {}).items():
        await add_resource(user_id, res, gain)

    if recipe_key == "pickaxe":
        cur = await get_field(user_id, "pickaxe_level")
        await set_field(user_id, "pickaxe_level", cur + 1)
    elif recipe_key == "sword":
        cur = await get_field(user_id, "sword_level")
        await set_field(user_id, "sword_level", cur + 1)
    elif recipe_key == "armor":
        cur = await get_field(user_id, "armor_level")
        if cur > 0:
            return False, "Броня уже скрафчена. Используйте улучшение."
        await set_field(user_id, "armor_level", 1)
    elif recipe_key == "armor_upgrade":
        cur = await get_field(user_id, "armor_level")
        await set_field(user_id, "armor_level", cur + 1)

    return True, f"✅ Скрафчено: {recipe['name']}"


@router_craft.callback_query(F.data == "craft_sticks")
async def craft_sticks(call: CallbackQuery):
    ok, msg = await _try_craft(call.from_user.id, "sticks")
    await call.answer(msg, show_alert=not ok)


@router_craft.callback_query(F.data == "craft_pickaxe")
async def craft_pickaxe(call: CallbackQuery):
    ok, msg = await _try_craft(call.from_user.id, "pickaxe")
    await call.answer(msg, show_alert=not ok)


@router_craft.callback_query(F.data == "craft_sword")
async def craft_sword(call: CallbackQuery):
    ok, msg = await _try_craft(call.from_user.id, "sword")
    await call.answer(msg, show_alert=not ok)


# ---------- Броня ----------

@router_craft.callback_query(F.data == "open_armor")
async def open_armor(call: CallbackQuery):
    row = await get_user(call.from_user.id)
    text, entities = await build_text([
        ("emoji", "armor"), f" Раздел брони.\nТекущий уровень брони: {row['armor_level']}\n\n",
        "Скрафтить новую броню или улучшить существующую:",
    ])
    await call.message.edit_text(text, entities=entities, reply_markup=await armor_menu_kb())
    await call.answer()


@router_craft.callback_query(F.data == "craft_armor")
async def craft_armor(call: CallbackQuery):
    ok, msg = await _try_craft(call.from_user.id, "armor")
    await call.answer(msg, show_alert=True)


@router_craft.callback_query(F.data == "upgrade_armor")
async def upgrade_armor(call: CallbackQuery):
    row = await get_user(call.from_user.id)
    if row["armor_level"] == 0:
        await call.answer("Сначала скрафтите базовую броню.", show_alert=True)
        return
    ok, msg = await _try_craft(call.from_user.id, "armor_upgrade")
    await call.answer(msg, show_alert=True)


# ---------- Печка ----------

@router_craft.callback_query(F.data == "open_furnace")
async def open_furnace(call: CallbackQuery):
    user = await get_user(call.from_user.id)
    text, entities = await build_text([
        ("emoji", "furnace"), f" Печка.\n",
        ("emoji", "raw_iron"), f" Сырая руда: {user['raw_iron']}\n",
        ("emoji", "wood"), f" Дерево (топливо): {user['wood']}\n\n",
        "1 дерево + 1 руда → 1 железо",
    ])
    await call.message.edit_text(text, entities=entities, reply_markup=await furnace_menu_kb())
    await call.answer()


@router_craft.callback_query(F.data == "furnace_smelt")
async def furnace_smelt(call: CallbackQuery):
    user = await get_user(call.from_user.id)
    amount = min(user["raw_iron"], user["wood"])
    if amount <= 0:
        await call.answer("Нужна и руда, и дерево (топливо) для переплавки.", show_alert=True)
        return
    await try_spend_resource(call.from_user.id, "raw_iron", amount)
    await try_spend_resource(call.from_user.id, "wood", amount)
    await add_resource(call.from_user.id, "iron", amount)
    await call.answer(f"🔥 Переплавлено: {amount} железа", show_alert=True)


# ==============================================================================
# ------------------------- handlers_pvp.py -------------------------
# ==============================================================================

# -*- coding: utf-8 -*-
"""
PVP: реплай на сообщение соперника + "пп <сумма>" — вызов на дуэль со ставкой.
Соперник может принять/отклонить. При принятии ставка списывается у обоих,
дерутся мечами, у каждого HP-полоска (сердечки), победитель забирает банк.
"""



router_pvp = Router(name="pvp")

PVP_PATTERN = re.compile(rf"^{TRIGGER_PVP}\s+(\d+)$", re.IGNORECASE)


@router_pvp.message(F.text.regexp(PVP_PATTERN) & F.reply_to_message)
async def pvp_challenge(message: Message):
    match = PVP_PATTERN.match(message.text.strip())
    bet = int(match.group(1))

    opponent = message.reply_to_message.from_user
    if opponent.id == message.from_user.id:
        await message.reply("Нельзя вызвать самого себя.")
        return
    if opponent.is_bot:
        await message.reply("Нельзя вызвать бота.")
        return

    await ensure_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    await ensure_user(opponent.id, opponent.username or "", opponent.first_name or "")

    challenger = await get_user(message.from_user.id)
    if challenger["diamonds"] < bet or bet <= 0:
        await message.reply("Недостаточно алмазов для такой ставки.")
        return

    challenge_id = new_challenge_id()
    await create_pvp_challenge(challenge_id, message.chat.id, message.from_user.id, opponent.id, bet)

    text, entities = await build_text([
        f"⚔️ {message.from_user.first_name} вызывает {opponent.first_name} на дуэль!\n",
        f"Ставка: {bet} ", ("emoji", "diamond"),
    ])
    await message.answer(text, entities=entities, reply_markup=await pvp_offer_kb(challenge_id))


@router_pvp.callback_query(F.data.startswith("pvp_decline_"))
async def pvp_decline(call: CallbackQuery):
    challenge_id = call.data.replace("pvp_decline_", "")
    challenge = await get_pvp_challenge(challenge_id)
    if not challenge:
        await call.answer("Заявка не найдена.", show_alert=True)
        return
    if call.from_user.id != challenge["opponent_id"]:
        await call.answer("Это не ваш вызов.", show_alert=True)
        return
    await delete_pvp_challenge(challenge_id)
    await call.message.edit_text("❌ Дуэль отклонена.")
    await call.answer()


@router_pvp.callback_query(F.data.startswith("pvp_accept_"))
async def pvp_accept(call: CallbackQuery):
    challenge_id = call.data.replace("pvp_accept_", "")
    challenge = await get_pvp_challenge(challenge_id)
    if not challenge:
        await call.answer("Заявка не найдена.", show_alert=True)
        return
    if call.from_user.id != challenge["opponent_id"]:
        await call.answer("Это не ваш вызов.", show_alert=True)
        return

    bet = challenge["bet"]
    challenger_id = challenge["challenger_id"]
    opponent_id = challenge["opponent_id"]

    ch_row = await get_user(challenger_id)
    op_row = await get_user(opponent_id)
    if ch_row["diamonds"] < bet:
        await call.answer("У вызвавшего игрока недостаточно алмазов, дуэль отменена.", show_alert=True)
        await delete_pvp_challenge(challenge_id)
        return
    if op_row["diamonds"] < bet:
        await call.answer("У вас недостаточно алмазов для этой ставки.", show_alert=True)
        return

    await try_spend_resource(challenger_id, "diamonds", bet)
    await try_spend_resource(opponent_id, "diamonds", bet)

    fight_data = {
        "challenger_id": challenger_id,
        "opponent_id": opponent_id,
        "challenger_hp": PVP_MAX_HP,
        "opponent_hp": PVP_MAX_HP,
        "bet": bet,
        "turn": challenger_id,  # кто бьёт следующим
    }
    await update_pvp_challenge(challenge_id, status="fighting", data=__import__("json").dumps(fight_data))

    ch_name = ch_row["first_name"] or "Игрок 1"
    op_name = op_row["first_name"] or "Игрок 2"

    text, entities = await build_text([
        "⚔️ Дуэль началась!\n\n",
        f"{ch_name}: {hp_hearts_bar(PVP_MAX_HP)}\n",
        f"{op_name}: {hp_hearts_bar(PVP_MAX_HP)}\n\n",
        f"Ход: {ch_name}",
    ])
    await call.message.edit_text(text, entities=entities, reply_markup=await pvp_fight_kb(challenge_id))
    await call.answer()


@router_pvp.callback_query(F.data.startswith("pvp_hit_"))
async def pvp_hit(call: CallbackQuery):
    import json
    challenge_id = call.data.replace("pvp_hit_", "")
    challenge = await get_pvp_challenge(challenge_id)
    if not challenge or challenge["status"] != "fighting":
        await call.answer("Бой уже завершён.", show_alert=True)
        return

    fight = json.loads(challenge["data"])
    if call.from_user.id != fight["turn"]:
        await call.answer("Сейчас не ваш ход!", show_alert=True)
        return

    attacker_id = fight["turn"]
    defender_id = fight["opponent_id"] if attacker_id == fight["challenger_id"] else fight["challenger_id"]

    attacker_row = await get_user(attacker_id)
    defender_row = await get_user(defender_id)

    dmg = apply_hit(attacker_row["sword_level"], defender_row["armor_level"])

    if defender_id == fight["opponent_id"]:
        fight["opponent_hp"] = max(0, fight["opponent_hp"] - dmg)
    else:
        fight["challenger_hp"] = max(0, fight["challenger_hp"] - dmg)

    ch_row = await get_user(fight["challenger_id"])
    op_row = await get_user(fight["opponent_id"])
    ch_name = ch_row["first_name"] or "Игрок 1"
    op_name = op_row["first_name"] or "Игрок 2"

    # Проверка на конец боя
    if fight["challenger_hp"] <= 0 or fight["opponent_hp"] <= 0:
        winner_id = fight["opponent_id"] if fight["challenger_hp"] <= 0 else fight["challenger_id"]
        loser_id = fight["challenger_id"] if winner_id == fight["opponent_id"] else fight["opponent_id"]
        prize = fight["bet"] * 2
        await add_resource(winner_id, "diamonds", prize)
        await set_field(winner_id, "wins", (await get_field(winner_id, "wins")) + 1)
        await set_field(loser_id, "losses", (await get_field(loser_id, "losses")) + 1)
        await delete_pvp_challenge(challenge_id)

        winner_row = await get_user(winner_id)
        winner_name = winner_row["first_name"] or "Победитель"

        text, entities = await build_text([
            f"🏆 {winner_name} побеждает в дуэли!\n",
            f"Выигрыш: {prize} ", ("emoji", "diamond"),
        ])
        await call.message.edit_text(text, entities=entities)
        await call.answer(f"Урон: {dmg}")
        return

    # передаём ход
    fight["turn"] = defender_id
    await update_pvp_challenge(challenge_id, data=json.dumps(fight))

    text, entities = await build_text([
        "⚔️ Дуэль продолжается!\n\n",
        f"{ch_name}: {hp_hearts_bar(fight['challenger_hp'])}\n",
        f"{op_name}: {hp_hearts_bar(fight['opponent_hp'])}\n\n",
        f"💥 Урон: {dmg}\n",
        f"Ход: {ch_name if fight['turn'] == fight['challenger_id'] else op_name}",
    ])
    await call.message.edit_text(text, entities=entities, reply_markup=await pvp_fight_kb(challenge_id))
    await call.answer(f"Урон: {dmg}")


@router_pvp.callback_query(F.data == "open_pvp_info")
async def pvp_info(call: CallbackQuery):
    from keyboards import back_kb
    text = (
        "⚔️ Как начать PVP-дуэль:\n\n"
        "Ответьте (реплай) на сообщение соперника в чате и напишите:\n"
        "«пп <сумма>» — например: пп 5\n\n"
        "Соперник получит приглашение с кнопками «Принять» / «Отклонить».\n"
        "Если он согласится — ставка спишется у обоих, и начнётся бой на мечах "
        "с полоской здоровья. Победитель забирает весь банк."
    )
    await call.message.edit_text(text, reply_markup=await back_kb())
    await call.answer()


# ==============================================================================
# ------------------------- handlers_transfer.py -------------------------
# ==============================================================================

# -*- coding: utf-8 -*-
"""
Перевод ресурсов: ответом на сообщение пользователя пишем
"дать <количество> <ресурс>", например "дать 5 алмазов" или "дать 10 железа".
"""



router_transfer = Router(name="transfer")

RESOURCE_ALIASES = {
    "алмаз": "diamonds", "алмаза": "diamonds", "алмазов": "diamonds", "алмазы": "diamonds",
    "железо": "iron", "железа": "iron",
    "уголь": "coal", "угля": "coal",
    "камень": "stone", "камня": "stone", "камней": "stone",
    "дерево": "wood", "дерева": "wood",
    "палка": "sticks", "палки": "sticks", "палок": "sticks",
    "руда": "raw_iron", "руды": "raw_iron",
}

TRANSFER_PATTERN = re.compile(rf"^{TRIGGER_TRANSFER}\s+(\d+)\s+(\S+)$", re.IGNORECASE)


@router_transfer.message(F.text.regexp(TRANSFER_PATTERN) & F.reply_to_message)
async def transfer_resource(message: Message):
    match = TRANSFER_PATTERN.match(message.text.strip())
    amount = int(match.group(1))
    resource_word = match.group(2).lower()

    resource = RESOURCE_ALIASES.get(resource_word)
    if resource is None:
        await message.reply(
            "Не распознал ресурс. Используйте: алмазы, железо, уголь, камень, дерево, палки, руда."
        )
        return

    target = message.reply_to_message.from_user
    if target.id == message.from_user.id:
        await message.reply("Нельзя переводить самому себе.")
        return
    if target.is_bot:
        await message.reply("Нельзя переводить боту.")
        return

    await ensure_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    await ensure_user(target.id, target.username or "", target.first_name or "")

    if amount <= 0:
        await message.reply("Количество должно быть больше нуля.")
        return

    ok = await try_spend_resource(message.from_user.id, resource, amount)
    if not ok:
        await message.reply("Недостаточно ресурсов для перевода.")
        return

    await add_resource(target.id, resource, amount)

    emoji_key = {
        "diamonds": "diamond", "iron": "iron", "coal": "coal",
        "stone": "stone", "wood": "wood", "sticks": "stick", "raw_iron": "raw_iron",
    }[resource]

    text, entities = await build_text([
        f"✅ {message.from_user.first_name} передал(а) {target.first_name}: ",
        f"+{amount} ", ("emoji", emoji_key),
    ])
    await message.answer(text, entities=entities)


# ==============================================================================
# ------------------------- handlers_lucky.py -------------------------
# ==============================================================================

# -*- coding: utf-8 -*-
"""
Lucky Block (за 5 алмазов случайные награды) и мини-игра "Полоски"
(выбираешь 1 из 5 полос, там либо приз, либо динамит-проигрыш).
"""



router_lucky = Router(name="lucky")

RESOURCE_EMOJI_KEY = {
    "diamonds": "diamond", "iron": "iron", "coal": "coal",
    "stone": "stone", "wood": "wood",
}
RESOURCE_NAME_RU = {
    "diamonds": "алмазов", "iron": "железа", "coal": "угля",
    "stone": "камня", "wood": "дерева",
}


@router_lucky.callback_query(F.data == "open_lucky")
async def open_lucky(call: CallbackQuery):
    text, entities = await build_text([
        ("emoji", "lucky_block"), f" Lucky Block — {LUCKY_BLOCK_COST} ", ("emoji", "diamond"),
        "\nСлучайный набор ресурсов при открытии. Иногда пусто, иногда джекпот!",
    ])
    await call.message.edit_text(text, entities=entities, reply_markup=await lucky_confirm_kb())
    await call.answer()


@router_lucky.message(F.text.func(lambda t: t and t.lower().strip() == TRIGGER_LUCKY))
async def text_lucky(message: Message):
    await ensure_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    text, entities = await build_text([
        ("emoji", "lucky_block"), f" Lucky Block — {LUCKY_BLOCK_COST} ", ("emoji", "diamond"),
        "\nСлучайный набор ресурсов при открытии. Иногда пусто, иногда джекпот!",
    ])
    await message.answer(text, entities=entities, reply_markup=await lucky_confirm_kb())


@router_lucky.callback_query(F.data == "lucky_open")
async def lucky_open(call: CallbackQuery):
    ok = await try_spend_resource(call.from_user.id, "diamonds", LUCKY_BLOCK_COST)
    if not ok:
        await call.answer("Недостаточно алмазов.", show_alert=True)
        return

    drops = open_lucky_block()
    if not drops:
        text, entities = await build_text([
            ("emoji", "lucky_block"), " Блок оказался пустым... Повезёт в следующий раз!",
        ])
        await call.message.edit_text(text, entities=entities, reply_markup=await back_kb())
        await call.answer()
        return

    parts = [("emoji", "lucky_block"), " Вы получили:\n"]
    for resource, amount in drops:
        await add_resource(call.from_user.id, resource, amount)
        parts.append(("emoji", RESOURCE_EMOJI_KEY[resource]))
        parts.append(f" +{amount} {RESOURCE_NAME_RU[resource]}\n")

    text, entities = await build_text(parts)
    await call.message.edit_text(text, entities=entities, reply_markup=await back_kb())
    await call.answer("🎉 Награда получена!")


# ---------- Мини-игра "Полоски" ----------

@router_lucky.message(F.text.func(lambda t: t and t.lower().strip() in ("полоски", "полоска")))
async def strip_game_start(message: Message):
    await ensure_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    round_data = generate_strip_round()
    round_id = new_mine_id()
    await save_game(round_id, "strip", message.chat.id, {
        "owner_id": message.from_user.id,
        **round_data,
    })
    text, entities = await build_text([
        "🎯 Игра «Полоски»! Выберите одну из пяти полос — в одной из них приз.",
    ])
    await message.answer(text, entities=entities, reply_markup=await strip_field_kb(round_id))


@router_lucky.callback_query(F.data.startswith("strip_"))
async def strip_pick(call: CallbackQuery):
    _, round_id, idx_str = call.data.split("_")
    idx = int(idx_str)

    game = await load_game(round_id)
    if game is None:
        await call.answer("Игра уже завершена.", show_alert=True)
        return
    if game["owner_id"] != call.from_user.id:
        await call.answer("Это не ваша игра!", show_alert=True)
        return

    winning_row = game["winning_row"]
    await delete_game(round_id)

    if idx != winning_row:
        text, entities = await build_text([
            ("emoji", "dynamite"), f" Мимо! Приз был в полосе {winning_row + 1}. Повезёт в следующий раз.",
        ])
        await call.message.edit_text(text, entities=entities, reply_markup=await back_kb())
        await call.answer()
        return

    resource = game["reward_type"]
    amount = game["reward_amount"]

    if resource == "dynamite" or amount <= 0:
        text, entities = await build_text([
            ("emoji", "dynamite"), " В этой полосе оказался динамит. Пусто!",
        ])
        await call.message.edit_text(text, entities=entities, reply_markup=await back_kb())
        await call.answer()
        return

    await add_resource(call.from_user.id, resource, amount)
    emoji_key = RESOURCE_EMOJI_KEY.get(resource, "diamond")
    name_ru = RESOURCE_NAME_RU.get(resource, resource)

    text, entities = await build_text([
        "🎉 Угадали! Вы нашли: ", ("emoji", emoji_key), f" +{amount} {name_ru}",
    ])
    await call.message.edit_text(text, entities=entities, reply_markup=await back_kb())
    await call.answer("🎉")


# ==============================================================================
# ------------------------- handlers_shop.py -------------------------
# ==============================================================================

# -*- coding: utf-8 -*-
"""
Магазин за Telegram Stars (валюта XTR, встроенная в Bot API — провайдер не нужен).

Поток покупки алмазов:
1. Пользователь жмёт "Купить алмазы за звёзды"
2. Бот просит ввести количество ЗВЁЗД, которое он хочет потратить
3. Пользователь пишет число, бот показывает кнопку "Оплатить N ⭐ (→ M алмазов)"
4. По нажатию бот вызывает send_invoice(currency="XTR") — Telegram сам показывает
   системное окно "Вы хотите перевести этому боту N Stars?"
5. pre_checkout_query подтверждается автоматически (без доп. проверок склада и т.п.)
6. При successful_payment начисляем алмазы/ресурсы согласно payload

Остальные товары (пак железа, пак переплавленных алмазов, Creative) — фиксированная
цена, отдельные инвойсы, вызываются сразу по нажатию кнопки в магазине.
"""



router_shop = Router(name="shop")


@router_shop.callback_query(F.data.in_(["open_shop", "back_shop"]))
async def open_shop(call: CallbackQuery):
    text, entities = await build_text([
        ("emoji", "btn_shop"), " Магазин.\nВсе покупки — за Telegram Stars ⭐.",
    ])
    await call.message.edit_text(text, entities=entities, reply_markup=await shop_menu_kb())
    await call.answer()


# ---------- Покупка алмазов за произвольное кол-во звёзд ----------

@router_shop.callback_query(F.data == "shop_diamonds")
async def shop_diamonds_start(call: CallbackQuery, state: FSMContext):
    text, entities = await build_text([
        ("emoji", "star"), " Введите количество звёзд, которое хотите потратить.\n",
        f"Курс: {STARS_PER_DIAMOND} ⭐ = 1 ", ("emoji", "diamond"),
    ])
    await call.message.edit_text(text, entities=entities, reply_markup=await back_kb("shop"))
    await state.set_state(UserStates.waiting_shop_diamond_amount)
    await call.answer()


@router_shop.message(UserStates.waiting_shop_diamond_amount, F.text.regexp(r"^\d+$"))
async def shop_diamonds_amount(message: Message, state: FSMContext):
    stars = int(message.text.strip())
    if stars <= 0:
        await message.reply("Введите число больше нуля.")
        return

    diamonds = stars // STARS_PER_DIAMOND
    if diamonds <= 0:
        await message.reply(f"Слишком мало звёзд. Минимум {STARS_PER_DIAMOND} ⭐ за 1 алмаз.")
        return

    # Пересчитываем звёзды под целое число алмазов, чтобы не было расхождений
    actual_stars = diamonds * STARS_PER_DIAMOND

    b = InlineKeyboardBuilder()
    b.button(
        text=f"⭐ Оплатить {actual_stars} → 💎 {diamonds}",
        callback_data=f"pay_diamonds_{actual_stars}_{diamonds}",
    )
    b.button(text="⬅️ Назад", callback_data="back_shop")
    b.adjust(1)

    await message.answer(
        f"К оплате: {actual_stars} ⭐ → вы получите {diamonds} 💎",
        reply_markup=b.as_markup(),
    )
    await state.clear()


@router_shop.callback_query(F.data.startswith("pay_diamonds_"))
async def pay_diamonds(call: CallbackQuery):
    _, _, stars_str, diamonds_str = call.data.split("_")
    stars = int(stars_str)
    diamonds = int(diamonds_str)

    await call.bot.send_invoice(
        chat_id=call.from_user.id,
        title=f"Покупка {diamonds} алмазов",
        description=f"Обмен звёзд на игровую валюту: {stars} ⭐ → {diamonds} 💎",
        payload=json.dumps({"type": "diamonds", "amount": diamonds}),
        currency="XTR",
        prices=[LabeledPrice(label=f"{diamonds} алмазов", amount=stars)],
    )
    await call.answer()


# ---------- Фиксированные паки ----------

@router_shop.callback_query(F.data == "shop_iron_pack")
async def shop_iron_pack(call: CallbackQuery):
    await call.bot.send_invoice(
        chat_id=call.from_user.id,
        title=f"{STARS_IRON_PACK_AMOUNT} железа (пак)",
        description=f"{STARS_IRON_PACK_AMOUNT} необработанного железа за {STARS_IRON_PACK_COST} ⭐",
        payload=json.dumps({"type": "iron_pack", "amount": STARS_IRON_PACK_AMOUNT}),
        currency="XTR",
        prices=[LabeledPrice(label="Пак железа", amount=STARS_IRON_PACK_COST)],
    )
    await call.answer()


@router_shop.callback_query(F.data == "shop_diamond_pack")
async def shop_diamond_pack(call: CallbackQuery):
    await call.bot.send_invoice(
        chat_id=call.from_user.id,
        title=f"{STARS_DIAMOND_PACK_AMOUNT} алмаза (пак)",
        description=f"{STARS_DIAMOND_PACK_AMOUNT} переплавленных алмаза за {STARS_DIAMOND_PACK_COST} ⭐",
        payload=json.dumps({"type": "diamond_pack", "amount": STARS_DIAMOND_PACK_AMOUNT}),
        currency="XTR",
        prices=[LabeledPrice(label="Пак алмазов", amount=STARS_DIAMOND_PACK_COST)],
    )
    await call.answer()


@router_shop.callback_query(F.data == "shop_creative")
async def shop_creative(call: CallbackQuery):
    await call.bot.send_invoice(
        chat_id=call.from_user.id,
        title="Creative-статус",
        description="VIP-статус: ежечасный бонус вместо ежедневного, увеличенные награды.",
        payload=json.dumps({"type": "creative"}),
        currency="XTR",
        prices=[LabeledPrice(label="Creative", amount=CREATIVE_COST_STARS)],
    )
    await call.answer()


# ---------- Обработка платежей ----------

@router_shop.pre_checkout_query()
async def process_pre_checkout(pre_checkout_q: PreCheckoutQuery):
    # Звёзды — без внешнего провайдера, доп. проверок склада не требуется, подтверждаем всегда
    await pre_checkout_q.answer(ok=True)


@router_shop.message(F.successful_payment)
async def process_successful_payment(message: Message):
    payload = json.loads(message.successful_payment.invoice_payload)
    user_id = message.from_user.id
    await ensure_user(user_id, message.from_user.username or "", message.from_user.first_name or "")

    ptype = payload.get("type")

    if ptype == "diamonds":
        amount = payload["amount"]
        await add_resource(user_id, "diamonds", amount)
        text, entities = await build_text([
            "✅ Оплата прошла успешно!\n+", str(amount), " ", ("emoji", "diamond"),
        ])
        await message.answer(text, entities=entities)

    elif ptype == "iron_pack":
        amount = payload["amount"]
        await add_resource(user_id, "raw_iron", amount)
        text, entities = await build_text([
            "✅ Оплата прошла успешно!\n+", str(amount), " ", ("emoji", "raw_iron"),
        ])
        await message.answer(text, entities=entities)

    elif ptype == "diamond_pack":
        amount = payload["amount"]
        await add_resource(user_id, "diamonds", amount)
        text, entities = await build_text([
            "✅ Оплата прошла успешно!\n+", str(amount), " ", ("emoji", "diamond"),
        ])
        await message.answer(text, entities=entities)

    elif ptype == "creative":
        until = int(time.time()) + 30 * 24 * 60 * 60  # 30 дней Creative-статуса
        await set_field(user_id, "is_creative", 1)
        await set_field(user_id, "creative_until", until)
        text, entities = await build_text([
            ("emoji", "btn_creative"), " Поздравляем! Вы получили Creative-статус на 30 дней.",
        ])
        await message.answer(text, entities=entities)


# ==============================================================================
# ------------------------- handlers_admin.py -------------------------
# ==============================================================================

# -*- coding: utf-8 -*-
"""
Админ-панель. Доступна только пользователю с ADMIN_ID из config.py.
Разделы: Статистика, Эмодзи и оформление, Цвета кнопок, Тексты, Выдать ресурсы, Рассылка.
Всё на русском языке с понятными подписями.
"""



router_admin = Router(name="admin")


def admin_only(handler):
    async def wrapper(event, *args, **kwargs):
        user_id = event.from_user.id
        if user_id != ADMIN_ID:
            if isinstance(event, CallbackQuery):
                await event.answer("⛔ Доступ только для администратора.", show_alert=True)
            else:
                await event.reply("⛔ Эта команда доступна только администратору бота.")
            return
        return await handler(event, *args, **kwargs)
    return wrapper


# ---------- Главное меню админки ----------

async def admin_main_kb():
    b = InlineKeyboardBuilder()
    b.button(text="📊 Статистика", callback_data="adm_stats")
    b.button(text="🎨 Эмодзи и оформление", callback_data="adm_emoji_groups")
    b.button(text="🎨 Цвета кнопок", callback_data="adm_colors")
    b.button(text="📝 Тексты бота", callback_data="adm_texts")
    b.button(text="💎 Выдать ресурсы", callback_data="adm_give")
    b.button(text="📢 Рассылка", callback_data="adm_broadcast")
    b.button(text="🏆 Топ игроков", callback_data="adm_top")
    b.adjust(1)
    return b.as_markup()


@router_admin.message(Command("admin"))
@admin_only
async def cmd_admin(message: Message):
    await message.answer("🛠 Админ-панель бота\n\nВыберите раздел:", reply_markup=await admin_main_kb())


@router_admin.callback_query(F.data == "adm_main")
@admin_only
async def adm_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("🛠 Админ-панель бота\n\nВыберите раздел:", reply_markup=await admin_main_kb())
    await call.answer()


# ---------- Статистика ----------

@router_admin.callback_query(F.data == "adm_stats")
@admin_only
async def adm_stats(call: CallbackQuery):
    stats = await stats_summary()
    text = (
        "📊 Статистика бота\n\n"
        f"👥 Всего пользователей: {stats.get('total_users') or 0}\n"
        f"💎 Алмазов в обороте: {stats.get('total_diamonds') or 0}\n"
        f"🔩 Железа в обороте: {stats.get('total_iron') or 0}\n"
        f"⚫ Угля в обороте: {stats.get('total_coal') or 0}\n"
        f"🪨 Камня в обороте: {stats.get('total_stone') or 0}\n"
        f"🪵 Дерева в обороте: {stats.get('total_wood') or 0}\n"
        f"👑 Creative-игроков: {stats.get('creative_count') or 0}\n"
        f"🏆 Всего побед в PVP: {stats.get('total_wins') or 0}\n"
    )
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ Назад", callback_data="adm_main")
    await call.message.edit_text(text, reply_markup=b.as_markup())
    await call.answer()


@router_admin.callback_query(F.data == "adm_top")
@admin_only
async def adm_top(call: CallbackQuery):
    users = await top_users("diamonds", 10)
    lines = ["🏆 Топ-10 по алмазам:\n"]
    for i, u in enumerate(users, 1):
        name = u["username"] and f"@{u['username']}" or (u["first_name"] or str(u["user_id"]))
        lines.append(f"{i}. {name} — {u['diamonds']} 💎")
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ Назад", callback_data="adm_main")
    await call.message.edit_text("\n".join(lines), reply_markup=b.as_markup())
    await call.answer()


# ---------- Эмодзи и оформление ----------

@router_admin.callback_query(F.data == "adm_emoji_groups")
@admin_only
async def adm_emoji_groups(call: CallbackQuery):
    groups = grouped_slots()
    b = InlineKeyboardBuilder()
    for group_name in groups:
        b.button(text=f"📁 {group_name}", callback_data=f"adm_egroup_{group_name}")
    b.button(text="⬅️ Назад", callback_data="adm_main")
    b.adjust(1)
    text = (
        "🎨 Эмодзи и оформление\n\n"
        "Здесь вы настраиваете премиум-эмодзи для каждого ресурса, предмета и кнопки.\n\n"
        "⚠️ Важно: премиум-эмодзи (custom_emoji_id) отображаются ТОЛЬКО в тексте "
        "сообщений. В тексте самих inline-кнопок Telegram премиум-эмодзи не "
        "поддерживает — там можно поставить только обычный emoji-символ.\n\n"
        "Выберите категорию:"
    )
    await call.message.edit_text(text, reply_markup=b.as_markup())
    await call.answer()


@router_admin.callback_query(F.data.startswith("adm_egroup_"))
@admin_only
async def adm_egroup(call: CallbackQuery):
    group_name = call.data.replace("adm_egroup_", "")
    groups = grouped_slots()
    slots = groups.get(group_name, [])

    b = InlineKeyboardBuilder()
    for slot_key in slots:
        info = EMOJI_SLOT_INFO[slot_key]
        row = await get_emoji(slot_key)
        current = row["fallback_emoji"] or "❓"
        is_premium = "⭐" if row["custom_emoji_id"] else ""
        b.button(text=f"{current} {info['title']} {is_premium}", callback_data=f"adm_eslot_{slot_key}")
    b.button(text="⬅️ Назад", callback_data="adm_emoji_groups")
    b.adjust(1)

    await call.message.edit_text(f"📁 Раздел: {group_name}\n\nВыберите элемент для изменения:", reply_markup=b.as_markup())
    await call.answer()


@router_admin.callback_query(F.data.startswith("adm_eslot_"))
@admin_only
async def adm_eslot(call: CallbackQuery, state: FSMContext):
    slot_key = call.data.replace("adm_eslot_", "")
    info = EMOJI_SLOT_INFO.get(slot_key, {"title": slot_key, "desc": ""})
    row = await get_emoji(slot_key)

    text = (
        f"⚙️ Настройка: {info['title']}\n\n"
        f"📌 Описание: {info['desc']}\n\n"
        f"Текущий обычный эмодзи: {row['fallback_emoji']}\n"
        f"Текущий premium ID: {row['custom_emoji_id'] or 'не установлен'}\n\n"
        "Отправьте новое значение одним сообщением в одном из форматов:\n"
        "• Обычный эмодзи — например: 💎\n"
        "• Premium ID — например: id:5368324170671202286\n"
        "(ID премиум-эмодзи можно получить, переслав нужный эмодзи "
        "специальному боту для получения custom_emoji_id, либо через Bot API "
        "метод getCustomEmojiStickers)"
    )
    b = InlineKeyboardBuilder()
    b.button(text="🗑 Убрать premium (оставить обычный)", callback_data=f"adm_eclear_{slot_key}")
    b.button(text="⬅️ Назад", callback_data="adm_emoji_groups")
    b.adjust(1)

    await state.update_data(editing_slot=slot_key)
    await state.set_state(AdminStates.waiting_emoji_value)
    await call.message.edit_text(text, reply_markup=b.as_markup())
    await call.answer()


@router_admin.callback_query(F.data.startswith("adm_eclear_"))
@admin_only
async def adm_eclear(call: CallbackQuery):
    slot_key = call.data.replace("adm_eclear_", "")
    await set_emoji(slot_key, custom_emoji_id="")
    await call.answer("✅ Premium-эмодзи убран, используется обычный.", show_alert=True)


@router_admin.message(AdminStates.waiting_emoji_value)
@admin_only
async def adm_eslot_input(message: Message, state: FSMContext):
    data = await state.get_data()
    slot_key = data.get("editing_slot")
    if not slot_key:
        await state.clear()
        return

    value = message.text.strip()
    if value.startswith("id:"):
        custom_id = value.replace("id:", "").strip()
        await set_emoji(slot_key, custom_emoji_id=custom_id)
        await message.answer(f"✅ Premium-эмодзи установлен для «{EMOJI_SLOT_INFO.get(slot_key, {}).get('title', slot_key)}».")
    else:
        await set_emoji(slot_key, fallback_emoji=value, custom_emoji_id="")
        await message.answer(f"✅ Обычный эмодзи установлен: {value}")

    await state.clear()
    await message.answer("Вернуться в меню: /admin")


# ---------- Цвета кнопок ----------

COLOR_OPTIONS = [("primary", "🔵 Основной"), ("secondary", "⚪ Второстепенный"), ("destructive", "🔴 Акцент/опасность")]


@router_admin.callback_query(F.data == "adm_colors")
@admin_only
async def adm_colors(call: CallbackQuery):
    rows = await all_button_colors()
    b = InlineKeyboardBuilder()
    for r in rows:
        info = EMOJI_SLOT_INFO.get(r["slot_key"], {"title": r["slot_key"]})
        b.button(text=f"{info['title']} — {r['color']}", callback_data=f"adm_csel_{r['slot_key']}")
    b.button(text="⬅️ Назад", callback_data="adm_main")
    b.adjust(1)
    text = (
        "🎨 Цвета кнопок\n\n"
        "⚠️ Технически Telegram не позволяет ботам задавать произвольный RGB-цвет "
        "у inline-кнопок — оформление зависит от темы клиента пользователя. "
        "Здесь вы задаёте смысловую метку (Основной/Второстепенный/Акцент), "
        "которая используется для группировки и вида кнопки в некоторых клиентах."
    )
    await call.message.edit_text(text, reply_markup=b.as_markup())
    await call.answer()


@router_admin.callback_query(F.data.startswith("adm_csel_"))
@admin_only
async def adm_csel(call: CallbackQuery):
    slot_key = call.data.replace("adm_csel_", "")
    b = InlineKeyboardBuilder()
    for color_key, color_label in COLOR_OPTIONS:
        b.button(text=color_label, callback_data=f"adm_cset_{slot_key}_{color_key}")
    b.button(text="⬅️ Назад", callback_data="adm_colors")
    b.adjust(1)
    await call.message.edit_text("Выберите цвет:", reply_markup=b.as_markup())
    await call.answer()


@router_admin.callback_query(F.data.startswith("adm_cset_"))
@admin_only
async def adm_cset(call: CallbackQuery):
    # формат: adm_cset_<slot_key>_<color>
    body = call.data[len("adm_cset_"):]
    slot_key, color = body.rsplit("_", 1)
    await set_button_color(slot_key, color)
    await call.answer("✅ Цвет обновлён.", show_alert=True)


# ---------- Тексты бота ----------

EDITABLE_TEXTS = {
    "welcome_text": "Текст приветствия (после эмодзи-заголовка)",
}


@router_admin.callback_query(F.data == "adm_texts")
@admin_only
async def adm_texts(call: CallbackQuery):
    b = InlineKeyboardBuilder()
    for key, label in EDITABLE_TEXTS.items():
        b.button(text=label, callback_data=f"adm_tsel_{key}")
    b.button(text="⬅️ Назад", callback_data="adm_main")
    b.adjust(1)
    await call.message.edit_text("📝 Тексты бота\n\nВыберите, что изменить:", reply_markup=b.as_markup())
    await call.answer()


@router_admin.callback_query(F.data.startswith("adm_tsel_"))
@admin_only
async def adm_tsel(call: CallbackQuery, state: FSMContext):
    key = call.data.replace("adm_tsel_", "")
    current = await get_text(key, "(не задано, используется текст по умолчанию)")
    await state.update_data(editing_text=key)
    await state.set_state(AdminStates.waiting_text_value)
    await call.message.edit_text(
        f"Текущий текст:\n\n{current}\n\nОтправьте новый текст сообщением."
    )
    await call.answer()


@router_admin.message(AdminStates.waiting_text_value)
@admin_only
async def adm_tsel_input(message: Message, state: FSMContext):
    data = await state.get_data()
    key = data.get("editing_text")
    if not key:
        await state.clear()
        return
    await set_text(key, message.text)
    await state.clear()
    await message.answer("✅ Текст обновлён. Вернуться в меню: /admin")


# ---------- Выдать ресурсы (себе или любому пользователю) ----------

GIVE_RESOURCES = [
    ("diamonds", "💎 Алмазы"), ("iron", "🔩 Железо"), ("raw_iron", "🟤 Руда железа"),
    ("coal", "⚫ Уголь"), ("stone", "🪨 Камень"), ("wood", "🪵 Дерево"), ("sticks", "➰ Палки"),
]


@router_admin.callback_query(F.data == "adm_give")
@admin_only
async def adm_give(call: CallbackQuery):
    b = InlineKeyboardBuilder()
    b.button(text="💎 Выдать себе алмазы", callback_data="adm_give_self_diamonds")
    b.button(text="👤 Выдать другому пользователю", callback_data="adm_give_other")
    b.button(text="⬅️ Назад", callback_data="adm_main")
    b.adjust(1)
    await call.message.edit_text(
        "💎 Выдача ресурсов\n\n"
        "Можно выдать ресурсы себе (быстрая кнопка для алмазов) или "
        "любому пользователю — по @username или ответом (реплаем) на его сообщение "
        "в общем чате с ботом.",
        reply_markup=b.as_markup(),
    )
    await call.answer()


@router_admin.callback_query(F.data == "adm_give_self_diamonds")
@admin_only
async def adm_give_self_diamonds(call: CallbackQuery, state: FSMContext):
    await state.update_data(give_target_id=ADMIN_ID, give_resource="diamonds")
    await state.set_state(AdminStates.waiting_give_resource_amount)
    await call.message.edit_text("💎 Введите количество алмазов для начисления себе:")
    await call.answer()


@router_admin.callback_query(F.data == "adm_give_other")
@admin_only
async def adm_give_other(call: CallbackQuery, state: FSMContext):
    b = InlineKeyboardBuilder()
    for res_key, res_label in GIVE_RESOURCES:
        b.button(text=res_label, callback_data=f"adm_gres_{res_key}")
    b.button(text="⬅️ Назад", callback_data="adm_give")
    b.adjust(2)
    await call.message.edit_text("Выберите ресурс для выдачи:", reply_markup=b.as_markup())
    await call.answer()


@router_admin.callback_query(F.data.startswith("adm_gres_"))
@admin_only
async def adm_gres(call: CallbackQuery, state: FSMContext):
    resource = call.data.replace("adm_gres_", "")
    await state.update_data(give_resource=resource)
    await state.set_state(AdminStates.waiting_give_target)
    await call.message.edit_text(
        "👤 Укажите получателя:\n\n"
        "Отправьте @username пользователя, либо перешлите (форвард) его "
        "сообщение сюда, либо ответьте (реплай) на его сообщение в этом чате с ботом."
    )
    await call.answer()


@router_admin.message(AdminStates.waiting_give_target)
@admin_only
async def adm_give_target_input(message: Message, state: FSMContext):
    target_id = None
    target_name = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.first_name
    elif message.forward_from:
        target_id = message.forward_from.id
        target_name = message.forward_from.first_name
    elif message.text and message.text.strip().startswith("@"):
        user_row = await get_user_by_username(message.text.strip())
        if user_row is None:
            await message.answer(
                "⚠️ Пользователь с таким @username не найден в базе бота "
                "(он должен хотя бы раз запустить бота). Попробуйте реплай или форвард."
            )
            return
        target_id = user_row["user_id"]
        target_name = user_row["first_name"] or user_row["username"]
    else:
        await message.answer("Не удалось определить пользователя. Используйте @username, реплай или форвард.")
        return

    await ensure_user(target_id)
    await state.update_data(give_target_id=target_id, give_target_name=target_name)
    await state.set_state(AdminStates.waiting_give_resource_amount)
    await message.answer(f"Получатель: {target_name} (id {target_id})\n\nВведите количество:")


@router_admin.message(AdminStates.waiting_give_resource_amount, F.text.regexp(r"^-?\d+$"))
@admin_only
async def adm_give_amount_input(message: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data.get("give_target_id")
    resource = data.get("give_resource", "diamonds")
    amount = int(message.text.strip())

    if target_id is None:
        await message.answer("Ошибка: получатель не определён. Начните заново: /admin")
        await state.clear()
        return

    await ensure_user(target_id)
    await add_resource(target_id, resource, amount)
    res_label = dict(GIVE_RESOURCES).get(resource, resource)

    await message.answer(f"✅ Начислено {amount} ({res_label}) пользователю с id {target_id}.")
    await state.clear()


# ---------- Рассылка ----------

@router_admin.callback_query(F.data == "adm_broadcast")
@admin_only
async def adm_broadcast(call: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_broadcast_text)
    await call.message.edit_text("📢 Отправьте текст сообщения для рассылки всем пользователям бота.")
    await call.answer()


@router_admin.message(AdminStates.waiting_broadcast_text)
@admin_only
async def adm_broadcast_input(message: Message, state: FSMContext):
    await state.clear()
    users = await all_users()
    sent, failed = 0, 0
    status_msg = await message.answer(f"⏳ Рассылка начата, получателей: {len(users)}")

    for u in users:
        try:
            await message.bot.send_message(u["user_id"], message.text)
            sent += 1
        except Exception:
            failed += 1

    await status_msg.edit_text(f"✅ Рассылка завершена.\nОтправлено: {sent}\nОшибок: {failed}")


# ==============================================================================
# ------------------------- main.py -------------------------
# ==============================================================================

# -*- coding: utf-8 -*-
"""
Точка входа. Запуск: python main.py
Переменные окружения (задаются на Railway во вкладке Variables):
    BOT_TOKEN — токен бота от @BotFather
    ADMIN_ID  — ваш Telegram user_id (число)
"""




# Роутеры

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def main():
    if not BOT_TOKEN or BOT_TOKEN == "ВАШ_ТОКЕН_СЮДА":
        raise RuntimeError(
            "Не задан BOT_TOKEN. Установите переменную окружения BOT_TOKEN "
            "(на Railway: Settings → Variables)."
        )

    await init_db()
    logger.info("База данных инициализирована.")

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    # ВАЖНО: порядок регистрации важен — более специфичные роутеры (regex-триггеры)
    # должны идти раньше общих текстовых хендлеров, если такие появятся.
    dp.include_router(router_admin)     # админ-команды первыми
    dp.include_router(router_start)
    dp.include_router(router_balance)
    dp.include_router(router_mine)
    dp.include_router(router_craft)
    dp.include_router(router_pvp)
    dp.include_router(router_transfer)
    dp.include_router(router_lucky)
    dp.include_router(router_shop)

    logger.info("Бот запускается...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
