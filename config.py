import os
import sys
import warnings
from pathlib import Path

APP_TIMEZONE = os.getenv("APP_TIMEZONE", "America/Sao_Paulo")
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV in {"prod", "production"}

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


def _bool_setting(name: str, default: bool) -> bool:
    value = str(_setting(name, "true" if default else "false")).strip().lower()
    if value not in {"true", "false"}:
        raise ValueError(f"{name} deve ser 'true' ou 'false'.")
    return value == "true"


MODULO_USUARIOS = _bool_setting("MODULO_USUARIOS", True)
MODULO_FINANCEIRO = _bool_setting("MODULO_FINANCEIRO", True)
MODULO_DRE = _bool_setting("MODULO_DRE", True)
MODULO_INTELIGENCIA = _bool_setting("MODULO_INTELIGENCIA", True)
MODULO_NFE = _bool_setting("MODULO_NFE", False)
MODULO_WHATSAPP = _bool_setting("MODULO_WHATSAPP", False)
MODO_HOMOLOGACAO = _bool_setting("MODO_HOMOLOGACAO", _running_tests())
MODO_DEMONSTRACAO = _bool_setting("MODO_DEMONSTRACAO", False)


DEFAULT_DATABASE_URL = f"sqlite:///{(PROJECT_ROOT / 'cafeteria.db').as_posix()}"
DEFAULT_DEMO_DATABASE_URL = f"sqlite:///{(PROJECT_ROOT / 'cafeteria_demo.db').as_posix()}"


def normalize_database_url(url: str) -> str:
    url = url.strip()
    # O driver instalado é o psycopg 3; URLs copiadas do Supabase usam apenas "postgresql://".
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


database_url_raw = _setting("DATABASE_URL")
if IS_PRODUCTION and not database_url_raw:
    raise ValueError(
        "APP_ENV=production exige DATABASE_URL explícita apontando para PostgreSQL/Supabase. "
        "SQLite de fallback está bloqueado em produção."
    )

DATABASE_URL = normalize_database_url(database_url_raw or DEFAULT_DATABASE_URL)
DEMO_DATABASE_URL = os.getenv("DEMO_DATABASE_URL", DEFAULT_DEMO_DATABASE_URL)
AUTH_SESSION_TTL_DAYS = int(os.getenv("AUTH_SESSION_TTL_DAYS", "14"))
if AUTH_SESSION_TTL_DAYS < 1:
    raise ValueError("AUTH_SESSION_TTL_DAYS deve ser maior que zero.")
AUTH_COOKIE_SAMESITE = os.getenv("AUTH_COOKIE_SAMESITE", "Strict")
cookie_secure_raw = os.getenv("AUTH_COOKIE_SECURE")
if cookie_secure_raw is None:
    AUTH_COOKIE_SECURE = IS_PRODUCTION
else:
    cookie_secure_value = cookie_secure_raw.strip().lower()
    if cookie_secure_value not in {"true", "false"}:
        raise ValueError("AUTH_COOKIE_SECURE deve ser 'true' ou 'false'.")
    AUTH_COOKIE_SECURE = cookie_secure_value == "true"
AUTH_COOKIE_NAME = os.getenv("AUTH_COOKIE_NAME", "__Host-cafe_session" if AUTH_COOKIE_SECURE else "cafe_session")
if not AUTH_COOKIE_SECURE and AUTH_COOKIE_NAME.startswith(("__Host-", "__Secure-")):
    raise ValueError(
        "Cookies com prefixo __Host- ou __Secure- exigem AUTH_COOKIE_SECURE=true."
    )
if IS_PRODUCTION and not AUTH_COOKIE_SECURE:
    warnings.warn(
        "APP_ENV=production com AUTH_COOKIE_SECURE=false expõe a sessão em conexões não HTTPS.",
        stacklevel=1,
    )
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
