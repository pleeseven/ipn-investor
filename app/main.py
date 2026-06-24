"""
ИПН Инвестор — FastAPI backend (MVP)
"""
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from pydantic import BaseModel, field_validator
from datetime import date
from typing import Optional
import json
import os

from .models import create_tables, get_db, User, Transaction, TaxCalculation
from .tax_engine import calc_tax, TxRow
from .xml_generator import generate_240
from .nbk_rates import get_rate

app = FastAPI(title="ИПН Инвестор", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

create_tables()


# ── Schemas ──────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    iin: str
    full_name: str

    @field_validator("iin")
    @classmethod
    def validate_iin(cls, v: str) -> str:
        v = v.strip()
        if not v.isdigit() or len(v) != 12:
            raise ValueError("ИИН должен содержать ровно 12 цифр")
        return v


class TransactionCreate(BaseModel):
    date: date
    type: str           # buy | sell | dividend | coupon
    ticker: str
    qty: float = 0
    price: float = 0
    commission: float = 0
    currency: str = "KZT"
    amount: float = 0   # для dividend/coupon
    is_kase_listed: bool = False

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        allowed = {"buy", "sell", "dividend", "coupon"}
        if v not in allowed:
            raise ValueError(f"type должен быть одним из: {allowed}")
        return v

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        return v.upper()


class PaymentStatusUpdate(BaseModel):
    status: str  # confirmed | filed | paid


# ── Users ─────────────────────────────────────────────────────────────────────

@app.post("/api/users", summary="Создать или получить пользователя")
def create_user(body: UserCreate, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(iin=body.iin).first()
    if user:
        return {"id": user.id, "iin": user.iin, "full_name": user.full_name}
    user = User(iin=body.iin, full_name=body.full_name)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "iin": user.iin, "full_name": user.full_name}


@app.get("/api/users/{user_id}")
def get_user(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).get(user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    return {"id": user.id, "iin": user.iin, "full_name": user.full_name}


# ── Transactions ──────────────────────────────────────────────────────────────

@app.get("/api/users/{user_id}/transactions")
def list_transactions(user_id: str, db: Session = Depends(get_db)):
    txs = db.query(Transaction).filter_by(user_id=user_id).order_by(Transaction.date).all()
    return [_tx_to_dict(t) for t in txs]


@app.post("/api/users/{user_id}/transactions")
async def add_transaction(user_id: str, body: TransactionCreate, db: Session = Depends(get_db)):
    user = db.query(User).get(user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")

    nbk_rate = await get_rate(db, body.currency, body.date)
    price_kzt = body.price * nbk_rate
    commission_kzt = body.commission * nbk_rate
    amount_kzt = body.amount * nbk_rate

    tx = Transaction(
        user_id=user_id,
        date=body.date,
        type=body.type,
        ticker=body.ticker.upper(),
        qty=body.qty,
        price=body.price,
        commission=body.commission,
        currency=body.currency,
        price_kzt=price_kzt,
        commission_kzt=commission_kzt,
        nbk_rate=nbk_rate,
        amount=body.amount,
        amount_kzt=amount_kzt,
        is_kase_listed=body.is_kase_listed,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return _tx_to_dict(tx)


@app.delete("/api/users/{user_id}/transactions/{tx_id}")
def delete_transaction(user_id: str, tx_id: str, db: Session = Depends(get_db)):
    tx = db.query(Transaction).filter_by(id=tx_id, user_id=user_id).first()
    if not tx:
        raise HTTPException(404, "Сделка не найдена")
    db.delete(tx)
    db.commit()
    return {"ok": True}


# ── Tax Calculation ───────────────────────────────────────────────────────────

@app.post("/api/users/{user_id}/calculate")
def calculate_tax(user_id: str, tax_year: int = 2024, db: Session = Depends(get_db)):
    user = db.query(User).get(user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")

    txs = db.query(Transaction).filter_by(user_id=user_id).all()
    if not txs:
        raise HTTPException(400, "Нет сделок для расчёта")

    rows = [
        TxRow(
            id=t.id,
            date=t.date,
            type=t.type,
            ticker=t.ticker,
            qty=t.qty,
            price_kzt=t.price_kzt or 0,
            commission_kzt=t.commission_kzt or 0,
            is_kase_listed=t.is_kase_listed or False,
            amount_kzt=t.amount_kzt or 0,
        )
        for t in txs
    ]

    result = calc_tax(rows, tax_year)
    xml = generate_240(user.iin, user.full_name or "", tax_year, result)

    # Сохраняем / обновляем расчёт
    existing = db.query(TaxCalculation).filter_by(user_id=user_id, tax_year=tax_year).first()
    if existing:
        db.delete(existing)
        db.commit()

    calc_obj = TaxCalculation(
        user_id=user_id,
        tax_year=tax_year,
        stocks_income_kzt=result["stocks_income_kzt"],
        stocks_tax_kzt=result["stocks_tax_kzt"],
        dividends_kz_kzt=result["dividends_kz_kzt"],
        dividends_kz_tax_kzt=result["dividends_kz_tax_kzt"],
        dividends_foreign_kzt=result["dividends_foreign_kzt"],
        dividends_foreign_tax_kzt=result["dividends_foreign_tax_kzt"],
        coupons_kzt=result["coupons_kzt"],
        coupons_tax_kzt=result["coupons_tax_kzt"],
        total_tax_kzt=result["total_tax_kzt"],
        details_json=json.dumps(result["details"], ensure_ascii=False),
        declaration_xml=xml,
    )
    db.add(calc_obj)
    db.commit()
    db.refresh(calc_obj)

    result["calculation_id"] = calc_obj.id
    result["xml_available"] = True
    return result


@app.get("/api/users/{user_id}/calculations")
def list_calculations(user_id: str, db: Session = Depends(get_db)):
    calcs = db.query(TaxCalculation).filter_by(user_id=user_id).order_by(TaxCalculation.tax_year.desc()).all()
    return [_calc_to_dict(c) for c in calcs]


@app.get("/api/calculations/{calc_id}/xml")
def download_xml(calc_id: str, db: Session = Depends(get_db)):
    calc = db.query(TaxCalculation).get(calc_id)
    if not calc or not calc.declaration_xml:
        raise HTTPException(404, "Декларация не найдена")
    return Response(
        content=calc.declaration_xml.encode("utf-8"),
        media_type="application/xml",
        headers={"Content-Disposition": f"attachment; filename=240_00_{calc.tax_year}.xml"},
    )


@app.patch("/api/calculations/{calc_id}/status")
def update_status(calc_id: str, body: PaymentStatusUpdate, db: Session = Depends(get_db)):
    calc = db.query(TaxCalculation).get(calc_id)
    if not calc:
        raise HTTPException(404, "Расчёт не найден")
    calc.status = body.status
    db.commit()
    return {"ok": True, "status": calc.status}


@app.get("/api/calculations/{calc_id}/kaspi-link")
def kaspi_link(calc_id: str, db: Session = Depends(get_db)):
    calc = db.query(TaxCalculation).get(calc_id)
    if not calc:
        raise HTTPException(404)
    user = db.query(User).get(calc.user_id)
    amount = int(calc.total_tax_kzt)
    deep_link = f"kaspi://pay?service=tax&kbk=101201&iin={user.iin}&amount={amount}&period={calc.tax_year}"
    web_link = f"https://kaspi.kz/pay/tax?kbk=101201&iin={user.iin}&amount={amount}"
    return {"deep_link": deep_link, "web_link": web_link, "amount": amount}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _tx_to_dict(t: Transaction) -> dict:
    return {
        "id": t.id,
        "date": t.date.isoformat(),
        "type": t.type,
        "ticker": t.ticker,
        "qty": t.qty,
        "price": t.price,
        "commission": t.commission,
        "currency": t.currency,
        "price_kzt": t.price_kzt,
        "commission_kzt": t.commission_kzt,
        "nbk_rate": t.nbk_rate,
        "amount": t.amount,
        "amount_kzt": t.amount_kzt,
        "is_kase_listed": t.is_kase_listed,
    }


def _calc_to_dict(c: TaxCalculation) -> dict:
    return {
        "id": c.id,
        "tax_year": c.tax_year,
        "stocks_income_kzt": c.stocks_income_kzt,
        "stocks_tax_kzt": c.stocks_tax_kzt,
        "dividends_kz_kzt": c.dividends_kz_kzt,
        "dividends_kz_tax_kzt": c.dividends_kz_tax_kzt,
        "dividends_foreign_kzt": c.dividends_foreign_kzt,
        "dividends_foreign_tax_kzt": c.dividends_foreign_tax_kzt,
        "coupons_kzt": c.coupons_kzt,
        "coupons_tax_kzt": c.coupons_tax_kzt,
        "total_tax_kzt": c.total_tax_kzt,
        "status": c.status,
        "calculated_at": c.calculated_at.isoformat(),
        "details": json.loads(c.details_json) if c.details_json else {},
    }


# ── Serve frontend ────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def serve_frontend():
    html_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    with open(html_path, encoding="utf-8") as f:
        return f.read()
