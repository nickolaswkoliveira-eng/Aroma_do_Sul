from datetime import timedelta

from passlib.hash import pbkdf2_sha256
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.entities import Audit, LoginAudit, Permission, Role, RolePermission, User
from utils.clock import local_now


ROLE_PERMISSIONS = {
    "ADMINISTRADOR": ["*"],
    "GERENTE": ["reports", "finance", "inventory", "intelligence"],
    "CAIXA": ["orders", "cash", "basic_reports"],
    "ATENDENTE": ["orders", "orders:create", "orders:update"],
    "COZINHA": ["kitchen:view", "orders:status"],
}


def seed_access_control(session: Session) -> None:
    for role_name in ROLE_PERMISSIONS:
        role = session.scalar(select(Role).where(Role.name == role_name))
        if role is None:
            role = Role(name=role_name, description=f"Perfil {role_name.lower()}")
            session.add(role)
    session.flush()
    for key in sorted({permission for values in ROLE_PERMISSIONS.values() for permission in values if permission != "*"}):
        if session.scalar(select(Permission).where(Permission.key == key)) is None:
            session.add(Permission(key=key, description=key.replace(":", " ").replace("_", " ").title()))
    session.commit()
    for role_name, keys in ROLE_PERMISSIONS.items():
        if role_name == "ADMINISTRADOR":
            continue
        role = session.scalar(select(Role).where(Role.name == role_name))
        for key in keys:
            permission = session.scalar(select(Permission).where(Permission.key == key))
            assigned = session.scalar(select(RolePermission).where(
                RolePermission.role_id == role.id, RolePermission.permission_id == permission.id))
            if assigned is None:
                session.add(RolePermission(role_id=role.id, permission_id=permission.id))
    session.commit()


def hash_password(password: str) -> str:
    return pbkdf2_sha256.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return pbkdf2_sha256.verify(password, password_hash)
    except (ValueError, TypeError):
        return False


def can_access(session: Session, user: User, permission: str) -> bool:
    role = session.get(Role, user.role_id) if user.role_id else None
    if role is None:
        return False
    if role.name == "ADMINISTRADOR":
        return True
    permission_row = session.scalar(select(Permission).where(Permission.key == permission))
    if permission_row is None:
        return False
    return session.scalar(select(RolePermission.id).where(
        RolePermission.role_id == role.id, RolePermission.permission_id == permission_row.id)) is not None


def authenticate(session: Session, username: str, password: str) -> User | None:
    cutoff = local_now() - timedelta(minutes=15)
    failed_attempts = session.scalar(select(func.count(LoginAudit.id)).where(
        LoginAudit.username == username,
        LoginAudit.success.is_(False),
        LoginAudit.created_at >= cutoff,
    )) or 0
    if failed_attempts >= 5:
        raise ValueError("Muitas tentativas inválidas. Aguarde 15 minutos antes de tentar novamente.")

    user = session.scalar(select(User).where(User.username == username, User.active.is_(True)))
    success = bool(user and verify_password(password, user.password_hash))
    session.add(LoginAudit(username=username, success=success))
    session.add(Audit(responsible=username or "DESCONHECIDO",
                      action="Login realizado" if success else "Tentativa de login inválida"))
    session.commit()
    return user if success else None


def create_user(session: Session, username: str, full_name: str, password: str, role_name: str,
                responsible: str = "SISTEMA_HOMOLOGACAO") -> User:
    if not username.strip() or not full_name.strip() or len(password) < 12:
        raise ValueError("Informe usuário, nome e senha com ao menos 12 caracteres.")
    if session.scalar(select(User.id).where(User.username == username.strip())):
        raise ValueError("Este usuário já está cadastrado.")
    role = session.scalar(select(Role).where(Role.name == role_name))
    if role is None:
        raise ValueError("Perfil não encontrado.")
    user = User(username=username.strip(), full_name=full_name.strip(), password_hash=hash_password(password),
                role_id=role.id, active=True)
    session.add(user)
    session.add(Audit(responsible=responsible, action="Usuário cadastrado", details=f"{username.strip()} · {role_name}"))
    session.commit()
    return user
