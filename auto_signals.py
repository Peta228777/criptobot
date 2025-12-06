# auto_signals.py

import asyncio
import random
import logging
from decimal import Decimal
from typing import Optional, Sequence

import aiohttp
from aiogram import Bot

logger = logging.getLogger(__name__)

# Базовый URL CoinGecko
COINGECKO_API_BASE = "https://api.coingecko.com/api/v3"

# Маппинг наших пар на ID в CoinGecko
COINGECKO_IDS = {
    "BTCUSDT": "bitcoin",
    "ETHUSDT": "ethereum",
    "SOLUSDT": "solana",
    "BNBUSDT": "binancecoin",
    # если добавишь пары в AUTO_SIGNALS_SYMBOLS – не забудь дописать сюда
}


async def fetch_coingecko_price(coin_id: str) -> Optional[dict]:
    """
    Берём цену и 24h изменение по монете с CoinGecko.
    Используем /simple/price с vs_currencies=usd и include_24hr_change=true.
    """
    url = f"{COINGECKO_API_BASE}/simple/price"
    params = {
        "ids": coin_id,
        "vs_currencies": "usd",
        "include_24hr_change": "true",
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    logger.warning("CoinGecko price %s status %s", coin_id, resp.status)
                    return None
                data = await resp.json()
                return data
        except Exception as e:
            logger.error("Error fetching CoinGecko price for %s: %s", coin_id, e)
            return None


def _format_price(p: Decimal) -> str:
    """
    Примитивное форматирование: чем меньше цена, тем больше знаков.
    """
    if p >= Decimal("100"):
        q = p.quantize(Decimal("0.1"))
    elif p >= Decimal("1"):
        q = p.quantize(Decimal("0.01"))
    elif p >= Decimal("0.1"):
        q = p.quantize(Decimal("0.001"))
    else:
        q = p.quantize(Decimal("0.0001"))
    return str(q)


async def build_auto_signal_text(
    symbols: Sequence[str],
    enabled: bool,
) -> Optional[str]:
    """
    Генерим авто-сигнал по случайному инструменту:
    направление + вход + SL + два TP.
    Данные берём с CoinGecko (цена в USD и 24h изменение).
    """
    if not enabled:
        return None

    symbols = list(symbols) or ["BTCUSDT"]
    pair = random.choice(symbols)

    coin_id = COINGECKO_IDS.get(pair)
    if not coin_id:
        logger.warning("No CoinGecko ID for pair %s", pair)
        return None

    data = await fetch_coingecko_price(coin_id)
    if not data or coin_id not in data:
        return None

    coin_data = data[coin_id]
    price_usd = coin_data.get("usd")
    change_percent = coin_data.get("usd_24h_change")

    try:
        price = Decimal(str(price_usd))
    except Exception:
        return None

    try:
        chg = Decimal(str(change_percent)) if change_percent is not None else None
    except Exception:
        chg = None

    # Определяем направление
    direction = None
    idea = None
    if chg is not None:
        if chg > Decimal("1"):
            direction = "long"
            idea = "🟢 Идея: LONG (преобладает восходящее движение за 24ч)"
        elif chg < Decimal("-1"):
            direction = "short"
            idea = "🔴 Идея: SHORT (преобладает нисходящее движение за 24ч)"
        else:
            idea = "⚪ Рынок во флете, явного тренда за 24ч нет. Сигнал без конкретных уровней."

    # Если нет направленного тренда — просто обзор без уровней
    if not direction:
        parts = [
            f"📡 <b>Авто-сигнал</b> по <b>{pair}</b>",
            f"Текущая цена: <b>{_format_price(price)}</b> USDT",
        ]
        if chg is not None:
            parts.append(f"Изменение за 24ч: <b>{chg}%</b>")
        if idea:
            parts.append("")
            parts.append(idea)
        parts.append("")
        parts.append("⚠️ Это автоматический технический сигнал от бота, не финансовая рекомендация.")
        return "\n".join(parts)

    # Считаем вход / стоп / тейки (простая модель по % от цены)
    entry = price

    if direction == "long":
        sl = entry * (Decimal("1") - Decimal("0.01"))   # -1%
        tp1 = entry * (Decimal("1") + Decimal("0.02"))  # +2%
        tp2 = entry * (Decimal("1") + Decimal("0.04"))  # +4%
        dir_text = "LONG"
    else:  # short
        sl = entry * (Decimal("1") + Decimal("0.01"))   # +1%
        tp1 = entry * (Decimal("1") - Decimal("0.02"))  # -2%
        tp2 = entry * (Decimal("1") - Decimal("0.04"))  # -4%
        dir_text = "SHORT"

    parts = [
        f"📡 <b>Авто-сигнал</b> по <b>{pair}</b>",
        f"Текущая цена: <b>{_format_price(price)}</b> USDT",
    ]
    if chg is not None:
        parts.append(f"Изменение за 24ч: <b>{chg}%</b>")
    if idea:
        parts.append("")
        parts.append(idea)

    parts.append("")
    parts.append(f"📊 <b>Параметры сделки ({dir_text})</b>")
    parts.append(f"Вход: <b>{_format_price(entry)}</b> USDT")
    parts.append(f"Стоп-лосс: <b>{_format_price(sl)}</b> USDT")
    parts.append(f"Тейк-профит 1: <b>{_format_price(tp1)}</b> USDT")
    parts.append(f"Тейк-профит 2: <b>{_format_price(tp2)}</b> USDT")

    parts.append("")
    parts.append("⚠️ Это автоматический технический сигнал от бота, не финансовая рекомендация.")

    return "\n".join(parts)


async def auto_signals_worker(
    bot: Bot,
    signals_channel_id: int,
    auto_signals_per_day: int,
    symbols: Sequence[str],
    enabled: bool,
) -> None:
    """
    Фоновая задача: раз в N секунд шлёт авто-сигнал в канал.
    """
    if not enabled:
        logger.info("Auto signals disabled, worker not started.")
        return

    if not isinstance(signals_channel_id, int):
        logger.warning("signals_channel_id is not int, auto-signals disabled.")
        return

    interval = int(24 * 3600 / max(auto_signals_per_day, 1))

    # немного ждём старт бота
    await asyncio.sleep(15)

    while True:
        try:
            text = await build_auto_signal_text(symbols, enabled)
            if text:
                await bot.send_message(signals_channel_id, text)
                logger.info("Auto signal sent to %s", signals_channel_id)
        except Exception as e:
            logger.error("Auto signals worker error: %s", e)

        await asyncio.sleep(interval)
