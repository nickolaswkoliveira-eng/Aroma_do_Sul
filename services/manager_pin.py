import re
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.entities import AppSetting, Audit
from services.auth import hash_password, verify_password
from utils.clock import local_now

PIN_SETTING_KEY = "manager_pin_hash"
PIN_FAILURE_ACTION = "PIN do gerente inválido"
MAX_PIN_FAILURES = 5
PIN_LOCK_MINUTES = 10


def has_manager_pin(session: Session) -> bool:
    return session.get(AppSetting, PIN_SETTING_KEY) is not None


def set_manager_pin(session: Session, pin: str, responsible: str) -> None:
    if not re.fullmatch(r"\d{4}", pin or ""):
        raise ValueError("O PIN deve ter exatamente 4 dígitos numéricos.")
    setting = session.get(AppSetting, PIN_SETTING_KEY)
    if setting is None:
        session.add(AppSetting(key=PIN_SETTING_KEY, value=hash_password(pin)))
    else:
        setting.value = hash_password(pin)
    session.add(Audit(responsible=responsible, action="PIN do gerente alterado", details=""))
    session.commit()


def verify_manager_pin(session: Session, pin: str, responsible: str) -> None:
    setting = session.get(AppSetting, PIN_SETTING_KEY)
    if setting is None:
        raise ValueError("O gerente ainda não definiu o PIN de desconto (Configurações).")
    since = local_now() - timedelta(minutes=PIN_LOCK_MINUTES)
    failures = session.scalar(
        select(func.count(Audit.id)).where(Audit.action == PIN_FAILURE_ACTION, Audit.created_at >= since)
    ) or 0
    if failures >= MAX_PIN_FAILURES:
        raise ValueError(f"Muitas tentativas com PIN incorreto. Aguarde {PIN_LOCK_MINUTES} minutos.")
    if not verify_password(pin or "", setting.value):
        # Confirma o registro da falha antes de o chamador reverter a transação.
        session.add(Audit(responsible=responsible, action=PIN_FAILURE_ACTION, details=""))
        session.commit()
        raise ValueError("PIN do gerente incorreto.")
