"""Verifica a integração com Supabase PostgreSQL e Storage sem imprimir credenciais.

Uso: py -3 scripts/check_integration.py
Lê DATABASE_URL, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY e BACKUP_ENCRYPTION_KEY
do ambiente (ou, para DATABASE_URL, dos segredos do Streamlit).
"""
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url

import config
from models.entities import Base

OK, WARN, FAIL = "OK", "PENDENTE", "FALHOU"
results: list[tuple[str, str, str]] = []


def report(area: str, status: str, detail: str) -> None:
    results.append((area, status, detail))
    print(f"[{status}] {area}: {detail}")


def check_postgres() -> None:
    url = make_url(config.DATABASE_URL)
    if not url.drivername.startswith("postgresql"):
        report("PostgreSQL", FAIL, f"DATABASE_URL não aponta para PostgreSQL (driver atual: {url.drivername}).")
        return
    engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, connect_args={"connect_timeout": 15})
    try:
        with engine.connect() as connection:
            database = connection.scalar(text("SELECT current_database()"))
            version = connection.scalar(text("SHOW server_version"))
            tables = sorted(inspect(connection).get_table_names())
            revision = None
            if "alembic_version" in tables:
                revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            columns = {c["name"]: str(c["type"]) for c in inspect(connection).get_columns("pedidos")} if "pedidos" in tables else {}
            counts = {
                table.name: connection.scalar(select(func.count()).select_from(table))
                for table in Base.metadata.sorted_tables if table.name in tables
            }
    except Exception as error:
        report("PostgreSQL", FAIL, f"sem conexão ({type(error).__name__}). Verifique IPv6/Session pooler, senha e sslmode.")
        return
    report("PostgreSQL", OK, f"host={url.host} banco={database} driver={url.drivername} versão={version} conexão=OK")

    head = ScriptDirectory.from_config(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))).get_current_head()
    if revision == head:
        report("Migrações", OK, f"revisão atual={revision} (head); nenhuma pendente.")
    else:
        report("Migrações", WARN, f"revisão atual={revision or 'nenhuma'}, head={head}. Rode: py -3 -m alembic upgrade head")
    print("  Tabelas:", ", ".join(tables) or "(nenhuma)")
    if columns.get("total") and "NUMERIC" not in columns["total"].upper():
        report("Colunas monetárias", WARN, f"pedidos.total é {columns['total']}; aplique a migração 0002.")
    print("  Linhas por tabela:", json.dumps(counts, ensure_ascii=False))


def check_storage() -> None:
    url = config._setting("SUPABASE_URL")
    key = config._setting("SUPABASE_SERVICE_ROLE_KEY")
    bucket = config._setting("SUPABASE_BACKUP_BUCKET", "database-backups")
    report("SUPABASE_URL", OK if url else WARN, "carregado" if url else "não carregado")
    report("SUPABASE_SERVICE_ROLE_KEY", OK if key else WARN, "carregada" if key else "não carregada")
    if not (url and key):
        report("Storage", WARN, "não foi possível testar o bucket sem URL e chave.")
        return
    headers = {"Authorization": f"Bearer {key}", "apikey": key}
    request = urllib.request.Request(f"{url.rstrip('/')}/storage/v1/bucket/{bucket}", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            info = json.loads(response.read())
    except urllib.error.HTTPError as error:
        report("Storage", FAIL, f"bucket '{bucket}' inacessível (HTTP {error.code}); verifique se existe e a chave.")
        return
    except urllib.error.URLError as error:
        report("Storage", FAIL, f"serviço inacessível: {error.reason}")
        return
    if info.get("public"):
        report("Storage", FAIL, f"bucket '{bucket}' existe, mas é PÚBLICO. Torne-o privado.")
    else:
        report("Storage", OK, f"bucket '{bucket}' existe e é privado; acesso com a chave OK.")


def check_backup_requirements() -> None:
    for tool in ("pg_dump", "pg_restore"):
        report(tool, OK if shutil.which(tool) else WARN, "instalado" if shutil.which(tool) else "não instalado neste computador (o workflow do GitHub instala o seu)")
    key = config._setting("BACKUP_ENCRYPTION_KEY")
    if not key:
        report("BACKUP_ENCRYPTION_KEY", WARN, "não carregada neste ambiente")
    else:
        try:
            from cryptography.fernet import Fernet
            Fernet(key.encode())
            report("BACKUP_ENCRYPTION_KEY", OK, "carregada e válida")
        except Exception:
            report("BACKUP_ENCRYPTION_KEY", FAIL, "carregada, mas inválida (use Fernet.generate_key())")


def main() -> int:
    print(f"DATABASE_URL carregado de: {'ambiente/segredos' if config._setting('DATABASE_URL') else 'padrão (SQLite local)'}")
    check_postgres()
    check_storage()
    check_backup_requirements()
    return 1 if any(status == FAIL for _, status, _ in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
