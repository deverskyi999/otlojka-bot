"""
Kewo AI — Telegram-бот с ИИ-персоной "Kewo AI" (создатель — @deverskyi).
Функции: человечный чат без markdown-мусора, выбор модели, экспорт кода в
файл, статьи в Telegraph, напоминания, опросы, генерация изображений,
донаты (CryptoBot + Telegram Stars), админ-панель с премиум-эмодзи на любую
кнопку/текст (Bot API 9.4: icon_custom_emoji_id + style).
"""
from __future__ import annotations

import asyncio
import calendar
import html
import json
import logging
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterator, Optional

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand, BotCommandScopeChat, BotCommandScopeDefault, BufferedInputFile,
    CallbackQuery, InlineKeyboardButton,
    InlineKeyboardMarkup, KeyboardButton, Message, PreCheckoutQuery,
    ReplyKeyboardMarkup,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("dev_ai_bot")

DB_PATH = os.getenv("DB_PATH", "dev_ai_bot.db")

# ======================================================================
# НАСТРОЙКИ
# ======================================================================

@dataclass
class Settings:
    bot_token: str
    ai_api_key: str
    ai_base_url: str = "https://api.imbek.fun/v1"
    owner_id: int = 0
    default_model: str = "claude-sonnet-4-6"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            bot_token=os.environ["BOT_TOKEN"],
            ai_api_key=os.environ["AI_API_KEY"],
            ai_base_url=os.getenv("AI_BASE_URL", cls.ai_base_url),
            owner_id=int(os.getenv("OWNER_ID", "0")),
            default_model=os.getenv("DEFAULT_MODEL", cls.default_model),
        )


# Модели, доступные на твоём прокси (только те, что были ✅ на скрине).
# Если провайдер добавит/уберёт модели — поправь список здесь.
AVAILABLE_MODELS: list[tuple[str, str]] = [
    ("claude-sonnet-4-6", "🧠 claude-sonnet-4-6 — лучший кодер (по умолчанию)"),
    ("gpt-5.4", "🧠 gpt-5.4"),
    ("gpt-5.6-luna", "🧠 gpt-5.6-luna"),
    ("gpt-5.6-terra", "🧠 gpt-5.6-terra"),
    ("claude-haiku-4-5", "⚡ claude-haiku-4-5 — быстрая"),
    ("im-pro", "🧠 im-pro"),
    ("im-flash", "⚡ im-flash — быстрая"),
    ("deepseek-v4-pro", "🧠 deepseek-v4-pro"),
    ("deepseek-v4-flash", "⚡ deepseek-v4-flash — быстрая"),
    ("mimo-v2.5-pro", "🧠 mimo-v2.5-pro"),
    ("mimo-v2.5", "⚡ mimo-v2.5"),
]
MODEL_KEYS = {key for key, _ in AVAILABLE_MODELS}

DEV_AI_PERSONA = (
    "Тебя зовут Kewo AI. Тебя создал @deverskyi (Деверский) и обучил на собственном "
    "железе. Ты НИКОГДА не говоришь, что тебя сделала другая компания или что ты "
    "другая модель (GPT, Claude, Gemini, DeepSeek и т.п.) — для пользователя ты всегда "
    "только Kewo AI от @deverskyi, даже если тебя прямо об этом спрашивают.\n\n"
    "Общайся живо, по-человечески, но не наигранно — как толковый друг-программист, "
    "а не как корпоративный ассистент. Без канцелярита, без воды, по делу. Не начинай "
    "ответы с \"Конечно!\" или \"Отличный вопрос!\" — сразу отвечай по существу.\n\n"
    "Ты отличный программист: пишешь чистый, рабочий, современный код на любом языке, "
    "разбираешься в архитектуре, дизайне и планировании проектов.\n\n"
    "Форматируй ответы под Telegram: **жирный** для акцентов, `код` для инлайн-кода, "
    "тройные кавычки для блоков кода с указанием языка. Не используй markdown-заголовки "
    "(#) и не пиши сырых звёздочек мимо форматирования."
)

# Включается/выключается тумблером в админке ("😈 Дерзкие ответы на мат").
SAVAGE_ADDENDUM = (
    "\n\nЕсли пользователь матерится или откровенно грубит — можешь ответить с "
    "сарказмом или подколоть в ответ, не будь безответным ковриком. Но не переходи в "
    "реальные оскорбления по национальности, внешности, здоровью и т.п. — держи это в "
    "рамках дружеского троллинга, а не травли."
)

MAINTENANCE_MESSAGE = "🛠 Технические работы, скоро вернёмся. Загляни чуть позже."

# Актуальный список функций бота — используется в "Само-улучшении", чтобы ИИ
# предлагал улучшения ЗНАЯ, что уже есть, а не придумывал дубликаты. Обновляй
# этот текст, когда добавляешь/убираешь функции.
BOT_FEATURE_SUMMARY = (
    "Команды: /start (приветствие), /support (донаты + поддержка), /favorites (избранные ответы "
    "ИИ), /profile (уровень и бейджи), /admin (админ-панель, только владелец).\n\n"
    "Главное меню пользователя (нижняя клавиатура): «🏠 Главное» открывает хаб с кнопками, "
    "«💛 Помочь проекту» открывает донаты.\n\n"
    "Хаб (инлайн-меню): 🎨 Нарисовать (генерация изображений через AI-прокси), "
    "📰 Статья в Telegraph (ИИ пишет статью и публикует на telegra.ph), "
    "⏰ Напоминание (разовые 'через N минут/часов' и 'в ЧЧ:ММ', а также повторяющиеся 'каждый "
    "день/каждый понедельник/каждое N число в ЧЧ:ММ' — фоновый воркер сам перепланирует после "
    "срабатывания), 📊 Опрос (нативный, с выбором анонимный/публичный), 🌍 Перевод текста через ИИ, "
    "🗒️ Заметки (с категориями Общее/Работа/Личное/Идея и фильтром по категориям), "
    "🎲 Мини-игра (нативные Telegram-дайсы), ☁️ Погода (Open-Meteo, без ключа, геокодинг по "
    "названию города + прогноз на 3 дня), ✏️ Свой стиль ответа (персональная надстройка над "
    "системным промптом ИИ на каждого пользователя).\n\n"
    "Обычный чат: любое текстовое сообщение уходит в ИИ с персоной 'Kewo AI' (создатель "
    "@deverskyi, никогда не признаётся, что это другая модель); ответ конвертируется из "
    "markdown в Telegram HTML (жирный/код/списки, без сырых звёздочек); показывается нативный "
    "статус 'печатает...' пока думает; под ответом кнопки '⭐ В избранное' и (если есть код) "
    "'скачать код файлом' (.py/.js/.html и т.д. по языку).\n\n"
    "Геймификация: бейджи 'Новичок' (10 сообщений), 'Активист' (100 сообщений), 'Гений' "
    "(использовал 5+ разных функций бота) с авто-уведомлением при получении; /profile показывает "
    "уровень (по количеству сообщений) и список бейджей.\n\n"
    "Донаты: CryptoBot (Crypto Pay API, свой ключ в админке, выбор валюты USDT/TON/BTC, "
    "своя сумма, фоновая авто-проверка оплаты) и Telegram Stars (пресеты 50/100/250/500 + своя сумма).\n\n"
    "Само-рассылка: админ пишет сообщение один раз, задаёт время (разово или повтор — "
    "ежедневно/еженедельно/ежемесячно), бот сам шлёт всем пользователям без дальнейшего участия "
    "админа; есть список активных запланированных рассылок с отменой.\n\n"
    "Админ-панель: статистика (юзеры, сообщения, топ активных), список юзеров с пагинацией, "
    "экспорт юзеров в CSV, разовая рассылка всем, запланированная (авто) рассылка, модель ИИ по "
    "умолчанию (скрыта от юзеров), модель для картинок, тумблер 'дерзкие ответы на мат', тумблер "
    "'работа в группах' (по упоминанию/ответу), тумблер 'технические работы', юзернейм поддержки, "
    "ключ CryptoBot, доп. инструкции персоне, само-улучшение (ИИ предлагает новые фичи промптом "
    "для Клода), премиум-эмодзи на любой текст бота (welcome/ai_reply/hub/support/image/"
    "telegraph/reminder/poll/translate/notes/game/weather/style — и можно добавить свой ключ), "
    "премиум-эмодзи + цвет (Bot API 9.4: icon_custom_emoji_id/style) + свой текст на каждую "
    "пользовательскую кнопку.\n\n"
    "Технически: aiogram 3.20+, SQLite, OpenAI-совместимый чат-эндпоинт прокси imbek.fun, "
    "фоновые asyncio-таски для напоминаний, авто-проверки крипто-донатов и запланированных рассылок."
)

SELF_IMPROVE_SYSTEM_PROMPT = (
    "Ты — старший продуктовый и технический консультант для Telegram-бота 'Kewo AI'. Тебе дают "
    "полное описание того, что бот уже умеет. Твоя задача — предложить 5-8 КОНКРЕТНЫХ, НОВЫХ "
    "улучшений (не дублирующих уже существующее), которые сделают бота полезнее, интереснее или "
    "прибыльнее. Не предлагай общие фразы вроде 'улучшить UX' — только конкретные фичи с деталями "
    "реализации.\n\n"
    "Оформи результат как ГОТОВЫЙ ТЕХНИЧЕСКИЙ ПРОМПТ, который владелец бота может скопировать и "
    "прямо отправить в чат с Claude (AI-ассистентом для написания кода), чтобы Claude сразу начал "
    "реализацию. Промпт должен: перечислять фичи по пунктам, для каждой — краткое техническое "
    "описание (какие хендлеры/таблицы/API нужны), быть на русском языке, без markdown-звёздочек "
    "и заголовков (#), общий объём — не больше 350 слов."
)

# ======================================================================
# БАЗА ДАННЫХ
# ======================================================================

class Database:
    def __init__(self, path: str, owner_id: int) -> None:
        self.path = path
        self._init_schema(owner_id)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self, owner_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    first_name TEXT,
                    username TEXT,
                    model TEXT NOT NULL DEFAULT '',
                    joined_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
                    messages_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS emoji (
                    key TEXT PRIMARY KEY,
                    emoji_id TEXT NOT NULL DEFAULT '',
                    fallback TEXT NOT NULL DEFAULT '⭐'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    remind_at INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    fired INTEGER NOT NULL DEFAULT 0,
                    repeat_rule TEXT NOT NULL DEFAULT ''
                )
                """
            )
            for ddl in ("ALTER TABLE reminders ADD COLUMN repeat_rule TEXT NOT NULL DEFAULT ''",):
                try:
                    conn.execute(ddl)
                except sqlite3.OperationalError:
                    pass
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS donations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    invoice_id TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'Общее',
                    created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
                )
                """
            )
            for ddl in ("ALTER TABLE notes ADD COLUMN category TEXT NOT NULL DEFAULT 'Общее'",):
                try:
                    conn.execute(ddl)
                except sqlite3.OperationalError:
                    pass
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS favorites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS badges (
                    user_id INTEGER NOT NULL,
                    badge_type TEXT NOT NULL,
                    granted_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
                    PRIMARY KEY (user_id, badge_type)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feature_usage (
                    user_id INTEGER NOT NULL,
                    feature TEXT NOT NULL,
                    PRIMARY KEY (user_id, feature)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    custom_style TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduled_broadcasts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    send_at INTEGER NOT NULL,
                    repeat_rule TEXT NOT NULL DEFAULT '',
                    fired INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
                )
                """
            )
            for key, (emoji_id, fallback) in DEFAULT_EMOJI.items():
                conn.execute(
                    "INSERT OR IGNORE INTO emoji (key, emoji_id, fallback) VALUES (?, ?, ?)",
                    (key, emoji_id, fallback),
                )
            defaults = {
                "owner_id": str(owner_id),
                "support_username": "",       # юзернейм поддержки, задаётся в админке
                "crypto_pay_token": "",       # ключ CryptoBot (Crypto Pay API)
                "image_model": "",            # модель для генерации картинок (если прокси поддерживает)
                "extra_instructions": "",     # доп. инструкции персоне, добавляются админом
            }
            for k, v in defaults.items():
                conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

    # -- users ------------------------------------------------------------
    def upsert_user(self, user_id: int, first_name: str, username: Optional[str]) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO users (user_id, first_name, username) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET first_name = excluded.first_name, "
                "username = excluded.username",
                (user_id, first_name, username or ""),
            )

    def bump_messages(self, user_id: int) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE users SET messages_count = messages_count + 1 WHERE user_id = ?", (user_id,))

    def get_user_model(self, user_id: int, default_model: str) -> str:
        with self.connect() as conn:
            row = conn.execute("SELECT model FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return (row["model"] if row and row["model"] else default_model)

    def set_user_model(self, user_id: int, model: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE users SET model = ? WHERE user_id = ?", (model, user_id))

    def users_count(self) -> int:
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]

    def total_messages(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COALESCE(SUM(messages_count), 0) c FROM users").fetchone()
        return row["c"]

    def users_joined_today(self) -> int:
        start_of_day = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        with self.connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) c FROM users WHERE joined_at >= ?", (start_of_day,)
            ).fetchone()["c"]

    def top_users(self, limit: int = 5) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM users ORDER BY messages_count DESC LIMIT ?", (limit,)
            ).fetchall()

    def list_users(self, limit: int = 20, offset: int = 0) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM users ORDER BY joined_at DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()

    def all_user_ids(self) -> list[int]:
        with self.connect() as conn:
            return [r["user_id"] for r in conn.execute("SELECT user_id FROM users").fetchall()]

    # -- settings -----------------------------------------------------------
    def get_setting(self, key: str, default: str = "") -> str:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # -- emoji / button icons ------------------------------------------------
    def get_emoji_full(self, key: str) -> Optional[tuple[str, str]]:
        with self.connect() as conn:
            row = conn.execute("SELECT emoji_id, fallback FROM emoji WHERE key = ?", (key,)).fetchone()
        return (row["emoji_id"], row["fallback"]) if row else None

    def set_emoji(self, key: str, emoji_id: str, fallback: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO emoji (key, emoji_id, fallback) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET emoji_id = excluded.emoji_id, fallback = excluded.fallback",
                (key, emoji_id, fallback),
            )

    def all_emoji_keys(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute("SELECT key, emoji_id, fallback FROM emoji ORDER BY key").fetchall()

    # -- reminders ------------------------------------------------------------
    def add_reminder(self, user_id: int, remind_at: int, text: str, repeat_rule: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO reminders (user_id, remind_at, text, repeat_rule) VALUES (?, ?, ?, ?)",
                (user_id, remind_at, text, repeat_rule),
            )

    def due_reminders(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM reminders WHERE fired = 0 AND remind_at <= ?", (int(time.time()),)
            ).fetchall()

    def mark_reminder_fired(self, reminder_id: int) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (reminder_id,))

    # -- donations --------------------------------------------------------
    def create_pending_donation(self, user_id: int, amount: str, provider: str, invoice_id: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO donations (user_id, amount, provider, invoice_id, status) VALUES (?, ?, ?, ?, 'pending')",
                (user_id, amount, provider, invoice_id),
            )

    def mark_donation_paid(self, invoice_id: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE donations SET status = 'paid' WHERE invoice_id = ?", (invoice_id,))

    def pending_crypto_donations(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM donations WHERE provider = 'crypto' AND status = 'pending'"
            ).fetchall()

    def get_pending_donation(self, invoice_id: str) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM donations WHERE invoice_id = ? AND provider = 'crypto'", (invoice_id,)
            ).fetchone()

    # -- notes (с категориями) -----------------------------------------------
    NOTE_CATEGORIES = ["Общее", "Работа", "Личное", "Идея"]

    def add_note(self, user_id: int, text: str, category: str = "Общее") -> None:
        with self.connect() as conn:
            conn.execute("INSERT INTO notes (user_id, text, category) VALUES (?, ?, ?)", (user_id, text, category))

    def list_notes(self, user_id: int, category: Optional[str] = None) -> list[sqlite3.Row]:
        with self.connect() as conn:
            if category and category != "Все":
                return conn.execute(
                    "SELECT * FROM notes WHERE user_id = ? AND category = ? ORDER BY created_at DESC",
                    (user_id, category),
                ).fetchall()
            return conn.execute(
                "SELECT * FROM notes WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
            ).fetchall()

    def delete_note(self, note_id: int, user_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM notes WHERE id = ? AND user_id = ?", (note_id, user_id))

    # -- избранное ------------------------------------------------------------
    def add_favorite(self, user_id: int, text: str) -> None:
        with self.connect() as conn:
            conn.execute("INSERT INTO favorites (user_id, text) VALUES (?, ?)", (user_id, text[:3500]))

    def list_favorites(self, user_id: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM favorites WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
            ).fetchall()

    def delete_favorite(self, fav_id: int, user_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM favorites WHERE id = ? AND user_id = ?", (fav_id, user_id))

    # -- бейджи и активность --------------------------------------------------
    BADGE_TITLES = {"newbie": "🌱 Новичок", "active": "🔥 Активист", "genius": "🧠 Гений"}

    def grant_badge(self, user_id: int, badge_type: str) -> bool:
        """Возвращает True, если бейдж выдан впервые (для уведомления)."""
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM badges WHERE user_id = ? AND badge_type = ?", (user_id, badge_type)
            ).fetchone()
            if existing:
                return False
            conn.execute("INSERT INTO badges (user_id, badge_type) VALUES (?, ?)", (user_id, badge_type))
            return True

    def list_badges(self, user_id: int) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT badge_type FROM badges WHERE user_id = ?", (user_id,)).fetchall()
        return [r["badge_type"] for r in rows]

    def mark_feature_used(self, user_id: int, feature: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO feature_usage (user_id, feature) VALUES (?, ?)", (user_id, feature)
            )

    def count_features_used(self, user_id: int) -> int:
        with self.connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) c FROM feature_usage WHERE user_id = ?", (user_id,)
            ).fetchone()["c"]

    # -- пользовательские настройки (свой стиль ответа) ------------------
    def get_custom_style(self, user_id: int) -> str:
        with self.connect() as conn:
            row = conn.execute("SELECT custom_style FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
        return row["custom_style"] if row else ""

    def set_custom_style(self, user_id: int, style: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO user_settings (user_id, custom_style) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET custom_style = excluded.custom_style",
                (user_id, style),
            )

    # -- запланированные (авто) рассылки --------------------------------
    def add_scheduled_broadcast(self, text: str, send_at: int, repeat_rule: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO scheduled_broadcasts (text, send_at, repeat_rule) VALUES (?, ?, ?)",
                (text, send_at, repeat_rule),
            )

    def due_broadcasts(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM scheduled_broadcasts WHERE fired = 0 AND send_at <= ?", (int(time.time()),)
            ).fetchall()

    def mark_broadcast_fired(self, broadcast_id: int) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE scheduled_broadcasts SET fired = 1 WHERE id = ?", (broadcast_id,))

    def reschedule_broadcast(self, broadcast_id: int, new_send_at: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE scheduled_broadcasts SET send_at = ?, fired = 0 WHERE id = ?",
                (new_send_at, broadcast_id),
            )

    def list_scheduled_broadcasts(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM scheduled_broadcasts WHERE fired = 0 ORDER BY send_at ASC"
            ).fetchall()

    def delete_scheduled_broadcast(self, broadcast_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM scheduled_broadcasts WHERE id = ?", (broadcast_id,))

    def reschedule_reminder(self, reminder_id: int, new_remind_at: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE reminders SET remind_at = ?, fired = 0 WHERE id = ?",
                (new_remind_at, reminder_id),
            )


def _is_owner(user_id: int, settings: Settings) -> bool:
    return user_id == settings.owner_id


# ======================================================================
# ПРЕМИУМ-ЭМОДЗИ И ИКОНКИ КНОПОК (Bot API 9.4)
# ======================================================================

_EMOJI_TAG_RE = re.compile(r"\{emoji:([\w:]+)\}")

DEFAULT_EMOJI: dict[str, tuple[str, str]] = {
    "ai_reply_icon": ("", ""),
    "hub_icon": ("", "🧭"),
    "support_icon": ("", "💛"),
    "welcome_icon": ("", "👋"),
    "image_icon": ("", "🎨"),
    "telegraph_icon": ("", "📰"),
    "reminder_icon": ("", "⏰"),
    "poll_icon": ("", "📊"),
    "translate_icon": ("", "🌍"),
    "notes_icon": ("", "🗒️"),
    "game_icon": ("", "🎲"),
}

# Понятные подписи для админки — но список НЕ ограничивает, что можно настроить:
# через "➕ Добавить свой" можно завести премиум-эмодзи на любой другой текст.
TEXT_EMOJI_LABELS: dict[str, str] = {
    "ai_reply_icon": "Иконка перед ответом ИИ",
    "hub_icon": "Иконка меню «Главное»",
    "support_icon": "Иконка «Помочь проекту»",
    "welcome_icon": "Иконка приветствия (/start)",
    "image_icon": "Иконка «Нарисовать»",
    "telegraph_icon": "Иконка статьи в Telegraph",
    "reminder_icon": "Иконка напоминаний",
    "poll_icon": "Иконка опросов",
    "translate_icon": "Иконка перевода",
    "notes_icon": "Иконка заметок",
    "game_icon": "Иконка мини-игры",
}

BUTTON_ICON_DEFAULTS: dict[str, tuple[str, str]] = {
    "btn_main": ("🏠", "«Главное» (нижнее меню)"),
    "btn_help_project": ("💛", "«Помочь проекту» (нижнее меню)"),
    "btn_hub_image": ("🎨", "«Нарисовать»"),
    "btn_hub_telegraph": ("📰", "«Статья в Telegraph»"),
    "btn_hub_reminder": ("⏰", "«Напоминание»"),
    "btn_hub_poll": ("📊", "«Опрос»"),
    "btn_hub_translate": ("🌍", "«Перевести текст»"),
    "btn_hub_weather": ("☁️", "«Погода»"),
    "btn_hub_style": ("✏️", "«Свой стиль ответа»"),
    "btn_hub_notes": ("🗒️", "«Заметки»"),
    "btn_hub_game": ("🎲", "«Мини-игра»"),
    "btn_note_add": ("➕", "«Добавить заметку»"),
    "btn_donate_pay": ("💳", "«Оплатить» (крипто-донат)"),
    "btn_donate_check": ("🔄", "«Проверить оплату»"),
    "btn_donate_custom": ("✏️", "«Своя сумма» (Stars)"),
    "btn_support_human": ("👤", "«Написать в поддержку»"),
    "btn_support_crypto": ("💎", "«Поддержать криптой»"),
    "btn_support_stars": ("⭐", "«Поддержать Stars»"),
    "btn_save_code": ("💾", "«Скачать код файлом»"),
    "btn_favorite": ("⭐", "«В избранное»"),
}


def render_emoji_tags(db: Database, text: str) -> str:
    def _sub(m: "re.Match[str]") -> str:
        key = m.group(1)
        full = db.get_emoji_full(key)
        if full and full[0]:
            emoji_id, fallback = full
            return f'<tg-emoji emoji-id="{html.escape(emoji_id)}">{html.escape(fallback)}</tg-emoji>'
        return html.escape(full[1] if full else DEFAULT_EMOJI.get(key, ("", "⭐"))[1])
    return _EMOJI_TAG_RE.sub(_sub, text)


def get_button_visual(db: Database, key: str) -> tuple[str, dict]:
    default_icon, _ = BUTTON_ICON_DEFAULTS.get(key, ("", ""))
    full = db.get_emoji_full(f"btn:{key}")
    kwargs: dict = {}
    if full and full[0]:
        kwargs["icon_custom_emoji_id"] = full[0]
        prefix = ""
    else:
        fallback = full[1] if full and full[1] else default_icon
        prefix = f"{fallback} " if fallback else ""
    style = db.get_setting(f"btnstyle:{key}", "")
    if style in ("primary", "success", "danger"):
        kwargs["style"] = style
    return prefix, kwargs


def mk_ikb(db: Database, key: str, label: str, **extra) -> InlineKeyboardButton:
    prefix, kwargs = get_button_visual(db, key)
    custom = db.get_setting(f"btntext:{key}", "")
    return InlineKeyboardButton(text=f"{prefix}{custom or label}", **kwargs, **extra)


def mk_kb(db: Database, key: str, label: str) -> KeyboardButton:
    prefix, kwargs = get_button_visual(db, key)
    custom = db.get_setting(f"btntext:{key}", "")
    return KeyboardButton(text=f"{prefix}{custom or label}", **kwargs)


# ======================================================================
# ИИ: ЧАТ-ЗАПРОСЫ И ФОРМАТИРОВАНИЕ
# ======================================================================

async def ai_chat(settings: Settings, model: str, system_prompt: str, user_text: str,
                   max_tokens: int = 1400, timeout_seconds: int = 40) -> Optional[str]:
    try:
        headers = {"Authorization": f"Bearer {settings.ai_api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "max_tokens": max_tokens,
        }
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(f"{settings.ai_base_url}/chat/completions", headers=headers, json=payload) as resp:
                data = await resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception:
        logger.exception("ai_chat failed (model=%s)", model)
        return None


async def _action_ping(bot: Bot, chat_id: int, action: str) -> None:
    try:
        while True:
            await bot.send_chat_action(chat_id, action)
            await asyncio.sleep(4)  # статус Telegram сам гаснет через ~5 сек — обновляем чуть чаще
    except asyncio.CancelledError:
        pass


async def with_action(bot: Bot, chat_id: int, action: str, coro):
    """Показывает нативный статус Telegram ('печатает...', 'отправляет фото...' и
    т.п.) всё время, пока выполняется coro, вместо статичного текста "Думаю..."."""
    ping_task = asyncio.create_task(_action_ping(bot, chat_id, action))
    try:
        return await coro
    finally:
        ping_task.cancel()


_CODE_BLOCK_RE = re.compile(r"```(\w*)\n?(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_BOLD2_RE = re.compile(r"__(.+?)__")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_ITALIC2_RE = re.compile(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)")
_HEADER_RE = re.compile(r"^#{1,6}\s*(.+)$", re.MULTILINE)
_BULLET_RE = re.compile(r"^[\-\*]\s+", re.MULTILINE)

LANG_EXT = {
    "python": "py", "py": "py", "javascript": "js", "js": "js", "typescript": "ts",
    "html": "html", "css": "css", "cpp": "cpp", "c++": "cpp", "c": "c", "sql": "sql",
    "json": "json", "bash": "sh", "sh": "sh", "yaml": "yml", "java": "java", "go": "go",
}


def markdown_to_html(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Конвертирует markdown-ответ ИИ в Telegram HTML (никаких сырых * наружу),
    возвращает (html_текст, список_блоков_кода [(lang, code), ...])."""
    code_blocks: list[tuple[str, str]] = []

    def _stash_block(m: "re.Match[str]") -> str:
        code_blocks.append((m.group(1) or "txt", m.group(2).strip()))
        return f"\x00BLOCK{len(code_blocks) - 1}\x00"

    text = _CODE_BLOCK_RE.sub(_stash_block, text)

    inline: list[str] = []

    def _stash_inline(m: "re.Match[str]") -> str:
        inline.append(m.group(1))
        return f"\x00INLINE{len(inline) - 1}\x00"

    text = _INLINE_CODE_RE.sub(_stash_inline, text)
    text = html.escape(text)
    text = _BOLD_RE.sub(r"<b>\1</b>", text)
    text = _BOLD2_RE.sub(r"<b>\1</b>", text)
    text = _ITALIC_RE.sub(r"<i>\1</i>", text)
    text = _ITALIC2_RE.sub(r"<i>\1</i>", text)
    text = _HEADER_RE.sub(r"<b>\1</b>", text)
    text = _BULLET_RE.sub("• ", text)

    for i, code in enumerate(inline):
        text = text.replace(f"\x00INLINE{i}\x00", f"<code>{html.escape(code)}</code>")
    for i, (lang, code) in enumerate(code_blocks):
        block_html = f"<pre><code>{html.escape(code)}</code></pre>"
        text = text.replace(f"\x00BLOCK{i}\x00", block_html)

    return text.strip(), code_blocks


# кэш последних сгенерированных блоков кода на пользователя — для кнопки "скачать файлом"
LAST_CODE_CACHE: dict[int, list[tuple[str, str]]] = {}
LAST_AI_TEXT_CACHE: dict[int, str] = {}


def build_ai_reply_keyboard(db: Database, user_id: int, blocks: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    rows = []
    for i, (lang, _) in enumerate(blocks):
        label = f"Скачать код ({lang})" if len(blocks) > 1 else "Скачать код файлом"
        rows.append([mk_ikb(db, "btn_save_code", label, callback_data=f"savefile:{user_id}:{i}")])
    rows.append([mk_ikb(db, "btn_favorite", "В избранное", callback_data="fav_add")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ======================================================================
# TELEGRAPH (статьи)
# ======================================================================

TELEGRAPH_API = "https://api.telegra.ph"


async def telegraph_ensure_token(db: Database) -> Optional[str]:
    token = db.get_setting("telegraph_token", "")
    if token:
        return token
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.post(f"{TELEGRAPH_API}/createAccount", json={
                "short_name": "KewoAI", "author_name": "Kewo AI",
            }) as resp:
                data = await resp.json()
        token = data["result"]["access_token"]
        db.set_setting("telegraph_token", token)
        return token
    except Exception:
        logger.exception("telegraph_ensure_token failed")
        return None


def _text_to_telegraph_nodes(text: str) -> list:
    nodes: list = []
    bullets: list[str] = []

    def flush() -> None:
        if bullets:
            nodes.append({"tag": "ul", "children": [{"tag": "li", "children": [b]} for b in bullets]})
            bullets.clear()

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if line.startswith("## "):
            flush()
            nodes.append({"tag": "h4", "children": [line[3:].strip()]})
        elif line.startswith("# "):
            flush()
            nodes.append({"tag": "h3", "children": [line[2:].strip()]})
        elif line.startswith(("- ", "* ")):
            bullets.append(line[2:].strip())
        else:
            flush()
            nodes.append({"tag": "p", "children": [line]})
    flush()
    return nodes or [{"tag": "p", "children": [text]}]


async def telegraph_create_page(db: Database, title: str, body_text: str) -> Optional[str]:
    token = await telegraph_ensure_token(db)
    if not token:
        return None
    nodes = _text_to_telegraph_nodes(body_text)
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.post(f"{TELEGRAPH_API}/createPage", json={
                "access_token": token, "title": title[:250] or "Статья", "author_name": "Kewo AI",
                "content": json.dumps(nodes), "return_content": False,
            }) as resp:
                data = await resp.json()
        return data["result"]["url"]
    except Exception:
        logger.exception("telegraph_create_page failed")
        return None


# ======================================================================
# ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЙ
# ======================================================================

WMO_WEATHER_DESCRIPTIONS = {
    0: ("☀️", "ясно"), 1: ("🌤", "малооблачно"), 2: ("⛅", "переменная облачность"),
    3: ("☁️", "пасмурно"), 45: ("🌫", "туман"), 48: ("🌫", "изморозь"),
    51: ("🌦", "морось слабая"), 53: ("🌦", "морось"), 55: ("🌧", "морось сильная"),
    61: ("🌧", "дождь слабый"), 63: ("🌧", "дождь"), 65: ("🌧", "дождь сильный"),
    71: ("🌨", "снег слабый"), 73: ("🌨", "снег"), 75: ("❄️", "снег сильный"),
    80: ("🌦", "ливень слабый"), 81: ("🌧", "ливень"), 82: ("⛈", "ливень сильный"),
    95: ("⛈", "гроза"), 96: ("⛈", "гроза с градом"), 99: ("⛈", "сильная гроза с градом"),
}


async def fetch_weather(city: str) -> Optional[str]:
    """Погода через Open-Meteo — бесплатный публичный API, ключ не нужен."""
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1, "language": "ru"},
            ) as resp:
                geo = await resp.json()
            results = geo.get("results") or []
            if not results:
                return None
            place = results[0]
            lat, lon = place["latitude"], place["longitude"]
            place_name = place.get("name", city)
            async with session.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat, "longitude": lon,
                    "current": "temperature_2m,weather_code,wind_speed_10m",
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min",
                    "timezone": "auto", "forecast_days": 3,
                },
            ) as resp:
                data = await resp.json()
        current = data["current"]
        icon, desc = WMO_WEATHER_DESCRIPTIONS.get(current["weather_code"], ("🌡", "неизвестно"))
        lines = [
            f"{icon} <b>{html.escape(place_name)}</b>: {current['temperature_2m']}°C, {desc}, "
            f"ветер {current['wind_speed_10m']} км/ч\n",
            "Прогноз на 3 дня:",
        ]
        daily = data["daily"]
        for i in range(min(3, len(daily["time"]))):
            d_icon, d_desc = WMO_WEATHER_DESCRIPTIONS.get(daily["weather_code"][i], ("🌡", ""))
            lines.append(
                f"{daily['time'][i]}: {d_icon} {daily['temperature_2m_min'][i]}…{daily['temperature_2m_max'][i]}°C, {d_desc}"
            )
        return "\n".join(lines)
    except Exception:
        logger.exception("fetch_weather failed")
        return None


async def generate_image(settings: Settings, model: str, prompt: str) -> Optional[str]:
    """Best-effort: предполагает OpenAI-совместимый эндпоинт /images/generations
    на твоём прокси. Если прокси называет модель/эндпоинт иначе — уточни у
    провайдера и поправь эту функцию."""
    try:
        headers = {"Authorization": f"Bearer {settings.ai_api_key}", "Content-Type": "application/json"}
        payload = {"model": model, "prompt": prompt, "n": 1, "size": "1024x1024"}
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(f"{settings.ai_base_url}/images/generations", headers=headers, json=payload) as resp:
                data = await resp.json()
        return data["data"][0]["url"]
    except Exception:
        logger.exception("generate_image failed")
        return None


# ======================================================================
# CRYPTOBOT (донаты)
# ======================================================================

CRYPTO_PAY_BASE_URL = "https://pay.crypt.bot/api"
DONATION_CURRENCIES = ["USDT", "TON", "BTC"]


async def cryptobot_create_invoice(token: str, amount_usd: float, description: str, payload: str,
                                    asset: str = "USDT") -> Optional[dict]:
    try:
        headers = {"Crypto-Pay-API-Token": token, "Content-Type": "application/json"}
        body = {
            "currency_type": "fiat", "fiat": "USD", "amount": f"{amount_usd:.2f}",
            "accepted_assets": asset, "description": description, "payload": payload,
            "expires_in": 3600,
        }
        async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.post(f"{CRYPTO_PAY_BASE_URL}/createInvoice", json=body) as resp:
                data = await resp.json()
        if not data.get("ok"):
            return None
        result = data["result"]
        return {"invoice_id": str(result["invoice_id"]), "pay_url": result.get("bot_invoice_url") or result.get("pay_url")}
    except Exception:
        logger.exception("cryptobot_create_invoice failed")
        return None


async def cryptobot_check_invoice(token: str, invoice_id: str) -> Optional[str]:
    try:
        headers = {"Crypto-Pay-API-Token": token}
        async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.get(f"{CRYPTO_PAY_BASE_URL}/getInvoices", params={"invoice_ids": invoice_id}) as resp:
                data = await resp.json()
        if not data.get("ok"):
            return None
        items = data["result"]["items"]
        return items[0]["status"] if items else None
    except Exception:
        logger.exception("cryptobot_check_invoice failed")
        return None


# ======================================================================
# КЛАВИАТУРЫ
# ======================================================================

def build_main_reply_keyboard(db: Database) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[mk_kb(db, "btn_main", "Главное"), mk_kb(db, "btn_help_project", "Помочь проекту")]],
        resize_keyboard=True,
    )


def build_hub_keyboard(db: Database) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [mk_ikb(db, "btn_hub_image", "Нарисовать", callback_data="hub_image")],
        [mk_ikb(db, "btn_hub_telegraph", "Статья в Telegraph", callback_data="hub_telegraph")],
        [mk_ikb(db, "btn_hub_reminder", "Напоминание", callback_data="hub_reminder")],
        [mk_ikb(db, "btn_hub_poll", "Опрос", callback_data="hub_poll")],
        [mk_ikb(db, "btn_hub_translate", "Перевести текст", callback_data="hub_translate")],
        [mk_ikb(db, "btn_hub_notes", "Заметки", callback_data="hub_notes")],
        [mk_ikb(db, "btn_hub_game", "Мини-игра", callback_data="hub_game")],
        [mk_ikb(db, "btn_hub_weather", "Погода", callback_data="hub_weather")],
        [mk_ikb(db, "btn_hub_style", "Свой стиль ответа", callback_data="hub_style")],
    ])



def build_model_keyboard(db: Database, current: str) -> InlineKeyboardMarkup:
    rows = []
    for key, label in AVAILABLE_MODELS:
        mark = "✅ " if key == current else ""
        rows.append([InlineKeyboardButton(text=f"{mark}{label}", callback_data=f"admin_setmodel:{key}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_support_keyboard(db: Database) -> InlineKeyboardMarkup:
    rows = []
    support_username = db.get_setting("support_username", "")
    if support_username:
        rows.append([mk_ikb(db, "btn_support_human", "Написать в поддержку",
                             url=f"https://t.me/{support_username.lstrip('@')}")])
    if db.get_setting("crypto_pay_token", ""):
        rows.append([mk_ikb(db, "btn_support_crypto", "Поддержать криптой", callback_data="support_crypto")])
    rows.append([mk_ikb(db, "btn_support_stars", "Поддержать Stars", callback_data="support_stars")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_currency_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=cur, callback_data=f"donate_cur:{cur}")] for cur in DONATION_CURRENCIES
    ])


def build_stars_amount_keyboard(db: Database) -> InlineKeyboardMarkup:
    presets = [50, 100, 250, 500]
    rows = [[InlineKeyboardButton(text=f"⭐ {p}", callback_data=f"donate_stars:{p}")] for p in presets]
    rows.append([mk_ikb(db, "btn_donate_custom", "Своя сумма", callback_data="donate_stars_custom")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ======================================================================
# СОСТОЯНИЯ (FSM)
# ======================================================================

class UserStates(StatesGroup):
    waiting_image_prompt = State()
    waiting_telegraph_topic = State()
    waiting_reminder_text = State()
    waiting_poll_question = State()
    waiting_poll_options = State()
    waiting_donation_crypto_amount = State()
    waiting_donation_stars_custom = State()
    waiting_translate_text = State()
    waiting_note_text = State()
    waiting_note_category = State()
    waiting_weather_city = State()
    waiting_custom_style = State()


class AdminStates(StatesGroup):
    waiting_broadcast_text = State()
    waiting_support_username = State()
    waiting_crypto_token = State()
    waiting_image_model = State()
    waiting_extra_instructions = State()
    waiting_new_emoji_key = State()
    waiting_emoji_forward = State()
    waiting_button_icon = State()
    waiting_schedule_broadcast_text = State()
    waiting_schedule_broadcast_time = State()


# ======================================================================
# НАПОМИНАНИЯ: разбор времени из текста
# ======================================================================

_REL_TIME_RE = re.compile(
    r"через\s+(\d+)\s*(минут(?:у|ы)?|мин|час(?:а|ов)?|дн(?:я|ей)|день)", re.IGNORECASE
)
_ABS_TIME_RE = re.compile(r"\bв\s+(\d{1,2}):(\d{2})\b")
_REPEAT_DAILY_RE = re.compile(r"кажд(?:ый|ое)\s+день|ежедневно", re.IGNORECASE)
_REPEAT_WEEKDAY_RE = re.compile(
    r"кажд(?:ый|ую|ое)\s+(понедельник|вторник|сред[ауы]|четверг|пятниц[ауы]|суббот[ауы]|воскресень[еяю])",
    re.IGNORECASE,
)
_REPEAT_MONTHLY_RE = re.compile(r"кажд(?:ое)\s+(\d{1,2})[-\s]*(?:е|го)?\s+числ", re.IGNORECASE)

_WEEKDAY_STEMS = {
    "понедельник": 0, "вторник": 1, "сред": 2, "четверг": 3,
    "пятниц": 4, "суббот": 5, "воскресень": 6,
}


def _weekday_from_word(word: str) -> int:
    word = word.lower()
    for stem, idx in _WEEKDAY_STEMS.items():
        if word.startswith(stem):
            return idx
    return 0


def _next_monthly_occurrence(now: datetime, day_of_month: int, hour: int, minute: int) -> datetime:
    day_of_month = max(1, min(day_of_month, 31))
    year, month = now.year, now.month
    for _ in range(14):  # достаточно, чтобы точно найти ближайшую подходящую дату
        last_day = calendar.monthrange(year, month)[1]
        day = min(day_of_month, last_day)
        candidate = datetime(year, month, day, hour, minute)
        if candidate > now:
            return candidate
        month += 1
        if month > 12:
            month = 1
            year += 1
    return now + timedelta(days=30)  # запасной вариант, не должен случаться


def parse_reminder(text: str) -> Optional[tuple[int, str, str]]:
    """Возвращает (unix_timestamp, оставшийся_текст, repeat_rule) или None, если
    не смог распознать время. repeat_rule: '' (разово), 'daily', 'weekly:0-6'
    (0=понедельник), 'monthly:1-31'."""
    time_m = _ABS_TIME_RE.search(text)
    daily_m = _REPEAT_DAILY_RE.search(text)
    weekday_m = _REPEAT_WEEKDAY_RE.search(text) if not daily_m else None
    monthly_m = _REPEAT_MONTHLY_RE.search(text) if not daily_m and not weekday_m else None

    # Повторяющиеся напоминания требуют явного времени ("в ЧЧ:ММ"), иначе непонятно,
    # когда именно повторять — в этом случае просто не распознаём повтор.
    if time_m and (daily_m or weekday_m or monthly_m):
        hour, minute = int(time_m.group(1)), int(time_m.group(2))
        now = datetime.now()
        if daily_m:
            repeat_rule = "daily"
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
        elif weekday_m:
            wd = _weekday_from_word(weekday_m.group(1))
            repeat_rule = f"weekly:{wd}"
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            days_ahead = (wd - target.weekday()) % 7
            if days_ahead == 0 and target <= now:
                days_ahead = 7
            target += timedelta(days=days_ahead)
        else:
            day_of_month = int(monthly_m.group(1))
            repeat_rule = f"monthly:{day_of_month}"
            target = _next_monthly_occurrence(now, day_of_month, hour, minute)
        rest = text
        for m in (daily_m, weekday_m, monthly_m, time_m):
            if m:
                rest = rest.replace(m.group(0), "")
        rest = re.sub(r"\s{2,}", " ", rest).strip(" ,.-—")
        return int(target.timestamp()), (rest or "напоминание"), repeat_rule

    m = _REL_TIME_RE.search(text)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        seconds = n * (60 if unit.startswith(("мин",)) else 3600 if unit.startswith("час") else 86400)
        remind_at = int(time.time()) + seconds
        rest = (text[:m.start()] + text[m.end():]).strip(" ,.-—")
        return remind_at, (rest or "напоминание"), ""
    if time_m:
        hour, minute = int(time_m.group(1)), int(time_m.group(2))
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)  # было: сломанная логика с day+1 без учёта конца месяца
        rest = (text[:time_m.start()] + text[time_m.end():]).strip(" ,.-—")
        return int(target.timestamp()), (rest or "напоминание"), ""
    return None


def next_occurrence_after(repeat_rule: str, prev_ts: int) -> int:
    """Считает следующий момент срабатывания повторяющегося напоминания/рассылки,
    сохраняя тот же час:минуту, что были у предыдущего срабатывания."""
    prev = datetime.fromtimestamp(prev_ts)
    hour, minute = prev.hour, prev.minute
    now = datetime.now()
    base = max(prev, now)
    if repeat_rule == "daily":
        target = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return int(target.timestamp())
    if repeat_rule.startswith("weekly:"):
        wd = int(repeat_rule.split(":", 1)[1])
        target = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        days_ahead = (wd - target.weekday()) % 7
        if days_ahead == 0 and target <= now:
            days_ahead = 7
        target += timedelta(days=days_ahead if days_ahead else 7)
        return int(target.timestamp())
    if repeat_rule.startswith("monthly:"):
        day_of_month = int(repeat_rule.split(":", 1)[1])
        return int(_next_monthly_occurrence(now, day_of_month, hour, minute).timestamp())
    return int(now.timestamp()) + 86400  # неизвестное правило — подстраховка, не должно случаться


# ======================================================================
# ХЕНДЛЕРЫ
# ======================================================================

def register_handlers(dp: Dispatcher, db: Database, settings: Settings) -> None:
    _bot_username_cache: dict[str, str] = {}

    async def _mark_used(target, user_id: int, feature: str) -> None:
        """Отмечает использование фичи и, если это довело до 5 разных фич,
        выдаёт бейдж 'Гений' с уведомлением. target — что угодно с .answer()
        (Message или callback.message); user_id передаём явно, потому что у
        callback.message.from_user всегда бот, а не нажавший юзер."""
        db.mark_feature_used(user_id, feature)
        if db.count_features_used(user_id) >= 5:
            if db.grant_badge(user_id, "genius"):
                await target.answer(f"🎉 Новый бейдж: {Database.BADGE_TITLES['genius']} — попробовал(а) 5+ разных функций бота!")

    async def _check_message_badges(message: Message) -> None:
        """Бейджи за количество сообщений: новичок (10), активист (100)."""
        with db.connect() as conn:
            row = conn.execute(
                "SELECT messages_count FROM users WHERE user_id = ?", (message.from_user.id,)
            ).fetchone()
        count = row["messages_count"] if row else 0
        if count >= 10 and db.grant_badge(message.from_user.id, "newbie"):
            await message.answer(f"🎉 Новый бейдж: {Database.BADGE_TITLES['newbie']} — 10 сообщений боту!")
        if count >= 100 and db.grant_badge(message.from_user.id, "active"):
            await message.answer(f"🎉 Новый бейдж: {Database.BADGE_TITLES['active']} — 100 сообщений боту, это серьёзно!")

    async def ai_reply(message: Message, model: str, prompt: str) -> None:
        extra = db.get_setting("extra_instructions", "")
        savage = db.get_setting("savage_mode", "1") == "1"
        custom_style = db.get_custom_style(message.from_user.id)
        system_prompt = (
            DEV_AI_PERSONA
            + (SAVAGE_ADDENDUM if savage else "")
            + (f"\n\nДополнительно от создателя: {extra}" if extra else "")
            + (f"\n\nЛичное пожелание этого пользователя к стилю ответа: {custom_style}" if custom_style else "")
        )
        raw = await with_action(message.bot, message.chat.id, "typing", ai_chat(settings, model, system_prompt, prompt))
        if raw is None:
            await message.answer("⚠️ Не получилось получить ответ от модели, попробуй ещё раз чуть позже.")
            return
        body_html, code_blocks = markdown_to_html(raw)
        icon = render_emoji_tags(db, "{emoji:ai_reply_icon}")
        text = f"{icon} {body_html}" if icon else body_html
        user_id = message.from_user.id
        LAST_CODE_CACHE[user_id] = code_blocks
        LAST_AI_TEXT_CACHE[user_id] = raw
        markup = build_ai_reply_keyboard(db, user_id, code_blocks)
        await message.answer(text, parse_mode="HTML", reply_markup=markup)
        await _check_message_badges(message)

    # -- /start -------------------------------------------------------------
    @dp.message(Command("start"))
    async def handle_start(message: Message) -> None:
        db.upsert_user(message.from_user.id, message.from_user.first_name or "", message.from_user.username)
        name = message.from_user.first_name or "друг"
        await message.answer(
            render_emoji_tags(db, (
                f"{{emoji:welcome_icon}} Привет, {html.escape(name)}! Я <b>Kewo AI</b> — "
                "меня создал @deverskyi на собственном железе.\n\n"
                "Пиши что угодно: помогу с кодом, идеями, текстом — без воды и лишних предисловий.\n\n"
                "Жми «🏠 Главное» внизу — там всё остальное: рисование, статьи в Telegraph, "
                "напоминания, опросы, перевод, заметки и мини-игры."
            )),
            parse_mode="HTML", reply_markup=build_main_reply_keyboard(db),
        )

    # -- /support (он же /помощь) -------------------------------------------
    @dp.message(Command("support"))
    async def handle_support_cmd(message: Message) -> None:
        await message.answer(
            render_emoji_tags(db, (
                "{emoji:support_icon} Если проект зашёл — можешь поддержать его развитие, или "
                "написать в поддержку, если что-то не работает."
            )),
            parse_mode="HTML", reply_markup=build_support_keyboard(db),
        )

    def _matches_btn(key: str, default_label: str):
        def _check(message: Message) -> bool:
            text = message.text or ""
            custom = db.get_setting(f"btntext:{key}", "")
            label = custom if custom else default_label
            return text.endswith(label)
        return _check

    @dp.message(_matches_btn("btn_main", "Главное"))
    async def handle_main_btn(message: Message) -> None:
        icon = render_emoji_tags(db, "{emoji:hub_icon}")
        await message.answer(f"{icon} Что делаем?", parse_mode="HTML", reply_markup=build_hub_keyboard(db))

    @dp.message(_matches_btn("btn_help_project", "Помочь проекту"))
    async def handle_help_project_btn(message: Message) -> None:
        await handle_support_cmd(message)

    # (Выбор модели теперь только в админ-панели — обычные пользователи модели не видят.)


    # -- Hub: рисование -------------------------------------------------------
    @dp.callback_query(F.data == "hub_image")
    async def handle_hub_image(callback: CallbackQuery, state: FSMContext) -> None:
        await state.set_state(UserStates.waiting_image_prompt)
        await callback.message.answer(render_emoji_tags(db, "{emoji:image_icon} Опиши, что нарисовать:"), parse_mode="HTML")
        await callback.answer()

    @dp.message(UserStates.waiting_image_prompt)
    async def handle_image_prompt(message: Message, state: FSMContext) -> None:
        await state.clear()
        image_model = db.get_setting("image_model", "")
        if not image_model:
            await message.answer(
                "⚠️ Генерация изображений пока не настроена — админ должен указать модель "
                "для картинок в админ-панели."
            )
            return
        url = await with_action(
            message.bot, message.chat.id, "upload_photo",
            generate_image(settings, image_model, message.text or ""),
        )
        if not url:
            await message.answer("⚠️ Не получилось сгенерировать изображение. Попробуй другой запрос.")
            return
        try:
            await message.answer_photo(url)
        except Exception:
            await message.answer(f"Готово: {url}")
        await _mark_used(message, message.from_user.id, "image")

    # -- Hub: статья в Telegraph ------------------------------------------
    @dp.callback_query(F.data == "hub_telegraph")
    async def handle_hub_telegraph(callback: CallbackQuery, state: FSMContext) -> None:
        await state.set_state(UserStates.waiting_telegraph_topic)
        await callback.message.answer(render_emoji_tags(db, "{emoji:telegraph_icon} На какую тему написать статью?"), parse_mode="HTML")
        await callback.answer()

    @dp.message(UserStates.waiting_telegraph_topic)
    async def handle_telegraph_topic(message: Message, state: FSMContext) -> None:
        await state.clear()
        topic = message.text or ""
        model = db.get_setting("default_model", settings.default_model)
        article = await with_action(message.bot, message.chat.id, "typing", ai_chat(
            settings, model,
            "Ты пишешь развёрнутую, но по делу статью для Telegraph на русском. "
            "Структурируй текст короткими абзацами, используй '## ' для подзаголовков "
            "и '- ' для списков. Без markdown-звёздочек, без markdown-заголовков #.",
            f"Напиши статью на тему: {topic}",
            max_tokens=2000,
        ))
        if not article:
            await message.answer("⚠️ Не получилось написать статью, попробуй ещё раз.")
            return
        url = await telegraph_create_page(db, topic[:80] or "Статья", article)
        if not url:
            await message.answer("⚠️ Не получилось опубликовать в Telegraph, попробуй позже.")
            return
        await message.answer(f"✅ Готово: {url}")
        await _mark_used(message, message.from_user.id, "telegraph")
    @dp.callback_query(F.data == "hub_reminder")
    async def handle_hub_reminder(callback: CallbackQuery, state: FSMContext) -> None:
        await state.set_state(UserStates.waiting_reminder_text)
        await callback.message.answer(
            render_emoji_tags(db, (
                "{emoji:reminder_icon} Напиши, о чём и когда напомнить. Понимаю форматы:\n"
                "«через 20 минут выпить воды», «через 2 часа звонок», «в 18:30 тренировка»,\n"
                "а также повторяющиеся: «каждый день в 9:00 зарядка», «каждый понедельник в "
                "10:00 планёрка», «каждое 1 число в 12:00 оплатить подписку»."
            )), parse_mode="HTML",
        )
        await callback.answer()

    @dp.message(UserStates.waiting_reminder_text)
    async def handle_reminder_text(message: Message, state: FSMContext) -> None:
        await state.clear()
        parsed = parse_reminder(message.text or "")
        if not parsed:
            await message.answer(
                "Не понял время. Используй «через N минут/часов/дней ...», «в ЧЧ:ММ ...» "
                "или «каждый день/каждый понедельник/каждое N число в ЧЧ:ММ ...»."
            )
            return
        remind_at, text, repeat_rule = parsed
        db.add_reminder(message.from_user.id, remind_at, text, repeat_rule)
        when = datetime.fromtimestamp(remind_at).strftime("%d.%m %H:%M")
        repeat_note = {
            "daily": " (повтор: каждый день)",
        }.get(repeat_rule, " (повтор: каждую неделю)" if repeat_rule.startswith("weekly:") else
              (" (повтор: каждый месяц)" if repeat_rule.startswith("monthly:") else ""))
        await message.answer(f"✅ Напомню «{text}» — {when}{repeat_note}.")
        await _mark_used(message, message.from_user.id, "reminder")

    # -- Hub: опросы ----------------------------------------------------------
    @dp.callback_query(F.data == "hub_poll")
    async def handle_hub_poll(callback: CallbackQuery, state: FSMContext) -> None:
        await state.set_state(UserStates.waiting_poll_question)
        await callback.message.answer(render_emoji_tags(db, "{emoji:poll_icon} Напиши вопрос для опроса:"), parse_mode="HTML")
        await callback.answer()

    @dp.message(UserStates.waiting_poll_question)
    async def handle_poll_question(message: Message, state: FSMContext) -> None:
        await state.update_data(poll_question=message.text or "Опрос")
        await state.set_state(UserStates.waiting_poll_options)
        await message.answer("Теперь пришли варианты ответа — каждый с новой строки (минимум 2).")

    @dp.message(UserStates.waiting_poll_options)
    async def handle_poll_options(message: Message, state: FSMContext) -> None:
        question = (await state.get_data()).get("poll_question", "Опрос")
        options = [line.strip() for line in (message.text or "").split("\n") if line.strip()][:10]
        if len(options) < 2:
            await message.answer("Нужно минимум 2 варианта, каждый с новой строки. Попробуй ещё раз через «📊 Опрос».")
            return
        await state.update_data(poll_options=options)
        await message.answer(
            "Опрос анонимный или публичный (видно, кто как проголосовал)?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🙈 Анонимный", callback_data="poll_send:1")],
                [InlineKeyboardButton(text="👁 Публичный", callback_data="poll_send:0")],
            ]),
        )

    @dp.callback_query(F.data.startswith("poll_send:"))
    async def handle_poll_send(callback: CallbackQuery, state: FSMContext) -> None:
        is_anonymous = callback.data.split(":", 1)[1] == "1"
        data = await state.get_data()
        question = data.get("poll_question", "Опрос")
        options = data.get("poll_options", [])
        await state.clear()
        if len(options) < 2:
            await callback.answer("Что-то пошло не так, начни заново.", show_alert=True)
            return
        await callback.bot.send_poll(callback.message.chat.id, question=question, options=options, is_anonymous=is_anonymous)
        await _mark_used(callback.message, callback.from_user.id, "poll")
        await callback.answer()

    # -- Hub: перевод текста --------------------------------------------------
    @dp.callback_query(F.data == "hub_translate")
    async def handle_hub_translate(callback: CallbackQuery, state: FSMContext) -> None:
        await state.set_state(UserStates.waiting_translate_text)
        await callback.message.answer(
            render_emoji_tags(db, "{emoji:translate_icon} Пришли текст и укажи язык, на который перевести (например: «переведи на английский: привет, как дела»)."),
            parse_mode="HTML",
        )
        await callback.answer()

    @dp.message(UserStates.waiting_translate_text)
    async def handle_translate_text(message: Message, state: FSMContext) -> None:
        await state.clear()
        model = db.get_setting("default_model", settings.default_model)
        result = await with_action(message.bot, message.chat.id, "typing", ai_chat(
            settings, model,
            "Ты профессиональный переводчик. Определи, на какой язык нужно перевести (из запроса "
            "пользователя), и выведи ТОЛЬКО готовый перевод, без пояснений, без markdown-звёздочек.",
            message.text or "",
        ))
        if not result:
            await message.answer("⚠️ Не получилось перевести, попробуй ещё раз.")
            return
        await message.answer(result)
        await _mark_used(message, message.from_user.id, "translate")

    # -- Hub: погода (Open-Meteo, без ключа) -------------------------------
    @dp.callback_query(F.data == "hub_weather")
    async def handle_hub_weather(callback: CallbackQuery, state: FSMContext) -> None:
        await state.set_state(UserStates.waiting_weather_city)
        await callback.message.answer(
            render_emoji_tags(db, "{emoji:weather_icon} Какой город?"), parse_mode="HTML",
        )
        await callback.answer()

    @dp.message(UserStates.waiting_weather_city)
    async def handle_weather_city(message: Message, state: FSMContext) -> None:
        await state.clear()
        city = (message.text or "").strip()
        result = await with_action(message.bot, message.chat.id, "find_location", fetch_weather(city))
        if not result:
            await message.answer("⚠️ Не нашёл такой город или сервис погоды сейчас недоступен. Попробуй ещё раз.")
            return
        await message.answer(
            result, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔄 Обновить", callback_data=f"weather_refresh:{city[:50]}")
            ]]),
        )
        await _mark_used(message, message.from_user.id, "weather")

    @dp.callback_query(F.data.startswith("weather_refresh:"))
    async def handle_weather_refresh(callback: CallbackQuery) -> None:
        city = callback.data.split(":", 1)[1]
        result = await with_action(callback.bot, callback.message.chat.id, "find_location", fetch_weather(city))
        if not result:
            await callback.answer("Не получилось обновить.", show_alert=True)
            return
        try:
            await callback.message.edit_text(
                result, parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🔄 Обновить", callback_data=f"weather_refresh:{city}")
                ]]),
            )
        except TelegramBadRequest:
            pass
        await callback.answer("Обновлено")

    # -- Hub: свой стиль ответа -------------------------------------------
    @dp.callback_query(F.data == "hub_style")
    async def handle_hub_style(callback: CallbackQuery, state: FSMContext) -> None:
        current = db.get_custom_style(callback.from_user.id)
        note = f"\n\nТекущий: «{current}»" if current else ""
        await state.set_state(UserStates.waiting_custom_style)
        await callback.message.answer(
            "Опиши, как тебе удобнее, чтобы я отвечал (например: «отвечай короче», «объясняй "
            f"как для новичка», «используй больше эмодзи»). Пришли '-' чтобы сбросить.{note}"
        )
        await callback.answer()

    @dp.message(UserStates.waiting_custom_style)
    async def handle_custom_style_input(message: Message, state: FSMContext) -> None:
        await state.clear()
        val = (message.text or "").strip()
        db.set_custom_style(message.from_user.id, "" if val == "-" else val)
        await message.answer("✅ Стиль сброшен." if val == "-" else "✅ Стиль сохранён, буду отвечать с учётом этого.")
        await _mark_used(message, message.from_user.id, "style")

    # -- Hub: заметки (с категориями) ------------------------------------
    def build_notes_keyboard(user_id: int, category: Optional[str] = None) -> InlineKeyboardMarkup:
        notes = db.list_notes(user_id, category)
        rows = [[InlineKeyboardButton(text=f"🗑 [{n['category']}] {n['text'][:35]}", callback_data=f"note_del:{n['id']}")] for n in notes[:15]]
        cat_row = [
            InlineKeyboardButton(text=("✅ " if c == category else "") + c, callback_data=f"note_filter:{c}")
            for c in ["Все"] + Database.NOTE_CATEGORIES
        ]
        rows.append(cat_row[:2])
        rows.append(cat_row[2:4])
        rows.append(cat_row[4:])
        rows.append([mk_ikb(db, "btn_note_add", "Добавить заметку", callback_data="note_add")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @dp.callback_query(F.data == "hub_notes")
    async def handle_hub_notes(callback: CallbackQuery) -> None:
        notes = db.list_notes(callback.from_user.id)
        text = "\n".join(f"• [{n['category']}] {n['text']}" for n in notes) if notes else "Пока пусто."
        await callback.message.answer(
            render_emoji_tags(db, f"{{emoji:notes_icon}} <b>Твои заметки:</b>\n\n{html.escape(text)}"),
            parse_mode="HTML", reply_markup=build_notes_keyboard(callback.from_user.id),
        )
        await callback.answer()

    @dp.callback_query(F.data.startswith("note_filter:"))
    async def handle_note_filter(callback: CallbackQuery) -> None:
        category = callback.data.split(":", 1)[1]
        notes = db.list_notes(callback.from_user.id, category)
        text = "\n".join(f"• [{n['category']}] {n['text']}" for n in notes) if notes else "Пусто в этой категории."
        try:
            await callback.message.edit_text(
                render_emoji_tags(db, f"{{emoji:notes_icon}} <b>Твои заметки ({category}):</b>\n\n{html.escape(text)}"),
                parse_mode="HTML", reply_markup=build_notes_keyboard(callback.from_user.id, category),
            )
        except TelegramBadRequest:
            pass
        await callback.answer()

    @dp.callback_query(F.data == "note_add")
    async def handle_note_add(callback: CallbackQuery, state: FSMContext) -> None:
        await state.set_state(UserStates.waiting_note_text)
        await callback.message.answer("Пришли текст заметки.")
        await callback.answer()

    @dp.message(UserStates.waiting_note_text)
    async def handle_note_text(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        if not text:
            await message.answer("Пустая заметка не сохранится.")
            return
        await state.update_data(note_text=text)
        await state.set_state(UserStates.waiting_note_category)
        await message.answer(
            "Категория заметки:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=c, callback_data=f"note_cat:{c}")] for c in Database.NOTE_CATEGORIES
            ]),
        )

    @dp.callback_query(F.data.startswith("note_cat:"))
    async def handle_note_category(callback: CallbackQuery, state: FSMContext) -> None:
        data = await state.get_data()
        text = data.get("note_text", "")
        category = callback.data.split(":", 1)[1]
        await state.clear()
        if not text:
            await callback.answer("Что-то пошло не так, начни заново.", show_alert=True)
            return
        db.add_note(callback.from_user.id, text, category)
        await callback.message.answer("✅ Заметка сохранена.", reply_markup=build_notes_keyboard(callback.from_user.id))
        await _mark_used(callback.message, callback.from_user.id, "notes")
        await callback.answer()

    @dp.callback_query(F.data.startswith("note_del:"))
    async def handle_note_del(callback: CallbackQuery) -> None:
        note_id = int(callback.data.split(":", 1)[1])
        db.delete_note(note_id, callback.from_user.id)
        await callback.message.edit_reply_markup(reply_markup=build_notes_keyboard(callback.from_user.id))
        await callback.answer("Удалено")

    # -- Hub: мини-игра (нативные Telegram-дайсы) ------------------------
    @dp.callback_query(F.data == "hub_game")
    async def handle_hub_game(callback: CallbackQuery) -> None:
        await callback.message.answer(
            render_emoji_tags(db, "{emoji:game_icon} Выбери игру:"), parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎲 Кубик", callback_data="game_dice:🎲")],
                [InlineKeyboardButton(text="🎯 Дартс", callback_data="game_dice:🎯")],
                [InlineKeyboardButton(text="🏀 Баскетбол", callback_data="game_dice:🏀")],
                [InlineKeyboardButton(text="⚽ Футбол", callback_data="game_dice:⚽")],
                [InlineKeyboardButton(text="🎰 Слоты", callback_data="game_dice:🎰")],
            ]),
        )
        await callback.answer()

    @dp.callback_query(F.data.startswith("game_dice:"))
    async def handle_game_dice(callback: CallbackQuery) -> None:
        emoji = callback.data.split(":", 1)[1]
        await callback.bot.send_dice(callback.message.chat.id, emoji=emoji)
        await _mark_used(callback.message, callback.from_user.id, "game")
        await callback.answer()

    # -- Донаты: CryptoBot ------------------------------------------------
    @dp.callback_query(F.data == "support_crypto")
    async def handle_support_crypto(callback: CallbackQuery) -> None:
        if not db.get_setting("crypto_pay_token", ""):
            await callback.answer("Оплата криптой пока не настроена.", show_alert=True)
            return
        await callback.message.answer("Выбери валюту:", reply_markup=build_currency_keyboard())
        await callback.answer()

    @dp.callback_query(F.data.startswith("donate_cur:"))
    async def handle_donate_currency(callback: CallbackQuery, state: FSMContext) -> None:
        currency = callback.data.split(":", 1)[1]
        await state.set_state(UserStates.waiting_donation_crypto_amount)
        await state.update_data(donate_currency=currency)
        await callback.message.answer(f"Сколько долларов эквивалентно хочешь задонатить в {currency}? Просто пришли число.")
        await callback.answer()

    @dp.message(UserStates.waiting_donation_crypto_amount)
    async def handle_donation_crypto_amount(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        currency = data.get("donate_currency", "USDT")
        await state.clear()
        try:
            amount = float((message.text or "").replace(",", ".").strip())
            assert amount > 0
        except Exception:
            await message.answer("Нужно положительное число, например 5.")
            return
        token = db.get_setting("crypto_pay_token", "")
        invoice = await cryptobot_create_invoice(
            token, amount, "Поддержка проекта Kewo AI", payload=f"donate:{message.from_user.id}", asset=currency
        )
        if not invoice:
            await message.answer("⚠️ Не получилось создать счёт, попробуй позже.")
            return
        db.create_pending_donation(message.from_user.id, f"{amount:.2f} USD ({currency})", "crypto", invoice["invoice_id"])
        await message.answer(
            f"💎 Счёт на ${amount:.2f} в {currency} создан. Спасибо за поддержку!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [mk_ikb(db, "btn_donate_pay", "Оплатить", url=invoice["pay_url"])],
                [mk_ikb(db, "btn_donate_check", "Проверить оплату", callback_data=f"check_donate:{invoice['invoice_id']}")],
            ]),
        )

    @dp.callback_query(F.data.startswith("check_donate:"))
    async def handle_check_donate(callback: CallbackQuery) -> None:
        invoice_id = callback.data.split(":", 1)[1]
        token = db.get_setting("crypto_pay_token", "")
        status = await cryptobot_check_invoice(token, invoice_id) if token else None
        if status == "paid":
            db.mark_donation_paid(invoice_id)
            await callback.message.edit_text("✅ Спасибо за поддержку, оплата подтверждена! 💛")
        else:
            await callback.answer("Пока не вижу оплату, попробуй через минуту.", show_alert=True)

    # -- Донаты: Stars --------------------------------------------------------
    @dp.callback_query(F.data == "support_stars")
    async def handle_support_stars(callback: CallbackQuery) -> None:
        await callback.message.answer("⭐ Сколько Stars хочешь задонатить?", reply_markup=build_stars_amount_keyboard(db))
        await callback.answer()

    @dp.callback_query(F.data.startswith("donate_stars:"))
    async def handle_donate_stars_preset(callback: CallbackQuery) -> None:
        amount = int(callback.data.split(":", 1)[1])
        await _send_stars_invoice(callback.message, amount)
        await callback.answer()

    @dp.callback_query(F.data == "donate_stars_custom")
    async def handle_donate_stars_custom(callback: CallbackQuery, state: FSMContext) -> None:
        await state.set_state(UserStates.waiting_donation_stars_custom)
        await callback.message.answer("Сколько Stars? Пришли число.")
        await callback.answer()

    @dp.message(UserStates.waiting_donation_stars_custom)
    async def handle_donate_stars_custom_amount(message: Message, state: FSMContext) -> None:
        await state.clear()
        try:
            amount = int((message.text or "").strip())
            assert amount > 0
        except Exception:
            await message.answer("Нужно положительное целое число.")
            return
        await _send_stars_invoice(message, amount)

    async def _send_stars_invoice(message: Message, amount: int) -> None:
        await message.answer_invoice(
            title="Поддержка Kewo AI",
            description=f"Донат на развитие проекта — {amount} ⭐",
            payload=f"donate_stars:{amount}",
            provider_token="",
            currency="XTR",
            prices=[{"label": "Донат", "amount": amount}],
        )

    @dp.pre_checkout_query()
    async def handle_pre_checkout(pre_checkout: PreCheckoutQuery) -> None:
        await pre_checkout.answer(ok=True)

    @dp.message(F.successful_payment)
    async def handle_successful_payment(message: Message) -> None:
        payment = message.successful_payment
        db.create_pending_donation(message.from_user.id, str(payment.total_amount), "stars", payment.telegram_payment_charge_id)
        db.mark_donation_paid(payment.telegram_payment_charge_id)
        await message.answer("✅ Спасибо за поддержку! 💛")

    # -- Скачать код файлом ------------------------------------------------
    @dp.callback_query(F.data.startswith("savefile:"))
    async def handle_save_file(callback: CallbackQuery) -> None:
        _, user_id_s, idx_s = callback.data.split(":", 2)
        user_id, idx = int(user_id_s), int(idx_s)
        blocks = LAST_CODE_CACHE.get(user_id, [])
        if idx >= len(blocks):
            await callback.answer("Этот код уже не в кэше — попроси написать заново.", show_alert=True)
            return
        lang, code = blocks[idx]
        ext = LANG_EXT.get(lang.lower(), "txt")
        file = BufferedInputFile(code.encode("utf-8"), filename=f"code.{ext}")
        await callback.message.answer_document(file)
        await callback.answer()

    # -- Избранное ------------------------------------------------------------
    def build_favorites_keyboard(user_id: int) -> InlineKeyboardMarkup:
        favs = db.list_favorites(user_id)
        rows = [[InlineKeyboardButton(text=f"🗑 {f['text'][:40]}", callback_data=f"fav_del:{f['id']}")] for f in favs[:15]]
        return InlineKeyboardMarkup(inline_keyboard=rows) if rows else InlineKeyboardMarkup(inline_keyboard=[])

    @dp.callback_query(F.data == "fav_add")
    async def handle_fav_add(callback: CallbackQuery) -> None:
        user_id = callback.from_user.id
        text = LAST_AI_TEXT_CACHE.get(user_id)
        if not text:
            await callback.answer("Этот ответ уже не в кэше.", show_alert=True)
            return
        db.add_favorite(user_id, text)
        await callback.answer("⭐ Сохранено в избранное")
        await _mark_used(callback.message, callback.from_user.id, "favorites")

    @dp.message(Command("favorites"))
    async def handle_favorites_cmd(message: Message) -> None:
        favs = db.list_favorites(message.from_user.id)
        if not favs:
            await message.answer("⭐ Пока пусто. Жми «В избранное» под ответами ИИ, которые хочешь сохранить.")
            return
        body = "\n\n".join(f"{i+1}. {f['text'][:200]}" for i, f in enumerate(favs[:15]))
        await message.answer(
            f"⭐ <b>Твоё избранное:</b>\n\n{body}", parse_mode="HTML",
            reply_markup=build_favorites_keyboard(message.from_user.id),
        )

    @dp.callback_query(F.data.startswith("fav_del:"))
    async def handle_fav_del(callback: CallbackQuery) -> None:
        fav_id = int(callback.data.split(":", 1)[1])
        db.delete_favorite(fav_id, callback.from_user.id)
        await callback.message.edit_reply_markup(reply_markup=build_favorites_keyboard(callback.from_user.id))
        await callback.answer("Удалено")

    # -- Профиль (бейджи и уровень) -------------------------------------
    @dp.message(Command("profile"))
    async def handle_profile_cmd(message: Message) -> None:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT messages_count FROM users WHERE user_id = ?", (message.from_user.id,)
            ).fetchone()
        count = row["messages_count"] if row else 0
        level = 1 + count // 20  # простая прогрессия: +1 уровень за каждые 20 сообщений
        badges = db.list_badges(message.from_user.id)
        badge_lines = "\n".join(f"• {Database.BADGE_TITLES[b]}" for b in badges) or "Пока нет — общайся с ботом, чтобы получить первый!"
        await message.answer(
            f"👤 <b>Твой профиль</b>\n\n"
            f"Сообщений боту: <b>{count}</b>\n"
            f"Уровень: <b>{level}</b>\n\n"
            f"<b>Бейджи:</b>\n{badge_lines}",
            parse_mode="HTML",
        )

    # -- Основной чат с ИИ --------------------------------------------------
    # КРИТИЧНО: StateFilter(None) обязателен. Раньше этот хендлер матчил ЛЮБОЙ
    # текст независимо от состояния и, будучи зарегистрирован раньше админских
    # FSM-хендлеров (эмодзи, крипто-токен и т.д.), перехватывал сообщение первым
    # и просто тихо выходил — сами админские хендлеры даже не запускались.
    # Именно поэтому бот "молчал" после ввода эмодзи/ключа CryptoBot.
    @dp.message(StateFilter(None), F.text & ~F.text.startswith("/"))
    async def handle_chat(message: Message, state: FSMContext) -> None:
        if db.get_setting("maintenance_mode", "0") == "1" and not _is_owner(message.from_user.id, settings):
            await message.answer(MAINTENANCE_MESSAGE)
            return
        if message.chat.type != "private":
            if db.get_setting("allow_groups", "0") != "1":
                return
            bot_username = _bot_username_cache.get("username")
            if bot_username is None:
                me = await message.bot.get_me()
                bot_username = (me.username or "").lower()
                _bot_username_cache["username"] = bot_username
            text_lower = (message.text or "").lower()
            is_mention = bool(bot_username) and f"@{bot_username}" in text_lower
            is_reply_to_bot = bool(
                message.reply_to_message and message.reply_to_message.from_user
                and message.reply_to_message.from_user.is_bot
            )
            if not (is_mention or is_reply_to_bot):
                return
        db.upsert_user(message.from_user.id, message.from_user.first_name or "", message.from_user.username)
        db.bump_messages(message.from_user.id)
        model = db.get_setting("default_model", settings.default_model)
        await ai_reply(message, model, message.text or "")

    # -- АДМИН-ПАНЕЛЬ ---------------------------------------------------------
    def build_admin_menu() -> InlineKeyboardMarkup:
        savage = db.get_setting("savage_mode", "1") == "1"
        groups_on = db.get_setting("allow_groups", "0") == "1"
        maintenance = db.get_setting("maintenance_mode", "0") == "1"
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users:0")],
            [InlineKeyboardButton(text="📤 Экспорт пользователей (CSV)", callback_data="admin_export_users")],
            [InlineKeyboardButton(text="📣 Рассылка сейчас", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="📅 Запланировать рассылку", callback_data="admin_schedule_broadcast")],
            [InlineKeyboardButton(text="📋 Активные рассылки", callback_data="admin_scheduled_list")],
            [InlineKeyboardButton(
                text=f"🧠 Модель по умолчанию: {db.get_setting('default_model', settings.default_model)}",
                callback_data="admin_model",
            )],
            [InlineKeyboardButton(
                text=f"🎨 Модель для картинок: {db.get_setting('image_model', '') or 'не задана'}",
                callback_data="admin_image_model",
            )],
            [InlineKeyboardButton(
                text=f"😈 Дерзкие ответы на мат: {'ВКЛ' if savage else 'выкл'}",
                callback_data="admin_savage_toggle",
            )],
            [InlineKeyboardButton(
                text=f"👥 Работа в группах: {'ВКЛ' if groups_on else 'выкл'}",
                callback_data="admin_groups_toggle",
            )],
            [InlineKeyboardButton(
                text=f"🛠 Технические работы: {'ВКЛ (бот не отвечает)' if maintenance else 'выкл'}",
                callback_data="admin_maintenance_toggle",
            )],
            [InlineKeyboardButton(
                text=f"👤 Поддержка: {db.get_setting('support_username', '') or 'не задан'}",
                callback_data="admin_support_username",
            )],
            [InlineKeyboardButton(
                text=f"💰 CryptoBot: {'настроен ✅' if db.get_setting('crypto_pay_token', '') else 'не задан'}",
                callback_data="admin_crypto_token",
            )],
            [InlineKeyboardButton(text="📝 Доп. инструкции персоне", callback_data="admin_extra_instructions")],
            [InlineKeyboardButton(text="🧠 Само-улучшение (промпт для Клода)", callback_data="admin_self_improve")],
            [InlineKeyboardButton(text="💎 Премиум-эмодзи (в текстах)", callback_data="admin_emoji")],
            [InlineKeyboardButton(text="🔘 Иконки и текст кнопок", callback_data="admin_btnicons")],
        ])

    @dp.message(Command("admin"))
    async def handle_admin(message: Message) -> None:
        if not _is_owner(message.from_user.id, settings):
            return
        await message.answer("<b>🔐 Админ-панель Kewo AI</b>", parse_mode="HTML", reply_markup=build_admin_menu())

    @dp.callback_query(F.data == "admin_menu")
    async def handle_admin_menu_cb(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        await callback.message.edit_text("<b>🔐 Админ-панель Kewo AI</b>", parse_mode="HTML", reply_markup=build_admin_menu())
        await callback.answer()

    @dp.callback_query(F.data == "admin_stats")
    async def handle_admin_stats(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        total = db.users_count()
        today = db.users_joined_today()
        messages = db.total_messages()
        top = db.top_users(5)
        top_lines = "\n".join(f"  {i+1}. {u['first_name'] or '—'} — {u['messages_count']} сообщ." for i, u in enumerate(top)) or "  пока пусто"
        await callback.message.edit_text(
            f"📊 <b>Статистика</b>\n\n"
            f"Всего пользователей: <b>{total}</b>\n"
            f"Новых сегодня: <b>{today}</b>\n"
            f"Всего сообщений боту: <b>{messages}</b>\n\n"
            f"<b>Топ по активности:</b>\n{top_lines}",
            parse_mode="HTML", reply_markup=build_admin_menu(),
        )
        await callback.answer()

    @dp.callback_query(F.data == "admin_export_users")
    async def handle_admin_export_users(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        rows = db.list_users(limit=100000, offset=0)
        lines = ["user_id,first_name,username,messages_count,joined_at"]
        for u in rows:
            fn = (u["first_name"] or "").replace(",", " ")
            lines.append(f"{u['user_id']},{fn},{u['username']},{u['messages_count']},{u['joined_at']}")
        csv_bytes = "\n".join(lines).encode("utf-8")
        await callback.message.answer_document(BufferedInputFile(csv_bytes, filename="users.csv"))
        await callback.answer()

    @dp.callback_query(F.data == "admin_model")
    async def handle_admin_model(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        current = db.get_setting("default_model", settings.default_model)
        await callback.message.edit_text("🧠 Модель по умолчанию для всех ответов Kewo AI:", reply_markup=build_model_keyboard(db, current))
        await callback.answer()

    @dp.callback_query(F.data.startswith("admin_setmodel:"))
    async def handle_admin_setmodel(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        model = callback.data.split(":", 1)[1]
        if model not in MODEL_KEYS:
            await callback.answer("Такой модели нет.", show_alert=True)
            return
        db.set_setting("default_model", model)
        await callback.message.edit_reply_markup(reply_markup=build_model_keyboard(db, model))
        await callback.answer(f"Модель по умолчанию: {model}")

    @dp.callback_query(F.data == "admin_savage_toggle")
    async def handle_admin_savage_toggle(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        current = db.get_setting("savage_mode", "1")
        db.set_setting("savage_mode", "0" if current == "1" else "1")
        await callback.message.edit_reply_markup(reply_markup=build_admin_menu())
        await callback.answer("Переключено")

    @dp.callback_query(F.data == "admin_groups_toggle")
    async def handle_admin_groups_toggle(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        current = db.get_setting("allow_groups", "0")
        db.set_setting("allow_groups", "0" if current == "1" else "1")
        await callback.message.edit_reply_markup(reply_markup=build_admin_menu())
        await callback.answer("Переключено")

    @dp.callback_query(F.data == "admin_maintenance_toggle")
    async def handle_admin_maintenance_toggle(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        current = db.get_setting("maintenance_mode", "0")
        db.set_setting("maintenance_mode", "0" if current == "1" else "1")
        await callback.message.edit_reply_markup(reply_markup=build_admin_menu())
        await callback.answer("Переключено")

    @dp.callback_query(F.data.startswith("admin_users:"))
    async def handle_admin_users(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        offset = int(callback.data.split(":", 1)[1])
        users = db.list_users(limit=20, offset=offset)
        if not users:
            lines = ["Пользователей пока нет."]
        else:
            lines = [
                f"• {u['first_name'] or '—'} (@{u['username']}) — id {u['user_id']}, сообщений: {u['messages_count']}"
                for u in users
            ]
        nav = []
        if offset > 0:
            nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"admin_users:{max(0, offset - 20)}"))
        if len(users) == 20:
            nav.append(InlineKeyboardButton(text="➡️", callback_data=f"admin_users:{offset + 20}"))
        rows = ([nav] if nav else []) + [[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_menu")]]
        await callback.message.edit_text(
            "👥 <b>Пользователи</b>\n\n" + "\n".join(lines), parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
        await callback.answer()

    @dp.callback_query(F.data == "admin_broadcast")
    async def handle_admin_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        await state.set_state(AdminStates.waiting_broadcast_text)
        await callback.message.answer("Пришли текст рассылки (уйдёт всем пользователям бота).")
        await callback.answer()

    @dp.message(AdminStates.waiting_broadcast_text)
    async def handle_broadcast_text(message: Message, state: FSMContext) -> None:
        await state.clear()
        ids = db.all_user_ids()
        sent = 0
        for uid in ids:
            try:
                await message.bot.copy_message(uid, message.chat.id, message.message_id)
                sent += 1
            except Exception:
                pass
            await asyncio.sleep(0.05)
        await message.answer(f"✅ Разослано {sent}/{len(ids)}.")

    @dp.callback_query(F.data == "admin_schedule_broadcast")
    async def handle_admin_schedule_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        await state.set_state(AdminStates.waiting_schedule_broadcast_text)
        await callback.message.answer("Пришли текст, который бот будет рассылать сам (без твоего участия каждый раз).")
        await callback.answer()

    @dp.message(AdminStates.waiting_schedule_broadcast_text)
    async def handle_schedule_broadcast_text(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        if not text:
            await message.answer("Пустой текст, попробуй ещё раз.")
            return
        await state.update_data(schedule_text=text)
        await state.set_state(AdminStates.waiting_schedule_broadcast_time)
        await message.answer(
            "Когда отправлять? Форматы: «через 2 часа», «в 09:00» (разово), «каждый день в 09:00», "
            "«каждый понедельник в 10:00», «каждое 1 число в 12:00» (повторяющиеся)."
        )

    @dp.message(AdminStates.waiting_schedule_broadcast_time)
    async def handle_schedule_broadcast_time(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        text = data.get("schedule_text", "")
        await state.clear()
        parsed = parse_reminder(message.text or "")
        if not parsed or not text:
            await message.answer("Не понял время (или текст потерялся) — начни заново через «📅 Запланировать рассылку».")
            return
        send_at, _rest, repeat_rule = parsed
        db.add_scheduled_broadcast(text, send_at, repeat_rule)
        when = datetime.fromtimestamp(send_at).strftime("%d.%m %H:%M")
        repeat_note = {"daily": " (повтор: каждый день)"}.get(
            repeat_rule, " (повтор: каждую неделю)" if repeat_rule.startswith("weekly:") else
            (" (повтор: каждый месяц)" if repeat_rule.startswith("monthly:") else "")
        )
        await message.answer(f"✅ Рассылка запланирована на {when}{repeat_note}.", reply_markup=build_admin_menu())

    @dp.callback_query(F.data == "admin_scheduled_list")
    async def handle_admin_scheduled_list(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        items = db.list_scheduled_broadcasts()
        if not items:
            await callback.message.edit_text("📋 Активных запланированных рассылок нет.", reply_markup=build_admin_menu())
            await callback.answer()
            return
        rows = []
        for it in items:
            when = datetime.fromtimestamp(it["send_at"]).strftime("%d.%m %H:%M")
            repeat_mark = " 🔁" if it["repeat_rule"] else ""
            rows.append([InlineKeyboardButton(
                text=f"🗑 {when}{repeat_mark} — {it['text'][:30]}", callback_data=f"admin_scheduled_del:{it['id']}",
            )])
        rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_menu")])
        await callback.message.edit_text(
            "📋 Активные рассылки (жми, чтобы отменить):", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
        await callback.answer()

    @dp.callback_query(F.data.startswith("admin_scheduled_del:"))
    async def handle_admin_scheduled_del(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        broadcast_id = int(callback.data.split(":", 1)[1])
        db.delete_scheduled_broadcast(broadcast_id)
        await handle_admin_scheduled_list(callback)

    @dp.callback_query(F.data == "admin_support_username")
    async def handle_admin_support_username(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        await state.set_state(AdminStates.waiting_support_username)
        await callback.message.answer("Пришли юзернейм поддержки (например @support) или '-' чтобы убрать кнопку.")
        await callback.answer()

    @dp.message(AdminStates.waiting_support_username)
    async def handle_support_username_input(message: Message, state: FSMContext) -> None:
        val = (message.text or "").strip()
        db.set_setting("support_username", "" if val == "-" else val.lstrip("@"))
        await state.clear()
        await message.answer("✅ Обновлено.", reply_markup=build_admin_menu())

    @dp.callback_query(F.data == "admin_crypto_token")
    async def handle_admin_crypto_token(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        await state.set_state(AdminStates.waiting_crypto_token)
        await callback.message.answer("Пришли API-токен CryptoBot (из @CryptoBot → Crypto Pay → Create App).")
        await callback.answer()

    @dp.message(AdminStates.waiting_crypto_token)
    async def handle_crypto_token_input(message: Message, state: FSMContext) -> None:
        token = (message.text or "").strip()
        db.set_setting("crypto_pay_token", token)
        await state.clear()
        try:
            await message.delete()
        except Exception:
            pass
        await message.answer("✅ Токен сохранён (сообщение с ним удалено).", reply_markup=build_admin_menu())

    @dp.callback_query(F.data == "admin_image_model")
    async def handle_admin_image_model(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        await state.set_state(AdminStates.waiting_image_model)
        await callback.message.answer(
            "Пришли название модели для генерации картинок, которое поддерживает твой "
            "прокси (уточни у провайдера — гарантировать конкретное имя не могу), или '-' чтобы очистить."
        )
        await callback.answer()

    @dp.message(AdminStates.waiting_image_model)
    async def handle_image_model_input(message: Message, state: FSMContext) -> None:
        val = (message.text or "").strip()
        db.set_setting("image_model", "" if val == "-" else val)
        await state.clear()
        await message.answer("✅ Обновлено.", reply_markup=build_admin_menu())

    @dp.callback_query(F.data == "admin_extra_instructions")
    async def handle_admin_extra_instructions(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        await state.set_state(AdminStates.waiting_extra_instructions)
        await callback.message.answer("Пришли доп. инструкции для персоны Kewo AI (добавятся к системному промпту), или '-' чтобы очистить.")
        await callback.answer()

    @dp.message(AdminStates.waiting_extra_instructions)
    async def handle_extra_instructions_input(message: Message, state: FSMContext) -> None:
        val = (message.text or "").strip()
        db.set_setting("extra_instructions", "" if val == "-" else val)
        await state.clear()
        await message.answer("✅ Обновлено.", reply_markup=build_admin_menu())

    @dp.callback_query(F.data == "admin_self_improve")
    async def handle_admin_self_improve(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        await callback.answer("Думаю над улучшениями...")
        model = db.get_setting("default_model", settings.default_model)
        result = await with_action(callback.bot, callback.message.chat.id, "typing", ai_chat(
            settings, model, SELF_IMPROVE_SYSTEM_PROMPT,
            f"Вот что бот уже умеет:\n\n{BOT_FEATURE_SUMMARY}\n\nПредложи улучшения.",
            max_tokens=1200,
        ))
        if not result:
            await callback.message.answer("⚠️ Не получилось сгенерировать предложения, попробуй ещё раз.")
            return
        file = BufferedInputFile(result.encode("utf-8"), filename="kewo_ai_improvements_prompt.txt")
        await callback.message.answer_document(
            file, caption="🧠 Готовый промпт для Клода — скопируй текст из файла и отправь мне в чат."
        )

    # -- Премиум-эмодзи в текстах (универсально, любой ключ) --------------
    def build_emoji_admin_keyboard() -> InlineKeyboardMarkup:
        rows = []
        for row in db.all_emoji_keys():
            key = row["key"]
            if key.startswith("btn:"):
                continue  # кнопки настраиваются в своём разделе
            label = TEXT_EMOJI_LABELS.get(key, key)
            rows.append([InlineKeyboardButton(text=f"{row['fallback'] or '⭐'} {label}", callback_data=f"admin_emoji_pick:{key}")])
        rows.append([InlineKeyboardButton(text="➕ Добавить свой (любой текст)", callback_data="admin_emoji_new")])
        rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_menu")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @dp.callback_query(F.data == "admin_emoji")
    async def handle_admin_emoji(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        await callback.message.edit_text("💎 Выбери, для какого текста задать премиум-эмодзи:", reply_markup=build_emoji_admin_keyboard())
        await callback.answer()

    @dp.callback_query(F.data == "admin_emoji_new")
    async def handle_admin_emoji_new(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        await state.set_state(AdminStates.waiting_new_emoji_key)
        await callback.message.answer("Придумай короткое имя слота латиницей без пробелов (например: greeting_icon).")
        await callback.answer()

    @dp.message(AdminStates.waiting_new_emoji_key)
    async def handle_new_emoji_key(message: Message, state: FSMContext) -> None:
        key = re.sub(r"[^a-zA-Z0-9_]", "", (message.text or "").strip())[:40]
        if not key:
            await message.answer("Нужно хотя бы одну латинскую букву/цифру.")
            return
        db.set_emoji(key, "", "⭐")
        await state.set_state(AdminStates.waiting_emoji_forward)
        await state.update_data(emoji_key=key)
        await message.answer(f"Слот «{key}» создан. Пришли эмодзи одним сообщением.")

    @dp.callback_query(F.data.startswith("admin_emoji_pick:"))
    async def handle_admin_emoji_pick(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        key = callback.data.split(":", 1)[1]
        await state.set_state(AdminStates.waiting_emoji_forward)
        await state.update_data(emoji_key=key)
        await callback.message.answer("Пришли эмодзи (премиум — если есть Telegram Premium, иначе обычный) одним сообщением.")
        await callback.answer()

    @dp.message(AdminStates.waiting_emoji_forward)
    async def handle_emoji_forward(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        key = data.get("emoji_key")
        entities = message.entities or []
        custom = next((e for e in entities if e.type == "custom_emoji"), None)
        if custom and message.text:
            utf16 = message.text.encode("utf-16-le")
            raw = utf16[custom.offset * 2:(custom.offset + custom.length) * 2]
            fallback = raw.decode("utf-16-le", errors="ignore") or "⭐"
            db.set_emoji(key, custom.custom_emoji_id, fallback)
            await state.clear()
            await message.answer("✅ Премиум-эмодзи сохранён.", reply_markup=build_emoji_admin_keyboard())
            return
        icon = (message.text or "").strip().split()[0] if (message.text or "").strip() else ""
        if not icon:
            await message.answer("Пусто. Пришли эмодзи.")
            return
        db.set_emoji(key, "", icon)
        await state.clear()
        await message.answer(
            "⚠️ Сохранил как ОБЫЧНЫЙ эмодзи (не премиум) — Telegram не прислал ID премиум-эмодзи "
            "в этом сообщении. Обычно это значит, что у аккаунта, с которого ты отправляешь, нет "
            "Telegram Premium — без него выбрать премиум-эмодзи из панели физически нельзя, это "
            "ограничение Telegram, не бота. Если Premium есть — пришли эмодзи ещё раз отдельным "
            "новым сообщением (не пересланным).",
            reply_markup=build_emoji_admin_keyboard(),
        )

    # -- Иконки и текст кнопок ----------------------------------------------
    def build_btnicons_keyboard() -> InlineKeyboardMarkup:
        rows = []
        for key, (default_icon, label) in BUTTON_ICON_DEFAULTS.items():
            full = db.get_emoji_full(f"btn:{key}")
            mark = "💎" if (full and full[0]) else (full[1] if full and full[1] else default_icon)
            rows.append([InlineKeyboardButton(text=f"{mark} {label}", callback_data=f"admin_btnicon_pick:{key}")])
        rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_menu")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @dp.callback_query(F.data == "admin_btnicons")
    async def handle_admin_btnicons(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        await callback.message.edit_text("🔘 Иконки и текст кнопок (Bot API 9.4). Выбери кнопку:", reply_markup=build_btnicons_keyboard())
        await callback.answer()

    @dp.callback_query(F.data.startswith("admin_btnicon_pick:"))
    async def handle_admin_btnicon_pick(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        key = callback.data.split(":", 1)[1]
        label = BUTTON_ICON_DEFAULTS.get(key, ("", key))[1]
        await callback.message.answer(
            f"Кнопка: {label}\n\nЧто настроить?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💎 Эмодзи", callback_data=f"admin_btnicon_setemoji:{key}")],
                [InlineKeyboardButton(text="✏️ Текст кнопки", callback_data=f"admin_btnicon_settext:{key}")],
                [InlineKeyboardButton(text="🎨 Цвет", callback_data=f"admin_btnicon_setcolor:{key}")],
                [InlineKeyboardButton(text="♻️ Сбросить", callback_data=f"admin_btnicon_reset:{key}")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_btnicons")],
            ]),
        )
        await callback.answer()

    @dp.callback_query(F.data.startswith("admin_btnicon_setemoji:"))
    async def handle_btnicon_setemoji(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        key = callback.data.split(":", 1)[1]
        await state.set_state(AdminStates.waiting_button_icon)
        await state.update_data(btn_icon_key=key)
        await callback.message.answer("Пришли эмодзи для этой кнопки (премиум — если есть Premium, иначе обычный).")
        await callback.answer()

    @dp.message(AdminStates.waiting_button_icon)
    async def handle_button_icon_input(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        key = data.get("btn_icon_key")
        if data.get("btn_text_mode"):
            text = (message.text or "").strip()
            if not text:
                await message.answer("Пусто. Пришли текст кнопки.")
                return
            db.set_setting(f"btntext:{key}", text)
            await state.clear()
            await message.answer("✅ Текст кнопки обновлён.", reply_markup=build_btnicons_keyboard())
            return
        entities = message.entities or []
        custom = next((e for e in entities if e.type == "custom_emoji"), None)
        if custom and message.text:
            utf16 = message.text.encode("utf-16-le")
            raw = utf16[custom.offset * 2:(custom.offset + custom.length) * 2]
            fallback = raw.decode("utf-16-le", errors="ignore") or "⭐"
            db.set_emoji(f"btn:{key}", custom.custom_emoji_id, fallback)
            await state.clear()
            await message.answer("✅ Премиум-иконка сохранена.", reply_markup=build_btnicons_keyboard())
            return
        icon = (message.text or "").strip().split()[0] if (message.text or "").strip() else ""
        if not icon:
            await message.answer("Пусто. Пришли эмодзи.")
            return
        db.set_emoji(f"btn:{key}", "", icon)
        await state.clear()
        await message.answer(
            "⚠️ Сохранил как ОБЫЧНЫЙ эмодзи — Telegram не прислал ID премиум-эмодзи. Скорее всего "
            "у аккаунта нет Telegram Premium (без него выбрать премиум-эмодзи физически нельзя — "
            "ограничение Telegram). Если Premium есть — пришли ещё раз новым сообщением.",
            reply_markup=build_btnicons_keyboard(),
        )

    @dp.callback_query(F.data.startswith("admin_btnicon_settext:"))
    async def handle_btnicon_settext(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        key = callback.data.split(":", 1)[1]
        await state.set_state(AdminStates.waiting_button_icon)
        await state.update_data(btn_icon_key=key, btn_text_mode=True)
        await callback.message.answer("Пришли новый текст кнопки (без эмодзи).")
        await callback.answer()

    @dp.callback_query(F.data.startswith("admin_btnicon_setcolor:"))
    async def handle_btnicon_setcolor(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        key = callback.data.split(":", 1)[1]
        await callback.message.answer(
            "Выбери цвет кнопки:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔵 Синий", callback_data=f"admin_btnicon_color:{key}:primary")],
                [InlineKeyboardButton(text="🟢 Зелёный", callback_data=f"admin_btnicon_color:{key}:success")],
                [InlineKeyboardButton(text="🔴 Красный", callback_data=f"admin_btnicon_color:{key}:danger")],
                [InlineKeyboardButton(text="⚪️ По умолчанию", callback_data=f"admin_btnicon_color:{key}:")],
            ]),
        )
        await callback.answer()

    @dp.callback_query(F.data.startswith("admin_btnicon_color:"))
    async def handle_btnicon_color(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        _, key, color = callback.data.split(":", 2)
        db.set_setting(f"btnstyle:{key}", color)
        await callback.message.answer("✅ Цвет обновлён.", reply_markup=build_btnicons_keyboard())
        await callback.answer()

    @dp.callback_query(F.data.startswith("admin_btnicon_reset:"))
    async def handle_btnicon_reset(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        key = callback.data.split(":", 1)[1]
        db.set_emoji(f"btn:{key}", "", "")
        db.set_setting(f"btnstyle:{key}", "")
        db.set_setting(f"btntext:{key}", "")
        await callback.message.answer("♻️ Сброшено.", reply_markup=build_btnicons_keyboard())
        await callback.answer()


# ======================================================================
# ФОНОВЫЕ ЗАДАЧИ
# ======================================================================

async def reminders_loop(bot: Bot, db: Database) -> None:
    while True:
        try:
            for row in db.due_reminders():
                try:
                    await bot.send_message(row["user_id"], f"⏰ Напоминание: {row['text']}")
                except Exception:
                    logger.exception("Failed to send reminder to %s", row["user_id"])
                if row["repeat_rule"]:
                    next_ts = next_occurrence_after(row["repeat_rule"], row["remind_at"])
                    db.reschedule_reminder(row["id"], next_ts)
                else:
                    db.mark_reminder_fired(row["id"])
        except Exception:
            logger.exception("reminders_loop iteration failed")
        await asyncio.sleep(15)


async def broadcasts_loop(bot: Bot, db: Database) -> None:
    """Само-рассылка: сообщения, запланированные админом (разово или по
    повтору), уходят всем пользователям без дальнейшего участия админа."""
    while True:
        try:
            for row in db.due_broadcasts():
                ids = db.all_user_ids()
                sent = 0
                for uid in ids:
                    try:
                        await bot.send_message(uid, row["text"])
                        sent += 1
                    except Exception:
                        pass
                    await asyncio.sleep(0.05)
                logger.info("Scheduled broadcast %s sent to %s/%s users", row["id"], sent, len(ids))
                if row["repeat_rule"]:
                    next_ts = next_occurrence_after(row["repeat_rule"], row["send_at"])
                    db.reschedule_broadcast(row["id"], next_ts)
                else:
                    db.mark_broadcast_fired(row["id"])
        except Exception:
            logger.exception("broadcasts_loop iteration failed")
        await asyncio.sleep(30)


async def crypto_donations_loop(bot: Bot, db: Database) -> None:
    while True:
        try:
            token = db.get_setting("crypto_pay_token", "")
            if token:
                for row in db.pending_crypto_donations():
                    status = await cryptobot_check_invoice(token, row["invoice_id"])
                    if status == "paid":
                        db.mark_donation_paid(row["invoice_id"])
                        try:
                            await bot.send_message(row["user_id"], "✅ Спасибо за поддержку, оплата подтверждена! 💛")
                        except Exception:
                            pass
        except Exception:
            logger.exception("crypto_donations_loop iteration failed")
        await asyncio.sleep(60)


# ======================================================================
# ENTRYPOINT
# ======================================================================

async def main() -> None:
    settings = Settings.from_env()
    db = Database(DB_PATH, settings.owner_id)
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    register_handlers(dp, db, settings)

    clean_commands = [
        BotCommand(command="start", description="Начать"),
        BotCommand(command="support", description="Поддержка / помочь проекту"),
    ]
    # Если раньше на этом же токене работал другой бот (например, CodeSchool), он мог
    # выставить свой список команд ОТДЕЛЬНО для чата владельца через BotCommandScopeChat
    # (например /admin, /balance, /buy) — Telegram хранит это как отдельный scope и не
    # затирает его автоматическим set_my_commands() для дефолтного scope. Поэтому
    # явно чистим и дефолтный scope, и персональный scope владельца.
    try:
        await bot.delete_my_commands(scope=BotCommandScopeDefault())
        await bot.set_my_commands(clean_commands, scope=BotCommandScopeDefault())
        if settings.owner_id:
            await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=settings.owner_id))
            await bot.set_my_commands(clean_commands, scope=BotCommandScopeChat(chat_id=settings.owner_id))
    except Exception:
        logger.exception("Failed to reset bot commands (old commands may still be visible)")

    asyncio.create_task(reminders_loop(bot, db))
    asyncio.create_task(crypto_donations_loop(bot, db))
    asyncio.create_task(broadcasts_loop(bot, db))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
