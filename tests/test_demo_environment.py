import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from sqlalchemy import URL, create_engine, func, select
from sqlalchemy.orm import Session

from database.connection import Base
from models.entities import (
    Audit, Category, DemoRecord, Order, OrderItem, Product, Role, User,
)
from services.demo_data import populate_demo_data
from services.demo_environment import (
    delete_demo_data, export_demo_data, restore_demo_backup,
)


class DemoEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)
        self.database_path = self.directory / "demo.sqlite3"
        self.engine = create_engine(URL.create("sqlite", database=str(self.database_path)))
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.session.add(Role(name="ADMINISTRADOR"))
        self.session.flush()
        self.session.add(User(
            username="demo-admin",
            full_name="Admin Demo",
            password_hash="test-hash",
            role_id=self.session.scalar(select(Role.id).where(Role.name == "ADMINISTRADOR")),
        ))
        self.session.commit()
        self.backup_directory = self.directory / "backups"

    def tearDown(self):
        self.session.close()
        self.engine.dispose()
        self.temporary_directory.cleanup()

    def _populate(self):
        return populate_demo_data(self.session)

    def test_cleanup_deletes_only_marked_rows_and_keeps_automatic_backup(self):
        self._populate()
        real_category = Category(name="Real")
        self.session.add(real_category)
        self.session.flush()
        real_product = Product(
            code="REAL001", name="Produto real", category_id=real_category.id,
            cost_price=2, sale_price=5,
        )
        self.session.add(real_product)
        self.session.add(Audit(action="Registro real preservado"))
        self.session.commit()

        deleted_count, backup_path = delete_demo_data(
            self.session, "ADMIN", "Dados de demonstração apagados",
            self.engine, self.backup_directory,
        )

        self.assertGreater(deleted_count, 0)
        self.assertTrue(backup_path.is_file())
        self.assertEqual(self.session.scalar(select(func.count(Order.id))), 0)
        self.assertIsNotNone(self.session.scalar(
            select(Category.id).where(Category.name == "Real")
        ))
        self.assertIsNotNone(self.session.scalar(
            select(Product.id).where(Product.code == "REAL001")
        ))
        self.assertIsNotNone(self.session.scalar(
            select(User.id).where(User.username == "demo-admin")
        ))
        self.assertEqual(
            self.session.scalar(select(func.count(DemoRecord.id)).where(DemoRecord.demo.is_(True))),
            0,
        )
        self.assertIsNotNone(self.session.scalar(
            select(Audit.id).where(Audit.action == "Dados de demonstração apagados")
        ))
        with closing(sqlite3.connect(backup_path)) as backup:
            self.assertGreater(
                backup.execute("SELECT COUNT(*) FROM pedidos").fetchone()[0], 1000
            )

    def test_cleanup_refuses_to_break_unmarked_relationships(self):
        self._populate()
        product = self.session.scalar(select(Product).where(Product.code == "CAF001"))
        order = Order(status="Recebido", total=5)
        self.session.add(order)
        self.session.flush()
        self.session.add(OrderItem(
            order_id=order.id, product_id=product.id, quantity=1, unit_price=5,
        ))
        self.session.commit()

        with self.assertRaisesRegex(ValueError, "registros não demonstrativos"):
            delete_demo_data(
                self.session, "ADMIN", "Dados de demonstração apagados",
                self.engine, self.backup_directory,
            )

        self.assertGreater(self.session.scalar(select(func.count(Order.id))), 1000)
        self.assertTrue(list(self.backup_directory.glob("demo-backup-*.sqlite3")))

    def test_regeneration_preserves_nonconflicting_unmarked_records(self):
        self._populate()
        real_category = Category(name="Personalizada")
        self.session.add(real_category)
        self.session.flush()
        self.session.add(Product(
            code="REAL002", name="Produto real", category_id=real_category.id,
        ))
        self.session.commit()

        self._populate()

        self.assertIsNotNone(self.session.scalar(
            select(Category.id).where(Category.name == "Personalizada")
        ))
        self.assertIsNotNone(self.session.scalar(
            select(Product.id).where(Product.code == "REAL002")
        ))
        self.assertGreater(self.session.scalar(select(func.count(Order.id))), 1000)

    def test_generation_refuses_to_overwrite_unmarked_catalog_conflicts(self):
        self.session.add(Category(name="Cafés"))
        self.session.commit()

        with self.assertRaisesRegex(ValueError, "demo=True"):
            self._populate()

        self.assertIsNotNone(self.session.scalar(
            select(Category.id).where(Category.name == "Cafés")
        ))
        self.assertEqual(self.session.scalar(select(func.count(Order.id))), 0)

    def test_import_restores_demo_data_and_preserves_accounts_and_audit(self):
        self._populate()
        self.session.add(Audit(action="Auditoria local preservada"))
        self.session.commit()
        backup_data = export_demo_data(self.session, "ADMIN", self.engine)
        self.assertGreater(len(backup_data), 0)

        delete_demo_data(
            self.session, "ADMIN", "Dados de demonstração apagados",
            self.engine, self.backup_directory,
        )
        backup_path = restore_demo_backup(
            self.session, backup_data, "ADMIN", self.engine, self.backup_directory,
        )

        self.assertTrue(backup_path.is_file())
        self.assertGreater(self.session.scalar(select(func.count(Order.id))), 1000)
        user = self.session.scalar(select(User).where(User.username == "demo-admin"))
        self.assertEqual(user.password_hash, "test-hash")
        audit_actions = set(self.session.scalars(select(Audit.action)))
        self.assertIn("Auditoria local preservada", audit_actions)
        self.assertIn("Dados de demonstração apagados", audit_actions)
        self.assertIn("Backup do ambiente de demonstração importado", audit_actions)

    def test_invalid_import_does_not_replace_the_current_database(self):
        self._populate()
        order_count = self.session.scalar(select(func.count(Order.id)))

        with self.assertRaisesRegex(ValueError, "backup SQLite válido"):
            restore_demo_backup(self.session, b"not a sqlite backup", "ADMIN", self.engine)

        self.assertEqual(self.session.scalar(select(func.count(Order.id))), order_count)

    def test_import_adds_comanda_tables_to_legacy_backup(self):
        legacy_path = self.directory / "legacy-demo.sqlite3"
        legacy_engine = create_engine(URL.create("sqlite", database=str(legacy_path)))
        legacy_tables = [
            table for table in Base.metadata.sorted_tables
            if table.name not in {"comandas", "comanda_pedidos"}
        ]
        try:
            Base.metadata.create_all(legacy_engine, tables=legacy_tables)
        finally:
            legacy_engine.dispose()
        with closing(sqlite3.connect(legacy_path)) as connection:
            connection.execute("PRAGMA user_version = 1")
            connection.commit()

        restore_demo_backup(
            self.session, legacy_path.read_bytes(), "ADMIN",
            self.engine, self.backup_directory,
        )

        with closing(sqlite3.connect(self.database_path)) as connection:
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertIn("comandas", tables)
        self.assertIn("comanda_pedidos", tables)

    def test_import_refuses_to_replace_unmarked_operational_data(self):
        self._populate()
        backup_data = export_demo_data(self.session, "ADMIN", self.engine)
        self.session.add(Product(code="REAL003", name="Produto real"))
        self.session.commit()

        with self.assertRaisesRegex(ValueError, "demo=True"):
            restore_demo_backup(self.session, backup_data, "ADMIN", self.engine)

        self.assertIsNotNone(self.session.scalar(
            select(Product.id).where(Product.code == "REAL003")
        ))


if __name__ == "__main__":
    unittest.main()
