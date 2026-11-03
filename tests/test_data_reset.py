import unittest

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from models.entities import (
    Audit, Base, Category, Comanda, ComandaOrder, Order, OrderItem, Permission, Product,
    RecipeItem, Role, Stock, User,
)
from services.data_reset import build_backup_download, clear_all_data, export_portable_backup


class PortableBackupTests(unittest.TestCase):
    def test_portable_backup_copies_rows_and_skips_sessions(self):
        import sqlite3
        import tempfile
        from contextlib import closing
        from pathlib import Path

        engine = create_engine("sqlite://", poolclass=__import__("sqlalchemy.pool", fromlist=["StaticPool"]).StaticPool)
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine)() as session:
            session.add_all([Category(name="Bolos"), Product(code="B1", name="Bolo", sale_price=10.5)])
            session.commit()
        data = export_portable_backup(engine)
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "copy.sqlite3"
            copy.write_bytes(data)
            with closing(sqlite3.connect(copy)) as connection:
                tables = {row[0] for row in connection.execute("select name from sqlite_master")}
                product = connection.execute("select name, sale_price from produtos").fetchall()
            self.assertEqual(product, [("Bolo", 10.5)])
            self.assertNotIn("sessoes_usuario", tables)


class BackupDownloadTests(unittest.TestCase):
    def test_sqlite_backup_download_is_a_valid_database(self):
        import sqlite3
        import tempfile
        from contextlib import closing
        from datetime import datetime
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.sqlite3"
            engine = create_engine(f"sqlite:///{path}")
            Base.metadata.create_all(engine)
            data, name, mime = build_backup_download(engine, "", datetime(2026, 11, 2, 17, 0, 0))
            engine.dispose()
            self.assertEqual(name, "cafeteria-backup-20261102-170000.sqlite3")
            self.assertEqual(mime, "application/vnd.sqlite3")
            copy = Path(directory) / "copy.sqlite3"
            copy.write_bytes(data)
            with closing(sqlite3.connect(copy)) as connection:
                tables = {row[0] for row in connection.execute("select name from sqlite_master")}
            self.assertIn("produtos", tables)


class ClearAllDataTests(unittest.TestCase):
    def test_clears_everything_except_users_roles_and_permissions(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine)() as session:
            role = Role(name="ADMINISTRADOR")
            session.add_all([role, Permission(key="orders")])
            session.flush()
            session.add(User(username="admin", full_name="Admin", role_id=role.id))
            category = Category(name="Bolos")
            session.add(category)
            session.flush()
            cake = Product(code="B1", name="Bolo", category_id=category.id, sale_price=10)
            flour = Product(code="I1", name="Farinha", unit="kg")
            session.add_all([cake, flour])
            session.flush()
            session.add_all([Stock(product_id=flour.id, quantity=5),
                             RecipeItem(product_id=cake.id, ingredient_id=flour.id, quantity=1)])
            order = Order(total=10)
            comanda = Comanda(total=10)
            session.add_all([order, comanda])
            session.flush()
            session.add_all([OrderItem(order_id=order.id, product_id=cake.id, quantity=1, unit_price=10),
                             ComandaOrder(comanda_id=comanda.id, order_id=order.id),
                             Audit(action="Pedido criado")])
            session.commit()

            clear_all_data(session, "tester")

            for model in (Product, Category, Order, Comanda, Stock, RecipeItem):
                self.assertEqual(session.scalar(select(func.count()).select_from(model)), 0)
            self.assertEqual(session.scalar(select(func.count()).select_from(User)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(Role)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(Permission)), 1)
            audits = session.scalars(select(Audit)).all()
            self.assertEqual([a.action for a in audits], ["Limpeza total de dados"])


if __name__ == "__main__":
    unittest.main()
