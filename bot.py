import logging
import sqlite3
from datetime import datetime
import os
from typing import List, Tuple

from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.dispatcher.filters import Text
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

# ==========================
# НАСТРОЙКИ
# ==========================

# Либо берём из переменных окружения (на хостинге),
# либо можно временно прописать прямо тут.
BOT_TOKEN = os.getenv("BOT_TOKEN", "8330326273:AAEuWSwkqi7ypz1LZL4LXRr2jSMpKjGc36k")
ADMIN_ID = int(os.getenv("ADMIN_ID", "682938643"))

# Цена и реферальная система
PRODUCT_PRICE_USD = 100           # цена доступа
REF_L1_PERCENT = 50               # первый уровень (50% = 50$)
REF_L2_PERCENT = 10               # второй уровень (10% = 10$)

# Реквизиты для оплаты (замени на свои)
PAYMENT_DETAILS = (
    "💸 *Реквизиты для оплаты доступа:*\n\n"
    f"Сумма: *{PRODUCT_PRICE_USD} USDT* (или эквивалент в $)\n"
    "Сеть: *TRC-20*\n"
    "Кошелёк: `TSY9xf24bQ3Kbd1Njp2w4pEEoqJow1nfpr`\n\n"
    "После оплаты нажми кнопку *«✅ Я оплатил»* и дождись подтверждения от админа.\n"
    "Если что-то пошло не так — сразу пиши в поддержку."
)

SUPPORT_CONTACT = "@your_support_username"  # замени на свой @

DB_PATH = "database.db"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, parse_mode="Markdown")
dp = Dispatcher(bot)

# ==========================
# БАЗА ДАННЫХ
# ==========================

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# Пользователи
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        first_seen TEXT,
        last_active TEXT,
        referrer_id INTEGER,
        balance REAL DEFAULT 0,
        level1_earned REAL DEFAULT 0,
        level2_earned REAL DEFAULT 0,
        total_withdrawn REAL DEFAULT 0
    );
    """
)

# Покупки (заявки на оплату доступа)
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS purchases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount REAL,
        status TEXT,
        created_at TEXT,
        confirmed_at TEXT
    );
    """
)

# Реферальные начисления
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS referral_earnings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_id INTEGER,
        referred_id INTEGER,
        level INTEGER,
        bonus REAL,
        created_at TEXT
    );
    """
)

conn.commit()


def save_user(user: types.User, referrer_id: int = None):
    """Создаём/обновляем пользователя в базе."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor.execute(
        """
        INSERT INTO users (user_id, username, full_name, first_seen, last_active, referrer_id)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            full_name = excluded.full_name,
            last_active = excluded.last_active
        """,
        (
            user.id,
            user.username or "",
            f"{user.first_name or ''} {user.last_name or ''}".strip(),
            now,
            now,
            referrer_id,
        ),
    )
    conn.commit()


def get_user(user_id: int):
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    return cursor.fetchone()


def create_purchase(user_id: int, amount: float):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor.execute(
        """
        INSERT INTO purchases (user_id, amount, status, created_at, confirmed_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, amount, "pending", now, "")
    )
    conn.commit()


def confirm_purchase(purchase_id: int):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor.execute(
        "UPDATE purchases SET status = 'confirmed', confirmed_at = ? WHERE id = ?",
        (now, purchase_id),
    )
    conn.commit()


def add_referral_bonus(referrer_id: int, referred_id: int, level: int, bonus: float):
    """Добавляем реферальный бонус и обновляем баланс пользователя."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor.execute(
        """
        INSERT INTO referral_earnings (referrer_id, referred_id, level, bonus, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (referrer_id, referred_id, level, bonus, now),
    )

    if level == 1:
        cursor.execute(
            "UPDATE users SET balance = balance + ?, level1_earned = level1_earned + ? WHERE user_id = ?",
            (bonus, bonus, referrer_id),
        )
    elif level == 2:
        cursor.execute(
            "UPDATE users SET balance = balance + ?, level2_earned = level2_earned + ? WHERE user_id = ?",
            (bonus, bonus, referrer_id),
        )

    conn.commit()


# ==========================
# ОБУЧЕНИЕ: ТРЕЙДИНГ
# ==========================

TRADING_LESSONS: List[Tuple[str, str]] = [
    (
        "Блок 1. Основа трейдинга",
        "🔹 *Что такое трейдинг*\n\n"
        "Трейдинг — это не казино и не угадайка. Это работа с вероятностями, "
        "рисками и понятными правилами.\n\n"
        "В этом блоке ты поймёшь:\n"
        "• чем трейдинг отличается от инвестиций\n"
        "• какие бывают типы ордеров\n"
        "• что такое риск-менеджмент и почему без него ВСЕ сливают\n\n"
        "Главная мысль: *твоя задача — не угадать рынок, а научиться управлять риском*."
    ),
    (
        "Блок 2. Психология и дисциплина",
        "🧠 *Психология трейдинга*\n\n"
        "Большинство сливают не потому что стратегия плохая, а потому что:\n"
        "• увеличивают лот 'на эмоциях'\n"
        "• отыгрываются после убытка\n"
        "• входят в рынок без плана\n\n"
        "Мы делаем упор на:\n"
        "• чёткий торговый план\n"
        "• фиксированный риск на сделку\n"
        "• отсутствие 'угадываний'\n\n"
        "Твоя сила — в дисциплине, а не в гениальности."
    ),
    (
        "Блок 3. Работа с сигналами",
        "📈 *Как работать с сигналами грамотно*\n\n"
        "Сигналы — это подсказка, а не волшебная палочка.\n\n"
        "Твоя задача:\n"
        "• не заходить 'на всё депо'\n"
        "• соблюдать риск 1–3% от депозита на сделку\n"
        "• не открывать 10 сделок одновременно, если депозит маленький\n\n"
        "Сигналы + риск-менеджмент + психология = работающая система."
    ),
    (
        "Блок 4. Путь к стабильности",
        "🚀 *Как прийти к стабильному результату*\n\n"
        "Не жди, что ты станешь миллионером за неделю.\n\n"
        "Реальный путь:\n"
        "• 1–4 недели — базовое понимание, адаптация к стратегии\n"
        "• 1–3 месяца — первые стабильные результаты\n"
        "• 6–12 месяцев — формирование сильного скилла\n\n"
        "Мы даём тебе:\n"
        "• базу и структуру\n"
        "• сигналы\n"
        "• систему заработка на рефералах\n\n"
        "Твоя задача — действовать."
    ),
]

# ==========================
# ОБУЧЕНИЕ: ТРАФИК ИЗ TIKTOK
# ==========================

TRAFFIC_LESSONS: List[Tuple[str, str]] = [
    (
        "Урок 1. Суть схемы: TikTok → Telegram → Деньги",
        "TikTok — это бесплатный поток людей.\n\n"
        "Схема проста:\n"
        "1) Ты снимаешь короткие видео с сильными триггерами: деньги, свобода, "
        "изменение жизни.\n"
        "2) В каждом видео ведёшь людей в Telegram-бота.\n"
        "3) В боте человек видит систему: обучение, сигналы, партнёрку 50%/10%.\n"
        f"4) Он покупает доступ за *{PRODUCT_PRICE_USD}$*, и ты забираешь *{PRODUCT_PRICE_USD * REF_L1_PERCENT / 100:.0f}$* как партнёр.\n"
        "5) Если он приводит других — ты забираешь ещё 10% со второго уровня.\n\n"
        "Это не сказка, а воронка: TikTok → бот → продажа → рефералы."
    ),
    (
        "Урок 2. Оформление профиля TikTok",
        "Оформление — это твой первый фильтр.\n\n"
        "Рекомендуется:\n"
        "• Имя: что-то в стиле 'Крипта и доход', 'Путь к $300 в день'.\n"
        "• Аватар: твоя адекватная фотка или логотип проекта.\n"
        "• Описание профиля:\n"
        "  'Обучаю зарабатывать на крипте и партнёрке.\n"
        "   Купил доступ один раз → зарабатываешь постоянно.\n"
        "   Ссылка на систему ниже 👇'\n\n"
        "Главное — сразу дать человеку понять, что ты про ДЕНЬГИ и СИСТЕМУ."
    ),
    (
        "Урок 3. Какие видео заходят лучше всего",
        "Тебе не нужно быть блогером.\n\n"
        "Типы роликов, которые работают:\n"
        "• Боль: 'Работаешь по 10 часов, а денег всё равно нет?'\n"
        "• Возможность: 'Вот схема, как люди делают +50$ за одного человека.'\n"
        "• Схема: 'TikTok → Telegram → заработок 2 источниками.'\n"
        "• Соцдоказательства: скрин дохода, отзыв, история.\n\n"
        "Старайся, чтобы в каждом ролике была эмоция и призыв: 'Ссылка в шапке профиля.'"
    ),
    (
        "Урок 4. Видео без лица",
        "Если не хочешь светиться — это не проблема.\n\n"
        "Форматы контента без лица:\n"
        "• Запись экрана + твой голос.\n"
        "• Текст на фоне + музыка (через CapCut).\n"
        "• Картинки с текстом + закадровый голос.\n\n"
        "Важно не то, как ты выглядишь, а что ты говоришь и насколько это цепляет."
    ),
    (
        "Урок 5. Как правильно вести на ссылку",
        "TikTok не любит прямое слово 'telegram'.\n\n"
        "Делай так:\n"
        "• Ставь ссылку на бота в шапку профиля.\n"
        "• В видео говори: 'Смотри ссылку в профиле' или 'Ссылка в закрепе'.\n"
        "• В комментариях можно закрепить: 'Подробности — в закреплённой ссылке.'\n\n"
        "Не надо писать домены с 't.me' в самом видео — меньше шансов на бан."
    ),
    (
        "Урок 6. План контента на неделю",
        "Стабильность > идеальность.\n\n"
        "Простой план:\n"
        "• Каждый день 1–3 коротких видео.\n"
        "• Чередуй: боль, возможность, история, объяснение схемы.\n"
        "• 30–50 видео — минимальный объём для ощутимого потока людей.\n\n"
        "Главное — не ждать 'идеального ролика', а делать КОЛИЧЕСТВО с нормальным качеством."
    ),
    (
        "Урок 7. Работа с комментариями",
        "Комментарии — это бесплатный прогрев.\n\n"
        "Отвечай так:\n"
        "• 'Реально ли это работает?' — 'Да. У нас 2 источника дохода: трейдинг + реферальная система 50%/10%.'\n"
        "• 'Сколько можно заработать?' — 'Кто-то отбивает 100$ за 2 человек, дальше идёт в плюс.'\n"
        "• 'Это пирамида?' — 'Нет. Ты покупаешь доступ к системе обучения и сигналам. Партнёрка — это бонус за то, что делишься.'\n\n"
        "Не спорь и не оправдывайся. Коротко, уверенно, по делу."
    ),
    (
        "Урок 8. Как просто объяснять партнёрку",
        "Говори максимально простыми словами:\n\n"
        f"• 'Ты покупаешь доступ к системе за {PRODUCT_PRICE_USD}$.'\n"
        f"• 'После этого получаешь реферальку: {REF_L1_PERCENT}% с каждого человека, кого приведёшь лично.'\n"
        f"• 'И ещё {REF_L2_PERCENT}% со второго уровня — тех, кого приведут твои люди.'\n\n"
        "Пример:\n"
        "Привёл 3 человек сам → 3 × 50$ = 150$.\n"
        "Они привели ещё людей — ты докручиваешь пассивом по 10$ с каждого второго уровня."
    ),
    (
        "Урок 9. Масштабирование через несколько аккаунтов",
        "Когда почувствуешь себя уверенно — масштабируйся.\n\n"
        "Идеи масштабирования:\n"
        "• Веди 2–3 разных TikTok-аккаунта с разной подачей.\n"
        "• Тестируй разные стили: строгий, мотивационный, с юмором.\n"
        "• Меняй заход: где-то упор на трейдинг, где-то на рефералку, где-то на свободу и образ жизни.\n\n"
        "Чем больше воронок, тем больше людей доходит до твоего бота и системы."
    ),
]

# ==========================
# КЛАВИАТУРЫ
# ==========================

def main_keyboard() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("🎓 Обучение трейдингу"), KeyboardButton("📈 Сигналы"))
    kb.row(KeyboardButton("🚀 Обучение по трафику"), KeyboardButton("🤝 Партнёрская программа"))
    kb.row(KeyboardButton("💰 Купить доступ"), KeyboardButton("👤 Мой профиль"))
    return kb


def admin_keyboard() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("👥 Все пользователи"), KeyboardButton("🧾 Покупки"))
    kb.row(KeyboardButton("🤝 Реферальные начисления"))
    return kb


def lessons_keyboard(lessons: List[Tuple[str, str]], prefix: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=1)
    for idx, (title, _) in enumerate(lessons):
        kb.insert(InlineKeyboardButton(text=title, callback_data=f"{prefix}:{idx}"))
    return kb


# ==========================
# ХЕЛПЕРЫ
# ==========================

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


async def log_to_admin(text: str):
    try:
        await bot.send_message(ADMIN_ID, f"🛠 LOG:\n{text}")
    except Exception as e:
        logging.error(f"Не удалось отправить лог админу: {e}")


# ==========================
# ОБРАБОТЧИКИ
# ==========================

@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    # Парсим рефералку: /start или /start ref_123
    referrer_id = None
    if message.get_args():
        args = message.get_args()
        if args.startswith("ref_"):
            try:
                referrer_id = int(args.replace("ref_", ""))
            except ValueError:
                referrer_id = None

    existing = get_user(message.from_user.id)
    if existing is None:
        save_user(message.from_user, referrer_id=referrer_id)
    else:
        # не затираем старого реферера
        _, _, _, _, _, old_ref, *_ = existing
        save_user(message.from_user, referrer_id=old_ref)

    text = (
        "👋 *Добро пожаловать в TradeX Partner Bot!*\n\n"
        "Здесь собрано всё, чтобы ты мог:\n"
        "• разобраться в трейдинге\n"
        "• получать торговые сигналы\n"
        "• научиться лить трафик из TikTok в Telegram\n"
        "• зарабатывать на партнёрке *50% + 10%*\n\n"
        "Ты платишь за доступ к системе *один раз — 100$*,\n"
        "а дальше можешь зарабатывать на своих рефералах сколько захочешь.\n\n"
        "2–3 активных человека уже могут вывести тебя в плюс.\n"
        "Выбирай действие ниже 👇"
    )
    await message.answer(text, reply_markup=main_keyboard())


# === ОБУЧЕНИЕ ТРЕЙДИНГУ ===

@dp.message_handler(Text(equals="🎓 Обучение трейдингу"))
async def trading_education(message: types.Message):
    text = (
        "🎓 *Обучение трейдингу*\n\n"
        "Это базовый курс, который даёт тебе понимание:\n"
        "• что такое трейдинг\n"
        "• как не сливаться на эмоциях\n"
        "• как грамотно работать с сигналами\n"
        "• как выстроить путь к стабильности\n\n"
        "Выбери блок ниже 👇"
    )
    kb = lessons_keyboard(TRADING_LESSONS, prefix="trading")
    await message.answer(text, reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data.startswith("trading:"))
async def trading_lesson_callback(call: types.CallbackQuery):
    idx = int(call.data.split(":")[1])
    title, body = TRADING_LESSONS[idx]
    await call.message.edit_text(
        f"*{title}*\n\n{body}",
        reply_markup=lessons_keyboard(TRADING_LESSONS, "trading")
    )


# === ОБУЧЕНИЕ ТРАФИКУ ===

@dp.message_handler(Text(equals="🚀 Обучение по трафику"))
async def traffic_education(message: types.Message):
    text = (
        "🚀 *Обучение по переливу трафика из TikTok в Telegram*\n\n"
        "Здесь ты узнаешь:\n"
        "• как оформить профиль TikTok под деньги\n"
        "• какие видео снимать, даже если ты стесняешься камеры\n"
        "• как вести людей в бота\n"
        "• как масштабировать трафик через несколько аккаунтов\n\n"
        "Выбери урок ниже 👇"
    )
    kb = lessons_keyboard(TRAFFIC_LESSONS, prefix="traffic")
    await message.answer(text, reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data.startswith("traffic:"))
async def traffic_lesson_callback(call: types.CallbackQuery):
    idx = int(call.data.split(":")[1])
    title, body = TRAFFIC_LESSONS[idx]
    await call.message.edit_text(
        f"*{title}*\n\n{body}",
        reply_markup=lessons_keyboard(TRAFFIC_LESSONS, "traffic")
    )


# === СИГНАЛЫ ===

@dp.message_handler(Text(equals="📈 Сигналы"))
async def signals_info(message: types.Message):
    text = (
        "📈 *Сигналы по трейдингу*\n\n"
        "После покупки доступа ты получаешь:\n"
        "• доступ к закрытому сигнал-каналу\n"
        "• уведомления по основным входам\n"
        "• структуру работы по сигналам из обучения\n\n"
        "Наша цель — не 'угадать x100', а выстроить системную работу.\n\n"
        "Чтобы попасть в закрытый канал — оформи доступ через «💰 Купить доступ»."
    )
    await message.answer(text)


# === ПАРТНЁРКА ===

@dp.message_handler(Text(equals="🤝 Партнёрская программа"))
async def partner_program(message: types.Message):
    user_row = get_user(message.from_user.id)
    if user_row is None:
        save_user(message.from_user)
        user_row = get_user(message.from_user.id)

    ref_link = f"https://t.me/{(await bot.me).username}?start=ref_{message.from_user.id}"

    cursor.execute(
        "SELECT balance, level1_earned, level2_earned, total_withdrawn FROM users WHERE user_id = ?",
        (message.from_user.id,),
    )
    row = cursor.fetchone()
    if row:
        balance, lvl1, lvl2, withdrawn = row
    else:
        balance = lvl1 = lvl2 = withdrawn = 0.0

    text = (
        "🤝 *Партнёрская программа TradeX*\n\n"
        "Ты можешь зарабатывать вместе с системой:\n\n"
        f"• *{REF_L1_PERCENT}%* (≈ {PRODUCT_PRICE_USD * REF_L1_PERCENT / 100:.0f}$) "
        f"с каждого, кого приведёшь лично\n"
        f"• *{REF_L2_PERCENT}%* (≈ {PRODUCT_PRICE_USD * REF_L2_PERCENT / 100:.0f}$) "
        f"со второго уровня — людей, которых приводят твои рефералы\n\n"
        "Пример:\n"
        "— Ты привёл 3 человек → получил 3 × 50$ = 150$\n"
        "— Они привели ещё людей → ты докручиваешь по 10$ с каждого второго уровня.\n\n"
        f"Твоя реферальная ссылка:\n`{ref_link}`\n\n"
        "*Твоя статистика:*\n"
        f"• Баланс для вывода: *{balance:.2f}$*\n"
        f"• Заработано 1 уровень: *{lvl1:.2f}$*\n"
        f"• Заработано 2 уровень: *{lvl2:.2f}$*\n"
        f"• Уже выведено: *{withdrawn:.2f}$*\n\n"
        "Твоя задача — привести первых 1–3 активных людей.\n"
        "Дальше система начинает работать на тебя."
    )
    await message.answer(text)


# === ПОКУПКА ДОСТУПА ===

@dp.message_handler(Text(equals="💰 Купить доступ"))
async def buy_access(message: types.Message):
    user_row = get_user(message.from_user.id)
    if user_row is None:
        save_user(message.from_user)

    create_purchase(message.from_user.id, PRODUCT_PRICE_USD)

    text = (
        "💰 *Покупка доступа к системе TradeX*\n\n"
        "Один раз оплачиваешь доступ — и получаешь:\n"
        "• обучение по трейдингу\n"
        "• сигналы\n"
        "• обучение по переливу трафика из TikTok\n"
        "• партнёрскую программу 50% + 10%\n\n"
        f"Стоимость доступа: *{PRODUCT_PRICE_USD}$*\n\n"
        f"{PAYMENT_DETAILS}\n\n"
        "После оплаты нажми кнопку *«✅ Я оплатил»*.\n"
        "Админ проверит платёж и активирует тебе доступ.\n"
        "Если хочешь ускорить — напиши админу и приложи скрин перевода."
    )

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("✅ Я оплатил"), KeyboardButton("⬅️ В меню"))
    await message.answer(text, reply_markup=kb)
    await log_to_admin(f"Новая заявка на оплату от {message.from_user.id}")


@dp.message_handler(Text(equals="✅ Я оплатил"))
async def i_paid(message: types.Message):
    await message.answer(
        "✅ Отлично! Мы получили сигнал, что ты оплатил.\n"
        "Админ скоро проверит платёж и активирует тебе доступ.\n\n"
        f"Если хочешь ускорить — напиши в поддержку: {SUPPORT_CONTACT}",
        reply_markup=main_keyboard(),
    )
    await log_to_admin(f"Пользователь {message.from_user.id} нажал 'Я оплатил'.")


@dp.message_handler(Text(equals="⬅️ В меню"))
async def back_to_menu(message: types.Message):
    await message.answer("🏠 Главное меню", reply_markup=main_keyboard())


# === ПРОФИЛЬ ===

@dp.message_handler(Text(equals="👤 Мой профиль"))
async def profile(message: types.Message):
    user_row = get_user(message.from_user.id)
    if user_row is None:
        save_user(message.from_user)
        user_row = get_user(message.from_user.id)

    (
        user_id,
        username,
        full_name,
        first_seen,
        last_active,
        referrer_id,
        balance,
        lvl1,
        lvl2,
        withdrawn,
    ) = user_row

    cursor.execute(
        "SELECT COUNT(*) FROM purchases WHERE user_id = ? AND status = 'confirmed'",
        (user_id,),
    )
    cnt_purchases = cursor.fetchone()[0]

    text = (
        "👤 *Твой профиль:*\n\n"
        f"ID: `{user_id}`\n"
        f"Username: @{username if username else '—'}\n"
        f"Имя: {full_name or '—'}\n\n"
        f"Первый вход: {first_seen}\n"
        f"Последняя активность: {last_active}\n\n"
        f"Оплаченных доступов: *{cnt_purchases}*\n"
        f"Баланс: *{balance:.2f}$*\n"
        f"1 уровень заработано: *{lvl1:.2f}$*\n"
        f"2 уровень заработано: *{lvl2:.2f}$*\n"
        f"Уже выведено: *{withdrawn:.2f}$*\n\n"
        f"Твой реферер: `{referrer_id}` (если 0 или None — значит, ты зашёл без приглашения).\n"
    )
    await message.answer(text)


# ==========================
# АДМИНКА
# ==========================

@dp.message_handler(commands=["admin"])
async def admin_panel(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.answer("🚫 У тебя нет доступа к админ-панели.")
    await message.answer("👨‍💻 Админ-панель", reply_markup=admin_keyboard())


@dp.message_handler(Text(equals="👥 Все пользователи"))
async def admin_all_users(message: types.Message):
    if not is_admin(message.from_user.id):
        return

    cursor.execute(
        "SELECT user_id, username, full_name, first_seen, last_active "
        "FROM users ORDER BY first_seen DESC"
    )
    rows = cursor.fetchall()

    if not rows:
        return await message.answer("Пока нет пользователей.")

    text_parts = ["👥 *Все пользователи:*\n\n"]
    for uid, username, full_name, first_seen, last_active in rows:
        text_parts.append(
            f"ID: `{uid}`\n"
            f"Username: @{username if username else '—'}\n"
            f"Имя: {full_name or '—'}\n"
            f"Первый вход: {first_seen}\n"
            f"Последняя активность: {last_active}\n"
            "─────────────\n"
        )

    text = "".join(text_parts)
    for i in range(0, len(text), 4000):
        await message.answer(text[i:i+4000])


@dp.message_handler(Text(equals="🧾 Покупки"))
async def admin_purchases(message: types.Message):
    if not is_admin(message.from_user.id):
        return

    cursor.execute(
        "SELECT id, user_id, amount, status, created_at, confirmed_at "
        "FROM purchases ORDER BY created_at DESC LIMIT 50"
    )
    rows = cursor.fetchall()

    if not rows:
        return await message.answer("Покупок пока нет.")

    text_parts = ["🧾 *Последние покупки:*\n\n"]
    for pid, uid, amount, status, created_at, confirmed_at in rows:
        text_parts.append(
            f"ID покупки: `{pid}`\n"
            f"Пользователь: `{uid}`\n"
            f"Сумма: {amount}$\n"
            f"Статус: *{status}*\n"
            f"Создано: {created_at}\n"
            f"Подтверждено: {confirmed_at or '—'}\n"
            "─────────────\n"
        )

    text = "".join(text_parts)
    for i in range(0, len(text), 4000):
        await message.answer(text[i:i+4000])


@dp.message_handler(Text(equals="🤝 Реферальные начисления"))
async def admin_ref_earnings(message: types.Message):
    if not is_admin(message.from_user.id):
        return

    cursor.execute(
        """
        SELECT referrer_id, referred_id, level, bonus, created_at
        FROM referral_earnings
        ORDER BY created_at DESC
        LIMIT 50
        """
    )
    rows = cursor.fetchall()

    if not rows:
        return await message.answer("Пока не было реферальных начислений.")

    text_parts = ["🤝 *Реферальные начисления (последние 50):*\n\n"]
    for referrer_id, referred_id, level, bonus, created_at in rows:
        text_parts.append(
            f"Кому: `{referrer_id}` | Уровень: {level}\n"
            f"За кого: `{referred_id}`\n"
            f"Бонус: *{bonus:.2f}$*\n"
            f"Когда: {created_at}\n"
            "─────────────\n"
        )

    text = "".join(text_parts)
    for i in range(0, len(text), 4000):
        await message.answer(text[i:i+4000])


@dp.message_handler(commands=["confirm"])
async def admin_confirm_purchase(message: types.Message):
    """Подтверждение оплаты: /confirm <ID_покупки>"""
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()
    if len(parts) < 2:
        return await message.answer("Использование: /confirm <ID_покупки>")

    try:
        purchase_id = int(parts[1])
    except ValueError:
        return await message.answer("ID покупки должен быть числом.")

    cursor.execute(
        "SELECT id, user_id, amount, status FROM purchases WHERE id = ?",
        (purchase_id,),
    )
    row = cursor.fetchone()
    if not row:
        return await message.answer("Покупка с таким ID не найдена.")

    pid, uid, amount, status = row
    if status == "confirmed":
        return await message.answer("Эта покупка уже подтверждена.")

    # подтверждаем покупку
    confirm_purchase(pid)

    # реферальные начисления
    cursor.execute("SELECT referrer_id FROM users WHERE user_id = ?", (uid,))
    ref_row = cursor.fetchone()
    ref1 = ref_row[0] if ref_row else None

    if ref1:
        bonus1 = amount * REF_L1_PERCENT / 100
        add_referral_bonus(ref1, uid, level=1, bonus=bonus1)

        # второй уровень
        cursor.execute("SELECT referrer_id FROM users WHERE user_id = ?", (ref1,))
        ref2_row = cursor.fetchone()
        ref2 = ref2_row[0] if ref2_row else None

        if ref2:
            bonus2 = amount * REF_L2_PERCENT / 100
            add_referral_bonus(ref2, uid, level=2, bonus=bonus2)

    await message.answer(f"✅ Покупка {pid} от пользователя {uid} подтверждена.")
    try:
        await bot.send_message(
            uid,
            "✅ Твоя оплата подтверждена!\n\n"
            "Доступ к системе активирован.\n"
            "Можешь изучать обучение, подключаться к сигналам и начинать заливать трафик.\n\n"
            "И не забудь поделиться своей реферальной ссылкой — партнёрка 50% + 10%.",
        )
    except Exception:
        pass

    await log_to_admin(f"Покупка {pid} подтверждена. Пользователь {uid}.")


# ==========================
# ЗАПУСК
# ==========================

async def on_startup(dispatcher):
    await log_to_admin("✅ Бот TradeX Partner Bot запущен.")

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
