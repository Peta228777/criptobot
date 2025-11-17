import asyncio
import logging
import random
import sqlite3
import csv
from datetime import datetime, timedelta

import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, FSInputFile

# ==========================
# НАСТРОЙКИ
# ==========================

BOT_TOKEN = "8330326273:AAEuWSwkqi7ypz1LZL4LXRr2jSMpKjGc36k"
ADMIN_ID = 682938643

TRONGRID_API_KEY = "b33b8d65-10c9-4f7b-99e0-ab47f3bbb60f"
WALLET_ADDRESS = "TSY9xf24bQ3Kbd1Njp2w4pEEoqJow1nfpr"
CHANNEL_ID = -1003464806734   # закрытый канал

PRICE_USDT = 50               # базовая цена подписки
SUB_DAYS = 30                 # срок подписки в днях

DB_PATH = "database.db"

EXPIRE_CHECK_INTERVAL = 1800  # 30 минут
PAYMENT_SCAN_INTERVAL = 60    # 1 минута


# ==========================
# ИНИЦИАЛИЗАЦИЯ
# ==========================

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# Таблица подписок
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS subscriptions(
        user_id INTEGER PRIMARY KEY,
        unique_price REAL,
        paid INTEGER,
        start_date TEXT,
        end_date TEXT,
        tx_amount REAL,
        tx_time TEXT
    );
    """
)

# Таблица всех пользователей
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS users(
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_seen TEXT,
        last_active TEXT
    );
    """
)

conn.commit()

# Временное хранение уникальных сумм
user_unique_price: dict[int, float] = {}


# ==========================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================

def is_admin(message: types.Message) -> bool:
    return message.from_user.id == ADMIN_ID


def save_user(user_id: int, username: str | None):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    cursor.execute(
        """
        INSERT INTO users (user_id, username, first_seen, last_active)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET last_active = excluded.last_active
        """,
        (user_id, username or "", now, now),
    )
    conn.commit()


def get_subscription(user_id: int):
    cursor.execute(
        """
        SELECT user_id, unique_price, paid, start_date, end_date, tx_amount, tx_time
        FROM subscriptions
        WHERE user_id = ?
        """,
        (user_id,),
    )
    return cursor.fetchone()


def save_payment(user_id: int, unique_price: float, tx_amount: float):
    now = datetime.now()
    end = now + timedelta(days=SUB_DAYS)

    cursor.execute(
        """
        INSERT OR REPLACE INTO subscriptions
        (user_id, unique_price, paid, start_date, end_date, tx_amount, tx_time)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            unique_price,
            1,
            now.strftime("%Y-%m-%d %H:%M"),
            end.strftime("%Y-%m-%d %H:%M"),
            tx_amount,
            now.strftime("%Y-%m-%d %H:%M"),
        ),
    )
    conn.commit()


def set_paid(user_id: int, paid: int):
    cursor.execute("UPDATE subscriptions SET paid = ? WHERE user_id = ?", (paid, user_id))
    conn.commit()


async def log_to_admin(text: str):
    try:
        await bot.send_message(ADMIN_ID, f"🛠 LOG:\n{text}")
    except Exception as e:
        logging.error(f"Не удалось отправить лог админу: {e}")


# ==========================
# ПРОВЕРКА TRONGRID
# ==========================

async def check_trx_payment(user_id: int) -> bool:
    """
    Проверяем, пришёл ли USDT с нужной уникальной суммой.
    """
    target_amount = user_unique_price.get(user_id)
    if target_amount is None:
        return False

    url = f"https://api.trongrid.io/v1/accounts/{WALLET_ADDRESS}/transactions/trc20"
    headers = {"TRON-PRO-API-KEY": TRONGRID_API_KEY}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            data = await resp.json()

    for tx in data.get("data", []):
        try:
            raw_value = tx.get("value") or tx.get("amount")
            if raw_value is None:
                continue
            amount = int(raw_value) / 1_000_000  # 6 знаков
            if abs(amount - target_amount) < 0.0000001:
                return True
        except Exception:
            continue

    return False


# ==========================
# КЛАВИАТУРЫ
# ==========================

def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📌 О боте"), KeyboardButton(text="📈 Получить сигналы")],
            [KeyboardButton(text="💰 Тарифы"), KeyboardButton(text="📞 Поддержка")],
            [KeyboardButton(text="👤 Профиль")],
        ],
        resize_keyboard=True,
    )


def admin_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👥 Все пользователи")],
            [KeyboardButton(text="📊 Все подписчики")],
            [KeyboardButton(text="🔥 Активные подписчики")],
            [KeyboardButton(text="⏳ Истёкшие")],
            [KeyboardButton(text="🧾 История платежей")],
            [KeyboardButton(text="📤 Экспорт CSV")],
        ],
        resize_keyboard=True,
    )


# ==========================
# ОБЫЧНЫЕ КОМАНДЫ
# ==========================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    save_user(message.from_user.id, message.from_user.username)

    row = get_subscription(message.from_user.id)
    now = datetime.now()

    if row:
        _, _, paid, _, end_date, _, _ = row
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d %H:%M")
        except Exception:
            end_dt = now

        if paid == 1 and end_dt > now:
            txt = (
                "🔥 У тебя уже есть активная подписка!\n"
                f"Действует до: *{end_date}*\n\n"
                "Можешь заходить в закрытый канал и получать сигналы 📈"
            )
            await message.answer(txt, parse_mode="Markdown")

    text = (
        "👋 *Добро пожаловать в Crypto Signals Bot!*\n\n"
        "Здесь ты сможешь получать премиальные сигналы по крипте.\n\n"
        "Выбирай действие ниже 👇"
    )
    await message.answer(text, reply_markup=main_keyboard(), parse_mode="Markdown")


@dp.message(lambda m: m.text == "📌 О боте")
async def about(message: types.Message):
    text = (
        "🤖 *Crypto Signals Bot*\n\n"
        "📈 Сигналы по BTC/ETH/ALT\n"
        "⏱ Мгновенные уведомления\n"
        "💰 Работа с USDT (TRC-20)\n\n"
        "Нажми «📈 Получить сигналы», чтобы оформить подписку."
    )
    await message.answer(text, parse_mode="Markdown")


@dp.message(lambda m: m.text == "💰 Тарифы")
async def tariffs(message: types.Message):
    text = (
        "💰 *Тарифы:*\n\n"
        f"📅 1 месяц — {PRICE_USDT} USDT\n"
        f"📅 2 месяца — {PRICE_USDT + 30} USDT (со скидкой)\n\n"
        "Оплата в USDT (TRC-20)."
    )
    await message.answer(text, parse_mode="Markdown")


@dp.message(lambda m: m.text == "📞 Поддержка")
async def support(message: types.Message):
    text = (
        "📞 *Поддержка:*\n\n"
        "Если есть вопросы — напиши:\n"
        "@your_support_username"
    )
    await message.answer(text, parse_mode="Markdown")


@dp.message(lambda m: m.text == "👤 Профиль")
async def profile(message: types.Message):
    row = get_subscription(message.from_user.id)
    now = datetime.now()

    if not row:
        return await message.answer(
            "У тебя пока нет активной подписки.\nНажми «📈 Получить сигналы», чтобы оформить.",
        )

    user_id, unique_price, paid, start_date, end_date, tx_amount, tx_time = row

    try:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d %H:%M")
    except Exception:
        end_dt = now

    status = "🟢 Активна" if paid == 1 and end_dt > now else "🔴 Не активна"
    days_left = max((end_dt - now).days, 0)

    text = (
        "👤 *Твой профиль:*\n\n"
        f"ID: `{user_id}`\n"
        f"Статус: {status}\n"
        f"Начало: {start_date}\n"
        f"Окончание: {end_date}\n"
        f"Осталось дней: {days_left}\n"
        f"Последний платёж: {tx_amount} USDT\n"
        f"Время платежа: {tx_time}\n"
    )
    await message.answer(text, parse_mode="Markdown")


# ==========================
# ОПЛАТА / УНИКАЛЬНАЯ СУММА
# ==========================

@dp.message(lambda m: m.text == "📈 Получить сигналы")
async def get_signals(message: types.Message):
    unique_tail = random.randint(1, 999)
    unique_price = float(f"{PRICE_USDT}.{unique_tail:03d}")
    user_unique_price[message.from_user.id] = unique_price

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔄 Проверить оплату")],
            [KeyboardButton(text="⬅️ В главное меню")],
        ],
        resize_keyboard=True,
    )

    text = (
        "🚀 *Оплата подписки*\n\n"
        f"1️⃣ Отправь *РОВНО* `{unique_price}` USDT (TRC-20)\n"
        f"2️⃣ На адрес:\n`{WALLET_ADDRESS}`\n\n"
        "⚠️ Важно: сумма должна совпасть до последнего знака, "
        "иначе бот не найдёт платёж.\n\n"
        "После отправки нажми «🔄 Проверить оплату»."
    )
    await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")


@dp.message(lambda m: m.text == "🔄 Проверить оплату")
async def check_payment_button(message: types.Message):
    await message.answer("⏳ Идёт проверка оплаты, подожди 5–15 секунд...")

    if await check_trx_payment(message.from_user.id):
        amount = user_unique_price.get(message.from_user.id)
        if amount is None:
            return await message.answer("Платёж найден, но уникальная сумма не найдена. Напиши админу.")

        save_payment(message.from_user.id, amount, amount)
        user_unique_price.pop(message.from_user.id, None)

        await message.answer("✅ Платёж подтверждён! Выдаю доступ в канал...")

        try:
            invite = await bot.create_chat_invite_link(CHANNEL_ID, member_limit=1)
            await message.answer(f"🔗 Вход в приватный канал:\n{invite.invite_link}")
            await log_to_admin(f"Новая подписка: {message.from_user.id} — {amount} USDT")
        except Exception as e:
            await message.answer(
                "Оплата прошла, но не удалось создать ссылку автоматически.\n"
                "Напиши админу, он выдаст доступ вручную."
            )
            await log_to_admin(f"Ошибка создания ссылки для {message.from_user.id}: {e}")
    else:
        await message.answer(
            "❌ Платёж пока не найден.\n"
            "Если ты только что отправил USDT — подожди 1–2 минуты и нажми ещё раз.\n"
            "Если проблема не пропадает — напиши в поддержку."
        )


@dp.message(lambda m: m.text == "⬅️ В главное меню")
async def back_to_menu(message: types.Message):
    await message.answer("🏠 Главное меню:", reply_markup=main_keyboard())


# ==========================
# АДМИН-ПАНЕЛЬ
# ==========================

@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if not is_admin(message):
        return await message.answer("🚫 У тебя нет доступа.")

    await message.answer("👨‍💻 Админ-панель", reply_markup=admin_keyboard())


@dp.message(lambda m: m.text == "👥 Все пользователи")
async def admin_all_users(message: types.Message):
    if not is_admin(message):
        return

    cursor.execute("SELECT * FROM users")
    rows = cursor.fetchall()

    if not rows:
        return await message.answer("Пока ни один пользователь не открывал бота.")

    text = "👥 *Все пользователи:*\n\n"
    for user_id, username, first_seen, last_active in rows:
        text += (
            f"🧑 ID: `{user_id}`\n"
            f"🔗 Username: @{username if username else 'нет'}\n"
            f"📅 Впервые: {first_seen}\n"
            f"⏱ Активность: {last_active}\n"
            "─────────────────────\n"
        )

    await message.answer(text, parse_mode="Markdown")


@dp.message(lambda m: m.text == "📊 Все подписчики")
async def admin_all_subs(message: types.Message):
    if not is_admin(message):
        return

    cursor.execute("SELECT * FROM subscriptions")
    rows = cursor.fetchall()

    if not rows:
        return await message.answer("Пока нет подписчиков.")

    text = "📄 *Список подписчиков:*\n\n"
    for r in rows:
        user_id, unique_price, paid, start_date, end_date, tx_amount, tx_time = r
        status = "🟢 Активна" if paid == 1 else "🔴 Не активна"
        text += (
            f"👤 ID: `{user_id}`\n"
            f"💵 Уникальная цена: {unique_price}\n"
            f"💰 Оплачено: {tx_amount} USDT\n"
            f"📅 Старт: {start_date}\n"
            f"⏳ Конец: {end_date}\n"
            f"📌 Статус: {status}\n"
            "─────────────────────\n"
        )

    await message.answer(text, parse_mode="Markdown")


@dp.message(lambda m: m.text == "🔥 Активные подписчики")
async def admin_active_subs(message: types.Message):
    if not is_admin(message):
        return

    cursor.execute("SELECT * FROM subscriptions WHERE paid = 1")
    rows = cursor.fetchall()

    if not rows:
        return await message.answer("Нет активных подписок.")

    text = "🔥 *Активные подписчики:*\n\n"
    for r in rows:
        user_id, _, _, _, end_date, tx_amount, _ = r
        text += (
            f"👤 ID: `{user_id}`\n"
            f"📅 До: {end_date}\n"
            f"💰 Оплачено: {tx_amount} USDT\n"
            "─────────────────────\n"
        )

    await message.answer(text, parse_mode="Markdown")


@dp.message(lambda m: m.text == "⏳ Истёкшие")
async def admin_expired_subs(message: types.Message):
    if not is_admin(message):
        return

    now = datetime.now()
    cursor.execute("SELECT * FROM subscriptions")
    rows = cursor.fetchall()

    expired = []
    for r in rows:
        user_id, unique_price, paid, start_date, end_date, tx_amount, tx_time = r
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d %H:%M")
        except Exception:
            continue
        if end_dt < now:
            expired.append(r)

    if not expired:
        return await message.answer("Истёкших подписок нет.")

    text = "⏳ *Истёкшие подписки:*\n\n"
    for r in expired:
        user_id, _, _, start_date, end_date, _, _ = r
        text += (
            f"👤 ID: `{user_id}`\n"
            f"📅 Старт: {start_date}\n"
            f"⏳ Истекла: {end_date}\n"
            "─────────────────────\n"
        )

    await message.answer(text, parse_mode="Markdown")


@dp.message(lambda m: m.text == "🧾 История платежей")
async def admin_pay_history(message: types.Message):
    if not is_admin(message):
        return

    cursor.execute("SELECT * FROM subscriptions WHERE tx_amount > 0 ORDER BY tx_time DESC")
    rows = cursor.fetchall()

    if not rows:
        return await message.answer("История платежей пуста.")

    text = "🧾 *История платежей:*\n\n"
    for r in rows:
        user_id, _, _, _, _, tx_amount, tx_time = r
        text += (
            f"👤 ID: `{user_id}`\n"
            f"💰 {tx_amount} USDT\n"
            f"⏱ {tx_time}\n"
            "─────────────────────\n"
        )

    await message.answer(text, parse_mode="Markdown")


@dp.message(lambda m: m.text == "📤 Экспорт CSV")
async def admin_export_csv(message: types.Message):
    if not is_admin(message):
        return

    cursor.execute("SELECT * FROM subscriptions")
    rows = cursor.fetchall()

    if not rows:
        return await message.answer("Нет данных для экспорта.")

    filename = "subscriptions_export.csv"
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["user_id", "unique_price", "paid", "start_date", "end_date", "tx_amount", "tx_time"])
        for row in rows:
            writer.writerow(row)

    doc = FSInputFile(filename)
    await message.answer_document(doc, caption="Экспорт подписчиков.")


# ==========================
# АДМИН-КОМАНДЫ: EXTEND / BAN / UNBAN
# ==========================

@dp.message(Command("extend"))
async def cmd_extend(message: types.Message):
    if not is_admin(message):
        return

    parts = message.text.split()
    if len(parts) < 3:
        return await message.answer("Использование: /extend <user_id> <days>")

    try:
        user_id = int(parts[1])
        days = int(parts[2])
    except ValueError:
        return await message.answer("user_id и days должны быть числами.")

    now = datetime.now()
    row = get_subscription(user_id)

    if row:
        _, unique_price, paid, start_date, end_date, tx_amount, tx_time = row
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d %H:%M")
        except Exception:
            end_dt = now
        if end_dt < now:
            end_dt = now
        new_end = end_dt + timedelta(days=days)
    else:
        unique_price = float(PRICE_USDT)
        paid = 1
        start_date = now.strftime("%Y-%m-%d %H:%M")
        new_end = now + timedelta(days=days)
        tx_amount = 0.0
        tx_time = now.strftime("%Y-%m-%d %H:%M")

    cursor.execute(
        """
        INSERT OR REPLACE INTO subscriptions
        (user_id, unique_price, paid, start_date, end_date, tx_amount, tx_time)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            unique_price,
            1,
            start_date,
            new_end.strftime("%Y-%m-%d %H:%M"),
            tx_amount,
            tx_time,
        ),
    )
    conn.commit()

    await message.answer(
        f"✅ Подписка пользователя {user_id} продлена/создана до {new_end.strftime('%Y-%m-%d %H:%M')}"
    )
    await log_to_admin(f"EXTEND: {user_id} +{days} дней")


@dp.message(Command("ban"))
async def cmd_ban(message: types.Message):
    if not is_admin(message):
        return

    parts = message.text.split()
    if len(parts) < 2:
        return await message.answer("Использование: /ban <user_id>")

    try:
        user_id = int(parts[1])
    except ValueError:
        return await message.answer("user_id должен быть числом.")

    set_paid(user_id, 0)
    try:
        await bot.ban_chat_member(CHANNEL_ID, user_id)
    except Exception:
        pass

    await message.answer(f"⛔ Пользователь {user_id} заблокирован и подписка отключена.")
    await log_to_admin(f"BAN: {user_id}")


@dp.message(Command("unban"))
async def cmd_unban(message: types.Message):
    if not is_admin(message):
        return

    parts = message.text.split()
    if len(parts) < 2:
        return await message.answer("Использование: /unban <user_id>")

    try:
        user_id = int(parts[1])
    except ValueError:
        return await message.answer("user_id должен быть числом.")

    try:
        await bot.unban_chat_member(CHANNEL_ID, user_id)
    except Exception:
        pass

    await message.answer(f"✅ Пользователь {user_id} разбанен в канале.")
    await log_to_admin(f"UNBAN: {user_id}")


# ==========================
# ФОНОВЫЕ ЗАДАЧИ
# ==========================

async def periodic_expire_check():
    await asyncio.sleep(5)
    while True:
        now = datetime.now()
        cursor.execute("SELECT * FROM subscriptions WHERE paid = 1")
        rows = cursor.fetchall()

        for r in rows:
            user_id, _, _, _, end_date, _, _ = r
            try:
                end_dt = datetime.strptime(end_date, "%Y-%m-%d %H:%M")
            except Exception:
                continue

            if end_dt < now:
                set_paid(user_id, 0)
                try:
                    await bot.ban_chat_member(CHANNEL_ID, user_id)
                    await bot.unban_chat_member(CHANNEL_ID, user_id)
                except Exception:
                    pass

                try:
                    await bot.send_message(
                        user_id,
                        "⚠️ Твоя подписка истекла. Для продления — оформи оплату снова в боте.",
                    )
                except Exception:
                    pass

                await log_to_admin(f"EXPIRE: подписка {user_id} истекла.")

        await asyncio.sleep(EXPIRE_CHECK_INTERVAL)


async def periodic_auto_check_payments():
    await asyncio.sleep(10)
    while True:
        if user_unique_price:
            for user_id in list(user_unique_price.keys()):
                try:
                    if await check_trx_payment(user_id):
                        amount = user_unique_price.get(user_id)
                        save_payment(user_id, amount, amount)
                        user_unique_price.pop(user_id, None)

                        try:
                            invite = await bot.create_chat_invite_link(CHANNEL_ID, member_limit=1)
                            await bot.send_message(
                                user_id,
                                f"✅ Оплата найдена автоматически!\nВот ссылка в канал:\n{invite.invite_link}",
                            )
                        except Exception as e:
                            await bot.send_message(
                                user_id,
                                "Оплата прошла, но не удалось создать ссылку автоматически.\n"
                                "Напиши админу, он выдаст доступ.",
                            )
                            await log_to_admin(f"AUTO-LINK ERROR {user_id}: {e}")

                        await log_to_admin(f"AUTO-PAYMENT: {user_id} — {amount} USDT")
                except Exception as e:
                    logging.error(f"Ошибка в periodic_auto_check_payments: {e}")

        await asyncio.sleep(PAYMENT_SCAN_INTERVAL)


# ==========================
# ЗАПУСК
# ==========================

async def main():
    asyncio.create_task(periodic_expire_check())
    asyncio.create_task(periodic_auto_check_payments())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
