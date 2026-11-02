import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from database.connection import Base
from models.entities import Role, User
from services.auth import can_access, seed_access_control


class AuthPermissionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        seed_access_control(self.session)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def _user_for_role(self, role_name: str) -> User:
        role = self.session.scalar(select(Role).where(Role.name == role_name))
        user = User(
            username=role_name.lower(),
            full_name=role_name.title(),
            password_hash="x",
            role_id=role.id if role else None,
            active=True,
        )
        self.session.add(user)
        self.session.commit()
        return user

    def test_manager_has_broad_access_except_admin_module(self):
        gerente = self._user_for_role("GERENTE")
        for permission in (
            "orders",
            "orders:create",
            "orders:update",
            "orders:status",
            "kitchen:view",
            "inventory",
            "cash",
            "reports",
            "basic_reports",
            "finance",
            "intelligence",
            "settings",
        ):
            self.assertTrue(can_access(self.session, gerente, permission), permission)
        self.assertFalse(can_access(self.session, gerente, "*"))

    def test_non_management_roles_cannot_access_finance_or_settings(self):
        for role_name in ("CAIXA", "ATENDENTE", "COZINHA"):
            user = self._user_for_role(role_name)
            self.assertFalse(can_access(self.session, user, "finance"), role_name)
            self.assertFalse(can_access(self.session, user, "settings"), role_name)

    def test_cashier_can_open_reports(self):
        caixa = self._user_for_role("CAIXA")
        self.assertTrue(can_access(self.session, caixa, "reports"))


if __name__ == "__main__":
    unittest.main()
