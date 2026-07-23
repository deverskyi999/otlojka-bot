# -*- coding: utf-8 -*-
"""
Конфигурация бота.
Заполните BOT_TOKEN и ADMIN_ID перед запуском.
"""

import os

# Токен бота, полученный от @BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН_СЮДА")

# Ваш Telegram user_id (узнать можно у @userinfobot)
# Только этот пользователь получит доступ к админ-панели
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Юзернейм создателя бота, отображается в приветствии
CREATOR_USERNAME = "@deverskyi"

# Путь к файлу базы данных SQLite
DB_PATH = os.getenv("DB_PATH", "bot.db")

# ---------- Игровые константы по умолчанию (всё это можно менять из админки) ----------

# Ежедневный бонус (обычный аккаунт)
DAILY_BONUS_DIAMONDS = 1

# Ежедневный (часовой) бонус для VIP/Creative
CREATIVE_HOURLY_DIAMONDS = 1
CREATIVE_HOURLY_IRON = 2

# Кулдаун добычи дерева (в секундах)
WOOD_COOLDOWN_SECONDS = 20 * 60  # 20 минут
WOOD_MIN = 1
WOOD_MAX = 5

# Размер поля шахты
MINE_SIZE = 5  # 5x5 = 25 ячеек
MINE_DYNAMITE_COUNT = 3  # количество "динамитов" (пусто/бомб) на поле

# Стоимость Lucky Block в алмазах
LUCKY_BLOCK_COST = 5

# Магазин звёзд: курс
# 1 алмаз = 2 звезды (пользователь вводит нужное кол-во алмазов, бот считает звёзды)
STARS_PER_DIAMOND = 2

# За 1 звезду: 5 необработанного железа
STARS_IRON_PACK_COST = 1
STARS_IRON_PACK_AMOUNT = 5

# За 1 звезду: 2 переплавленных алмаза (пример спец-пака)
STARS_DIAMOND_PACK_COST = 1
STARS_DIAMOND_PACK_AMOUNT = 2

# Стоимость Creative-статуса (звёзды)
CREATIVE_COST_STARS = 100

# HP игрока в PVP (в сердечках)
PVP_MAX_HP = 10

# Слова-триггеры (можно менять прямо тут или сделать настраиваемыми через админку -> settings table)
TRIGGER_HELP = ["хелп", "help", "команды", "помощь"]
TRIGGER_MINE = "копать"          # игра "шахта": копать <сумма|макс>
TRIGGER_TRANSFER = "дать"        # перевод ресурсов: реплай + "дать <кол-во> <ресурс>"
TRIGGER_PVP = "пп"               # вызов на пвп: реплай + "пп <сумма>"
TRIGGER_CRAFT = "крафт"
TRIGGER_ARMOR = "броня"
TRIGGER_CHOP = "добыть"          # добыча дерева
TRIGGER_FURNACE = "печка"
TRIGGER_LUCKY = "лаки"
TRIGGER_BALANCE = "баланс"
TRIGGER_INVENTORY = "инвентарь"
TRIGGER_SHOP = "магазин"
