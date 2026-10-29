import unittest
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import plotly.graph_objects as go
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from database.connection import Base
from models.entities import (
    Audit, CashMovement, CashSession, Comanda, ComandaOrder, DemoRecord, Order,
    Payable, Product, Receivable, RecipeItem, Role, Stock, StockMovement, User,
)
from services.domain import (
    add_cash_movement, cancel_order, close_cash, close_comanda, cmv_for_period, create_order,
    open_cash, purchase_recommendations, product_unit_costs, stock_level,
    update_order_status,
)
from services.demo_data import DEMO_MARKER, populate_demo_data
from services.demo_environment import clear_demo_records
from services.seed import seed_demo_data
from components.charts import apply_chart_theme, format_sales_series
from utils.clock import local_now, local_today
from utils.formatting import date_only, date_time, time_only


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        seed_demo_data(self.session)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_order_deducts_recipe_when_preparation_starts(self):
        product = self.session.scalar(select(Product).where(Product.name == "Cappuccino"))
        recipe = self.session.scalar(select(RecipeItem).where(RecipeItem.product_id == product.id).limit(1))
        stock = self.session.scalar(select(Stock).where(Stock.product_id == recipe.ingredient_id))
        initial_quantity = stock.quantity
        order = create_order(self.session, [{"product_id": product.id, "quantity": 1}])
        update_order_status(self.session, order, "Em preparo")
        self.assertAlmostEqual(stock.quantity, initial_quantity - recipe.quantity)
        with self.assertRaises(ValueError):
            update_order_status(self.session, order, "Em preparo")
        self.assertAlmostEqual(stock.quantity, initial_quantity - recipe.quantity)

    def test_finalized_order_opens_editable_comanda_and_closes_through_cash(self):
        product = self.session.scalar(select(Product).where(Product.name == "Café coado"))
        with patch("services.domain.MODO_DEMONSTRACAO", True):
            first_order = create_order(
                self.session, [{"product_id": product.id, "quantity": 1}],
                customer_name="Ana",
            )
            for status in ("Em preparo", "Pronto", "Entregue", "Finalizado"):
                update_order_status(self.session, first_order, status)

            comanda = self.session.scalar(select(Comanda).where(Comanda.status == "Aberta"))
            self.assertIsNotNone(comanda)
            self.assertEqual(comanda.total, first_order.total)
            self.assertEqual(
                self.session.scalar(
                    select(ComandaOrder.order_id).where(
                        ComandaOrder.comanda_id == comanda.id
                    )
                ),
                first_order.id,
            )

            second_order = create_order(
                self.session,
                [{"product_id": product.id, "quantity": 2}],
                comanda_id=comanda.id,
            )
            self.assertEqual(comanda.total, first_order.total + second_order.total)
            self.assertEqual(
                self.session.scalar(
                    select(ComandaOrder.comanda_id).where(
                        ComandaOrder.order_id == second_order.id
                    )
                ),
                comanda.id,
            )
            with self.assertRaisesRegex(ValueError, "Finalize os pedidos"):
                close_comanda(self.session, comanda, "Pix")

            for status in ("Em preparo", "Pronto", "Entregue", "Finalizado"):
                update_order_status(self.session, second_order, status)
            open_cash(self.session, 20)
            received = close_comanda(self.session, comanda, "Pix", "Operador")

        self.assertEqual(received, first_order.total + second_order.total)
        self.assertEqual(comanda.status, "Fechada")
        movement = self.session.scalar(
            select(CashMovement).where(
                CashMovement.description == f"Comanda #{comanda.id}"
            )
        )
        self.assertIsNotNone(movement)
        self.assertEqual(movement.method, "Pix")
        self.assertEqual(movement.amount, received)
        self.assertGreater(
            self.session.scalar(
                select(func.count(DemoRecord.id)).where(
                    DemoRecord.entity == "comanda_pedidos",
                    DemoRecord.demo.is_(True),
                )
            ),
            0,
        )
        clear_demo_records(self.session)
        self.session.commit()
        self.assertEqual(
            self.session.scalar(
                select(func.count(Comanda.id)).where(Comanda.status == "Aberta")
            ),
            0,
        )

    def test_insufficient_ingredient_stock_blocks_order(self):
        product = self.session.scalar(select(Product).where(Product.name == "Cappuccino"))
        recipe = self.session.scalar(select(RecipeItem).where(RecipeItem.product_id == product.id).limit(1))
        stock = self.session.scalar(select(Stock).where(Stock.product_id == recipe.ingredient_id))
        stock.quantity = 0
        self.session.commit()
        with self.assertRaises(ValueError):
            create_order(self.session, [{"product_id": product.id, "quantity": 1}])

    def test_cancelled_order_returns_preparation_stock_and_is_audited(self):
        product = self.session.scalar(select(Product).where(Product.name == "Cappuccino"))
        recipe = self.session.scalar(select(RecipeItem).where(RecipeItem.product_id == product.id).limit(1))
        stock = self.session.scalar(select(Stock).where(Stock.product_id == recipe.ingredient_id))
        initial_quantity = stock.quantity
        order = create_order(self.session, [{"product_id": product.id, "quantity": 1}])
        update_order_status(self.session, order, "Em preparo")
        cancel_order(self.session, order, "Cliente desistiu", "Operador")

        self.assertEqual(order.status, "Cancelado")
        self.assertAlmostEqual(stock.quantity, initial_quantity)
        self.assertIsNotNone(self.session.scalar(select(Audit.id).where(Audit.action == "Pedido cancelado")))
        with self.assertRaisesRegex(ValueError, "já foi cancelado"):
            cancel_order(self.session, order, "Segunda desistência", "Operador")

    def test_product_without_recipe_uses_its_own_stock(self):
        product = Product(code="TEST001", name="Produto de estoque", sale_price=5, cost_price=2)
        self.session.add(product)
        self.session.flush()
        stock = Stock(product_id=product.id, quantity=2, minimum_quantity=1)
        self.session.add(stock)
        self.session.commit()
        with self.assertRaises(ValueError):
            create_order(self.session, [{"product_id": product.id, "quantity": 3}])
        order = create_order(self.session, [{"product_id": product.id, "quantity": 1}])
        update_order_status(self.session, order, "Em preparo")
        self.assertEqual(stock.quantity, 1)

    def test_visible_datetime_formats_hide_subseconds(self):
        value = datetime(2026, 10, 18, 7, 35, 42, 123456)
        self.assertEqual(time_only(value), "07:35")
        self.assertEqual(date_only(value), "18/10/2026")
        self.assertEqual(date_time(value), "18/10/2026 07:35")

    def test_chart_labels_follow_selected_period(self):
        orders = [
            SimpleNamespace(created_at=datetime(2026, 10, 18, 7, 35, 59, 123), total=10),
            SimpleNamespace(created_at=datetime(2026, 10, 18, 8, 45, 12, 999), total=20),
        ]
        self.assertEqual(format_sales_series(orders, "Dia")[0], ["07:00", "08:00"])
        self.assertEqual(format_sales_series(orders, "Semana")[0], ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"])
        self.assertEqual(format_sales_series(orders, "Mês")[0], ["18/10"])
        self.assertEqual(format_sales_series(orders, "Ano")[0], ["Out/2026"])

    def test_sales_chart_fills_missing_hours_and_dates(self):
        orders = [
            SimpleNamespace(created_at=datetime(2026, 10, 18, 7, 35), total=10),
            SimpleNamespace(created_at=datetime(2026, 10, 18, 9, 45), total=20),
        ]
        labels, values = format_sales_series(orders, "Dia", date(2026, 10, 18), date(2026, 10, 18))
        self.assertEqual(len(labels), 24)
        self.assertEqual(values[7], 10)
        self.assertEqual(values[8], 0)
        self.assertEqual(values[9], 20)
        labels, values = format_sales_series(
            orders, "Mês", date(2026, 10, 18), date(2026, 10, 20)
        )
        self.assertEqual(labels, ["18/10", "19/10", "20/10"])
        self.assertEqual(values, [30, 0, 0])

    def test_application_clock_uses_configured_local_wall_time(self):
        self.assertIsNone(local_now().tzinfo)
        self.assertEqual(local_today(), local_now().date())

    def test_single_point_chart_hides_value_axis_and_centers_marker(self):
        figure = go.Figure(go.Scatter(x=["12:00"], y=[15]))
        apply_chart_theme(figure, single_point=True)
        self.assertEqual(figure.layout.xaxis.type, "category")
        self.assertFalse(figure.layout.yaxis.visible)
        self.assertEqual(figure.data[0].marker.size, 16)

    def test_purchase_suggestion_uses_consumption_trend_and_coverage(self):
        product = self.session.scalar(select(Product).where(Product.name == "Leite integral"))
        stock = self.session.scalar(select(Stock).where(Stock.product_id == product.id))
        stock.quantity = 4
        stock.minimum_quantity = 25
        self.session.add(StockMovement(product_id=product.id, movement_type="Saída", quantity=21,
                                       created_at=local_now() - timedelta(days=1)))
        self.session.add(StockMovement(product_id=product.id, movement_type="Saída", quantity=14,
                                       created_at=local_now() - timedelta(days=8)))
        self.session.commit()
        suggestion = next(item for item in purchase_recommendations(self.session) if item["product"].id == product.id)
        self.assertAlmostEqual(suggestion["daily_average"], 2.7)
        self.assertAlmostEqual(suggestion["days_remaining"], 4 / 2.7)
        self.assertEqual(suggestion["suggested_quantity"], 46)
        self.assertIn("acelerou", suggestion["reason"])

    def test_cmv_uses_recipe_cost(self):
        product = self.session.scalar(select(Product).where(Product.name == "Cappuccino"))
        create_order(self.session, [{"product_id": product.id, "quantity": 1}])
        metrics = cmv_for_period(self.session, local_today(), local_today())
        self.assertEqual(metrics["revenue"], 12)
        self.assertAlmostEqual(metrics["cost"], 2.016)
        self.assertAlmostEqual(metrics["ratio"], 2.016 / 12)
        self.assertAlmostEqual(product_unit_costs(self.session, {product.id})[product.id], metrics["cost"])

    def test_products_without_recipes_use_their_registered_cost(self):
        product = Product(code="COST001", name="Sem ficha", cost_price=3.5, sale_price=8)
        self.session.add(product)
        self.session.commit()
        self.assertEqual(product_unit_costs(self.session, {product.id})[product.id], 3.5)

    def test_stock_levels_use_consistent_thresholds(self):
        self.assertEqual(stock_level(0, 10), "Zerado")
        self.assertEqual(stock_level(2, 10), "Crítico")
        self.assertEqual(stock_level(2.01, 10), "Atenção")
        self.assertEqual(stock_level(5, 10), "Adequado")
        self.assertEqual(stock_level(1, 0), "Adequado")

    def test_demo_data_is_ninety_days_marked_and_repeatable(self):
        demo_engine = create_engine("sqlite://")
        Base.metadata.create_all(demo_engine)
        try:
            with Session(demo_engine) as demo_session:
                admin_role = Role(name="ADMINISTRADOR")
                demo_session.add(admin_role)
                demo_session.flush()
                demo_session.add(User(
                    username="demo-admin", full_name="Admin Demo", role_id=admin_role.id
                ))
                demo_session.commit()
                role_count = demo_session.scalar(select(func.count(Role.id)))
                user_count = demo_session.scalar(select(func.count(User.id)))
                fixed_now = datetime.combine(local_today(), time(10, 15))
                with patch("services.demo_data.local_now", return_value=fixed_now):
                    first = populate_demo_data(demo_session)
                self.assertEqual(first["days"], 90)
                self.assertGreater(first["orders"], 1000)
                self.assertEqual(demo_session.scalar(select(func.count(Order.id))), first["orders"])
                self.assertEqual(demo_session.scalar(select(func.count(CashSession.id))), 90)
                self.assertGreater(demo_session.scalar(select(func.count(CashMovement.id))), 0)
                self.assertGreater(demo_session.scalar(select(func.count(Payable.id))), 0)
                self.assertGreater(demo_session.scalar(select(func.count(Receivable.id))), 0)
                self.assertEqual(demo_session.scalar(select(func.count(Role.id))), role_count)
                self.assertEqual(demo_session.scalar(select(func.count(User.id))), user_count)
                self.assertEqual(first["audits"], demo_session.scalar(select(func.count(Audit.id))))
                self.assertGreater(first["cancelled_orders"], 0)
                self.assertGreater(first["comandas"], 0)
                audit_row = demo_session.scalar(
                    select(Audit).where(Audit.action == "Dados de demonstração gerados")
                )
                self.assertIn(DEMO_MARKER, audit_row.responsible)
                self.assertEqual(
                    demo_session.scalar(select(func.min(func.date(Order.created_at)))),
                    (local_today() - timedelta(days=89)).isoformat(),
                )
                self.assertLessEqual(
                    demo_session.scalar(select(func.max(Order.created_at))), fixed_now
                )
                self.assertLessEqual(
                    demo_session.scalar(select(func.max(CashMovement.created_at))), fixed_now
                )
                self.assertLessEqual(
                    demo_session.scalar(select(func.max(StockMovement.created_at))), fixed_now
                )
                second = populate_demo_data(demo_session)
                self.assertEqual(second["orders"], first["orders"])
                self.assertEqual(
                    demo_session.scalar(select(func.count(Order.id))), first["orders"]
                )
                self.assertEqual(
                    demo_session.scalar(select(func.count(Audit.id))), second["audits"]
                )
                self.assertEqual(demo_session.scalar(select(func.count(Role.id))), role_count)
                self.assertEqual(demo_session.scalar(select(func.count(User.id))), user_count)
        finally:
            demo_engine.dispose()

    def test_cash_balance_and_close(self):
        cash = open_cash(self.session, 100, "Operador teste")
        add_cash_movement(self.session, cash, "Entrada", "Pix", 25, "Venda teste")
        add_cash_movement(self.session, cash, "Saída", "Sangria", 10, "Sangria teste")
        final_balance = close_cash(self.session, cash)
        self.assertEqual(final_balance, 115)
        self.assertFalse(cash.is_open)
        next_cash = open_cash(self.session, 50)
        self.assertTrue(next_cash.is_open)


if __name__ == "__main__":
    unittest.main()
