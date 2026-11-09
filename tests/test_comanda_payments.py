import unittest

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from database.connection import Base
from models.entities import Audit, CashMovement, Comanda, ComandaPayment, Product
from services.domain import (
    apply_comanda_discount, close_comanda, comanda_balance, create_order, discount_from_percent,
    equal_share, open_cash, receive_comanda_payment, remove_comanda_discount, update_order_status,
)
from services.manager_pin import has_manager_pin, set_manager_pin
from services.seed import seed_demo_data


class ComandaPaymentTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        seed_demo_data(self.session)
        open_cash(self.session, 0, "Turno teste")
        product = self.session.scalar(select(Product).where(Product.name == "Café coado"))
        order = create_order(self.session, [{"product_id": product.id, "quantity": 4}], customer_name="Ana")
        for status in ("Em preparo", "Pronto", "Entregue", "Finalizado"):
            update_order_status(self.session, order, status)
        self.comanda = self.session.scalar(select(Comanda).where(Comanda.status == "Aberta"))
        self.total = self.comanda.total

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_equal_share_gives_leftover_cents_to_last_person(self):
        self.assertEqual(equal_share(100.0, 3), 33.33)
        self.assertEqual(equal_share(66.67, 2), 33.33)
        self.assertEqual(equal_share(33.34, 1), 33.34)
        with self.assertRaises(ValueError):
            equal_share(10, 0)

    def test_split_payments_close_comanda_with_one_movement_each(self):
        first = receive_comanda_payment(self.session, self.comanda, "Pix", 5.0)
        self.assertFalse(first["closed"])
        self.assertAlmostEqual(first["remaining"], self.total - 5.0)
        self.assertEqual(self.comanda.status, "Aberta")
        last = receive_comanda_payment(self.session, self.comanda, "Dinheiro", self.total - 5.0)
        self.assertTrue(last["closed"])
        self.assertEqual(self.comanda.status, "Fechada")
        movements = self.session.scalars(
            select(CashMovement).where(CashMovement.description == f"Comanda #{self.comanda.id}")
        ).all()
        self.assertEqual({item.method for item in movements}, {"Pix", "Dinheiro"})
        self.assertAlmostEqual(sum(item.amount for item in movements), self.total)
        self.assertEqual(self.session.scalar(select(func.count(ComandaPayment.id))), 2)

    def test_payment_cannot_exceed_balance_or_be_zero(self):
        with self.assertRaisesRegex(ValueError, "excede"):
            receive_comanda_payment(self.session, self.comanda, "Pix", self.total + 0.01)
        with self.assertRaisesRegex(ValueError, "maior que zero"):
            receive_comanda_payment(self.session, self.comanda, "Pix", 0)

    def test_close_comanda_receives_only_remaining_balance(self):
        receive_comanda_payment(self.session, self.comanda, "Pix", 5.0)
        received = close_comanda(self.session, self.comanda, "Débito")
        self.assertAlmostEqual(received, self.total - 5.0)
        self.assertEqual(self.comanda.status, "Fechada")

    def test_discount_requires_manager_pin(self):
        with self.assertRaisesRegex(ValueError, "não definiu"):
            apply_comanda_discount(self.session, self.comanda, 2.0, "", "1234")
        set_manager_pin(self.session, "4321", "Gerente")
        self.assertTrue(has_manager_pin(self.session))
        with self.assertRaisesRegex(ValueError, "incorreto"):
            apply_comanda_discount(self.session, self.comanda, 2.0, "", "1234")
        self.assertEqual(self.comanda.discount, 0)
        self.assertEqual(
            self.session.scalar(select(func.count(Audit.id)).where(Audit.action == "PIN do gerente inválido")), 1
        )

    def test_pin_must_have_four_digits(self):
        for invalid in ("123", "12345", "abcd", ""):
            with self.assertRaises(ValueError):
                set_manager_pin(self.session, invalid, "Gerente")

    def test_pin_locks_after_repeated_failures(self):
        set_manager_pin(self.session, "4321", "Gerente")
        for _ in range(5):
            with self.assertRaisesRegex(ValueError, "incorreto"):
                apply_comanda_discount(self.session, self.comanda, 1.0, "", "0000")
        with self.assertRaisesRegex(ValueError, "Muitas tentativas"):
            apply_comanda_discount(self.session, self.comanda, 1.0, "", "4321")

    def test_discount_reduces_amount_received_and_can_be_removed(self):
        set_manager_pin(self.session, "4321", "Gerente")
        apply_comanda_discount(self.session, self.comanda, 3.0, "Cortesia", "4321", "Gerente")
        balance = comanda_balance(self.session, self.comanda)
        self.assertAlmostEqual(balance["remaining"], self.total - 3.0)
        self.assertEqual(self.comanda.discount_reason, "Cortesia")
        remove_comanda_discount(self.session, self.comanda)
        self.assertAlmostEqual(comanda_balance(self.session, self.comanda)["remaining"], self.total)
        apply_comanda_discount(self.session, self.comanda, 3.0, "", "4321")
        received = close_comanda(self.session, self.comanda, "Pix")
        self.assertAlmostEqual(received, self.total - 3.0)
        self.assertEqual(self.comanda.status, "Fechada")

    def test_discount_must_leave_amount_to_pay(self):
        set_manager_pin(self.session, "4321", "Gerente")
        with self.assertRaisesRegex(ValueError, "ao menos"):
            apply_comanda_discount(self.session, self.comanda, self.total, "", "4321")
        with self.assertRaisesRegex(ValueError, "maior que zero"):
            apply_comanda_discount(self.session, self.comanda, 0, "", "4321")

    def test_percent_discount_conversion(self):
        self.assertEqual(discount_from_percent(100.0, 10), 10.0)
        self.assertEqual(discount_from_percent(33.33, 15), 5.0)
        with self.assertRaises(ValueError):
            discount_from_percent(100.0, 100)
    def test_discount_appears_in_sales_report(self):
        from pages.reports import _daily_sales_dataframe
        from utils.clock import local_today
        set_manager_pin(self.session, "4321", "Gerente")
        apply_comanda_discount(self.session, self.comanda, 3.0, "", "4321")
        close_comanda(self.session, self.comanda, "Pix")
        frame, summary = _daily_sales_dataframe(self.session, local_today())
        self.assertEqual(float(frame.iloc[0]["Desconto"]), 3.0)
        self.assertAlmostEqual(summary["discount"], 3.0)
        self.assertAlmostEqual(summary["total"], self.total - 3.0)

    def test_own_consumption_deducts_stock_without_touching_cash(self):
        from models.entities import OwnConsumption, Stock
        from services.domain import cash_balance, register_own_consumption
        from models.entities import CashSession
        product = self.session.scalar(select(Product).where(Product.name == "Café coado"))
        cash = self.session.scalar(select(CashSession).where(CashSession.is_open.is_(True)))
        balance_before = cash_balance(self.session, cash)
        from sqlalchemy import func as sa_func
        stock_before = self.session.scalar(select(sa_func.sum(Stock.quantity)))
        cost = register_own_consumption(self.session, product.id, 1, "Equipe")
        row = self.session.scalar(select(OwnConsumption))
        self.assertEqual(row.consumed_by, "Equipe")
        self.assertAlmostEqual(row.total_cost, cost)
        self.assertAlmostEqual(cash_balance(self.session, cash), balance_before)
        stock_after = self.session.scalar(select(sa_func.sum(Stock.quantity)))
        self.assertLess(stock_after, stock_before)
        with self.assertRaises(ValueError):
            register_own_consumption(self.session, product.id, 0)


if __name__ == "__main__":
    unittest.main()
