import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path

from sqlalchemy import URL, create_engine, text

from services.database_backup import (
    create_automatic_backup, export_sqlite_backup, latest_automatic_backup,
)


class DatabaseBackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)
        self.database_path = self.directory / "cafeteria.db"
        self.backup_directory = self.directory / "backups"
        self.engine = create_engine(URL.create("sqlite", database=str(self.database_path)))
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TABLE vendas (id INTEGER PRIMARY KEY, total INTEGER)"))
            connection.execute(text("INSERT INTO vendas (total) VALUES (1250)"))

    def tearDown(self):
        self.engine.dispose()
        self.temporary_directory.cleanup()

    def test_creates_valid_snapshot_and_reuses_current_interval(self):
        now = datetime(2026, 10, 21, 19, 17)
        backup_path = create_automatic_backup(
            self.engine, self.backup_directory, now=now,
        )
        repeated_path = create_automatic_backup(
            self.engine, self.backup_directory, now=now.replace(minute=19),
        )

        self.assertEqual(backup_path.name, "cafeteria-20261021-1915.sqlite3")
        self.assertEqual(repeated_path, backup_path)
        self.assertEqual(latest_automatic_backup(self.backup_directory), backup_path)
        with closing(sqlite3.connect(backup_path)) as connection:
            self.assertEqual(
                connection.execute("SELECT total FROM vendas").fetchone()[0], 1250,
            )
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_retention_removes_oldest_automatic_snapshots(self):
        base = datetime(2026, 10, 21, 10, 0)
        for interval in range(3):
            create_automatic_backup(
                self.engine,
                self.backup_directory,
                retention_count=2,
                now=base.replace(minute=interval * 15),
            )

        backups = sorted(self.backup_directory.glob("cafeteria-*.sqlite3"))
        self.assertEqual(len(backups), 2)
        self.assertEqual(backups[0].name, "cafeteria-20261021-1015.sqlite3")

    def test_export_returns_a_verified_copy_of_current_database(self):
        backup_data = export_sqlite_backup(self.engine)
        exported_path = self.directory / "download.sqlite3"
        exported_path.write_bytes(backup_data)

        with closing(sqlite3.connect(exported_path)) as connection:
            self.assertEqual(
                connection.execute("SELECT total FROM vendas").fetchone()[0], 1250,
            )
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_does_not_create_backup_when_database_file_is_missing(self):
        self.engine.dispose()
        self.database_path.unlink()

        backup_path = create_automatic_backup(
            self.engine, self.backup_directory,
        )

        self.assertIsNone(backup_path)
        self.assertFalse(self.backup_directory.exists())


if __name__ == "__main__":
    unittest.main()
