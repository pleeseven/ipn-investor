"""
Генерация декларации 240.00 в XML-формате для cabinet.egov.kz.
"""
from lxml import etree
from datetime import date


def generate_240(iin: str, full_name: str, tax_year: int, calc: dict) -> str:
    XSI = "http://www.w3.org/2001/XMLSchema-instance"
    NSMAP = {"xsi": XSI}
    root = etree.Element("Form240", nsmap=NSMAP)
    root.set("version", "1.0")

    # Заголовок
    hdr = etree.SubElement(root, "Header")
    etree.SubElement(hdr, "FormCode").text = "240.00"
    etree.SubElement(hdr, "TaxPeriod").text = str(tax_year)
    etree.SubElement(hdr, "IIN").text = iin
    etree.SubElement(hdr, "FullName").text = full_name
    etree.SubElement(hdr, "GeneratedAt").text = date.today().isoformat()

    # Раздел A — Доходы из иностранных источников (иностранные акции/дивиденды)
    sec_a = etree.SubElement(root, "SectionA")
    etree.SubElement(sec_a, "A001").text = _fmt(calc.get("stocks_income_kzt", 0))
    etree.SubElement(sec_a, "A002").text = _fmt(calc.get("dividends_foreign_kzt", 0))
    etree.SubElement(sec_a, "A003").text = _fmt(
        calc.get("stocks_income_kzt", 0) + calc.get("dividends_foreign_kzt", 0)
    )

    # Раздел B — Доходы из источников в РК
    sec_b = etree.SubElement(root, "SectionB")
    etree.SubElement(sec_b, "B001").text = _fmt(calc.get("dividends_kz_kzt", 0))
    etree.SubElement(sec_b, "B002").text = _fmt(calc.get("coupons_kzt", 0))

    # Раздел C — Исчисленный ИПН
    sec_c = etree.SubElement(root, "SectionC")
    etree.SubElement(sec_c, "C001_StocksTax").text = _fmt(calc.get("stocks_tax_kzt", 0))
    etree.SubElement(sec_c, "C002_DivKZTax").text = _fmt(calc.get("dividends_kz_tax_kzt", 0))
    etree.SubElement(sec_c, "C003_DivForeignTax").text = _fmt(calc.get("dividends_foreign_tax_kzt", 0))
    etree.SubElement(sec_c, "C004_CouponsTax").text = _fmt(calc.get("coupons_tax_kzt", 0))
    etree.SubElement(sec_c, "C005_TotalTax").text = _fmt(calc.get("total_tax_kzt", 0))

    # КБК для оплаты
    pay = etree.SubElement(root, "Payment")
    etree.SubElement(pay, "KBK").text = "101201"
    etree.SubElement(pay, "Amount").text = _fmt(calc.get("total_tax_kzt", 0))
    etree.SubElement(pay, "Period").text = str(tax_year)

    return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding="UTF-8").decode()


def _fmt(val: float) -> str:
    return f"{val:.2f}"
