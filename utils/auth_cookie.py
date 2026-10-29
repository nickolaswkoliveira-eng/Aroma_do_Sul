from __future__ import annotations

import json
from datetime import timedelta

import streamlit as st
import streamlit.components.v1 as components

from config import AUTH_COOKIE_NAME, AUTH_COOKIE_SAMESITE, AUTH_COOKIE_SECURE, AUTH_SESSION_TTL_DAYS


def read_session_cookie() -> str:
    return (st.context.cookies.get(AUTH_COOKIE_NAME) or "").strip()


def write_session_cookie(token: str) -> None:
    token = token.strip()
    if not token:
        return
    max_age = int(timedelta(days=AUTH_SESSION_TTL_DAYS).total_seconds())
    secure_flag = "; Secure" if AUTH_COOKIE_SECURE else ""
    payload = json.dumps(token)
    same_site = AUTH_COOKIE_SAMESITE
    script = f"""
    <script>
      const token = {payload};
      document.cookie = "{AUTH_COOKIE_NAME}=" + encodeURIComponent(token) +
        "; Path=/; Max-Age={max_age}; SameSite={same_site}{secure_flag}";
    </script>
    """
    components.html(script, height=0, width=0)


def clear_session_cookie() -> None:
    secure_flag = "; Secure" if AUTH_COOKIE_SECURE else ""
    same_site = AUTH_COOKIE_SAMESITE
    script = f"""
    <script>
      document.cookie = "{AUTH_COOKIE_NAME}=; Path=/; Max-Age=0; SameSite={same_site}{secure_flag}";
    </script>
    """
    components.html(script, height=0, width=0)
