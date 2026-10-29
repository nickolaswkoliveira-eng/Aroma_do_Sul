import unittest

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from database.connection import Base
from models.entities import (
    Audit, Category, Customer, DemoRecord, Order, Permission, Product, Role,
    RolePermission, User,
)
from services.demo_operacoes import (
    carregar_dados_demo, contar_registros_demo, limpar_dados_demo,
    registros_reais_por_tabela, validar_dados_demo,
)

BUSINESS_TABLES = {
    "categorias", "produtos", "ingredientes", "estoque", "ficha_tecnica",
    "movimentacoes_estoque", "clientes", "pedidos", "itens_pedido", "comandas",
    "comanda_pedidos", "caixa", "movimentacoes_caixa", "fluxo_caixa",
    "contas_pagar", "contas_receber", "auditoria",
}


class DemoOperationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        cls.session = Session(cls.engine)
        role = Role(name="ADMINISTRADOR")
        cls.session.add(role)
        cls.session.flush()
        permission = Permission(key="orders", description="Pedidos")
        cls.session.add(permission)
        cls.session.flush()
        cls.session.add_all([
            RolePermission(role_id=role.id, permission_id=permission.id),
            User(username="admin", full_name="Administrador", role_id=role.id),
        ])
        cls.session.commit()
        cls.result = carregar_dados_demo(cls.session)

    @classmethod
    def tearDownClass(cls):
        cls.session.close()
        cls.engine.dispose()

    def test_load_covers_every_business_table_and_validates(self):
        self.assertTrue(BUSINESS_TABLES <= set(self.result["por_tabela"]), self.result["por_tabela"])
        failed = [c for c in self.result["validacao"] if not c["ok"]]
        self.assertEqual(failed, [])
        self.assertGreater(len(self.result["validacao"]), 6)

    def test_every_table_has_enough_records_for_dashboards(self):
        counts = self.result["por_tabela"]
        self.assertGreaterEqual(counts["clientes"], 20)
        self.assertGreaterEqual(counts["produtos"], 20)
        self.assertGreater(counts["pedidos"], 2000)
        self.assertGreater(counts["itens_pedido"], counts["pedidos"])
        self.assertGreaterEqual(counts["caixa"], 90)
        self.assertGreater(counts["contas_pagar"], 15)
        self.assertGreater(counts["contas_receber"], 10)
        self.assertGreater(counts["auditoria"], 100)
        self.assertEqual(sum(counts.values()), self.session.scalar(select(func.count(DemoRecord.id))))

    def test_dashboard_and_report_queries_find_data(self):
        statuses = set(self.session.scalars(select(Order.status).distinct()))
        self.assertTrue({"Finalizado", "Cancelado"} <= statuses)
        self.assertGreater(self.result["gerado"]["cancelled_orders"], 0)
        self.assertGreater(self.result["gerado"]["comandas"], 0)

    def test_validation_detects_corrupted_order_total(self):
        order = self.session.scalar(select(Order).where(Order.status == "Finalizado"))
        original = order.total
        order.total = original + 10
        self.session.flush()
        try:
            failed = [c["verificacao"] for c in validar_dados_demo(self.session) if not c["ok"]]
            self.assertTrue(any("Total do pedido" in name or "Receita" in name for name in failed))
        finally:
            self.session.rollback()
        self.assertEqual(self.session.get(Order, order.id).total, original)

    def test_load_is_blocked_when_real_data_exists(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            session.add(Customer(name="Cliente Real"))
            session.commit()
            with self.assertRaises(ValueError):
                carregar_dados_demo(session)
            self.assertEqual(session.scalar(select(func.count(Order.id))), 0)
        engine.dispose()


class DemoCleanupTests(unittest.TestCase):
    def test_cleanup_removes_only_demo_and_preserves_everything_else(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            role = Role(name="ADMINISTRADOR")
            session.add(role)
            session.flush()
            session.add_all([
                User(username="admin", full_name="Administrador", role_id=role.id),
                Permission(key="reports", description="Relatórios"),
            ])
            session.commit()
            carregar_dados_demo(session)
            # Dados reais criados depois da demo, sem referência a registros demo.
            session.add_all([Category(name="Categoria Real"), Customer(name="Cliente Real")])
            session.commit()
            real_before = registros_reais_por_tabela(session)
            self.assertEqual(real_before, {"categorias": 1, "clientes": 1})

            outcome = limpar_dados_demo(session)
            self.assertGreater(outcome["removidos"], 5000)
            self.assertEqual(contar_registros_demo(session), {})
            self.assertEqual(registros_reais_por_tabela(session), real_before)
            self.assertEqual(session.scalar(select(func.count(User.id))), 1)
            self.assertEqual(session.scalar(select(func.count(Role.id))), 1)
            self.assertEqual(session.scalar(select(func.count(Permission.id))), 1)
            self.assertEqual(session.scalar(select(func.count(Order.id))), 0)
            self.assertEqual(session.scalar(select(func.count(Product.id))), 0)
            self.assertEqual(session.scalar(select(func.count(Audit.id))), 0)

            # A rotina é idempotente e a carga pode ser repetida depois da limpeza.
            self.assertEqual(limpar_dados_demo(session)["removidos"], 0)
        engine.dispose()

    def test_cleanup_is_blocked_when_real_record_references_demo_data(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            carregar_dados_demo(session)
            demo_category = session.scalar(select(Category).where(Category.name == "Cafés"))
            session.add(Product(code="REAL01", name="Produto Real", category_id=demo_category.id,
                                cost_price=1, sale_price=5))
            session.commit()
            with self.assertRaises(ValueError):
                limpar_dados_demo(session)
            self.assertGreater(sum(contar_registros_demo(session).values()), 0)
            self.assertIsNotNone(session.scalar(select(Product).where(Product.code == "REAL01")))
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
