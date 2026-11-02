import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from database.connection import Base
from models.entities import Comanda, Product
from pages.reports import _daily_sales_dataframe, _daily_sales_excel, _daily_sales_pdf
from services.domain import close_comanda, create_order, open_cash, update_order_status
from services.seed import seed_demo_data
from utils.clock import local_today


class DailySalesReportTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        seed_demo_data(self.session)
        open_cash(self.session, 0, "Operador")

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_daily_sales_uses_closed_comandas_and_exports_excel(self):
        product = self.session.scalar(select(Product).where(Product.name == "Café coado"))
        order = create_order(self.session, [{"product_id": product.id, "quantity": 2}], customer_name="Ana")
        for status in ("Em preparo", "Pronto", "Entregue", "Finalizado"):
            update_order_status(self.session, order, status)

        linked_comanda = self.session.scalar(select(Comanda).where(Comanda.status == "Aberta"))
        received = close_comanda(self.session, linked_comanda, "Pix", "Operador")

        frame, summary = _daily_sales_dataframe(self.session, local_today())
        self.assertEqual(summary["count"], 1)
        self.assertAlmostEqual(summary["total"], received)
        self.assertEqual(int(frame.iloc[0]["Comanda"]), linked_comanda.id)

        excel_bytes = _daily_sales_excel(frame, summary, local_today())
        self.assertGreater(len(excel_bytes), 1000)
        pdf_bytes = _daily_sales_pdf(frame, summary, local_today())
        self.assertGreater(len(pdf_bytes), 500)


if __name__ == "__main__":
    unittest.main()
