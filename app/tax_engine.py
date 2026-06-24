"""
FIFO tax engine — расчёт ИПН по НК РК ст. 320, 331, 337.
"""
from dataclasses import dataclass, field
from datetime import date
from collections import defaultdict
from typing import List
import json


@dataclass
class TxRow:
    id: str
    date: date
    type: str          # buy | sell | dividend | coupon
    ticker: str
    qty: float
    price_kzt: float   # уже в тенге
    commission_kzt: float
    is_kase_listed: bool
    amount_kzt: float  # для dividend/coupon


@dataclass
class Lot:
    date: date
    qty: float
    price_kzt: float
    commission_kzt: float  # пропорциональная часть комиссии


@dataclass
class SaleDetail:
    ticker: str
    sale_date: date
    qty: float
    revenue_kzt: float
    cost_kzt: float
    income_kzt: float
    rate: float
    tax_kzt: float
    exempt_reason: str = ""


TAX_RATE_STOCKS = 0.10
TAX_RATE_DIVIDENDS_KZ = 0.05
TAX_RATE_DIVIDENDS_FOREIGN = 0.10
TAX_RATE_COUPONS = 0.10
MIN_HOLD_DAYS_KASE = 1095  # 3 года


def calc_tax(transactions: List[TxRow], tax_year: int) -> dict:
    year_txs = [t for t in transactions if t.date.year == tax_year]

    # ── Акции: FIFO ──────────────────────────────────────────────────────────
    lots: dict[str, List[Lot]] = defaultdict(list)
    sale_details: List[SaleDetail] = []

    for tx in sorted(year_txs, key=lambda x: x.date):
        if tx.type == "buy":
            lots[tx.ticker].append(Lot(
                date=tx.date,
                qty=tx.qty,
                price_kzt=tx.price_kzt,
                commission_kzt=tx.commission_kzt,
            ))

        elif tx.type == "sell":
            revenue = tx.qty * tx.price_kzt - tx.commission_kzt
            remaining = tx.qty
            cost = 0.0
            earliest_buy_date = None

            queue = lots[tx.ticker]
            while remaining > 0 and queue:
                lot = queue[0]
                if earliest_buy_date is None:
                    earliest_buy_date = lot.date
                used = min(lot.qty, remaining)
                proportion = used / lot.qty
                cost += used * lot.price_kzt + lot.commission_kzt * proportion
                lot.qty -= used
                lot.commission_kzt -= lot.commission_kzt * proportion
                if lot.qty < 1e-9:
                    queue.pop(0)
                remaining -= used

            income = revenue - cost

            # льгота KASE ≥ 3 лет: считаем от даты самой ранней купленной партии
            exempt = False
            exempt_reason = ""
            if tx.is_kase_listed and earliest_buy_date is not None:
                hold_days = (tx.date - earliest_buy_date).days
                if hold_days >= MIN_HOLD_DAYS_KASE:
                    exempt = True
                    exempt_reason = "KASE ≥ 3 лет (ст. 331 НК РК)"

            rate = 0.0 if exempt else TAX_RATE_STOCKS
            tax = max(0, income) * rate

            sale_details.append(SaleDetail(
                ticker=tx.ticker,
                sale_date=tx.date,
                qty=tx.qty,
                revenue_kzt=revenue,
                cost_kzt=cost,
                income_kzt=income,
                rate=rate,
                tax_kzt=tax,
                exempt_reason=exempt_reason,
            ))

    # Зачёт убытков: суммируем все доходы/убытки по акциям
    total_stock_income = sum(d.income_kzt for d in sale_details)
    tax_base_stocks = max(0, total_stock_income)
    # Пересчитываем итоговый налог с учётом зачёта убытков
    stocks_tax = tax_base_stocks * TAX_RATE_STOCKS if sale_details and not all(d.rate == 0 for d in sale_details) else sum(d.tax_kzt for d in sale_details)

    # ── Дивиденды ────────────────────────────────────────────────────────────
    divs = [t for t in year_txs if t.type == "dividend"]
    div_kz = sum(t.amount_kzt for t in divs if t.is_kase_listed)
    div_foreign = sum(t.amount_kzt for t in divs if not t.is_kase_listed)
    div_kz_tax = div_kz * TAX_RATE_DIVIDENDS_KZ
    div_foreign_tax = div_foreign * TAX_RATE_DIVIDENDS_FOREIGN

    # ── Купоны ───────────────────────────────────────────────────────────────
    coupons = [t for t in year_txs if t.type == "coupon"]
    coupon_taxable = sum(t.amount_kzt for t in coupons if not t.is_kase_listed)
    coupon_exempt = sum(t.amount_kzt for t in coupons if t.is_kase_listed)
    coupon_tax = coupon_taxable * TAX_RATE_COUPONS

    total_tax = stocks_tax + div_kz_tax + div_foreign_tax + coupon_tax

    details = {
        "sales": [
            {
                "ticker": d.ticker,
                "date": d.sale_date.isoformat(),
                "qty": d.qty,
                "revenue_kzt": round(d.revenue_kzt, 2),
                "cost_kzt": round(d.cost_kzt, 2),
                "income_kzt": round(d.income_kzt, 2),
                "rate_pct": round(d.rate * 100, 0),
                "tax_kzt": round(d.tax_kzt, 2),
                "exempt_reason": d.exempt_reason,
            }
            for d in sale_details
        ],
        "dividends_kz": round(div_kz, 2),
        "dividends_foreign": round(div_foreign, 2),
        "coupons_taxable": round(coupon_taxable, 2),
        "coupons_exempt": round(coupon_exempt, 2),
    }

    return {
        "tax_year": tax_year,
        "stocks_income_kzt": round(total_stock_income, 2),
        "stocks_tax_kzt": round(stocks_tax, 2),
        "dividends_kz_kzt": round(div_kz, 2),
        "dividends_kz_tax_kzt": round(div_kz_tax, 2),
        "dividends_foreign_kzt": round(div_foreign, 2),
        "dividends_foreign_tax_kzt": round(div_foreign_tax, 2),
        "coupons_kzt": round(coupon_taxable, 2),
        "coupons_tax_kzt": round(coupon_tax, 2),
        "total_tax_kzt": round(total_tax, 2),
        "details": details,
    }
