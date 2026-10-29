import os
import sys
from pathlib import Path

APP_TIMEZONE = os.getenv("APP_TIMEZONE", "America/Sao_Paulo")
MODULO_USUARIOS = False
MODULO_FINANCEIRO = True
MODULO_DRE = True
MODULO_INTELIGENCIA = True
MODULO_NFE = False
MODULO_WHATSAPP = False

PROJECT_ROOT = Path(__file__).resolve().parent


def _running_tests() -> bool:
    # Testes nunca devem herdar o banco de produção dos segredos locais.
    return (
        "pytest" in sys.modules
        or "unittest" in Path(sys.argv[0]).as_posix().lower()
    )


def _setting(name: str, default: str | None = None) -> str | None:
    """Lê a configuração do ambiente e, na ausência, dos segredos do Streamlit."""
    value = os.getenv(name)
    if value:
        return value
    if _running_tests():
        return default
    # O Streamlit exporta os segredos para os.environ e sobrescreve variáveis já definidas;
    # o ambiente explícito deve prevalecer, então o estado anterior é restaurado.
    snapshot = dict(os.environ)
    try:
        import streamlit as st

        secret = st.secrets.get(name)
    except Exception:
        return default
    finally:
        for key, original in snapshot.items():
            if os.environ.get(key) != original:
                os.environ[key] = original
    return str(secret) if secret else default


MODO_HOMOLOGACAO = str(_setting("MODO_HOMOLOGACAO", "true")).lower() == "true"
MODO_DEMONSTRACAO = str(_setting("MODO_DEMONSTRACAO", "false")).lower() == "true"


DEFAULT_DATABASE_URL = f"sqlite:///{(PROJECT_ROOT / 'cafeteria.db').as_posix()}"
DEFAULT_DEMO_DATABASE_URL = f"sqlite:///{(PROJECT_ROOT / 'cafeteria_demo.db').as_posix()}"


def normalize_database_url(url: str) -> str:
    url = url.strip()
    # O driver instalado é o psycopg 3; URLs copiadas do Supabase usam apenas "postgresql://".
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


DATABASE_URL = normalize_database_url(_setting("DATABASE_URL", DEFAULT_DATABASE_URL))
DEMO_DATABASE_URL = os.getenv("DEMO_DATABASE_URL", DEFAULT_DEMO_DATABASE_URL)
BACKUP_DIRECTORY = Path(
    os.getenv("BACKUP_DIRECTORY", str(PROJECT_ROOT / "backups"))
).expanduser()
if not BACKUP_DIRECTORY.is_absolute():
    BACKUP_DIRECTORY = PROJECT_ROOT / BACKUP_DIRECTORY
BACKUP_DIRECTORY = BACKUP_DIRECTORY.resolve()
BACKUP_RETENTION_COUNT = int(os.getenv("BACKUP_RETENTION_COUNT", "96"))
if BACKUP_RETENTION_COUNT < 1:
    raise ValueError("BACKUP_RETENTION_COUNT deve ser maior que zero.")
APP_NAME = "Café Aroma do Sul"
