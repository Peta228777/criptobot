# auto_signals.py

import asyncio
import random
import logging
from decimal import Decimal
from typing import Optional, Sequence

import aiohttp
from aiogram import Bot

logger = logging.getLogger(__name__)

# Базовый URL Binance для публичного API
BINANCE_API_BASE = "https://api.binance.com"


async def fetch_binance_24h(symbol: str) -> Optional[dict]:
    """
    Берём статистику за 24 часа по символу с публичного API Binance.
    """
    url = f"{BINANCE_API_BASE}/api/v3/ticker/24hr"
    params = {"symbol": symbol}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    logger.warning("Binance 24h ticker %s status %s", symbol, resp.status)
                    return None
                data = await resp.json()
                return data
        except Exception as e:
            logger.error("Error fetching Binance 24h ticker for %s: %s", symbol, e)
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
    Это не финрекомендация, а автоген по простой логике.
    """
    if not enabled:
        return None

    symbols = list(symbols) or ["BTCUSDT"]
    symbol = random.choice(symbols)

    data = await fetch_binance_24h(symbol)
    if not data:
        return None

    last_price = data.get("lastPrice")
    change_percent = data.get("priceChangePercent")

    try:
        price = Decimal(str(last_price))
    except Exception:
        return None

    try:
        chg = Decimal(str(change_percent))
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

    # Если нет направленного тренда — обзор без уровней
    if not direction:
        parts = [
            f"📡 <b>Авто-сигнал</b> по <b>{symbol}</b>",
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

    # Считаем вход / стоп / тейки (очень простая модель по % от цены)
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
        f"📡 <b>Авто-сигнал</b> по <b>{symbol}</b>",
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
    Фоновая задача: раз в N часов шлёт авто-сигнал в канал.
    """
    if not enabled:
        logger.info("Auto signals disabled, worker not started.")
        return

    if not isinstance(signals_channel_id, int):
        logger.warning("signals_channel_id is not int, auto-signals disabled.")
        return

    interval = int(24 * 3600 / max(auto_signals_per_day, 1))

    # чуть ждём старта бота
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
