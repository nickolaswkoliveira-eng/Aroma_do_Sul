from datetime import date, datetime


def currency(value: float) -> str:
    formatted = f"R$ {value:,.2f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def date_time(value: datetime | None) -> str:
    return value.strftime("%d/%m/%Y %H:%M") if value else "-"


def time_only(value: datetime | None) -> str:
    return value.strftime("%H:%M") if value else "-"


def date_only(value: date | datetime | None) -> str:
    return value.strftime("%d/%m/%Y") if value else "-"


def quantity(value: float, decimals: int = 3) -> str:
    rendered = f"{float(value):.{decimals}f}".rstrip("0").rstrip(".")
    return rendered or "0"
