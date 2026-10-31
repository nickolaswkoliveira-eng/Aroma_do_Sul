import importlib
import os
import sys
import unittest
from unittest.mock import patch


def _load_config():
    sys.modules.pop("config", None)
    return importlib.import_module("config")


class AuthCookieConfigTests(unittest.TestCase):
    def test_development_defaults_cookie_without_secure_prefix(self):
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "development",
                "DATABASE_URL": "sqlite:///dev.db",
            },
            clear=True,
        ):
            config = _load_config()
        self.assertFalse(config.AUTH_COOKIE_SECURE)
        self.assertEqual(config.AUTH_COOKIE_NAME, "cafe_session")

    def test_production_defaults_secure_cookie_with_host_prefix(self):
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "production",
                "DATABASE_URL": "postgresql://user:pass@localhost:5432/postgres",
            },
            clear=True,
        ):
            config = _load_config()
        self.assertTrue(config.AUTH_COOKIE_SECURE)
        self.assertEqual(config.AUTH_COOKIE_NAME, "__Host-cafe_session")

    def test_secure_prefix_requires_secure_cookie(self):
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "development",
                "DATABASE_URL": "sqlite:///dev.db",
                "AUTH_COOKIE_SECURE": "false",
                "AUTH_COOKIE_NAME": "__Host-manual",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "exigem AUTH_COOKIE_SECURE=true"):
                _load_config()


if __name__ == "__main__":
    unittest.main()
