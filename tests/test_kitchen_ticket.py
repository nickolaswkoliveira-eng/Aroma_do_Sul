import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models.entities import Base, Category, Customer, Order, OrderItem, Product
from services.kitchen_ticket import build_kitchen_ticket_html


class KitchenTicketTests(unittest.TestCase):
    def test_ticket_has_items_table_and_escapes_html(self):
        engine = create_engine("sqlite://", poolclass=StaticPool)
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine)() as session:
            customer = Customer(name="<Ana>")
            product = Product(code="B1", name="Bolo de cenoura", sale_price=10)
            session.add_all([customer, product])
            session.flush()
            order = Order(customer_id=customer.id, table_number=3, notes="sem açúcar", total=20)
            session.add(order)
            session.flush()
            session.add(OrderItem(order_id=order.id, product_id=product.id, quantity=2, unit_price=10, notes="aquecer"))
            session.commit()
            html = build_kitchen_ticket_html(session, order, auto_print=True)
        self.assertIn("2x</b> Bolo de cenoura", html)
        self.assertIn("MESA 03", html)
        self.assertIn("&lt;Ana&gt;", html)
        self.assertIn("aquecer", html)
        self.assertIn("window.print", html)
        self.assertIn("80mm", html)
