from sqlalchemy import create_engine, Column, String, Integer, Float, Boolean, Date, DateTime, Text, ForeignKey
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from datetime import datetime
import uuid

SQLALCHEMY_DATABASE_URL = "sqlite:///./taxbot.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def gen_id():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=gen_id)
    iin = Column(String(12), unique=True, nullable=False)
    full_name = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    transactions = relationship("Transaction", back_populates="user")
    calculations = relationship("TaxCalculation", back_populates="user")


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False)
    type = Column(String(10), nullable=False)   # buy, sell, dividend, coupon
    ticker = Column(String(20), nullable=False)
    qty = Column(Float, default=0)
    price = Column(Float, default=0)
    commission = Column(Float, default=0)
    currency = Column(String(3), default="KZT")
    price_kzt = Column(Float)
    commission_kzt = Column(Float)
    nbk_rate = Column(Float, default=1.0)
    amount = Column(Float, default=0)           # for dividends/coupons
    amount_kzt = Column(Float, default=0)
    is_kase_listed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    user = relationship("User", back_populates="transactions")


class TaxCalculation(Base):
    __tablename__ = "tax_calculations"
    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    tax_year = Column(Integer, nullable=False)
    # Акции
    stocks_income_kzt = Column(Float, default=0)
    stocks_tax_kzt = Column(Float, default=0)
    # Дивиденды
    dividends_kz_kzt = Column(Float, default=0)
    dividends_kz_tax_kzt = Column(Float, default=0)
    dividends_foreign_kzt = Column(Float, default=0)
    dividends_foreign_tax_kzt = Column(Float, default=0)
    # Купоны
    coupons_kzt = Column(Float, default=0)
    coupons_tax_kzt = Column(Float, default=0)
    # Итого
    total_tax_kzt = Column(Float, default=0)
    details_json = Column(Text)
    status = Column(String(20), default="draft")   # draft, confirmed, filed, paid
    calculated_at = Column(DateTime, default=datetime.utcnow)
    declaration_xml = Column(Text)
    user = relationship("User", back_populates="calculations")


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"
    date = Column(Date, primary_key=True)
    currency = Column(String(3), primary_key=True)
    rate_kzt = Column(Float, nullable=False)


def create_tables():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
