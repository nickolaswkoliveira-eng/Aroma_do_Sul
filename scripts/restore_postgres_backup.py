"""Restaura um backup criptografado em um banco PostgreSQL de TESTE.

Uso:
  py -3 scripts/restore_postgres_backup.py --file cafeteria-AAAAMMDD-HHMMSS.dump.enc --target "postgresql://..."
Defina BACKUP_ENCRYPTION_KEY no ambiente. Por segurança, restaurar sobre o banco
configurado em DATABASE_URL exige --allow-production.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import DATABASE_URL, normalize_database_url
from services.postgres_backup import BackupError, decrypt_bytes, restore_dump


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="Arquivo .dump.enc baixado do Storage.")
    parser.add_argument("--target", required=True, help="URL do banco de destino.")
    parser.add_argument("--allow-production", action="store_true")
    arguments = parser.parse_args()

    target = normalize_database_url(arguments.target)
    if target == DATABASE_URL and not arguments.allow_production:
        print("ERRO: o destino é o banco de produção. Use um banco de teste ou --allow-production.", file=sys.stderr)
        return 2
    key = os.getenv("BACKUP_ENCRYPTION_KEY")
    if not key:
        print("ERRO: defina BACKUP_ENCRYPTION_KEY.", file=sys.stderr)
        return 2
    try:
        dump = decrypt_bytes(Path(arguments.file).read_bytes(), key)
        restore_dump(dump, target)
    except (BackupError, OSError) as error:
        print(f"ERRO: {error}", file=sys.stderr)
        return 1
    print("Restauração concluída. Confira contagens e totais antes de usar o banco.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
