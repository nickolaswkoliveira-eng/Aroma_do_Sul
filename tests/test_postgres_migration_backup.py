import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import URL, create_engine, func, select
from sqlalchemy.orm import Session

import config
from database.connection import Base
from models.entities import (
    BackupRun, CashFlow, CashMovement, CashSession, Category, Comanda, Customer,
    Order, OrderItem, Payable, Product,
)
from services.database_health import database_health
from services.database_migration import MigrationError, migrate_database, migrate_with_safety_backup
from services.postgres_backup import (
    BackupError, SupabaseStorage, backup_name, decrypt_bytes, encrypt_bytes,
    parse_backup_name, run_backup, select_backups_to_keep,
)
from cryptography.fernet import Fernet


class ConfigTests(unittest.TestCase):
    def test_database_url_prefix_is_normalized(self):
        for prefix in ("postgresql://", "postgres://"):
            self.assertEqual(
                config.normalize_database_url(f"{prefix}u:p@host:5432/db"),
                "postgresql+psycopg://u:p@host:5432/db",
            )
        self.assertEqual(
            config.normalize_database_url("postgresql+psycopg://u:p@h/db"),
            "postgresql+psycopg://u:p@h/db",
        )
        self.assertEqual(config.normalize_database_url("sqlite:///x.db"), "sqlite:///x.db")

    def test_setting_prefers_environment(self):
        with patch.dict(os.environ, {"CHAVE_TESTE": "valor"}):
            self.assertEqual(config._setting("CHAVE_TESTE", "padrao"), "valor")
        self.assertEqual(config._setting("CHAVE_INEXISTENTE_XYZ", "padrao"), "padrao")


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.source = create_engine(URL.create("sqlite", database=str(root / "origem.db")))
        self.target = create_engine(URL.create("sqlite", database=str(root / "destino.db")))
        Base.metadata.create_all(self.source)
        with Session(self.source) as session:
            category = Category(name="Cafés")
            session.add(category)
            session.flush()
            product = Product(code="C1", name="Café", category_id=category.id, cost_price=2.5, sale_price=7.9)
            customer = Customer(name="Ana")
            session.add_all([product, customer])
            session.flush()
            order = Order(customer_id=customer.id, total=15.8, status="Finalizado")
            session.add(order)
            session.flush()
            session.add(OrderItem(order_id=order.id, product_id=product.id, quantity=2, unit_price=7.9))
            cash = CashSession(opening_balance=100.0)
            session.add(cash)
            session.flush()
            session.add(CashMovement(cash_session_id=cash.id, movement_type="Entrada", amount=15.8))
            session.add(Payable(description="Aluguel", amount=1234.56, competence=date(2026, 1, 1), due_date=date(2026, 1, 10)))
            session.add(CashFlow(reference_date=date(2026, 1, 2), entry_type="Entrada", amount=15.8))
            session.commit()

    def tearDown(self):
        self.source.dispose()
        self.target.dispose()
        self.directory.cleanup()

    def test_migration_copies_everything_and_validates(self):
        report = migrate_database(self.source, self.target)
        self.assertEqual(report["pedidos"]["rows"], 1)
        with Session(self.target) as session:
            self.assertEqual(session.scalar(select(func.count(OrderItem.id))), 1)
            self.assertAlmostEqual(session.scalar(select(func.sum(Payable.amount))), 1234.56)

    def test_migration_refuses_populated_target(self):
        migrate_database(self.source, self.target)
        with self.assertRaises(MigrationError):
            migrate_database(self.source, self.target)

    def test_failed_migration_leaves_target_empty(self):
        with patch("services.database_migration._table_summary", side_effect=[
            {"rows": 0}, {"rows": 99},
        ] + [{"rows": 0}] * 100):
            with self.assertRaises(MigrationError):
                migrate_database(self.source, self.target)
        with Session(self.target) as session:
            self.assertEqual(session.scalar(select(func.count(Order.id))), 0)

    def test_safety_backup_is_written_before_migration(self):
        report, backup_file = migrate_with_safety_backup(
            self.source, self.target, Path(self.directory.name) / "bk",
        )
        self.assertTrue(Path(backup_file).is_file())
        self.assertEqual(report["pedidos"]["rows"], 1)


class PostgresBackupTests(unittest.TestCase):
    def test_encryption_round_trip_and_wrong_key(self):
        key = Fernet.generate_key().decode()
        encrypted = encrypt_bytes(b"dados de venda", key)
        self.assertNotIn(b"dados de venda", encrypted)
        self.assertEqual(decrypt_bytes(encrypted, key), b"dados de venda")
        with self.assertRaises(BackupError):
            decrypt_bytes(encrypted, Fernet.generate_key().decode())
        with self.assertRaises(BackupError):
            encrypt_bytes(b"x", "chave-invalida")

    def test_backup_name_round_trip(self):
        moment = datetime(2026, 3, 4, 2, 0, 5)
        self.assertEqual(parse_backup_name(backup_name(moment)), moment)
        self.assertIsNone(parse_backup_name("outro-arquivo.txt"))

    def test_retention_keeps_daily_weekly_monthly_and_recent(self):
        now = datetime(2026, 10, 28, 3, 0, 0)
        names = [backup_name(now - timedelta(days=day)) for day in range(0, 800)]
        keep = select_backups_to_keep(names, now)
        kept_moments = sorted(parse_backup_name(name) for name in keep)
        self.assertIn(backup_name(now), keep)
        self.assertTrue(all(backup_name(now - timedelta(days=d)) in keep for d in range(0, 31)))
        self.assertLess(len(keep), 80)
        self.assertGreater(now - kept_moments[0], timedelta(days=300))
        self.assertLess(now - kept_moments[0], timedelta(days=400))

    def test_retention_never_removes_when_few_backups(self):
        now = datetime(2026, 10, 28)
        names = [backup_name(now - timedelta(days=500)), backup_name(now - timedelta(days=600))]
        self.assertEqual(select_backups_to_keep(names, now), set(names))

    def test_run_backup_uploads_verifies_and_prunes(self):
        now = datetime(2026, 10, 28, 3, 0, 0)
        key = Fernet.generate_key().decode()
        old = [backup_name(now - timedelta(days=d)) for d in (400, 401, 402, 403)]

        class FakeStorage:
            bucket = "b"

            def __init__(self):
                self.objects = {name: b"x" for name in old}
                self.deleted = []

            def upload(self, name, data):
                self.objects[name] = data

            def download(self, name):
                return self.objects[name]

            def list_names(self):
                return list(self.objects)

            def delete(self, names):
                self.deleted.extend(names)

        storage = FakeStorage()
        with patch("services.postgres_backup.dump_database", return_value=b"PGDMP-dados"):
            result = run_backup("postgresql://u:p@h/db", storage, key, now)
        self.assertEqual(decrypt_bytes(storage.objects[result["name"]], key), b"PGDMP-dados")
        self.assertTrue(set(storage.deleted).issubset(set(old)))
        self.assertIn(result["name"], storage.objects)

    def test_run_backup_detects_corrupted_upload(self):
        class BadStorage:
            bucket = "b"

            def upload(self, name, data):
                pass

            def download(self, name):
                return b"corrompido"

        with patch("services.postgres_backup.dump_database", return_value=b"dump"):
            with self.assertRaises(BackupError):
                run_backup("postgresql://u:p@h/db", BadStorage(), Fernet.generate_key().decode(), datetime.now())

    def test_storage_object_path_is_encoded(self):
        storage = SupabaseStorage("https://x.supabase.co/", "k", "bucket")
        self.assertEqual(storage.base, "https://x.supabase.co/storage/v1")
        self.assertEqual(storage._object_path("a b.enc"), "/object/bucket/a%20b.enc")


class DatabaseHealthExternalBackupTests(unittest.TestCase):
    def test_sqlite_health_still_reports_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(URL.create("sqlite", database=str(Path(directory) / "a.db")))
            Base.metadata.create_all(engine)
            result = database_health(engine, Path(directory) / "bk")
            engine.dispose()
        self.assertTrue(result["connected"])
        self.assertEqual(result["integrity"], "ok")


class AlembicEmptyDatabaseTests(unittest.TestCase):
    def test_upgrade_creates_full_schema_on_empty_database(self):
        import subprocess
        import sys
        from sqlalchemy import inspect

        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "novo.db"
            environment = dict(os.environ, DATABASE_URL=f"sqlite:///{database.as_posix()}")
            completed = subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=root, env=environment, capture_output=True, text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            engine = create_engine(f"sqlite:///{database.as_posix()}")
            tables = set(inspect(engine).get_table_names())
            engine.dispose()
        expected = {table.name for table in Base.metadata.sorted_tables}
        self.assertTrue(expected <= tables, f"faltando: {expected - tables}")


if __name__ == "__main__":
    unittest.main()
