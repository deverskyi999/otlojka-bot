import os, logging, sqlite3
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          MessageHandler, filters, ContextTypes)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN  = os.environ["BOT_TOKEN"]
ADMIN_IDS  = {6663785244, 8830973658}

PLATFORM_DISPLAY = {"yandex": "Яндекс Карты", "2gis": "2ГИС",
                    "google": "Гугл Карты",    "avito": "Авито"}

# ══════════════════════════════════════════════════════════════════
#  DATABASE
# ══════════════════════════════════════════════════════════════════

DB_PATH = "bot.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
        allowed INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now')))""")
    c.execute("""CREATE TABLE IF NOT EXISTS allowed_usernames (username TEXT PRIMARY KEY)""")
    c.execute("""CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, author_username TEXT,
        platform TEXT, price TEXT, description TEXT, channel_id TEXT, message_id INTEGER,
        status TEXT DEFAULT 'active', auto_delete_at TEXT, created_at TEXT DEFAULT (datetime('now')))""")
    c.execute("""CREATE TABLE IF NOT EXISTS channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT UNIQUE,
        channel_name TEXT, added_at TEXT DEFAULT (datetime('now')))""")
    c.execute("""CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)""")
    defaults = {
        "btn_post":           "📝 Выложить задание",
        "btn_stats":          "📊 Статистика",
        "btn_delete":         "🗑 Удалить задание",
        "btn_yandex":         "🗺 Яндекс Карты",
        "btn_2gis":           "🗺 2ГИС",
        "btn_google":         "🗺 Гугл Карты",
        "btn_avito":          "🛍 Авито",
        "btn_other":          "✏️ Другое",
        "ch_btn_contact":     "Написать",
        "ch_btn_payment":     "Выплаты",
        "ch_btn_learn":       "Обучение",
        "link_payment":       "",
        "link_learn":         "",
        "prices_yandex":      "120₽,150₽,200₽",
        "prices_2gis":        "10₽,20₽",
        "prices_avito":       "200₽,300₽,400₽,500₽",
        "prices_google":      "40₽,60₽,100₽",
        "task_template":      "НОВОЕ ЗАДАНИЕ!\n\n• Платформа: {platform}\n• Оплата: {price}\n• Описание: {description}\n\n𖥔 — · ──  ·  easy money  ·  ── · — 𖥔",
        "closed_template":    "🔓Данное задание закончилось, дождитесь следующего, чтобы приступить к работе!\n\n𖥔 — · ──  ·  easy money  ·  ── · — 𖥔",
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    conn.commit(); conn.close()

# ── Users ──────────────────────────────────────────────

def upsert_user(user_id, username, first_name):
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO users (user_id,username,first_name) VALUES (?,?,?)",
                 (user_id, username or "", first_name or ""))
    conn.execute("UPDATE users SET username=?,first_name=? WHERE user_id=?",
                 (username or "", first_name or "", user_id))
    if username:
        pre = conn.execute("SELECT username FROM allowed_usernames WHERE username=?",
                           (username.lower(),)).fetchone()
        if pre:
            conn.execute("UPDATE users SET allowed=1 WHERE user_id=?", (user_id,))
    conn.commit(); conn.close()

def is_allowed(user_id):
    conn = get_conn()
    row = conn.execute("SELECT allowed FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return bool(row and row["allowed"] == 1)

def set_allowed(user_id, allowed: bool):
    conn = get_conn()
    conn.execute("UPDATE users SET allowed=? WHERE user_id=?", (1 if allowed else 0, user_id))
    conn.commit(); conn.close()

def get_all_users():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_allowed_users():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM users WHERE allowed=1 AND user_id > 0").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_user_by_username(username):
    username = username.lstrip("@").lower()
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE LOWER(username)=?", (username,)).fetchone()
    conn.close()
    return dict(row) if row else None

def add_user_by_username(username):
    username = username.lstrip("@").lower()
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO allowed_usernames (username) VALUES (?)", (username,))
    conn.execute("UPDATE users SET allowed=1 WHERE LOWER(username)=?", (username,))
    conn.commit(); conn.close()

def remove_user_access(user_id):
    conn = get_conn()
    conn.execute("UPDATE users SET allowed=0 WHERE user_id=?", (user_id,))
    conn.commit(); conn.close()

# ── Tasks ──────────────────────────────────────────────

def create_task(user_id, author_username, platform, price, description, channel_id, message_id, auto_delete_at=None):
    conn = get_conn()
    c = conn.execute(
        "INSERT INTO tasks (user_id,author_username,platform,price,description,channel_id,message_id,auto_delete_at) VALUES (?,?,?,?,?,?,?,?)",
        (user_id, author_username, platform, price, description, channel_id, message_id, auto_delete_at))
    task_id = c.lastrowid; conn.commit(); conn.close()
    return task_id

def get_active_tasks(user_id):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM tasks WHERE user_id=? AND status='active' ORDER BY created_at DESC", (user_id,)).fetchall()
    conn.close(); return [dict(r) for r in rows]

def get_task(task_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    conn.close(); return dict(row) if row else None

def close_task(task_id):
    conn = get_conn()
    conn.execute("UPDATE tasks SET status='closed' WHERE id=?", (task_id,))
    conn.commit(); conn.close()

def get_tasks_to_auto_delete():
    conn = get_conn()
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute("SELECT * FROM tasks WHERE status='active' AND auto_delete_at IS NOT NULL AND auto_delete_at<=?", (now,)).fetchall()
    conn.close(); return [dict(r) for r in rows]

def get_all_active_tasks():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM tasks WHERE status='active' ORDER BY created_at DESC").fetchall()
    conn.close(); return [dict(r) for r in rows]

# ── Channels ───────────────────────────────────────────

def add_channel(channel_id, channel_name):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO channels (channel_id,channel_name) VALUES (?,?)", (channel_id, channel_name))
    conn.commit(); conn.close()

def get_channels():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM channels ORDER BY added_at DESC").fetchall()
    conn.close(); return [dict(r) for r in rows]

def delete_channel(channel_id):
    conn = get_conn()
    conn.execute("DELETE FROM channels WHERE channel_id=?", (channel_id,))
    conn.commit(); conn.close()

# ── Settings ───────────────────────────────────────────

def get_setting(key, default=None):
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close(); return row["value"] if row else default

def set_setting(key, value):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, value))
    conn.commit(); conn.close()

def get_prices(platform_key):
    val = get_setting(f"prices_{platform_key}", "")
    return [p.strip() for p in val.split(",") if p.strip()]

def get_stats():
    conn = get_conn()
    s = {
        "total_users":   conn.execute("SELECT COUNT(*) as n FROM users").fetchone()["n"],
        "allowed_users": conn.execute("SELECT COUNT(*) as n FROM users WHERE allowed=1").fetchone()["n"],
        "total_tasks":   conn.execute("SELECT COUNT(*) as n FROM tasks").fetchone()["n"],
        "active_tasks":  conn.execute("SELECT COUNT(*) as n FROM tasks WHERE status='active'").fetchone()["n"],
    }
    conn.close(); return s

# ══════════════════════════════════════════════════════════════════
#  KEYBOARDS
# ══════════════════════════════════════════════════════════════════

def back_kb(cb="back_main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=cb)]])

def cancel_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="cancel")]])

# ── Main menu ──────────────────────────────────────────
def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(get_setting("btn_post",   "📝 Выложить задание"), callback_data="post_task")],
        [InlineKeyboardButton(get_setting("btn_stats",  "📊 Статистика"),        callback_data="stats")],
        [InlineKeyboardButton(get_setting("btn_delete", "🗑 Удалить задание"),   callback_data="delete_task_menu")],
    ])

# ── Platform ───────────────────────────────────────────
def platform_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(get_setting("btn_yandex", "🗺 Яндекс Карты"), callback_data="platform_yandex"),
         InlineKeyboardButton(get_setting("btn_2gis",   "🗺 2ГИС"),          callback_data="platform_2gis")],
        [InlineKeyboardButton(get_setting("btn_google", "🗺 Гугл Карты"),   callback_data="platform_google"),
         InlineKeyboardButton(get_setting("btn_avito",  "🛍 Авито"),         callback_data="platform_avito")],
        [InlineKeyboardButton(get_setting("btn_other",  "✏️ Другое"),        callback_data="platform_other")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel")],
    ])

# ── Price selection ────────────────────────────────────
def price_kb(platform_key):
    prices = get_prices(platform_key)
    buttons = []
    row = []
    for i, p in enumerate(prices):
        row.append(InlineKeyboardButton(p, callback_data=f"price_{p}"))
        if len(row) == 2:
            buttons.append(row); row = []
    if row: buttons.append(row)
    buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(buttons)

# ── Channel post buttons ───────────────────────────────
def channel_post_kb(author_username):
    contact = get_setting("ch_btn_contact", "Написать")
    payment = get_setting("ch_btn_payment", "Выплаты")
    learn   = get_setting("ch_btn_learn",   "Обучение")
    pay_url = get_setting("link_payment", "")
    lrn_url = get_setting("link_learn",   "")
    buttons = [[InlineKeyboardButton(contact, url=f"https://t.me/{author_username}")]]
    row2 = []
    if pay_url: row2.append(InlineKeyboardButton(payment, url=pay_url))
    if lrn_url: row2.append(InlineKeyboardButton(learn,   url=lrn_url))
    if row2: buttons.append(row2)
    return InlineKeyboardMarkup(buttons)

# ── Confirm / autodel ──────────────────────────────────
def confirm_post_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Выложить задание", callback_data="confirm_post")],
        [InlineKeyboardButton("❌ Отменить",         callback_data="cancel")],
    ])

def auto_delete_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("30 мин", callback_data="autodel_30"),
         InlineKeyboardButton("1 час",  callback_data="autodel_60"),
         InlineKeyboardButton("2 часа", callback_data="autodel_120")],
        [InlineKeyboardButton("6 часов",  callback_data="autodel_360"),
         InlineKeyboardButton("12 часов", callback_data="autodel_720"),
         InlineKeyboardButton("24 часа",  callback_data="autodel_1440")],
        [InlineKeyboardButton("🙋 Удалю сам", callback_data="autodel_manual")],
    ])

# ── Delete tasks list ──────────────────────────────────
def delete_tasks_kb(user_id):
    tasks = get_active_tasks(user_id)
    if not tasks: return None
    buttons = [[InlineKeyboardButton(f"#{t['id']} | {t['platform']} | {t['price']}", callback_data=f"do_delete_{t['id']}")] for t in tasks]
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(buttons)

# ── Channel select ─────────────────────────────────────
def channel_select_kb():
    channels = get_channels()
    if not channels: return None
    buttons = [[InlineKeyboardButton(ch["channel_name"], callback_data=f"channel_{ch['channel_id']}")] for ch in channels]
    buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(buttons)

# ══ ADMIN keyboards ════════════════════════════════════

def admin_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Пользователи",    callback_data="adm_users"),
         InlineKeyboardButton("➕ Добавить",         callback_data="adm_add_user")],
        [InlineKeyboardButton("🗑 Удалить задание",  callback_data="adm_del_task"),
         InlineKeyboardButton("📢 Каналы",           callback_data="adm_channels")],
        [InlineKeyboardButton("💰 Цены платформ",   callback_data="adm_prices"),
         InlineKeyboardButton("🔤 Кнопки бота",      callback_data="adm_bot_buttons")],
        [InlineKeyboardButton("📋 Шаблоны текста",  callback_data="adm_templates"),
         InlineKeyboardButton("🔗 Ссылки кнопок",   callback_data="adm_links")],
        [InlineKeyboardButton("📨 Рассылка",         callback_data="adm_broadcast")],
        [InlineKeyboardButton("📊 Статистика",       callback_data="adm_stats")],
    ])

def admin_users_kb(users):
    buttons = []
    for u in users:
        status = "✅" if u["allowed"] else "🚫"
        name   = u["username"] or u["first_name"] or str(u["user_id"])
        buttons.append([InlineKeyboardButton(f"{status} @{name}", callback_data=f"adm_toggle_{u['user_id']}")])
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="adm_back")])
    return InlineKeyboardMarkup(buttons)

def admin_tasks_kb(tasks):
    buttons = []
    for t in tasks:
        uname = t.get("author_username") or "?"
        buttons.append([InlineKeyboardButton(f"#{t['id']} @{uname} | {t['platform']} | {t['price']}", callback_data=f"adm_close_{t['id']}")])
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="adm_back")])
    return InlineKeyboardMarkup(buttons)

def admin_prices_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗺 Яндекс Карты", callback_data="adm_price_yandex")],
        [InlineKeyboardButton("🗺 2ГИС",          callback_data="adm_price_2gis")],
        [InlineKeyboardButton("🗺 Гугл Карты",    callback_data="adm_price_google")],
        [InlineKeyboardButton("🛍 Авито",          callback_data="adm_price_avito")],
        [InlineKeyboardButton("🔙 Назад",          callback_data="adm_back")],
    ])

def admin_bot_buttons_kb():
    items = [
        ("btn_post",   "Главная: Выложить"),
        ("btn_stats",  "Главная: Статистика"),
        ("btn_delete", "Главная: Удалить"),
        ("btn_yandex", "Платформа: Яндекс"),
        ("btn_2gis",   "Платформа: 2ГИС"),
        ("btn_google", "Платформа: Гугл"),
        ("btn_avito",  "Платформа: Авито"),
        ("btn_other",  "Платформа: Другое"),
    ]
    buttons = [[InlineKeyboardButton(label, callback_data=f"adm_btn_{key}")] for key, label in items]
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="adm_back")])
    return InlineKeyboardMarkup(buttons)

def admin_channel_buttons_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Название 'Написать'", callback_data="adm_btn_ch_btn_contact")],
        [InlineKeyboardButton("Название 'Выплаты'",  callback_data="adm_btn_ch_btn_payment")],
        [InlineKeyboardButton("Название 'Обучение'", callback_data="adm_btn_ch_btn_learn")],
        [InlineKeyboardButton("🔙 Назад",             callback_data="adm_back")],
    ])

def admin_links_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Ссылка «Выплаты»",          callback_data="adm_link_payment")],
        [InlineKeyboardButton("📚 Ссылка «Обучение»",         callback_data="adm_link_learn")],
        [InlineKeyboardButton("🔤 Названия кнопок канала",    callback_data="adm_channel_buttons")],
        [InlineKeyboardButton("🔙 Назад",                      callback_data="adm_back")],
    ])

def admin_templates_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Шаблон задания",  callback_data="adm_edit_template")],
        [InlineKeyboardButton("🔚 Шаблон закрытия", callback_data="adm_edit_closed_tpl")],
        [InlineKeyboardButton("🔙 Назад", callback_data="adm_back")],
    ])

def broadcast_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Всем пользователям",       callback_data="adm_bc_all")],
        [InlineKeyboardButton("👤 Конкретному пользователю", callback_data="adm_bc_one")],
        [InlineKeyboardButton("🔙 Назад", callback_data="adm_back")],
    ])

def admin_channels_kb():
    channels = get_channels()
    buttons  = [[InlineKeyboardButton(f"🗑 {ch['channel_name']}", callback_data=f"adm_delch_{ch['channel_id']}")] for ch in channels]
    buttons.append([InlineKeyboardButton("➕ Добавить канал", callback_data="adm_add_channel")])
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="adm_back")])
    return InlineKeyboardMarkup(buttons)

# ══════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════

def is_admin(uid): return uid in ADMIN_IDS

def build_task_text(platform, price, description):
    return get_setting("task_template").format(
        platform=platform, price=price, description=description)

def build_closed_text():
    return get_setting("closed_template")

def fmt_min(m):
    if m < 60: return f"{m} мин"
    h = m // 60
    return f"{h} ч" if m % 60 == 0 else f"{h} ч {m%60} мин"

async def close_task_in_channel(ctx, task):
    try:
        await ctx.bot.edit_message_text(
            chat_id=task["channel_id"], message_id=task["message_id"],
            text=build_closed_text(), reply_markup=None)
    except Exception as e:
        logger.warning(f"Edit failed: {e}")
    close_task(task["id"])

# ══════════════════════════════════════════════════════════════════
#  COMMANDS
# ══════════════════════════════════════════════════════════════════

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user.id, user.username, user.first_name)
    if not is_allowed(user.id) and not is_admin(user.id):
        await update.message.reply_text("🚫 У вас нет доступа.\nОбратитесь к администратору.")
        return
    ctx.user_data.clear()
    await update.message.reply_text(
        f"👋 Привет, *{user.first_name}*!\n\nВыберите действие:",
        parse_mode="Markdown", reply_markup=main_menu_kb())

async def admin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user.id, user.username, user.first_name)
    if is_admin(user.id):
        ctx.user_data.clear()
        await update.message.reply_text("🛠 *Панель администратора*", parse_mode="Markdown",
                                        reply_markup=admin_menu_kb())
    else:
        await update.message.reply_text("❌ Команда не найдена.")

# ══════════════════════════════════════════════════════════════════
#  CALLBACKS
# ══════════════════════════════════════════════════════════════════

async def callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    await q.answer()
    data = q.data
    uid  = q.from_user.id

    # ── Navigation ──────────────────────────────────────
    if data == "back_main":
        ctx.user_data.clear()
        await q.edit_message_text("Выберите действие:", reply_markup=main_menu_kb())
        return
    if data == "cancel":
        ctx.user_data.clear()
        await q.edit_message_text("❌ Отменено.", reply_markup=main_menu_kb())
        return

    # ── Post task ───────────────────────────────────────
    if data == "post_task":
        if not is_allowed(uid) and not is_admin(uid):
            await q.edit_message_text("🚫 Нет доступа."); return
        if not get_channels():
            await q.edit_message_text("⚠️ Каналы не настроены. Обратитесь к администратору.",
                                      reply_markup=back_kb()); return
        await q.edit_message_text("📌 Выберите платформу:", reply_markup=platform_kb()); return

    if data.startswith("platform_"):
        key = data[len("platform_"):]
        if key == "other":
            ctx.user_data.update({"platform_key": "other", "state": "wait_platform_text"})
            await q.edit_message_text("✏️ Введите название платформы:", reply_markup=cancel_kb())
        else:
            display = PLATFORM_DISPLAY.get(key, key)
            ctx.user_data.update({"platform_key": key, "platform": display})
            await q.edit_message_text(
                f"📌 Платформа: *{display}*\n\n💰 Выберите оплату:",
                parse_mode="Markdown", reply_markup=price_kb(key))
        return

    if data.startswith("price_"):
        price = data[len("price_"):]
        ctx.user_data.update({"price": price, "state": "wait_description"})
        plat  = ctx.user_data.get("platform", "—")
        await q.edit_message_text(
            f"📌 *{plat}* | 💰 *{price}*\n\n📝 Введите описание задания:",
            parse_mode="Markdown", reply_markup=cancel_kb()); return

    if data.startswith("channel_"):
        channel_id = data[len("channel_"):]
        ctx.user_data["selected_channel"] = channel_id
        plat  = ctx.user_data.get("platform", "—")
        price = ctx.user_data.get("price", "—")
        desc  = ctx.user_data.get("description", "—")
        preview = build_task_text(plat, price, desc)
        await q.edit_message_text(f"👁 *Предпросмотр:*\n\n{preview}",
                                  parse_mode="Markdown", reply_markup=confirm_post_kb()); return

    if data == "confirm_post":
        plat  = ctx.user_data.get("platform", "—")
        price = ctx.user_data.get("price", "—")
        desc  = ctx.user_data.get("description", "—")
        ch_id = ctx.user_data.get("selected_channel")
        uname = q.from_user.username
        if not uname:
            await q.edit_message_text(
                "⚠️ У вас нет username в Telegram.\n\nУстановите его: Настройки → Изменить профиль → Имя пользователя",
                reply_markup=back_kb()); return
        text = build_task_text(plat, price, desc)
        kb   = channel_post_kb(uname)
        try:
            msg = await ctx.bot.send_message(chat_id=ch_id, text=text, reply_markup=kb)
        except Exception as e:
            await q.edit_message_text(f"❌ Ошибка публикации: {e}\n\nПроверьте что бот — администратор канала.",
                                      reply_markup=back_kb()); return
        task_id = create_task(uid, uname, plat, price, desc, ch_id, msg.message_id)
        ctx.user_data["last_task_id"] = task_id
        ctx.user_data["state"] = "wait_autodel"
        await q.edit_message_text("✅ Задание опубликовано!\n\n⏱ Когда автоматически закрыть задание?",
                                  reply_markup=auto_delete_kb()); return

    if data.startswith("autodel_"):
        val     = data[len("autodel_"):]
        task_id = ctx.user_data.get("last_task_id")
        if task_id and val != "manual":
            mins    = int(val)
            auto_at = (datetime.utcnow() + timedelta(minutes=mins)).strftime("%Y-%m-%d %H:%M:%S")
            conn = get_conn()
            conn.execute("UPDATE tasks SET auto_delete_at=? WHERE id=?", (auto_at, task_id))
            conn.commit(); conn.close()
            await q.edit_message_text(f"⏰ Задание закроется через {fmt_min(mins)}.", reply_markup=back_kb())
        else:
            await q.edit_message_text("👌 Закроете вручную через «Удалить задание».", reply_markup=back_kb())
        ctx.user_data.clear(); return

    # ── Stats ───────────────────────────────────────────
    if data == "stats":
        tasks = get_active_tasks(uid)
        await q.edit_message_text(f"📊 *Ваша статистика*\n\n• Активных заданий: {len(tasks)}",
                                  parse_mode="Markdown", reply_markup=back_kb()); return

    # ── Delete task ─────────────────────────────────────
    if data == "delete_task_menu":
        kb = delete_tasks_kb(uid)
        if not kb:
            await q.edit_message_text("📭 Нет активных заданий.", reply_markup=back_kb()); return
        await q.edit_message_text("🗑 Выберите задание для закрытия:", reply_markup=kb); return

    if data.startswith("do_delete_"):
        task_id = int(data[len("do_delete_"):])
        task    = get_task(task_id)
        if task and task["user_id"] == uid and task["status"] == "active":
            await close_task_in_channel(ctx, task)
            await q.edit_message_text("✅ Задание закрыто.", reply_markup=back_kb())
        else:
            await q.edit_message_text("⚠️ Задание не найдено.", reply_markup=back_kb())
        return

    # ══════════════════════ ADMIN ══════════════════════

    if not is_admin(uid): return

    if data == "adm_back":
        await q.edit_message_text("🛠 *Панель администратора*", parse_mode="Markdown",
                                  reply_markup=admin_menu_kb()); return

    if data == "adm_stats":
        s = get_stats()
        await q.edit_message_text(
            f"📊 *Статистика*\n\n"
            f"👥 Всего пользователей: {s['total_users']}\n"
            f"✅ С доступом: {s['allowed_users']}\n"
            f"📋 Всего заданий: {s['total_tasks']}\n"
            f"🟢 Активных: {s['active_tasks']}",
            parse_mode="Markdown", reply_markup=back_kb("adm_back")); return

    if data == "adm_users":
        users = get_all_users()
        if not users:
            await q.edit_message_text("👥 Нет пользователей.", reply_markup=back_kb("adm_back")); return
        await q.edit_message_text("👥 *Пользователи*\nНажмите для смены доступа:",
                                  parse_mode="Markdown", reply_markup=admin_users_kb(users)); return

    if data.startswith("adm_toggle_"):
        target_id = int(data[len("adm_toggle_"):])
        users  = get_all_users()
        target = next((u for u in users if u["user_id"] == target_id), None)
        if target: set_allowed(target_id, not target["allowed"])
        users = get_all_users()
        await q.edit_message_text("👥 *Пользователи*\nНажмите для смены доступа:",
                                  parse_mode="Markdown", reply_markup=admin_users_kb(users)); return

    if data == "adm_add_user":
        ctx.user_data["state"] = "wait_add_user"
        await q.edit_message_text("➕ Введите @username пользователя:",
                                  reply_markup=back_kb("adm_back")); return

    if data == "adm_del_task":
        tasks = get_all_active_tasks()
        if not tasks:
            await q.edit_message_text("📭 Нет активных заданий.", reply_markup=back_kb("adm_back")); return
        await q.edit_message_text("🗑 Выберите задание:", reply_markup=admin_tasks_kb(tasks)); return

    if data.startswith("adm_close_"):
        task_id = int(data[len("adm_close_"):])
        task    = get_task(task_id)
        if task and task["status"] == "active":
            await close_task_in_channel(ctx, task)
            await q.edit_message_text("✅ Задание закрыто.", reply_markup=back_kb("adm_back"))
        else:
            await q.edit_message_text("⚠️ Не найдено.", reply_markup=back_kb("adm_back"))
        return

    if data == "adm_channels":
        await q.edit_message_text("📢 *Каналы*", parse_mode="Markdown",
                                  reply_markup=admin_channels_kb()); return

    if data == "adm_add_channel":
        ctx.user_data["state"] = "wait_add_channel_id"
        await q.edit_message_text("📢 Введите ID канала (например: `-1001234567890`):",
                                  reply_markup=back_kb("adm_back")); return

    if data.startswith("adm_delch_"):
        ch_id = data[len("adm_delch_"):]
        delete_channel(ch_id)
        await q.edit_message_text("✅ Канал удалён.", reply_markup=admin_channels_kb()); return

    if data == "adm_prices":
        await q.edit_message_text("💰 *Цены платформ*\nВыберите платформу:",
                                  parse_mode="Markdown", reply_markup=admin_prices_kb()); return

    if data.startswith("adm_price_"):
        key     = data[len("adm_price_"):]
        current = get_setting(f"prices_{key}", "")
        display = PLATFORM_DISPLAY.get(key, key)
        ctx.user_data.update({"state": "wait_edit_price", "edit_price_key": key})
        await q.edit_message_text(
            f"💰 *{display}*\n\nТекущие цены: `{current}`\n\n"
            "Введите новые цены через запятую:\n_Пример: 100₽,200₽,300₽_",
            parse_mode="Markdown", reply_markup=back_kb("adm_back")); return

    if data == "adm_bot_buttons":
        await q.edit_message_text("🔤 *Кнопки бота*:", parse_mode="Markdown",
                                  reply_markup=admin_bot_buttons_kb()); return

    if data == "adm_channel_buttons":
        await q.edit_message_text("🔤 *Кнопки канала*:", parse_mode="Markdown",
                                  reply_markup=admin_channel_buttons_kb()); return

    if data.startswith("adm_btn_"):
        key     = data[len("adm_btn_"):]
        current = get_setting(key, "")
        ctx.user_data.update({"state": "wait_edit_btn", "edit_btn_key": key})
        await q.edit_message_text(f"✏️ Текущий текст: *{current}*\n\nВведите новый:",
                                  parse_mode="Markdown", reply_markup=back_kb("adm_back")); return

    if data == "adm_links":
        pay = get_setting("link_payment", "") or "не задана"
        lrn = get_setting("link_learn",   "") or "не задана"
        await q.edit_message_text(
            f"🔗 *Ссылки кнопок канала*\n\n💳 Выплаты: `{pay}`\n📚 Обучение: `{lrn}`",
            parse_mode="Markdown", reply_markup=admin_links_kb()); return

    if data == "adm_link_payment":
        ctx.user_data.update({"state": "wait_edit_link", "edit_link_key": "link_payment"})
        await q.edit_message_text("💳 Введите ссылку для кнопки *Выплаты*:",
                                  parse_mode="Markdown", reply_markup=back_kb("adm_back")); return

    if data == "adm_link_learn":
        ctx.user_data.update({"state": "wait_edit_link", "edit_link_key": "link_learn"})
        await q.edit_message_text("📚 Введите ссылку для кнопки *Обучение*:",
                                  parse_mode="Markdown", reply_markup=back_kb("adm_back")); return

    if data == "adm_templates":
        await q.edit_message_text("📋 *Шаблоны текста*", parse_mode="Markdown",
                                  reply_markup=admin_templates_kb()); return

    if data == "adm_edit_template":
        current = get_setting("task_template", "")
        ctx.user_data["state"] = "wait_edit_template"
        await q.edit_message_text(
            f"📝 *Текущий шаблон:*\n\n`{current}`\n\n"
            "Переменные: `{platform}` `{price}` `{description}`",
            parse_mode="Markdown", reply_markup=back_kb("adm_back")); return

    if data == "adm_edit_closed_tpl":
        current = get_setting("closed_template", "")
        ctx.user_data["state"] = "wait_edit_closed_tpl"
        await q.edit_message_text(f"🔚 *Текущий шаблон закрытия:*\n\n`{current}`\n\nВведите новый текст:",
                                  parse_mode="Markdown", reply_markup=back_kb("adm_back")); return

    if data == "adm_broadcast":
        await q.edit_message_text("📨 *Рассылка* — выберите получателей:",
                                  parse_mode="Markdown", reply_markup=broadcast_kb()); return

    if data == "adm_bc_all":
        ctx.user_data["state"] = "wait_bc_msg_all"
        await q.edit_message_text("📨 Введите сообщение для *всех* пользователей:",
                                  parse_mode="Markdown", reply_markup=back_kb("adm_back")); return

    if data == "adm_bc_one":
        ctx.user_data["state"] = "wait_bc_username"
        await q.edit_message_text("👤 Введите @username получателя:",
                                  reply_markup=back_kb("adm_back")); return

# ══════════════════════════════════════════════════════════════════
#  MESSAGE HANDLER
# ══════════════════════════════════════════════════════════════════

async def message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user  = update.effective_user
    text  = (update.message.text or "").strip()
    state = ctx.user_data.get("state")

    if not is_allowed(user.id) and not is_admin(user.id):
        await update.message.reply_text("🚫 Нет доступа."); return

    # ── Platform text (Другое) ──────────────────────────
    if state == "wait_platform_text":
        ctx.user_data.update({"platform": text, "state": "wait_price_text"})
        await update.message.reply_text(f"✅ Платформа: *{text}*\n\n💰 Введите цену:",
                                        parse_mode="Markdown", reply_markup=cancel_kb()); return

    if state == "wait_price_text":
        ctx.user_data.update({"price": text, "state": "wait_description"})
        plat = ctx.user_data.get("platform", "—")
        await update.message.reply_text(f"📌 *{plat}* | 💰 *{text}*\n\n📝 Введите описание:",
                                        parse_mode="Markdown", reply_markup=cancel_kb()); return

    # ── Description ─────────────────────────────────────
    if state == "wait_description":
        ctx.user_data["description"] = text
        channels = get_channels()
        plat  = ctx.user_data.get("platform", "—")
        price = ctx.user_data.get("price", "—")
        if len(channels) == 1:
            ctx.user_data["selected_channel"] = channels[0]["channel_id"]
            preview = build_task_text(plat, price, text)
            await update.message.reply_text(f"👁 *Предпросмотр:*\n\n{preview}",
                                            parse_mode="Markdown", reply_markup=confirm_post_kb())
        else:
            await update.message.reply_text("📢 Выберите канал:", reply_markup=channel_select_kb())
        return

    # ── Admin: add user ─────────────────────────────────
    if state == "wait_add_user":
        if not is_admin(user.id): return
        uname = text.lstrip("@")
        add_user_by_username(uname)
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ @{uname} добавлен и получил доступ.",
                                        reply_markup=admin_menu_kb()); return

    # ── Admin: add channel ──────────────────────────────
    if state == "wait_add_channel_id":
        if not is_admin(user.id): return
        ctx.user_data.update({"new_channel_id": text, "state": "wait_add_channel_name"})
        await update.message.reply_text("✏️ Введите название канала:"); return

    if state == "wait_add_channel_name":
        if not is_admin(user.id): return
        ch_id = ctx.user_data.get("new_channel_id")
        add_channel(ch_id, text)
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Канал «{text}» добавлен.",
                                        reply_markup=admin_menu_kb()); return

    # ── Admin: edit prices ──────────────────────────────
    if state == "wait_edit_price":
        if not is_admin(user.id): return
        key = ctx.user_data.get("edit_price_key")
        set_setting(f"prices_{key}", text)
        display = PLATFORM_DISPLAY.get(key, key)
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Цены для *{display}*: `{text}`",
                                        parse_mode="Markdown", reply_markup=admin_menu_kb()); return

    # ── Admin: edit button text ─────────────────────────
    if state == "wait_edit_btn":
        if not is_admin(user.id): return
        key = ctx.user_data.get("edit_btn_key")
        set_setting(key, text)
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Кнопка обновлена: *{text}*",
                                        parse_mode="Markdown", reply_markup=admin_menu_kb()); return

    # ── Admin: edit link ────────────────────────────────
    if state == "wait_edit_link":
        if not is_admin(user.id): return
        key = ctx.user_data.get("edit_link_key")
        set_setting(key, text)
        label = "Выплаты" if key == "link_payment" else "Обучение"
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Ссылка «{label}» обновлена.",
                                        reply_markup=admin_menu_kb()); return

    # ── Admin: edit templates ───────────────────────────
    if state == "wait_edit_template":
        if not is_admin(user.id): return
        set_setting("task_template", text)
        ctx.user_data.clear()
        await update.message.reply_text("✅ Шаблон задания обновлён.", reply_markup=admin_menu_kb()); return

    if state == "wait_edit_closed_tpl":
        if not is_admin(user.id): return
        set_setting("closed_template", text)
        ctx.user_data.clear()
        await update.message.reply_text("✅ Шаблон закрытия обновлён.", reply_markup=admin_menu_kb()); return

    # ── Admin: broadcast all ────────────────────────────
    if state == "wait_bc_msg_all":
        if not is_admin(user.id): return
        users  = get_allowed_users()
        sent = failed = 0
        for u in users:
            try:
                await ctx.bot.send_message(chat_id=u["user_id"], text=f"📢 {text}")
                sent += 1
            except:
                failed += 1
        ctx.user_data.clear()
        await update.message.reply_text(
            f"✅ Рассылка завершена!\n✉️ Отправлено: {sent}\n❌ Ошибок: {failed}",
            reply_markup=admin_menu_kb()); return

    if state == "wait_bc_username":
        if not is_admin(user.id): return
        ctx.user_data.update({"bc_target": text.lstrip("@"), "state": "wait_bc_msg_one"})
        await update.message.reply_text(f"✉️ Введите сообщение для @{text.lstrip('@')}:"); return

    if state == "wait_bc_msg_one":
        if not is_admin(user.id): return
        target_uname = ctx.user_data.get("bc_target")
        target = get_user_by_username(target_uname)
        if target and target.get("user_id") and target["user_id"] > 0:
            try:
                await ctx.bot.send_message(chat_id=target["user_id"], text=f"📢 {text}")
                await update.message.reply_text(f"✅ Сообщение отправлено @{target_uname}.",
                                                reply_markup=admin_menu_kb())
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка: {e}", reply_markup=admin_menu_kb())
        else:
            await update.message.reply_text(
                f"⚠️ @{target_uname} не найден или не запускал бота.",
                reply_markup=admin_menu_kb())
        ctx.user_data.clear(); return

    await update.message.reply_text("Используйте кнопки меню ↓", reply_markup=main_menu_kb())

# ══════════════════════════════════════════════════════════════════
#  AUTO-DELETE JOB
# ══════════════════════════════════════════════════════════════════

async def auto_delete_job(context: ContextTypes.DEFAULT_TYPE):
    for task in get_tasks_to_auto_delete():
        logger.info(f"Auto-closing task #{task['id']}")
        await close_task_in_channel(context, task)

# ══════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.job_queue.run_repeating(auto_delete_job, interval=60, first=10)
    logger.info("Bot started")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
