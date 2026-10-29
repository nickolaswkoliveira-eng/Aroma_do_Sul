import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.engine import make_url

BACKUP_SUFFIX = ".dump.enc"
DAILY_DAYS = 30
WEEKLY_WEEKS = 12
MONTHLY_MONTHS = 12
MINIMUM_KEPT = 3


class BackupError(RuntimeError):
    pass


def backup_name(now: datetime) -> str:
    return f"cafeteria-{now:%Y%m%d-%H%M%S}{BACKUP_SUFFIX}"


def parse_backup_name(name: str) -> datetime | None:
    base = name.rsplit("/", 1)[-1]
    if not (base.startswith("cafeteria-") and base.endswith(BACKUP_SUFFIX)):
        return None
    try:
        return datetime.strptime(base[len("cafeteria-"):-len(BACKUP_SUFFIX)], "%Y%m%d-%H%M%S")
    except ValueError:
        return None


def select_backups_to_keep(names: list[str], now: datetime) -> set[str]:
    """Retenção: o mais recente de cada dia (30 dias), semana (12) e mês (12)."""
    dated = sorted(
        ((parse_backup_name(name), name) for name in names),
        key=lambda item: item[0] or datetime.min,
        reverse=True,
    )
    dated = [(moment, name) for moment, name in dated if moment is not None]
    keep: set[str] = {name for _, name in dated[:MINIMUM_KEPT]}
    seen_days, seen_weeks, seen_months = set(), set(), set()
    for moment, name in dated:  # do mais novo para o mais antigo
        age = now - moment
        day = moment.date()
        week = moment.isocalendar()[:2]
        month = (moment.year, moment.month)
        if age <= timedelta(days=DAILY_DAYS) and day not in seen_days:
            keep.add(name)
        if age <= timedelta(weeks=WEEKLY_WEEKS) and week not in seen_weeks:
            keep.add(name)
        if age <= timedelta(days=31 * MONTHLY_MONTHS) and month not in seen_months:
            keep.add(name)
        seen_days.add(day)
        seen_weeks.add(week)
        seen_months.add(month)
    return keep


def encrypt_bytes(data: bytes, key: str) -> bytes:
    try:
        return Fernet(key.encode()).encrypt(data)
    except (ValueError, TypeError) as error:
        raise BackupError("BACKUP_ENCRYPTION_KEY inválida. Gere com Fernet.generate_key().") from error


def decrypt_bytes(data: bytes, key: str) -> bytes:
    try:
        return Fernet(key.encode()).decrypt(data)
    except InvalidToken as error:
        raise BackupError("Chave incorreta ou arquivo de backup corrompido.") from error


def _pg_environment(database_url: str) -> tuple[list[str], dict]:
    url = make_url(database_url)
    if not url.drivername.startswith("postgresql"):
        raise BackupError("DATABASE_URL não aponta para PostgreSQL.")
    arguments = [
        "--host", url.host or "localhost",
        "--port", str(url.port or 5432),
        "--username", url.username or "postgres",
        "--dbname", url.database or "postgres",
    ]
    environment = dict(os.environ)
    environment["PGPASSWORD"] = url.password or ""
    environment.setdefault("PGSSLMODE", url.query.get("sslmode", "require"))
    return arguments, environment


def _run(command: list[str], environment: dict) -> None:
    try:
        completed = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=1800)
    except FileNotFoundError as error:
        raise BackupError(f"Ferramenta não encontrada: {command[0]}. Instale o cliente PostgreSQL.") from error
    except subprocess.TimeoutExpired as error:
        raise BackupError("Tempo limite excedido ao executar " + command[0]) from error
    if completed.returncode != 0:
        raise BackupError(f"{command[0]} falhou: {completed.stderr.strip()[:500]}")


def dump_database(database_url: str) -> bytes:
    """Gera um dump pg_dump (formato custom) do schema público e valida sua leitura."""
    arguments, environment = _pg_environment(database_url)
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "dump.custom"
        _run(
            ["pg_dump", *arguments, "--format=custom", "--no-owner", "--no-privileges",
             "--schema=public", "--file", str(target)],
            environment,
        )
        data = target.read_bytes()
        _run(["pg_restore", "--list", str(target)], environment)
    if not data:
        raise BackupError("O dump gerado está vazio.")
    return data


def restore_dump(dump: bytes, target_url: str) -> None:
    arguments, environment = _pg_environment(target_url)
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "dump.custom"
        source.write_bytes(dump)
        _run(
            ["pg_restore", *arguments, "--no-owner", "--no-privileges",
             "--clean", "--if-exists", "--exit-on-error", str(source)],
            environment,
        )


class SupabaseStorage:
    def __init__(self, project_url: str, service_key: str, bucket: str, timeout: int = 120):
        self.base = project_url.rstrip("/") + "/storage/v1"
        self.bucket = bucket
        self.timeout = timeout
        self.headers = {"Authorization": f"Bearer {service_key}", "apikey": service_key}

    def _request(self, method: str, path: str, body: bytes | None = None, content_type: str | None = None):
        headers = dict(self.headers)
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(self.base + path, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:300]
            raise BackupError(f"Storage {method} {path} falhou ({error.code}): {detail}") from error
        except urllib.error.URLError as error:
            raise BackupError(f"Storage indisponível: {error.reason}") from error

    def _object_path(self, name: str) -> str:
        return f"/object/{self.bucket}/{urllib.parse.quote(name)}"

    def upload(self, name: str, data: bytes) -> None:
        self._request("POST", self._object_path(name), data, "application/octet-stream")

    def download(self, name: str) -> bytes:
        return self._request("GET", self._object_path(name))

    def list_names(self) -> list[str]:
        body = json.dumps({"prefix": "", "limit": 1000, "sortBy": {"column": "name", "order": "asc"}})
        response = self._request("POST", f"/object/list/{self.bucket}", body.encode(), "application/json")
        return [item["name"] for item in json.loads(response) if item.get("id")]

    def delete(self, names: list[str]) -> None:
        if names:
            body = json.dumps({"prefixes": names}).encode()
            self._request("DELETE", f"/object/{self.bucket}", body, "application/json")


def run_backup(database_url: str, storage: SupabaseStorage, encryption_key: str, now: datetime) -> dict:
    """Dump → criptografia → upload → conferência do envio → retenção."""
    dump = dump_database(database_url)
    encrypted = encrypt_bytes(dump, encryption_key)
    name = backup_name(now)
    storage.upload(name, encrypted)
    stored = storage.download(name)
    if stored != encrypted:
        raise BackupError("O arquivo gravado no Storage difere do enviado; backup não confiável.")
    names = storage.list_names()
    removable = [item for item in names if parse_backup_name(item) and item not in select_backups_to_keep(names, now)]
    storage.delete(removable)
    return {"name": name, "size_bytes": len(encrypted), "removed": removable}
