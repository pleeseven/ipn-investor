"""
Получение курсов НБ РК с кешированием в БД.
"""
import httpx
from datetime import date, timedelta
from xml.etree import ElementTree
from typing import Optional
from sqlalchemy.orm import Session
from .models import ExchangeRate


NBK_API_URL = "https://api.nationalbank.kz/rss/rates_all.xml"

FALLBACK_RATES = {
    "USD": 450.0,
    "EUR": 490.0,
    "RUB": 4.9,
}


async def get_rate(db: Session, currency: str, tx_date: date) -> float:
    if currency == "KZT":
        return 1.0

    cached = db.query(ExchangeRate).filter_by(date=tx_date, currency=currency).first()
    if cached:
        return cached.rate_kzt

    # Попытка загрузить с НБ РК
    try:
        rate = await _fetch_nbk_rate(currency, tx_date)
    except Exception:
        rate = None

    if rate is None:
        # Ищем ближайший предыдущий известный курс в БД
        prev = (
            db.query(ExchangeRate)
            .filter(ExchangeRate.currency == currency, ExchangeRate.date < tx_date)
            .order_by(ExchangeRate.date.desc())
            .first()
        )
        rate = prev.rate_kzt if prev else FALLBACK_RATES.get(currency, 1.0)

    db.add(ExchangeRate(date=tx_date, currency=currency, rate_kzt=rate))
    db.commit()
    return rate


async def _fetch_nbk_rate(currency: str, tx_date: date) -> Optional[float]:
    params = {"fdate": tx_date.isoformat(), "lang": "rus"}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(NBK_API_URL, params=params)
        resp.raise_for_status()

    root = ElementTree.fromstring(resp.text)
    for item in root.iter("item"):
        title = item.find("title")
        description = item.find("description")
        quant = item.find("quant")
        if title is not None and currency.upper() in title.text.upper():
            rate = float(description.text.replace(",", "."))
            qty = int(quant.text) if quant is not None else 1
            return rate / qty
    return None
