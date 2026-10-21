from datetime import date, datetime
from zoneinfo import ZoneInfo

from config import APP_TIMEZONE


def local_now() -> datetime:
    return datetime.now(ZoneInfo(APP_TIMEZONE)).replace(tzinfo=None)


def local_today() -> date:
    return local_now().date()
